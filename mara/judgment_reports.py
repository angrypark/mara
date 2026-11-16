"""Public decision explanations, not private reasoning transcripts or quality scores."""
import re
from .contracts import validate,schema

VERSION='mara.judgment-report/1.0'
SECTIONS=('portfolio_context','market_context','decision_method','conclusion')
MIN_BODY_CHARACTERS=1400


def body_length(report):
    return sum(len(re.sub(r'\s','',report.get(k,''))) for k in SECTIONS)


def validate_report(output,payload):
    report=output.get('judgment_report')
    if not report and not payload.get('narrative_contract'):return
    try:
        validate(report,schema('judgment-report'))
        if report['as_of']!=payload['as_of']:raise ValueError('basis date differs from the input')
        if any(len(re.sub(r'\s','',report[k]))<250 for k in SECTIONS):raise ValueError('each section needs at least 250 non-whitespace characters')
        if body_length(report)<MIN_BODY_CHARACTERS:raise ValueError('at least 1400 non-whitespace body characters across the four sections required')
        normalized=[re.sub(r'\s','',report[k]) for k in SECTIONS]
        if len(set(normalized))!=len(SECTIONS):raise ValueError('sections must not be duplicated')
        allowed={f['id'] for f in payload.get('market',{}).get('facts',[])}
        if not set(report['evidence_ids'])<=allowed:raise ValueError('unknown market evidence reference')
        if allowed and not report['evidence_ids']:raise ValueError('use the actual supporting market references')
    except (ValueError,TypeError,KeyError) as exc:
        raise ValueError('Judgment report: '+str(exc)) from None
