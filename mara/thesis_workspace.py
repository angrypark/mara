"""Candidate-specific preparation, grounded in the facts actually delivered to a role."""
import hashlib
import json
from .domain import dumps
from .earnings_bridge import observations

VERSION='mara.thesis-workspace/1.0'


def build(payload,role):
    market=payload.get('market',{});as_of=payload.get('as_of',market.get('as_of'))
    scope=payload.get('decision_scope',{});candidates=[];definitions={}
    prior={r['id']:r for r in (payload.get('previous') or {}).get('question_followups',[])}
    categories={}
    for f in market.get('facts',[]):
        if not (f.get('published_at','9999')<=as_of and f.get('known_at','9999')<=as_of<=f.get('valid_until','')):continue
        try:v=json.loads(f['text'])
        except (ValueError,TypeError):continue
        if not isinstance(v,dict):continue
        symbol=v.get('symbol') or f.get('company_identity',{}).get('symbol')
        if f.get('research_tool')=='company_company':
            companies=v.get('companies',[])
            symbol=companies[0].get('symbol') if len(companies)==1 else None
        if not symbol:
            for kind in ('sec_financials','fund_holdings'):
                prefix='research-'+kind+'-'
                if f.get('research_tool')==kind and f['id'].startswith(prefix):symbol=f['id'].removeprefix(prefix)
        if symbol:categories.setdefault(symbol,[]).append((f,v))
    for q in scope.get('questions',[]):
        symbol=q['target']
        if symbol=='portfolio':continue
        equity=market.get('assets',{}).get(symbol,{}).get('kind') in {'STOCK','FOREIGN_STOCK','REIT','DEPOSITARY_RECEIPT'}
        relevant=categories.get(symbol,[])
        ids=lambda tool:[f['id'] for f,v in relevant if f.get('research_tool') in tool]
        bridge=ids({'company_normalize_earnings'});values=ids({'company_valuation'})
        quotes=ids({'company_company'});financial=ids({'sec_financials','company_xbrl_read'})
        task=[dict(id=q['id']+'-normalize',gap_type='analysis_and_source_binding',
            required='같은 연간 기간·USD·주식 기준의 관측값과 명시적 정상화 조정식',
            action='company/xbrl_read로 같은 연간 기간의 USD와 shares를 읽고 normalize_earnings에 관측 위치·조정계수·이유·재투자·희석·반증을 지정해요.',
            available_fact_ids=financial+bridge),
            dict(id=q['id']+'-price',gap_type='assumption_challenge',
            required='정상화와 성장·할인·영구성장 가정의 근거, 가격이 요구하는 이익, 반증 조건',
            action='valuation의 normalization_fact_id를 연결하고 가격이 요구하는 이익을 비교해요. 음수 이익은 별도 방법이 필요해요.',available_fact_ids=values)] if equity else [
            dict(id=q['id']+'-exposure',gap_type='coverage_and_selection_reason',required='전체 구성·집중·중복·비용과 단순 분산 대안 대비 편입 이유',
                action='analysis.products/lookthrough의 기준일·부분 coverage를 먼저 확인. 운용사 전체 보유 근거가 없으면 미확인으로 남기고 company DCF로 대체하지 않아요.',available_fact_ids=ids({'fund_holdings','fund_profile'}))]
        # Rules are instructions, not source assertions or automatically resolved questions.
        task.append(dict(id=q['id']+'-allocation',gap_type='comparative_judgment',required='왜 0 또는 해당 비중인가: 같은 자금·통화의 작은 대안과 기회비용',
            action='결정적인 대안을 investment_case.alternatives에 weights와 comparison_path로 남겨요. 리더가 새 대안을 제시하면 /analysis/alternative_comparisons/{index}에서 재계산 후 검토해요. 수치 통과와 선택 이유의 충분성을 구분해요.',available_fact_ids=[]))
        compact_tasks=[]
        for task in task:
            step=task['id'].rsplit('-',1)[-1]
            definitions[step]={k:task[k] for k in ('required','action')}
            compact_tasks.append({k:v for k,v in task.items() if k not in ('required','action')})
            compact_tasks[-1]['step']=step
        task=compact_tasks
        row={'question_id':q['id'],'target':symbol,'owner':q['owner'],'asset_path':'equity' if equity else 'fund_or_other',
            'state':'requires_analysis_review','prior_review':prior.get(q['id'],{}).get('review'),
            'quote_fact_ids':quotes,'tasks':task,'observation_locators':[],'observation_count':0}
        if equity:
            all_rows=observations(dict(market,facts=[f for f,v in relevant]),symbol);row['observation_count']=len(all_rows)
            annual=[x for x in all_rows if x.get('start') and x.get('unit') in ('USD','shares')]
            # Bounded navigation only; not a complete financial statement or a chosen normalization.
            annual.sort(key=lambda x:(x.get('end') or '',x.get('filed') or ''),reverse=True)
            preferred=('net_income','operating_cashflow','capital_expenditure','productive_asset_purchases','stock_compensation','diluted_shares','WeightedAverageNumberOfDilutedSharesOutstanding')
            selected=[];seen=set()
            for x in annual:
                key='annual_diluted_shares' if x['unit']=='shares' else 'operating_cashflow' if x['concept']=='NetCashProvidedByUsedInOperatingActivities' else x['concept']
                if x['concept'] in preferred and key not in seen:selected.append(x);seen.add(key)
            selected.sort(key=lambda r:0 if r['unit']=='shares' else 1 if r['concept'] in ('operating_cashflow','NetCashProvidedByUsedInOperatingActivities') else 2)
            row['observation_locators']=selected[:6]
            row['observation_navigation_only']=True
        candidates.append(row)
    result=dict(schema_version=VERSION,as_of=as_of,role=role,candidates=candidates,task_definitions=definitions,
        comparison_paths=['/analysis/'+k for k in ('selected_comparison','perspective_comparisons','alternative_comparisons','lookthrough','products') if payload.get('analysis',{}).get(k)],
        completion_rule='Prepared inputs, computed arithmetic and source availability do not resolve a decision. R4 reviews the existing question ID against the final proposal; cash/defer is not automatically optimal.',
        unchanged='No new investor constraints, weights, rates or recommendation defaults. Existing decision_scope remains frozen.')
    # Never silently truncate a fact or a reason: remove locator lists with an explicit navigation fallback.
    if len(dumps(result))>24000:
        result['locator_omission']='Bounded navigation, not complete statements. Per-candidate locators are reduced equally, keeping shares and cash flow first; use xbrl_read/evidence_read for omitted observations.'
        for keep in (4,2,1,0):
            for r in candidates:r['observation_locators']=r['observation_locators'][:keep]
            if len(dumps(result))<=24000:break
    result['input_facts_sha256']=hashlib.sha256(dumps(market.get('facts',[])).encode()).hexdigest()
    return result
