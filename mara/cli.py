import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path
from .agents import DemoModel, HTTPModel, PERSONAS, CONTRACTS
from .domain import dumps, day
from .engine import Engine
from .knowledge import Knowledge
from .feeds import fetch_market
from .store import Store, Session, SHARED


def read(path):
    return json.loads(Path(path).read_text())


def parser():
    p=argparse.ArgumentParser(description='Mara: user-scoped portfolio deliberation, no order execution')
    p.add_argument('--db',default='.local/mara-v1.sqlite3')
    sub=p.add_subparsers(dest='command',required=True)
    u=sub.add_parser('create-user',help='Trusted local operator only; emits token once'); u.add_argument('name')
    for name in ['profile','holdings','cashflow','market','knowledge','shared-knowledge']:
        s=sub.add_parser(name); s.add_argument('file')
        if name in ['profile','knowledge','shared-knowledge']: s.add_argument('--as-of',required=True)
    for name in ['run','tick']:
        s=sub.add_parser(name); s.add_argument('--as-of',required=True); s.add_argument('--market-id')
        s.add_argument('--market-url',help='HTTPS URL of a trusted market pack; local operator only')
        s.add_argument('--demo',action='store_true'); s.add_argument('--force',action='store_true')
    s=sub.add_parser('due'); s.add_argument('--as-of',required=True)
    s=sub.add_parser('report'); s.add_argument('--id')
    s=sub.add_parser('link-portfolio-replay')
    for name in ('report_id','prepared','submission','outcomes'):s.add_argument(name)
    s.add_argument('--comparability',required=True);s.add_argument('--as-of',required=True)
    s=sub.add_parser('export'); s.add_argument('output')
    s=sub.add_parser('prune-shared'); s.add_argument('--as-of',required=True)
    s=sub.add_parser('prune'); s.add_argument('--as-of',required=True)
    from .registry import catalogue
    s=sub.add_parser('role-knowledge')
    s.add_argument('role',choices=[a['id'] for a in catalogue()])
    s.add_argument('--namespace', choices=('model_portfolio',))
    s.add_argument('--as-of',required=True)
    s=sub.add_parser('guide'); s.add_argument('role',choices=list(CONTRACTS)+list(PERSONAS)); s.add_argument('file'); s.add_argument('--reason',required=True); s.add_argument('--as-of',required=True)
    s=sub.add_parser('restore-guide'); s.add_argument('event_id'); s.add_argument('--reason',required=True); s.add_argument('--as-of',required=True)
    s=sub.add_parser('recover'); s.add_argument('--reason',required=True); s.add_argument('--as-of',required=True)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    store=Store(args.db)
    try:
        if args.command=='create-user': result={'user':args.name,'token':store.create_user(args.name)}
        elif args.command=='shared-knowledge': result={'event_id':Knowledge(Session(store,SHARED)).apply(read(args.file),args.as_of)}
        elif args.command=='prune-shared': result={'audit_id':Knowledge(Session(store,SHARED)).prune(args.as_of)}
        elif args.command=='market': result={'market_id':store.publish_market(read(args.file))}
        else:
            token=os.environ.get('MARA_TOKEN')
            if not token: raise PermissionError('MARA_TOKEN required')
            s=store.session(token)
            engine=Engine(s,None)
            c=args.command
            if c=='profile': result={'event_id':engine.set_profile(read(args.file),args.as_of)}
            elif c=='holdings': result={'event_id':engine.set_holdings(read(args.file))}
            elif c=='cashflow': result={'event_id':engine.cashflow(read(args.file))}
            elif c=='due': result=engine.due(args.as_of)
            elif c in {'run','tick'}:
                if c=='tick' and not engine.due(args.as_of)['due']: result={'skipped':'not due'}
                else:
                    if args.market_url:
                        pack=fetch_market(args.market_url)
                        if pack['as_of']!=args.as_of: raise ValueError('Feed date must match requested date')
                        args.market_id=store.publish_market(pack)
                    engine.model=DemoModel() if args.demo else HTTPModel()
                    result=engine.run(args.as_of,args.market_id,args.force)
            elif c=='report':
                result=s.get(args.id) if args.id else s.latest('completed')
                if result is None: raise ValueError('No completed report')
                if result['kind'] in ('completed','model_completed'):
                    from .portfolio_replay import status_for_proposal
                    result['portfolio_replay']=status_for_proposal(s,result['id'])
            elif c=='link-portfolio-replay':
                from .portfolio_replay import link
                result={'event_id':link(s,args.report_id,read(args.prepared),read(args.submission),
                                       read(args.outcomes),args.comparability,args.as_of)}
            elif c=='export':
                path=Path(args.output)
                # Exclusive creation avoids clobbering any preexisting user file.
                fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as f: f.write(dumps(s.export())+'\n')
                result={'export':str(path)}
            elif c=='prune': result={'audit_id':Knowledge(s).prune(args.as_of)}
            elif c=='role-knowledge':
                items = Knowledge(s,namespace=args.namespace).current(args.as_of)
                result={'role':args.role,'items':[item for item in items.values()
                                                  if item.get('owner_role')==args.role]}
            elif c=='knowledge': result={'event_id':Knowledge(s).apply(read(args.file),args.as_of)}
            elif c in {'guide','restore-guide'}:
                if not args.reason.strip(): raise ValueError('Reason required')
                if c=='guide': role,text=args.role,Path(args.file).read_text()
                else:
                    old=s.get(args.event_id)
                    if old['kind']!='guide': raise ValueError('Not a guide version')
                    role,text=old['body']['role'],old['body']['text']
                if not text.strip() or len(text)>22000: raise ValueError('Invalid guide length')
                versions=[e for e in s.events('guide') if e['body']['role']==role]
                result={'event_id':s.append('guide',{'role':role,'text':text,'reason':args.reason,
                   'version':len(versions)+1,'restored_from':getattr(args,'event_id',None)},args.as_of)}
            else: s.recover(args.reason,args.as_of); result={'recovered':True}
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (urllib.error.URLError, TimeoutError) as exc:
        print('Provider/feed unavailable; no completed proposal was published. Check connectivity and configuration.',file=sys.stderr)
        return 3
    except (ValueError,KeyError,PermissionError,RuntimeError) as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        return 2
    finally: store.close()


if __name__=='__main__': sys.exit(main())
