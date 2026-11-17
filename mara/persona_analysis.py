"""Persona-based research jobs; keep actual holdings and current context separate."""
import copy,json,re,threading,uuid
from datetime import datetime,timezone,timedelta
from . import domain as d
from .persona import ensure,snapshot
from .engine import Engine,ContextNeedsInput
from .output_validation import AgentOutputError
from .company_research import CompanyLibrary
from .onboarding import InputError,KST,SOURCE


def market_for_persona(setup,profile,actual,old,progress):
    now=datetime.now(timezone.utc);today=now.astimezone(KST).date().isoformat()
    if old['as_of']==today:
        progress('같은 날의 고정 시장 자료를 사용하고 개인 페르소나를 새로 적용해요.')
        return copy.deepcopy(old)
    symbols=list(dict.fromkeys((profile.get('candidate_screen') or {}).get('symbols') or list(old['assets'])))
    symbols=list(dict.fromkeys(symbols+list(actual['positions'])));symbols=[x for x in symbols if x not in ('USD_CASH','CASH')]
    if not 1<=len(symbols)<=80:raise InputError('시장 자료를 갱신할 후보 범위를 확인해주세요.')
    m=copy.deepcopy(old);m.update(as_of=today,facts=[],prices={},assets={})
    for key in ('return_histories','fx_history','fund_constituents','sector_lookthrough'):m.pop(key,None)
    memberships={}
    with setup.broker() as (b,_):
        sectors=b.sectors()['sectors'];roots=[x for x in sectors if x['depth']==0]
        requested=set(profile.get('criteria',{}).get('preferred_sectors',[])+profile.get('criteria',{}).get('excluded_sectors',[]))
        for row in sectors:
            if row['depth']==0 or row['name'] in requested:memberships[row['name']]=b.sector_stocks(row['sectorId'])
        stocks={x['symbol']:x for x in b.stocks(symbols)};quotes={x['symbol']:x for x in b.prices(symbols)};fx=b.exchange_rate()
    captured=datetime.now(timezone.utc)
    if fx['baseCurrency']!='USD' or fx['quoteCurrency']!='KRW' or not datetime.fromisoformat(fx['validFrom'])<=captured<=datetime.fromisoformat(fx['validUntil']):raise InputError('환율의 통화·유효 시점을 확인하지 못했어요.')
    rate=float(fx['midRate']);d.number(rate,.000001)
    m['prices']['USD_CASH']={'price':rate,'observed_at':today,'known_at':today,'source':SOURCE}
    m['assets']['USD_CASH']={'market':'US','currency':'USD','kind':'cash','asset_class':'cash','stress_loss':.2,'liquid':True,'expense_ratio':0,'eligible':True,'sector_exposures':{},'sector_source':SOURCE,'sector_as_of':today,'sector_valid_until':today,'sector_complete':True}
    valid=(d.day(today)+timedelta(days=7)).isoformat()
    for name in symbols:
        stock,q=stocks[name],quotes[name];stamp=datetime.fromisoformat(q['timestamp'])
        if stamp.tzinfo is None or stamp>captured or q['currency']!='USD' or stock['currency']!='USD':raise InputError('종목 시세의 통화·시점을 확인하지 못했어요.')
        is_stock=stock['securityType'] in {'STOCK','FOREIGN_STOCK','DEPOSITARY_RECEIPT','REIT'}
        tags={key:1. for key,value in memberships.items() if any(x['symbol']==name for x in value['stocks'])} if is_stock else {}
        m['prices'][name]={'price':float(q['lastPrice'])*rate,'observed_at':stamp.astimezone(KST).date().isoformat(),'known_at':today,'source':SOURCE}
        asset={'market':'US','currency':'USD','kind':stock['securityType'],'asset_class':'equity' if is_stock else 'unknown','stress_loss':.5,'liquid':False,'expense_ratio':0 if is_stock else None,'eligible':stock['status']=='ACTIVE' and stock.get('leverageFactor') in (None,'1','1.0',1)}
        if tags:asset.update(sector_exposures=tags,sector_as_of=today,sector_valid_until=valid,sector_source=SOURCE,sector_complete=True)
        m['assets'][name]=asset;m['facts'].append({'id':'toss-'+name,'topic':name,'text':d.dumps({'instrument':stock,'quote':q,'sector_tags':list(tags)}),'source':SOURCE,'published_at':today,'known_at':today,'valid_until':valid,'uncertainty':'기본 상품·시세 자료. 기업 가치·체결 가능성 입증이 아님.'})
    m['facts'].append({'id':'toss-usdkrw','topic':'FX','text':d.dumps(fx),'source':SOURCE,'published_at':today,'known_at':today,'valid_until':today,'uncertainty':'관측 매매기준율. 실제 환전 비용은 별도.'})
    if setup.research_factory:
        with setup.broker() as (b,_):setup.research_factory(setup.directory/'research',now=captured).enrich(m,symbols,b,progress)
    ids={f['id'] for f in m['facts']}
    m['facts'] += [copy.deepcopy(f) for f in old['facts'] if f['id'] not in ids and not f['id'].startswith('toss-') and f['valid_until']>=today and f.get('research_tool')!='company_valuation']
    from .sector_lookthrough import apply
    apply(m,memberships,{'as_of':today,'expected_root_names':[x['name'] for x in roots]});d.market(m)
    return m


