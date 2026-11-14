'use strict';
const $=id=>document.getElementById(id), form=$('setup-form');
const csrf=document.querySelector('meta[name="mara-csrf"]').content;
const money=n=>Number(n).toLocaleString('ko-KR',{maximumFractionDigits:0})+'원';
const pct=n=>n==null?'계산 불가':(n*100).toFixed(1)+'%';
const pretty=x=>JSON.stringify(x,null,2);
let initialized=false, displayed=null, running=false, selectedHistory=false;
let modelReady=null, lastJobSignature=null, expectedJobId=null;
const busy=new Set();
function text(id,value){$(id).textContent=value??'—'}
function list(id,items){$(id).replaceChildren(...items.map(x=>{const e=document.createElement('li');e.textContent=x;return e}))}
function rows(id,values){$(id).replaceChildren(...values.map(row=>{const tr=document.createElement('tr');for(const v of row){const td=document.createElement('td');td.textContent=v;tr.append(td)}return tr}))}
async function api(path,body){const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Mara-CSRF':csrf},body:JSON.stringify(body)};const r=await fetch(path,options);const v=await r.json();if(!r.ok)throw new Error(v.error||'요청에 실패했어요.');return v}
function readForm(){const result={};for(const el of form.elements){if(!el.name)continue;if(el.multiple)result[el.name]=Array.from(el.selectedOptions,x=>x.value);else if(el.type==='checkbox')result[el.name]=el.checked;else if(el.type==='number')result[el.name]=el.value===''?'':Number(el.value)/(el.hasAttribute('data-percent')?100:1);else result[el.name]=el.value}return result}
function restore(value){for(const [key,v] of Object.entries(value)){const el=form.elements.namedItem(key);if(!el)continue;if(el.multiple){for(const option of el.options)option.selected=(v||[]).includes(option.value)}else if(el.type==='checkbox')el.checked=false;else el.value=v==null?'':el.hasAttribute('data-percent')&&v!==''?Number((Number(v)*100).toFixed(4)):v}}
function focusTarget(target){
  const el=form.elements.namedItem(target)||$(target);if(!el)return;
  if(target==='model-settings')el.open=true;
  el.scrollIntoView({block:'center',behavior:'smooth'});
  const input=target==='model-settings'?$('model-id'):el;
  if(input.focus)input.focus({preventScroll:true});
}
function generationFeedback(message,issues=[],kind='info',focus=false){
  const box=$('generate-feedback');box.hidden=false;box.dataset.kind=kind;
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
  if(modelReady===false)issues.push({target:'model-settings',message:'분석 모델이 설정되지 않았어요. 모델 ID와 API 키를 저장해주세요.'});
  return issues;
}
function updateJob(job){
  if(!job)return;
  if(expectedJobId&&job.id!==expectedJobId)return;
  const signature=JSON.stringify([job.id,job.status,job.message]);
  if(signature===lastJobSignature)return;
  if(busy.has('generate')&&job.id!==expectedJobId)return;
  lastJobSignature=signature;
  const failed=['failed','interrupted'].includes(job.status);
  const links=job.status==='completed'?[{target:'proposal',message:'제안과 평가 결과 보기'}]:[];
  generationFeedback(job.message,links,failed?'error':job.status==='completed'?'success':'info',failed&&job.id===expectedJobId);
}
function snapshot(s,force=false){if(!s)return;const old=readForm();if(!force&&form.elements.snapshot_id.value===s.id)return;rows('holdings-body',s.items.map(x=>[x.symbol,x.name,x.quantity]));text('snapshot-time',new Date(s.captured_at).toLocaleString('ko-KR')+' 조회');text('holding-exclusions',s.items.length?`미국 보유 ${s.items.length}개 · 이번 범위에서 제외한 국내·기타 보유 ${s.excluded_count}개`:`미국 주식 보유가 없어요. 범위 밖 보유 ${s.excluded_count}개`);for(const key of ['preferred_sectors','excluded_sectors']){const select=form.elements[key];select.replaceChildren(...s.sectors.map(x=>{const o=document.createElement('option');o.value=x.name;o.textContent='　'.repeat(x.depth)+x.name;o.selected=(old[key]||[]).includes(x.name);return o}))}form.elements.snapshot_id.value=s.id;form.elements.confirmed.checked=false}
function modelStatus(s){modelReady=s.configured;text('model-status',s.configured?`설정된 모델: ${s.model} · 실제 호출 성공 여부는 제안 생성에서 확인해요.`:'분석 모델 설정이 없어요. 입력은 임시 저장할 수 있고, 모델 설정 후 실제 제안을 생성할 수 있어요.');text('generate-prerequisite',s.configured?'생성 시 입력을 저장하고 분석을 시작해요.':'생성 전 분석 모델 설정이 필요해요. 위의 모델 ID와 API 키를 저장해주세요.');if(!s.configured)$('model-settings').open=true;if(!$('model-id').value)$('model-id').value=s.model||''}
function show(row){
  displayed=row.id;const r=row.body,p=r.proposal,a=r.validation.final_numeric,m=a.metrics||{},h=a.historical||{};
  text('rationale',p.rationale);$('rationale').className='';text('action',{hold:'유지',adjust:'조정 제안',defer:'보류'}[p.action]);
  const capital=r.funding?.proposal_capital??r.valuation.nav;
  text('funding',`실제 평가액 ${money(r.valuation.nav)} · 제안 기준액 ${money(capital)} · 추가 필요 자금 ${money(r.funding?.additional_funding_needed||0)} · 제안 범위 밖 금액 ${money(r.funding?.amount_outside_proposal||0)}`);
  rows('weights',Object.entries(p.weights).map(([s,w])=>[s==='CASH'?'원화 현금':s,pct(w),money(w*capital),pct(r.valuation.weights[s]||0)]));list('risks',[...p.risks,...p.dissent]);list('checks',p.next_checks);
  text('evaluation-status',{pass:'수치 조건 충족',blocked:'제한 위반',needs_review:'추가 확인 필요'}[a.status]||'검증 기록');
  const cards=[['가정한 시나리오 손실',pct(a.scenario_loss_fraction)],['시나리오 손실액',m.scenario_loss_amount==null?'—':money(m.scenario_loss_amount)],['최대 종목 비중',pct(m.max_position_fraction)],['종목 HHI',m.position_hhi?.toFixed(3)??'해당 없음'],['유효 종목 수',m.effective_positions?.toFixed(1)??'해당 없음'],['생활비 현금 여력',m.cash_months_of_expenses==null?'해당 없음':m.cash_months_of_expenses.toFixed(1)+'개월'],['연환산 변동성',pct(h.annualized_volatility)],['Sharpe ratio',h.sharpe?.toFixed(2)??'계산 불가'],['과거 최대 낙폭',pct(h.max_drawdown)]];
  $('metrics').replaceChildren(...cards.map(([label,value])=>{const c=document.createElement('div');c.className='metric';const l=document.createElement('span');l.textContent=label;l.className='label';const b=document.createElement('b');b.textContent=value;c.append(l,b);return c}));
  list('evaluation-issues',[...a.errors,...(a.missing||[]),...(a.warnings||[]),...r.validation.final_critique.issues,...r.validation.final_critique.unsupported_claims]);list('evaluation-limits',[...(a.limitations||[]),h.reason||h.method||'',`검증 에이전트: ${r.validation.final_critique.reason}`].filter(Boolean));
  text('exposures',pretty({섹터:m.sector_exposures,섹터_미확인_비중:m.unknown_sector_fraction,자산군:m.asset_classes,통화:m.currencies}));text('validation',pretty(r.validation));
  $('perspectives').replaceChildren(...Object.entries(r.perspectives).map(([name,v])=>{const div=document.createElement('div');div.className='card';const title=document.createElement('h3');title.textContent={buffett:'Buffett · 기업 가치',marks:'Marks · 위험과 사이클',bogle:'Bogle · 비용과 분산'}[name];const thesis=document.createElement('p');thesis.textContent=v.thesis;const detail=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='비중·근거·가정';pre.textContent=pretty(v);detail.append(summary,pre);div.append(title,thesis,detail);return div}));text('raw',pretty(row));text('next',`다음 평가 기준일 ${r.next_evaluation} · 다음 리밸런싱 기준일 ${r.next_rebalance} · 제안만 저장됨`);
}
async function load(){try{
  const s=await api('/api/state'),o=s.onboarding;text('service','실행 중');text('broker-state',s.broker_connected?'조회 연결 확인':'연결 확인 필요');text('broker-time',s.broker_check?.checked_at?'최근 확인 '+new Date(s.broker_check.checked_at).toLocaleString('ko-KR'):'보유 불러오기로 확인해주세요.');
  if(!initialized){snapshot(o.snapshot,true);restore(o.draft);if(o.snapshot)form.elements.snapshot_id.value=o.snapshot.id;form.elements.confirmed.checked=false;initialized=true}
  modelStatus(o.model);text('capital-limit','기존 보유와 현금을 합친 운용 상한: '+money(o.capital_limit));running=o.job?.status==='running';text('job',o.job?.message||'');for(const id of ['generate','refresh-holdings','save-model'])$(id).disabled=running||busy.has(id);
  $('generate').textContent=running?'포트폴리오 분석 중…':busy.has('generate')?'요청 확인 중…':'초기 포트폴리오 제안 생성';updateJob(o.job);
  if(o.latest&&o.latest.id!==displayed&&!selectedHistory)show(o.latest);
  $('historylist').replaceChildren(...o.history.map(r=>{const div=document.createElement('div'),b=document.createElement('button');b.type='button';b.className='rowbutton';b.textContent=r.as_of+' · '+({adjust:'조정 제안',hold:'유지',defer:'보류'}[r.action]||r.action)+(r.revision_of?' · 수정본':'');b.onclick=async()=>{try{show(await api('/api/portfolio/report/'+r.id));selectedHistory=true}catch(e){text('message',e.message)}};div.append(b);return div}));
  if(s.latest)text('demo-result',pretty({구분:'합성 데모',평가일:s.latest.effective,제안:s.latest.body.proposal,회고:s.latest.body.reflection}));
}catch(e){text('service','연결 확인 필요');text('message','서비스 상태를 불러오지 못했어요. '+e.message)}}
async function action(button,fn){if(busy.has(button.id))return;busy.add(button.id);button.disabled=true;try{await fn()}catch(e){text('message',e.message);if(button.id==='generate'||button.id==='save-draft')generationFeedback(e.message,[],'error',true);if(button.id==='save-model')text('model-message',e.message);if(button.id==='refresh-holdings')text('snapshot-time',e.message)}finally{busy.delete(button.id);button.disabled=running&&['generate','refresh-holdings','save-model'].includes(button.id);if(button.id==='generate')button.textContent=running?'포트폴리오 분석 중…':'초기 포트폴리오 제안 생성'}}
$('save-draft').onclick=()=>action($('save-draft'),async()=>{await api('/api/setup/draft',readForm());const message='입력을 이 Mac에 임시 저장했어요. 주문이나 분석은 실행하지 않았어요.';text('message',message);generationFeedback(message,[],'success')});
$('refresh-holdings').onclick=()=>action($('refresh-holdings'),async()=>{text('message','토스 보유와 섹터 목록을 조회하고 있어요.');snapshot(await api('/api/setup/holdings',{}),true);text('message','보유를 불러왔어요. 실제 현금과 보유 확인란을 확인해주세요.')});
$('clear-sectors').onclick=()=>{for(const key of ['preferred_sectors','excluded_sectors'])for(const o of form.elements[key].options)o.selected=false};
$('save-model').onclick=()=>action($('save-model'),async()=>{const s=await api('/api/setup/model',{model:$('model-id').value.trim(),api_key:$('model-key').value});$('model-key').value='';modelStatus(s);text('model-message','로컬에 저장했어요. 실제 호출은 제안 생성 때 수행해요.')});
form.onsubmit=async e=>{
  e.preventDefault();if(running||busy.has('generate'))return;
  await action($('generate'),async()=>{
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
  });
};
// Handle native constraints explicitly so even an invalid submit gives feedback beside the button.
form.noValidate=true;
$('demo-next').onclick=()=>action($('demo-next'),async()=>{const r=await fetch('/api/demo-next',{method:'POST',headers:{'X-Mara-CSRF':csrf}});if(!r.ok)throw new Error('모의 평가 실패');await load();text('message','별도 데모 평가를 저장했어요.')});
function theme(value){document.documentElement.dataset.theme=value;$('theme').textContent=value==='dark'?'라이트 모드':'다크 모드'}
try{theme(localStorage.getItem('workspace-theme')||'light')}catch(e){theme('light')}
$('theme').onclick=()=>{const value=document.documentElement.dataset.theme==='dark'?'light':'dark';theme(value);try{localStorage.setItem('workspace-theme',value)}catch(e){}};
load();setInterval(load,5000);
