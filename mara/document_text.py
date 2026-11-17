"""Bounded text extraction for verified public issuer documents, not table parsing."""
import json
import re
import subprocess
import sys
import io
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


EXTRACTION_VERSION='mara.document-text/1.3'


class ExtractionError(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code


class FilingText(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    BLOCK={'p','div','tr','h1','h2','h3','br'}
    def __init__(self):super().__init__();self.hidden=0;self.parts=[];self.stack=[];self.skipped=0
    def close_optional(self,tags,boundaries):
        # HTML permits omitted end tags. A hidden prior row/cell must not hide
        # its visible sibling; stop at the containing table/list boundary.
        for tag,_ in reversed(self.stack):
            if tag in tags:self.handle_endtag(tag);return
            if tag in boundaries:return
    def handle_starttag(self,t,a):
        if t=='tr':self.close_optional({'tr'},{'table'})
        if t in {'td','th'}:self.close_optional({'td','th'},{'tr','table'})
        if t in {'thead','tbody','tfoot'}:self.close_optional({'thead','tbody','tfoot'},{'table'})
        if t=='li':self.close_optional({'li'},{'ul','ol'})
        if t in {'dt','dd'}:self.close_optional({'dt','dd'},{'dl'})
        if t=='option':self.close_optional({'option'},{'select','datalist','optgroup'})
        if t in {'p','div','table','ul','ol','dl','section','article','aside','header','footer','h1','h2','h3','h4','h5','h6'}:
            self.close_optional({'p'},{'table','td','th'})
        attrs=dict(a);style=re.sub(r'\s+','',attrs.get('style','') or '').lower()
        display=None;important=False
        for declaration in style.split(';'):
            name,_,value=declaration.partition(':');priority=value.endswith('!important')
            if name=='display' and (priority or not important):display=value.removesuffix('!important');important=priority
        hides=t in ('script','style','ix:header') or 'hidden' in attrs or display=='none'
        if hides:self.skipped+=1
        if t not in self.VOID:self.stack.append((t,hides));self.hidden+=int(hides)
        if not self.hidden and not hides:
            if t in self.BLOCK:self.parts.append('\n')
            if t in ('td','th'):self.parts.append(' | ')
    def handle_endtag(self,t):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==t:
                self.hidden-=sum(int(hides) for _,hides in self.stack[i:]);del self.stack[i:];break
    def handle_data(self,s):
        if not self.hidden:self.parts.append(s)
    def text(self):return re.sub(r'[ \t]+',' ',''.join(self.parts))


def extract(raw):
    if raw.startswith(b'PK'):
        # Read only the text XML of a bounded DOCX; never evaluate macros/links.
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist())>2000:raise ValueError('DOCX entry limit')
                info=archive.getinfo('word/document.xml')
                if info.file_size>16_000_000:raise ValueError('DOCX XML limit')
                xml=archive.read(info)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():raise ValueError('DOCX XML declarations unsupported')
            root=ET.fromstring(xml)
            parts=[' '.join(t.text or '' for t in para.iter() if t.tag.endswith('}t')) for para in root.iter() if para.tag.endswith('}p')]
        except (KeyError,zipfile.BadZipFile,ET.ParseError):raise ValueError('Unsupported DOCX structure') from None
        text='\n'.join(parts)
        if not 100<=len(text)<=3_000_000:raise ValueError('DOCX text limit or empty text')
        return text,{'format':'docx','scope':'Paragraph text only; no rendered page numbers or verified table alignment; external links not fetched'}
    if raw.startswith(b'%PDF-'):
        # The untrusted parser is bounded separately from the long-lived service.
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve())],input=raw,capture_output=True,timeout=30)
            if result.returncode:raise ExtractionError('source_text_extraction_failed')
            value=json.loads(result.stdout)
        except subprocess.TimeoutExpired:raise ExtractionError('source_text_extraction_timeout') from None
        except (OSError,ValueError):raise ExtractionError('source_text_extraction_failed') from None
        return value['text'],{'format':'pdf','pages':value['pages'],'scope':'Text layer with PDF page markers; no OCR or verified table-cell alignment'}
    if b'<html' not in raw[:10000].lower() and b'<!doctype' not in raw[:1000].lower():
        raise ValueError('Unsupported issuer document format')
    p=FilingText();p.feed(raw.decode('utf-8',errors='replace'));text=p.text()
    if len(text.strip())<100:raise ValueError('Issuer document text unavailable')
    return text,{'format':'html','explicit_hidden_elements_skipped':p.skipped,
        'scope':'Static HTML text excluding explicit hidden attributes and inline display:none. External CSS, visibility overrides and JavaScript rendering are not evaluated; excerpts are not whole-document review.'}


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



def excerpt_page(text,query,offset=0,limit=5):
    """Character cursor reaches later notes without mistaking TOC matches for evidence."""
    if type(offset)!=int or not 0<=offset<=len(text):raise ValueError('Invalid document cursor')
    if type(limit)!=int or not 1<=limit<=5:raise ValueError('Invalid excerpt limit')
    if not isinstance(query,str) or not 1<=len(query)<=200:raise ValueError('Invalid document query')
    terms=list(dict.fromkeys(x.strip() for x in query.split('|') if x.strip()))[:6]
    if not terms:raise ValueError('Empty document query')
    def find(terms):
        found=[]
        for term in terms:
            # Search is bounded by document size; only the next page is materialized.
            for n,m in enumerate(re.finditer(re.escape(term),text[offset:],re.I)):
                found.append((m.start()+offset,m.end()+offset,term))
                if n>=limit:break
        return sorted(found)
    matches=find(terms);mode='explicit_terms' if '|' in query else 'exact_phrase'
    if not matches and len(terms)==1:
        terms=list(dict.fromkeys(x for x in re.findall(r'[A-Za-z][A-Za-z-]{3,}',query) if x.lower() not in {'with','from','that','this','into'}))[:6]
        matches=find(terms);mode='individual_words_fallback'
    hits=[]
    for start,end,term in matches[:limit]:
        left=max(0,start-250);right=min(len(text),end+1400)
        hits.append({'query':term,'match_start':start,'start':left,'end':right,'excerpt':text[left:right]})
    return {'hits':hits,'query_terms':terms,'query_mode':mode,'search_offset':offset,
            'next_offset':matches[limit-1][0]+1 if len(matches)>limit else None,
            'status':'matched' if hits else 'no_matches'}


def read_chunk(text,offset=0,limit=10000):
    if type(offset)!=int or not 0<=offset<len(text):raise ValueError('Invalid document cursor')
    if type(limit)!=int or not 500<=limit<=12000:raise ValueError('Document read limit must be 500..12000')
    end=min(len(text),offset+limit)
    return {'start':offset,'end':end,'text':text[offset:end],'next_offset':end if end<len(text) else None,
            'scope':'Extracted text range only; tables require period/unit/header cross-check, no OCR'}

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
