"""Public collection traffic only. LAS has its own independent client/transport."""
import ipaddress
import math
import os
import socket
import threading
import time
from urllib.parse import urljoin, urlsplit, parse_qsl
import httpx
from .collection import CollectionError


def number(name, default, low, high):
    try:
        value = float(os.getenv(name, str(default)))
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError
        return value
    except ValueError:
        raise CollectionError(f'{name} must be between {low} and {high}.') from None


def validate_url(url, resolve=True):
    try:
        u = urlsplit(url)
        if (u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password
                or u.fragment or u.port not in (None, 80, 443) or any(ord(c) < 33 for c in url)):
            raise ValueError
        if u.hostname.lower().rstrip('.') in ('localhost', 'localhost.localdomain') or u.hostname.lower().endswith(('.localhost', '.local')):
            raise ValueError
        # Query strings are needed by documented APIs. Credential-bearing URLs are rejected.
        if any(any(secret in key.lower() for secret in ('key', 'token', 'secret', 'password', 'signature', 'credential')) for key, _ in parse_qsl(u.query)):
            raise ValueError
        try:
            literal = ipaddress.ip_address(u.hostname)
        except ValueError:
            literal = None
        if literal and not literal.is_global:
            raise ValueError
        addresses = []
        if resolve:
            addresses = list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme=='https' else 80), type=socket.SOCK_STREAM)))
            if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
                raise ValueError
        return u, addresses
    except (ValueError, OSError):
        raise CollectionError('Outbound URL rejected or DNS unavailable: use public HTTP(S), without credentials or private/local/link-local destinations.') from None


class PublicTransport(httpx.BaseTransport):
    """Pin a validated public IP, retaining the original HTTP Host and TLS SNI."""
    def __init__(self):
        self.inner = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        u, addresses = validate_url(str(request.url))
        extensions = dict(request.extensions, sni_hostname=u.hostname)
        pinned = httpx.Request(request.method, request.url.copy_with(host=addresses[0]),
                               headers={**dict(request.headers), 'host': u.netloc},
                               content=request.content, extensions=extensions)
        return self.inner.handle_request(pinned)

    def close(self):
        self.inner.close()


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.next = {}

    def wait(self, host):
        interval = 3.1 if host == 'export.arxiv.org' else number('TUNA_REQUEST_INTERVAL_SECONDS', .4, .05, 60)
        if host in ('openreview.net','api2.openreview.net'):interval=max(1.0,interval)
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next.get(host, now))
            self.next[host] = slot + interval
        time.sleep(max(0, slot-now))


limiter = RateLimiter()


def fetch_bytes(url, limit=None, *, transport=None, sleep=time.sleep):
    limit = limit or int(number('TUNA_MAX_PDF_MB', 30, 1, 200) * 1_000_000)
    timeout = number('TUNA_DOWNLOAD_TIMEOUT_SECONDS', 30, 1, 90)
    for attempt in range(3):
        current = url
        try:
            with httpx.Client(timeout=timeout, transport=transport or PublicTransport(), follow_redirects=False, trust_env=False) as client:
                for redirect in range(5):
                    u, _ = validate_url(current)
                    limiter.wait(u.hostname)
                    with client.stream('GET', current, headers={'User-Agent': 'endless-tuna/0.3 (local academic research collector)', 'Accept-Encoding': 'identity'}) as response:
                        if response.status_code in (429, 500, 502, 503, 504):
                            if attempt == 2:
                                raise CollectionError(f'Source HTTP {response.status_code} after 3 attempts.')
                            retry = response.headers.get('retry-after', '1')
                            try: retry = float(retry)
                            except ValueError: retry = 1
                            if retry > 10:
                                raise CollectionError(f'Source HTTP {response.status_code}; requested retry delay exceeds this attempt budget. Retry later.')
                            sleep(max(.25, retry))
                            break
                        if response.is_redirect:
                            if not response.headers.get('location'):
                                raise CollectionError('Source redirect has no destination.')
                            current = urljoin(current, response.headers['location'])
                            validate_url(current)
                            continue
                        if not response.is_success:
                            raise CollectionError(f'Source returned HTTP {response.status_code}. Check source access or retry.')
                        data = bytearray()
                        for chunk in response.iter_bytes():
                            data.extend(chunk)
                            if len(data) > limit:
                                raise CollectionError('Source exceeds configured file-size limit.')
                        return bytes(data), current
                else:
                    raise CollectionError('Source exceeded 5 redirects.')
        except httpx.RequestError:
            if attempt == 2:
                raise CollectionError('Source network failure or timeout after 3 attempts.') from None
            sleep(.5 * (attempt+1))
    raise CollectionError('Source retries exhausted.')
