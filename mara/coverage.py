"""Frozen evidence requirements and delivery checks, separate from changing analysis exhibits."""
import json
from .decision import source_values


COVERAGE={
 'context.cashflow':('context',[],['/analysis/household/monthly_remaining_after_investing']),
 'context.household':('context',[],['/analysis/household/property_equity','/analysis/household/stress']),
 'market.macro':('evidence',['treasury','bls','fed_statement'],[]),
 'market.institutional':('evidence',['institutional_reports'],[]),
 'selection.product':('bogle',['fund_profile'],['/analysis/products']),
 'selection.lookthrough':('validation',['fund_holdings'],['/analysis/products']),
 'selection.quality_price':('buffett',['fund_profile'],['/analysis/products']),
 'allocation.alternatives':('leader',[],['/analysis/comparison/results']),
 'risk.quantitative':('validation',['fund_history'],['/analysis/comparison/results']),
 'risk.fx_household':('validation',[],['/analysis/fx_stress/scenarios','/analysis/household/stress']),
 'implementation.costs':('leader',[],['/analysis/costs/monthly_cost_sensitivity']),
 'monitoring.falsifiers':('leader',[],['/proposal/investment_case/monitoring']),
}


def coverage_ledger(report,market):
    rows=[];case=report['proposal'].get('investment_case',{});facts=market['facts']
    selected={s for s,w in report['proposal']['weights'].items() if w>0 and s!='CASH'}
    alternatives={s for a in case.get('alternatives',[]) for s,w in a['weights'].items() if w>0 and s!='CASH'}
    # Cash retains opportunity-cost research; only clearly marked alternative assets enter this denominator.
    targets=sorted(selected|alternatives)
    for key,(role,common_tools,paths) in COVERAGE.items():
        paths=list(paths);requirements=[]
        asset_specific=key.startswith('selection.') or key=='risk.quantitative'
        if key=='selection.lookthrough':paths=['/analysis/lookthrough']
        if key in ('selection.product','selection.quality_price') and targets and all(market['assets'].get(s,{}).get('kind') in {'STOCK','FOREIGN_STOCK','REIT','DEPOSITARY_RECEIPT'} for s in targets):paths=[]
        if asset_specific:
            for symbol in targets:
                individual=market['assets'].get(symbol,{}).get('kind') in {'STOCK','FOREIGN_STOCK','REIT','DEPOSITARY_RECEIPT'}
                tools=({'selection.product':['sec_filings','sec_financials'],
                    'selection.quality_price':['sec_financials','company_filing_search','company_valuation'],
                    'selection.lookthrough':['sec_filings'],'risk.quantitative':['validated_total_return_history']} if individual else
                    {'selection.product':['fund_profile'],'selection.quality_price':['fund_profile'],
                    'selection.lookthrough':['fund_holdings'],'risk.quantitative':['fund_history']})[key]
                for tool in tools:
                    if tool.startswith('company_'):
                        ids=[]
                        for f in facts:
                            if f.get('research_tool')!=tool and not (tool=='company_filing_search' and f.get('research_tool')=='company_filing_read'):continue
                            try:value=json.loads(f['text'])
                            except (ValueError,TypeError):continue
                            if value.get('symbol')==symbol and (tool!='company_filing_search' or value.get('hits') or
                                f.get('research_tool')=='company_filing_read' and value.get('text') and value.get('raw_ref',{}).get('sha256') and value.get('extraction_version')):ids.append(f['id'])
                    else:ids=[x[0] for x in source_values(market,tool,symbol)]
                    requirements.append({'target':symbol,'evidence_type':tool,'fact_ids':ids,'retrieved':bool(ids)})
        else:
            for tool in common_tools:
                ids=[f['id'] for f in facts if f.get('research_tool')==tool]
                requirements.append({'target':'common','evidence_type':tool,'fact_ids':ids,'retrieved':bool(ids)})
        refs=sorted({fid for req in requirements for fid in req['fact_ids']})
        relevant=[x for x in report['evidence_delivery'] if x['role']==role]
        sent=set().union(*(set(x['fact_ids']) for x in relevant)) if relevant else set()
        missing=[req['target']+': '+req['evidence_type'] for req in requirements if not req['retrieved']]
        absent=[]
        for path in paths:
            value=report
            try:
                for part in path[1:].split('/'):value=value[int(part)] if isinstance(value,list) else value[part]
                if value is None or value in ({},[]):absent.append(path)
            except (KeyError,IndexError,ValueError,TypeError):absent.append(path)
        if key in ('allocation.alternatives','risk.quantitative') and not report['analysis']['comparison'].get('available'):absent.append('comparison unavailable')
        if key=='selection.lookthrough' and not report['analysis'].get('lookthrough',{}).get('available'):absent.append('lookthrough unavailable')
        # No all-cash escape: opportunity-cost alternatives must be explicit.
        if asset_specific and not targets:missing.append('Explicit researched alternative assets missing')
        delivered=bool(relevant) and set(refs)<=sent
        collected=not missing and not absent
        rows.append({'id':key,'owner':role,'required_evidence_types':sorted({x['evidence_type'] for x in requirements}) or ['personal_input_or_calculation_or_monitoring_rule'],
            'asset_requirements':requirements,'selected_targets':sorted(selected),'alternative_targets':sorted(alternatives),
            'fact_ids':refs,'calculation_paths':paths,'input_ids':[x['input_id'] for x in relevant],
            'claim_ids':[c['id'] for c in case.get('claims',[]) if c['requirement_id']==key],
            'retrieved':collected,'delivered':delivered,'support_status':'requires_independent_claim_review',
            'missing_causes':missing+absent,'fallback_attempts':[{'tool':x['tool'],'target':x['target'],'status':x['status'],'reason':x['reason']} for x in market.get('research',{}).get('calls',[]) if any(req['evidence_type']==x['tool'] and req['target'] in ('common',x['target']) for req in requirements) and x['status']!='collected'],
            'applicability':'Fixed common requirement plus all selected/reported alternative assets, independently typed. Cash does not remove opportunity cost.',
            'next_action':'독립 평가자가 주장·반증·자료 범위를 대조' if collected and delivered else '담당 역할이 결측 자료/계산을 확보하고 새 입력으로 재검증'})
    return rows

