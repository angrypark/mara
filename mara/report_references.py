"""Validate author-written exhibit links before accepting a final proposal."""
import math


def errors(proposal,analysis,funding,valuation):
    root={'proposal':proposal,'analysis':analysis,'funding':funding,'valuation':valuation};failures=[]
    def inspect_transient(value,path):
        if isinstance(value,dict):
            for key,item in value.items():inspect_transient(item,path+'/'+str(key).replace('~','~0').replace('/','~1'))
        elif isinstance(value,list):
            for index,item in enumerate(value):inspect_transient(item,path+'/'+str(index))
        elif isinstance(value,str) and '/reference_feedback/' in value:
            failures.append({'path':path,'reason':'Temporary correction input is not a durable final-report calculation link. It may exist in the original author input; cite the corresponding /analysis/, /funding/ or /valuation/ value instead. This is a report-link issue, not evidence fabrication.'})
    inspect_transient(proposal,'/proposal')
    def resolve(path):
        if not isinstance(path,str) or (not path.startswith(('/analysis/','/funding/','/valuation/')) and path!='/proposal/investment_case/monitoring'):
            raise ValueError('Use body-relative /analysis/..., /funding/..., /valuation/... or /proposal/investment_case/monitoring; never /input/ or /report/')
        value=root
        for part in path[1:].split('/'):
            part=part.replace('~1','/').replace('~0','~');value=value[int(part)] if isinstance(value,list) else value[part]
        if value is None or value==[] or value=={} or value=='':raise ValueError('Reference is empty')
        if path.startswith(('/funding/','/valuation/')) and type(value) not in (int,float):raise ValueError('Funding/valuation reference must be numeric')
        return value
    for claim in proposal.get('investment_case',{}).get('claims',[]):
        for path in claim.get('calculation_paths',[]):
            try:resolve(path)
            except (ValueError,KeyError,IndexError,TypeError) as exc:failures.append({'claim_id':claim['id'],'path':path,'reason':str(exc)[:300]})
    for alternative in proposal.get('investment_case',{}).get('alternatives',[]):
        path=alternative['comparison_path']
        try:
            result=resolve(path)
            if not path.startswith('/analysis/') or not isinstance(result,dict) or not isinstance(result.get('weights'),dict) or not result['weights']:
                raise ValueError('Alternative comparison_path must select an analysis result object with explicit weights, not a scalar or unrelated object')
            if isinstance(result,dict) and isinstance(result.get('weights'),dict):
                a={s:w for s,w in alternative['weights'].items() if w>0};b={s:w for s,w in result['weights'].items() if w>0}
                if a.keys()!=b.keys() or any(not math.isclose(w,b[s],abs_tol=1e-9,rel_tol=0) for s,w in a.items()):raise ValueError('Alternative weights differ from the linked comparison')
        except (ValueError,KeyError,IndexError,TypeError) as exc:failures.append({'alternative':alternative['name'],'path':path,'reason':str(exc)[:300]})
    return failures
