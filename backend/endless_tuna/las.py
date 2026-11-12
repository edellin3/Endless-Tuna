"""The only model gateway client. No provider fallback, redirects, or body logging."""
import json
import math
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from . import config  # noqa: F401 -- load the application's optional .env


class LASError(Exception):
    def __init__(self, code: str, message: str, *, retryable=False, status=None):
        super().__init__(message)
        self.code, self.retryable, self.status = code, retryable, status

    def diagnostic(self):
        return {'ok': False, 'code': self.code, 'message': str(self), 'retryable': self.retryable,
                'upstream_status': self.status}


@dataclass(frozen=True)
class LASConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str = ''
    timeout: float = 90

    @classmethod
    def from_env(cls):
        # An explicitly empty LAS_API_KEY does not inherit an unrelated key.
        key = os.environ.get('LAS_API_KEY', os.environ.get('OPENAI_KEY', '')).strip()
        try:
            timeout = float(os.environ.get('LAS_TIMEOUT_SECONDS', '90'))
            if not math.isfinite(timeout) or not 0 < timeout <= 600:
                raise ValueError
        except ValueError:
            raise LASError('invalid_configuration', 'LAS_TIMEOUT_SECONDS must be between 0 and 600 seconds.') from None
        return cls(os.environ.get('LAS_API_BASE_URL', 'https://llm-west.ncsu-las.net/v1').strip(),
                   key, os.environ.get('LAS_MODEL', '').strip(), timeout)

    def normalized_url(self):
        try:
            parts = urlsplit(self.base_url)
            if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
                    or parts.password or parts.query or parts.fragment or (parts.port is not None and parts.port <= 0)):
                raise ValueError
            # Accept a host root or an already versioned prefix. Never append /v1 twice.
            path = parts.path.rstrip('/')
            if not path.endswith('/v1'):
                path += '/v1'
            return urlunsplit((parts.scheme, parts.netloc, path, '', ''))
        except ValueError:
            raise LASError('invalid_configuration', 'Set a valid LAS_API_BASE_URL without credentials, query, or fragment.') from None

    def require(self, model=False):
        if not self.base_url or not self.api_key:
            raise LASError('missing_configuration', 'LAS configuration required. Set the server endpoint and a server-side API key.')
        if model and not self.model:
            raise LASError('missing_configuration', 'LAS configuration required. Set LAS_MODEL or select a discovered model ID in Settings.')
        secrets = [v for v in (self.api_key, os.getenv('LAS_API_KEY'), os.getenv('OPENAI_KEY')) if v]
        if any(secret in self.base_url or secret in self.model for secret in secrets):
            raise LASError('invalid_configuration', 'Keep LAS credentials separate from endpoint and model configuration.')
        if len(self.model) > 512 or any(ord(c) < 32 for c in self.model):
            raise LASError('invalid_configuration', 'LAS model configuration is invalid.')
        self.normalized_url()
        if any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise LASError('invalid_configuration', 'LAS credential configuration is invalid.')


Schema = TypeVar('Schema', bound=BaseModel)


class LASClient:
    def __init__(self, config=None, *, transport=None, sleep=time.sleep):
        self.config = config or LASConfig.from_env()
        self.transport, self.sleep = transport, sleep

    def _request(self, method, endpoint, payload=None):
        self.config.require(model=method == 'POST')
        attempts = 3 if method == 'GET' else 1
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=self.config.timeout, transport=self.transport,
                                  follow_redirects=False, trust_env=False) as client:
                    response = client.request(method, self.config.normalized_url() + endpoint,
                                              headers={'Authorization': 'Bearer ' + self.config.api_key,
                                                       'Accept': 'application/json'}, json=payload)
            except httpx.TimeoutException:
                error = LASError('timeout', 'LAS request timed out. Check network access or retry.', retryable=True)
            except httpx.RequestError:
                error = LASError('network_failure', 'LAS could not be reached. Check network access and the configured endpoint.', retryable=True)
            except (ValueError, httpx.InvalidURL):
                error = LASError('invalid_configuration', 'LAS connection configuration is invalid.')
            else:
                if response.is_success:
                    try:
                        result = response.json()
                        if not isinstance(result, dict):
                            raise ValueError
                        return result
                    except (ValueError, UnicodeError):
                        raise LASError('malformed_response', 'LAS returned a malformed JSON response.') from None
                status = response.status_code
                # Never expose HTML, JSON error messages, request objects, or credentials.
                code, message, retryable = {
                    401: ('authentication_failure', 'LAS authentication failed. Check the server credential configuration.', False),
                    403: ('access_denied', 'LAS denied access (403). Check model/service permissions and network access; this does not establish that the key is wrong.', False),
                    400: ('invalid_request', 'LAS rejected this chat request. Check model compatibility and configuration.', False),
                    404: ('invalid_model' if method == 'POST' else 'endpoint_not_found', 'LAS model or endpoint was not found. Discover models and check the selected ID and endpoint.', False),
                    429: ('rate_limited', 'LAS rate limit reached. Retry later.', True),
                }.get(status, ('service_unavailable', 'LAS is temporarily unavailable. Retry later.', True)
                      if status in (500, 502, 503, 504) else ('request_failed', 'LAS rejected the request. Check the endpoint and service configuration.', False))
                if status in (400, 422):
                    # Inspect only the machine code to distinguish invalid model errors.
                    try:
                        upstream = response.json().get('error', {})
                        if isinstance(upstream, dict) and upstream.get('code') in ('model_not_found', 'invalid_model', 'unknown_model'):
                            code, message = 'invalid_model', 'LAS rejected the selected model ID. Check connection and choose a discovered model.'
                    except (ValueError, AttributeError):
                        pass
                error = LASError(code, message, retryable=retryable, status=status)
            if not error.retryable or attempt + 1 == attempts:
                raise error from None
            # Bounded GET retries only. Never replay an ambiguously completed inference.
            self.sleep(0.25 * (2 ** attempt))
        raise AssertionError('unreachable')

    def discover_models(self):
        result = self._request('GET', '/models')
        rows = result.get('data')
        if not isinstance(rows, list):
            raise LASError('malformed_response', 'LAS model discovery returned an invalid model list.')
        ids = []
        for row in rows:
            model = row.get('id') if isinstance(row, dict) else None
            if (not isinstance(model, str) or not model.strip() or len(model) > 512
                    or any(ord(c) < 32 for c in model) or self.config.api_key in model):
                raise LASError('malformed_response', 'LAS model discovery returned an invalid model ID.')
            if model not in ids:
                ids.append(model)
        return ids

    def complete(self, messages, *, max_tokens=128):
        result = self._request('POST', '/chat/completions', {
            'model': self.config.model, 'messages': messages, 'max_tokens': max_tokens, 'stream': False,
        })
        try:
            choice = result['choices'][0]
            text = choice['message']['content']
            if not isinstance(text, str) or not text.strip() or choice.get('finish_reason') == 'length':
                raise ValueError
            return text.strip()
        except (KeyError, IndexError, TypeError, ValueError):
            raise LASError('malformed_response', 'LAS returned no complete, usable text response.') from None

    def extract_json(self, messages, schema: type[Schema]) -> Schema:
        text = self.complete(messages, max_tokens=2048)
        try:
            # Ordinary chat only: the application owns JSON/schema validation.
            return schema.model_validate(json.loads(text))
        except (ValueError, ValidationError):
            raise LASError('malformed_response', 'LAS extraction did not match the required JSON schema. Review the source or retry.', retryable=True) from None
