"""Loopback-only portfolio setup and separate demo. No broker order route."""
import argparse
import copy
import fcntl
import json
import os
import secrets
import sys
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .agents import DemoModel
from .engine import Engine
from .store import Store
from .connection import status as connection_status
from .onboarding import PortfolioSetup,InputError
from .reporting import present
from .workbench import runs, project
from .dialogue import Dialogues, DialogueError
from .contracts import schema


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
        # Serve the UI from the same process version as its API, even while files are edited.
        self.assets={name:resource('web/'+name).read_text() for name in ['dashboard.html','dashboard.js','report.js','workbench.js','dashboard.css']}
        self.last_error=None
        config=self.directory/'demo-session.json'
        db=Store(self.path)
        if not config.exists():
            private_json(config,{'token':db.create_user('service-demo')})
        self.token=json.loads(config.read_text())['token']
        db.session(self.token)  # fail closed for mismatched database/config
        db.close()
        self.setup=PortfolioSetup(self.directory)
        self.dialogues={'portfolio':Dialogues(self.setup.session,self.setup.analysis_model),
                        'demo':Dialogues(self.demo_session,DemoModel)}

    @contextmanager
    def demo_session(self):
        db=Store(self.path)
        try:yield db.session(self.token)
        finally:db.close()

    def session_for(self,scope):
        if scope not in self.dialogues:raise PermissionError('Scope unavailable')
        return self.setup.session() if scope=='portfolio' else self.demo_session()

    def workbench(self,scope,run_id=None):
        with self.session_for(scope) as s:return project(s,run_id) if run_id else {'runs':runs(s)}

    def recover_after_restart(self):
        # Call only after holding the exclusive process flock. This DB is demo-only.
        db=Store(self.path)
        try: db.session(self.token).recover('Demo service restart under exclusive process lock',date.today().isoformat())
        finally: db.close()
        self.setup.recover()
        for manager in self.dialogues.values():manager.recover()

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
                return {'service':'running','mode':'portfolio','live_trading':False,'onboarding':self.setup.state(),
                    'broker':'toss','broker_connected':broker_status['verified'],'broker_check':broker_status,'error':self.last_error,
                    'today':date.today().isoformat(),'latest':present(s,latest),'trading_limits':limits,
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
                return present(db.session(self.token),row)
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
                    page=app.assets['dashboard.html'].replace('__NONCE__',app.nonce)
                    return self.send(200,page,'text/html; charset=utf-8')
                if self.path=='/dashboard.js': return self.send(200,app.assets['dashboard.js'],'text/javascript; charset=utf-8')
                if self.path=='/report.js': return self.send(200,app.assets['report.js'],'text/javascript; charset=utf-8')
                if self.path=='/workbench.js': return self.send(200,app.assets['workbench.js'],'text/javascript; charset=utf-8')
                if self.path=='/dashboard.css': return self.send(200,app.assets['dashboard.css'],'text/css; charset=utf-8')
                if self.path=='/health': return self.send(200,{'status':'ok','mode':'portfolio','live_trading':False})
                if self.path=='/api/state': return self.send(200,app.state())
                parts=self.path.strip('/').split('/')
                if parts[:2]==['api','contracts'] and len(parts)==3:
                    try:return self.send(200,schema(parts[2]))
                    except (ValueError,OSError):return self.send(404,{'error':'Unknown contract'})
                if parts[:2]==['api','workbench'] and len(parts) in (3,4):
                    return self.send(200,app.workbench(parts[2],parts[3] if len(parts)==4 else None))
                if parts[:2]==['api','dialogue'] and len(parts)==5 and parts[2] in app.dialogues:
                    return self.send(200,app.dialogues[parts[2]].read(parts[3],parts[4]))
                if self.path.startswith('/api/portfolio/report/'): return self.send(200,app.setup.report(self.path.rsplit('/',1)[-1]))
                if self.path.startswith('/api/report/'): return self.send(200,app.report(self.path.rsplit('/',1)[-1]))
                self.send(404,{'error':'Not found'})
            except PermissionError: self.send(404,{'error':'Report unavailable'})
            except Exception: self.send(500,{'error':'Service unavailable'})
        def do_POST(self):
            origin='http://'+self.headers.get('Host','')
            if not self.host_ok() or self.headers.get('Origin')!=origin or self.headers.get('X-Mara-CSRF')!=app.nonce:
                return self.send(403,{'error':'화면이 갱신되었거나 요청 출처를 확인할 수 없어요. 화면을 새로고침한 뒤 다시 시도해주세요.'})
            routes={'/api/setup/draft':app.setup.draft,'/api/setup/model':app.setup.save_model,
                    '/api/setup/generate':app.setup.start,'/api/setup/holdings':lambda body:app.setup.refresh()}
            for scope,manager in app.dialogues.items():routes['/api/dialogue/'+scope]=manager.start
            if self.path not in routes and self.path!='/api/demo-next': return self.send(404,{'error':'No such action'})
            try:
                if self.headers.get('Transfer-Encoding'): raise InputError('지원하지 않는 전송 형식이에요.')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=32768: raise InputError('입력은 32KB 이하로 보내주세요.')
                if self.path=='/api/demo-next':
                    if length: raise InputError('No request body expected')
                    return self.send(200,app.run_demo(next_week=True))
                if self.headers.get_content_type()!='application/json': raise InputError('JSON 입력이 필요해요.')
                self.connection.settimeout(10)
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict): raise InputError('입력 형식을 확인해주세요.')
                self.send(202 if self.path=='/api/setup/generate' or self.path.startswith('/api/dialogue/') else 200,routes[self.path](body))
            except (InputError,DialogueError) as exc: self.send(400,{'error':str(exc)})
            except PermissionError:self.send(404,{'error':'선택한 실행 또는 에이전트를 찾을 수 없어요.'})
            except (ValueError,UnicodeError): self.send(400,{'error':'입력 형식을 확인해주세요.'})
            except Exception: self.send(503,{'error':'처리하지 못했어요. 연결 설정을 확인하고 다시 시도해주세요.'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Persistent local Mara portfolio dashboard; no live trading')
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
    print(f'Mara: http://127.0.0.1:{args.port} (proposals only)',flush=True)
    try: server.serve_forever()
    finally: stop.set(); server.server_close(); lock.close()

if __name__=='__main__': main()
