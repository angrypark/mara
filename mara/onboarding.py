"""Private HTML onboarding and read-only proposal jobs. No trading dependencies."""
import copy
import fcntl
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from . import domain as d
from .agents import HTTPModel,validate_output
from .codex_model import CodexModel,CodexError,status as codex_status
from .connection import identity,save_private
from .engine import Engine,ContextNeedsInput,ContextRepeatError
from .output_validation import AgentOutputError, failed_job_diagnostic
from .clarifications import answers,save_answers,notes_history,questions
from .store import Store
from .reporting import present
from .toss import TossClient,secret_config

KST=ZoneInfo('Asia/Seoul')
SOURCE='https://openapi.tossinvest.com/openapi-docs/latest/openapi.json'
FIELDS={'goal','horizon_months','total_assets','monthly_income','monthly_expenses','cash_need','cash_need_date',
    'max_loss_fraction','max_position_fraction','contribution_amount','contribution_every_days','rebalance_every_days',
    'constraints','capital_amount','capital_mode','cash_krw','cash_usd','last_rebalanced','rationale','symbols',
    'risk_level','preferred_sectors','excluded_sectors','max_sector_fraction','max_equity_fraction',
    'min_cash_fraction','max_foreign_fraction','snapshot_id','confirmed','revision_reason','context_notes'}


class InputError(ValueError): pass


def numeric(value,label,maximum=None,integer=False):
    try:
        if isinstance(value,bool) or value is None or value=='': raise ValueError()
        result=float(value)
        d.number(result,0,maximum)
        if integer:
            if not result.is_integer() or result<1: raise ValueError()
            result=int(result)
        return result
    except (TypeError,ValueError): raise InputError(label+' 값을 확인해주세요.') from None


def clean_draft(value):
    if not isinstance(value,dict) or set(value)-FIELDS or len(d.dumps(value))>24000:
        raise InputError('입력 형식이나 길이를 확인해주세요.')
    for key,v in value.items():
        if key in ('preferred_sectors','excluded_sectors'):
            if not isinstance(v,list) or len(v)>60 or any(not isinstance(x,str) or len(x)>100 for x in v):
                raise InputError('섹터 선택을 확인해주세요.')
        elif not isinstance(v,(str,int,float,bool,type(None))) or isinstance(v,str) and len(v)>4000:
            raise InputError('입력 길이를 확인해주세요.')
    return copy.deepcopy(value)


