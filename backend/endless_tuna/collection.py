"""Deterministic metadata/PDF adapters. This module never performs model inference."""
import io
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf import PdfReader


class CollectionError(Exception):
    pass


class Person(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    organizations: list[str] = Field(default_factory=list, max_length=30)


class Metadata(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    abstract: str = Field(default='', max_length=100000)
    authors: list[Person] = Field(default_factory=list, max_length=2000)
    pdf_url: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=2000)
    identifiers: dict[str, str] = Field(default_factory=dict)
    detail_pending: bool = False
    version: str = 'proceedings'
    inventory_url: str | None = None
    year: int | None = None
    track: str | None = None
    source_warnings: list[str] = Field(default_factory=list, max_length=100)


def public_url(url):
    from .network import validate_url
    validate_url(url)
    return url


def fetch_bytes(url, limit=None):
    from .network import fetch_bytes as fetch
    return fetch(url, limit)


def parse_metadata(raw, source_url):
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError):
        soup = BeautifulSoup(raw, 'html.parser')
        title = soup.find('meta', attrs={'name': 'citation_title'})
        if not title or not title.get('content'):
            raise CollectionError('No deterministic metadata adapter matched this source. LAS configuration required for AI extraction; stored papers remain accessible.')
        values = lambda name: [m.get('content', '') for m in soup.find_all('meta', attrs={'name': name})]
        doc = {'papers': [{'title': title['content'], 'abstract': next(iter(values('citation_abstract')), ''),
                           'authors': [{'name': name} for name in values('citation_author')],
                           'pdf_url': next(iter(values('citation_pdf_url')), None)}]}
    try:
        if not isinstance(doc, dict) or not isinstance(doc.get('papers'), list) or not doc['papers']:
            raise ValueError
        if len(doc['papers']) > 500:
            raise ValueError
        records = [Metadata.model_validate(item) for item in doc['papers']]
        for record in records:
            record.source_url = urljoin(source_url, record.source_url or source_url)
            if record.pdf_url:
                record.pdf_url = urljoin(source_url, record.pdf_url)
        return records
    except (ValueError, ValidationError):
        raise CollectionError('Source metadata does not match the supported paper schema.') from None


def parse_pdf_pages(raw):
    try:
        if not raw.lstrip().startswith(b'%PDF-'):
            raise ValueError
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted or not reader.pages or len(reader.pages) > 500:
            raise ValueError
        pages = [(page.extract_text() or '') for page in reader.pages]
        if sum(len(text) for text in pages) > 5_000_000:
            raise ValueError
        return pages
    except Exception:
        raise CollectionError('PDF validation/parsing failed: response may be HTML, truncated, encrypted, or unsupported.') from None


def parse_pdf(raw):
    pages = parse_pdf_pages(raw)
    return '\n'.join(pages), len(pages)
