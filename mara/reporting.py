"""Read-only presentation assembled from immutable run evidence, including older runs."""
import copy


def present(session,row):
    if row is None:return None
    result=copy.deepcopy(session.get(row['id']));r=result['body']
    comparison=r.get('analysis',{}).get('comparison',{})
    if comparison.get('available') and 'sensitivity' not in comparison:
        # Old all-cash results could finish the base comparison then fail the
        # cash-only sensitivity calendar. Preserve originals; display the gap.
        comparison['sensitivity']=[]
        comparison['sensitivity_unavailable_reason']='이 원본 보고서의 추가 민감도 계산은 완료되지 않았어요. 화면에서는 빈 검증 목록으로 표시하며 원본과 점수는 변경하지 않아요.'
    if row['kind']!='completed':raise PermissionError('Completed report required')
    from .history import market_input,profile_input
    boundary=r.get('history_scope',{'after_seq':0,'reset_id':None})
    market=market_input(session.get(r['market_id'])['body'],boundary);profile=profile_input(session.get(r['profile_id'])['body'],boundary)
    previous=session.get(r['previous_id']) if r.get('previous_id') else None
    prior_market=session.get(previous['body']['market_id'])['body'] if previous else None
    started=session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? AND kind=? ORDER BY seq LIMIT 1',
        (session.owner,r['run_id'],'run_started')).fetchone()
    registry=session.decode(started)['body'].get('agent_registry',[]) if started else []
    analyses={};provenance={};memory=[];role_reports={};report_history=[];latest_outputs={}
    accepted={e['body']['output_id'] for e in session.events('agent_validation')
              if e['run_id']==r['run_id'] and e['seq']<=result['seq'] and e['body']['status']=='accepted'}
    events=session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? AND kind=? AND seq<=? ORDER BY seq',
        (session.owner,r['run_id'],'agent_output',result['seq'])).fetchall()
    for event in events:
        event=session.decode(event);body=event['body'];role=body['role']
        if event['id'] in accepted:analyses[role]=body['output']
        source=session.get(body['input_id'])['body']
        stage=source['payload'].get('analysis_stage',role)
        item={'role':role,'stage':stage,'source_output_id':event['id'],'source_input_id':body['input_id'],
              'sequence':event['seq'],'contract_accepted':event['id'] in accepted,
              'feedback':copy.deepcopy(source['payload'].get('output_feedback')),
              'structured_output':copy.deepcopy(body['output']),
              'report':copy.deepcopy(body['output'].get('judgment_report'))}
        report_history.append(item)
        if event['id'] in accepted:
            latest_outputs[(role,stage)]=event['id']
            if item['report']:role_reports[(role,stage)]=item
        provenance.setdefault(role,[]).append({'output_id':event['id'],'input_id':body['input_id'],
            'guide_hash':source['guide_hash'],'provider':source['provider']})
        if role=='memory' and event['id'] in accepted:memory.append(body['output'])
    facts=[f for f in market['facts'] if f['valid_until']>=r['as_of']]
    expired_count=len(market['facts'])-len(facts)
    seen={f['id'] for f in facts}
    for event in session.events('research_evidence'):
        fact=event['body']['fact']
        if event['run_id']==r['run_id'] and event['seq']<=result['seq'] and fact['id'] not in seen and fact['known_at']<=r['as_of'] and fact['published_at']<=r['as_of']<=fact['valid_until']:
            facts.append(copy.deepcopy(fact));seen.add(fact['id'])
    evaluations=[e for e in session.events('report_evaluation') if e['body']['completed_id']==row['id']]
    if evaluations and evaluations[-1]['body']['output'].get('judgment_report'):
        ev=evaluations[-1]['body'];role_reports[('evaluator','evaluator')]={'role':'evaluator','stage':'evaluator',
            'source_output_id':ev['output_id'],'report':copy.deepcopy(ev['output']['judgment_report'])}
    for item in report_history:
        item['latest_accepted_for_stage']=latest_outputs.get((item['role'],item['stage']))==item['source_output_id']
    from .final_report import safe_assemble,verified
    stored=r.get('final_report');valid=verified(stored,r,facts) if stored else False
    reader=copy.deepcopy(stored) if valid else safe_assemble(r,facts)
    reader_status='stored_verified' if valid else 'display_projection' if stored is None else 'invalid_saved_document_projection'
    if stored is not None and not valid:
        reader['assembly_status']='incomplete'
        reader.setdefault('assembly_issues',[]).append({'code':'saved_document_unverified','path':'/final_report'})
        # The displayed projection is a different document; preserve the saved
        # original in body and recompute this projection's own digest.
        from .final_report import digest
        if 'provenance' in reader:
            reader['provenance'].pop('document_sha256',None);reader['provenance']['document_sha256']=digest(reader)
    prices=[]
    for symbol,quote in market['prices'].items():
        before=prior_market['prices'].get(symbol) if prior_market and prior_market['base_currency']==market['base_currency'] else None
        prices.append({'symbol':symbol,'price':quote['price'],'observed_at':quote['observed_at'],
            'source':quote['source'],'previous_price':before['price'] if before else None,
            'previous_observed_at':before['observed_at'] if before else None,
            'price_change':quote['price']/before['price']-1 if before and before['price'] else None})
    from .persona import snapshot
    frozen_persona=snapshot(session.get(r['persona_id'])) if r.get('persona_id') else None
    latest_profile=session.latest('profile')
    result['view']={'user_persona':frozen_persona,'persona_is_current':bool(frozen_persona and latest_profile and latest_profile['id']==r['profile_id']), 'version':1,'kind':'revision' if r.get('revision_of') else 'weekly' if previous else 'initial',
        'base_currency':profile['base_currency'],'context':analyses.get('context'),
        'judgment_reports':list(role_reports.values()),
        'judgment_report_history':report_history,
        'final_report':reader,'final_report_status':reader_status,
        'judgment_report_status':{'available':bool(role_reports),'final_action':r['proposal']['action'],
            'eligibility':r['proposal']['eligibility'],
            'rule':'각 문서는 해당 역할·단계의 원문 의견. 리더 종합안도 최종 검증 전 문서이며 공식 행동·보류 여부는 최종 검증을 반영한 상태가 우선해요.'},
        'market_analysis':analyses.get('evidence'),'sources':facts,'prices':prices,
        'expired_source_count':expired_count,'agent_records':provenance,'agent_registry':registry,
        'memory':memory,'pruning':session.get(r['pruning_audit_id'])['body'],
        'quality_evaluation':evaluations[-1]['body'] if evaluations else None,
        'evaluation_stability':stability_receipt(session,row['id'],evaluations[-1]['body'].get('evaluator_spec_hash') if evaluations else None),
        'risk_budget':r.get('risk_budget'),
        'criteria':{key:profile.get(key) for key in ['goal','horizon_months','cash_need','max_loss_fraction','max_position_fraction','criteria','loss_budget_scope','analysis_loss_budget']},
        'previous':{'id':previous['id'],'as_of':previous['effective'],
            'proposal':previous['body']['proposal'],'valuation':previous['body']['valuation'],
            'perspectives':previous['body']['perspectives'],'funding':previous['body'].get('funding')} if previous else None}
    return result


def stability_receipt(session,completed_id,spec_hash):
    if not completed_id or not spec_hash:return None
    return next((dict(e['body'],source_event_id=e['id'],recorded_at=e['recorded']) for e in reversed(session.events('quality_stability_result')) if e['body'].get('base_completed_id')==completed_id and e['body'].get('evaluator_spec_hash')==spec_hash),None)
