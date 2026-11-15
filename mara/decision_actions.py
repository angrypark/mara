"""Persisted, idempotent user actions: independent evaluation or dialogue revision."""
import threading
import re
from datetime import date
from .dialogue import DialogueError
from .workbench import run_events
from .engine import Engine
from .output_validation import AgentOutputError
from .evaluation import evaluate_report


class DecisionActions:
    def __init__(self,sessions,models,library=None):
        self.sessions,self.models,self.library=sessions,models,library
        self.guard=threading.RLock();self.thread=None

    def recover(self):
        with self.sessions() as s:
            latest={}
            for e in sorted(s.events('evaluation_status'),key=lambda x:x['seq']):latest[e['run_id']]=e
            for run_id,e in latest.items():
                if e['body']['status']=='running':s.append('evaluation_status',dict(e['body'],status='failed',error_type='InterruptedByRestart'),date.today().isoformat(),run_id)
            done={e['body']['request_id'] for e in s.events('decision_action_result')}
            for e in s.events('decision_action_request'):
                if e['body']['request_id'] not in done:
                    # A completed proposal/evaluation is authoritative even if process stopped before acknowledgement.
                    new=next((x for x in s.events('completed') if (x['body'].get('amendment') or {}).get('request_id')==e['body']['request_id']),None)
                    evaluated=any(x['run_id']==e['run_id'] for x in s.events('report_evaluation')) if e['body']['action']=='evaluate' else False
                    s.append('decision_action_result',{'request_id':e['body']['request_id'],
                        'status':'completed' if new or evaluated else 'interrupted',
                        'new_run_id':new['run_id'] if new else None,
                        'message':'저장된 결과를 복원했어요.' if new or evaluated else '재시작으로 중단됐어요. 원본은 보존됐고 새 요청으로 다시 실행할 수 있어요.'},date.today().isoformat(),e['run_id'])

    def start(self,body):
        if set(body)-{'action','run_id','request_id','dialogue_request_id'} or not {'action','run_id','request_id'}<=body.keys():raise DialogueError('작업 요청 형식을 확인해주세요.')
        if body['action'] not in ('evaluate','revise') or not all(isinstance(body[k],str) for k in body):raise DialogueError('작업 요청 형식을 확인해주세요.')
        if not re.fullmatch('[a-f0-9-]{32,36}',body['request_id']):raise DialogueError('요청 ID를 확인해주세요.')
        with self.guard,self.sessions() as s:
            events=run_events(s,body['run_id']);completed=next((e for e in events if e['kind']=='completed'),None)
            if not completed:raise DialogueError('완료된 제안에서 사용할 수 있어요.')
            old=next((e for e in s.events('decision_action_request') if e['body']['request_id']==body['request_id']),None)
            if old:
                if old['body']['request']!=body:raise DialogueError('같은 요청 ID의 내용이 달라요.')
                return {'accepted':True,'duplicate':True,'request_id':body['request_id']}
            if self.thread and self.thread.is_alive() or s.store.db.execute('SELECT 1 FROM locks WHERE owner=?',(s.owner,)).fetchone():raise DialogueError('진행 중인 분석이 끝난 뒤 다시 시도해주세요.')
            amendment=None
            if body['action']=='revise':
                if s.latest('completed')['id']!=completed['id']:raise DialogueError('더 새로운 제안이 있어요. 최신 제안에서 변경을 반영해주세요.')
                replies=[e for e in events if e['kind']=='dialogue_result' and e['body']['request_id']==body.get('dialogue_request_id') and e['body']['status']=='completed']
                if not replies:raise DialogueError('완료된 대화 답변을 선택해주세요.')
                reply=replies[-1];change=reply['body']['answer'].get('proposed_change')
                if not change or change['scope']!='reasoning':raise DialogueError('이 답변은 적용 가능한 판단 변경이 아니에요. 목표·제약·보유 변경은 투자 설정에서 확인해주세요.')
                req=next(e for e in events if e['kind']=='dialogue_request' and e['body']['request_id']==body['dialogue_request_id'])
                role=req['body']['agent_id'];target={'reflection':'context','memory':'context','evaluator':'leader'}.get(role,role)
                amendment={'schema_version':'mara.amendment/1.0.0','request_id':body['request_id'],
                    'completed_id':completed['id'],'base_run_id':body['run_id'],'agent_id':role,'target_role':target,
                    'dialogue_request_id':body['dialogue_request_id'],'dialogue_result_id':reply['id'],
                    'source_output_id':req['body']['source_output_id'],'user_message':req['body']['message'],
                    'original_role_output':s.get(req['body']['source_output_id'])['body']['output'] if req['body']['source_output_id'] else None,
                    'target_stage':req['body'].get('context',{}).get('role_input',{}).get('analysis_stage') if role=='validation' else None,
                    'change':change,'basis':'frozen_snapshot','recorded_on':date.today().isoformat()}
            request=dict(request=body,action=body['action'],request_id=body['request_id'],completed_id=completed['id'],amendment=amendment)
            s.append('decision_action_request',request,date.today().isoformat(),body['run_id'])
            self.thread=threading.Thread(target=self._work,args=(request,body['run_id']),daemon=True);self.thread.start()
            return {'accepted':True,'duplicate':False,'request_id':body['request_id']}

    def _work(self,req,run_id):
        result={'request_id':req['request_id'],'status':'failed','new_run_id':None}
        with self.sessions() as s:
            try:
                model=self.models()
                if req['action']=='evaluate':
                    s.lock(req['request_id'])
                    try:evaluate_report(s,model,req['completed_id'])
                    finally:s.unlock(req['request_id'])
                else:
                    source=s.get(req['completed_id'])
                    r=Engine(s,model,self.library).run(source['effective'],force=True,
                        revision_reason=req['amendment']['change']['summary'],amendment=req['amendment'])
                    result['new_run_id']=r['run_id']
                result.update(status='completed',message='독립 평가를 저장했어요.' if req['action']=='evaluate' else '변경에 따른 새 판단과 후속 검증을 저장했어요. 원본과 비교해 확인해주세요.')
            except AgentOutputError as exc:
                result.update(error_type=type(exc).__name__,message=exc.message,output_validation=exc.details)
            except Exception as exc:
                result.update(error_type=type(exc).__name__,message='후속 분석이 끝나지 못했어요. 원본 제안은 보존됐어요. 실행 상태와 추가 확인 항목을 확인해주세요.')
            s.append('decision_action_result',result,date.today().isoformat(),run_id)
