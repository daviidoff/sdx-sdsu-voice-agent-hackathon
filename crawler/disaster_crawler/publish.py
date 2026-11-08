"""Publish a complete report through the backend's durable import API."""
import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from .tls import tls_context


def publish_report(report, base_url):
    parts = urlsplit(base_url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Publish URL must be an HTTP(S) backend URL without credentials')
    request = Request(base_url.rstrip('/') + '/api/discovery/import',
                      data=json.dumps(report, ensure_ascii=False, allow_nan=False).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=30, context=tls_context()) as response:
        return json.load(response)
