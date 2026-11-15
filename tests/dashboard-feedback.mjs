// DOM regression tests: trusted repository HTML, fake HTTP, no broker/model requests.
// Setup: npm install --prefix .local/test-ui --no-save --ignore-scripts happy-dom@15.11.7
// Run: node tests/dashboard-feedback.mjs (Node >=20; no production dependency).
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Window } from '../.local/test-ui/node_modules/happy-dom/lib/index.js';

const html=await readFile(new URL('../web/dashboard.html',import.meta.url),'utf8');
const reportScript=await readFile(new URL('../web/report.js',import.meta.url),'utf8');
const clarificationScript=await readFile(new URL('../web/clarifications.js',import.meta.url),'utf8');
const script=await readFile(new URL('../web/dashboard.js',import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function settle(){await tick();await tick();await tick()}
function fixture(){return {service:'running',broker_connected:true,broker_check:{},latest:null,onboarding:{
  capital_limit:30000000,model:{configured:true,model:'test-only'},history:[],latest:null,job:null,
  snapshot:{id:'snapshot-test',captured_at:'2026-11-14T10:00:00Z',items:[],excluded_count:0,sectors:[]},
  draft:{goal:'Test goal',horizon_months:120,total_assets:30000000,capital_mode:'total',capital_amount:1000000,
    contribution_amount:0,contribution_every_days:30,rebalance_every_days:90,monthly_income:3000000,
    monthly_expenses:1000000,cash_need:100000,cash_need_date:'2099-01-01',risk_level:'balanced',
    max_loss_fraction:0,max_position_fraction:0,max_sector_fraction:0,max_equity_fraction:0,
    min_cash_fraction:0,max_foreign_fraction:0,cash_krw:1000000,cash_usd:0,
    last_rebalanced:'2026-11-14',rationale:'Test holdings',snapshot_id:'snapshot-test'}}}}

async function setup(change=()=>{},generation=()=>({job_id:'new-job',status:'running'})){
  const state=fixture();change(state);const calls=[];
  const w=new Window({url:'http://127.0.0.1:8788',settings:{
    disableJavaScriptFileLoading:true,disableCSSFileLoading:true,disableIframePageLoading:true}});
  // The DOM runner has no layout/scroll engine. Focus and target links still use real DOM nodes.
  w.HTMLElement.prototype.scrollIntoView=function(){};
  w.setInterval=()=>0;
  w.fetch=async(path,options)=>{
    calls.push({path,body:options?.body?JSON.parse(options.body):null});
    if(path==='/api/state')return {ok:true,json:async()=>structuredClone(state)};
    if(path==='/api/setup/answers'){
      const request=JSON.parse(options.body),a=request.answers[0],q=state.onboarding.job.structured_questions.find(q=>q.id===a.question_id);
      const row={...a,answer_id:'answer-'+calls.length,recorded_at:new Date().toISOString(),question:q,source_output_id:request.context_output_id,answer:a.text||q.options.find(o=>o.id===a.option_id).label};
      state.onboarding.clarification_answers=[...(state.onboarding.clarification_answers||[]).filter(x=>x.question_id!==a.question_id),row];
      return {ok:true,json:async()=>({saved:true,answers:structuredClone(state.onboarding.clarification_answers)})};
    }
    if(path==='/api/setup/draft')return {ok:true,json:async()=>({saved:true})};
    if(path==='/api/setup/model'){
      const config=JSON.parse(options.body);
      state.onboarding.model={provider:config.provider,model:config.model,configured:true,
        codex:{installed:true,authenticated:true,compatible:true,version:'test-version'}};
      return {ok:true,json:async()=>structuredClone(state.onboarding.model)};
    }
    if(path==='/api/setup/generate'){
      const result=generation(state);
      return {ok:!result.error,json:async()=>result};
    }
    throw new Error('Unexpected HTTP request: '+path);
  };
  w.document.write(html.replace(/<script[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link[^>]*>/g,''));
  w.eval(reportScript);w.eval(clarificationScript);w.eval(script+'\nwindow.__testPoll=load;');await settle();
  const $=id=>w.document.getElementById(id),form=$('setup-form');
  form.elements.namedItem('confirmed').checked=true;
  return {w,state,calls,$,form,submit:async()=>{form.requestSubmit();await settle()},poll:async()=>{await w.__testPoll();await settle()},close:()=>w.happyDOM.close()};
}
const cases=[];
function test(name,run){cases.push({name,run})}

test('missing model gives inline, persistent guidance and preserves input',async()=>{
  const h=await setup(s=>{s.onboarding.model={configured:false,model:null}});
  try{
    await h.submit();
    assert.equal(h.$('generate-feedback').hidden,false);
    assert.equal(h.$('generate-feedback').getAttribute('role'),'alert');
    assert.match(h.$('generate-issues').textContent,/분석 모델이 설정되지/);
    assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,0);
    assert.equal(h.calls.find(x=>x.path==='/api/setup/draft').body.goal,'Test goal');
    await h.poll();assert.match(h.$('generate-issues').textContent,/모델 ID와 API 키/);
    h.$('generate-issues').querySelector('button').click();
    assert.equal(h.$('model-settings').open,true);
    assert.equal(h.w.document.activeElement.id,'model-id');
    assert.equal(h.$('generate').disabled,false);
  }finally{await h.close()}
});

test('native required and step errors show at the button and link to inputs',async()=>{
  const h=await setup();
  try{
    h.form.elements.namedItem('goal').value='';
    h.form.elements.namedItem('max_sector_fraction').value='30.15';
    h.form.elements.namedItem('confirmed').checked=false;
    await h.submit();
    assert.equal(h.form.noValidate,true);
    const message=h.$('generate-issues').textContent;
    assert.match(message,/투자 목표.*필수/);assert.match(message,/0.1 단위/);assert.match(message,/보유·현금 확인/);
    assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,0);
    h.$('generate-issues').querySelector('button').click();
    assert.equal(h.w.document.activeElement.name,'goal');
  }finally{await h.close()}
});

test('server rejection remains next to the button after status polling',async()=>{
  const h=await setup(()=>{},()=>({error:'보유 수량이 바뀌었어요. 다시 확인해주세요.'}));
  try{
    await h.submit();assert.match(h.$('generate-message').textContent,/보유 수량/);
    assert.equal(h.$('generate-feedback').dataset.kind,'error');
    await h.poll();assert.match(h.$('generate-message').textContent,/보유 수량/);
    assert.equal(h.$('generate').disabled,false);
    assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
  }finally{await h.close()}
});

test('request, progress, failure, retry and completion stay visible',async()=>{
  const h=await setup(()=>{},s=>{s.onboarding.job={id:'new-job',status:'running',message:'독립 관점 분석 중'};return {job_id:'new-job',status:'running'}});
  try{
    await h.submit();assert.match(h.$('generate-message').textContent,/독립 관점/);
    assert.equal(h.$('generate').disabled,true);assert.match(h.$('generate').textContent,/분석 중/);
    await h.submit();assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
    h.state.onboarding.job={id:'new-job',status:'failed',message:'모델 호출에 실패했어요.'};
    await h.poll();assert.match(h.$('generate-message').textContent,/모델 호출/);
    assert.equal(h.$('generate-feedback').dataset.kind,'error');assert.equal(h.$('generate').disabled,false);
    await h.submit();assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,2);
    h.state.onboarding.job={id:'new-job',status:'completed',message:'제안을 저장했어요.'};
    await h.poll();assert.equal(h.$('generate-feedback').dataset.kind,'success');
    assert.match(h.$('generate-issues').textContent,/제안과 평가 결과 보기/);
    assert.equal(h.$('generate').disabled,false);
  }finally{await h.close()}
});

