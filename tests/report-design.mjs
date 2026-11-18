import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {Window} from '../.local/test-ui/node_modules/happy-dom/lib/index.js';
const row=JSON.parse(execFileSync('python3',['tests/final_report_fixture.py'],{encoding:'utf8',env:{...process.env,PYTHONPATH:'.'}}));
const w=new Window({url:'http://127.0.0.1:8788',settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true}}),d=w.document;
const chapter=id=>d.querySelector(`[data-chapter="${id}"]`),visible=()=>[...d.querySelectorAll('.portfolio-section')].filter(x=>!x.hidden).map(x=>x.id);
try{
 d.write((await readFile('web/dashboard.html','utf8')).replace(/<script[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link[^>]*>/g,''));w.eval(await readFile('web/report.js','utf8'));
 const original=JSON.stringify(row);w.MaraReport.render(row);
 assert.equal(visible().length,4);assert.equal(d.querySelector('.reader-verdict p').textContent,row.view.final_report.decision.rationale);
 chapter('portfolio-adjustment').click();assert.deepEqual(visible(),['portfolio-adjustment']);
 chapter('portfolio-adjustment').focus();w.MaraReport.render(row);assert.equal(d.activeElement,chapter('portfolio-adjustment'));
 const asset=d.querySelector('.allocation-legend-title');const symbol=asset.closest('[data-symbol]').dataset.symbol;asset.click();asset.focus();
 assert.equal(asset.getAttribute('aria-pressed'),'true');assert.ok(d.querySelectorAll('.allocation-segment.allocation-dimmed').length>0);
 const before=[...d.querySelectorAll('.allocation-segment')].map(x=>[x.dataset.symbol,x.dataset.weight,x.style.width]);
 w.MaraReport.render(row);assert.deepEqual(visible(),['portfolio-adjustment']);assert.equal(d.querySelector('.allocation-visual').dataset.selectedAsset,symbol);assert.equal(d.activeElement.closest('[data-symbol]').dataset.symbol,symbol);
 assert.deepEqual([...d.querySelectorAll('.allocation-segment')].map(x=>[x.dataset.symbol,x.dataset.weight,x.style.width]),before);
 d.querySelector('.allocation-legend-title[aria-pressed=true]').click();assert.equal(d.querySelectorAll('.allocation-dimmed').length,0);
 const claim=d.querySelector('.reader-claim-row');const link=d.createElement('a');link.href='#'+claim.id;d.body.append(link);link.click();
 assert.deepEqual(visible(),['portfolio-reasons']);assert.equal(claim.open,true);assert.equal(d.getElementById('portfolio-more-reasons').open,true);
 chapter('all').click();assert.equal(visible().length,4);
 chapter('portfolio-market').click();w.location.hash='#portfolio-current';w.dispatchEvent(new w.HashChangeEvent('hashchange'));assert.deepEqual(visible(),['portfolio-current']);
 w.location.hash='';const another=structuredClone(row);another.id+='-next';w.MaraReport.render(another);assert.equal(visible().length,4);assert.equal(d.querySelector('.allocation-visual').dataset.selectedAsset,'');
 assert.equal(JSON.stringify(row),original);console.log('PASS report design: chapter selection, direct anchors, nested evidence, poll state, asset emphasis, unchanged weights, report reset and input immutability');
}finally{await w.happyDOM.close()}
