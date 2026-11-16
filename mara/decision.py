"""Proposal-specific evidence and household arithmetic; no execution authority."""
import json
import math
import re
from urllib.parse import urlsplit
from . import domain as d

POLICY='proposal-evidence-1.0'


def contributions(profile):
    monthly=profile.get('contribution_schedule','days')=='monthly'
    amount=profile['contribution_amount'] if monthly else profile['contribution_amount']*365.25/12/profile['contribution_every_days']
    return {'monthly_amount':amount,'schedule':'calendar_month' if monthly else 'every_n_days',
        'amount_per_payment':profile['contribution_amount'],
        'method':'매월 같은 금액. 연 12회.' if monthly else '매회 금액 × 365.25 ÷ 12 ÷ 납입 간격(일). 실제 입금액이 아닌 월평균 계획.'}


def household(profile):
    h=profile.get('household',{});property_value=h.get('property_value');debt=h.get('mortgage_balance')
    payment=h.get('monthly_debt_payment');included=h.get('debt_payment_in_expenses','unknown')
    uncertain_payment=bool(payment and included=='unknown')
    extra=payment if included in ('no','unknown') and payment is not None else 0
    surplus=profile['monthly_income']-profile['monthly_expenses']-extra
    complete=(debt==0 or included=='yes' or included=='no' and payment is not None) if debt is not None else None
    if uncertain_payment:complete=False
    return {'base_currency':profile['base_currency'],'property_value':property_value,'mortgage_balance':debt,
        'property_equity':property_value-debt if property_value is not None and debt is not None else None,
        'loan_to_value':debt/property_value if property_value and debt is not None else None,
        'outside_emergency_cash':h.get('outside_emergency_cash'),
        'reported_liquid_cash':h.get('reported_liquid_cash'),
        'reported_liquid_cash_scope':'사용자 진술 전체 유동 현금. 계좌 현금·별도 비상금과 포함 관계가 있어 합산하지 않음. 목적별 필요액·즉시 사용 가능액 확인과 별개.',
        'monthly_debt_payment':payment,'debt_payment_in_expenses':included,
        'monthly_surplus_before_investing':surplus,'monthly_contribution':contributions(profile)['monthly_amount'],
        'monthly_remaining_after_investing':surplus-contributions(profile)['monthly_amount'],
        'cashflow_complete':complete,
        'limits':('상환액의 지출 포함 여부가 미확인이므로 별도 차감한 보수적 조건부 현금흐름이에요. 포함 여부 확인 전에는 확정 잔여액이 아니에요. ' if uncertain_payment else '')+'부동산 자기자본은 매수 가능 현금이 아니에요. 부동산 시가는 사용자 입력이며 보증·처분 비용·기타 부채를 반영한 전체 순자산이 아니에요. 소득 지속성은 보장하지 않아요.'}


def cik(value):
    if isinstance(value,bool) or not re.fullmatch(r'\d{1,10}',str(value)):return None
    return str(int(value)) if int(value)>0 else None


def valid_filings(value,as_of):
    identity=cik(value.get('cik'))
    if not identity:return False
    for row in value.get('filings',[]):
        try:
            age=(d.day(as_of)-d.day(row['filed'])).days
            url=urlsplit(row['url']);acc=row['accession']
            if (0<=age<=550 and row['form'] in {'10-K','10-Q','8-K','20-F','6-K','10-K/A','10-Q/A'}
                and re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc) and url.scheme=='https' and url.hostname=='www.sec.gov'
                and not url.username and not url.password and url.path.startswith('/Archives/edgar/data/'+identity+'/'+acc.replace('-','')+'/')):return True
        except (ValueError,TypeError,KeyError):continue
    return False


def current_metric(value,name,as_of):
    if name in value.get('stale_metrics',[]):return False
    for series in value.get('metrics',{}).get(name,[]):
        if series.get('unit')!='USD' or series.get('period_type')!='annual':continue
        for row in series.get('observations',[]):
            try:
                if isinstance(row,list):row=dict(zip(value['observation_columns'],row))
                end=d.day(row['end']);filed=d.day(row['filed']);start=d.day(row['start'])
                number=row['value']
                if (330<=(end-start).days<=380 and 0<=(d.day(as_of)-end).days<=550 and end<=filed<=d.day(as_of)
                    and isinstance(number,(int,float)) and not isinstance(number,bool) and math.isfinite(number)
                    and row['form'] in {'10-K','10-Q','10-K/A','10-Q/A'} and re.fullmatch(r'\d{10}-\d{2}-\d{6}',row['accession'])):return True
            except (ValueError,TypeError,KeyError):continue
    return False


