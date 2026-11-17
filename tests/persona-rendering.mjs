// Synthetic persona UI contract and retry behavior; no service or personal data.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {Window} from '../.local/test-ui/node_modules/happy-dom/lib/index.js';
const html=await readFile('web/dashboard.html','utf8'),script=await readFile('web/persona.js','utf8');
const w=new Window({url:'http://127.0.0.1:8788',settings:{disableJavaScriptFileLoading:true,disableCSSFileLoading:true}});
w.document.write(html.replace(/<script[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link[^>]*>/g,''));
w.eval(script);const $=id=>w.document.getElementById(id),calls=[];
let state={persona:{id:'persona-1',body:{version:1,status:'current',profile_id:'profile-1',title:'Synthetic',summary:'Test goal',facts:[{id:'monthly_income',label:'월 소득',value:100,unit:'KRW/month',status:'recorded'}],preferences:{},risk:{confirmed_loss_capacity_fraction:null,reference_loss_fraction:.2},unknowns:[],answer_memory:[],handoff_policy:'Frozen version'}},turns:[],running:false};
let failSend=true,failAnalyze=true;
const api=async(path,body)=>{if(!body)return structuredClone(state);calls.push({path,body:structuredClone(body)});if(path.endsWith('messages')&&failSend){failSend=false;throw Error('Synthetic network loss')}if(path.endsWith('analyze')&&failAnalyze){failAnalyze=false;throw Error('Synthetic network loss')}return {job_id:'j'}};
w.MaraPersona.init({api,needsInput:()=>false,analysisStarted:()=>{}});
await w.MaraPersona.refresh();assert.match($('persona-facts').textContent,/기존 기록/);assert.match($('persona-facts').textContent,/감내손실 미확인/);
assert.equal($('advanced-settings').open,false);assert.equal(w.document.querySelectorAll('#context-requests').length,1);
$('persona-message').value='Synthetic interest';await $('persona-send').onclick();assert.equal($('persona-message').value,'Synthetic interest');await $('persona-send').onclick();assert.equal($('persona-message').value,'');assert.equal(calls[0].body.request_id,calls[1].body.request_id);
state.turns=[{message:'hello',result:{reply:'reply',updates:[],issues:[],question:{prompt:'One question',options:[{label:'Example',message:'Suggested answer'}]}}}];
$('persona-message').value='Unsaved draft';await w.MaraPersona.refresh();assert.equal($('persona-message').value,'Unsaved draft');const before=calls.length;$('persona-question').querySelector('button').click();assert.equal($('persona-message').value,'Suggested answer');assert.equal(calls.length,before);
await w.MaraPersona.analyze();await w.MaraPersona.analyze();assert.equal(calls.at(-1).body.request_id,calls.at(-2).body.request_id);assert.equal(calls.at(-1).body.persona_id,'persona-1');
console.log('persona UI: render, single question, draft preservation, option no-auto-send, message and analysis retry IDs passed');await w.happyDOM.close();
