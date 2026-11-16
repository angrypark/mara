/* Generic component viewer. All analyst and user content is rendered as inert text. */
'use strict';
window.MaraWorkbench=(()=>{
  const $=id=>document.getElementById(id),el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
  const statuses={completed:'완료',running:'분석 중',pending:'대기',needs_input:'추가 확인',failed:'실패',interrupted:'중단',skipped:'이번 실행 없음',blocked:'보류'};
  const actions={hold:'유지',adjust:'조정 검토',defer:'보류'}, pct=x=>x==null?'미확인':(x*100).toFixed(1)+'%';
  const symbols=s=>s==='CASH'?'기준통화 현금':s==='USD_CASH'?'달러 현금':s;
  let scope='portfolio',runId=null,doc=null,selected='overview',selectedStage=null,tab='analysis',epoch=0,signature='',chatSignature='',loading=false;
  const drafts=new Map();
  let flowObserver=null;
  async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Mara-CSRF':document.querySelector('meta[name="mara-csrf"]').content},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.error||'불러오지 못했어요.');return value}
  const key=()=>[scope,runId,selected].join('/'),current=()=>{const c=doc?.components.find(c=>c.id===selected),stage=doc?.extensions?.flow?.find(x=>x.id===selectedStage&&x.agent_id===selected);return c&&stage?.snapshot?{...c,...stage.snapshot}:c};
  const button=(label,fn,cls='')=>{const b=el('button',cls,label);b.type='button';b.onclick=fn;return b};
  function saveDraft(){drafts.set(key(),$('wb-question').value)}
  function bar(value,kind='proposal'){const track=el('div','bar-track'),b=el('span','bar '+kind);b.style.width=Math.max(0,Math.min(100,Number(value)*100||0))+'%';track.append(b);track.setAttribute('aria-hidden','true');return track}
  function objectView(value,depth=0){
    if(value==null)return el('span','hint','기록 없음 / 계산 불가');
    if(typeof value!=='object')return el('span','wb-value',typeof value==='boolean'?(value?'예':'아니요'):String(value));
    if(Array.isArray(value)){const list=el('ul','wb-value-list');if(!value.length)return el('p','hint','기록된 항목이 없어요.');for(const v of value){const li=el('li');li.append(objectView(v,depth+1));list.append(li)}return list}
    const dl=el('dl','wb-data');for(const [k,v] of Object.entries(value)){
      if(v&&typeof v==='object'){const details=el('details','wb-data-group');details.open=depth===0;details.append(el('summary','',fieldLabel(k)),objectView(v,depth+1));const dd=el('dd');dd.append(details);dl.append(dd)}
      else{dl.append(el('dt','',fieldLabel(k)));const dd=el('dd');dd.append(objectView(v,depth+1));dl.append(dd)}
    }return dl;
  }
  function fieldLabel(k){return ({profile:'투자 맥락',market:'시장 스냅샷',actual:'실제 보유',previous:'이전 판단',anchors:'보호할 맥락',valuation:'실제 평가액과 비중',funding:'자금 범위',knowledge:'이번에 불러온 지식',coverage:'자료 범위',available:'확인한 자료',missing:'확인하지 못한 자료',reason:'이유',status:'상태',actionable_risky_allocation:'위험자산 제안 확정 가능',goal:'목표',constraints:'제약',context_analysis:'맥락 분석',evidence_analysis:'시장 분석',performance:'성과',current_reflection:'이번 회고',rebalance_due:'리밸런싱 검토 시점',as_of:'기준일',facts:'원본 사실',prices:'가격',assets:'자산 정보',summary:'요약',input_id:'입력 기록',output_id:'출력 기록',guide_hash:'가이드 버전 해시',provider:'실행 모델',recorded_at:'기록 시각',next_checks:'다음 확인',unresolved_risks:'미해결 위험'})[k]||k}
  function list(values){return objectView(values)}
  function chip(text,status){const n=el('span','pill',text);if(status)n.dataset.status=status;return n}
  function validateDocument(d){
    if(!['mara.workbench/1.0.0','mara.workbench/1.1.0','mara.workbench/1.2.0'].includes(d?.schema_version))throw Error('지원하지 않는 결과 계약이에요. 화면과 서버 버전을 확인해주세요.');
    if(!d.run||!Array.isArray(d.components)||!d.components.length||!Array.isArray(d.sources)||!Array.isArray(d.edges))throw Error('결과 구조가 올바르지 않아요.');
    const ids=new Set(d.components.map(c=>c.id)),sources=new Set(d.sources.map(s=>s.id));
    if(ids.size!==d.components.length||sources.size!==d.sources.length||d.edges.some(e=>!ids.has(e.from)||!ids.has(e.to)))throw Error('중복되거나 알 수 없는 컴포넌트 참조예요.');
    for(const c of d.components){if(!Array.isArray(c.blocks)||!Array.isArray(c.source_ids)||c.source_ids.some(id=>!sources.has(id)))throw Error('컴포넌트 근거 참조를 확인할 수 없어요.');if(c.output?.weights){const w=Object.values(c.output.weights);if(w.some(n=>typeof n!=='number'||!Number.isFinite(n)||n<0||n>1)||Math.abs(w.reduce((a,b)=>a+b,0)-1)>1e-6)throw Error('제안 비중 계약에 맞지 않아요.')}}
  }
  function render(d){
    validateDocument(d);doc=d;runId=d.run.id;$('wb-content').hidden=false;$('wb-empty').hidden=true;$('report-empty').hidden=true;
    if(selected!=='overview'&&!current())selected='overview';
    $('wb-run-state').textContent=statuses[d.run.status];$('wb-run-state').dataset.status=d.run.status;
    $('wb-run-note').textContent=(d.run.mode==='demo'?'합성 데모 · 실제 분석 아님 · ':'')+d.run.as_of+' · '+d.run.message;
    let riskBanner=$('wb-risk-scope');if(!riskBanner){riskBanner=el('p','notice');riskBanner.id='wb-risk-scope';$('wb-run-note').after(riskBanner)}const riskBudget=d.portfolio?.risk_budget||d.extensions?.analysis?.risk_budget;riskBanner.hidden=riskBudget?.scope!=='analysis_only';riskBanner.textContent=riskBudget?.scope==='analysis_only'?`분석 전용 · 이번 제안의 충격 비교 예산 ${pct(riskBudget.effective_fraction)} / 기존 기준 ${pct(riskBudget.reference_fraction)}. 실제 감내손실 확인이나 주문 가능한 제안이 아니에요.`:'';
    $('wb-contract-tag').textContent='v'+d.schema_version.split('/')[1]+' · '+d.components.length+'개 역할';
    nodes();pane();
  }
  function nodes(){
    flow();actionState();
    const nav=$('wb-nodes');nav.replaceChildren();
    const overview=button('전체 판단 · 비교',()=>choose('overview'),'wb-node wb-overview');overview.setAttribute('aria-pressed',String(selected==='overview'));nav.append(overview);
    let group='';for(const c of doc.components){if(c.role!==group){group=c.role;nav.append(el('p','wb-group',group==='R3'?'R3 · 독립 투자 관점':group+' · '+({R1:'판단의 기준',R2:'시장 이해',R4:'검증',R5:'종합',R6:'회고',F1:'기억'}[group]||'추가 역할')))}
      const b=button('',()=>choose(c.id),'wb-node');b.dataset.agent=c.id;b.setAttribute('aria-pressed',String(selected===c.id));b.append(el('span','wb-node-label',c.label));const state=el('span','wb-node-state',statuses[c.status]||c.status);state.dataset.status=c.status;b.append(state);nav.append(b)}
  }
  function flow(){
    const root=$('wb-flow');if(!root)return;if(flowObserver)flowObserver.disconnect();root.replaceChildren();root.tabIndex=0;root.setAttribute('aria-label','의사결정 흐름. 좁은 화면에서는 좌우로 이동할 수 있어요.');
    const stages=doc.extensions?.flow||[];if(!stages.length){root.append(el('p','hint','이전 실행의 역할 연결은 입력·연결 탭에서 확인할 수 있어요.'));return}
    const graph=el('div','wb-flow-map');root.append(graph);
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('aria-hidden','true');svg.classList.add('wb-flow-lines');graph.append(svg);
    const perspectiveIds=doc.components.filter(c=>c.kind==='perspective').map(c=>c.id),positions={reflection:[1,1],memory:[2,1],context:[1,3],evidence:[2,3],review:[4,3],leader:[5,3],final_review:[6,3],evaluator:[7,3]};
    perspectiveIds.forEach((id,i)=>positions[id]=[3,2+i]);
    for(const step of stages){const c=doc.components.find(x=>x.id===step.agent_id),b=button('',()=>choose(step.agent_id,step.id),'wb-flow-node');b.dataset.step=step.id;b.dataset.status=step.status;b.setAttribute('aria-pressed',String(selected===step.agent_id&&(!selectedStage||selectedStage===step.id)));
      const [col,row]=positions[step.id]||[3,2];b.style.gridColumn=col;b.style.gridRow=row;
      b.append(el('span','wb-flow-role',c.role),el('strong','',step.label),el('span','wb-flow-state',statuses[step.status]||step.status));b.title=step.record_ids.length+'개 출력 기록 · 클릭하여 근거와 대화 열기';graph.append(b)}
    const draw=()=>{if(!graph.isConnected)return;svg.replaceChildren();svg.setAttribute('viewBox','0 0 '+graph.offsetWidth+' '+graph.offsetHeight);const base=graph.getBoundingClientRect();
      for(const step of stages){const to=graph.querySelector('[data-step="'+step.id+'"]');for(const id of step.depends_on){const from=graph.querySelector('[data-step="'+id+'"]');if(!from||!to)continue;const a=from.getBoundingClientRect(),b=to.getBoundingClientRect();const x1=a.right-base.left,y1=a.top+a.height/2-base.top,x2=b.left-base.left,y2=b.top+b.height/2-base.top,mid=(x1+x2)/2;
        const path=document.createElementNS(ns,'path');path.setAttribute('d',`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`);svg.append(path);const arrow=document.createElementNS(ns,'path');arrow.setAttribute('d',`M ${x2-5} ${y2-3} L ${x2} ${y2} L ${x2-5} ${y2+3}`);svg.append(arrow)}}};
    requestAnimationFrame(draw);
    if(typeof ResizeObserver==='function'){flowObserver=new ResizeObserver(draw);flowObserver.observe(graph)}
  }
  async function decisionAction(action,messageId){
    const status=$('wb-action-status'),ticket=runId;if(status)status.textContent=action==='evaluate'?'独立 평가를 요청하고 있어요…'.replace('独立','독립'):'변경을 반영한 새 판단을 요청하고 있어요…';
    try{const body={action,run_id:ticket,request_id:crypto.randomUUID()};if(messageId)body.dialogue_request_id=messageId;await api('/api/decision-action/'+scope,body);await refresh()}
    catch(e){if(status)status.textContent=e.message}
  }
  function actionState(){
    const root=$('wb-action-status');if(!root)return;root.replaceChildren();
    const lineage=doc.extensions?.lineage;if(lineage){const box=el('div','wb-change-banner');box.append(el('strong','','대화에서 이어진 새 판단'),el('p','',lineage.amendment.change.summary),el('p','hint','당시 '+doc.run.as_of+' 자료로 전체 재검증 · 원본 보존'));
      if(lineage.change_response)box.append(el('p','',({accepted:'수용',partial:'일부 수용',rejected:'미수용'})[lineage.change_response.status]+' · '+lineage.change_response.reason));
      box.append(button('원본 판단과 비교',async()=>{runId=lineage.amendment.base_run_id;signature='';await refresh()}));root.append(box)}
    for(const a of (doc.extensions?.decision_actions||[]).slice(-3)){const box=el('div','wb-action-note');box.append(el('span','',a.result.message||(a.action==='revise'?'대화 변경의 후속 분석·검증 중…':'독립 품질 평가 중…')));if(a.result.new_run_id)box.append(button('새 판단 열기',async()=>{runId=a.result.new_run_id;signature='';await refresh()}));root.append(box)}
  }
  function evidenceStatus(value){return ({pass:'충족',fail:'실패',unknown:'미확인',met:'충족',partial:'일부',missing:'누락',contradicted:'반박됨',supported:'지원됨',unsupported:'미입증',conditional:'조건부',unresolved:'미해결'})[value]||value}
  function calculationView(path){
    const roots={analysis:doc.extensions?.analysis,funding:doc.portfolio?.funding,valuation:doc.portfolio?.actual,proposal:doc.portfolio?.proposal};
    let value=roots;for(const part of path.slice(1).split('/')){const key=part.replace(/~1/g,'/').replace(/~0/g,'~');value=value&&Object.hasOwn(value,key)?value[key]:undefined}
    const box=el('details');box.append(el('summary','','계산값 확인'),el('p','hint',path),value===undefined?el('p','notice','이 원본 보고서에는 해당 계산 경로가 없어요.'):objectView(value));return box;
  }
  function reportCase(root){
    const c=doc.portfolio?.proposal?.investment_case;if(!c)return;
    const lead=el('section','wb-block');lead.append(el('h4','','승인 전에 읽을 핵심 판단'),list(c.key_points));root.append(lead);
    const claims=el('details','wb-block');claims.append(el('summary','','핵심 주장 · 근거와 반대 조건 '+c.claims.length+'개'));
    for(const claim of c.claims){const box=el('details','wb-quality-item');box.append(el('summary','',evidenceStatus(claim.status)+' · '+claim.statement),el('p','',claim.importance),el('p','','반대 근거: '+claim.counterevidence),el('p','','판단에 미치는 영향: '+claim.decision_impact),list(claim.assumptions),sourceButtons(claim.fact_ids));for(const path of claim.calculation_paths)box.append(calculationView(path));claims.append(box)}root.append(claims);
    const alternatives=el('details','wb-block');alternatives.append(el('summary','','대안별 선택 이유와 판단 변경 조건'));
    for(const option of c.alternatives||[]){const box=el('article','wb-tool-call');box.append(el('h5','',option.name),chip(({preferred:'선택',rejected:'채택하지 않음',conditional:'조건부',diagnostic_only:'제약 비교용'})[option.decision]||option.decision),el('p','',Object.entries(option.weights).map(([s,w])=>symbols(s)+' '+pct(w)).join(' · ')),el('p','',option.reason),el('p','','판단 변경 조건: '+option.change_condition),el('p','hint','계산 근거 '+option.comparison_path));alternatives.append(box)}root.append(alternatives);
    const plan=el('details','wb-block');plan.append(el('summary','','실행 조건과 반증 계획'),list(c.implementation));for(const m of c.monitoring){plan.append(el('h5','',m.variable),el('p','',m.condition+' → '+m.action),el('p','hint',m.check_at+' · 담당 '+m.owner),el('p','','반례 확인: '+m.counterexample_test))}plan.append(list(c.scope_limits));root.append(plan);
  }
  function krwComparisonView(root,c){
    if(!c?.available){if(c?.reason)root.append(el('p','notice','원화 비교 자료: '+c.reason));return;}
    const section=el('section','wb-block');section.append(el('h4','','원화 기준 대안 비교'),el('p','hint',c.start+' ~ '+c.end+' · '+c.observations+'개월 · 월말 NAV × USD/KRW'),el('p','notice',c.cash_scope),el('p','hint',c.amount_unit));
    const select=el('select');select.setAttribute('aria-label','원화 비교 지표');for(const [key,label] of [['annualized_return','시간가중 연환산 수익률'],['annualized_volatility','월별 연환산 변동성'],['month_end_max_drawdown','월말 최대 낙폭'],['ending_wealth','납입 포함 평가액 · KRW'],['profit','납입을 뺀 손익 · KRW']]){const o=el('option','',label);o.value=key;select.append(o)}
    const chart=el('div');function redraw(){chart.replaceChildren();const metric=select.value,rows=Object.entries(c.results),max=Math.max(.001,...rows.map(([,r])=>Math.abs(r[metric])));for(const [name,r] of rows){const line=el('div','allocation-line');line.append(el('span','bar-label',name),bar(Math.abs(r[metric])/max),el('b','bar-value',['ending_wealth','profit'].includes(metric)?r[metric].toLocaleString('ko-KR',{maximumFractionDigits:0})+' KRW':pct(r[metric])));chart.append(line)}}select.addEventListener('change',redraw);section.append(select,chart);redraw();
    section.append(el('p','hint','지표 절댓값을 같은 축으로 비교해요. 현재 전략을 과거에 적용한 가상 비교이며 미래 목표액·실제 수익이 아니에요.'),el('p','', '별도 계산 재현: '+({passed:'일치',failed:'불일치'}[c.independent_replay?.status]||'미확인')));
    const detail=el('details');detail.append(el('summary','','원화 계산의 가정·비용·민감도'),el('p','',c.cost_scope),el('p','',c.fx_source_limits),objectView(c.assumptions),objectView(c.sensitivity),objectView(c.independent_replay),list(c.limitations));section.append(detail);root.append(section);
  }
  function quantitativeView(root){
    const a=doc.extensions?.analysis;if(!a)return;
    krwComparisonView(root,a.krw_comparison);
    const section=el('section','wb-block');section.append(el('h4','','같은 조건에서 배분 대안 비교'));
    const c=a.comparison;
    if(!c?.available||!c.results||!Array.isArray(c.sensitivity)){section.append(el('p','notice',c?.reason||'검증된 공통 수익률 자료가 없어요.'));root.append(section)}else{
    section.append(el('p','hint',c.start+' ~ '+c.end+' · '+c.observations+'개월 · 월별 NAV 총수익률 · USD'),el('p','hint',c.amount_unit),el('p','notice',c.cash_proxy_warning));
    const choice=el('select');choice.setAttribute('aria-label','비교 지표');for(const [key,label] of [['annualized_return','시간가중 연환산 수익률'],['annualized_volatility','월별 수익률의 연환산 변동성'],['month_end_max_drawdown','월말 최대 낙폭'],['ending_wealth','납입 포함 평가액 · 정규화 USD'],['profit','납입을 뺀 손익 · 정규화 USD']]){const o=el('option','',label);o.value=key;choice.append(o)}
    const chart=el('div');function redraw(){chart.replaceChildren();const metric=choice.value,rows=Object.entries(c.results),max=Math.max(.001,...rows.map(([,v])=>Math.abs(v[metric])));for(const [name,v] of rows){const row=el('div','allocation-line'),value=v[metric];row.append(el('span','bar-label',name),bar(Math.abs(value)/max),el('b','bar-value',['ending_wealth','profit'].includes(metric)?value.toLocaleString('ko-KR',{maximumFractionDigits:1}):pct(value)));chart.append(row)}chart.append(el('p','hint','막대는 선택한 지표의 절댓값을 같은 축으로 비교해요. 수익률이 높은 대안이 적합한 대안이라는 뜻은 아니에요.'))}choice.addEventListener('change',redraw);section.append(choice,chart);redraw();
    const detail=el('details');detail.append(el('summary','','가정·비용·리밸런싱 민감도와 제약 확인'),objectView(c.assumptions));for(const [name,v] of Object.entries(c.results)){detail.append(el('h5','',name),el('p','','납입 '+v.contributed.toFixed(1)+' · 평가액 '+v.ending_wealth.toFixed(1)+' · 손익 '+v.profit.toFixed(1)+' · 계좌 거래비용 '+v.transaction_cost_paid.toFixed(2)),objectView(c.feasibility?.[name]||{}))}detail.append(objectView(c.sensitivity),list(c.limitations));section.append(detail);root.append(section);
    }
    const risk=el('details','wb-block');risk.append(el('summary','','환율·가계 복합 충격과 내부 집중'),el('p','hint',a.fx_stress?.limitation||''));for(const x of a.fx_stress?.scenarios||[]){risk.append(el('p','','주식 '+pct(x.equity_return_assumption)+' / 환율 '+pct(x.foreign_currency_return_in_base_assumption)+' → 제안액 변화 '+pct(x.portfolio_change_fraction)+' · 손실 '+x.loss_on_proposal_capital.toLocaleString('ko-KR')+' '+a.fx_stress.base_currency))}const joint=a.household?.joint_stress;if(joint && Array.isArray(joint.scenarios)){risk.append(el('h5','','소득·자산 동시 충격과 납입 재개'),el('p','hint',joint.scope));for(const row of joint.scenarios.filter(x=>x && [x.income_fraction_assumption,x.mortgage_rate_increase_assumption,x.cash_needed_if_contributions_paused,x.gap_against_reported_account_cash_only,x.income_needed_to_resume_planned_contribution].every(Number.isFinite)))risk.append(el('p','','소득 '+pct(row.income_fraction_assumption)+' 유지 / 가정 금리 +'+pct(row.mortgage_rate_increase_assumption)+' · 납입 중단 시 6개월 필요 현금 '+row.cash_needed_if_contributions_paused.toLocaleString('ko-KR')+' · 보고 계좌 현금만으로 부족한 금액 '+row.gap_against_reported_account_cash_only.toLocaleString('ko-KR')+' · 예정 납입 재개에 필요한 월 소득 '+row.income_needed_to_resume_planned_contribution.toLocaleString('ko-KR')+' '+a.fx_stress.base_currency));risk.append(el('p','hint',joint.liquidity_basis),el('p','hint',joint.limitations))}risk.append(objectView(a.lookthrough||{}),objectView(a.household||{}));root.append(risk);
    if(a.costs){const costs=el('details','wb-block');costs.append(el('summary','','납입 비용·환전 조건·거래 수량 예시'),objectView(a.costs));root.append(costs)}
  }
  function coverageView(root,q){
    const rows=doc.extensions?.coverage_ledger||[];if(!rows.length)return;
    const box=el('details','wb-block');box.append(el('summary','','자료 충분성 · 고정 '+rows.length+'개 요구'));
    for(const row of rows){if(!Array.isArray(row.input_ids)||!Array.isArray(row.claim_ids)||!Array.isArray(row.fact_ids)||!Array.isArray(row.missing_causes)){box.append(el('p','notice','자료 충분성 기록의 형식을 확인해야 해요. 원본 판단은 보존돼요.'));continue}const verdict=q?.output.coverage?.find(x=>x.id===row.id);const entry=el('details');entry.append(el('summary','',row.id+' · '+(row.retrieved?'수집됨':'수집 미완료')+' / '+(row.delivered?'전달됨':'전달 미확인')+' / '+(verdict?evidenceStatus(verdict.status):'독립 검토 대기')),el('p','',verdict?.reason||row.next_action),el('p','hint','담당 '+row.owner+' · 입력 '+row.input_ids.length+'건 · 연결 주장 '+row.claim_ids.length+'개'),list(row.missing_causes),sourceButtons(row.fact_ids));box.append(entry)}root.append(box);
  }
  function campaignView(root){
    const c=doc.extensions?.quality_campaign;if(!c)return;const box=el('details','wb-block');box.open=true;box.append(el('summary','','독립 평가와 개선 '+c.completed_improvements+' / '+c.required_improvements+'회'),el('p','hint','기준 보고서 평가 후 개선·새 판단·독립 평가를 반복해요. 실행 5회 완료와 보고서 엄격 기준 통과는 별개예요.'));
    if(c.checkpoint?.status==='running')box.append(el('p','notice',(c.checkpoint.round?'개선 '+c.checkpoint.round+'회':'기준 보고서')+' · '+(c.checkpoint.stage==='generation'?'판단 생성':'독립 평가')+' 진행 중이에요. 완료한 기록부터 표시해요.'));
    if(c.checkpoint?.status==='failed')box.append(el('p','notice','현재 단계가 중단됐어요. 원본과 완료한 회차를 보존했으며 재개 시 여기서 이어가요.'));
    for(const r of c.rounds){const row=el('details');row.append(el('summary','',(r.round?'개선 '+r.round+'회':'기준 보고서')+' · '+r.score.total+'점 · '+(r.score.strict_pass?'엄격 기준 충족':'미충족')),list(r.changes),el('p','hint','독립 응답 '+r.evaluator_output_id+' · '+r.recorded_at),button('이 회차 판단 열기',async()=>{runId=r.run_id;signature='';await refresh()}));box.append(row)}box.append(el('p','',c.G6==='pass'?'G6 · 서로 다른 평가 호출로 5회 개선 완료':'G6 · 5회 평가 이력을 확인하는 중이에요.'));root.append(box);
  }
  function qualityView(root){
    campaignView(root);
    const q=doc.extensions?.evaluation,c=doc.components.find(x=>x.id==='evaluator');
    root.append(el('h4','','독립 보고서 품질 평가'));coverageView(root,q);
    if(!q){root.append(el('p','hint',c?.status==='running'?'평가자가 당시 근거와 보고서를 대조하고 있어요.':c?.status==='failed'?'평가가 완료되지 못했어요. 제안 원본은 보존되어 있어요.':'아직 이 제안의 독립 품질 평가가 없어요.'));if(doc.run.status==='completed'){const b=button('이 제안 독립 평가하기',()=>decisionAction('evaluate'));b.disabled=c?.status==='running';root.append(b)}return}
    if(c?.status==='failed')root.append(el('p','error','최근 평가가 중단됐어요. 아래는 이전에 저장된 평가예요.'),button('평가 다시 실행',()=>decisionAction('evaluate')));
    const heading=el('div','wb-score-heading');heading.append(el('b','wb-score',q.score.total+' / 100'),el('div','',q.output.summary));root.append(heading,el('p','hint','기준 v'+q.rubric.version+' · 자료 기준 '+q.as_of+' · 평가 '+q.evaluated_at+' · 보고서 품질이며 미래 수익 점수가 아니에요.'));
    if(q.score.gates){const gates=el('div','wb-block'),labels={G1:'자료 무결성',G2:'핵심 주장과 반대 근거',G3:'독립 계산',G4:'개인 적합성과 권한',G5:'필수 자료 공백 해소'};gates.append(el('strong','',q.score.strict_pass?'보고서 엄격 기준 충족':'보고서 엄격 기준 미충족'));for(const [id,state] of Object.entries(q.score.gates)){const review=q.output.gates.find(x=>x.id===id);gates.append(el('p','',id+' '+labels[id]+' · '+evidenceStatus(state)+' · '+(review?.reason||'')));if(review&&review.status!==state)gates.append(el('p','notice','평가자 판단 '+evidenceStatus(review.status)+' 이후 코드 검사가 '+evidenceStatus(state)+'으로 판정했어요. 아래 계산·근거 지적을 함께 확인하세요.'))}gates.append(list(q.score.deterministic_findings||[]),el('p','hint','85점 이상·모든 기준 3단계 이상·필수 gate 충족·중요 결함 0개를 함께 확인해요. 5회 실행 완료 여부와는 별개예요.'));root.append(gates)}
    const stability=doc.extensions?.evaluation_stability;if(stability){const check=el('details','wb-block');check.append(el('summary','','이 보고서의 후속 표현·순서 시험 · '+(stability.passed?'사전 조건 충족':'사전 조건 미충족')),el('p','',stability.valid_outputs+'/'+stability.cases+'개 유효 응답 · 점수 범위 '+(stability.total_score_range==null?'미확인':stability.total_score_range.toFixed(1))+'점 · gate 판정 '+(stability.gate_invariance?'동일':'다름/미확인')),el('p','hint','이 보고서를 고정해 별도로 실행한 후속 시험이에요. 원래 평가 점수·gate를 수정하지 않으며 투자 성과·정확성 보증이 아니에요.'),el('p','hint',stability.scope),objectView(stability));root.append(check)}
    if(q.output.red_flags.length){const box=el('div','notice');box.append(el('strong','','먼저 해결할 결함'),list(q.output.red_flags));root.append(box)}
    const chart=el('div','wb-quality-grid');for(const criterion of q.rubric.criteria){const r=q.output.criteria.find(x=>x.id===criterion.id),item=el('details','wb-quality-item');const summary=el('summary');summary.append(el('span','',criterion.label),el('b','',r.score+' / 4'),bar(r.score/4));item.append(summary,el('p','',r.reason),el('p','hint','가중치 '+criterion.weight+'점 · '+criterion.requirement));
      for(const check of (r.checks||[])){const atom=el('details');atom.append(el('summary','',check.id+' · '+evidenceStatus(check.status)),el('p','',check.observation),el('p','hint',check.counterevidence),list(check.evidence_paths));item.append(atom)}
      if(r.missing.length)item.append(el('h5','','부족한 근거'),list(r.missing));if(r.improvements.length)item.append(el('h5','','개선할 내용'),list(r.improvements));item.append(el('h5','','평가에 사용한 근거'));
      r.evidence_paths.forEach((path,index)=>{const detail=el('details');let value=c?.inputs;for(const part of path.slice(1).split('/'))value=value?.[part.replace(/~1/g,'/').replace(/~0/g,'~')];detail.append(el('summary','','근거 '+(index+1)+' 펼치기'),el('p','hint',path),objectView(value));item.append(detail)});chart.append(item)}root.append(chart,el('p','hint',q.score.rule));
    const references=el('details','wb-block');references.append(el('summary','','평가 기준에 참고한 공개 보고서'));
    for(const match of (c?.inputs?.reference_guide||'').matchAll(/\[([^\]]+)\]\((https:\/\/[^)]+)\)/g)){const a=el('a','',match[1]);a.href=match[2];a.target='_blank';a.rel='noopener';const p=el('p');p.append(a);references.append(p)}root.append(references);
  }
  function choose(id,stage=null){saveDraft();selected=id;selectedStage=stage;tab='analysis';epoch++;chatSignature='';nodes();pane();resetChat();loadChat();$('wb-title').focus({preventScroll:true});if(innerWidth<1100)$('wb-title').scrollIntoView({block:'start',behavior:'smooth'})}
  function setTab(name){tab=name;pane()}
  function sourceButtons(ids){const row=el('div','source-chips');for(const id of ids)row.append(button(id,()=>{setTab('sources');document.getElementById('wb-source-'+id)?.scrollIntoView({block:'nearest',behavior:'smooth'})},'source-chip'));return row}
  function judgmentReport(root,report){
    if(!report)return;const article=el('article','judgment-report');
    article.append(el('h3','',report.title),el('p','hint',report.as_of+' · 상세 판단 리포트'));
    const decision=doc.portfolio?.proposal;article.append(el('p','notice','이 문서는 선택한 역할·단계의 의견이에요. 공식 최종 상태: '+(decision?({hold:'유지',adjust:'조정 제안',defer:'보류'}[decision.action]||decision.action):'판단 진행 중')+' · 주문 지시가 아니에요. 리더 종합안도 최종 검증 결과와 함께 읽어주세요.'));
    for(const [key,label] of [['portfolio_context','현재 포트폴리오와 투자 맥락'],['market_context','현재 시황과 투자 영향'],['decision_method','검토 기준과 판단 절차'],['conclusion','이 역할의 최종 의견']]){const section=el('section');section.append(el('h4','',label));for(const paragraph of report[key].split(/\n\s*\n/))section.append(el('p','',paragraph));article.append(section)}
    article.append(sourceButtons(report.evidence_ids||[]));root.append(article);
  }
  function pane(){
    const c=current(),root=$('wb-pane');root.replaceChildren();
    $('wb-role').textContent=c?c.role+' / '+(statuses[c.status]||c.status):'PORTFOLIO / OVERVIEW';
    $('wb-title').textContent=c?.label||'이번 판단의 전체 모습';$('wb-description').textContent=c?.description||'실제 보유, 이번 제안과 관점 차이를 비교해요.';
    document.querySelectorAll('[data-wb-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.wbTab===tab)));
    if(tab==='sources'){sources(root,c);return}
    if(tab==='contract'){
      const url=c?.contract||'/api/contracts/workbench';const a=el('a','',c?'이 역할의 출력 JSON Schema':'작업실 JSON Schema');a.href=url;a.target='_blank';a.rel='noopener';root.append(a,el('p','hint','내려받는 결과에는 이 실행의 투자 맥락이 포함될 수 있어요.'));
      root.append(button('선택한 결과 JSON 내려받기',()=>{const blob=new Blob([JSON.stringify(c||doc,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='mara-'+runId+'-'+selected+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0)}));
      root.append(el('pre','',JSON.stringify(c?c.output:doc,null,2)));if(c){if(c.extensions?.output_validation?.length)root.append(el('h4','','응답 검증 · 교정 이력'),objectView(c.extensions.output_validation));root.append(el('h4','','실행과 가이드 버전'),objectView(c.records))}return;
    }
    if(tab==='inputs'){
      root.append(el('h4','','다른 역할과의 연결'));const links=doc.edges.filter(e=>!c||e.from===c.id||e.to===c.id);const group=el('div','wb-relations');
      for(const e of links){const line=el('div','wb-relation');for(const [i,id] of [e.from,e.to].entries()){if(i)line.append(el('span','hint','→ '+e.label+' →'));line.append(button(doc.components.find(c=>c.id===id)?.label||id,()=>choose(id)))}group.append(line)}root.append(group);
      if(c){root.append(el('h4','','분석 당시 전달한 입력'),el('p','hint','실행에 고정된 입력이에요. 대화에서 한 설명은 투자 설정을 자동 변경하지 않아요.'),objectView(c.inputs))}return;
    }
    if(!c){overview(root);return}
    if(c.output?.judgment_report)judgmentReport(root,c.output.judgment_report);
    else root.append(el('p','hint','이 실행에는 새 형식의 상세 판단 리포트가 없어요. 아래는 당시 저장된 원문이며 새 내용으로 보충하지 않았어요.'));
    if(c.id==='evaluator'){qualityView(root);return}
    if(c.extensions?.research_activity?.length){const activity=el('details','wb-block');activity.append(el('summary','','추가 기업 조사 · '+c.extensions.research_activity.filter(x=>x.kind==='research_tool_result').length+'개 도구 결과'),objectView(c.extensions.research_activity));root.append(activity)}
    const summary=el('div','wb-summary');summary.append(chip(statuses[c.status],c.status),el('p','',c.summary));root.append(summary);
    if(c.status==='needs_input')root.append(button('투자 설정에서 답 반영하기',()=>document.getElementById('tab-setup').click()));
    if(c.source_ids.length)root.append(sourceButtons(c.source_ids));
    if(!c.blocks.length)root.append(el('p','empty','이 역할의 출력이 아직 없어요. 대화로 역할과 필요한 자료를 확인할 수 있어요.'));
    for(const block of c.blocks){const box=el('section','wb-block');box.append(el('h4','',block.title));
      if(block.key==='research_tools'){researchTools(box,block.value)}
      else if(block.key==='decision_status'){decisionStatus(box,block.value)}
      else if(block.key==='monthly_allocation'){monthlyPlan(box,block.value)}
      else if(block.key==='findings'){findings(box,block.value)}
      else if(block.key==='household'){household(box,block.value)}
      else if(block.key==='analysis_skills'){for(const skill of block.value)box.append(el('p','',skill.label+' · v'+skill.version))}
      else if(block.kind==='weights'){const map=block.value;for(const [s,w] of Object.entries(map).sort((a,b)=>b[1]-a[1])){const row=el('div','exposure-row');row.append(el('span','',symbols(s)),el('b','',pct(w)),bar(w));box.append(row)}}
      else box.append(objectView(block.value));root.append(box)}
  }
  function findings(root,items){
    const category={personal_context:'개인 맥락 확인',constraint:'입력 조건 검토',market_evidence:'시장 자료 수집',capability:'분석 도구 보강',execution:'주문 전 확인',uncertainty:'불확실성 관리'};
    for(const item of items||[]){const card=el('article','wb-tool-call');card.append(chip(item.blocks_proposal?'제안 보류 사유':'추가 확인'),el('b','',category[item.category]||item.category),el('p','',item.subject+' · '+item.reason),el('p','hint','해소 기준: '+item.resolution));
      if(item.owner==='user'||item.owner==='context')card.append(button('투자 설정 확인',()=>document.getElementById('tab-setup').click()));
      else if(doc.components.some(c=>c.id===item.owner))card.append(button('담당 역할 보기',()=>choose(item.owner)));
      root.append(card)}
  }
  function decisionStatus(root,value){
    root.append(chip(value.status==='blocked'?'제안 보류':'사용자 검토 가능'),el('p','hint','배분 계획에 대한 판단이에요. 실제 주문은 승인하거나 전송하지 않아요.'));
    if(value.funding_availability==='conditional_on_deposit')root.append(el('p','notice','향후 납입을 전제로 한 계획이에요. 현재 입금된 금액으로 해석하지 않아요.'));
    if(value.numeric_blockers?.length&&!value.findings?.length)root.append(el('h4','','수치·필수 자료 검증'),list(value.numeric_blockers));
    findings(root,value.findings);
    if(!value.findings?.length&&value.analyst_blockers?.length)root.append(list(value.analyst_blockers));
    const detail=el('details');detail.append(el('summary','','주문 전에 확인할 항목'),list(value.execution_checks||[]));root.append(detail);
  }
  function monthlyPlan(root,value){
    root.append(el('p','',value.status==='blocked'?'보류 중인 참고 배분 · 납입 지시가 아니에요.':'실제 납입 후 재검토할 목표 배분'),el('p','hint',value.schedule==='monthly'?'매월 한 번 기준':'입력한 일수 간격마다 납입'));
    for(const [symbol,amount] of Object.entries(value.amounts||{})){const row=el('div','exposure-row');row.append(el('span','',symbols(symbol)),el('b','',Number(amount).toLocaleString('ko-KR')+' '+value.currency));root.append(row)}
    root.append(el('p','hint',value.rule));
  }
  function household(root,value){
    const labels={property_value:'부동산 시가',mortgage_balance:'담보대출 잔액',property_equity:'부동산 자기자본',outside_emergency_cash:'별도 비상 현금',reported_liquid_cash:'사용자 진술 전체 현금 (합산 안 함)',monthly_debt_payment:'월 대출 상환액',monthly_surplus_before_investing:'납입 전 월 잉여',monthly_contribution:'월 납입 계획',monthly_remaining_after_investing:'납입 후 월 잔여'};
    const unit=value.base_currency==='KRW'?'원':' '+(value.base_currency||'');const dl=el('dl','wb-data');for(const [key,label] of Object.entries(labels)){dl.append(el('dt','',label),el('dd','',value[key]==null?'미확인':Number(value[key]).toLocaleString('ko-KR')+unit))}root.append(dl);
    root.append(el('p','hint',value.debt_payment_in_expenses==='yes'?'대출 상환은 월 지출에 포함되어 다시 차감하지 않았어요.':value.debt_payment_in_expenses==='no'?'대출 상환을 별도 지출로 반영해요.':'대출 상환의 지출 포함 여부가 미확인이에요.'),el('p','hint',value.limits));if(value.reported_liquid_cash_scope)root.append(el('p','hint',value.reported_liquid_cash_scope));
  }
  function researchTools(root,value){
    const labels={collected:'수집됨',failed:'조회 실패',skipped:'이번 범위에서 제외'};
    const reasons={future_observation:'기준일 뒤의 관측이라 현재 판단에서 제외했어요.',stale_observation:'허용 기간보다 오래된 관측이에요.',identity_mismatch:'요청한 종목과 공급자의 기업 식별이 일치하지 않아요.',currency_mismatch:'요청한 기준통화와 다른 값이에요.',observation_timezone_missing:'관측 시각의 시간대를 확인할 수 없어요.',insufficient_observations:'계산에 필요한 관측 수가 부족해요.',source_format_changed:'공급자 문서 형식이 달라 파서 보완이 필요해요.',source_structure_changed:'공급자 응답의 필수 필드나 타입이 달라졌어요.',required_source_field_missing:'필요한 원문 항목이 없어요.',quote_not_observed:'공급자 응답에 호가가 없어요. 최근 거래량·운용사 스프레드로 사전 검토하고 주문 직전 호가는 별도로 확인해요.',active_evidence_budget:'분석 자료 크기 한도',financial_evidence_budget:'재무 자료 크기 한도',collection_time_budget:'수집 시간 한도',time_budget_or_timeout:'응답 대기 시간 초과',SEC_identifier_unavailable:'SEC 기업 식별자 미확인',SEC_identity_source_failed:'SEC 기업 식별 확인에 실패해 재무 조회 제외',fund_profile_unavailable:'상품 정보를 확인하지 못해 구성 조회 제외',unsupported_or_invalid_data:'지원 형식·단위·시점 조건 미충족',network_unavailable:'외부 연결 실패',http_403:'공급자 접근 거부',http_429:'공급자 요청 한도 초과'};
    root.append(el('p','hint','기본 기업 수집은 보유 우선 최대 8개예요. 에이전트는 별도 조사 도구로 후보를 더 수집하고 페이지별로 읽을 수 있어요. 역할의 추가 기업 조사 기록에서 실제 범위를 확인하세요. ITOT·IVV는 분산 대안 비교용이며 수집 성공이 편입 결정을 뜻하지 않아요.'));
    for(const tool of value.tools||[]){
      const calls=(value.calls||[]).filter(c=>c.tool===tool.id),ok=calls.filter(c=>c.status==='collected').length;
      const detail=el('details','wb-tool');detail.open=!!calls.some(c=>c.status==='failed');
      detail.append(el('summary','',tool.label+' · '+ok+'/'+calls.length+' 수집'),el('p','hint',tool.provides));
      if(!calls.length)detail.append(el('p','hint','이번 실행의 대상이 없어요.'));
      for(const call of calls){
        const row=el('div','wb-tool-call');row.append(chip(labels[call.status]||call.status),el('b','',call.target),el('p','hint',reasons[call.reason]||call.reason));
        if(call.fact_ids?.length)row.append(sourceButtons(call.fact_ids));
        for(const ref of call.raw_refs||[]){const a=el('a','', '수집 원문 · '+ref.sha256.slice(0,10)+' · '+ref.retrieved_at);a.href='/api/research-raw/'+doc.run.id+'/'+ref.sha256;a.target='_blank';a.rel='noopener';row.append(a)}
        detail.append(row);
      }root.append(detail);
    }
    const omitted=value.selection?.not_deeply_collected||[];
    if(omitted.length)root.append(el('p','notice','상세 수집 범위 밖: '+omitted.join(', ')));
    root.append(el('p','hint','원본 응답은 해시와 수집 시각으로 보존해요. 자료가 오래됐거나 일부 조회에 실패하면 해당 항목은 판단 근거로 채우지 않아요.'));
  }
  function sources(root,c){
    const used=new Set(c?.source_ids||[]);root.append(el('p','hint',c?'직접 인용 '+used.size+'개 · 아래에 이번 실행의 공통 근거도 함께 표시해요.':'당시 수집한 원본 근거예요. 관측 시점과 적용 기한을 함께 확인해요.'));
    for(const s of [...doc.sources].sort((a,b)=>Number(used.has(b.id))-Number(used.has(a.id)))){
      const card=el('article','wb-source');card.id='wb-source-'+s.id;card.append(chip(used.has(s.id)?'이 역할이 인용':'공통 자료'),el('h4','',s.topic+' · '+s.id),el('p','hint','발행 '+s.published_at+' · 이용 가능 '+s.known_at+' · 유효 기한 '+s.valid_until+(s.active?'':' · 현재 판단에서 제외')));
      const detail=el('details');detail.append(el('summary','','원본 근거 펼치기'),el('p','source-text',s.text));card.append(detail);
      if(s.uncertainty)card.append(el('p','notice',s.uncertainty));
      try{const url=new URL(s.source);if(url.protocol==='https:'){const a=el('a','',url.hostname+' 원문');a.href=url.href;a.rel='noopener noreferrer';a.target='_blank';card.append(a)}}catch(e){}
      if(scope==='portfolio')for(const raw of s.raw_refs||[]){if(!/^[a-f0-9]{64}$/.test(raw.sha256))continue;const p=el('p'),a=el('a','','수집 당시 보존 원문 · '+raw.sha256.slice(0,10));a.href='/api/research-raw/'+runId+'/'+raw.sha256;a.target='_blank';a.rel='noopener';p.append(a);card.append(p)}
      root.append(card);
    }if(!doc.sources.length)root.append(el('p','empty','저장된 근거가 없어요.'));
  }
  function overview(root){
    reportCase(root);
    const p=doc.portfolio;
    const finished=doc.components.filter(c=>['completed','blocked','needs_input'].includes(c.status)).length;
    const strip=el('div','wb-progress');strip.append(el('span','',finished+' / '+doc.components.length+' 역할 기록'),bar(finished/doc.components.length));root.append(strip);
    if(!p){qualityView(root);root.append(el('p','wb-summary',doc.run.message),el('p','hint','아직 종합된 제안이 없어요. 왼쪽 역할을 선택하면 완료한 분석과 추가 확인을 볼 수 있어요.'));return}
    quantitativeView(root);qualityView(root);
    if(p.risk_budget?.scope==='analysis_only'){const b=p.risk_budget;root.append(el('p','notice',`분석 전용 · 이번 제안의 충격 비교 예산 ${pct(b.effective_fraction)} / 기존 기준 ${pct(b.reference_fraction)}. 실제 감내손실 확인이나 주문 가능한 제안이 아니에요.`))}
    const pr=p.proposal,capital=p.funding?.proposal_capital??p.actual.nav;
    const decision=el('div','wb-summary');decision.append(chip(actions[pr.action]||pr.action,pr.action),el('p','',pr.rationale));root.append(decision);
    if(pr.decision_status){const detail=el('details','wb-block');detail.open=pr.action==='defer';detail.append(el('summary','','판단 상태와 남은 확인'));decisionStatus(detail,pr.decision_status);root.append(detail)}
    if(pr.monthly_allocation){const plan=el('section','wb-block');plan.append(el('h4','','정기 납입 배분 계획'));monthlyPlan(plan,pr.monthly_allocation);root.append(plan)}
    if(pr.action==='defer')root.append(el('p','notice','보류된 비중은 검토 중인 후보예요. 확정안이나 주문 가능한 포트폴리오가 아니에요.'));
    const metrics=el('div','metrics');for(const [label,value] of [['실제 보유 평가액',p.actual.nav],['제안 기준액',capital],['추가 필요 자금',p.funding?.additional_funding_needed??0]]){const box=el('div','metric');box.append(el('span','label',label),el('b','',Number(value).toLocaleString('ko-KR')+' '+p.base_currency));metrics.append(box)}root.append(metrics);
    const maps=[p.actual.nav?p.actual.weights:null,pr.weights,p.previous?.proposal?.weights||null],names=['실제 보유','이번 제안','지난 제안'];
    root.append(el('h4','','실제 보유와 제안 비중'));for(const s of [...new Set(maps.flatMap(w=>Object.keys(w||{})))]){const row=el('div','allocation-row');row.append(el('b','allocation-symbol',symbols(s)));const group=el('div');maps.forEach((w,i)=>{const line=el('div','allocation-line');line.append(el('span','bar-label',names[i]),bar(w?.[s]||0,['actual','proposal','previous'][i]),el('b','bar-value',w?pct(w[s]||0):'비교 없음'));group.append(line)});row.append(group);root.append(row)}
    const perspectives=doc.components.filter(c=>c.kind==='perspective'&&c.output?.weights);root.append(el('h4','','관점별 차이'));const scroll=el('div','scroll'),table=el('table','wb-comparison'),head=el('tr');head.append(el('th','','자산'));for(const c of perspectives)head.append(el('th','',c.label));table.append(head);
    for(const s of [...new Set(perspectives.flatMap(c=>Object.keys(c.output.weights)))]){const tr=el('tr');tr.append(el('th','',symbols(s)));for(const c of perspectives){const td=el('td');td.append(el('b','',pct(c.output.weights[s]||0)),bar(c.output.weights[s]||0));tr.append(td)}table.append(tr)}scroll.append(table);root.append(scroll);
    const risk=p.validation.final_numeric,h=risk.historical||{},rm=risk.metrics||{},monthlyRisk=h.status!=='available'&&doc.extensions?.analysis?.comparison?.available?doc.extensions.analysis.comparison.results?.proposal:null;root.append(el('h4','','위험 평가와 미확인 항목'));
    const riskCards=el('div','metrics');for(const [label,v] of [['가정한 시나리오 손실',pct(risk.scenario_loss_fraction)],['최대 종목 비중',pct(rm.max_position_fraction)],[monthlyRisk?'월별 NAV 연환산 변동성':'연환산 변동성',pct(monthlyRisk?.annualized_volatility??h.annualized_volatility)],[monthlyRisk?'월말 최대 낙폭':'과거 최대 낙폭',pct(monthlyRisk?.month_end_max_drawdown??h.max_drawdown)],['Sharpe ratio',h.sharpe==null?'미확인':h.sharpe.toFixed(2)],['정성 검증',p.validation.final_critique.qualitative_pass?'조건 충족':'추가 확인']]){const box=el('div','metric');box.append(el('span','label',label),el('b','',v));riskCards.append(box)}root.append(riskCards,el('p','hint','시나리오 손실은 가정이에요. 과거 지표는 현재 비중을 재현한 가상 통계이며 실제 성과가 아니에요.'));
    for(const [title,values] of [['검증 결과',[...(risk.errors||[]),...(risk.missing||[]),...(risk.warnings||[])].map(message=>monthlyRisk&&/변동성.*자료 부족/.test(message)?'일별 시세 기준: '+message+' · 월별 NAV 통계는 위에서 별도 계산했어요.':message)],['남은 의견 차이',pr.dissent],['다음 확인',pr.next_checks]]){root.append(el('h4','',title),list(values||[]))}
    if(monthlyRisk)root.append(el('p','notice','표시한 과거 변동성·낙폭은 위 USD 월별 NAV 가상 비교의 값이에요. 실제 원화 계좌 성과·일중 손실과 다르며, 무위험 수익률을 확인하지 않은 Sharpe는 계산하지 않아요.'));
    const perf=p.performance;root.append(el('h4','','결과와 다음 평가'),el('p','',perf?(perf.limitation||'확인된 기간 수익률: '+pct(perf.modified_dietz)):'최초 평가예요. 아직 비교할 실제 투자 결과가 없어요.'),el('p','hint','다음 평가 '+p.next_evaluation+' · 리밸런싱 검토 '+p.next_rebalance));
    root.append(button('리더에게 판단 근거 묻기',()=>choose('leader')));
  }
  function resetChat(){
    chatSignature='';
    $('wb-question').value=drafts.get(key())||'';$('wb-chat-messages').replaceChildren();$('wb-chat-suggestions').replaceChildren();$('wb-chat-status').textContent='';
    const c=current();$('wb-chat-title').textContent=c?c.label+'와 대화':'역할을 선택해 질문하세요';$('wb-chat-context').textContent=c?doc.run.as_of+' 실행 · '+(doc.run.mode==='demo'?'합성 응답':'저장된 맥락으로 답변'):'';
    $('wb-send').disabled=!c;$('wb-question').disabled=!c;
    if(c){const questions=c.kind==='evidence'?['확인된 사실과 아직 모르는 점을 나눠주세요.','이번 시장 변화가 내 제약에 어떤 영향을 주나요?']:['이 판단의 가장 약한 근거는 무엇인가요?','어떤 사실이 달라지면 판단을 바꾸나요?'];for(const q of questions)$('wb-chat-suggestions').append(button(q,()=>{$('wb-question').value=q;$('wb-question').focus()},'wb-suggestion'))}
  }
  async function loadChat(){
    if(!current())return;const ticket=epoch,k=key();
    try{const data=await api('/api/dialogue/'+k);if(ticket!==epoch||k!==key())return;
      if(data.schema_version!=='mara.dialogue/1.0.0'||data.run_id!==runId||data.agent_id!==selected)throw Error('대화 범위 또는 계약이 일치하지 않아요.');
      const sig=JSON.stringify(data);if(sig!==chatSignature){chatSignature=sig;const root=$('wb-chat-messages');root.replaceChildren();
        for(const m of data.messages){const box=el('article','wb-chat-message '+m.role);box.append(el('p','eyebrow',m.role==='user'?'나':m.role==='status'?'실행 상태':current().label),el('p','wb-answer',m.text));if(m.evidence_ids.length)box.append(sourceButtons(m.evidence_ids));if(m.uncertainties.length){const details=el('details');details.append(el('summary','','불확실성과 한계'),list(m.uncertainties));box.append(details)}
          if(m.proposed_change&&m.proposed_change.scope!=='none'){const change=el('div','wb-proposed-change');change.append(el('strong','','판단 변경 제안'),el('p','',m.proposed_change.summary),el('p','hint',m.proposed_change.reason));if(m.proposed_change.scope==='reasoning'){const apply=button('변경 반영 · 후속 재평가',()=>decisionAction('revise',m.request_id),'primary');apply.disabled=doc.run.status!=='completed'||doc.extensions?.decision_actions?.some(x=>x.result.status==='running');change.append(apply,el('p','hint','당시 자료로 새 실행을 만들고 검증·종합·품질 평가를 다시 해요.'))}else change.append(button('투자 설정에서 변경하기',()=>document.getElementById('tab-setup').click()));box.append(change)}root.append(box)}
        if(!data.messages.length)root.append(el('p','hint','이 실행과 에이전트에 대한 첫 질문을 남겨보세요.'));
        root.scrollTop=root.scrollHeight;
      }
      $('wb-send').disabled=data.pending;$('wb-chat-status').textContent=data.pending?'답변을 작성하고 있어요…':'대화는 이 실행에 저장돼요.';
    }catch(e){if(ticket===epoch){$('wb-chat-status').textContent=e.message;$('wb-send').disabled=true}}
  }
  async function refresh(){
    if(loading)return;loading=true;const ticket=epoch,requestedScope=scope;
    try{
      const r=await api('/api/workbench/'+scope);if(ticket!==epoch||requestedScope!==scope)return;
      const selectedValue=runId,select=$('wb-run');select.replaceChildren(...r.runs.map(r=>{const o=el('option','',r.as_of+' · '+(statuses[r.status]||r.status)+(r.revision_of?' · 수정본':''));o.value=r.id;return o}));
      if(!r.runs.length){runId=null;doc=null;signature='';$('wb-content').hidden=true;$('wb-empty').hidden=false;select.append(el('option','','아직 분석 없음'));return}
      runId=r.runs.some(r=>r.id===selectedValue)?selectedValue:r.runs[0].id;select.value=runId;
      const id=runId,d=await api('/api/workbench/'+scope+'/'+id);if(ticket!==epoch||id!==runId)return;
      const sig=JSON.stringify(d);if(sig!==signature){saveDraft();signature=sig;render(d);resetChat()}
      $('report-document').hidden=!d.run.report_id;
      if(d.run.report_id&&$('report-document').dataset.reportId!==d.run.report_id){
        const report=await api((scope==='demo'?'/api/report/':'/api/portfolio/report/')+d.run.report_id);
        if(ticket!==epoch||id!==runId)return;
        window.MaraReport?.render(report);$('report-document').dataset.reportId=d.run.report_id;
      }
      $('wb-message').textContent='';await loadChat();
    }catch(e){if(ticket===epoch){$('wb-message').textContent=e.message;$('wb-content').hidden=true;doc=null;$('wb-send').disabled=true}}
    finally{loading=false;if(ticket!==epoch)refresh()}
  }
  function clear(){epoch++;doc=null;signature='';chatSignature='';$('wb-content').hidden=true;$('wb-question').value='';$('wb-chat-messages').replaceChildren();$('wb-send').disabled=true}
  function openReport(row){const nextScope=row.body.mode==='demo'?'demo':'portfolio';if(runId===row.body.run_id&&scope===nextScope)return;saveDraft();scope=nextScope;runId=row.body.run_id;selected='overview';$('wb-scope').value=scope;clear();refresh()}
  $('wb-scope').onchange=()=>{saveDraft();scope=$('wb-scope').value;runId=null;selected='overview';clear();refresh()};
  $('wb-run').onchange=()=>{saveDraft();runId=$('wb-run').value;selected='overview';clear();refresh()};
  $('wb-refresh').onclick=()=>refresh();document.querySelectorAll('[data-wb-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.wbTab));
  $('wb-chat-form').onsubmit=async e=>{
    e.preventDefault();if(!current()||$('wb-send').disabled)return;const message=$('wb-question').value.trim();if(!message){$('wb-chat-status').textContent='질문을 입력해주세요.';return}
    const ticket=epoch,k=key();$('wb-send').disabled=true;$('wb-chat-status').textContent='질문을 전달하고 있어요…';
    const request_id=crypto.randomUUID();
    try{const body={run_id:runId,agent_id:selected,request_id,message};if(current().source_output_id)body.source_output_id=current().source_output_id;await api('/api/dialogue/'+scope,body);if(ticket!==epoch||k!==key())return;$('wb-question').value='';drafts.delete(k);chatSignature='';await loadChat()}
    catch(e){if(ticket===epoch){$('wb-chat-status').textContent=e.message;$('wb-send').disabled=false}}
  };
  setInterval(()=>{if(!$('report-panel').hidden){loadChat();if(doc?.run.status==='running'||doc?.extensions?.quality_campaign?.checkpoint?.status==='running'||doc?.extensions?.decision_actions?.some(a=>a.result.status==='running')||doc?.components.some(c=>c.status==='running'))refresh()}},3000);
  return {refresh,openReport,render,choose,setTab,validateDocument};
})();