def source_values(market,tool,symbol):
    out=[]
    for f in market.get('facts',[]):
        if f.get('research_tool')!=tool or f.get('valid_until','')<market['as_of']:continue
        if f.get('known_at','9999')>market['as_of']:continue
        try:v=json.loads(f['text'])
        except (ValueError,TypeError):continue
        if not isinstance(v,dict):continue
        if f['id']!='research-'+tool+'-'+symbol.replace('.','-'):
            identity=f.get('company_identity',{});company_cik=cik(identity.get('cik'));source=urlsplit(f.get('source',''))
            if tool not in ('sec_filings','sec_financials') or identity.get('symbol','').replace('.','-')!=symbol.replace('.','-') or not company_cik or company_cik!=cik(v.get('cik')):continue
            expected=('/submissions/CIK' if tool=='sec_filings' else '/api/xbrl/companyfacts/CIK')+company_cik.zfill(10)+'.json'
            if source.scheme!='https' or source.hostname!='data.sec.gov' or source.path!=expected or source.username or source.password:continue
            if identity.get('verification')!='SEC submissions ticker match' or not re.fullmatch('[a-f0-9]{64}',identity.get('version','')):continue
        if isinstance(v,dict):out.append((f['id'],v))
    return out


def asset_requirements(market,symbol):
    a=market['assets'].get(symbol,{});missing=[];refs=[]
    if symbol not in market['prices']:missing.append('현재 가격과 기준통화 환산')
    if a.get('asset_class','unknown')=='unknown':missing.append('상품의 자산군과 위험 구조')
    if a.get('asset_class')=='cash':return {'missing':missing,'evidence_ids':refs,'kind':'cash'}
    if a.get('kind') in {'STOCK','FOREIGN_STOCK','DEPOSITARY_RECEIPT','REIT'}:
        financials=source_values(market,'sec_financials',symbol)
        filings=[(fid,v) for fid,v in source_values(market,'sec_filings',symbol) if v.get('symbol','').replace('.','-')==symbol.replace('.','-') and valid_filings(v,market['as_of'])]
        for fid,v in financials:
            if (all(current_metric(v,name,market['as_of']) for name in ('revenue','operating_cashflow'))
                and cik(v.get('cik')) and any(cik(v.get('cik'))==cik(f.get('cik')) for _,f in filings)):refs.append(fid)
        if not refs:missing.append('현재 유효한 매출·영업현금흐름과 기간/단위')
        if not filings:missing.append('기업 식별을 확인한 공시 목록')
        refs.extend(fid for fid,_ in filings)
        kind='individual_equity'
    else:
        for tool,label in [('fund_profile','운용목적·추종방식·보수'),('fund_holdings','내부 구성과 집중도')]:
            values=source_values(market,tool,symbol)
            if tool=='fund_profile':values=[(fid,v) for fid,v in values if v.get('symbol')==symbol and v.get('objective') and v.get('benchmark') and isinstance(v.get('expense_ratio'),(int,float)) and not isinstance(v.get('expense_ratio'),bool) and 0<=v['expense_ratio']<=.1]
            else:values=[(fid,v) for fid,v in values if isinstance(v.get('holdings_count'),int) and v['holdings_count']>0 and v.get('sector_weights') and isinstance(v.get('reported_weight_sum'),(int,float)) and .97<=v['reported_weight_sum']<=1.03]
            if not values:missing.append(label)
            refs.extend(fid for fid,_ in values)
        kind='fund'
    return {'missing':missing,'evidence_ids':refs,'kind':kind}


