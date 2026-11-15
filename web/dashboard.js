'use strict';
const $=id=>document.getElementById(id), form=$('setup-form');
const csrf=document.querySelector('meta[name="mara-csrf"]').content;
const money=n=>Number(n).toLocaleString('ko-KR',{maximumFractionDigits:0})+'원';
const pct=n=>n==null?'계산 불가':(n*100).toFixed(1)+'%';
const pretty=x=>JSON.stringify(x,null,2);
let loadSequence=0;
let initialized=false, displayed=null, running=false, selectedHistory=false;
let modelReady=null, lastJobSignature=null, expectedJobId=null, feedbackIssues=[];
let modelSettingsInitialized=false, savedModelProvider='openai';
let demoReport=null, viewChosen=false, showingDemo=false, generateLabel='초기 포트폴리오 제안 생성';
function selectView(name,chosen=true){
  if(chosen)viewChosen=true;const report=name==='report';
  form.hidden=report;$('report-panel').hidden=!report;$('setup-toc').hidden=report;$('report-toc').hidden=!report;
  $('tab-setup').setAttribute('aria-pressed',String(!report));$('tab-report').setAttribute('aria-pressed',String(report));
}
$('tab-setup').onclick=()=>selectView('setup');
$('tab-report').onclick=()=>selectView('report');
const busy=new Set();
function text(id,value){$(id).textContent=value??'—'}
function list(id,items){$(id).replaceChildren(...items.map(x=>{const e=document.createElement('li');e.textContent=x;return e}))}
function rows(id,values){$(id).replaceChildren(...values.map(row=>{const tr=document.createElement('tr');for(const v of row){const td=document.createElement('td');td.textContent=v;tr.append(td)}return tr}))}
async function api(path,body){const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Mara-CSRF':csrf},body:JSON.stringify(body)};const r=await fetch(path,options);const v=await r.json();if(!r.ok)throw new Error(v.error||'요청에 실패했어요.');return v}
function readForm(){const result={};for(const el of form.elements){if(!el.name||el.dataset.contextControl)continue;if(el.multiple)result[el.name]=Array.from(el.selectedOptions,x=>x.value);else if(el.type==='checkbox')result[el.name]=el.checked;else if(el.type==='number')result[el.name]=el.value===''?'':Number(el.value)/(el.hasAttribute('data-percent')?100:1);else result[el.name]=el.value}return result}
function restore(value){if(Object.keys(value).length&&!value.contribution_schedule)form.elements.contribution_schedule.value='days';for(const [key,v] of Object.entries(value)){const el=form.elements.namedItem(key);if(!el)continue;if(el.multiple){for(const option of el.options)option.selected=(v||[]).includes(option.value)}else if(el.type==='checkbox')el.checked=false;else el.value=v==null?'':el.hasAttribute('data-percent')&&v!==''?Number((Number(v)*100).toFixed(4)):v}}
function focusTarget(target){
  selectView(target==='proposal'?'report':'setup');
  const el=form.elements.namedItem(target)||$(target);if(!el)return;
  if(target==='model-settings')el.open=true;
  el.scrollIntoView({block:'center',behavior:'smooth'});
  const input=target==='model-settings'?$('model-id'):el;
  if(input.focus)input.focus({preventScroll:true});
}
function generationFeedback(message,issues=[],kind='info',focus=false){
  feedbackIssues=issues;const box=$('generate-feedback');box.hidden=false;box.dataset.kind=kind;
  box.setAttribute('role',kind==='error'?'alert':'status');text('generate-message',message);
  $('generate-issues').hidden=!issues.length;
  $('generate-issues').replaceChildren(...issues.map(issue=>{
    const li=document.createElement('li');
    if(issue.target){const button=document.createElement('button');button.type='button';button.className='rowbutton';button.textContent=issue.message;button.onclick=()=>focusTarget(issue.target);li.append(button)}
    else li.textContent=issue.message;
    return li;
  }));
  if(focus){box.scrollIntoView({block:'nearest',behavior:'smooth'});box.focus({preventScroll:true})}
}
function generationIssues(){
  const issues=[];
  for(const el of form.elements){
    if(el.willValidate===false||!el.validity||el.validity.valid)continue;
    const name=el.name==='confirmed'?'보유·현금 확인':el.labels?.[0]?.childNodes?.[0]?.textContent?.trim()||el.name;
    let reason='입력 형식이나 범위를 확인해주세요.';
    if(el.validity.valueMissing)reason=el.type==='checkbox'?'확인란을 선택해주세요.':'필수 항목이에요.';
    if(el.validity.badInput)reason='숫자로 입력해주세요.';
    if(el.validity.rangeUnderflow||el.validity.rangeOverflow)reason=`${el.min||'제한 없음'}~${el.max||'상한 없음'} 범위로 입력해주세요.`;
    if(el.validity.stepMismatch)reason=`${el.step||'1'} 단위로 입력해주세요.`;
    issues.push({target:el.name,message:name+': '+reason});
  }
  if(!form.elements.snapshot_id.value)issues.push({target:'refresh-holdings',message:'토스 보유·섹터 불러오기를 먼저 눌러주세요.'});
  if(modelReady===false)issues.push({target:'model-settings',message:savedModelProvider==='codex'?'Codex 실행을 준비하지 못했어요. 설치·로그인 상태를 확인하고 실행 설정을 저장해주세요.':'분석 모델이 설정되지 않았어요. Codex를 선택하거나 모델 ID와 API 키를 저장해주세요.'});
  return issues;
}
function updateJob(job){
  if(!job)return;
  if(expectedJobId&&job.id!==expectedJobId)return;
  const signature=JSON.stringify([job.id,job.status,job.message,job.questions]);
  if(signature===lastJobSignature)return;
  if(busy.has('generate')&&job.id!==expectedJobId)return;
  lastJobSignature=signature;
  const needsInput=job.status==='needs_input';
  if(needsInput){$('generate-feedback').hidden=true;return}
  const failed=['failed','interrupted','needs_input'].includes(job.status);
  const links=job.status==='completed'?[{target:'proposal',message:'제안과 평가 결과 보기'}]:[];
  generationFeedback(job.message,links,failed?'error':job.status==='completed'?'success':'info',failed&&job.id===expectedJobId);
}
function snapshot(s,force=false){if(!s)return;const old=readForm();if(!force&&form.elements.snapshot_id.value===s.id)return;rows('holdings-body',s.items.map(x=>[x.symbol,x.name,x.quantity]));text('snapshot-time',new Date(s.captured_at).toLocaleString('ko-KR')+' 조회');text('holding-exclusions',s.items.length?`미국 보유 ${s.items.length}개 · 이번 범위에서 제외한 국내·기타 보유 ${s.excluded_count}개`:`미국 주식 보유가 없어요. 범위 밖 보유 ${s.excluded_count}개`);for(const key of ['preferred_sectors','excluded_sectors']){const select=form.elements[key];select.replaceChildren(...s.sectors.map(x=>{const o=document.createElement('option');o.value=x.name;o.textContent='　'.repeat(x.depth)+x.name;o.selected=(old[key]||[]).includes(x.name);return o}))}form.elements.snapshot_id.value=s.id;form.elements.confirmed.checked=false}
function providerFields(){
  const codex=$('model-provider').value==='codex';$('api-key-field').hidden=codex;$('model-key').disabled=codex;
  $('model-id').placeholder=codex?'비우면 Codex 기본 모델':'사용 권한이 있는 API 모델 ID';
  text('model-id-help',codex?'선택 사항이에요. 비우면 개인 CLI 설정과 별도로 Codex 기본 모델을 사용해요.':'JSON 응답을 지원하는 모델 ID가 필요해요.');
  text('provider-help',codex?'이 Mac에 로그인된 Codex로 역할별 분석을 실행해요. 별도 API 키는 필요 없고 Codex 사용 한도가 적용돼요. 입력한 투자 맥락·보유·시장 자료를 Codex에 전달해요.':'OpenAI API 모델 ID와 키를 이 Mac에 저장해요. 키는 다시 표시하지 않아요. 투자 맥락·보유·시장 자료를 모델에 전달하며 API 사용료가 발생할 수 있어요.');
}
function modelStatus(s,reset=false){
  modelReady=s.configured;savedModelProvider=s.provider||'openai';
  if(savedModelProvider==='codex'){
    const detail=!s.codex?.installed?'Codex CLI를 찾지 못했어요.':!s.codex?.compatible?'Codex CLI 업데이트가 필요해요.':'Codex 로그인이 필요해요. 터미널에서 codex login을 실행해주세요.';
    text('model-status',s.configured?`Codex 실행 준비됨 · ${s.model||'Codex 기본 모델'} · CLI ${s.codex?.version||''} · 별도 API 키 필요 없음`:detail);
  }else text('model-status',s.configured?`설정된 API 모델: ${s.model} · 실제 호출 성공 여부는 제안 생성에서 확인해요.`:'분석 실행 설정이 없어요. Codex 또는 OpenAI API를 선택해 저장해주세요. 입력 임시 저장은 가능해요.');
  text('generate-prerequisite',s.configured?`생성 시 입력을 저장하고 ${savedModelProvider==='codex'?'Codex로 ':''}분석을 시작해요.`:'생성 전 위의 Codex / API 실행 설정을 저장해주세요.');
  if(!s.configured)$('model-settings').open=true;
  if(!modelSettingsInitialized||reset){$('model-provider').value=savedModelProvider;$('model-id').value=s.model||'';modelSettingsInitialized=true;providerFields()}
}
function show(row){displayed=row.id;showingDemo=row.body.mode==='demo';window.MaraReport.render(row);$('report-document').dataset.reportId=row.id;window.MaraWorkbench?.openReport(row)}
async function load(){const sequence=++loadSequence;try{
  const s=await api('/api/state');if(sequence!==loadSequence)return;const o=s.onboarding;text('service','실행 중');text('broker-state',s.broker_connected?'조회 연결 확인':'연결 확인 필요');text('broker-time',s.broker_check?.checked_at?'최근 확인 '+new Date(s.broker_check.checked_at).toLocaleString('ko-KR'):'보유 불러오기로 확인해주세요.');
  if(!initialized){snapshot(o.snapshot,true);restore(o.draft);if(o.snapshot)form.elements.snapshot_id.value=o.snapshot.id;form.elements.confirmed.checked=false;initialized=true}
  modelStatus(o.model);text('capital-limit','기존 보유와 현금을 합친 운용 상한: '+money(o.capital_limit));generateLabel=o.latest?'포트폴리오 평가·제안 생성':'초기 포트폴리오 제안 생성';running=o.job?.status==='running';text('job',o.job?.message||'');for(const id of ['generate','refresh-holdings','save-model'])$(id).disabled=running||busy.has(id);
  window.MaraClarifications?.update(o.job,o.clarification_answers,o.context_note_history);
  $('generate').textContent=running?'포트폴리오 분석 중…':busy.has('generate')?'요청 확인 중…':generateLabel;updateJob(o.job);
  if(o.latest&&o.latest.id!==displayed&&!selectedHistory){show(o.latest);if(!viewChosen||o.job?.id===expectedJobId)selectView('report',false)}
  $('historylist').replaceChildren(...o.history.map(r=>{const div=document.createElement('div'),b=document.createElement('button');b.type='button';b.className='rowbutton';b.textContent=r.as_of+' · '+({adjust:'조정 제안',hold:'유지',defer:'보류'}[r.action]||r.action)+(r.revision_of?' · 수정본':'');b.onclick=async()=>{try{show(await api('/api/portfolio/report/'+r.id));selectedHistory=true;selectView('report')}catch(e){text('message',e.message)}};div.append(b);return div}));
  demoReport=s.latest;$('demo-view').disabled=!demoReport;
  window.MaraWorkbench?.refresh();
  if(s.latest)text('demo-result',pretty({구분:'합성 데모',평가일:s.latest.effective,제안:s.latest.body.proposal,회고:s.latest.body.reflection}));
}catch(e){text('service','연결 확인 필요');text('message','서비스 상태를 불러오지 못했어요. '+e.message)}}
async function action(button,fn){if(busy.has(button.id))return;busy.add(button.id);button.disabled=true;try{await fn()}catch(e){text('message',e.message);if(button.id==='generate'||button.id==='save-draft')generationFeedback(e.message,[],'error',true);if(button.id==='save-model')text('model-message',e.message);if(button.id==='refresh-holdings')text('snapshot-time',e.message)}finally{busy.delete(button.id);button.disabled=running&&['generate','refresh-holdings','save-model'].includes(button.id);if(button.id==='generate')button.textContent=running?'포트폴리오 분석 중…':generateLabel}}
window.MaraClarifications?.init({api,submit:()=>form.requestSubmit()});
$('save-draft').onclick=()=>action($('save-draft'),async()=>{await api('/api/setup/draft',readForm());const message='입력을 이 Mac에 임시 저장했어요. 주문이나 분석은 실행하지 않았어요.';text('message',message);generationFeedback(message,[],'success')});
$('refresh-holdings').onclick=()=>action($('refresh-holdings'),async()=>{text('message','토스 보유와 섹터 목록을 조회하고 있어요.');snapshot(await api('/api/setup/holdings',{}),true);text('message','보유를 불러왔어요. 실제 현금과 보유 확인란을 확인해주세요.')});
$('clear-sectors').onclick=()=>{for(const key of ['preferred_sectors','excluded_sectors'])for(const o of form.elements[key].options)o.selected=false};
$('model-provider').onchange=providerFields;
$('save-model').onclick=()=>action($('save-model'),async()=>{const value={provider:$('model-provider').value,model:$('model-id').value.trim()};if(value.provider==='openai')value.api_key=$('model-key').value;const s=await api('/api/setup/model',value);$('model-key').value='';modelStatus(s,true);if(feedbackIssues.some(i=>i.target==='model-settings')){const issues=generationIssues();generationFeedback(issues.length?'실행 설정을 저장했어요. 남은 입력 항목을 확인해주세요.':'실행 설정을 저장했어요. 이제 제안을 생성할 수 있어요.',issues,issues.length?'error':'success')}text('model-message',s.provider==='codex'?'Codex 설치·로그인을 확인하고 저장했어요. 이제 제안을 생성할 수 있어요.':'로컬에 저장했어요. 실제 호출은 제안 생성 때 수행해요.')});
form.onsubmit=async e=>{
  e.preventDefault();if(running||busy.has('generate')){window.MaraClarifications?.resumeFinished();return;}
  if(window.MaraClarifications&&!window.MaraClarifications.beforeGenerate())return;
  try{await action($('generate'),async()=>{
    expectedJobId=null;$('generate').textContent='요청 확인 중…';
    generationFeedback('입력을 저장하고 생성 조건을 확인하고 있어요.');
    const payload=readForm(),issues=generationIssues();
    await api('/api/setup/draft',payload);
    if(issues.length){generationFeedback('입력은 저장했어요. 다음 항목을 확인하면 제안을 생성할 수 있어요.',issues,'error',true);return}
    generationFeedback('포트폴리오 제안 생성을 요청하고 있어요.');
    const result=await api('/api/setup/generate',payload);
    expectedJobId=result.job_id;lastJobSignature=null;selectedHistory=false;running=true;
    generationFeedback('제안 생성을 시작했어요. 아래에 진행 상태와 결과가 표시돼요. 화면을 닫아도 분석은 계속돼요.');
    await load();
  });}finally{window.MaraClarifications?.resumeFinished()}
};
// Handle native constraints explicitly so even an invalid submit gives feedback beside the button.
form.noValidate=true;
$('demo-view').onclick=()=>{if(demoReport){show(demoReport);selectedHistory=true;selectView('report')}};
$('print-report').onclick=()=>window.print();
let printDetails=[];
window.addEventListener('beforeprint',()=>{printDetails=Array.from($('report-panel').querySelectorAll('details:not([open])'));printDetails.forEach(d=>d.open=true)});
window.addEventListener('afterprint',()=>{printDetails.forEach(d=>d.open=false);printDetails=[]});
$('demo-next').onclick=()=>action($('demo-next'),async()=>{const r=await fetch('/api/demo-next',{method:'POST',headers:{'X-Mara-CSRF':csrf}});if(!r.ok)throw new Error('모의 평가 실패');await load();if(showingDemo&&demoReport)show(demoReport);text('message','별도 데모 평가를 저장했어요.')});
function theme(value){document.documentElement.dataset.theme=value;$('theme').textContent=value==='dark'?'라이트 모드':'다크 모드'}
try{theme(localStorage.getItem('workspace-theme')||'light')}catch(e){theme('light')}
$('theme').onclick=()=>{const value=document.documentElement.dataset.theme==='dark'?'light':'dark';theme(value);try{localStorage.setItem('workspace-theme',value)}catch(e){}};
load();setInterval(load,5000);
