"""Official policy statements, dated separately from discovery RSS headlines."""
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
from .commentary_sources import Visible
from .research_sources import dated

FED_BASE='https://www.federalreserve.gov'
TITLE='Federal Reserve issues FOMC statement'


class StatementBody(HTMLParser):
    """Select the official article body after its heading, not an English word."""
    def __init__(self):
        super().__init__();self.depth=0;self.target=None;self.done=False;self.heading=False;self.seen_title=False;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('h1','h2','h3'):self.heading=True
        if tag=='div':
            self.depth+=1;classes=set(dict(attrs).get('class','').split())
            if self.seen_title and not self.done and self.target is None and {'col-xs-12','col-sm-8','col-md-8'}<=classes:self.target=self.depth
    def handle_endtag(self,tag):
        if tag in ('h1','h2','h3'):self.heading=False
        if tag=='div':
            if self.depth==self.target:self.target=None;self.done=True
            self.depth=max(0,self.depth-1)
    def handle_data(self,value):
        text=' '.join(value.split())
        if self.heading and text==TITLE:self.seen_title=True
        if self.target is not None and text:self.parts.append(text)


class Links(HTMLParser):
    def __init__(self):super().__init__();self.href=None;self.parts=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.href=dict(attrs).get('href');self.parts=[]
    def handle_data(self,value):
        if self.href:self.parts.append(value)
    def handle_endtag(self,tag):
        if tag=='a' and self.href:self.links.append((self.href,' '.join(self.parts)));self.href=None


def latest_statement(raw,as_of):
    parser=Links();parser.feed(raw);found=[]
    for href,title in parser.links:
        url=urljoin(FED_BASE,href);parts=urlsplit(url)
        match=re.fullmatch(r'/newsevents/pressreleases/monetary(\d{8})a.htm',parts.path)
        if parts.hostname!='www.federalreserve.gov' or parts.scheme!='https' or not match or 'fomc statement' not in title.lower():continue
        stamp=datetime.strptime(match.group(1),'%Y%m%d').date().isoformat()
        if stamp<=as_of:found.append((stamp,url))
    if not found:raise ValueError('No dated FOMC statement in the official list')
    stamp,url=max(found);dated(stamp,as_of,100);return url


def discover_statement(fetch,as_of):
    # A valid but empty current-year list at the year boundary is not a data gap.
    base=FED_BASE+'/newsevents/pressreleases/'
    current=fetch(base+as_of[:4]+'-press-fomc.htm')
    try:return latest_statement(current,as_of)
    except ValueError:
        prior=fetch(base+str(int(as_of[:4])-1)+'-press-fomc.htm')
        return latest_statement(prior,as_of)


def statement(raw,url,as_of):
    match=re.fullmatch(r'https://www.federalreserve.gov/newsevents/pressreleases/monetary(\d{8})a.htm',url)
    if not match:raise ValueError('Unexpected statement identity')
    stamp=datetime.strptime(match.group(1),'%Y%m%d').date();dated(stamp.isoformat(),as_of,100)
    parser=Visible();parser.feed(raw);text='\n'.join(parser.parts)
    title=TITLE
    date_label=stamp.strftime('%B ')+str(stamp.day)+stamp.strftime(', %Y')
    positions=[m.start() for m in re.finditer(re.escape(title),text) if date_label in text[max(0,m.start()-180):m.start()]]
    if len(positions)!=1:raise ValueError('Statement body date disagrees with URL')
    article=StatementBody();article.feed(raw);body='\n'.join(article.parts)
    boundaries=[body.index(marker) for marker in ('For media inquiries','Implementation Note','Last Update:') if marker in body]
    if not article.done or not boundaries:raise ValueError('Statement boundary changed')
    excerpt=body[:min(boundaries)].strip()
    if not 300<len(excerpt)<10000 or 'federal funds rate' not in excerpt:raise ValueError('Incomplete monetary policy statement')
    return {'observed_at':stamp.isoformat(),'publisher':'Federal Reserve','title':title,'source_kind':'official_policy_statement',
        'statement_text':excerpt,'read_scope':'정책 성명 본문. 기자회견/전망표/다른 연설은 포함하지 않음.',
        'limits':'발표된 정책 결정과 위원회의 평가. 미래 금리/수익률 확정 예측이 아님. 최신 성명 여부는 같은 연도 공식 목록에서 검증.'}
