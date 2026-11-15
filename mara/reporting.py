"""Read-only presentation assembled from immutable run evidence, including older runs."""
import copy


def present(session,row):
    if row is None:return None
    result=copy.deepcopy(session.get(row['id']));r=result['body']
    if row['kind']!='completed':raise PermissionError('Completed report required')
    market=session.get(r['market_id'])['body'];profile=session.get(r['profile_id'])['body']
    previous=session.get(r['previous_id']) if r.get('previous_id') else None
    prior_market=session.get(previous['body']['market_id'])['body'] if previous else None
    started=session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? AND kind=? ORDER BY seq LIMIT 1',
        (session.owner,r['run_id'],'run_started')).fetchone()
    registry=session.decode(started)['body'].get('agent_registry',[]) if started else []
    analyses={};provenance={};memory=[]
    events=session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? AND kind=? ORDER BY seq',
        (session.owner,r['run_id'],'agent_output')).fetchall()
    for event in events:
        event=session.decode(event);body=event['body'];role=body['role']
        analyses[role]=body['output']
        source=session.get(body['input_id'])['body']
        provenance.setdefault(role,[]).append({'output_id':event['id'],'input_id':body['input_id'],
            'guide_hash':source['guide_hash'],'provider':source['provider']})
        if role=='memory':memory.append(body['output'])
    facts=[f for f in market['facts'] if f['valid_until']>=r['as_of']]
    prices=[]
    for symbol,quote in market['prices'].items():
        before=prior_market['prices'].get(symbol) if prior_market and prior_market['base_currency']==market['base_currency'] else None
        prices.append({'symbol':symbol,'price':quote['price'],'observed_at':quote['observed_at'],
            'source':quote['source'],'previous_price':before['price'] if before else None,
            'previous_observed_at':before['observed_at'] if before else None,
            'price_change':quote['price']/before['price']-1 if before and before['price'] else None})
    result['view']={'version':1,'kind':'revision' if r.get('revision_of') else 'weekly' if previous else 'initial',
        'base_currency':profile['base_currency'],'context':analyses.get('context'),
        'market_analysis':analyses.get('evidence'),'sources':facts,'prices':prices,
        'expired_source_count':len(market['facts'])-len(facts),'agent_records':provenance,'agent_registry':registry,
        'memory':memory,'pruning':session.get(r['pruning_audit_id'])['body'],
        'criteria':{key:profile.get(key) for key in ['goal','horizon_months','cash_need','max_loss_fraction','max_position_fraction','criteria']},
        'previous':{'id':previous['id'],'as_of':previous['effective'],
            'proposal':previous['body']['proposal'],'valuation':previous['body']['valuation'],
            'perspectives':previous['body']['perspectives'],'funding':previous['body'].get('funding')} if previous else None}
    return result