test('network error during submit is visible and does not erase input',async()=>{
  const h=await setup();
  try{
    h.w.fetch=async()=>{throw new Error('Network unavailable')};
    await h.submit();assert.match(h.$('generate-message').textContent,/Network unavailable/);
    assert.equal(h.form.elements.namedItem('goal').value,'Test goal');
    assert.equal(h.$('generate').disabled,false);
  }finally{await h.close()}
});

test('Codex selection hides API key, saves without it, and enables generation',async()=>{
  const h=await setup(s=>{s.onboarding.model={provider:'openai',configured:false,model:null}});
  try{
    await h.submit();assert.match(h.$('generate-issues').textContent,/분석 모델이 설정되지/);
    h.$('model-provider').value='codex';h.$('model-provider').dispatchEvent(new h.w.Event('change'));
    assert.equal(h.$('api-key-field').hidden,true);
    h.$('model-key').value='must-not-send';h.$('model-id').value='';
    h.$('save-model').click();await settle();
    const request=h.calls.find(x=>x.path==='/api/setup/model');
    assert.deepEqual(request.body,{provider:'codex',model:''});
    assert.match(h.$('model-status').textContent,/Codex 실행 준비됨/);
    assert.doesNotMatch(h.$('generate-issues').textContent,/분석 모델이 설정되지/);
    assert.equal(h.$('generate-feedback').dataset.kind,'success');
    assert.match(h.$('generate-prerequisite').textContent,/Codex로/);
    await h.submit();assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
  }finally{await h.close()}
});

