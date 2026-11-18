import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {Window} from '../.local/test-ui/node_modules/happy-dom/lib/index.js';
const fixture=JSON.parse(execFileSync('python3',['tests/final_report_fixture.py'],{encoding:'utf8',env:{...process.env,PYTHONPATH:'.'}}));
const w=new Window({url:'http://127.0.0.1:8788',settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true}});
const base=()=>{const r=structuredClone(fixture);r.body.valuation={nav:1000,values:{OLD:600,CASH:400,ZERO:0},weights:{OLD:.6,CASH:.4}};r.body.funding={source:'reported_holdings',amount_outside_proposal:0};Object.assign(r.view.final_report.allocation,{proposal_capital:1200,weights:{NEW:.5,CASH:.5}});return r};
const chart=()=>w.document.querySelector('#portfolio-allocation-comparison');
const series=key=>chart().querySelector(`[data-series="${key}"]`);
const segments=key=>Object.fromEntries([...series(key).querySelectorAll('.allocation-segment')].map(n=>[n.dataset.symbol,Number(n.dataset.weight)]));
const legend=s=>chart().querySelector(`.allocation-legend-item[data-symbol="${s}"]`);
try{
 w.document.write((await readFile('web/dashboard.html','utf8')).replace(/<script[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link[^>]*>/g,''));w.eval(await readFile('web/report.js','utf8'));
 const r=base(),before=JSON.stringify(r);w.MaraReport.render(r);assert.equal(JSON.stringify(r),before);
 assert.deepEqual(segments('current'),{OLD:.6,CASH:.4});assert.deepEqual(segments('after'),{CASH:.5,NEW:.5});
 assert.match(legend('OLD').textContent,/60.0% → 0.0%.*-60.0%p.*목표에서 제외/);
 assert.match(legend('NEW').textContent,/0.0% → 50.0%.*\+50.0%p/);assert.ok(legend('ZERO'));
 assert.match(series('current').querySelector('[role=img]').getAttribute('aria-label'),/OLD 60.0%.*600/);
 assert.equal(series('current').querySelector('[data-symbol=CASH]').style.backgroundColor,series('after').querySelector('[data-symbol=CASH]').style.backgroundColor);
 const future=base();future.body.funding.source='future_income';future.body.funding.amount_outside_proposal=1000;w.MaraReport.render(future);
 assert.ok(Math.abs(segments('after').OLD-600/2200)<1e-12);assert.ok(Math.abs(segments('after').CASH-1000/2200)<1e-12);
 assert.deepEqual(segments('contribution'),{CASH:.5,NEW:.5});assert.match(legend('OLD').textContent,/기존 보유 유지 · 신규 납입 없음/);
 assert.match(series('after').textContent,/납입 후 전체/);assert.match(legend('CASH').textContent,/45.5%/);
 const partial=base();partial.view.final_report.allocation.proposal_capital=500;partial.body.funding.amount_outside_proposal=500;w.MaraReport.render(partial);
 assert.match(series('after').textContent,/이번 제안 범위/);assert.equal(chart().querySelector('.allocation-weight-change'),null);assert.match(chart().textContent,/전체 조정 후 비중은 계산하지 않았어요/);
 const empty=base();empty.body.valuation={nav:0,values:{CASH:0},weights:{}};w.MaraReport.render(empty);assert.deepEqual(segments('current'),{});assert.match(series('current').textContent,/현재 보유 자산이 없어요/);assert.deepEqual(segments('after'),{CASH:.5,NEW:.5});
 empty.view.final_report.allocation.proposal_capital=0;w.MaraReport.render(empty);assert.deepEqual(segments('after'),{});assert.match(series('after').textContent,/배분할 금액이 없어요/);
 const missing=base();missing.body.valuation={nav:null,values:{},weights:{}};w.MaraReport.render(missing);assert.match(series('current').textContent,/자료를 확인/);assert.equal(series('current').querySelector('.allocation-stack'),null);
 const mismatch=base();mismatch.body.valuation.values.OLD=500;w.MaraReport.render(mismatch);assert.equal(series('current').querySelector('.allocation-stack'),null);
 for(const weights of [{NEW:.4,CASH:.4},{NEW:-.1,CASH:1.1},{NEW:null,CASH:1}]){const bad=base();bad.view.final_report.allocation.weights=weights;w.MaraReport.render(bad);assert.equal(series('after').querySelector('.allocation-stack'),null);assert.match(series('after').textContent,/자료/)}
 const many=base();many.body.valuation={nav:1000,values:Object.fromEntries(Array.from({length:15},(_,i)=>['ASSET'+i,1000/15])),weights:{}};w.MaraReport.render(many);assert.equal(series('current').querySelectorAll('.allocation-segment').length,15);assert.equal(chart().querySelectorAll('.allocation-legend-item').length,17);
 console.log('PASS allocation chart: portfolio vs contribution denominators, scope, omitted assets, zero/missing/invalid amounts, many assets, accessible labels and immutability');
}finally{await w.happyDOM.close()}
