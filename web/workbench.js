/* Generic component viewer. All analyst and user content is rendered as inert text. */
'use strict';
window.MaraWorkbench=(()=>{
  const $=id=>document.getElementById(id),el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
  const statuses={completed:'완료',running:'분석 중',pending:'대기',needs_input:'추가 확인',failed:'실패',interrupted:'중단',skipped:'이번 실행 없음',blocked:'보류'};
  const actions={hold:'유지',adjust:'조정 검토',defer:'보류'}, pct=x=>x==null?'미확인':(x*100).toFixed(1)+'%';
  const symbols=s=>s==='CASH'?'기준통화 현금':s==='USD_CASH'?'달러 현금':s;
  let scope='portfolio',runId=null,doc=null,selected='overview',tab='analysis',epoch=0,signature='',chatSignature='',loading=false;
  const drafts=new Map();
  async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Mara-CSRF':document.querySelector('meta[name="mara-csrf"]').content},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.error||'불러오지 못했어요.');return value}
  const key=()=>[scope,runId,selected].join('/'),current=()=>doc?.components.find(c=>c.id===selected);
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
    if(d?.schema_version!=='mara.workbench/1.0.0')throw Error('지원하지 않는 결과 계약이에요. 화면과 서버 버전을 확인해주세요.');
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
    $('wb-contract-tag').textContent='v1.0 · '+d.components.length+'개 역할';
    nodes();pane();
  }
  function nodes(){
    const nav=$('wb-nodes');nav.replaceChildren();
    const overview=button('전체 판단 · 비교',()=>choose('overview'),'wb-node wb-overview');overview.setAttribute('aria-pressed',String(selected==='overview'));nav.append(overview);
    let group='';for(const c of doc.components){if(c.role!==group){group=c.role;nav.append(el('p','wb-group',group==='R3'?'R3 · 독립 투자 관점':group+' · '+({R1:'판단의 기준',R2:'시장 이해',R4:'검증',R5:'종합',R6:'회고',F1:'기억'}[group]||'추가 역할')))}
      const b=button('',()=>choose(c.id),'wb-node');b.dataset.agent=c.id;b.setAttribute('aria-pressed',String(selected===c.id));b.append(el('span','wb-node-label',c.label));const state=el('span','wb-node-state',statuses[c.status]||c.status);state.dataset.status=c.status;b.append(state);nav.append(b)}
  }
  function choose(id){saveDraft();selected=id;tab='analysis';epoch++;chatSignature='';nodes();pane();resetChat();loadChat();$('wb-title').focus({preventScroll:true})}
  function setTab(name){tab=name;pane()}
  function sourceButtons(ids){const row=el('div','source-chips');for(const id of ids)row.append(button(id,()=>{setTab('sources');document.getElementById('wb-source-'+id)?.scrollIntoView({block:'nearest',behavior:'smooth'})},'source-chip'));return row}
  function pane(){
    const c=current(),root=$('wb-pane');root.replaceChildren();
    $('wb-role').textContent=c?c.role+' / '+(statuses[c.status]||c.status):'PORTFOLIO / OVERVIEW';
    $('wb-title').textContent=c?.label||'이번 판단의 전체 모습';$('wb-description').textContent=c?.description||'실제 보유, 이번 제안과 관점 차이를 비교해요.';
    document.querySelectorAll('[data-wb-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.wbTab===tab)));
    if(tab==='sources'){sources(root,c);return}
    if(tab==='contract'){
      const url=c?.contract||'/api/contracts/workbench';const a=el('a','',c?'이 역할의 출력 JSON Schema':'작업실 JSON Schema');a.href=url;a.target='_blank';a.rel='noopener';root.append(a,el('p','hint','내려받는 결과에는 이 실행의 투자 맥락이 포함될 수 있어요.'));
      root.append(button('선택한 결과 JSON 내려받기',()=>{const blob=new Blob([JSON.stringify(c||doc,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='mara-'+runId+'-'+selected+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0)}));
      root.append(el('pre','',JSON.stringify(c?.output??doc,null,2)));if(c){root.append(el('h4','','실행과 가이드 버전'),objectView(c.records))}return;
    }
    if(tab==='inputs'){
      root.append(el('h4','','다른 역할과의 연결'));const links=doc.edges.filter(e=>!c||e.from===c.id||e.to===c.id);const group=el('div','wb-relations');
      for(const e of links){const line=el('div','wb-relation');for(const [i,id] of [e.from,e.to].entries()){if(i)line.append(el('span','hint','→ '+e.label+' →'));line.append(button(doc.components.find(c=>c.id===id)?.label||id,()=>choose(id)))}group.append(line)}root.append(group);
      if(c){root.append(el('h4','','분석 당시 전달한 입력'),el('p','hint','실행에 고정된 입력이에요. 대화에서 한 설명은 투자 설정을 자동 변경하지 않아요.'),objectView(c.inputs))}return;
    }
    if(!c){overview(root);return}
    const summary=el('div','wb-summary');summary.append(chip(statuses[c.status],c.status),el('p','',c.summary));root.append(summary);
    if(c.status==='needs_input')root.append(button('투자 설정에서 답 반영하기',()=>document.getElementById('tab-setup').click()));
    if(c.source_ids.length)root.append(sourceButtons(c.source_ids));
    if(!c.blocks.length)root.append(el('p','empty','이 역할의 출력이 아직 없어요. 대화로 역할과 필요한 자료를 확인할 수 있어요.'));
    for(const block of c.blocks){const box=el('section','wb-block');box.append(el('h4','',block.title));
      if(block.kind==='weights'){const map=block.value;for(const [s,w] of Object.entries(map).sort((a,b)=>b[1]-a[1])){const row=el('div','exposure-row');row.append(el('span','',symbols(s)),el('b','',pct(w)),bar(w));box.append(row)}}
      else box.append(objectView(block.value));root.append(box)}
  }
  function sources(root,c){
    const used=new Set(c?.source_ids||[]);root.append(el('p','hint',c?'직접 인용 '+used.size+'개 · 아래에 이번 실행의 공통 근거도 함께 표시해요.':'당시 수집한 원본 근거예요. 관측 시점과 적용 기한을 함께 확인해요.'));
    for(const s of [...doc.sources].sort((a,b)=>Number(used.has(b.id))-Number(used.has(a.id)))){
      const card=el('article','wb-source');card.id='wb-source-'+s.id;card.append(chip(used.has(s.id)?'이 역할이 인용':'공통 자료'),el('h4','',s.topic+' · '+s.id),el('p','hint','발행 '+s.published_at+' · 이용 가능 '+s.known_at+' · 유효 기한 '+s.valid_until+(s.active?'':' · 현재 판단에서 제외')));
      const detail=el('details');detail.append(el('summary','','원본 근거 펼치기'),el('p','source-text',s.text));card.append(detail);
      if(s.uncertainty)card.append(el('p','notice',s.uncertainty));
      try{const url=new URL(s.source);if(url.protocol==='https:'){const a=el('a','',url.hostname+' 원문');a.href=url.href;a.rel='noopener noreferrer';a.target='_blank';card.append(a)}}catch(e){}
      root.append(card);
    }if(!doc.sources.length)root.append(el('p','empty','저장된 근거가 없어요.'));
  }
  function overview(root){
    const p=doc.portfolio;
    const finished=doc.components.filter(c=>['completed','blocked','needs_input'].includes(c.status)).length;
    const strip=el('div','wb-progress');strip.append(el('span','',finished+' / '+doc.components.length+' 역할 기록'),bar(finished/doc.components.length));root.append(strip);
    if(!p){root.append(el('p','wb-summary',doc.run.message),el('p','hint','아직 종합된 제안이 없어요. 왼쪽 역할을 선택하면 완료한 분석과 추가 확인을 볼 수 있어요.'));return}
    const pr=p.proposal,capital=p.funding?.proposal_capital??p.actual.nav;
    const decision=el('div','wb-summary');decision.append(chip(actions[pr.action]||pr.action,pr.action),el('p','',pr.rationale));root.append(decision);
    if(pr.action==='defer')root.append(el('p','notice','보류된 비중은 검토 중인 후보예요. 확정안이나 주문 가능한 포트폴리오가 아니에요.'));
    const metrics=el('div','metrics');for(const [label,value] of [['실제 보유 평가액',p.actual.nav],['제안 기준액',capital],['추가 필요 자금',p.funding?.additional_funding_needed??0]]){const box=el('div','metric');box.append(el('span','label',label),el('b','',Number(value).toLocaleString('ko-KR')+' '+p.base_currency));metrics.append(box)}root.append(metrics);
    const maps=[p.actual.nav?p.actual.weights:null,pr.weights,p.previous?.proposal?.weights||null],names=['실제 보유','이번 제안','지난 제안'];
    root.append(el('h4','','실제 보유와 제안 비중'));for(const s of [...new Set(maps.flatMap(w=>Object.keys(w||{})))]){const row=el('div','allocation-row');row.append(el('b','allocation-symbol',symbols(s)));const group=el('div');maps.forEach((w,i)=>{const line=el('div','allocation-line');line.append(el('span','bar-label',names[i]),bar(w?.[s]||0,['actual','proposal','previous'][i]),el('b','bar-value',w?pct(w[s]||0):'비교 없음'));group.append(line)});row.append(group);root.append(row)}
    const perspectives=doc.components.filter(c=>c.kind==='perspective'&&c.output?.weights);root.append(el('h4','','관점별 차이'));const scroll=el('div','scroll'),table=el('table','wb-comparison'),head=el('tr');head.append(el('th','','자산'));for(const c of perspectives)head.append(el('th','',c.label));table.append(head);
    for(const s of [...new Set(perspectives.flatMap(c=>Object.keys(c.output.weights)))]){const tr=el('tr');tr.append(el('th','',symbols(s)));for(const c of perspectives){const td=el('td');td.append(el('b','',pct(c.output.weights[s]||0)),bar(c.output.weights[s]||0));tr.append(td)}table.append(tr)}scroll.append(table);root.append(scroll);
    const risk=p.validation.final_numeric,h=risk.historical||{},rm=risk.metrics||{};root.append(el('h4','','위험 평가와 미확인 항목'));
    const riskCards=el('div','metrics');for(const [label,v] of [['가정한 시나리오 손실',pct(risk.scenario_loss_fraction)],['최대 종목 비중',pct(rm.max_position_fraction)],['연환산 변동성',pct(h.annualized_volatility)],['과거 최대 낙폭',pct(h.max_drawdown)],['Sharpe ratio',h.sharpe==null?'미확인':h.sharpe.toFixed(2)],['정성 검증',p.validation.final_critique.qualitative_pass?'조건 충족':'추가 확인']]){const box=el('div','metric');box.append(el('span','label',label),el('b','',v));riskCards.append(box)}root.append(riskCards,el('p','hint','시나리오 손실은 가정이에요. 과거 지표는 현재 비중을 재현한 가상 통계이며 실제 성과가 아니에요.'));
    for(const [title,values] of [['검증 결과',[...(risk.errors||[]),...(risk.missing||[]),...(risk.warnings||[])]],['남은 의견 차이',pr.dissent],['다음 확인',pr.next_checks]]){root.append(el('h4','',title),list(values||[]))}
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
        for(const m of data.messages){const box=el('article','wb-chat-message '+m.role);box.append(el('p','eyebrow',m.role==='user'?'나':m.role==='status'?'실행 상태':current().label),el('p','wb-answer',m.text));if(m.evidence_ids.length)box.append(sourceButtons(m.evidence_ids));if(m.uncertainties.length){const details=el('details');details.append(el('summary','','불확실성과 한계'),list(m.uncertainties));box.append(details)}root.append(box)}
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
    try{await api('/api/dialogue/'+scope,{run_id:runId,agent_id:selected,request_id,message});if(ticket!==epoch||k!==key())return;$('wb-question').value='';drafts.delete(k);chatSignature='';await loadChat()}
    catch(e){if(ticket===epoch){$('wb-chat-status').textContent=e.message;$('wb-send').disabled=false}}
  };
  setInterval(()=>{if(!$('report-panel').hidden){loadChat();if(doc?.run.status==='running')refresh()}},3000);
  return {refresh,openReport,render,choose,setTab,validateDocument};
})();