def assessment(weights,market):
    """Only selected positive positions create minimum-research blockers.

    Passing this gate means the inputs support deliberation. R4 still judges
    valuation, suitability and material unresolved risks of the actual thesis.
    """
    if market.get('coverage',{}).get('proposal_policy')!=POLICY:return None
    selected={s:asset_requirements(market,s) for s,w in weights.items() if w>0 and s!='CASH'}
    gaps=[{'subject':s,'owner':'evidence','category':'market_evidence','blocks':'proposal',
           'reason':reason,'resolution':'대상 자료를 수집하거나 근거가 있는 다른 후보/현금 대안과 비교해요.'}
          for s,v in selected.items() for reason in v['missing']]
    return {'policy':POLICY,'selected_assets':selected,'blockers':gaps,
        'execution_checks':['주문 시점 가격·호가·거래 단위·계좌 가능 여부','수수료·환전 스프레드·세금과 적용 한도','실제 입금과 사용자의 주문 지시'],
        'limits':'최소 분석 자료 검사이며 적정 가치·수익·개인 적합성 통과가 아니에요. 주문 전 확인만 남았다는 이유로 배분 연구를 자동 보류하지 않지만, 실제 제안에 중요한 비용/위험 공백은 R4가 보류할 수 있어요.'}


def semantics(profile,market):
    return {'version':'mara.decision-context/1.0.0','scope':'portfolio_proposal_only','orders_authorized':False,
        'cash':'CASH는 기준통화 현금이며 종목·ETF 하나의 집중 상한 대상에서 제외. USD_CASH는 환율 노출을 가진 현금.',
        'position_limit':'max_position_fraction은 비현금 상품 하나의 상한. ETF 내부 분산과 상품 비중 상한은 별개.',
        'contribution':contributions(profile),'household':household(profile),
        'contribution_mandate':{'preference':profile.get('contribution_risk_preference','inherit'),
            'scope':'향후 소득의 신규 납입 배분 선호. 기존 보유 현금 전액 투입 지시가 아님.',
            'rule':'growth이면 현재 한도 안에서 더 높은 위험자산 대안을 실제 비교. 낮은 비중을 택하면 구체적인 한도·근거·트레이드오프를 제시. 비상금 개월 수를 사용자 의무로 신설하거나 고소득을 무위험 소득으로 가정하지 않음. 손실·상품·섹터 등 기존 수치 제약은 변경하지 않음.'},
        'candidate_readiness':{s:asset_requirements(market,s) for s in market['assets'] if s!='USD_CASH'} if market.get('coverage',{}).get('proposal_policy')==POLICY else {},
        'decision_rule':'개인 적합성·실제 제약 위반·제안의 핵심 주장 근거 부족은 보류. 개별주 가치판단과 광범위 지수 적립의 근거 기준을 구분. 완전한 미래 예측이나 모든 지표의 존재는 요구하지 않아요.',
        'funding':'제안 금액·현재 보유·실제 사용 가능한 현금·향후 월소득은 서로 달라요. 부동산 자기자본을 주식 투자 현금에 더하지 않고 첫 납입을 정기 납입과 중복 합산하지 않아요.'}


def decision_findings(check,review):
    findings=[];covered=set()
    for gap in (check.get('evidence_assessment') or {}).get('blockers',[]):
        reason=gap['subject']+': '+gap['reason'];covered.add(reason)
        findings.append({'category':gap['category'],'blocks_proposal':True,'subject':gap['subject'],
            'reason':reason,'resolution':gap['resolution'],'owner':gap['owner']})
    for reason in check['errors']:
        findings.append({'category':'constraint','blocks_proposal':True,'subject':'수치 제약',
            'reason':reason,'resolution':'사용자 한도를 유지한 다른 비중을 검토해요. 한도 변경이 필요하면 사용자가 직접 결정해요.','owner':'leader'})
    for reason in check['missing']:
        if reason in covered:continue
        personal=reason.startswith('향후 소득만으로')
        findings.append({'category':'personal_context' if personal else 'market_evidence','blocks_proposal':True,
            'subject':'납입 재원' if personal else '필수 검증 자료','reason':reason,
            'resolution':'납입 규모와 실제 재원을 확인해요.' if personal else '부족한 노출·분류 자료를 확인하거나 그 제약을 검증할 수 있는 대안 배분을 검토해요.',
            'owner':'context' if personal else 'evidence'})
    findings.extend(review.get('findings',[]))
    if not review['qualitative_pass'] and not any(x['blocks_proposal'] for x in review.get('findings',[])):
        findings.append({'category':'capability','blocks_proposal':True,'subject':'정성 검증',
            'reason':review['reason'][:1500],'resolution':'검증 역할이 제시한 문제와 해소 조건을 확인해요.','owner':'validation'})
    return findings
