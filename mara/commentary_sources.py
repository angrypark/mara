"""Dated publisher commentary and headline discovery, separate from official facts."""
import re
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from .research_sources import dated

REPORTS={
 'blackrock':{'publisher':'BlackRock Investment Institute','url':'https://www.blackrock.com/corporate/insights/blackrock-investment-institute/global-weekly-commentary'},
 'schwab':{'publisher':'Charles Schwab','url':'https://www.schwab.com/learn/story/weekly-traders-outlook'},
}
NEWS='https://www.cnbc.com/id/100003114/device/rss/rss.html'


class Visible(HTMLParser):
    def __init__(self):super().__init__();self.hidden=0;self.parts=[];self.heading=False;self.headings=[];self.stack=[];self.article_parts=[];self.article_headings=[]
    def handle_starttag(self,t,a):
        attrs=dict(a)
        scope=('article-banner-content' in attrs.get('class','').split() or attrs.get('data-component')=='storyheader-panel')
        if t not in ('meta','link','img','input','br','hr','source','wbr'):self.stack.append((t,scope))
        if t in ('script','style','nav','footer','header'):self.hidden+=1
        if t=='h1' and not self.hidden:self.heading=True
    def handle_endtag(self,t):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==t:self.stack=self.stack[:i];break
        if t in ('script','style','nav','footer','header') and self.hidden:self.hidden-=1
        if t=='h1':self.heading=False
    def handle_data(self,data):
        if self.hidden:return
        text=' '.join(data.split())
        if text:self.parts.append(text)
        if self.heading and text:self.headings.append(text)
        if text and any(scope for _,scope in self.stack):
            self.article_parts.append(text)
            if self.heading:self.article_headings.append(text)


def report(raw,provider,as_of):
    config=REPORTS[provider];p=Visible();p.feed(raw);text='\n'.join(p.parts)
    # Only the publisher's article-header component binds a date to this title.
    # Calendars, navigation, related articles and script metadata are not dates
    # of this article. Changed/ambiguous publisher markup fails closed.
    dates=re.findall(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.? \d{1,2}, \d{4}\b','\n'.join(p.article_parts))
    if len(set(dates))!=1:raise ValueError('Article publication date unavailable or ambiguous')
    observed=None
    for candidate in dates:
        for fmt in ('%B %d, %Y','%b %d, %Y'):
            try:observed=datetime.strptime(candidate.replace('.',''),fmt).date().isoformat();break
            except ValueError:pass
        if observed:break
    if observed is None or not p.article_headings:raise ValueError('Article date or headline unavailable')
    dated(observed,as_of,21)
    if provider=='blackrock':
        # Weekly titles and prose change; the transcript marker is stable.
        begin=text.find('Title slide:')
        if begin<0:begin=text.find('Market take')
    else:begin=text.find('The Week That Was')
    if begin<0:raise ValueError('Article body unavailable')
    body=text[begin:]
    if len(body)<500:raise ValueError('Article body unavailable')
    # Read the full response locally; model receives a short attributed extract,
    # the article scope and its frozen raw reference. No paywall circumvention.
    sentences=re.split(r'(?<=[.!?])\s+',body)
    chosen=[];words=0
    for sentence in sentences:
        count=len(sentence.split())
        if words+count>150:break
        if len(sentence)>45:chosen.append(sentence);words+=count
    if not chosen:raise ValueError('No bounded article excerpt')
    return {'publisher':config['publisher'],'title':' '.join(p.article_headings),
        'observed_at':observed,'source_kind':'institutional_opinion','read_scope':'원문 HTML 수집, 도입부 일부 발췌만 분석 입력에 포함',
        'attributed_excerpt':'\n'.join(chosen),'excerpt_words':words,
        'limits':'기관의 견해·전망이며 확인된 미래 사실이 아니에요. 전체 보고서의 모든 주장/표를 검토한 것이 아니며 단기 전술 전망을 장기 적립 지시로 옮기지 않아요.'}


def news(raw,as_of,collected_at):
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():raise ValueError('Unsafe XML')
    root=ET.fromstring(raw);items=[];seen=set();now=datetime.fromisoformat(collected_at)
    for row in root.findall('./channel/item'):
        title=row.findtext('title');url=row.findtext('link');date=row.findtext('pubDate')
        if not title or not url or not date:continue
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname!='www.cnbc.com' or u.username or u.password:continue
        stamp=parsedate_to_datetime(date)
        if stamp.tzinfo is None or stamp>now:continue
        observed=stamp.astimezone(timezone.utc).date().isoformat()
        try:dated(observed,as_of,7)
        except ValueError:continue
        if url in seen:continue
        seen.add(url)
        # Headlines only: the bounded feed is discovery, not article-body review.
        items.append({'title':title,'url':url,'published_at':stamp.isoformat(),'scope':'headline_only'})
        if len(items)>=8:break
    if not items:raise ValueError('No current headlines')
    return {'publisher':'CNBC','observed_at':max(x['published_at'][:10] for x in items),
        'source_kind':'news_headlines','items':items,
        'limits':'공식 RSS 제목만 수집했어요. 기사 본문·사건 원전·인과관계는 검토하지 않았고, 산업/종목 전수 조사가 아니에요. 주장 확인에는 해당 원문이 필요해요.'}