function contextFixture(s){
  s.onboarding.job={id:'context-job',context_output_id:'output-1',status:'needs_input',message:'확인이 필요해요.',
    structured_questions:[{id:'funding_source',prompt:'추가 자금의 출처는 무엇인가요?',reason:'차입 여부를 확인해요.',revisit_reason:'',options:[
      {id:'savings',label:'별도 저축',description:'차입하지 않은 자금',requires_text:false},
      {id:'other',label:'다른 출처',description:'출처를 적어주세요.',requires_text:true}]},
      {id:'funding_timing',prompt:'언제 투입할 계획인가요?',reason:'투입 시점을 확인해요.',revisit_reason:'',options:[
      {id:'now',label:'지금 가능해요',description:'현재 준비된 자금',requires_text:false},
      {id:'later',label:'추후 투입해요',description:'날짜를 알려주세요.',requires_text:true}]}]};
}
test('one stable choice panel keeps focus and drafts on polling, saves sequentially and resumes',async()=>{
  const h=await setup(contextFixture,s=>{s.onboarding.job={id:'new-job',status:'running',message:'분석 중'};return {job_id:'new-job',status:'running'}});
  try{
    assert.equal(h.$('context-requests').hidden,false);assert.equal(h.$('generation-actions').hidden,true);
    assert.equal(h.$('generate-feedback').hidden,true);assert.equal(h.$('answer-context'),null);
    assert.equal(h.$('context-card').querySelector('input:checked'),null);
    const textarea=h.$('context-answer');textarea.value='매달 모은 자금';textarea.focus();
    await h.poll();assert.equal(h.$('context-answer'),textarea);assert.equal(h.w.document.activeElement,textarea);assert.equal(textarea.value,'매달 모은 자금');
    h.$('context-card').querySelector('input[value=savings]').click();h.$('context-next').click();await settle();
    assert.equal(h.$('context-progress').textContent,'2 / 2');assert.equal(h.calls.filter(x=>x.path==='/api/setup/answers').length,1);
    h.$('context-back').click();assert.equal(h.$('context-answer').value,'매달 모은 자금');
    h.$('context-next').click();await settle();assert.equal(h.calls.filter(x=>x.path==='/api/setup/answers').length,1);
    h.$('context-card').querySelector('input[value=later]').click();h.$('context-next').click();await settle();
    assert.match(h.$('context-feedback').textContent,/구체적인 설명/);
    h.$('context-answer').value='2027년 3월';h.$('context-next').click();await settle();await settle();
    assert.equal(h.calls.filter(x=>x.path==='/api/setup/answers').length,2);
    assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
    assert.equal(h.$('context-requests').hidden,true);assert.equal(h.$('context-memory').hidden,false);
    assert.match(h.$('context-memory-list').textContent,/2027년 3월/);
    const draft=h.calls.find(c=>c.path==='/api/setup/draft').body;assert.equal(draft['context-choice'],undefined);
  }finally{await h.close()}
});

test('saved answers restore after reload; failed resume preserves them and one question panel',async()=>{
  const h=await setup(s=>{contextFixture(s);s.onboarding.job.structured_questions=s.onboarding.job.structured_questions.slice(0,1)},()=>({error:'보유 확인이 필요해요.'}));
  try{
    h.$('context-card').querySelector('input[value=savings]').click();h.$('context-next').click();await settle();await settle();
    assert.equal(h.state.onboarding.clarification_answers.length,1);assert.match(h.$('generate-message').textContent,/보유 확인/);
    assert.equal(h.$('context-requests').hidden,false);assert.match(h.$('context-memory-list').textContent,/별도 저축/);
    const h2=await setup(s=>Object.assign(s,structuredClone(h.state)));
    try{assert.equal(h2.$('context-card').querySelector('input:checked').value,'savings');assert.match(h2.$('context-memory-title').textContent,/답변 1개/)}finally{await h2.close()}
    h.$('context-next').click();await settle();assert.equal(h.calls.filter(x=>x.path==='/api/setup/answers').length,1);
  }finally{await h.close()}
});

