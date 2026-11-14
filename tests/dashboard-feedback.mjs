// DOM regression tests: trusted repository HTML, fake HTTP, no broker/model requests.
// Setup: npm install --prefix .local/test-ui --no-save --ignore-scripts happy-dom@15.11.7
// Run: node tests/dashboard-feedback.mjs (Node >=20; no production dependency).
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Window } from '../.local/test-ui/node_modules/happy-dom/lib/index.js';

const html=await readFile(new URL('../web/dashboard.html',import.meta.url),'utf8');
const reportScript=await readFile(new URL('../web/report.js',import.meta.url),'utf8');
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
  w.eval(reportScript);w.eval(script+'\nwindow.__testPoll=load;');await settle();
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

for(const {name,run} of cases){await run();console.log('PASS '+name)}
console.log(cases.length+' dashboard feedback tests passed');
