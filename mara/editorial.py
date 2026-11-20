"""Select an investor-facing brief after the decision; never change the decision.

The source report and all facts stay immutable. This is an attributed model
summary, not an investment approval or a semantic fact-checking certificate.
"""
import calendar
import copy
from datetime import date
from .contracts import validate, schema
from .domain import dumps
from .final_report import digest
from .registry import role_guide

VERSION='mara.reader-brief/1.0'


def period(as_of):
    end=date.fromisoformat(as_of);month=end.year*12+end.month-1-3
    year,zero_month=divmod(month,12);month=zero_month+1
    start=date(year,month,min(end.day,calendar.monthrange(year,month)[1]))
    return {'start':start.isoformat(),'end':as_of}


def inputs(report,facts):
    """Final decision and final evidence, without repeated full role reports."""
    return {'as_of':report['as_of'],'period':period(report['as_of']),
        'funding':copy.deepcopy(report.get('funding',{})),
        'valuation':copy.deepcopy(report.get('valuation',{})),
        'proposal':copy.deepcopy(report.get('proposal',{})),
        'risk_budget':copy.deepcopy(report.get('risk_budget',{})),
        'final_review':copy.deepcopy(report.get('validation',{}).get('final_critique',{})),
        'market':{'facts':copy.deepcopy(facts)},
        'editorial_boundary':'Explain the frozen decision. Do not change weights, action, approval, funding or claim status. Market interpretation is not a new portfolio decision.'}


def check(brief,payload):
    validate(brief,schema('reader-brief'))
    if brief['as_of']!=payload['as_of'] or brief['period']!=payload['period']:
        raise ValueError('Brief period differs from the frozen input')
    facts={f['id']:f for f in payload['market']['facts']}
    claims={c['id']:c for c in payload['proposal'].get('investment_case',{}).get('claims',[])}
    if len({t['id'] for t in brief['themes']})!=len(brief['themes']):raise ValueError('Duplicate theme id')
    for theme in brief['themes']:
        for fid in theme['fact_ids']:
            if fid not in facts:raise ValueError('Unknown brief fact')
            f=facts[fid]
            if not f['published_at']<=payload['as_of'] or not f['known_at']<=payload['as_of']<=f['valid_until']:
                raise ValueError('Brief fact outside known-time boundary')
    for reason in brief['key_reasons']:
        if not set(reason['claim_ids'])<=claims.keys():raise ValueError('Unknown brief claim')
    if not brief['themes'] and not brief['missing_evidence']:raise ValueError('Empty market brief needs explicit evidence gaps')
    return brief


def create(session,model,report,facts):
    if model.mode!='live':return None
    payload=inputs(report,facts);guide=role_guide('editor')
    contract=schema('reader-brief');run_id=report['run_id'];as_of=report['as_of']
    receipt={'version':VERSION,'input_sha256':digest(payload),'guide_sha256':digest(guide),
        'provider':model.identity,'decision_scope':'Explanation only; decision and holdings unchanged'}
    for attempt in (1,2):
        from .submission_recovery import guard
        guard(session,run_id,as_of)
        iid=session.append('report_editor_input',dict(receipt,payload=payload,guide=guide,contract=contract,
            attempt=attempt,attempt_input_sha256=digest(payload)),as_of,run_id)
        from .codex_model import ProviderSubmissionError
        provider_error=None
        try:output=model.complete('editor',guide,payload,contract)
        except ProviderSubmissionError as exc:provider_error=exc;output=exc.output
        oid=session.append('report_editor_output',dict(input_id=iid,output=output,**({'provider_failure':provider_error.diagnostic,'raw_provider_response':provider_error.raw_response} if provider_error else {})),as_of,run_id)
        try:
            if provider_error:raise provider_error
            check(output,payload)
        except (ValueError,KeyError,TypeError) as exc:
            session.append('report_editor_validation',{'input_id':iid,'output_id':oid,'status':'rejected','error':str(exc)},as_of,run_id)
            if attempt==2:raise ValueError('Reader brief failed reference validation') from None
            payload=dict(payload,repair={'error':str(exc),'previous_output':output,
                'instruction':'Correct only the reference/contract error; do not fill evidence gaps with invented claims.'})
            continue
        session.append('report_editor_validation',{'input_id':iid,'output_id':oid,'status':'accepted',
            'scope':'Structure, dates and references only; content quality requires independent review'},as_of,run_id)
        return {'brief':output,'provenance':dict(receipt,input_id=iid,output_id=oid,
            attempt_input_sha256=digest(payload),brief_sha256=digest(output))}


def presented(record,report,facts):
    if not isinstance(record,dict):return None
    try:
        payload=inputs(report,facts);brief=check(record['brief'],payload);p=record['provenance']
        if digest(payload)!=p['input_sha256'] or digest(brief)!=p['brief_sha256']:return None
        return copy.deepcopy(brief)
    except (ValueError,KeyError,TypeError):return None