test('unknown network outcome retries same request ID and leaves direct input editable',async()=>{
  const h=await setup(contextFixture);const fetch=h.w.fetch;let tries=0,requests=[];
  h.w.fetch=async(path,opts)=>{if(path==='/api/setup/answers'){requests.push(JSON.parse(opts.body));if(++tries===1)throw new Error('응답 연결 끊김')}return fetch(path,opts)};
  try{
    h.$('context-answer').value='직접 마련한 저축';h.$('context-next').click();await settle();
    assert.match(h.$('context-feedback').textContent,/연결 끊김/);assert.equal(h.$('context-answer').value,'직접 마련한 저축');
    h.$('context-next').click();await settle();assert.equal(requests[0].request_id,requests[1].request_id);assert.equal(h.$('context-progress').textContent,'2 / 2');
  }finally{await h.close()}
});

test('reconfirmation shows prior answer but never preselects changed option meaning',async()=>{
  const h=await setup(s=>{contextFixture(s);const q=structuredClone(s.onboarding.job.structured_questions[0]);
    s.onboarding.clarification_answers=[{question_id:q.id,question:q,source_output_id:'older-output',option_id:'savings',text:'이전 설명',answer:'이전 의미',answer_id:'saved-1',recorded_at:'2026-11-15T00:00:00Z'}];
    s.onboarding.job.structured_questions[0].options[0].label='차입한 자금';
  });
  try{
    assert.match(h.$('context-card').textContent,/저장된 답변: 이전 의미/);
    assert.equal(h.$('context-card').querySelector('input:checked'),null);assert.equal(h.$('context-answer').value,'');
    h.$('context-next').click();await settle();assert.equal(h.calls.filter(c=>c.path==='/api/setup/answers').length,0);
  }finally{await h.close()}
});

test('pending save locks answer controls and memory edits until the saved snapshot resumes',async()=>{
  const h=await setup(s=>{contextFixture(s);s.onboarding.job.structured_questions=s.onboarding.job.structured_questions.slice(0,1);
    const q=structuredClone(s.onboarding.job.structured_questions[0]);s.onboarding.clarification_answers=[{question_id:q.id,question:q,source_output_id:'older',option_id:null,text:'previous',answer:'previous',answer_id:'a-1',recorded_at:'2026-01-01'}];
  });
  const fetch=h.w.fetch;let release;
  h.w.fetch=async(path,opts)=>{if(path==='/api/setup/answers')await new Promise(resolve=>{release=resolve});return fetch(path,opts)};
  try{
    h.$('context-answer').value='FIRST';h.$('context-next').click();await settle();
    assert.equal(h.$('context-answer').disabled,true);
    assert.ok([...h.$('context-card').querySelectorAll('input')].every(x=>x.disabled));
    assert.ok([...h.$('context-memory-list').querySelectorAll('button')].every(x=>x.disabled));
    release();await settle();await settle();assert.equal(h.state.onboarding.clarification_answers[0].text,'FIRST');
    assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
  }finally{await h.close()}
});

test('resume keeps final answer locked until the generation request finishes',async()=>{
 const h=await setup(s=>{contextFixture(s);s.onboarding.job.structured_questions=s.onboarding.job.structured_questions.slice(0,1)});
 const fetch=h.w.fetch;let release;
 h.w.fetch=async(path,opts)=>{if(path==='/api/setup/draft')await new Promise(resolve=>{release=resolve});return fetch(path,opts)};
 try{
  h.$('context-answer').value='FIRST';h.$('context-next').click();await settle();
  assert.equal(h.$('context-answer').disabled,true);assert.equal(h.$('context-next').disabled,true);
  release();await settle();await settle();assert.equal(h.state.onboarding.clarification_answers[0].text,'FIRST');
  assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
 }finally{await h.close()}
});

test('historical notes allow explicit review without answering old questions again',async()=>{
 const h=await setup(s=>{contextFixture(s);s.onboarding.context_note_history=[{text:'Previously saved context',recorded_at:'2026-11-15',source_id:'old-note'}]});
 try{
  assert.equal(h.$('context-recheck').hidden,false);h.$('context-recheck').click();await settle();
  assert.equal(h.calls.filter(x=>x.path==='/api/setup/generate').length,1);
  assert.equal(h.calls.filter(x=>x.path==='/api/setup/answers').length,0);
 }finally{await h.close()}
});

for(const {name,run} of cases){await run();console.log('PASS '+name)}
console.log(cases.length+' dashboard feedback tests passed');
