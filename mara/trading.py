"""User-run execution code. Installed dashboard never imports or invokes this module."""
import argparse
import fcntl
import hashlib
import json
import os
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN,InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from .store import Store
from .toss import TossClient,secret_config
from .domain import dumps


def dec(v):
    try: n=Decimal(str(v))
    except InvalidOperation: raise ValueError('Invalid decimal')
    if not n.is_finite() or n<0: raise ValueError('Expected nonnegative finite decimal')
    return n


def instant(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('Timezone required')
    return t


def fresh(value,now,seconds):
    age=(now-instant(value)).total_seconds()
    if not 0<=age<=seconds: raise ValueError('Stale or future broker evidence')


def validate_policy(policy):
    if policy.get('market')!='US': raise ValueError('This execution adapter supports US stocks only')
    for k in ['max_order_krw','max_daily_krw','max_capital_krw']:
        if policy.get(k) is None or dec(policy[k])<=0: raise ValueError('Configure '+k)
    if not policy.get('allowed_symbols'): raise ValueError('Configure allowed_symbols')
    if not 0<=dec(policy.get('fee_buffer_fraction','0.01'))<=Decimal('0.1'): raise ValueError('Invalid fee buffer')
    return policy


def build_plan(report,actual,snapshot,policy,now):
    validate_policy(policy)
    p=report['proposal']
    if p['action'] not in {'hold','adjust'} or p['eligibility']!='review_now': raise ValueError('Proposal not eligible now')
    if report['mode']!='live': raise ValueError('Synthetic proposals cannot produce broker orders')
    if actual['base_currency']!='USD': raise ValueError('Use a USD portfolio with confirmed USD cash')
    if report['as_of']!=now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat(): raise ValueError('Same-day report required')
    fresh(snapshot['captured_at'],now,120)
    if snapshot['open_orders']['orders'] or snapshot['open_orders'].get('hasNext'): raise ValueError('Existing broker orders require reconciliation first')
    session=snapshot['calendar']['today'].get('regularMarket')
    if not session or not instant(session['startTime'])<=now<instant(session['endTime']): raise ValueError('US regular market only')
    fx=snapshot['fx']
    if fx['baseCurrency']!='USD' or fx['quoteCurrency']!='KRW' or not instant(fx['validFrom'])<=now<instant(fx['validUntil']):
        raise ValueError('Valid USD/KRW quote required')
    rate=max(dec(fx['rate']),dec(fx['midRate']))
    if rate<=0: raise ValueError('Positive FX rate required')
    quotes={q['symbol']:q for q in snapshot['prices']}
    stocks={s['symbol']:s for s in snapshot['stocks']}
    broker={h['symbol']:dec(h['quantity']) for h in snapshot['holdings']['items'] if dec(h['quantity'])}
    recorded={s:dec(q) for s,q in actual['positions'].items() if dec(q)}
    if broker!=recorded: raise ValueError('Reconcile actual holdings before planning')
    symbols=(set(p['weights'])|set(recorded))-{'CASH'}
    if not symbols<=set(policy['allowed_symbols']): raise ValueError('Symbol outside configured universe')
    for symbol in symbols:
        q=quotes[symbol]; info=stocks[symbol]
        fresh(q['timestamp'],now,60)
        if q['currency']!='USD' or info['currency']!='USD' or info['market'] not in {'NYSE','NASDAQ','AMEX','US_ETC'} or info['status']!='ACTIVE':
            raise ValueError('Unsupported stock or currency')
        if info.get('leverageFactor') is not None and dec(info['leverageFactor'])!=1: raise ValueError('Leveraged products excluded')
        if dec(q['lastPrice'])<=0: raise ValueError('Positive price required')
    nav=dec(actual['cash'])+sum((recorded.get(s,Decimal(0))*dec(quotes[s]['lastPrice']) for s in symbols),Decimal(0))
    if nav*rate>dec(policy['max_capital_krw']): raise ValueError('Portfolio exceeds capital limit')
    if p['action']=='hold': return {'orders':[],'gross_krw':'0','account_seq':snapshot['account_seq'],
            'report_id':report['event_id'],'created_at':now.isoformat(),'valid_until':fx['validUntil'],'mode':'dry-run'}
    if abs(sum(dec(w) for w in p['weights'].values())-1)>Decimal('0.000001'): raise ValueError('Invalid target weights')
    buffer=1+dec(policy.get('fee_buffer_fraction','0.01'))
    orders=[]; buy_total=Decimal(0); gross=Decimal(0)
    for symbol in sorted(symbols):
        price=dec(quotes[symbol]['lastPrice'])
        target=(nav*dec(p['weights'].get(symbol,0))/price).to_integral_value(rounding=ROUND_DOWN)
        delta=target-recorded.get(symbol,Decimal(0))
        qty=abs(delta).to_integral_value(rounding=ROUND_DOWN)
        if not qty: continue
        side='BUY' if delta>0 else 'SELL'
        # Limit at reference price; no automatic chase. Exchange precision follows official spec.
        limit=price.quantize(Decimal('0.01') if price>=1 else Decimal('0.0001'),rounding=ROUND_DOWN)
        if side=='SELL' and qty>dec(snapshot['sellable'][symbol]): raise ValueError('Insufficient sellable quantity')
        notional=qty*limit*rate*buffer
        if notional>dec(policy['max_order_krw']): raise ValueError('Order exceeds KRW limit; revise target, never split to bypass')
        gross+=notional
        if side=='BUY': buy_total+=qty*limit*buffer
        orders.append({'symbol':symbol,'side':side,'orderType':'LIMIT','timeInForce':'DAY',
                       'quantity':str(qty),'price':str(limit),'notional_krw':str(notional)})
    if gross>dec(policy['max_daily_krw']): raise ValueError('Plan exceeds daily KRW limit')
    if buy_total>dec(snapshot['buying_power']['cashBuyingPower']): raise ValueError('Insufficient settled buying power; sell proceeds not assumed')
    return {'orders':sorted(orders,key=lambda o:o['side']=='BUY'),'gross_krw':str(gross),
            'account_seq':snapshot['account_seq'],'fx_rate':str(rate),'created_at':now.isoformat(),
            'report_id':report['event_id'],'mode':'dry-run','valid_until':min(instant(fx['validUntil']),instant(session['endTime'])).isoformat()}


class Executor:
    """Durable intent before submit. Ambiguous requests stop, never automatically retransmit."""
    def __init__(self,session,broker,policy,kill_file,clock=None):
        self.s,self.broker,self.policy,self.kill=session,broker,validate_policy(policy),Path(kill_file)
        self.clock=clock or (lambda: datetime.now(timezone.utc))

    def execute(self,plan,now):
        if self.kill.exists(): raise ValueError('STOP file is present')
        if self.policy.get('live_enabled') is not True: raise ValueError('Live execution is disabled')
        fresh(plan['created_at'],now,60)
        if plan['account_seq']!=self.broker.account or plan['account_seq']!=self.policy.get('account_seq'):
            raise ValueError('Account mismatch')
        day=now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
        # All modes of the same broker account must share this local ledger and process lock.
        history=[self.s.decode(r) for r in self.s.store.db.execute("SELECT * FROM events WHERE kind='broker_intent' ORDER BY seq").fetchall()]
        history=[e for e in history if e['body']['account_seq']==self.broker.account]
        statuses={}
        for row in self.s.store.db.execute("SELECT * FROM events WHERE kind='broker_status' ORDER BY seq").fetchall():
            event=self.s.decode(row)['body']
            if event.get('intent_id'): statuses[event['intent_id']]=event['order']['status']
        if any(statuses.get(e['id']) not in {'FILLED','CANCELED','REJECTED'} for e in history):
            raise ValueError('Unresolved broker intent: reconcile before new orders')
        if any(e['body']['report_id']==plan['report_id'] for e in history): raise ValueError('Report already submitted or ambiguous; reconcile without replay')
        used=sum((dec(e['body']['notional_krw']) for e in history if e['effective']==day),Decimal(0))
        if used+dec(plan['gross_krw'])>dec(self.policy['max_daily_krw']): raise ValueError('Daily ledger limit exceeded')
        outputs=[]
        for i,order in enumerate(plan['orders']):
            current=self.clock()
            if current.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()!=day: raise ValueError('Trading day changed; re-plan with new daily budget')
            fresh(plan['created_at'],current,60)
            if current>=instant(plan['valid_until']): raise ValueError('FX or market session expired')
            quote=self.broker.prices([order['symbol']])[0]
            fresh(quote['timestamp'],current,60)
            if quote['currency']!='USD' or abs(dec(quote['lastPrice'])/dec(order['price'])-1)>Decimal('0.005'):
                raise ValueError('Price moved; create a new analysis rather than chase')
            if self.kill.exists(): raise ValueError('STOP file is present')
            if dec(order['notional_krw'])>dec(self.policy['max_order_krw']): raise ValueError('Order limit exceeded')
            if self.broker.open_orders()['orders']: raise ValueError('Pending order; stop and reconcile')
            if order['side']=='BUY' and dec(order['quantity'])*dec(order['price'])*(1+dec(self.policy.get('fee_buffer_fraction','0.01')))>dec(self.broker.buying_power()['cashBuyingPower']): raise ValueError('Buying power changed')
            if order['side']=='SELL' and dec(order['quantity'])>dec(self.broker.sellable(order['symbol'])['sellableQuantity']): raise ValueError('Sellable quantity changed')
            payload={k:v for k,v in order.items() if k!='notional_krw'}
            key=hashlib.sha256((self.s.owner+str(self.broker.account)+plan['report_id']+str(i)).encode()).hexdigest()[:32]
            payload['clientOrderId']=key
            eid=self.s.append('broker_intent',{'report_id':plan['report_id'],'account_seq':self.broker.account,
                'notional_krw':order['notional_krw'],'payload':payload,'created_at':now.isoformat()},day)
            try:
                result=self.broker.submit(payload)  # once only; no transport retry
                if not result.get('orderId'): raise ValueError('Missing acknowledgement')
            except Exception:
                self.s.append('broker_unknown',{'intent_id':eid,'reason':'Submission outcome unknown. No automatic retry.'},day)
                raise RuntimeError('Order outcome unknown; reconcile in broker before further actions') from None
            self.s.append('broker_ack',{'intent_id':eid,'order_id':result['orderId']},day)
            status=self.broker.order(result['orderId'])
            self.s.append('broker_status',{'intent_id':eid,'order':status},day)
            outputs.append(status)
            # Partial, pending, canceled or unknown statuses never masquerade as a full fill.
            if status['status']!='FILLED': break
        return outputs


def main(argv=None):
    p=argparse.ArgumentParser(description='User-operated Toss integration; default is read-only/dry-run')
    p.add_argument('--credentials',default='.local/toss/credentials.json')
    p.add_argument('--policy',default='.local/toss/policy.json')
    p.add_argument('--db',default='.local/mara-v1.sqlite3')
    p.add_argument('action',choices=['accounts','snapshot','plan','execute','reconcile'])
    p.add_argument('--report-id'); p.add_argument('--order-id'); p.add_argument('--intent-id')
    args=p.parse_args(argv)
    root=Path(args.credentials).resolve().parent
    # Lock all account commands for this credential directory across processes.
    fd=os.open(str(root/'operator.lock'),os.O_WRONLY|os.O_CREAT,0o600)
    with os.fdopen(fd,'w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        config=secret_config(args.credentials)
        broker=TossClient(config,root/'access-token.json')
        policy=json.loads(Path(args.policy).read_text())
        now=datetime.now(timezone.utc)
        if args.action=='accounts':
            print(dumps([{'account_seq':a['accountSeq'],'type':a['accountType'],'account_suffix':a['accountNo'][-4:]} for a in broker.accounts()])); return
        db=Store(args.db)
        try:
            session=db.session(os.environ['MARA_TOKEN'])
            if args.action=='reconcile':
                if not args.order_id: raise ValueError('--order-id required; do not replay an unknown order')
                status=broker.order(args.order_id)
                if not args.intent_id: raise ValueError('--intent-id required to reconcile a recorded submission')
                intent=session.get(args.intent_id)
                if intent['kind']!='broker_intent' or intent['body']['account_seq']!=broker.account: raise ValueError('Intent/account mismatch')
                original=intent['body']['payload']
                if any(status[key]!=original[key] for key in ['symbol','side']) or dec(status['quantity'])!=dec(original['quantity']): raise ValueError('Order does not match recorded intent')
                session.append('broker_status',{'manual_reconciliation':True,'intent_id':args.intent_id,'order':status},now.date().isoformat())
                print(dumps(status)); return
            snapshot=broker.snapshot(policy['allowed_symbols'],now)
            sid=session.append('broker_snapshot',snapshot,now.date().isoformat())
            if args.action=='snapshot': print(dumps({'snapshot_id':sid,'account_seq':broker.account})); return
            row=session.get(args.report_id) if args.report_id else session.latest('completed')
            if not row or row['kind']!='completed': raise ValueError('Completed live report required')
            report=dict(row['body'],event_id=row['id'])
            actual=session.get(report['actual_id'])['body']
            plan=build_plan(report,actual,snapshot,policy,datetime.now(timezone.utc))
            session.append('broker_plan',dict(plan,snapshot_id=sid),now.date().isoformat())
            if args.action=='plan': print(dumps(plan)); return
            # No command in the service calls execute. Only a user's separate explicit CLI can.
            print(dumps(Executor(session,broker,policy,root/'STOP').execute(plan,datetime.now(timezone.utc))))
        finally: db.close()

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc))
        raise SystemExit(2)
