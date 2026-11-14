"""Loopback-only demo service. Intentionally has no broker order route or live worker."""
import argparse
import copy
import fcntl
import json
import os
import secrets
import sys
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .agents import DemoModel
from .engine import Engine
from .store import Store
from .connection import status as connection_status


def resource(relative):
    root=Path(__file__).resolve().parent.parent
    path=root/relative
    return path if path.exists() else Path(sys.prefix)/'share/mara'/relative


def private_json(path, value):
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: json.dump(value,f)


class Application:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.directory/'demo.sqlite3'
        self.mutex=threading.RLock()
        self.nonce=secrets.token_urlsafe(32)
        self.last_error=None
        config=self.directory/'demo-session.json'
        db=Store(self.path)
        if not config.exists():
            private_json(config,{'token':db.create_user('service-demo')})
        self.token=json.loads(config.read_text())['token']
        db.session(self.token)  # fail closed for mismatched database/config
        db.close()

    def recover_after_restart(self):
        # Call only after holding the exclusive process flock. This DB is demo-only.
        db=Store(self.path)
        try: db.session(self.token).recover('Demo service restart under exclusive process lock',date.today().isoformat())
        finally: db.close()

    def run_demo(self, next_week=False):
        with self.mutex:
            db=Store(self.path)
            try:
                s=db.session(self.token); e=Engine(s,DemoModel()); last=s.latest('completed')
                as_of=date.today()
                if last:
                    due=date.fromisoformat(last['body']['next_evaluation'])
                    if next_week: as_of=due
                    elif as_of<due: return {'skipped':'not due'}
                p=json.loads(resource('examples/profile.json').read_text())
                h=json.loads(resource('examples/holdings.json').read_text())
                m=json.loads(resource('examples/market.json').read_text())
                day=as_of.isoformat()
                if not last:
                    p['cash_need_date']=(as_of+timedelta(days=180)).isoformat()
                    e.set_profile(p,day)
                h['as_of']=day
                h['last_rebalanced']=s.latest('actual')['body']['last_rebalanced'] if last else day
                e.set_holdings(h)
                m['as_of']=day; m['synthetic']=True
                for q in m['prices'].values(): q.update(observed_at=day,known_at=day)
                for f in m['facts']: f.update(published_at=day,known_at=day,valid_until=(as_of+timedelta(days=7)).isoformat())
                result=e.run(day,db.publish_market(m)); self.last_error=None
                return {'event_id':result['event_id'],'as_of':day}
            except Exception as exc:
                self.last_error=type(exc).__name__
                raise
            finally: db.close()

    def state(self):
        with self.mutex:
            db=Store(self.path)
            try:
                s=db.session(self.token)
                reports=s.events('completed')
                latest=reports[-1] if reports else None
                limits={}
                policy_path=self.directory.parent/'toss/policy.json'
                if policy_path.exists():
                    policy=json.loads(policy_path.read_text())
                    limits={key:policy.get(key) for key in ['market','max_capital_krw','max_order_krw','max_daily_krw']}
                broker_status=connection_status(self.directory.parent/'toss')
                return {'service':'running','mode':'demo','live_trading':False,
                    'broker':'toss','broker_connected':broker_status['verified'],'broker_check':broker_status,'error':self.last_error,
                    'today':date.today().isoformat(),'latest':latest,'trading_limits':limits,
                    'history':[{'id':e['id'],'as_of':e['effective'],'action':e['body']['proposal']['action']}
                               for e in reversed(reports[-40:])],
                    'knowledge_count':len(s.events('knowledge'))}
            finally: db.close()

    def report(self, eid):
        with self.mutex:
            db=Store(self.path)
            try:
                row=db.session(self.token).get(eid)
                if row['kind']!='completed': raise PermissionError('Report required')
                return row
            finally: db.close()


def make_server(app,port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # never log query strings, secrets or user records
        def send(self,code,body,content_type='application/json; charset=utf-8'):
            data=body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'nonce-"+app.nonce+"'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(data)
        def host_ok(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        def do_GET(self):
            if not self.host_ok(): return self.send(403,{'error':'Invalid host'})
            try:
                if self.path=='/':
                    page=resource('web/dashboard.html').read_text().replace('__NONCE__',app.nonce)
                    return self.send(200,page,'text/html; charset=utf-8')
                if self.path=='/health': return self.send(200,{'status':'ok','mode':'demo','live_trading':False})
                if self.path=='/api/state': return self.send(200,app.state())
                if self.path.startswith('/api/report/'): return self.send(200,app.report(self.path.rsplit('/',1)[-1]))
                self.send(404,{'error':'Not found'})
            except PermissionError: self.send(404,{'error':'Report unavailable'})
            except Exception: self.send(500,{'error':'Service unavailable'})
        def do_POST(self):
            origin='http://'+self.headers.get('Host','')
            if not self.host_ok() or self.headers.get('Origin')!=origin or self.headers.get('X-Mara-CSRF')!=app.nonce:
                return self.send(403,{'error':'Same-origin action required'})
            if self.path!='/api/demo-next': return self.send(404,{'error':'No such action'})
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length','0')!='0':
                return self.send(400,{'error':'No request body expected'})
            try: self.send(200,app.run_demo(next_week=True))
            except Exception: self.send(500,{'error':'Demo execution failed; inspect local state'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Persistent local Mara demo dashboard; no live trading')
    parser.add_argument('--directory',default='.local/service')
    parser.add_argument('--port',type=int,default=8788)
    args=parser.parse_args(argv)
    directory=Path(args.directory); directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=open(directory/'process.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    app=Application(directory)
    app.recover_after_restart()
    server=make_server(app,args.port)
    stop=threading.Event()
    def worker():
        while not stop.is_set():
            try: app.run_demo()
            except Exception: pass  # error type appears in state; no hidden fallback
            stop.wait(60)
    thread=threading.Thread(target=worker,daemon=True); thread.start()
    print(f'Mara: http://127.0.0.1:{args.port} (demo only)',flush=True)
    try: server.serve_forever()
    finally: stop.set(); server.server_close(); lock.close()

if __name__=='__main__': main()
