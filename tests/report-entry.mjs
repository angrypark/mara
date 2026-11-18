// Integrated navigation with synthetic completed and in-progress runs only.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {Window} from '../.local/test-ui/node_modules/happy-dom/lib/index.js';
const fixture=name=>JSON.parse(execFileSync('python3',['tests/'+name],{encoding:'utf8',maxBuffer:16*1024*1024,env:{...process.env,PYTHONPATH:'.'}}));
const report=fixture('final_report_fixture.py'), wb=fixture('workbench_fixture.py');
const html=await readFile('web/dashboard.html','utf8');
const scripts=await Promise.all(['report','workbench','dashboard'].map(n=>readFile('web/'+n+'.js','utf8')));
report.body.mode='portfolio';
const older=structuredClone(report);older.id='older-report';older.body.run_id='older-run';
const completed=structuredClone(wb.weekly);completed.run.id=report.body.run_id;completed.run.report_id=report.id;
const oldProcess=structuredClone(completed);oldProcess.run.id=older.body.run_id;oldProcess.run.report_id=older.id;
const pending=structuredClone(wb.partial);pending.run.id='pending-run';pending.run.report_id=null;
const state={broker_connected:true,broker_check:{},latest:null,onboarding:{capital_limit:0,model:{configured:true,model:'test-only'},snapshot:null,draft:{},latest:report,history:[{id:older.id,as_of:'2026-11-01',action:'defer'}],job:null}};
const docs=new Map([completed,oldProcess,pending].map(d=>[d.run.id,d]));
const w=new Window({url:'http://127.0.0.1:8790',settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true}});
const $=id=>w.document.getElementById(id);
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setTimeout(r,0))};
try{
 const scrolled=[];w.HTMLElement.prototype.scrollIntoView=function(){scrolled.push(this.id)};w.setInterval=()=>0;
 w.fetch=async path=>({ok:true,json:async()=>{
  if(path==='/api/state')return structuredClone(state);
  if(path==='/api/workbench/portfolio')return {runs:[...docs.values()].map(d=>d.run)};
  if(path.startsWith('/api/workbench/portfolio/'))return structuredClone(docs.get(path.split('/').at(-1)));
  if(path.startsWith('/api/portfolio/report/'))return structuredClone(path.endsWith(older.id)?older:report);
  if(path.startsWith('/api/dialogue/'))return {messages:[],pending:false};
  throw Error('Unexpected request '+path);
 }});
 w.document.write(html.replace(/<script[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link[^>]*>/g,''));
 scripts.forEach((script,i)=>w.eval(script+(i===2?'\nwindow.__poll=load;':'')));
 await settle();
 assert.equal($('report-panel').hidden,false);
 assert.equal($('report-document').tagName,'SECTION');
 assert.equal($('report-document').hidden,false);
 assert.equal($('analysis-process').open,false);
 assert.equal($('final-reader').closest('details'),null);
 assert.ok($('report-document').compareDocumentPosition($('analysis-process'))&w.Node.DOCUMENT_POSITION_FOLLOWING);

 $('analysis-process').open=true;$('wb-run').value=pending.run.id;
 $('wb-run').dispatchEvent(new w.Event('change'));await settle();
 assert.equal($('report-document').hidden,true);assert.equal($('analysis-process').open,true);
 await w.__poll();await settle();
 assert.equal($('wb-run').value,pending.run.id);assert.equal($('report-document').hidden,true);

 $('historylist').querySelector('button').click();await settle();
 assert.equal($('report-document').dataset.reportId,older.id);
 assert.equal(w.document.activeElement.id,'report-title');assert.equal(scrolled.at(-1),'report-title');
 const scrollCount=scrolled.length;
 assert.equal($('report-document').hidden,false);assert.equal($('analysis-process').open,false);
 await w.__poll();await settle();
 assert.equal($('report-document').dataset.reportId,older.id);
 assert.equal($('wb-run').value,older.body.run_id);assert.equal(scrolled.length,scrollCount);

 $('tab-setup').click();assert.equal($('report-panel').hidden,true);
 w.location.hash='#workbench';w.dispatchEvent(new w.HashChangeEvent('hashchange'));await settle();
 assert.equal($('report-panel').hidden,false);assert.equal($('analysis-process').open,true);
 assert.equal($('report-document').dataset.reportId,older.id);
 $('analysis-process').open=false;
 $('report-toc').querySelector('a[href="#workbench"]').click();await settle();
 assert.equal($('analysis-process').open,true);
 console.log('PASS report entry: completed first; running state separate; selected history pinned; process anchor opens');
}finally{await w.happyDOM.close()}