def inputs(value,snapshot,cap,now):
    v=clean_draft(value)
    if v.get('confirmed') is not True or v.get('snapshot_id')!=snapshot['id']:
        raise InputError('토스 보유 내역을 불러온 뒤 확인란을 선택해주세요.')
    age=(now-datetime.fromisoformat(snapshot['body']['captured_at'])).total_seconds()
    if not 0<=age<86400: raise InputError('보유 조회가 하루 이상 지났어요. 다시 불러와주세요.')
    for key,label in [('goal','투자 목표'),('rationale','현재 보유 이유')]:
        if not isinstance(v.get(key),str) or not v[key].strip(): raise InputError(label+'를 입력해주세요. 모르면 미확인으로 적어주세요.')
    if v.get('capital_mode') not in ('total','additional'): raise InputError('운용액이 기존 보유 포함 총액인지 추가 투자금인지 선택해주세요.')
    p={key:numeric(v.get(key),key) for key in ['total_assets','monthly_income','monthly_expenses','cash_need','contribution_amount']}
    p.update({key:numeric(v.get(key),key,integer=True) for key in ['horizon_months','contribution_every_days','rebalance_every_days']})
    p.update({key:numeric(v.get(key),key,1) for key in ['max_loss_fraction','max_position_fraction']})
    p.update(base_currency='KRW',markets=['US'],goal=v['goal'].strip(),cash_need_date=v.get('cash_need_date'),
             constraints=[x.strip() for x in v.get('constraints','').splitlines() if x.strip()])
    notes=v.get('context_notes','')
    if not isinstance(notes,str):raise InputError('추가 설명은 글로 입력해주세요.')
    p.update(asset_scope='financial_assets',context_notes=notes.strip())
    p['criteria']={key:v.get(key) for key in ['risk_level','preferred_sectors','excluded_sectors']}
    p['criteria'].update({key:numeric(v.get(key),key,1) for key in ['max_sector_fraction','max_equity_fraction','min_cash_fraction','max_foreign_fraction']})
    try:
        d.profile(p); d.day(v['last_rebalanced'])
        if v['last_rebalanced']>now.astimezone(KST).date().isoformat(): raise ValueError()
        if p['cash_need'] and p['cash_need_date']<now.astimezone(KST).date().isoformat(): raise ValueError()
    except (ValueError,TypeError,KeyError): raise InputError('투자 기간·날짜·위험 선호·섹터 선택을 확인해주세요.') from None
    allowed={s['name'] for s in snapshot['body']['sectors']}
    if not set(p['criteria']['preferred_sectors']+p['criteria']['excluded_sectors'])<=allowed:
        raise InputError('최신 섹터 목록에서 다시 선택해주세요.')
    cash={currency:numeric(v.get(key),key) for currency,key in [('KRW','cash_krw'),('USD','cash_usd')]}
    amount=numeric(v.get('capital_amount'),'운용액',cap)
    if v['capital_mode']=='total' and amount<=0: raise InputError('운용 총액은 0보다 커야 해요.')
    symbols=sorted(set(x.upper() for x in re.split(r'[\s,]+',v.get('symbols','').strip()) if x))
    if len(symbols)>30 or any(not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',s) for s in symbols):
        raise InputError('검토할 미국 주식·ETF 티커를 최대 30개 입력해주세요.')
    if not isinstance(v.get('revision_reason',''),str): raise InputError('변경 이유를 확인해주세요.')
    return p,cash,amount,symbols


class PortfolioSetup:
    def __init__(self,directory,client_factory=TossClient,model_factory=None):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.directory/'portfolio.sqlite3'; self.broker_dir=self.directory.parent/'toss'
        self.model_path=self.directory.parent/'model.json'
        self.client_factory=client_factory; self.model_factory=model_factory
        self.guard=threading.RLock(); self.thread=None
        config=self.directory/'portfolio-session.json'
        with self.session() as s:
            if not config.exists(): save_private(config,{'token':s.store.create_user('local-portfolio')})
        self.token=json.loads(config.read_text())['token']
        with self.session() as s: pass

    @contextmanager
    def session(self):
        db=Store(self.path)
        try: yield db.session(self.token) if hasattr(self,'token') else type('Database',(),{'store':db})()
        finally: db.close()

    @contextmanager
    def broker(self):
        self.broker_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(str(self.broker_dir/'operator.lock'),os.O_WRONLY|os.O_CREAT,0o600)
        with os.fdopen(fd,'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            config=secret_config(self.broker_dir/'credentials.json')
            yield self.client_factory(config,self.broker_dir/'access-token.json'),config

    def capital_limit(self):
        try: value=json.loads((self.broker_dir/'policy.json').read_text())['max_capital_krw']
        except (OSError,KeyError,ValueError): return 30000000
        return numeric(value,'총 운용 한도')

    def model_state(self):
        if self.model_factory: return {'configured':True,'model':'injected-test-provider'}
        if self.model_path.exists():
            try:
                c=json.loads(self.model_path.read_text())
                if c.get('provider')=='codex':
                    info=codex_status()
                    return {'provider':'codex','configured':info['installed'] and info['compatible'] and info['authenticated'],
                            'model':c.get('model') or '', 'codex':info}
                return {'provider':'openai','configured':bool(c.get('api_key') and c.get('model')),'model':c.get('model')}
            except (OSError,ValueError): pass
        return {'provider':'openai','configured':bool(os.environ.get('MARA_API_KEY') and os.environ.get('MARA_MODEL')),'model':os.environ.get('MARA_MODEL')}

    def analysis_model(self):
        if self.model_factory:return self.model_factory()
        config=json.loads(self.model_path.read_text()) if self.model_path.exists() else None
        if config and config.get('provider')=='codex':return CodexModel(config.get('model',''))
        return HTTPModel(config)

    def save_model(self,value):
        if not isinstance(value,dict) or set(value)-{'provider','model','api_key'}: raise InputError('모델 설정을 확인해주세요.')
        provider=value.get('provider','openai')
        if provider not in {'openai','codex'}:raise InputError('분석 실행 방식을 선택해주세요.')
        model=value.get('model',''); key=value.get('api_key','')
        if not isinstance(model,str) or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:\-]{0,119}',model)) or (provider=='openai' and not model): raise InputError('사용할 모델 ID를 입력해주세요.')
        if not isinstance(key,str) or len(key)>1000 or '\n' in key: raise InputError('API 키 형식을 확인해주세요.')
        with self.guard:
            if self.thread and self.thread.is_alive(): raise InputError('분석이 끝난 뒤 모델 설정을 변경해주세요.')
            if provider=='codex':
                info=codex_status(refresh=True)
                if not info['installed'] or not info['compatible']:raise InputError('지원하는 Codex CLI를 설치하거나 업데이트해주세요.')
                if not info['authenticated']:raise InputError('Codex 로그인이 필요해요. 터미널에서 codex login을 실행해주세요.')
                old=json.loads(self.model_path.read_text()) if self.model_path.exists() else {}
                # Retain an existing API credential locally when switching providers; never pass it to Codex.
                save_private(self.model_path,dict(old,provider='codex',model=model))
                return self.model_state()
            if not key and self.model_path.exists(): key=json.loads(self.model_path.read_text()).get('api_key','')
            if not key.strip(): raise InputError('OpenAI API 키를 입력해주세요.')
            save_private(self.model_path,{'provider':'openai','model':model,'api_key':key.strip()})
        return self.model_state()

    def draft(self,value):
        value=clean_draft(value)
        # Confirmation is per generation, not a durable authorization.
        value['confirmed']=False
        with self.session() as s: eid=s.append('onboarding_draft',value,date.today().isoformat())
        return {'saved':True,'id':eid}

    def refresh(self):
        with self.broker() as (b,c):
            raw=b.holdings(); sectors=b.sectors()['sectors']
        items=raw['items']
        included=[x for x in items if x['marketCountry']=='US' and x['currency']=='USD']
        snapshot={'captured_at':datetime.now(timezone.utc).isoformat(),'identity':identity(c),
            'holdings':raw,'included':included,'excluded_count':len(items)-len(included),'sectors':sectors}
        with self.session() as s:
            eid=s.append('onboarding_snapshot',snapshot,date.today().isoformat())
            return self.public_snapshot(s.get(eid))

    @staticmethod
    def public_snapshot(row):
        if not row:return None
        b=row['body']
        return {'id':row['id'],'captured_at':b['captured_at'],'excluded_count':b['excluded_count'],
                'items':[{k:x[k] for k in ('symbol','name','quantity')} for x in b['included']],
                'sectors':b['sectors']}

    def state(self):
        with self.session() as s:
            reports=s.events('completed'); draft=s.latest('onboarding_draft'); job=s.latest('onboarding_job')
            job_value=copy.deepcopy(job['body']) if job else None
            diagnostic=failed_job_diagnostic(s,job) if job else None
            if diagnostic:job_value.update(message=diagnostic.message,output_validation=diagnostic.details,
                diagnostic_source='read_only_validation_of_original_output')
            if job_value and job_value.get('status')=='needs_input' and job_value.get('context_output_id'):
                job_value['structured_questions']=questions(s.get(job_value['context_output_id'])['body']['output'])
            return {'draft':draft['body'] if draft else {},'snapshot':self.public_snapshot(s.latest('onboarding_snapshot')),
                'model':self.model_state(),'latest':present(s,reports[-1]) if reports else None,
                'history':[{'id':r['id'],'as_of':r['effective'],'action':r['body']['proposal']['action'],
                            'revision_of':r['body'].get('revision_of'),'previous_id':r['body'].get('previous_id')} for r in reversed(reports[-40:])],
                'job':job_value,'clarification_answers':answers(s),
                'context_note_history':notes_history(s,draft['body'].get('context_notes','') if draft else ''),
                'capital_limit':self.capital_limit()}

    def answer_context(self,value):
        with self.guard:
            if self.thread and self.thread.is_alive():raise InputError('진행 중인 분석이 끝난 뒤 답변을 수정해주세요.')
            with self.session() as s:return save_answers(s,value)

    def report(self,eid):
        with self.session() as s:
            row=s.get(eid)
            if row['kind']!='completed': raise PermissionError()
            return present(s,row)

    def job(self,jid,status,message,**kwargs):
        with self.session() as s: s.append('onboarding_job',dict(id=jid,status=status,message=message,**kwargs),date.today().isoformat())

    def recover(self):
        with self.session() as s:
            s.recover('Service restarted under exclusive process lock; no automatic retry',date.today().isoformat())
            row=s.latest('onboarding_job')
            if row and row['body']['status']=='running':
                s.append('onboarding_job',dict(row['body'],status='interrupted',message='서비스가 재시작됐어요. 입력을 확인한 뒤 다시 생성해주세요.'),date.today().isoformat())
            elif row and row['body']['status']=='failed' and row['body'].get('error_type')=='ValueError':
                # Repair only the old, identifiable R1-stop case. Keep every original event.
                failed=s.latest('failed');jobs=s.events('onboarding_job')
                starts=[j for j in jobs if j['body']['id']==row['body']['id'] and j['body']['status']=='running']
                if not failed or not starts or not starts[0]['seq']<failed['seq']<row['seq']:return
                records=s.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? AND kind IN (?,?) ORDER BY seq',
                    (s.owner,failed['run_id'],'agent_input','agent_output')).fetchall()
                if len(records)!=2:return
                source,output=[s.decode(r) for r in records]
                b=output['body']
                if source['kind']!='agent_input' or output['kind']!='agent_output' or b.get('role')!='context' or b.get('input_id')!=source['id']:return
                try:validate_output('context',b['output'],source['body']['payload'])
                except (ValueError,TypeError,KeyError):return
                if b['output']['missing']:
                    s.append('onboarding_job',{'id':row['body']['id'],'status':'needs_input',
                        'message':ContextNeedsInput.message,'questions':b['output']['missing'],
                        'context_output_id':output['id'],'previous_job_event':row['id'],
                        'reason':'Show the validated context questions previously hidden as a generic failure'},date.today().isoformat())

    def start(self,value):
        value=clean_draft(value)
        with self.guard:
            if self.thread and self.thread.is_alive(): raise InputError('이미 포트폴리오를 분석하고 있어요.')
            with self.session() as s:
                snapshot=s.latest('onboarding_snapshot')
                if not snapshot: raise InputError('토스 보유를 먼저 불러와주세요.')
                inputs(value,snapshot,self.capital_limit(),datetime.now(timezone.utc))
                last=s.latest('completed')
                if last and last['effective']==date.today().isoformat() and not value.get('revision_reason','').strip():
                    raise InputError('같은 날 다시 생성할 때는 변경 이유를 입력해주세요.')
            if not self.model_state()['configured']: raise InputError('화면 아래 분석 모델 설정을 먼저 저장해주세요. 입력 임시 저장은 가능해요.')
            self.draft(value)
            jid=uuid.uuid4().hex
            self.job(jid,'running','보유와 시장 자료를 다시 확인하고 있어요.')
            self.thread=threading.Thread(target=self._generate,args=(jid,value,snapshot),daemon=True)
            self.thread.start()
            return {'job_id':jid,'status':'running'}

    def _generate(self,jid,value,snapshot):
        try:
            self.generate(value,snapshot,lambda msg:self.job(jid,'running',msg))
            self.job(jid,'completed','포트폴리오 제안과 분석 리포트를 저장했어요. 주문은 전송하지 않았어요.')
        except ContextNeedsInput as exc:
            self.job(jid,'needs_input',exc.message,questions=exc.questions,context_output_id=exc.output_id,
                     structured_questions=exc.structured_questions)
        except ContextRepeatError as exc:
            self.job(jid,'failed',exc.message,error_type='ContextRepeatError')
        except AgentOutputError as exc:
            self.job(jid,'failed',exc.message,error_type='AgentOutputError',output_validation=exc.details)
        except (InputError,CodexError) as exc: self.job(jid,'failed',str(exc))
        except Exception as exc:
            self.job(jid,'failed','생성하지 못했어요. 토스 연결·모델 설정·시장 자료를 확인한 뒤 다시 시도해주세요.',error_type=type(exc).__name__)

    def generate(self,value,snapshot,progress=lambda msg:None):
        now=datetime.now(timezone.utc); today=now.astimezone(KST).date().isoformat()
        p,cash,amount,candidates=inputs(value,snapshot,self.capital_limit(),now)
        positions={x['symbol']:numeric(x['quantity'],'보유 수량') for x in snapshot['body']['included'] if float(x['quantity'])}
        with self.broker() as (b,config):
            if identity(config)!=snapshot['body']['identity']: raise InputError('계좌 설정이 바뀌었어요. 보유를 다시 불러와주세요.')
            fresh=b.holdings()
            current={x['symbol']:numeric(x['quantity'],'보유 수량') for x in fresh['items'] if x['marketCountry']=='US' and x['currency']=='USD' and float(x['quantity'])}
            if current!=positions: raise InputError('보유 수량이 바뀌었어요. 최신 내역을 다시 불러와 확인해주세요.')
            sectors=snapshot['body']['sectors']; memberships={}
            requested=set(p['criteria']['preferred_sectors']+p['criteria']['excluded_sectors'])
            for sector in sectors:
                if sector['depth']==0 or sector['name'] in requested:
                    progress('섹터 노출 확인 중: '+sector['name'])
                    memberships[sector['name']]=b.sector_stocks(sector['sectorId'])
            automatic=not candidates
            if automatic:
                # A disclosed, deterministic candidate screen; not a recommendation.
                excluded={x['symbol'] for name in p['criteria']['excluded_sectors'] for x in memberships[name]['stocks']}
                ranked=[]
                for name in p['criteria']['preferred_sectors']:
                    ranked.extend(x['symbol'] for x in memberships[name]['stocks'][:3])
                for sector in sectors:
                    if sector['depth']==0: ranked.extend(x['symbol'] for x in memberships[sector['name']]['stocks'][:2])
                candidates=list(dict.fromkeys(x for x in ranked if x not in excluded and re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',x)))[:30]
            symbols=sorted(set(candidates)|set(positions))
            if not symbols: raise InputError('조회한 섹터에서 분석 후보를 찾지 못했어요. 검토할 티커를 직접 입력해주세요.')
            if len(symbols)>80: raise InputError('조회·분석할 종목이 너무 많아요. 후보를 줄여주세요.')
            stocks=b.stocks(symbols); prices=b.prices(symbols)
            fx=b.exchange_rate()
        captured=datetime.now(timezone.utc)
        if fx['baseCurrency']!='USD' or fx['quoteCurrency']!='KRW': raise InputError('환율 통화가 맞지 않아요.')
        if not datetime.fromisoformat(fx['validFrom'])<=captured<=datetime.fromisoformat(fx['validUntil']):
            raise InputError('유효한 환율을 받지 못했어요. 잠시 후 다시 시도해주세요.')
        rate=numeric(fx['midRate'],'환율')
        if rate<=0: raise InputError('환율이 올바르지 않아요.')
        actual={'as_of':today,'base_currency':'KRW','cash':cash['KRW'],
            'cash_components':cash,'positions':positions,'rationale':value['rationale'],
            'last_rebalanced':value['last_rebalanced'],'snapshot_id':snapshot['id'],'cashflows_reconciled':False}
        m={'as_of':today,'base_currency':'KRW','prices':{},'assets':{},'facts':[]}
        # USD cash is a distinct FX-exposed asset; CASH always denotes base-currency cash.
        if cash['USD']:actual['positions']['USD_CASH']=cash['USD']
        m['prices']['USD_CASH']={'price':rate,'observed_at':today,'known_at':today,'source':SOURCE}
        m['assets']['USD_CASH']={'market':'US','currency':'USD','kind':'cash','asset_class':'cash',
            'stress_loss':0.2,'stress_assumption':'USD의 KRW 환산 가치 20% 하락 가정. 예측이나 손실 한도가 아니에요.',
            'liquid':True,'expense_ratio':0,'eligible':True,'sector_exposures':{},'sector_source':SOURCE,
            'sector_as_of':today,'sector_valid_until':today,'sector_complete':True}
        m['coverage']={'status':'limited','available':['종목 기본 정보','시세','토스 섹터 분류','USD/KRW 환율'],
            'missing':['기업 가치 평가 자료','거시·산업·지정학 뉴스','ETF 내부 구성','거래 비용·세금','거래 유동성','동일 통화 과거 총수익률'],
            'actionable_risky_allocation':False,
            'reason':'현재 연결은 기본 조회 자료예요. 가격·섹터만으로 저평가나 전망을 확인할 수 없어 위험자산 제안을 확정하지 않아요.'}
        p['candidate_screen']={'automatic':automatic,'symbols':candidates,
            'method':'현재 보유 + 선호 섹터별 시총 상위 3개 + 대분류별 상위 2개에서 제외 섹터 제거 후 신규 후보 최대 30개' if automatic else '사용자 지정 후보 + 현재 보유',
            'limitation':'전체 시장 탐색이 아니며 대형주 편향이 있어요. 자동 후보에는 ETF가 포함되지 않아요. 기업 가치·뉴스 추가 검토가 필요해요.'}
        valid=(d.day(today)+timedelta(days=7)).isoformat()
        stockmap={x['symbol']:x for x in stocks}; quotemap={x['symbol']:x for x in prices}
        for symbol in symbols:
            if symbol not in stockmap or symbol not in quotemap: raise InputError(symbol+' 시세·기본 정보가 없어요.')
            stock,q=stockmap[symbol],quotemap[symbol]
            if q['currency']!='USD' or stock['market'] not in {'NYSE','NASDAQ','AMEX','US_ETC'}: raise InputError(symbol+'은 미국 달러 종목이 아니에요.')
            if not q.get('timestamp'): raise InputError(symbol+'의 시세 시각이 없어 평가할 수 없어요.')
            stamp=datetime.fromisoformat(q['timestamp'])
            if stamp.tzinfo is None or stamp>captured: raise InputError('시세 시각이 올바르지 않아요.')
            observed=stamp.astimezone(KST).date().isoformat()
            m['prices'][symbol]={'price':numeric(q['lastPrice'],'가격')*rate,'observed_at':observed,'known_at':today,'source':SOURCE}
            is_stock=stock.get('securityType') in {'STOCK','FOREIGN_STOCK','DEPOSITARY_RECEIPT','REIT'}
            tags={name:1.0 for name,data in memberships.items() if any(x['symbol']==symbol for x in data['stocks'])} if is_stock else {}
            asset={'market':'US','currency':'USD','kind':stock['securityType'],
                'asset_class':'equity' if is_stock else 'unknown','stress_loss':0.5,
                'stress_assumption':'모든 위험자산 50% 가격 하락. 시스템의 점검 가정이며 예측이 아니에요.',
                'liquid':False,'expense_ratio':0 if is_stock else None,
                'eligible':stock['status']=='ACTIVE' and stock.get('leverageFactor') in (None,'1','1.0',1)}
            if tags: asset.update(sector_exposures=tags,sector_source=SOURCE,sector_as_of=today,sector_valid_until=valid,sector_complete=True)
            m['assets'][symbol]=asset
            m['facts'].append({'id':'toss-'+symbol,'topic':symbol,'text':d.dumps({'instrument':stock,'quote':q,'sector_tags':list(tags)}),
                'source':SOURCE,'published_at':today,'known_at':today,'valid_until':valid,
                'uncertainty':'기본 정보와 시세만 확인. 기업 가치·뉴스·ETF 내부 구성·거래 유동성·과거 수익률 미확인. 섹터는 토스 자체 분류이며 중복 가능.'})
        m['facts'].append({'id':'toss-usdkrw','topic':'FX','text':d.dumps(fx),'source':SOURCE,
            'published_at':today,'known_at':today,'valid_until':today,'uncertainty':'이번 평가에 매매기준율 사용. 실제 환전비용·세금 제외.'})
        d.market(m); nav=d.valuation(actual,m,allow_empty=True)['nav']
        p['proposal_capital']=amount if value['capital_mode']=='total' else nav+amount
        p['funding_mode']=value['capital_mode']
        if not 0<p['proposal_capital']<=self.capital_limit(): raise InputError('기존 보유와 추가 자금을 합친 제안 총액이 운용 한도를 넘어요.')
        if p['proposal_capital']>p['total_assets']: raise InputError('제안 운용액이 입력한 총 금융자산보다 커요. 자산과 운용액을 확인해주세요.')
        if p['cash_need']>p['proposal_capital']: raise InputError('포트폴리오 안에서 남길 현금이 운용 총액보다 커요.')
        d.profile(p); d.holdings(actual)
        model=self.analysis_model()
        if model.mode!='live': raise InputError('실제 제안에는 합성 모델을 사용할 수 없어요.')
        original_complete=model.complete
        def complete(role,*args):
            progress({'context':'개인 맥락','evidence':'시장 근거','buffett':'Buffett 관점','marks':'Marks 관점','bogle':'Bogle 관점','validation':'위험·적합성 검증','leader':'최종 제안','reflection':'회고','memory':'지식 정리'}.get(role,role)+' 분석 중이에요.')
            return original_complete(role,*args)
        model.complete=complete
        with self.session() as s:
            p['clarification_answers']=answers(s)
            p['context_note_history']=notes_history(s,p.get('context_notes',''))
            with s.store.transaction():
                source_id=s.append('onboarding_evidence',{'snapshot_id':snapshot['id'],'captured_at':captured.isoformat(),
                    'holdings':fresh,'stocks':stocks,'prices':prices,'fx':fx,'sectors':memberships},today)
                actual['evidence_id']=source_id
                e=Engine(s,model); e.set_profile(p,today); e.set_holdings(actual)
                mid=s.store.publish_market(m)
            return e.run(today,mid,force=True,revision_reason=value.get('revision_reason'))
