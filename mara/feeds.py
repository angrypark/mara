"""Fetch a curator-produced market pack. Provider adapters can emit this same contract."""
import json
import urllib.request
from .domain import market


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Feed redirects are disabled; configure the canonical HTTPS URL')


def fetch_market(url):
    if not url.startswith('https://'): raise ValueError('HTTPS feed URL required')
    request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'Mara/1.0'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000: raise ValueError('Market pack exceeds 2 MB')
    return market(json.loads(raw))
