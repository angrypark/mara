/* Read-only report renderer. Model/source text is always inserted as text, never HTML. */
'use strict';
window.MaraReport=(()=>{
  const $=id=>document.getElementById(id);
  const el=(tag,cls,value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!=null)n.textContent=value;return n};
  const text=(id,value)=>{$(id).textContent=value??'기록 없음'};
  const pct=n=>n==null?'계산 불가':(n*100).toFixed(1)+'%';
  const number=(n,d=1)=>n==null?'계산 불가':Number(n).toLocaleString('ko-KR',{maximumFractionDigits:d});
  const action={hold:'유지',adjust:'조정 제안',defer:'보류'};
  const names={buffett:['Warren Buffett','기업 가치 · 안전마진'],marks:['Howard Marks','위험 · 사이클'],bogle:['John Bogle','비용 · 분산']};
  const labels={equity:'주식',bond:'채권',cash:'현금',unknown:'미확인',other:'기타'};
  const sourceId=i=>'report-source-'+i;
  const symbol=s=>s==='CASH'?'기준통화 현금':s;
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
  function sourceLinks(ids,sources){
    const box=el('div','source-chips');
    for(const id of ids||[]){const i=sources.findIndex(s=>s.id===id);if(i<0){box.append(el('span','hint','연결되지 않은 근거: '+id));continue}
      const a=el('a','source-chip','근거 '+(i+1));a.href='#'+sourceId(i);a.title=sources[i].topic+' · '+id;box.append(a)}
    if(!box.childElementCount)box.append(el('span','hint','인용된 근거가 없어요.'));return box;
  }
  function sourcesView(sources,expired){
    text('source-note',`이 평가에서 사용 가능한 근거 ${sources.length}개. ${expired||0}개의 만료 근거는 현재 목록에서 제외했으며 원본 실행 기록에는 보존돼요. 출처 수는 독립적인 정보의 수나 신뢰도 점수가 아니에요.`);
    $('source-list').replaceChildren(...sources.map((s,i)=>{
      const card=el('article','source-card');card.id=sourceId(i);
      card.append(el('h3','',`${i+1}. ${s.topic||s.id}`),el('p','hint',`발표 ${s.published_at} · 인지 ${s.known_at} · 유효 ${s.valid_until}`));
      const detail=el('details');detail.append(el('summary','','근거 내용 · '+s.id),el('p','source-text',s.text));card.append(detail);
      if(s.uncertainty)card.append(el('p','hint','자료의 한계: '+s.uncertainty));
      try{const url=new URL(s.source);if(url.protocol==='https:'){const link=el('a','','출처 보기 · '+url.hostname);link.href=url.href;link.target='_blank';link.rel='noreferrer noopener';card.append(link)}}catch(e){}
      return card;
    }));
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
    table('weights',symbols.map(s=>[symbol(s),pct(maps[1][s]||0),money((maps[1][s]||0)*capital),maps[0]?pct(maps[0][s]||0):'보유 없음',maps[2]?pct(maps[2][s]||0):'비교 없음']));
  }
  function render(row){
    const r=row.body,v=row.view||{},p=r.proposal,a=r.validation.final_numeric,m=a.metrics||{},h=a.historical||{},prior=v.previous;
    const currency=v.base_currency||'KRW',money=n=>n==null?'계산 불가':number(n,currency==='KRW'?0:2)+' '+currency;
    const capital=r.funding?.proposal_capital??r.valuation.nav,sources=v.sources||[],market=v.market_analysis||{},reflection=r.reflection;
    $('report-empty').hidden=true;$('report-content').hidden=false;$('report-demo').hidden=r.mode!=='demo';
    text('report-kind',r.revision_of?'같은 날 수정본':prior?'주간 평가':'최초 포트폴리오');
    text('report-title',(prior?'주간 분석':'초기 포트폴리오')+' 리포트');
    text('report-period',(prior?prior.as_of+' → ':'')+r.as_of+' · 기준통화 '+currency+(r.revision_reason?' · 수정 이유: '+r.revision_reason:''));
    text('action',action[p.action]||p.action);$('action').dataset.status=p.action;text('rationale',p.rationale);
    text('report-context',v.context?.summary||v.criteria?.goal||'당시 투자 맥락은 원본 실행 기록에서 확인해요.');
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
      ['종목 HHI',m.position_hhi==null?'해당 없음':number(m.position_hhi,3),'현금 제외 · ETF 내부 미반영'],['유효 종목 수',m.effective_positions==null?'해당 없음':number(m.effective_positions)],['생활비 현금 여력',m.cash_months_of_expenses==null?'해당 없음':number(m.cash_months_of_expenses)+'개월'],
      ['연환산 변동성',pct(h.annualized_volatility)],['Sharpe ratio',number(h.sharpe,2)],['과거 최대 낙폭',pct(h.max_drawdown)]
    ]);
    const sectors={...(m.sector_exposures||{})};if(m.unknown_sector_fraction)sectors.unknown=m.unknown_sector_fraction;
    exposure('sector-chart',sectors,v.criteria?.criteria?.max_sector_fraction);exposure('class-chart',m.asset_classes);exposure('currency-chart',m.currencies);
    list('evaluation-issues',[...(a.errors||[]),...(a.missing||[]),...(a.warnings||[]),...(qualitative.issues||[]),...(qualitative.unsupported_claims||[])],'기록된 위반이나 확인 항목이 없어요. 손실 위험이 없다는 뜻은 아니에요.');
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
  }
  return {render};
})();
