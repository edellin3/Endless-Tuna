"""Official 2026 virtual-program inventory; no browser execution or model calls."""
import json
import re
from urllib.parse import urlsplit, urljoin, parse_qs, urlencode
from bs4 import BeautifulSoup
from .adapters import Inventory
from .collection import Metadata, Person, CollectionError
from .network import validate_url

LISTING = 'https://neurips.cc/virtual/2026/papers.html'
HOSTS = {'neurips.cc', 'www.neurips.cc'}
TRACKS = {
    'https://openreview.net/group?id=NeurIPS.cc/2026/Conference': 'Main Conference',
    'https://openreview.net/group?id=NeurIPS.cc/2026/Evaluations_and_Datasets_Track': 'Evaluations and Datasets',
    'https://openreview.net/group?id=NeurIPS.cc/2026/Position_Paper_Track': 'Position Papers',
    'journal-track/NeurIPS_2026-Posters_TMLR.xlsx': 'Journal to Conference: TMLR',
    'journal-track/NeurIPS_2026-Posters_JMLR.xlsx': 'Journal to Conference: JMLR',
    'journal-track/NeurIPS_2026-Posters_AoS.xlsx': 'Journal to Conference: Annals of Statistics',
    'neurips2026-bridging-the-future': 'Bridging the Future',
}


def supports(url):
    u = urlsplit(url)
    return u.hostname in HOSTS and re.fullmatch(r'/virtual/2026/(?:loc/[a-z]+/)?papers\.html', u.path) is not None


def openreview_id(url):
    u = urlsplit(url or '')
    values = parse_qs(u.query).get('id', [])
    if u.scheme in ('http', 'https') and u.hostname == 'openreview.net' and u.path == '/forum' and len(values) == 1 and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', values[0]):
        return values[0]
    return None


def track_name(source):
    if source in TRACKS: return TRACKS[source]
    return ('Other published track: ' + source[:120]) if source else 'Unspecified published track (needs review)'


def parse_program(raw, abstracts, inventory_url):
    try:
        data = json.loads(raw)
        rows = data['results']
        if not isinstance(rows, list) or not rows or len(rows) > 30000 or data.get('next') or data.get('count') != len(rows):
            raise ValueError('Incomplete or paginated official program; refusing a completeness claim.')
        if not isinstance(abstracts, dict): raise ValueError('Invalid abstracts map.')
        found = {}
        for row in rows:
            if row.get('eventtype') != 'Poster' or row.get('visible') is False: continue
            if row.get('decision') and not row['decision'].casefold().startswith('accept'): continue
            event = row['id']
            if not isinstance(event, int) or isinstance(event, bool) or event < 1: raise ValueError('Invalid event ID.')
            poster = f'https://neurips.cc/virtual/2026/poster/{event}'
            forum = next((openreview_id(value) for value in [row.get('paper_url'), row.get('url'), *[m.get('uri') for m in row.get('eventmedia', []) if m.get('visible') is not False]] if openreview_id(value)), None)
            source = 'https://openreview.net/forum?' + urlencode({'id': forum}) if forum else poster
            track = track_name(row.get('sourceurl'))
            warnings = []
            authors = []
            for position, author in enumerate(row['authors'], 1):
                name = (author.get('fullname') or '').strip()
                if not name:
                    warnings.append(f'Official event {event} has no author name at position {position}. The missing-name label is not a verified person name.')
                    name = '[Name missing in official source]'
                authors.append(Person(name=name))
            if not authors: raise ValueError('Missing ordered author list.')
            # Profile "institution" is not evidence of a paper-time affiliation.
            identifiers = {'neurips-program-event': str(event), 'neurips-poster': poster}
            if forum: identifiers['openreview'] = forum
            pdf = row.get('paper_pdf_url')
            if pdf:
                pdf = urljoin(LISTING, pdf)
                validate_url(pdf, resolve=False)
            elif forum:
                # Documented public OpenReview PDF endpoint, anchored to the exact official note ID.
                pdf = 'https://openreview.net/pdf?' + urlencode({'id': forum})
            if not row.get('sourceurl'):warnings.append('Official program does not identify the track; track membership needs review.')
            record = Metadata(title=row['name'], authors=authors, abstract=abstracts.get(str(event)) or row.get('abstract') or '',
                              source_url=source, pdf_url=pdf, inventory_url=inventory_url, identifiers=identifiers,
                              version='openreview:' + forum if forum else 'official-program', year=2026, track=track, source_warnings=warnings)
            key = (source, track)
            if key in found:
                previous = found[key]
                if previous.title != record.title or [a.name for a in previous.authors] != [a.name for a in record.authors]:
                    raise ValueError('Conflicting presentations for the same official paper identity.')
                continue
            found[key] = record
        if not found: raise ValueError('No published paper posters were found.')
        records = sorted(found.values(), key=lambda r: (r.title.casefold(), r.source_url, r.track))
        return Inventory(records, len({r.source_url for r in records}), inventory_url)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise CollectionError('Official NeurIPS 2026 program could not be validated (' + type(error).__name__ + '). No complete inventory was recorded.') from None


class NeurIPS2026:
    name = 'neurips-2026-program'
    multi_track = True
    stop_on_repeated_pdf_denial = True

    def inventory(self, url, fetch):
        raw, final = fetch(url, limit=3_000_000)
        if not supports(final): raise CollectionError('NeurIPS 2026 paper listing redirected away from its supported official page.')
        soup = BeautifulSoup(raw, 'html.parser')
        scripts = '\n'.join(s.get_text() for s in soup.find_all('script') if not s.get('src'))
        files = re.findall(r'''["'](/static/virtual/data/neurips-2026-(?:orals-posters|abstracts)\.json)["']''', scripts)
        inventory_path = next((p for p in files if p.endswith('-orals-posters.json')), None)
        abstracts_path = next((p for p in files if p.endswith('-abstracts.json')), None)
        if not inventory_path or not abstracts_path:
            raise CollectionError('Official 2026 page no longer references the recognized inventory and abstracts feeds.')
        inventory_url = urljoin(final, inventory_path)
        inventory, resolved = fetch(inventory_url, limit=50_000_000)
        if resolved != inventory_url: raise CollectionError('Official inventory redirected; review the adapter before proceeding.')
        abstracts_url = urljoin(final, abstracts_path)
        abstracts, resolved = fetch(abstracts_url, limit=30_000_000)
        if resolved != abstracts_url: raise CollectionError('Official abstracts redirected; review the adapter before proceeding.')
        try: abstracts = json.loads(abstracts)
        except (ValueError, UnicodeError): raise CollectionError('Official abstracts feed is malformed JSON.') from None
        return parse_program(inventory, abstracts, inventory_url)

    def hydrate(self, record, fetch):
        return record  # Inventory already includes ordered authors and the separate abstract map.
