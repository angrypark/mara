"""Bounded text extraction for verified public issuer documents, not table parsing."""
import json
import re
import subprocess
import sys
from html.parser import HTMLParser


class FilingText(HTMLParser):
    def __init__(self):super().__init__();self.hidden=0;self.parts=[]
    def handle_starttag(self,t,a):
        if t in ('script','style','ix:header'):self.hidden+=1
        if t in ('p','div','tr','h1','h2','h3','br'):self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style','ix:header'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,s):
        if not self.hidden:self.parts.append(s)
    def text(self):return re.sub(r'[ \t]+',' ',''.join(self.parts))


def extract(raw):
    if raw.startswith(b'%PDF-'):
        # The untrusted parser is bounded separately from the long-lived service.
        try:
            result=subprocess.run([sys.executable,'-m','mara.document_text'],input=raw,capture_output=True,timeout=30)
            if result.returncode:raise ValueError('PDF extraction unavailable or exceeded document limits')
            value=json.loads(result.stdout)
        except (OSError,subprocess.TimeoutExpired,ValueError):
            raise ValueError('PDF text extraction failed; no HTML fallback for binary PDF') from None
        return value['text'],{'format':'pdf','pages':value['pages'],'scope':'Text layer with PDF page markers; no OCR or verified table-cell alignment'}
    if b'<html' not in raw[:10000].lower() and b'<!doctype' not in raw[:1000].lower():
        raise ValueError('Unsupported issuer document format')
    p=FilingText();p.feed(raw.decode('utf-8',errors='replace'));text=p.text()
    if len(text.strip())<100:raise ValueError('Issuer document text unavailable')
    return text,{'format':'html','scope':'Visible HTML text; keyword excerpts are not whole-document review'}


def excerpts(text,query):
    terms=list(dict.fromkeys(x.strip() for x in query.split('|') if x.strip()))[:6]
    def matches(terms):
        return {term:list(re.finditer(re.escape(term),text,re.I))[:2] for term in terms}
    found=matches(terms);mode='explicit_terms' if '|' in query else 'exact_phrase'
    if not any(found.values()) and len(terms)==1:
        terms=list(dict.fromkeys(x for x in re.findall(r'[A-Za-z][A-Za-z-]{3,}',query) if x.lower() not in {'with','from','that','this','into'}))[:6]
        found=matches(terms);mode='individual_words_fallback'
    hits=[]
    for nth in (0,1):
        for term in terms:
            if len(found[term])<=nth:continue
            match=found[term][nth];start=max(0,match.start()-250);end=min(len(text),match.end()+1400)
            hits.append({'query':term,'start':start,'end':end,'excerpt':text[start:end]})
            if len(hits)==5:return hits,terms,mode
    return hits,terms,mode


if __name__=='__main__':
    import io,resource
    from pypdf import PdfReader
    resource.setrlimit(resource.RLIMIT_CPU,(25,25))
    raw=sys.stdin.buffer.read(8_000_001)
    if len(raw)>8_000_000:raise ValueError('PDF byte limit')
    reader=PdfReader(io.BytesIO(raw))
    if reader.is_encrypted and not reader.decrypt(''):raise ValueError('PDF requires a nonempty password')
    if not 1<=len(reader.pages)<=350:raise ValueError('PDF page limit')
    parts=[];size=0
    for n,page in enumerate(reader.pages,1):
        content=page.get_contents()
        if content and len(content.get_data())>10_000_000:raise ValueError('PDF stream limit')
        text=page.extract_text() or '';size+=len(text)
        if size>3_000_000:raise ValueError('PDF text limit')
        parts.append('[PDF page '+str(n)+']\n'+text)
    if size<100:raise ValueError('PDF text layer unavailable; OCR required')
    print(json.dumps({'text':'\n'.join(parts),'pages':len(reader.pages)}))