def start(setup,body):
    if not isinstance(body,dict) or set(body)!={'request_id','persona_id'} or not isinstance(body['request_id'],str) or not re.fullmatch('[a-f0-9-]{32,36}',body['request_id']):raise InputError('분석 요청을 확인해주세요.')
    with setup.guard,setup.session() as s:
        with s.store.transaction():
            old=next((x for x in s.events('persona_analysis_request') if x['body']['request_id']==body['request_id']),None)
            if old:
                if old['body']['persona_id']!=body['persona_id']:raise InputError('같은 요청 ID의 페르소나가 달라요.')
                return {'job_id':old['body']['job_id'],'duplicate':True}
            if setup.thread and setup.thread.is_alive() or s.store.db.execute('SELECT 1 FROM locks WHERE owner=?',(s.owner,)).fetchone():raise InputError('이미 분석이 진행 중이에요.')
            p=s.latest('profile');h=s.latest('actual')
            if not p:raise InputError('개인 페르소나에 필요한 맥락을 대화로 조금 더 알려주세요.')
            persona=ensure(s,p)
            if persona['id']!=body['persona_id']:raise InputError('페르소나가 바뀌었어요. 최신 버전을 확인해주세요.')
            if not h:raise InputError('현재 보유 기록이 없어요. 상세 설정의 보유 조회에서 계좌와 현금 범위를 먼저 확인해주세요.')
            if not setup.model_state()['configured']:raise InputError('Codex / API 실행 설정을 먼저 확인해주세요.')
            if p['body'].get('contested_fields'):raise InputError('이전에 철회하거나 정정 중인 값이 있어요: '+', '.join(p['body']['contested_fields'])+'. 현재 값을 대화로 정리한 뒤 분석할 수 있어요.')
            d.profile(p['body']);capital=p['body'].get('proposal_capital')
            if capital is None or not 0<capital<=setup.capital_limit():raise InputError('제안할 납입금·운용액을 대화에서 정리해주세요.')
            latest=s.latest('completed');m=s.get(latest['body']['market_id']) if latest else s.latest('market',shared=True)
            if not m:raise InputError('첫 시장 자료가 없어요. 상세 설정의 최초 연결을 완료한 뒤 대화 흐름을 사용할 수 있어요.')
            jid=uuid.uuid4().hex;request=dict(body,job_id=jid,profile_id=p['id'],actual_id=h['id'],market_id=m['id'],persona_hash=snapshot(persona)['hash'])
            s.append('persona_analysis_request',request,datetime.now(timezone.utc).astimezone(KST).date().isoformat())
        setup.job(jid,'running','개인 페르소나를 고정하고 시장 자료를 준비해요.',persona_id=persona['id'])
        setup.thread=threading.Thread(target=work,args=(setup,request),daemon=True);setup.thread.start()
        return {'job_id':jid,'status':'running','persona_id':persona['id']}


def work(setup,request):
    jid=request['job_id'];progress=lambda message:setup.job(jid,'running',message,persona_id=request['persona_id'])
    try:
        with setup.session() as s:
            p=s.get(request['profile_id'])['body'];h=s.get(request['actual_id'])['body'];old=s.get(request['market_id'])['body']
            market=market_for_persona(setup,p,h,old,progress);mid=s.store.publish_market(market);model=setup.analysis_model();original=model.complete
            def complete(role,*args):progress(role+' · 개인 페르소나를 바탕으로 분석 중이에요.');return original(role,*args)
            model.complete=complete
            result=Engine(s,model,CompanyLibrary(setup.directory/'company-research',quote_provider=setup.research_quote)).run(market['as_of'],mid,force=True,
                revision_reason='대화로 정리한 개인 페르소나 적용',profile_id=request['profile_id'],actual_id=request['actual_id'])
            assert result['persona_id']==request['persona_id'] and result['persona_hash']==request['persona_hash']
            s.append('persona_analysis_result',{'request_id':request['request_id'],'completed_id':result['event_id'],'persona_id':result['persona_id']},market['as_of'])
        setup.job(jid,'completed','개인 페르소나를 반영한 분석과 제안을 저장했어요. 실제 보유·주문은 바꾸지 않았어요.',persona_id=request['persona_id'])
    except ContextNeedsInput as exc:setup.job(jid,'needs_input',exc.message,questions=exc.questions,context_output_id=exc.output_id,structured_questions=exc.structured_questions,persona_id=request['persona_id'])
    except AgentOutputError as exc:setup.job(jid,'failed',exc.message,error_type='AgentOutputError',output_validation=exc.details,persona_id=request['persona_id'])
    except Exception as exc:setup.job(jid,'failed',str(exc) if isinstance(exc,InputError) else '페르소나는 보존됐어요. 시장 자료 또는 분석 실행을 완료하지 못했어요.',error_type=type(exc).__name__,persona_id=request['persona_id'])
