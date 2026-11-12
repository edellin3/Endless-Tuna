"""Official PMLR volumes and RSS 2025 proceedings; deterministic, bounded parsing."""
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .adapters import Inventory
from .collection import CollectionError, Metadata, Person

PMLR_HOST = 'proceedings.mlr.press'
RSS_HOSTS = {'www.roboticsproceedings.org', 'roboticsproceedings.org'}


def pmlr_volume(url):
    u = urlsplit(url)
    return u.hostname == PMLR_HOST and re.fullmatch(r'/v[1-9][0-9]*/?', u.path) is not None and not u.query and not u.fragment


def rss_volume(url):
    u = urlsplit(url)
    return u.hostname in RSS_HOSTS and u.path.rstrip('/') == '/rss21' and not u.query and not u.fragment


def event_year(soup):
    # Event year, not citation_publication_date (CoRL 2024 was published in 2025).
    heading = next((h.get_text(' ', strip=True) for h in soup.select('h1,h2') if re.search(r'Volume \d+:', h.get_text())), '')
    match = re.search(r'\b(19\d{2}|20\d{2})\b', heading)
    return int(match[0]) if match else None


def citation_record(raw, final, record, abstract_selector):
    soup = BeautifulSoup(raw, 'html.parser')
    def values(name):
        return [m.get('content', '').strip() for m in soup.find_all('meta', attrs={'name': name}) if m.get('content', '').strip()]
    titles, names, pdfs = values('citation_title'), values('citation_author'), values('citation_pdf_url')
    if not titles or not names:
        raise CollectionError('Official paper citation metadata is incomplete; inventory membership retained.')
    abstract = soup.select_one(abstract_selector)
    identifiers = dict(record.identifiers)
    if values('citation_doi'): identifiers['doi'] = values('citation_doi')[0]
    pdf = urljoin(final, pdfs[0]) if pdfs else record.pdf_url
    if pdf and urlsplit(pdf).hostname in RSS_HOSTS:
        pdf = 'https://www.roboticsproceedings.org' + urlsplit(pdf).path
    return record.model_copy(update=dict(title=titles[0], authors=[Person(name=n) for n in names],
        abstract=abstract.get_text(' ', strip=True) if abstract else '', pdf_url=pdf,
        identifiers=identifiers, detail_pending=False))


class PMLR:
    name = 'pmlr-volume'

    def inventory(self, url, fetch):
        raw, final = fetch(url, limit=12_000_000)
        if not pmlr_volume(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise CollectionError('PMLR volume redirected away from its official inventory.')
        soup = BeautifulSoup(raw, 'html.parser')
        volume = urlsplit(final).path.strip('/')
        year = event_year(soup)
        found = {}
        for paper in soup.select('.paper'):
            title = paper.select_one('.title')
            link = next((a for a in paper.select('a[href]') if a.get_text(strip=True).lower() == 'abs'), None)
            if title is None or link is None:
                raise CollectionError('PMLR inventory structure changed: a paper has no title or abstract link.')
            href = urljoin(final, link['href'])
            u = urlsplit(href)
            if u.hostname != PMLR_HOST or not re.fullmatch('/'+volume+r'/[A-Za-z0-9_-]+\.html', u.path) or u.query or u.fragment:
                raise CollectionError('PMLR inventory includes an unrecognized official paper link.')
            found[href] = Metadata(title=title.get_text(' ', strip=True), source_url=href,
                identifiers={'pmlr': volume + '/' + u.path.rsplit('/',1)[1][:-5]}, year=year,
                detail_pending=True, inventory_url=final)
        if not found:
            raise CollectionError('PMLR volume contains no recognized paper entries. It may be unpublished or use an unsupported layout.')
        return Inventory(list(found.values()), len(found), final)

    def hydrate(self, record, fetch):
        raw, final = fetch(record.source_url, limit=2_000_000)
        if final != record.source_url:
            raise CollectionError('PMLR paper redirected away from its official inventory record.')
        return citation_record(raw, final, record, '#abstract')


class RSS2025:
    name = 'rss-2025'

    def inventory(self, url, fetch):
        raw, final = fetch(url, limit=5_000_000)
        if not rss_volume(final):
            raise CollectionError('RSS inventory redirected away from the supported RSS 2025 proceedings.')
        soup = BeautifulSoup(raw, 'html.parser')
        found = {}
        for a in soup.select('.content a[href]'):
            u = urlsplit(urljoin(final, a['href']))
            if u.hostname not in RSS_HOSTS or not re.fullmatch(r'/rss21/p\d{3}\.html', u.path) or u.query or u.fragment:
                continue
            href = 'https://www.roboticsproceedings.org' + u.path
            if not a.get_text(strip=True): continue
            found[href] = Metadata(title=a.get_text(' ', strip=True), source_url=href,
                year=2025, detail_pending=True, inventory_url=final,
                identifiers={'rss': 'rss21/'+u.path.rsplit('/',1)[1][:-5]})
        if not found:
            raise CollectionError('RSS 2025 inventory contains no recognized paper links; source structure may have changed.')
        return Inventory(list(found.values()), len(found), final)

    def hydrate(self, record, fetch):
        raw, final = fetch(record.source_url, limit=2_000_000)
        if urlsplit(final).hostname not in RSS_HOSTS or urlsplit(final).path != urlsplit(record.source_url).path:
            raise CollectionError('RSS paper redirected away from its official record.')
        return citation_record(raw, final, record, '.content > p[style]')
