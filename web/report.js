/* Read-only report renderer. Model/source text is always inserted as text, never HTML. */
'use strict';
window.MaraReport=(()=>{
  let renderedId=null, selectedChapter='all', selectedAsset=null;
  const chapters=[['portfolio-market','01','현재 시장 상황'],['portfolio-current','02','포트폴리오 요약'],['portfolio-adjustment','03','포트폴리오 조정안'],['portfolio-reasons','04','주요 근거']];
  function chooseChapter(id){
    selectedChapter=id;
    for(const [key] of chapters){const section=$(key);if(section)section.hidden=id!=='all'&&key!==id}
    for(const button of document.querySelectorAll('.reader-navigation button'))button.setAttribute('aria-pressed',String(button.dataset.chapter===id));
  }
  function revealAnchor(hash){
    const target=$(hash.replace(/^#/,''));if(!target)return;
    const section=target.closest('.portfolio-section');if(section&&section.hidden)chooseChapter(section.id);
    for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
  }
  window.addEventListener('hashchange',()=>revealAnchor(location.hash));
  document.addEventListener('click',event=>{const a=event.target.closest('a[href^="#"]');if(a)revealAnchor(a.hash)});
  function highlightAsset(figure,value){
    selectedAsset=value;figure.dataset.selectedAsset=value||'';
    for(const node of figure.querySelectorAll('.allocation-segment,.allocation-legend-item')){
      node.classList.toggle('allocation-dimmed',Boolean(value)&&node.dataset.symbol!==value);
      node.classList.toggle('allocation-selected',Boolean(value)&&node.dataset.symbol===value);
    }
    for(const button of figure.querySelectorAll('.allocation-legend-title'))button.setAttribute('aria-pressed',String(button.closest('[data-symbol]').dataset.symbol===value));
    const reset=figure.querySelector('.allocation-reset');if(reset)reset.setAttribute('aria-pressed',String(!value));
    const status=figure.querySelector('.allocation-selection');if(status)status.textContent=value?symbol(value)+' 강조 중 · 전체 비중과 금액은 그대로 표시해요.':'자산을 선택하면 현재와 조정 후 비중을 함께 강조해요.';
  }
  const $=id=>document.getElementById(id);
  const el=(tag,cls,value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!=null)n.textContent=value;return n};
  const text=(id,value)=>{$(id).textContent=value??'기록 없음'};
  const pct=n=>n==null?'계산 불가':(n*100).toFixed(1)+'%';
  const number=(n,d=1)=>n==null?'계산 불가':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:d});
  const action={hold:'유지',adjust:'조정 제안',defer:'보류'};
  const names={wood:['Cathie Wood','혁신 채택 · 성장 가치'],buffett:['Warren Buffett','기업 가치 · 안전마진'],marks:['Howard Marks','위험 · 사이클'],bogle:['John Bogle','비용 · 분산']};
  const labels={equity:'주식',bond:'채권',cash:'현금',unknown:'미확인',other:'기타'};
  const sourceId=i=>'report-source-'+i;
  const symbol=s=>s==='CASH'?'기준통화 현금':s;
  function publication(f){
    try{if(JSON.parse(f.text).date_provenance?.status?.startsWith('available-by'))return '공개 확인 '+f.published_at+' (원문 발표일 미확인)'}catch(e){}
    return '발표 '+f.published_at;
  }
  function items(values,empty='기록된 항목이 없어요.'){
    const ul=el('ul');for(const v of values?.length?values:[empty])ul.append(el('li','',v));return ul;
  }
  function list(id,values,empty){$(id).replaceChildren(...items(values,empty).children)}
  function cards(id,values){$(id).replaceChildren(...values.map(([label,value,note])=>{const c=el('div','metric');c.append(el('span','label',label),el('b','',value));if(note)c.append(el('span','hint',note));return c}))}
  function table(id,values){$(id).replaceChildren(...values.map(values=>{const tr=el('tr');for(const v of values)tr.append(el('td','',v));return tr}))}
  function section(title,values,empty){const box=el('div','reason-group');box.append(el('h4','',title),items(values,empty));return box}
  function track(value,cls='proposal',limit=null){
    const wrap=el('div','bar-track'),bar=el('span','bar '+cls);bar.style.width=Math.max(0,Math.min(100,(value||0)*100))+'%';wrap.append(bar);
    if(limit!=null){const line=el('span','limit-mark');line.style.left=Math.min(100,limit*100)+'%';line.title='설정 상한 '+pct(limit);wrap.append(line)}
    wrap.setAttribute('aria-hidden','true');return wrap;
  }
  function exposure(id,values,limit=null){
    const box=$(id);box.replaceChildren();
    if(!Object.keys(values||{}).length){box.append(el('p','hint','표시할 노출 자료가 없어요.'));return}
    for(const [name,value] of Object.entries(values).sort((a,b)=>b[1]-a[1])){
      const row=el('div','exposure-row');row.append(el('span','',labels[name]||name),el('b','',pct(value)),track(value,name==='unknown'?'unknown':limit!=null&&value>limit?'over':'proposal',limit));box.append(row);
    }
    if(limit!=null)box.append(el('p','hint','세로선: 설정 상한 '+pct(limit)));
  }
  let factGraph=null,factReport=null,factSources=[],evidencePanel=null,evidenceTrigger=null,evidencePinned=false,evidenceTimer=null,evidenceRestoring=false,evidenceReturnTrigger=null;
  const factNode=id=>factGraph?.facts?.find(n=>n.fact_id===id);
  function closeEvidence(restore=false){
    clearTimeout(evidenceTimer);if(evidencePanel)evidencePanel.hidden=true;
    evidenceTrigger?.setAttribute('aria-expanded','false');const old=evidenceReturnTrigger||evidenceTrigger;evidenceTrigger=null;evidencePinned=false;evidenceReturnTrigger=null;
    if(restore&&old?.isConnected){evidenceRestoring=true;old.focus();evidenceRestoring=false;}
  }
  function chart(series){
    const figure=el('figure','fact-series'),ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 360 150');svg.setAttribute('role','img');svg.setAttribute('aria-label',series.symbol+' '+series.price_kind+' 가격 관측');
    const points=series.observations,values=points.map(p=>p.value),times=points.map(p=>Date.parse(p.date)),lo=Math.min(...values),hi=Math.max(...values);
    const line=document.createElementNS(ns,'polyline');line.setAttribute('fill','none');line.setAttribute('stroke','currentColor');line.setAttribute('stroke-width','2');
    line.setAttribute('points',points.map((p,i)=>`${15+(times[i]-times[0])/(times.at(-1)-times[0]||1)*330},${125-(p.value-lo)/(hi-lo||1)*110}`).join(' '));svg.append(line);
    figure.append(el('figcaption','',series.symbol+' · '+series.currency+'/주 · '+({close:'종가',adjusted_close:'수정종가'}[series.price_kind]||series.price_kind)),svg,
      el('p','hint','요청 기간 '+series.requested_start+' → '+series.requested_end+' · '+({daily:'일별',weekly:'주별',monthly:'월별',irregular:'불규칙 표본'}[series.frequency]||series.frequency)),
      el('p','hint','실제 관측 '+points[0].date+' → '+points.at(-1).date+' · 최저 '+number(lo,3)+' / 최고 '+number(hi,3)),
      el('p','','실제 관측 구간 변동률 '+pct(series.calculation.period_return)),el('p','hint',series.calculation.scope),el('p','hint','선은 관측점을 연결한 표시예요. 사이의 가격을 관측하거나 채운 값이 아니에요.'));
    const d=el('details');d.append(el('summary','','관측값·계산 규칙'));const t=el('table');
    for(const p of points){const row=el('tr');row.append(el('td','',p.date),el('td','',number(p.value,4)));t.append(row)}
    d.append(t,el('pre','',JSON.stringify(series.calculation,null,2)));figure.append(d);return figure;
  }
  function evidenceContent(id){
    const node=factNode(id),f=node?.original||factSources.find(f=>f.id===id),card=el('article','fact-detail');
    card.dataset.factId=id;if(!f){card.append(el('h4','',id),el('p','notice','이 판단의 근거를 당시 자료에서 찾지 못했어요.'));return card}
    let parsed;try{parsed=JSON.parse(f.text)}catch(e){}
    card.append(el('h4','',typeof parsed?.title==='string'?parsed.title:f.topic||id),el('p','hint','fact '+id),el('p','hint',`${publication(f)} · 인지 ${f.known_at} · 당시 유효 ${f.valid_until}`));
    if(node)card.append(el('p','hint','버전 '+node.snapshot_id),el('p','hint',node.kind==='valuation'?'분석 가정에 따른 계산 · 관측 사실과 구분해요.':'당시 제공된 자료 · 인용 연결 자체가 주장의 타당성을 보증하지 않아요.'));
    if(node?.current_at_report===false)card.append(el('p','notice','보고서 기준 시점과 맞지 않는 자료예요.'));
    for(const issue of factGraph?.issues||[])if(issue.fact_id===id)card.append(el('p','notice','근거 연결 검사: '+issue.code+' · 이 항목은 확인이 필요해요.'));
    let excerpt=f.text;
    if(parsed&&typeof parsed==='object'){
      if(typeof parsed.text==='string')excerpt=parsed.text;
      else if(Array.isArray(parsed.hits))excerpt=parsed.hits.map(h=>h.excerpt||h.text||'').join('\n\n');
      else if(Array.isArray(parsed.verified_facts))excerpt=JSON.stringify({observed_period:parsed.observation_period,facts:parsed.verified_facts,read_scope:parsed.read_scope},null,2);
      else if(Array.isArray(parsed.observations))excerpt=JSON.stringify({namespace:parsed.namespace,tag:parsed.tag,unit:parsed.unit,observations:parsed.observations},null,2);
    }
    if(Array.isArray(parsed?.verified_facts)&&parsed.verified_facts.length){
      const t=el('table','fact-values'),head=el('thead'),row=el('tr');t.append(el('caption','hint','소수는 최대 네 자리로 표시해요. 정확한 값은 보존한 전체 근거에서 확인할 수 있어요.'));
      for(const label of ['날짜 / 지표','값','단위']){const th=el('th','',label);th.scope='col';row.append(th)}head.append(row);t.append(head);
      const body=el('tbody');
      for(const value of parsed.verified_facts){
        const r=el('tr'),v=value&&typeof value==='object'?value:{value};
        const display=v.value!=null&&typeof v.value==='object'?JSON.stringify(v.value):v.value??'기록 없음';
        const label=el('td','',[v.date,v.metric,v.start&&v.end?v.start+' → '+v.end:null].filter(Boolean).join(' · ')||'관측');
        const extra=Object.fromEntries(Object.entries(v).filter(([k])=>!['date','metric','start','end','value','unit'].includes(k)));
        if(Object.keys(extra).length){const detail=el('details');detail.append(el('summary','','계산·추가 조건'),el('pre','',JSON.stringify(extra,null,2)));label.append(detail)}
        r.append(label,el('td','',typeof display==='number'&&Number.isFinite(display)?number(display,4):String(display)),el('td','',v.unit||'미기재'));body.append(r);
      }
      t.append(body);card.append(t);
      if(typeof parsed.read_scope==='string')card.append(el('p','hint','읽은 범위: '+parsed.read_scope));
    }else card.append(el('p','fact-excerpt',excerpt.length>900?excerpt.slice(0,900)+'\n[미리보기 일부 · 전체 내용은 아래에서 확인해요.]':excerpt));
    if(node?.series)card.append(chart(node.series));
    if(f.uncertainty)card.append(el('p','notice','자료의 한계: '+f.uncertainty));
    if(node?.parents?.length){card.append(el('p','hint',node.derivation_status==='bound_parent_snapshots'?'계산 생성 때 기록한 원자료 버전':'보고서의 인용 연결 · 계산 생성 때의 자료 버전은 확인되지 않았어요.'));for(const parent of node.parents){
      const b=el('button','source-chip',parent.fact_id+(parent.snapshot_id?'':' · 연결 누락'));b.type='button';
      b.disabled=!parent.snapshot_id||factNode(parent.fact_id)?.snapshot_id!==parent.snapshot_id;b.addEventListener('click',()=>showEvidence(b,[parent.fact_id],true));card.append(b);
    }}
    const raw=el('details');raw.append(el('summary','','보존한 전체 근거와 schema'),el('pre','',JSON.stringify(node||f,null,2)));card.append(raw);
    try{const url=new URL(f.source);if(url.protocol==='https:'){const a=el('a','','출처 원문 · '+url.hostname);a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';card.append(a)}}catch(e){}
    return card;
  }
  function calculationContent(path){
    const card=el('article','fact-detail');card.append(el('h4','','계산 근거'),el('p','hint',path));
    try{if(!/^\/(analysis|funding|valuation|proposal)\//.test(path))throw new Error('Unsupported calculation');
      let value=factReport;for(const token of path.slice(1).split('/')){const key=token.replace(/~1/g,'/').replace(/~0/g,'~');if(value===null||typeof value!=='object'||!Object.hasOwn(value,key))throw new Error('Missing calculation');value=value[key]}
      if(value===undefined||value===null||value===''||(typeof value==='object'&&!Object.keys(value).length))throw new Error('Missing calculation');
      card.append(el('pre','',JSON.stringify(value,null,2)),el('p','hint','이 보고서에 저장된 계산과 가정이에요. 외부 관측 사실과 구분해요.'));
    }catch(e){card.append(el('p','notice','당시 계산을 찾지 못했어요. 이 연결은 확인이 필요해요.'))}
    return card;
  }
  function showEvidence(trigger,ids,pinned=false,paths=[]){
    clearTimeout(evidenceTimer);if(evidencePinned&&!pinned&&evidenceTrigger!==trigger)return;
    if(!evidencePanel){evidencePanel=el('div','evidence-panel');evidencePanel.id='evidence-panel';evidencePanel.setAttribute('role','dialog');evidencePanel.setAttribute('aria-label','판단의 근거');
      evidencePanel.addEventListener('mouseenter',()=>clearTimeout(evidenceTimer));evidencePanel.addEventListener('mouseleave',()=>{if(!evidencePinned)evidenceTimer=setTimeout(()=>closeEvidence(),200)});
      document.body.append(evidencePanel);
    }
    if(pinned&&!evidencePanel.contains(trigger))evidenceReturnTrigger=trigger;
    evidenceTrigger?.setAttribute('aria-expanded','false');evidenceTrigger=trigger;evidencePinned=pinned||evidencePinned;trigger.setAttribute('aria-expanded','true');
    const head=el('div','evidence-heading'),title=el('b','','판단에 인용한 근거'),pin=el('button','',evidencePinned?'고정됨':'고정해서 읽기'),close=el('button','','닫기');pin.type=close.type='button';
    pin.addEventListener('click',()=>{evidencePinned=true;pin.textContent='고정됨'});close.addEventListener('click',()=>closeEvidence(true));head.append(title,pin,close);
    evidencePanel.replaceChildren(head,el('p','hint','보고서 당시 자료예요. 최신 값으로 바꾸지 않아요.'),...ids.map(evidenceContent),...paths.map(calculationContent));
    if(factGraph?.storage_status==='index_mismatch_source_projection')evidencePanel.insertBefore(el('p','notice','저장 색인이 원본과 달라 원본 실행에서 근거를 다시 구성했어요.'),head.nextSibling);
    else if(factGraph?.storage_status==='source_projection_not_indexed')evidencePanel.insertBefore(el('p','hint','별도 DB 색인이 없는 과거 보고서예요. 당시 실행 원본에서 구성했어요.'),head.nextSibling);evidencePanel.hidden=false;
    if(pinned)close.focus();
  }
  function attachEvidence(node,ids,paths=[]){
    ids=ids||[];if(!ids.length&&!paths.length)return;node.dataset.calculationPaths=JSON.stringify(paths);node.dataset.evidenceIds=JSON.stringify(ids);node.classList.add('evidence-trigger');node.setAttribute('aria-controls','evidence-panel');node.setAttribute('aria-expanded','false');node.setAttribute('aria-haspopup','dialog');
    node.addEventListener('mouseenter',()=>showEvidence(node,ids,false,paths));node.addEventListener('mouseleave',()=>{if(!evidencePinned)evidenceTimer=setTimeout(()=>closeEvidence(),200)});
    node.addEventListener('focus',()=>{if(!evidenceRestoring)showEvidence(node,ids,false,paths)});node.addEventListener('blur',e=>{if(!evidencePinned&&!evidencePanel?.contains(e.relatedTarget))closeEvidence()});
    node.addEventListener('click',e=>{e.preventDefault();showEvidence(node,ids,true,paths)});
  }
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&evidencePanel&&!evidencePanel.hidden){e.preventDefault();closeEvidence(true)}});
  function sourceLinks(ids,sources){
    const box=el('div','source-chips');
    for(const id of ids||[]){const i=sources.findIndex(s=>s.id===id);if(i<0){box.append(el('span','hint','연결되지 않은 근거: '+id));continue}
      const a=el('a','source-chip','근거 '+(i+1));a.href='#'+sourceId(i);a.title=sources[i].topic+' · '+id;attachEvidence(a,[id]);box.append(a)}
    if(!box.childElementCount)box.append(el('span','hint','인용된 근거가 없어요.'));return box;
  }
  function sourcesView(sources,expired){
    text('source-note',`이 평가에서 사용 가능한 근거 ${sources.length}개. ${expired||0}개의 만료 근거는 현재 목록에서 제외했으며 원본 실행 기록에는 보존돼요. 출처 수는 독립적인 정보의 수나 신뢰도 점수가 아니에요. 인쇄본에는 출처·시점·한계를 싣고 원문 상세는 화면에서 확인해요.`);
    $('source-list').replaceChildren(...sources.map((s,i)=>{
      const card=el('article','source-card');card.id=sourceId(i);
      card.append(el('h3','',`${i+1}. ${s.topic||s.id}`),el('p','hint',`${publication(s)} · 인지 ${s.known_at} · 유효 ${s.valid_until}`));
      const detail=el('details');detail.append(el('summary','','근거 내용 · '+s.id),el('p','source-text',s.text));card.append(detail);
      if(s.uncertainty)card.append(el('p','hint','자료의 한계: '+s.uncertainty));
      try{const url=new URL(s.source);if(url.protocol==='https:'){const link=el('a','','출처 보기 · '+url.hostname);link.href=url.href;link.target='_blank';link.rel='noreferrer noopener';card.append(link)}}catch(e){}
      return card;
    }));
  }
  function allocationComparison(values,nav,weights,capital,newContribution,outside,money){
    const figure=el('figure','allocation-visual');figure.id='portfolio-allocation-comparison';
    figure.append(el('figcaption','','비중 변화 · 현재 보유와 이번 제안'));
    const validAmount=n=>Number.isFinite(n)&&n>=0;
    const actualValid=validAmount(nav)&&Object.values(values).every(validAmount)&&Math.abs(Object.values(values).reduce((a,b)=>a+b,0)-nav)<=Math.max(.01,(nav||0)*.000001);
    const weightSum=Object.values(weights).reduce((a,b)=>a+b,0);
    const proposalValid=validAmount(capital)&&Object.values(weights).every(validAmount)&&Object.keys(weights).length>0&&Math.abs(weightSum-1)<.000001;
    const symbols=[...new Set([...Object.keys(values),...Object.keys(weights)])].sort((a,b)=>(values[b]||0)-(values[a]||0)||a.localeCompare(b));
    const palette=['#3670c7','#bd651d','#168677','#9958b4','#b64c6f','#6a7d28','#577f94','#8d6c4f'];
    const colors=new Map(symbols.map((s,i)=>[s,s==='CASH'?'#7d8795':palette[symbols.filter(x=>x!=='CASH').indexOf(s)%palette.length]]));
    const planned=Object.fromEntries(symbols.map(s=>[s,proposalValid?capital*(weights[s]||0):null]));
    const after=Object.fromEntries(symbols.map(s=>[s,newContribution?actualValid&&proposalValid?(values[s]||0)+planned[s]:null:planned[s]]));
    const afterTotal=newContribution?actualValid&&proposalValid?nav+capital:null:capital;
    const partial=!newContribution&&(outside>0||(validAmount(nav)&&validAmount(capital)&&capital<nav));
    const afterLabel=newContribution?'납입 후 전체 (가정)':partial?'이번 제안 범위':'조정 후 계획';
    const afterValid=proposalValid&&(!newContribution||actualValid);
    const row=(key,label,amounts,total,valid)=>{
      const row=el('div','allocation-series');row.dataset.series=key;
      const heading=el('div','allocation-series-heading');heading.append(el('b','',label),el('span','',valid?money(total):'계산 불가'));row.append(heading);
      if(!valid){row.append(el('p','allocation-empty','금액 또는 비중 자료를 확인해야 해요.'));figure.append(row);return}
      if(total===0){row.append(el('p','allocation-empty',key==='current'?'현재 보유 자산이 없어요.':'배분할 금액이 없어요.'));figure.append(row);return}
      const bar=el('div','allocation-stack');bar.setAttribute('role','img');
      bar.setAttribute('aria-label',label+' · '+money(total)+' · '+symbols.filter(s=>amounts[s]>0).map(s=>symbol(s)+' '+pct(amounts[s]/total)+' '+money(amounts[s])).join(', '));
      for(const s of symbols){if(!(amounts[s]>0))continue;const share=amounts[s]/total,segment=el('span','allocation-segment');segment.dataset.symbol=s;segment.dataset.weight=String(share);segment.style.width=(share*100)+'%';segment.style.backgroundColor=colors.get(s);segment.setAttribute('aria-hidden','true');segment.title=symbol(s)+' · '+pct(share)+' · '+money(amounts[s]);if(share>=.12)segment.textContent=pct(share);bar.append(segment)}
      row.append(bar);figure.append(row);
    };
    row('current','현재 전체',values,nav,actualValid);
    row('after',afterLabel,after,afterTotal,afterValid);
    if(newContribution)row('contribution','신규 납입분만',planned,capital,proposalValid);
    figure.append(el('p','hint',partial?'두 막대의 기준 금액이 달라요. 제안 범위 밖 자산의 배분이 정해지지 않아 전체 조정 후 비중은 계산하지 않았어요.':newContribution?'납입 후 전체는 기존 보유 + 신규 납입액이에요. 가격 불변·기존 보유 유지를 가정해요.':'각 막대는 표시된 기준 금액의 100%예요. 비중 차이는 %p로 표시해요.'));
    const legend=el('ul','allocation-legend');legend.setAttribute('aria-label','자산별 비중과 금액');
    for(const s of symbols){
      const item=el('li','allocation-legend-item');item.dataset.symbol=s;
      const title=el('button','allocation-legend-title'),swatch=el('span','allocation-swatch');swatch.style.backgroundColor=colors.get(s);swatch.setAttribute('aria-hidden','true');title.type='button';title.setAttribute('aria-pressed','false');title.addEventListener('click',()=>highlightAsset(figure,selectedAsset===s?null:s));title.append(swatch,el('b','',symbol(s)));item.append(title);
      const beforeWeight=actualValid&&nav>0?(values[s]||0)/nav:null,afterWeight=afterValid&&afterTotal>0?after[s]/afterTotal:null;
      item.append(el('div','allocation-legend-weights',(beforeWeight==null?'비중 없음':pct(beforeWeight))+' → '+(afterWeight==null?'계산 불가':pct(afterWeight))));
      if(!partial&&beforeWeight!=null&&afterWeight!=null){const delta=(afterWeight-beforeWeight)*100;item.append(el('span','allocation-weight-change',(delta>0?'+':'')+delta.toFixed(1)+'%p'))}
      item.append(el('span','allocation-legend-amount',(partial?'제안액 ':newContribution?'납입 후 ':'조정 후 ')+(afterValid?money(after[s]):'계산 불가')));
      if(newContribution)item.append(el('span','hint','신규 납입 '+(proposalValid?money(planned[s])+' · '+pct(weights[s]||0):'계산 불가')));
      if(!(weights[s]>0)&&(values[s]||0)>0)item.append(el('span','hint',newContribution?'기존 보유 유지 · 신규 납입 없음':partial?'이번 제안에 미포함':'목표에서 제외'));
      legend.append(item);
    }
    const controls=el('div','allocation-controls'),reset=el('button','allocation-reset','전체 자산');reset.type='button';reset.addEventListener('click',()=>highlightAsset(figure,null));
    const selection=el('p','hint allocation-selection');selection.setAttribute('role','status');controls.append(reset,selection);
    figure.append(controls,legend);highlightAsset(figure,symbols.includes(selectedAsset)?selectedAsset:null);return figure;
  }
  function portfolioLayout(box,doc,r,v,sources,money){
    const makeSection=(id,index,title)=>{const s=el('section','portfolio-section');s.id=id;const head=el('div','section-title');head.append(el('span','section-index',index),el('h3','',title));s.append(head);return s};
    const fold=(id,title,...nodes)=>{const d=el('details','reader-fold');d.id=id;d.append(el('summary','',title),...nodes);return d};
    const metric=(label,value,note)=>{const d=el('div','metric');d.append(el('span','label',label),el('b','',value));if(note)d.append(el('span','hint',note));return d};
    const grid=box.querySelector('.reader-overview-grid'),allocationOriginal=grid.children[0],reviewOriginal=grid.children[1];
    grid.remove();
    const claims=[...box.querySelectorAll('.reader-claim-row')];claims.forEach(c=>c.remove());
    const appendix=fold('reader-appendix','대안·확인할 질문·재검토 일정과 출처',...box.childNodes);
    const market=makeSection('portfolio-market','01','현재 시장 상황'),analysis=v.market_analysis||{},brief=v.reader_brief;
    market.append(el('p','hint',r.as_of+' 기준 자료 · 실시간 시세가 아니에요.'));
    const summary=analysis.summary||'이 보고서에는 시장 해석이 별도로 기록되지 않았어요.';
    if(brief){
      market.append(el('p','eyebrow',brief.period.start+' → '+brief.period.end+' · 최근 3개월'),el('h4','market-headline',brief.headline),el('p','market-lead',brief.summary));
      const themes=el('div','market-themes');
      for(const theme of brief.themes){const card=el('article','market-theme'),heading=el('h4'),button=el('button','claim-statement',theme.title);button.type='button';attachEvidence(button,theme.fact_ids);heading.append(button);
        card.append(heading,el('p','',theme.what_happened),el('p','market-implication','포트폴리오에 주는 의미: '+theme.portfolio_meaning));
        const detail=fold('market-theme-'+theme.id,'반대 근거와 확인 범위',el('p','',theme.counterpoint),sourceLinks(theme.fact_ids,sources));card.append(detail);themes.append(card)}
      market.append(themes);
      if(brief.missing_evidence.length)market.append(fold('market-brief-gaps','아직 확인하지 못한 자료 '+brief.missing_evidence.length+'개',items(brief.missing_evidence)));
    }else{
      market.append(el('p','eyebrow','이 실행에는 최종 시황 요약이 없어요.'),el('p','market-lead',summary));
    }
    const factIds=[...new Set(analysis.facts||[])];
    const facts=el('div','market-fact-list');
    for(const id of factIds.slice(0,3)){
      const f=sources.find(f=>f.id===id),row=el('div','market-fact-row'),b=el('button','market-fact-title',f?.topic||id);b.type='button';attachEvidence(b,[id]);
      row.append(b,el('span','hint','fact · '+id+(f?' · '+publication(f):'')));facts.append(row);
      if(f?.text&&!/^[\s]*[\[{]/.test(f.text))row.append(el('p','hint',f.text.length>160?f.text.slice(0,160)+'…':f.text));
    }
    if(!factIds.length)facts.append(el('p','hint','시장 해석에 연결된 fact가 없어요.'));
    if(!brief)market.append(facts);
    market.append(fold('portfolio-market-details','분석 초기에 작성한 시황과 연결된 fact '+factIds.length+'개',el('p','',summary),
      section('주요 요인',analysis.drivers),section('포트폴리오에 주는 의미',analysis.portfolio_implications),section('자료의 한계',analysis.uncertainties),sourceLinks(factIds,sources)));
    const current=makeSection('portfolio-current','02','포트폴리오 요약'),perf=r.performance,nav=r.valuation?.nav,previousNav=v.previous?.valuation?.nav;
    const change=Number.isFinite(nav)&&Number.isFinite(previousNav)&&previousNav>0?nav/previousNav-1:null;
    const metrics=el('div','metrics portfolio-metrics');
    metrics.append(metric('현재 평가액',money(nav),'보고서 기준일의 실제 보유'),
      metric('기간 손익',money(perf?.pnl),perf?'외부 입출금을 제외한 손익':'비교할 이전 평가가 없어요.'),
      metric('기간 수익률',pct(perf?.modified_dietz),'입출금 시점을 반영한 Modified Dietz'),
      metric('평가액 변동률',pct(change),'입출금 포함 · 투자 수익률과 달라요.'));
    current.append(metrics,el('p','hint',perf?.limitation||(!perf?'최초 평가여서 기간 손익과 수익률을 계산할 수 없어요.':(v.previous?.as_of||'이전 평가')+' → '+r.as_of+' · 실제 보유의 기간 성과예요.')));
    if(perf)current.append(el('p','hint','기간 시작 '+money(perf.start_nav)+' · 외부 순입출금 '+money(perf.external_net_flows)+' · '+(v.previous?.as_of||'이전 평가')+' → '+r.as_of));
    const values=r.valuation?.values||{},actualWeights=r.valuation?.weights||{},quotes=new Map((v.prices||[]).map(p=>[p.symbol,p]));
    const holdings=el('table','portfolio-table');holdings.append(el('caption','','현재 보유 내역 · 금액은 '+(v.base_currency||'기준통화')));
    const hh=el('tr');['자산','평가액','보유 비중','가격 변동률','가격 비교 기간'].forEach(x=>hh.append(el('th','',x)));const thead=el('thead');thead.append(hh);holdings.append(thead);
    const hb=el('tbody');for(const [s,value] of Object.entries(values).sort((a,b)=>b[1]-a[1])){
      const q=quotes.get(s),tr=el('tr');[symbol(s),money(value),nav>0?pct(actualWeights[s]):'비중 없음',s==='CASH'?'—':q?.price_change==null?'비교 없음':pct(q.price_change),q?.previous_observed_at?q.previous_observed_at+' → '+q.observed_at:'비교 자료 없음'].forEach(x=>tr.append(el('td','',x)));hb.append(tr);
    }holdings.append(hb);const hs=el('div','scroll');hs.append(holdings);current.append(hs,el('p','hint','가격 변동률은 두 시점의 가격만 비교해요. 배당·거래·입출금을 반영한 종목 수익률이 아니에요.'));
    if(!hb.childElementCount)current.append(el('p','notice','현재 보유 내역이 없어요.'));
    const plan=makeSection('portfolio-adjustment','03','포트폴리오 조정안');
    allocationOriginal.querySelector('h3')?.remove();
    allocationOriginal.querySelector('.scroll')?.remove();
    plan.append(el('p','notice','최종 판단: '+(action[doc.decision.action]||doc.decision.action)+' · 정기 납입 계획: '+(doc.allocation.monthly_plan?.status==='blocked'?'보류':doc.allocation.monthly_plan?.status==='conditional_plan'?'조건부 계획':'상태 미기록')+' · 실제 주문은 별도 승인이 필요해요.'));
    const review=doc.reasons.final_review||{};
    plan.append(el('p','hint','최종 검토: '+(review.qualitative_pass===true?'해당 검토 범위에서 통과':review.qualitative_pass===false?'보류':'미기록')+' · 세부 설명은 주요 근거에서 확인해요.'));
    const capital=doc.allocation.proposal_capital,weights=doc.allocation.weights||{},monthly=doc.allocation.monthly_plan?.amounts||{},newContribution=r.funding?.source==='future_income';
    const amounts=el('div','metrics');amounts.append(metric(newContribution?'신규 납입 기준액':'조정 후 기준액',money(capital)),metric('추가 필요 자금',money(r.funding?.additional_funding_needed)),metric('제안 범위 밖 금액',money(r.funding?.amount_outside_proposal)));plan.append(amounts);
    if(newContribution)plan.append(el('p','hint','이번 안은 새로 납입할 '+money(capital)+'의 배분이에요. 기존 보유는 유지한다고 가정해 납입 후 금액을 함께 표시해요. 기존 보유를 매도하거나 재배분하는 제안은 아니에요.'));
    else if(r.funding?.amount_outside_proposal>0)plan.append(el('p','notice','전체 보유 중 '+money(r.funding.amount_outside_proposal)+'은 이번 제안 범위 밖이에요. 아래 증감액은 전체 현재 보유와 제안액의 차이이며, 범위 밖 자산의 처리 방안이 정해지기 전에는 매도액으로 사용할 수 없어요.'));
    plan.append(allocationComparison(values,nav,weights,capital,newContribution,r.funding?.amount_outside_proposal,money));
    const all=[...new Set([...Object.keys(values),...Object.keys(weights)])].sort((a,b)=>(weights[b]||0)-(weights[a]||0));
    const adjustment=el('table','portfolio-table adjustment-table');adjustment.id='portfolio-adjustment-table';adjustment.append(el('caption','',newContribution?'현재 보유 → 신규 납입 후 · 기존 보유 유지와 가격 불변을 가정해요.':'현재 보유 → 조정 후 계획 · 목표에서 제외한 보유도 포함해요.'));
    const ah=el('tr');['자산','현재 금액',newContribution?'납입 후 금액(가정)':'조정 후 금액',newContribution?'신규 납입액':'증감액',newContribution?'납입분 비중':'목표 비중','매회 납입 배분'].forEach(x=>ah.append(el('th','',x)));const ath=el('thead');ath.append(ah);adjustment.append(ath);const ab=el('tbody');
    for(const s of all){
      const actual=Object.hasOwn(values,s)?values[s]:r.valuation?.values?0:null,planned=capital==null?null:capital*(weights[s]||0),target=newContribution?(actual==null||planned==null?null:actual+planned):planned,delta=actual==null||target==null?null:target-actual,tr=el('tr');tr.dataset.symbol=s;
      const diff=delta==null?'계산 불가':(delta>0?'+':'')+money(delta);[symbol(s),money(actual),money(target),diff,pct(weights[s]||0),money(Object.hasOwn(monthly,s)?monthly[s]:weights[s]>0?null:0)].forEach(x=>tr.append(el('td','',x)));ab.append(tr);
    }adjustment.append(ab);const as=el('div','scroll');as.append(adjustment);plan.append(as,el('p','hint','증감액 = 조정 후 금액 − 현재 금액. 수수료·세금·수량 반올림 전의 비교액이며, 미입금 자금은 현재 쓸 수 있는 현금에 포함하지 않아요. 현금 행의 증감은 현금 잔액 변화예요.'),fold('portfolio-allocation-context','납입 주기·자금 범위와 적용 조건',...allocationOriginal.childNodes));
    const reasons=makeSection('portfolio-reasons','04','주요 근거');
    reasons.append(el('p','hint','종합안의 핵심 이유를 먼저 읽고, 아래에서 판단별 설명과 fact를 확인해요.'));
    const keyPoints=el('ol','portfolio-key-points');
    if(brief?.key_reasons.length){for(const reason of brief.key_reasons){const li=el('li'),button=el('button','claim-statement',reason.headline);button.type='button';
      const selected=doc.reasons.claims.filter(x=>reason.claim_ids.includes(x.claim.id)).map(x=>x.claim);
      attachEvidence(button,[...new Set(selected.flatMap(x=>x.fact_ids||[]))],[...new Set(selected.flatMap(x=>x.calculation_paths||[]))]);
      li.append(button,el('p','',reason.explanation));
      const links=el('div','source-chips');for(const id of reason.claim_ids){const a=el('a','source-chip','판단 '+id);a.href='#reader-claim-'+id;a.addEventListener('click',()=>{const more=$('portfolio-more-reasons'),claim=$('reader-claim-'+id);if(more)more.open=true;if(claim)claim.open=true});links.append(a)}li.append(links);keyPoints.append(li)}
    }else for(const point of doc.reasons.key_points||[])keyPoints.append(el('li','',point));reasons.append(keyPoints);
    if(brief)reasons.append(fold('portfolio-original-rationale','종합 의견 원문',items(doc.reasons.key_points),el('p','',doc.decision.rationale)));
    else reasons.append(el('h4','','이 조정안을 제안한 이유'),el('p','',doc.decision.rationale||'종합 설명은 아래 원문을 확인해 주세요.'));
    const more=fold('portfolio-more-reasons','판단별 설명과 근거 '+claims.length+'개');
    claims.forEach((claim,i)=>{
      const card=el('article','portfolio-reason'),heading=claim.querySelector('h4'),state=claim.querySelector('summary p'),impact=[...claim.children].find(n=>n.tagName==='P'&&n.textContent.startsWith('결정에 미친 영향:'));
      if(heading)card.append(heading);if(state)card.append(state);if(impact){impact.textContent=impact.textContent.replace(/^결정에 미친 영향: /,'');card.append(impact)}
      claim.querySelector('summary').replaceChildren(document.createTextNode('근거와 반론 보기'));card.append(claim);more.append(card);
    });
    if(!claims.length)reasons.append(el('p','notice','구조화된 판단 근거가 없어요. 아래 종합 의견과 원문을 확인해 주세요.'));
    if(claims.length)reasons.append(more);
    reviewOriginal.querySelector('h3')?.remove();reasons.append(fold('portfolio-final-review','종합 의견·최종 검토와 남은 문제',...reviewOriginal.childNodes));
    const overview=el('div','reader-verdict');overview.setAttribute('aria-label','최종 판단 요약');
    overview.append(el('span','eyebrow','이번 판단'),el('h3','',action[doc.decision.action]||doc.decision.action),el('p','',doc.decision.rationale));
    const navigation=el('nav','reader-navigation');navigation.setAttribute('aria-label','보고서 항목 선택');
    for(const [id,index,label] of [['all','','전체 보기'],...chapters]){const button=el('button');button.type='button';button.dataset.chapter=id;button.setAttribute('aria-pressed',String(selectedChapter===id));if(index)button.append(el('span','',index));button.append(document.createTextNode(label));button.addEventListener('click',()=>chooseChapter(id));navigation.append(button)}
    box.replaceChildren(overview,navigation,market,current,plan,reasons,appendix);
    for(const section of [market,current,plan,reasons])section.hidden=selectedChapter!=='all'&&selectedChapter!==section.id;
  }
  function readerDocument(doc,status,r,sources,money,v){
    const box=el('article','final-reader');box.id='final-reader';
    box.append(el('h3','','이번 판단과 적용 범위'));
    if(!doc?.reasons){box.append(el('p','notice','최종 보고서 구성을 마치지 못했어요. 아래에 원래 분석과 확인된 상태를 보존했어요.'));return box}
    if(v?.audit_findings?.length){
      const audit=el('section','notice');audit.id='independent-report-audit';audit.append(el('h3','','독립 검산과 범위 검토'),el('p','','원 분석 기록과 판정은 보존했어요. 아래 정정·검토를 함께 읽어주세요.'));
      for(const finding of v.audit_findings){
        audit.append(el('h4','',finding.classification==='verified_arithmetic_correction'?'검산 정정':'판단 범위에 관한 검토 의견'),el('p','','원문: '+finding.original_text),el('p','',finding.correction_or_review),el('p','hint',finding.limits),el('p','hint','검토: '+finding.reviewer+' · '+finding.recorded_at));
        const link=el('a','reader-origin','해당 단계 원문');link.href='#role-output-'+finding.source_output_id;link.addEventListener('click',()=>{const history=$('role-report-history');if(history)history.open=true});audit.append(link);
      }
      box.append(audit);
    }
    const decision=doc.decision,allocation=doc.allocation,review=doc.reasons.final_review||{},open=doc.open_issues;
    const originLink=origin=>{const link=el('a','reader-origin','해당 단계 원문');link.href='#role-output-'+origin?.output_id;link.addEventListener('click',()=>{const history=$('role-report-history');if(history)history.open=true});return link};
    box.append(el('p','notice','최종 판단: '+(action[decision.action]||decision.action)+' · 실행 권한: '+(decision.decision_status?.execution_status==='not_authorized'?'부여되지 않았어요':decision.decision_status?.execution_status||'기록 없음')),
      el('p','',allocation.scope),el('p','',`제안 기준액 ${money(allocation.proposal_capital)} · 실제 보유 평가액 ${money(allocation.actual_nav)} · 자금 상태: ${decision.funding?.availability==='conditional_on_deposit'?'앞으로 입금할 자금의 조건부 계획':'기록된 보유 기준'}`));
    const cadence=allocation.contribution_basis||{};
    box.append(el('p','hint','납입 주기: '+(cadence.schedule==='calendar_month'?'매월':cadence.every_days?cadence.every_days+'일마다':'당시 설정한 간격마다')+' '+money(cadence.amount_per_payment)+' · 월평균 환산 '+money(cadence.monthly_amount)),el('p','hint',cadence.method));
    const t=el('table'),head=el('tr');for(const name of ['자산','제안 비중','기준액 배분','매회 납입 배분'])head.append(el('th','',name));t.append(head);
    for(const row of allocation.rows){const tr=el('tr');for(const value of [symbol(row.symbol),pct(row.weight),money(row.planned_amount),money(row.monthly_amount)])tr.append(el('td','',value));t.append(tr)}
    const scroll=el('div','scroll');scroll.append(t);box.append(scroll,el('p','notice','정기 납입 계획: '+(allocation.monthly_plan.status==='blocked'?'보류':allocation.monthly_plan.status==='conditional_plan'?'조건부 계획':'상태 미기록')),el('p','hint',allocation.monthly_plan.rule||'정기 납입 계획이 별도로 기록되지 않았어요.'));
    const calibration=doc.decision_calibration;
    if(calibration){
      const fold=(id,title,...nodes)=>{const d=el('details','reader-fold');d.id=id;d.append(el('summary','',title),...nodes);return d};
      const details=el('div');
      const kinds={fact_verification:'자료 확인',calculation_link:'계산 연결',future_judgment:'미래 판단'};
      const gaps=[...(calibration.gaps||[]).map(g=>({...g,author:'리더'})),...(calibration.final_review_gaps||[]).map(g=>({...g,author:'최종 검증'}))];
      for(const g of gaps)details.append(el('h4','',g.author+' · '+g.subject+' · '+(kinds[g.kind]||g.kind)),el('p','hint',({unresolved:'미해결',resolved:'근거 확인됨',managed_by_scenario:'시나리오로 관리'}[g.status]||g.status)),el('p','',g.reason),el('p','','확인할 조건: '+g.resolution_condition),el('p','','다음 행동: '+g.next_action));
      for(const c of calibration.resolution?.choices||[])details.append(el('h4','',({cash_wait:'현금 대기',small_participation:'소규모 참여',higher_participation:'더 높은 비중'}[c.participation]||'비교안')),el('p','',c.why_this_size),el('p','','기회비용: '+c.opportunity_cost),...c.scenarios.map(x=>el('p','',({adverse:'불리한 경우',base:'기준 경우',favorable:'유리한 경우'}[x.name]||x.name)+': '+x.assumptions.join(' / ')+' → '+x.implication)),el('p','','재검토: '+c.review_condition+' · '+c.review_by),el('p','','반증: '+c.falsifier));
      if(calibration.resolution)details.append(el('p','',calibration.resolution.decisive_tradeoff));
      box.append(fold('decision-calibration','판단 공백과 시나리오·비중 비교',details));
      const trace=el('div'),requestStates={pending:'배정 대기',deferred_capacity:'조사 대상 한도로 이연',round_budget:'조사 횟수 한도',research_unavailable:'조사 도구 미연결',frozen_snapshot:'당시 자료로만 검토',duplicate:'중복 요청',reassessed:'요청자 재평가',scenario_review:'시나리오 검토',repeat_target_stopped:'근거 없는 반복 조사 중단',returned_for_reassessment:'응답 후 재평가 대기'};
      const traceOrigins=v?.feedback_provenance?.rows||{};
      if(calibration.learning?.status==='reused_prefix')trace.append(el('p','hint','앞선 실행의 일부 요청·응답을 재사용해 분석을 이어갔어요. 각 기록의 최초 시각과 이번 연결 시각을 구분하며, 새 요청과 새 평가도 함께 표시해요.'));
      for(const q of calibration.requests||[]){
        trace.append(el('h4','',q.requester+' → '+(q.recipient||'evidence')+' · '+q.need),el('p','','상태: '+(requestStates[q.status]||q.status)),el('p','','필요한 이유: '+q.decision_impact),el('p','','수용 조건: '+q.acceptance),el('p','','처리 사유: '+(q.response?.reason||q.scheduling_reason||q.status)),el('p','','요청자 재판단: '+(q.assessment?.reason||'응답 후 평가 기록 없음')));
        const origins=traceOrigins[q.request_event_id];
        if(!origins)trace.append(el('p','hint','이 실행의 요청 기록 시각: '+(q.requested_at||'미기록')+' · 최초 기록 출처는 확인되지 않았어요.'));
        for(const [edge,origin] of Object.entries(origins||{})){
          const label={request:'요청 작성',queued:'요청 등록',response:'자료 응답',assessment:'요청자 평가'}[edge]||edge;
          trace.append(el('p','hint',label+': '+(origin.status==='reused'?'앞선 기록 재사용 · 최초 '+origin.origin_recorded+' · 이번 연결 '+origin.current_recorded:origin.status==='new'?'이번 실행에서 작성 · '+origin.current_recorded:'원 기록 연결 미검증')));
        }
      }
      const learning=calibration.learning||{};
      for(const conflict of learning.memory_feedback?.conflicts||[]){trace.append(el('h4','','기억 정리에서 남긴 이견'),el('p','',conflict.text));for(const [role,reviews] of Object.entries(learning.memory_reviews||{})){const review=reviews.find(x=>x.conflict_id===conflict.id);trace.append(el('p','',({leader:'리더',final_validation:'최종 검증'}[role]||role)+': '+(review?review.reason+' · 다음 확인: '+review.next_action:'평가 기록 없음')))}}
      const reused=learning.status==='reused_prefix';
      const learningState={reviewed:'완료',reused_prefix:'이전 회고 재사용',skipped_frozen_revision:'당시 자료 재검토로 생략',no_predecessor:'이전 판단 없음',pending:'진행 중'}[learning.status]||learning.status||'미기록';
      trace.append(el('p','','회고 상태: '+learningState+' · '+(reused?'재사용한 지식 처리 ':'지식 변경 ')+(learning.applications?.length||0)+'건 · 사용 평가 '+(learning.knowledge_usage?.length||0)+'건'),el('p','hint','기록 전달과 모델이 보고한 사용을 뜻해요. 투자성과 개선을 확인한 수치는 아니에요.'));
      if(reused)trace.append(el('p','hint','앞선 회고와 지식 처리 기록을 이어서 사용했어요. 이번 실행에서 같은 지식 변경을 다시 적용하거나 새 학습으로 집계하지 않았어요.'));
      box.append(fold('request-learning-trace','자료 요청과 회고 기록',trace));
    }
    box.append(el('h3','','선택 이유와 마지막 검토'),el('p','hint','선택 이유와 아래 주장 상태는 리더의 판단이에요. 마지막 검토의 범위와 반론을 함께 읽어요.'),items(doc.reasons.key_points));
    box.append(el('p','notice','마지막 검토: '+(review.qualitative_pass===true?'해당 검토 범위에서 통과':review.qualitative_pass===false?'보류':'미기록')),el('p','',review.reason));
    box.append(sourceLinks(review.judgment_report?.evidence_ids||[],sources));
    if(doc.reasons.final_review_origin.output_id)box.append(originLink(doc.reasons.final_review_origin));
    for(const [label,values] of [['검토에서 남긴 문제',open.final_review_issues],['뒷받침되지 않은 주장',open.unsupported_claims],['수치 검증의 미해결',open.numeric_blockers],['반대 의견',open.dissent]]){
      if(values?.length)box.append(section(label,values));
    }
    for(const entry of doc.reasons.claims){const c=entry.claim,card=el('article','final-claim');card.dataset.claimId=c.id;
      const heading=el('h4'),claimButton=el('button','claim-statement',c.statement);claimButton.type='button';attachEvidence(claimButton,c.fact_ids,c.calculation_paths);heading.append(claimButton);
      card.append(heading,el('p','hint','리더 판단: '+({supported:'근거가 뒷받침한다고 판단',conditional:'조건부',unresolved:'미해결'}[c.status]||c.status)+(review.qualitative_pass===false?' · 최종 검토는 보류됐어요.':'')),
        section('가정',c.assumptions),el('p','','반대 근거: '+c.counterevidence),el('p','','결정에 미친 영향: '+c.decision_impact),sourceLinks(c.fact_ids,sources));
      if(c.calculation_paths?.length){const links=el('div','source-chips');for(const path of c.calculation_paths){const i=doc.references.calculations.findIndex(x=>x.path===path);const a=el('a','source-chip','계산 근거');a.href='#final-calculation-'+i;a.title=path;a.addEventListener('click',()=>{const parent=$('final-calculations'),item=$('final-calculation-'+i);if(parent)parent.open=true;if(item)item.open=true});links.append(a)}card.append(links);if(!c.fact_ids?.length){const empty=card.querySelector('.source-chips');if(empty)empty.firstChild.textContent='별도 외부 fact 인용 없이 아래 계산 경로를 참조한 판단이에요.'}}
      if(entry.origin.output_id)card.append(originLink(entry.origin));box.append(card);
    }
    box.append(section('판단의 적용 범위와 한계',doc.reasons.scope_limits),section('남은 위험',open.risks));
    box.append(el('h3','','비교한 대안'));
    for(const entry of doc.alternatives){const alt=entry.alternative;box.append(el('h4','',alt.name),
      el('p','hint',({preferred:'리더가 선호한 안',rejected:'채택하지 않은 안',conditional:'조건부 안',diagnostic_only:'제약을 확인하기 위한 비교안'}[alt.decision]||alt.decision)),
      el('p','',Object.entries(alt.weights||{}).map(([s,w])=>symbol(s)+' '+pct(w)).join(' · ')),el('p','',alt.reason),el('p','','판단을 바꿀 조건: '+alt.change_condition));}
    box.append(el('h3','','원래 질문과 남은 확인'));
    for(const q of open.questions){const card=el('article','final-question');card.dataset.questionId=q.id;card.append(el('h4','',q.target+' · '+q.question),
      el('p','hint','마지막 검토자 판단: '+(q.review?.status==='supported'?'검토 범위에서 근거가 뒷받침함':q.review?.status==='unresolved'?'미해결':'미검토')),
      el('p','',q.review?.reason||q.acceptance),el('p','','다음 확인: '+(q.review?.next_action||'구체적인 후속 판단이 기록되지 않았어요.')),sourceLinks(q.fact_ids,sources));for(const finding of v?.audit_findings||[])if(finding.classification==='verified_arithmetic_correction'&&finding.original_text===q.review?.reason)card.append(el('p','notice','독립 검산 정정: '+finding.correction_or_review));box.append(card)}
    box.append(el('h3','','언제 무엇을 다시 확인하나'));
    for(const check of doc.next_review.monitoring)box.append(el('h4','',check.variable),el('p','',check.condition),el('p','',check.check_at+' · 담당 '+check.owner),el('p','','그때 할 일: '+check.action),el('p','','반례 확인: '+check.counterexample_test));
    box.append(section('다음 확인 항목',doc.next_review.next_checks),section('실행 전 조건',doc.next_review.implementation));
    const refs=el('section','final-references');refs.append(el('h3','','핵심 근거와 읽은 범위'));
    for(const f of doc.references.facts){const i=sources.findIndex(s=>s.id===f.fact_id),item=el('div','final-reference');
      item.append(el('p','',`${i>=0?'근거 '+(i+1):'연결 미확인'} · ${f.title||f.fact_id}`));
      if(f.available){const scope=f.read_scope||{};item.append(el('p','hint',`${publication(sources.find(x=>x.id===f.fact_id)||f)} · 확인 ${f.known_at} · 유효 ${f.valid_until}`));
        if(scope.filing)item.append(el('p','hint',scope.filing.form+' · '+scope.filing.accession));
        if(scope.ranges)item.append(el('p','hint','읽은 본문 위치: '+scope.ranges.map(x=>x.start+'–'+x.end+'자').join(', ')));
        if(scope.tag)item.append(el('p','hint',`${scope.namespace}:${scope.tag} · ${scope.unit} · ${scope.observations}개 관측`));
        item.append(el('p','hint',scope.limits||f.uncertainty));
        try{const url=new URL(f.source);if(url.protocol==='https:'){const link=el('a','',url.href);link.href=url.href;link.rel='noreferrer noopener';link.target='_blank';item.append(link)}}catch(e){}
      }else item.append(el('p','notice','이 근거를 현재 보고서에서 찾을 수 없어요.'));
      refs.append(item);
    }
    box.append(refs);
    const calculations=el('details','final-calculations');calculations.id='final-calculations';calculations.append(el('summary','','계산 근거와 원래 위치'));
    for(const [i,ref] of doc.references.calculations.entries()){const item=el('details');item.id='final-calculation-'+i;item.append(el('summary','',ref.path+(ref.available?'':' · 연결 실패')));
      try{let value=r;for(const key of ref.path.slice(1).split('/'))value=value[key.replace(/~1/g,'/').replace(/~0/g,'~')];item.append(el('pre','',JSON.stringify(value,null,2)))}catch(e){item.append(el('p','','계산을 찾지 못했어요.'))}calculations.append(item)}
    box.append(calculations);
    const integrity=el('details','final-integrity');integrity.id='final-integrity';integrity.append(el('summary','','보고서 구성 검사와 버전'),el('p','',doc.assembly_scope),
      el('p','',status==='stored_verified'?'실행 당시 저장한 문서와 입력을 대조했어요.':status==='display_projection'?'기존 원본을 현재 표시 규칙으로 구성했어요. 새 분석이 아니에요.':'저장 문서를 확인하지 못해 원래 결과에서 표시본을 만들었어요.'),el('pre','',JSON.stringify(doc.provenance,null,2)));
    if(doc.assembly_issues.length){box.prepend(el('p','notice','보고서 구성에서 확인할 문제가 남았어요. 원본 판단은 아래에 보존했어요.'));integrity.append(el('pre','',JSON.stringify(doc.assembly_issues,null,2)))}
    box.append(integrity);
    for(const card of box.querySelectorAll('.final-claim')){
      const assumptions=card.querySelector('.reason-group');if(assumptions){const d=el('details');d.append(el('summary','','가정과 적용 조건'),assumptions);card.append(d)}
    }
    for(const card of [...box.querySelectorAll('.final-claim')]){
      const d=el('details','final-claim reader-claim-row');d.id='reader-claim-'+card.dataset.claimId;d.dataset.claimId=card.dataset.claimId;
      const summary=el('summary'),heading=card.querySelector('h4'),state=heading.nextElementSibling;
      summary.append(heading,state,el('span','hint','가정·반론·결정 영향 펼치기'));d.append(summary);
      while(card.firstChild)d.append(card.firstChild);card.replaceWith(d);
    }
    // Exact repeated objections are shown once, under the final review.
    const objections=new Set([...(open.final_review_issues||[]),...(open.unsupported_claims||[]),...(open.dissent||[])]);
    for(const group of box.querySelectorAll('.reason-group'))if(group.querySelector('h4')?.textContent==='남은 위험'){
      for(const li of [...group.querySelectorAll('li')])if(objections.has(li.textContent))li.remove();
      if(!group.querySelector('li'))group.remove();
    }
    const firstHeading=box.querySelector('h3'),reasonHeading=[...box.querySelectorAll('h3')].find(n=>n.textContent==='선택 이유와 마지막 검토');
    if(firstHeading&&reasonHeading){
      const grid=el('div','reader-overview-grid'),left=el('div'),right=el('div');firstHeading.before(grid);grid.append(left,right);
      let n=firstHeading;while(n&&n!==reasonHeading){const next=n.nextSibling;left.append(n);n=next}
      n=reasonHeading;while(n&&!n.classList.contains('final-claim')){const next=n.nextSibling;right.append(n);n=next}
    }
    // Preserve all sentences; collapse complete sections, never truncate a claim.
    function fold(title,nextTitle,id,label){
      const headings=[...box.children],start=headings.find(n=>n.tagName==='H3'&&n.textContent===title);if(!start)return;
      const d=el('details','reader-fold');d.id=id;d.append(el('summary','',label));start.before(d);
      let n=start;while(n){const next=n.nextSibling;if(n!==start&&n.tagName==='H3'&&n.textContent===nextTitle)break;d.append(n);n=next}
    }
    fold('비교한 대안','원래 질문과 남은 확인','reader-alternatives','대안 '+doc.alternatives.length+'개 · 선택 이유와 변경 조건');
    fold('원래 질문과 남은 확인','언제 무엇을 다시 확인하나','reader-questions','질문 '+open.questions.length+'개 · 미해결 '+open.questions.filter(q=>q.review?.status!=='supported').length+'개 · 전체 근거와 다음 확인');
    const monitorHeading=[...box.children].find(n=>n.tagName==='H3'&&n.textContent==='언제 무엇을 다시 확인하나');
    if(monitorHeading){let n=monitorHeading.nextSibling;while(n&&n!==refs){
      if(n.tagName==='H4'){const d=el('details','reader-monitor-row'),summary=el('summary');summary.append(n.cloneNode(true));n.before(d);let current=n;while(current&&current!==refs&&(current===n||current.tagName!=='H4')&&!current.classList?.contains('reason-group')){const next=current.nextSibling;d.append(current);current=next}d.prepend(summary);n=current}
      else if(n.classList?.contains('reason-group')){const next=n.nextSibling;const d=el('details','reader-fold');n.before(d);d.append(el('summary','',n.querySelector('h4')?.textContent||'후속 조건'),n);n=next}
      else n=n.nextSibling;
    }}
    const refDetails=el('details','reader-fold');refDetails.id='reader-references';refs.before(refDetails);refDetails.append(el('summary','','핵심 출처 '+doc.references.facts.length+'개 · 읽은 범위와 한계'),refs);
    portfolioLayout(box,doc,r,v,sources,money);
    return box;
  }
  function personas(r,v,sources){
    const recorded=(v.agent_registry?.length?v.agent_registry.map(a=>a.id):Object.keys(names)).filter(id=>r.perspectives?.[id]);
    const roles=[...new Set([...recorded,...Object.keys(r.perspectives||{})])];
    const metadata=Object.fromEntries((v.agent_registry||[]).map(a=>[a.id,[a.label,a.description]]));
    const identity=role=>metadata[role]||names[role]||[role,'독립 투자 관점'];
    $('perspective-weights').closest('table').querySelector('thead tr').replaceChildren(...['자산',...roles.map(role=>identity(role)[0]),'최종 제안'].map(label=>el('th','',label)));
    $('perspectives').replaceChildren(...roles.map(role=>{
      const p=r.perspectives?.[role],card=el('article','persona '+role);card.dataset.persona=role;
      card.append(el('p','eyebrow',identity(role)[1]),el('h3','',identity(role)[0]));
      if(!p){card.append(el('p','hint','이 관점의 분석 기록이 없어요.'));return card}
      card.append(el('p','persona-thesis',p.thesis),section('이 판단을 한 근거',p.decision_basis,'이전 형식의 보고서예요. 아래 가정과 원본 분석에서 근거를 확인해요.'));
      const weights=el('div','persona-weights');
      for(const [s,w] of Object.entries(p.weights).filter(([,w])=>w>0).sort((a,b)=>b[1]-a[1])){const row=el('div','exposure-row');row.append(el('span','',symbol(s)),el('b','',pct(w)),track(w,role));weights.append(row)}
      card.append(weights,section('지난 판단에서 달라진 점',p.changes_since_previous,v.previous?'변화가 별도로 기록되지 않았어요.':'최초 평가여서 비교할 이전 판단이 없어요.'));
      card.append(section('핵심 가정',p.assumptions),section('위험 · 반대 근거',p.risks));
      const details=el('details');details.append(el('summary','','판단을 바꿀 조건과 다음 확인'),section('판단을 바꿀 조건',p.falsifiers),section('다음에 확인할 것',p.next_checks));
      const prior=v.previous?.perspectives?.[role];if(prior)details.append(el('h4','','지난 판단'),el('p','',prior.thesis));
      if(r.reflection?.perspective_review?.[role])details.append(el('h4','','이 관점의 지난 분석 평가'),el('p','',r.reflection.perspective_review[role]));
      card.append(details,sourceLinks(p.evidence_ids,sources));
      const status=r.validation.numeric?.[role]?.status;if(status)card.append(el('p','hint','관점별 수치 평가: '+({pass:'수치 조건 충족',blocked:'제한 위반',needs_review:'추가 확인 필요'}[status]||status)));
      return card;
    }));
    const maps=[...roles.map(role=>r.perspectives?.[role]?.weights||{}),r.proposal.weights];
    const symbols=[...new Set(maps.flatMap(w=>Object.keys(w)))].filter(s=>maps.some(w=>w[s]>0));
    $('perspective-weights').replaceChildren(...symbols.map(s=>{const tr=el('tr');tr.append(el('th','',symbol(s)));tr.firstChild.scope='row';
      maps.forEach((w,i)=>{const td=el('td','weight-cell');td.append(el('span','',pct(w[s]||0)),track(w[s]||0,roles[i]||'proposal'));tr.append(td)});return tr}));
  }
  function allocation(r,v,money,capital){
    const maps=[r.valuation.nav>0?r.valuation.weights:null,r.proposal.weights,v.previous?.proposal?.weights||null];
    const symbols=[...new Set(maps.flatMap(w=>Object.keys(w||{})))].filter(s=>maps.some(w=>w?.[s]>0));
    const series=['actual','proposal','previous'],label=['실제 보유','이번 제안','지난 제안'];
    $('allocation-chart').replaceChildren(...symbols.map(s=>{
      const row=el('div','allocation-row');row.append(el('b','allocation-symbol',symbol(s)));const bars=el('div','allocation-bars');
      maps.forEach((w,i)=>{const line=el('div','allocation-line');line.append(el('span','bar-label',label[i]),track(w?.[s]||0,series[i]),el('span','bar-value',w?pct(w[s]||0):'비교 없음'));bars.append(line)});row.append(bars);return row;
    }));
    const sleeve=r.analysis?.allocation_sleeves;if(sleeve){const box=el('section','reason-group');box.append(el('h3','','투자 부분과 현금 완충'),el('p','hint',sleeve.scope));const t=el('table'),head=el('tr');for(const x of ['자산','전체 납입 비중','투자 부분 내부','월평균 환산액'])head.append(el('th','',x));t.append(head);for(const x of sleeve.rows){const row=el('tr');for(const value of [symbol(x.symbol),pct(x.whole_fraction),x.invested_fraction==null?'현금 완충':pct(x.invested_fraction),money(x.monthly_amount)])row.append(el('td','',value));t.append(row)}box.append(t,el('p','hint',sleeve.cash_warning));$('allocation-chart').append(box)}
    table('weights',symbols.map(s=>[symbol(s),pct(maps[1][s]||0),money((maps[1][s]||0)*capital),maps[0]?pct(maps[0][s]||0):'보유 없음',maps[2]?pct(maps[2][s]||0):'비교 없음']));
  }
  function render(row){
    const focused=document.activeElement,focusedChapter=focused?.dataset.chapter,focusedAsset=focused?.matches('.allocation-legend-title')?focused.closest('[data-symbol]').dataset.symbol:null,focusedReset=focused?.matches('.allocation-reset');
    const changedReport=renderedId!==row.id;if(changedReport){selectedChapter='all';selectedAsset=null}
    const opened=renderedId===row.id?[...$('report-content').querySelectorAll('details[id][open]')].map(n=>n.id):[];
    // These are rebuilt each render; persistent legacy sections stay in the archive.
    for(const id of ['reader-supporting','role-report-history'])$(id)?.remove();
    const keepEvidence=renderedId===row.id&&evidencePinned&&factGraph&&JSON.stringify(factGraph)===JSON.stringify(row.view?.evidence_graph);
    const keptIds=evidenceReturnTrigger?.dataset.evidenceIds||evidenceTrigger?.dataset.evidenceIds,keptPaths=evidenceReturnTrigger?.dataset.calculationPaths||evidenceTrigger?.dataset.calculationPaths;if(!keepEvidence)closeEvidence();factGraph=row.view?.evidence_graph;factReport=row.body;factSources=row.view?.sources||[];
    const r=row.body,v=row.view||{},p=r.proposal,a=r.validation.final_numeric,m=a.metrics||{},h=a.historical||{},prior=v.previous;
    const currency=v.base_currency||'KRW',money=n=>n==null?'계산 불가':number(n,currency==='KRW'?0:2)+' '+currency;
    const capital=r.funding?.proposal_capital??r.valuation.nav,sources=v.sources||[],market=v.market_analysis||{},reflection=r.reflection;
    $('report-empty').hidden=true;$('report-content').hidden=false;$('report-demo').hidden=r.mode!=='demo';
    text('report-kind',r.revision_of?'같은 날 수정본':prior?'주간 평가':'최초 포트폴리오');
    text('report-title',(prior?'주간 분석':'초기 포트폴리오')+' 리포트');
    text('report-period',(prior?prior.as_of+' → ':'')+r.as_of+' · 기준통화 '+currency);
    text('action',action[p.action]||p.action);$('action').dataset.status=p.action;text('rationale',p.rationale);
    let budgetNotice=$('risk-budget-notice');if(!budgetNotice){budgetNotice=el('p','notice');budgetNotice.id='risk-budget-notice';$('report-context').before(budgetNotice)}const budget=r.risk_budget;budgetNotice.hidden=budget?.scope!=='analysis_only';budgetNotice.textContent=budget?.scope==='analysis_only'?`분석 전용 · 이번 제안의 충격 비교 예산 ${pct(budget.effective_fraction)} / 기존 기준 ${pct(budget.reference_fraction)}. 실제 감내손실은 미확인이고 이 보고서로 주문 계획을 만들 수 없어요.`:'';
    $('report-metadata')?.remove();if(r.revision_reason||r.history_scope?.reset_id){const metadata=el('details','report-metadata');metadata.id='report-metadata';metadata.append(el('summary','','보고서 작성 이력'));if(r.revision_reason)metadata.append(el('p','hint','수정 이유: '+r.revision_reason));if(r.history_scope?.reset_id)metadata.append(el('p','hint','초기화 이전의 분석·회고·학습 기억은 제외했어요. 초기화 이후에 쌓인 판단과 학습은 다시 사용할 수 있어요. 원본 기록과 현재 개인 사실은 보존돼요.'));$('report-period').after(metadata)}
    text('report-context',v.context?.summary||v.criteria?.goal||'당시 투자 맥락은 원본 실행 기록에서 확인해요.');
    let structured=$('structured-report');if(!structured){structured=el('div');structured.id='structured-report';$('report-context').after(structured)}structured.replaceChildren();
    if(v.final_report)structured.append(readerDocument(v.final_report,v.final_report_status,r,sources,money,v));
    $('report-content').dataset.finalReader=String(Boolean(v.final_report?.reasons));
    const reports=v.judgment_report_history?.length?v.judgment_report_history:v.judgment_reports||[],history=el('details','role-history');history.id='role-report-history';
    history.append(el('summary','','판단 과정 원문과 수정 이력'));
    if(reports.length){history.append(el('p','notice',v.judgment_report_status?.rule||'각 역할·단계의 원문 의견이며 공식 최종 상태와 함께 읽어주세요.'));
      for(const item of reports){const report=item.report&&typeof item.report==='object'?item.report:{},article=el('article','role-output'+(item.report?' judgment-report':''));article.dataset.role=item.role;article.dataset.stage=item.stage;
        article.id='role-output-'+item.source_output_id;
        article.append(el('h3','',typeof report.title==='string'?report.title:'구조화 원문 · '+item.role),el('p','hint',(report.as_of||r.as_of)+' · '+item.role+' / '+item.stage),el('p','notice','공식 최종 상태: '+(action[p.action]||p.action)+' · 이 문서는 해당 단계의 의견이며 주문 지시가 아니에요.'));
        if(item.contract_accepted!==undefined)article.append(el('p','hint',item.latest_accepted_for_stage?'이 단계의 마지막 계약 수용본':item.contract_accepted?'이전 계약 수용본':'계약 미수용 출력'));
        if(item.feedback){const feedback=el('details');feedback.append(el('summary','','수정 요청 원문'),el('pre','',JSON.stringify(item.feedback,null,2)));article.append(feedback)}
        if(item.report&&item.contract_accepted!==false){
          for(const [key,label] of [['portfolio_context','현재 포트폴리오와 투자 맥락'],['market_context','현재 시황과 투자 영향'],['decision_method','검토 기준과 판단 절차'],['conclusion','이 역할의 최종 의견']]){const section=el('section');section.append(el('h4','',label));for(const paragraph of (typeof report[key]==='string'?report[key]:'원문에 이 항목이 없어요.').split(/\n\s*\n/))section.append(el('p','',paragraph));article.append(section)}
          article.append(sourceLinks(Array.isArray(report.evidence_ids)?report.evidence_ids:[],sources));
        }
        const original=el('details');original.append(el('summary','','구조화 출력 원문'),el('pre','',JSON.stringify(item.structured_output??item.report,null,2)));article.append(original);history.append(article)}
    }else history.append(el('p','hint','이전 형식의 보고서예요. 당시 작성된 요약을 아래에 보존하며 새 상세 본문을 소급해서 만들지 않았어요.'));
    if(p.investment_case&&!v.final_report?.reasons){
      const c=p.investment_case;structured.append(el('h3','','승인 전에 읽을 핵심 판단'));
      for(const line of c.key_points)structured.append(el('p','',line));
      structured.append(el('h3','','대안별 선택 이유와 변경 조건'));
      for(const option of c.alternatives)structured.append(el('h4','',option.name),el('p','notice','상태: '+({preferred:'선호 대안',rejected:'채택하지 않음',diagnostic_only:'제약 검토용',conditional:'조건부'}[option.decision]||option.decision||'미기록')),el('p','',Object.entries(option.weights||{}).map(([s,w])=>symbol(s)+' '+pct(w)).join(' · ')),el('p','',option.reason),el('p','hint','판단 변경 조건: '+option.change_condition));
      structured.append(el('h3','','핵심 주장과 반대 근거'));
      for(const claim of c.claims){const block=el('article','source-card');block.append(el('h4','',claim.statement),el('p','notice','주장 상태: '+({supported:'근거 확인',conditional:'조건부',unresolved:'미해결'}[claim.status]||claim.status||'미기록')),section('적용 가정',claim.assumptions),el('p','','반대 근거: '+claim.counterevidence),el('p','','판단 영향: '+claim.decision_impact),sourceLinks(claim.fact_ids,sources));structured.append(block)}
    }
    const quality=v.quality_evaluation;if(quality){structured.append(el('h3','','독립 보고서 품질 평가'),el('p','notice',(quality.score.strict_pass===true?'엄격 기준 충족':quality.score.strict_pass===false?'엄격 기준 미충족':'이전 척도 · 엄격 기준 미평가')+' · '+quality.score.total+' / 100 · 기준 v'+quality.rubric.version),el('p','',quality.output.summary));for(const [id,state] of Object.entries(quality.score.gates||{}))structured.append(el('p','',id+' · '+({pass:'충족',fail:'실패',unknown:'미확인'}[state]||state)));structured.append(el('p','hint','보고서 품질 평가이며 수익 예측·사용자 승인·주문 권한이 아니에요. 세부 관찰 항목과 원본 계산은 분석 작업실에서 확인해요.'))}
    const post=v.evaluation_stability;if(post)structured.append(el('h3','','이 보고서의 후속 표현·순서 시험'),el('p','notice',(post.passed?'사전 조건 충족':'사전 조건 미충족')+' · '+post.valid_outputs+'/'+post.cases+'개 유효 응답 · 점수 범위 '+(post.total_score_range==null?'미확인':post.total_score_range.toFixed(1))+'점'),el('p','hint','원래 평가 점수·gate를 수정하지 않은 별도 후속 시험이에요. 투자 성과·평가 정확성 보증이 아니에요.'),el('p','hint',post.scope));
    const joint=r.analysis?.household?.joint_stress;if(joint && Array.isArray(joint.scenarios)){structured.append(el('h3','','가계 동시 충격과 납입 재개'),el('p','hint',joint.scope));for(const x of joint.scenarios)structured.append(el('p','','소득 '+pct(x.income_fraction_assumption)+' 유지 · 금리 +'+pct(x.mortgage_rate_increase_assumption)+' · 6개월 필요 현금 '+number(x.cash_needed_if_contributions_paused,0)+' / 계좌 현금 대비 부족액 '+number(x.gap_against_reported_account_cash_only,0)+' / 납입 재개 월 소득 '+number(x.income_needed_to_resume_planned_contribution,0)+' '+(r.analysis?.fx_stress?.base_currency||v.base_currency||'통화 미확인')));structured.append(el('p','hint',joint.liquidity_basis),el('p','hint',joint.limitations))}
    if(v.portfolio_replay?.status==='no_comparable_replay'){
      structured.append(el('p','notice','이 제안과 비교할 수 있는 과거 시점 재생 사례가 아직 연결되지 않았어요.'));
    }
    for(const item of v.portfolio_replay?.cases||[]){
      const result=item.score;
      structured.append(el('h3','','유사 과거 시점 재생'),el('p','',item.comparability),
        el('p','hint',result.start+' ~ '+result.end+' · '+result.observations+'거래일 · '+result.currency+' · '+result.basis),
        el('p','','과거 제안 '+pct(result.proposal.return)+' · 기준안 '+pct(result.benchmark.return)
          +' · 최대 낙폭 '+pct(result.proposal.max_drawdown)+' / '+pct(result.benchmark.max_drawdown)));
    }
    const krw=r.analysis?.krw_comparison;if(krw?.available){structured.append(el('h3','','원화 기준 역사적 배분 비교'),el('p','notice','별도 계산 재현: '+({passed:'일치',failed:'불일치 · 검증 실패 수치를 승인 근거로 사용하지 않아요.'}[krw.independent_replay?.status]||'미확인')),el('p','hint',krw.start+' ~ '+krw.end+' · '+krw.observations+'개월 · '+krw.amount_unit),el('p','notice',krw.cash_scope),el('p','hint',krw.cost_scope));for(const [name,result] of Object.entries(krw.results))structured.append(el('p','',name+' · 연환산 '+pct(result.annualized_return)+' · 월말 최대 낙폭 '+pct(result.month_end_max_drawdown)+' · 납입 '+number(result.contributed,0)+' / 평가액 '+number(result.ending_wealth,0)+' / 손익 '+number(result.profit,0)+' KRW'));structured.append(el('p','hint',krw.fx_source_limits),el('p','hint',krw.independent_replay?.scope||''))}
    const comparison=r.analysis?.comparison;if(comparison?.sensitivity_unavailable_reason)structured.append(el('p','notice',comparison.sensitivity_unavailable_reason));if(comparison?.unavailable_selected_assets?.length)structured.append(el('p','notice','이번 제안 자체의 백테스트는 미완료예요. 공통 수익률 자료가 없는 자산: '+comparison.unavailable_selected_assets.join(', ')+'. 아래 지수 비교 결과는 제안 수익률이 아니에요.'));if(comparison?.available){structured.append(el('h3','','동일 조건의 역사적 배분 비교'),el('p','hint',comparison.start+' ~ '+comparison.end+' · '+comparison.observations+'개월 · '+comparison.amount_unit),el('p','notice',comparison.cash_proxy_warning));for(const [name,result] of Object.entries(comparison.results))structured.append(el('p','',name+' · 연환산 '+pct(result.annualized_return)+' · 월별 연환산 변동성 '+pct(result.annualized_volatility)+' · 월말 최대 낙폭 '+pct(result.month_end_max_drawdown)+' · 납입 '+number(result.contributed,1)+' / 평가액 '+number(result.ending_wealth,1)+' / 손익 '+number(result.profit,1)+' (정규화 USD)'));for(const limit of comparison.limitations)structured.append(el('p','hint',limit))}
    let personaNote=$('report-persona');if(!personaNote){personaNote=el('p','notice');personaNote.id='report-persona';$('report-context').after(personaNote)}const persona=v.user_persona;personaNote.textContent=persona?'이 보고서의 개인 페르소나 v'+persona.body.version+' · '+(v.persona_is_current?'현재 설정과 같아요.':'현재 설정과 달라요. 보고서는 당시 맥락을 유지해요.'):'이전 보고서에는 개인 페르소나 버전이 별도로 기록되지 않았어요.';
    cards('report-summary',[['실제 보유 평가액',money(r.valuation.nav)],['제안 기준액',money(capital)],['추가 필요 자금',money(r.funding?.additional_funding_needed??0)]]);
    text('market-summary',market.summary||'이전 형식의 리포트예요. 당시 기록된 변화와 출처를 확인해요.');
    list('market-drivers',market.drivers,'주요 요인이 별도로 기록되지 않았어요.');list('market-changes',market.changes||p.market_changes,prior?'기록된 변화가 없어요.':'최초 평가여서 비교할 이전 자료가 없어요.');
    list('market-implications',market.portfolio_implications,'기록된 해석이 없어요.');list('market-uncertainties',market.uncertainties);
    $('market-summary').append(sourceLinks(market.facts,sources));
    text('price-note','스냅샷 가격의 변화이며 배당·분할·입출금을 반영한 투자 수익률이 아니에요. '+currency+' 환산 가격은 환율 변화도 포함해요.');
    table('market-prices',(v.prices||[]).map(q=>[symbol(q.symbol),q.previous_price==null?'비교 없음':money(q.previous_price),money(q.price),q.price_change==null?'비교 없음':pct(q.price_change),(q.previous_observed_at?q.previous_observed_at+' → ':'')+q.observed_at]));
    personas(r,v,sources);allocation(r,v,money,capital);
    text('funding',`실제 평가액 ${money(r.valuation.nav)} · 제안 기준액 ${money(capital)} · 추가 필요 ${money(r.funding?.additional_funding_needed??0)} · 제안 범위 밖 ${money(r.funding?.amount_outside_proposal??0)}. 각 비중은 해당 구성의 총액 기준이에요.`);
    list('premise-changes',p.premise_changes);text('leader-response',p.validation_response);list('risks',[...(p.risks||[]),...(p.dissent||[])]);list('checks',p.next_checks);
    const qualitative=r.validation.final_critique;
    text('evaluation-status',qualitative.qualitative_pass===false?'정성 검증 보류':({pass:'수치 조건 충족',blocked:'제한 위반',needs_review:'추가 확인 필요'}[a.status]||'검증 기록'));
    $('evaluation-status').dataset.status=qualitative.qualitative_pass===false?'blocked':a.status;
    cards('metrics',[
      ['가정한 시나리오 손실',pct(a.scenario_loss_fraction),'손실 상한 보장이 아니에요.'],['시나리오 손실액',money(m.scenario_loss_amount)],['최대 종목 비중',pct(m.max_position_fraction)],
      ['종목 HHI',m.position_hhi==null?'해당 없음':number(m.position_hhi,3),'현금 제외 · ETF 내부 미반영'],['유효 종목 수',m.effective_positions==null?'해당 없음':number(m.effective_positions)],['제안 현금 / 월 지출',m.cash_months_of_expenses==null?'해당 없음':number(m.cash_months_of_expenses)+'개월','미납입 금액을 포함할 수 있는 계획 비율 · 실제 비상금 아님'],
      ['연환산 변동성',pct(h.annualized_volatility)],['Sharpe ratio',number(h.sharpe,2)],['과거 최대 낙폭',pct(h.max_drawdown)]
    ]);
    const sectors={...(m.sector_exposures||{})};if(m.unknown_sector_fraction)sectors.unknown=m.unknown_sector_fraction;
    exposure('sector-chart',sectors,v.criteria?.criteria?.max_sector_fraction);exposure('class-chart',m.asset_classes);exposure('currency-chart',m.currencies);
    list('evaluation-issues',[...(a.errors||[]),...(a.missing||[]),...(a.warnings||[]),...(qualitative.issues||[]),...(qualitative.unsupported_claims||[])].map(message=>a.historical?.status!=='available'&&r.analysis?.comparison?.available&&/변동성.*자료 부족/.test(message)?'일별 시세 기준: '+message+' · 월별 NAV 비교는 별도 표를 확인해주세요.':message),'기록된 위반이나 확인 항목이 없어요. 손실 위험이 없다는 뜻은 아니에요.');
    list('evaluation-limits',[...(a.limitations||[]),h.reason||h.method,qualitative.reason&&'검증 에이전트: '+qualitative.reason].filter(Boolean));text('validation',JSON.stringify(r.validation,null,2));
    const perf=r.performance;
    cards('performance-summary',perf?[['기간 시작 평가액',money(perf.start_nav)],['확인된 손익',money(perf.pnl)],['기간 수익률 · Modified Dietz',pct(perf.modified_dietz)]]:[]);
    text('performance-note',!perf?'최초 평가예요. 비교할 과거 투자 결과가 아직 없어요.':perf.limitation||'실제 보유와 외부 입출금을 반영한 구간 성과예요. 제안의 성과나 특정 에이전트의 기여도로 간주하지 않아요.');
    text('investment-reflection',reflection?.investment_outcome||'다음 평가부터 실제 결과와 당시 판단을 비교해요.');text('process-reflection',reflection?.process_evaluation||'다음 평가부터 근거 수집·분석·검증 과정의 개선점을 기록해요.');list('lessons',reflection?.lessons,'아직 축적된 실행 회고가 없어요.');
    text('next',`다음 평가 기준일 ${r.next_evaluation} · 리밸런싱 기준일 ${r.next_rebalance}${r.rebalance_due?' (검토 시점 도래)':''}. 평가와 리밸런싱은 별개이며 제안은 실제 보유를 바꾸지 않아요.`);
    const memory=v.memory||[],opLabels={add:'추가',merge:'통합',revise:'수정',deactivate:'비활성화',archive:'보관'};
    list('memory-summary',memory.map(x=>x.summary),'최초 평가이거나 별도의 지식 갱신 제안이 없어요.');
    list('memory-operations',memory.flatMap(x=>(x.operations||[]).map(op=>(opLabels[op.action]||op.action)+': '+(op.text||op.key||'')+' · '+op.reason)), '에이전트가 제안한 변경이 없어요.');
    list('memory-conflicts',[...memory.flatMap(x=>x.conflicts||[]),...(v.pruning?.unresolved_groups||[]).map(x=>'추가 검토: '+x.topic+' · 적용 조건 '+x.condition)],'미해결 충돌이 별도로 기록되지 않았어요.');
    text('anchor-summary',`정기 전체 점검 변경 기록 ${v.pruning?.changes?.length??0}건. 목표·제약, 현재 보유 이유, 미해결 위험과 다음 확인은 실행 기록에 보존돼요. 원본 기록은 가지치기로 삭제하지 않아요.`);
    sourcesView(sources,v.expired_source_count);text('agent-records',JSON.stringify(v.agent_records||{},null,2));const {view,...original}=row;text('raw',JSON.stringify(original,null,2));
    if(v.final_report?.reasons){
      let context=$('reader-context-original');if(!context){context=el('details','reader-fold');context.id='reader-context-original';context.append(el('summary','','개인 맥락과 종합 원문'));$('structured-report').before(context);for(const n of [$('rationale')?.closest('.decision-strip'),$('report-context'),$('report-persona')])if(n)context.append(n)}
      const support=el('details','reader-fold');support.id='reader-supporting';support.append(el('summary','','수치 비교와 후속 평가 상세'));
      const core=$('final-reader');let n=core.nextSibling;while(n){const next=n.nextSibling;support.append(n);n=next}structured.append(support);
      for(const [id,label] of [['agents','관점별 비교'],['proposal','배분 상세'],['evaluation','위험 수치와 전체 검증'],['reflection-report','결과와 회고'],['sources-report','전체 근거 DB · fact ID와 원문']]){
        const section=$(id);if(!section)continue;let wrapper=$('reader-extra-'+id);if(!wrapper){wrapper=el('details','reader-fold reader-extra');wrapper.id='reader-extra-'+id;section.before(wrapper);wrapper.append(el('summary','',label),section)}
      }
    }
    structured.append(history);
    // The early market opinion remains accessible, but never reads as the
    // final allocation. This also applies to older immutable reports.
    let early=$('early-market-record');if(!early){early=el('details','early-market-record');early.id='early-market-record';early.append(el('summary','','초기 시황 기록 · 최종 제안 전에 작성했어요.'));$('market-report').before(early);early.append($('market-report'))}
    if(v.final_report?.reasons){
      const context=$('reader-context-original');
      for(const n of [$('report-summary'),$('report-overview').querySelector('.flow-strip')])if(n&&context&&!context.contains(n))context.append(n);
      let archive=$('report-archive');if(!archive){archive=el('details','reader-fold report-archive');archive.id='report-archive';archive.append(el('summary','','분석 상세와 원본 기록'));$('report-overview').after(archive)}
      for(const id of ['reader-context-original','early-market-record','reader-extra-agents','reader-extra-proposal','reader-extra-evaluation','reader-extra-reflection-report','reader-extra-sources-report','reader-supporting','role-report-history']){const node=$(id);if(node&&!archive.contains(node))archive.append(node)}
    }
    if(keepEvidence){const next=[...$('report-content').querySelectorAll('[data-evidence-ids]')].find(n=>n.dataset.evidenceIds===keptIds&&n.dataset.calculationPaths===keptPaths);if(next){evidenceTrigger=next;evidenceReturnTrigger=next;next.setAttribute('aria-expanded','true')}else closeEvidence()}
    if(renderedId!==row.id)early.open=false;for(const id of opened){const item=$(id);if(item)item.open=true}renderedId=row.id;if(changedReport)revealAnchor(location.hash);else{const control=focusedChapter?[...document.querySelectorAll('.reader-navigation button')].find(n=>n.dataset.chapter===focusedChapter):focusedAsset?[...document.querySelectorAll('.allocation-legend-title')].find(n=>n.closest('[data-symbol]').dataset.symbol===focusedAsset):focusedReset?document.querySelector('.allocation-reset'):null;control?.focus({preventScroll:true})}
  }
  return {render};
})();
