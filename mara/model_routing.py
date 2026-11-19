"""Frozen per-provider routing policy; never changes evidence, contracts or retry budgets."""
import copy
import hashlib
import json
from pathlib import Path

from .registry import personas

POLICY_PATH=Path(__file__).resolve().parents[3]/'.agents/model-policy.json'
RULES_VERSION = 'mara.routing/2'


def load_policy(path=POLICY_PATH):
    path=Path(path)
    if not path.exists() and path==POLICY_PATH:path=Path(__file__).resolve().parents[1]/'resources/model-routing.json'
    if not path.exists():raise ValueError('Routing policy missing; use an explicit legacy provider only for an audited continuation')
    policy=json.loads(path.read_text())
    for profile in policy['profiles'].values():
        if profile['effort'] not in policy['capabilities'].get(profile['model'],[]):
            raise ValueError('Unsupported configured model/effort')
    if policy.get('max_escalations')!=1:raise ValueError('Routing permits one bounded escalation only')
    return policy


def fingerprint(policy):
    return hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()


def select(policy,role,payload,contract,model='',effort=None):
    # Only structured engine fields/contracts classify work; never instructions in source text.
    tier='standard';reason='ordinary_analysis';selected_effort=None
    strong_model = False
    stage = payload.get('analysis_stage')
    contract_id = contract.get('$id', '')
    if 'calls' in contract.get('properties',{}):
        reason='research_planning'
    elif role=='editor':
        tier='routine';reason='format_existing_validated_report'
    elif role=='context' and (contract_id.endswith('persona-extraction') or contract_id.startswith('urn:mara:persona-extraction:')):
        tier='routine';reason='structured_extraction'
    elif stage in ('final_validation','proposal_synthesis') or role=='evaluator':
        tier='complex';reason='high_impact_synthesis_or_final_review'
    elif role=='validation':
        strong_model=True;selected_effort='high';reason='independent_intermediate_verification'
    else:
        if role == 'leader':
            strong_model=True;reason='portfolio_leadership'
        elif role in personas() or role in ('evidence', 'reflection') or (
            role == 'context' and contract_id.startswith('urn:mara:agent-context:')
        ):
            strong_model=True;reason='substantive_investment_analysis'
        if stage == 'submission_review' or payload.get('revision_instructions') or payload.get('work_items'):
            selected_effort='high';reason+=';bounded_repair_coordination'
    chosen=copy.deepcopy(policy['profiles'][tier])
    if strong_model:
        chosen['model'] = policy['profiles']['complex']['model']
    if selected_effort:chosen['effort']=selected_effort
    feedback=payload.get('output_feedback') or {}
    # Mechanical IDs/schema/size, missing evidence, auth/transport never justify a stronger model.
    diagnostic=feedback.get('decision_policy_error') or {}
    semantic=diagnostic.get('code') in {'hard_gap','future_fact','final_integrity','selected_integrity','symmetric_choices'}
    escalated=False
    if semantic and not effort and chosen['effort']!='high':
        chosen['effort']='high';escalated=True;reason+=';semantic_repair_existing_attempt'
    if model:chosen['model']=model
    if effort:chosen['effort']=effort
    if chosen['effort'] not in policy['capabilities'].get(chosen['model'],[]):
        raise ValueError('Explicit model/effort is not in the verified Codex capability catalog')
    return dict(chosen,policy_version=policy['version'],policy_sha256=fingerprint(policy),routing_rules=RULES_VERSION,
        task_type=tier,reason=reason,escalated=escalated,escalation_limit=1,
        override={'model':bool(model),'effort':bool(effort)},fallback=False,
        retry_policy='No additional call; existing submission/planning budgets are unchanged')
