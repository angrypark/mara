// Run from repository root after the Happy DOM setup in dashboard-feedback.mjs.
// Render real synthetic Engine reports; never access the user's service or portfolio.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { Window } from '../.local/test-ui/node_modules/happy-dom/lib/index.js';
const fixture=JSON.parse(execFileSync('python3',['-c',"import runpy; runpy.run_path('tests/report_fixture.py', run_name='__main__')"],{maxBuffer:16*1024*1024,encoding:'utf8'}));
const html=await readFile('web/dashboard.html','utf8'),reportScript=await readFile('web/report.js','utf8'),dashboard=await readFile('web/dashboard.js','utf8');
const tick=()=>new Promise(r=>setTimeout(r,0));
function setup(){
  const w=new Window({url:'http://127.0.0.1:8788',settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true,disableIframePageLoading:true}});
  w.HTMLElement.prototype.scrollIntoView=function(){};w.setInterval=()=>0;
  w.document.write(html.replace(/<script[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link[^>]*>/g,''));w.eval(reportScript);
  return {w,$:id=>w.document.getElementById(id),render:row=>w.MaraReport.render(row),close:()=>w.happyDOM.close()};
}
const cases=[];const test=(name,run)=>cases.push({name,run});
test('weekly report joins actual prior evidence and all persona rationale sections',async()=>{
  const h=setup();try{
    h.render(fixture.weekly);
    assert.equal(h.$('report-content').hidden,false);assert.equal(h.$('report-demo').hidden,false);
    assert.match(h.$('report-title').textContent,/주간/);assert.match(h.$('report-period').textContent,/2026-11-14 → 2026-11-21/);
    assert.match(h.$('report-summary').textContent,/USD/);assert.match(h.$('market-summary').textContent,/실제 시황 분석이 아니/);
    assert.equal(h.$('perspectives').querySelectorAll('article').length,4);
    for(const p of h.$('perspectives').children){assert.match(p.textContent,/이 판단을 한 근거/);assert.match(p.textContent,/핵심 가정/);assert.match(p.textContent,/판단을 바꿀 조건/);assert.match(p.textContent,/지난 판단/)}
    assert.equal(h.$('perspective-weights').querySelectorAll('tr').length,3);assert.match(h.$('market-prices').textContent,/1.0%/);
    assert.match(h.$('allocation-chart').textContent,/실제 보유.*이번 제안.*지난 제안/);
    assert.equal(h.$('weights').querySelector('tr').children.length,5);assert.match(h.$('leader-response').textContent,/DEMO/);
    assert.match(h.$('memory-summary').textContent,/DEMO/);assert.match(h.$('anchor-summary').textContent,/원본 기록/);
    for(const a of h.w.document.querySelectorAll('.source-chip'))assert.ok(h.w.document.querySelector(a.getAttribute('href')));
  }finally{await h.close()}
});
test('unreconciled performance and missing history never become zero returns',async()=>{
  const h=setup();try{
    h.render(fixture.weekly);
    const perf=h.$('performance-summary').textContent;assert.match(perf,/확인된 손익계산 불가/);assert.match(perf,/Modified Dietz계산 불가/);
    assert.doesNotMatch(perf,/0.0%/);assert.match(h.$('performance-note').textContent,/입출금 대조/);
    assert.match(h.$('metrics').textContent,/연환산 변동성계산 불가/);assert.match(h.$('sector-chart').textContent,/미확인/);
    h.render(fixture.initial);assert.equal(h.$('performance-summary').children.length,0);assert.match(h.$('performance-note').textContent,/최초 평가/);
    assert.match(h.$('allocation-chart').textContent,/비교 없음/);assert.equal(h.$('report-kind').textContent,'최초 포트폴리오');
  }finally{await h.close()}
});
test('independent proposals, actual holdings, cap violations, zero balances and revisions remain distinct',async()=>{
  const h=setup();try{
    const r=structuredClone(fixture.weekly),b=r.body;b.mode='live';
    b.proposal.weights={BROAD:.2,CASH:.8};b.perspectives.buffett.weights={BROAD:.7,CASH:.3};
    b.perspectives.marks.weights={BROAD:.1,CASH:.9};b.revision_of='earlier-revision';b.revision_reason='수치 제한 수정';
    b.validation.final_numeric.metrics.sector_exposures={Technology:.6};r.view.criteria.criteria={max_sector_fraction:.3};
    b.valuation={nav:0,weights:{},values:{}};h.render(r);
    assert.equal(h.$('report-demo').hidden,true);assert.equal(h.$('report-kind').textContent,'같은 날 수정본');
    const row=Array.from(h.$('perspective-weights').querySelectorAll('tr')).find(x=>x.firstChild.textContent==='BROAD');
    assert.equal(row.children[1].textContent,'70.0%');assert.equal(row.children[2].textContent,'10.0%');assert.equal(row.children[5].textContent,'20.0%');
    assert.match(h.$('weights').textContent,/보유 없음/);assert.ok(h.$('sector-chart').querySelector('.bar.over'));
    assert.equal(h.$('sector-chart').querySelector('.limit-mark').style.left,'30%');
  }finally{await h.close()}
});
test('new perspectives extend printable cards and comparison columns',async()=>{
  const h=setup();try{
    const r=structuredClone(fixture.weekly);r.body.perspectives.additional=structuredClone(r.body.perspectives.bogle);
    r.view.agent_registry=[{id:'additional',label:'추가 관점',description:'확장 검증'}];h.render(r);
    assert.equal(h.$('perspectives').children.length,5);assert.match(h.$('perspectives').querySelector('[data-persona="additional"]').textContent,/추가 관점/);
    assert.equal(h.$('perspective-weights').querySelector('tr').children.length,7);
    assert.match(h.$('perspective-weights').closest('table').querySelector('thead').textContent,/추가 관점/);
  }finally{await h.close()}
});
test('older report fields degrade explicitly and untrusted strings stay inert',async()=>{
  const h=setup();try{
    const r=structuredClone(fixture.weekly);r.view.market_analysis=null;
    for(const p of Object.values(r.body.perspectives)){delete p.decision_basis;delete p.changes_since_previous}
    r.body.perspectives.buffett.thesis='<img src=x onerror="window.compromised=true">';
    r.view.sources[0].source='javascript:window.compromised=true';r.view.sources[0].text='<script>window.compromised=true</script>';
    h.render(r);assert.match(h.$('market-summary').textContent,/이전 형식/);assert.match(h.$('perspectives').textContent,/이전 형식/);
    assert.equal(h.$('perspectives').querySelectorAll('img').length,0);assert.equal(h.$('source-list').querySelectorAll('a,script').length,0);
    assert.match(h.$('source-list').textContent,/<script>/);assert.equal(h.w.compromised,undefined);
  }finally{await h.close()}
});
test('dashboard navigation, stored history and print preserve the setup draft',async()=>{
  const h=setup();try{
    const state={onboarding:{draft:{goal:'keep my draft'},snapshot:null,model:{provider:'codex',configured:true,codex:{version:'test'}},job:null,latest:fixture.weekly,history:[{id:fixture.initial.id,as_of:'2026-11-14',action:'hold'}],capital_limit:30000000},latest:fixture.weekly,broker_check:{},broker_connected:true};
    h.w.fetch=async path=>({ok:true,json:async()=>structuredClone(path==='/api/state'?state:fixture.initial)});
    h.w.eval(dashboard);await tick();await tick();
    assert.equal(h.$('report-panel').hidden,true);assert.equal(h.$('setup-form').hidden,false);assert.match(h.$('generate').textContent,/평가·제안/);
    h.$('tab-setup').click();assert.equal(h.$('setup-form').hidden,false);
    h.$('setup-form').elements.namedItem('goal').value='draft changed';h.$('tab-report').click();
    assert.equal(h.$('setup-form').elements.namedItem('goal').value,'draft changed');assert.equal(h.$('tab-report').getAttribute('aria-pressed'),'true');
    h.$('historylist').querySelector('button').click();await tick();await tick();assert.match(h.$('report-kind').textContent,/최초/);
    const closed=Array.from(h.$('report-content').querySelectorAll('details:not([open])'));assert.ok(closed.length);
    h.w.dispatchEvent(new h.w.Event('beforeprint'));assert.ok(closed.every(x=>x.open));
    h.w.dispatchEvent(new h.w.Event('afterprint'));assert.ok(closed.every(x=>!x.open));
  }finally{await h.close()}
});
test('printable structured claims quality gates and historical units remain visible',async()=>{
  const h=setup();try{
    const r=structuredClone(fixture.weekly);delete r.view.final_report; // Legacy body-only fixture.
    r.body.proposal.investment_case={key_points:['Synthetic decision summary'],alternatives:[{name:'Alternative A',decision:'rejected',weights:{CASH:1},reason:'Synthetic reason',change_condition:'Synthetic boundary'}],claims:[{statement:'Synthetic claim',status:'conditional',assumptions:['Synthetic assumption'],counterevidence:'Synthetic countercase',decision_impact:'Synthetic impact',fact_ids:[r.view.sources[0].id]}]};
    r.view.quality_evaluation={score:{strict_pass:false,total:50,gates:{G3:'fail'}},rubric:{version:'2.0.0'},output:{summary:'Synthetic independent failure'}};
    r.body.analysis={comparison:{available:true,start:'2020-01-31',end:'2022-12-31',observations:36,amount_unit:'Normalized USD only',cash_proxy_warning:'USD proxy, not KRW account',results:{fixture:{annualized_return:.02,annualized_volatility:.1,month_end_max_drawdown:.3,contributed:100,ending_wealth:110,profit:10}},limitations:['Synthetic history, not prediction']}};
    h.render(r);const t=h.$('structured-report').textContent;
    assert.match(t,/Synthetic decision summary/);assert.match(t,/Synthetic countercase/);assert.match(t,/채택하지 않음/);assert.match(t,/기준통화 현금 100.0%/);assert.match(t,/주장 상태: 조건부/);assert.match(t,/Synthetic assumption/);assert.match(t,/엄격 기준 미충족/);assert.match(t,/G3 · 실패/);assert.match(t,/USD proxy, not KRW account/);assert.match(t,/월말 최대 낙폭 30.0%/);
    delete r.view.quality_evaluation.score.strict_pass;r.view.quality_evaluation.rubric.version='1.0.0';h.render(r);assert.match(h.$('structured-report').textContent,/엄격 기준 미평가/);assert.doesNotMatch(h.$('structured-report').textContent,/엄격 기준 미충족/);h.render(fixture.initial);assert.doesNotMatch(h.$('structured-report').textContent,/Synthetic claim/);
  }finally{await h.close()}
});
test('all full reports print the four sections and preserve stage and final status',async()=>{const h=setup();try{const r=structuredClone(fixture.weekly),report={title:'Full expert report',as_of:r.body.as_of,portfolio_context:'Actual portfolio context',market_context:'Market basis',decision_method:'Public criteria and alternatives',conclusion:'Stage opinion',evidence_ids:[]};r.body.proposal.action='defer';delete r.view.judgment_report_history;r.view.judgment_reports=[{role:'validation',stage:'perspective_validation',report},{role:'validation',stage:'final_validation',report:{...report,title:'Final validation report'}}];const before=JSON.stringify(r);h.render(r);const reports=h.$('structured-report').querySelectorAll('.judgment-report');assert.equal(reports.length,2);for(const article of reports){assert.equal(article.querySelectorAll('section').length,4);assert.match(article.textContent,/공식 최종 상태: 보류/)}assert.equal(JSON.stringify(r),before);h.render(fixture.initial);assert.equal(h.$('structured-report').querySelectorAll('.judgment-report').length,0)}finally{await h.close()}});
for(const {name,run} of cases){await run();console.log('PASS '+name)}
console.log(cases.length+' report rendering tests passed');
