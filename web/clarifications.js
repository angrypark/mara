/* Explicit clarification answers. Polling never replaces an active question editor. */
'use strict';
window.MaraClarifications=(()=>{
  const $=id=>document.getElementById(id),el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n};
  let config,job=null,answers=[],history=[],index=0,signature='',memorySignature='',saving=false,resuming=false,editing=null,recheck=false;
  const drafts=new Map();
  const source=()=>editing?.source_output_id||job?.context_output_id;
  const qs=()=>editing?[editing.question]:(job?.structured_questions||[]);
  const key=q=>source()+'/'+q.id;
  const known=q=>answers.find(a=>a.question_id===q.id);
  function draft(q){if(!drafts.has(key(q))){const previous=known(q),a=previous?.source_output_id===source()?previous:null;drafts.set(key(q),{question_id:q.id,option_id:a?.option_id??null,text:a?.text||'',expected_answer_id:previous?.answer_id??null})}return drafts.get(key(q))}
  function remember(){const q=qs()[index];if(!q)return;const d=draft(q),field=$('context-answer');if(field)d.text=field.value;const chosen=$('context-card').querySelector('input:checked');d.option_id=chosen?.value||null}
  function status(text,error=false){$('context-feedback').textContent=text;$('context-feedback').dataset.kind=error?'error':'info'}
  function controls(){const locked=saving||resuming;for(const control of $('context-card').querySelectorAll('input,textarea,button'))control.disabled=locked;for(const control of $('context-memory-list').querySelectorAll('button'))control.disabled=locked||job?.status==='running';const q=qs()[index];$('context-recheck').hidden=!!editing||(!answers.length&&!history.length);$('context-recheck').disabled=locked;$('context-back').hidden=!!editing||index===0;$('context-back').disabled=locked;$('context-next').disabled=locked||!q;$('context-next').textContent=resuming?'분석 재개 중…':saving?'답변 저장 중…':editing?'수정한 답변 저장':index===qs().length-1?'답변 저장하고 분석 계속':'답변 저장하고 다음'}
  function render(focus=false){
    const q=qs()[index];$('context-requests').hidden=!q;$('generation-actions').hidden=!!q;
    if(!q)return;const d=draft(q),root=$('context-card');root.replaceChildren();
    $('context-progress').textContent=editing?'답변 수정':`${index+1} / ${qs().length}`;
    const title=el('h4','context-question',q.prompt);title.id='context-question-title';title.tabIndex=-1;root.append(title,el('p','hint',q.reason));
    if(q.revisit_reason)root.append(el('p','context-revisit','다시 확인하는 이유: '+q.revisit_reason));
    const prior=known(q);if(prior)root.append(el('p','context-previous','저장된 답변: '+prior.answer));
    const fieldset=el('fieldset','context-options');const legend=el('legend','sr-only','답변 선택');fieldset.append(legend);
    for(const o of q.options||[]){const label=el('label','context-option'),input=el('input');input.type='radio';input.name='context-choice';input.value=o.id;input.checked=d.option_id===o.id;input.dataset.contextControl='true';const copy=el('span');copy.append(el('strong','',o.label));if(o.description)copy.append(el('small','',o.description));label.append(input,copy);input.onchange=()=>{d.option_id=o.id;status('선택했어요. 저장 버튼을 누르면 다음 분석에 반영돼요.');hint()};fieldset.append(label)}
    const custom=el('label','context-option'),radio=el('input');radio.type='radio';radio.name='context-choice';radio.value='';radio.checked=d.option_id===null&&!!d.text;radio.dataset.contextControl='true';custom.append(radio,el('span','','직접 답변할게요'));radio.onchange=()=>{d.option_id=null;hint();$('context-answer').focus({preventScroll:true})};fieldset.append(custom);root.append(fieldset);
    const label=el('label','context-answer-label','답변 또는 덧붙일 내용'),textarea=el('textarea');textarea.id='context-answer';textarea.maxLength=1200;textarea.rows=3;textarea.value=d.text;textarea.placeholder='날짜·금액 등 필요한 내용을 적거나 선택지에 설명을 덧붙여주세요.';textarea.setAttribute('aria-describedby','context-answer-hint');textarea.oninput=()=>{d.text=textarea.value};label.append(textarea);root.append(label,el('p','hint',''));root.lastChild.id='context-answer-hint';hint();controls();status('');
    if(editing){const cancel=el('button','rowbutton','수정 취소');cancel.type='button';cancel.disabled=saving||resuming;cancel.onclick=()=>{if(saving||resuming)return;editing=null;index=0;render()};root.append(cancel)}
    if(focus)title.focus({preventScroll:true});
  }
  function hint(){const q=qs()[index],d=draft(q),o=q.options.find(o=>o.id===d.option_id);$('context-answer-hint').textContent=o?.requires_text?'이 선택은 구체적인 설명도 필요해요.':d.option_id?'선택만 저장하거나 설명을 덧붙일 수 있어요.':'직접 답변은 위 입력란에 적어주세요.'}
  async function save(){
    remember();const q=qs()[index],d=draft(q),o=q.options.find(o=>o.id===d.option_id);
    if((!o||o.requires_text)&&!d.text.trim()){status('이 질문에 답하거나 선택한 내용의 구체적인 설명을 적어주세요.',true);$('context-answer').focus({preventScroll:true});return false}
    const a=known(q);if(a?.source_output_id===source()&&a.option_id===d.option_id&&a.text===d.text.trim())return true;
    const payload={context_output_id:source(),request_id:crypto.randomUUID(),answers:[{question_id:d.question_id,option_id:d.option_id,text:d.text,expected_answer_id:d.expected_answer_id}]};
    // Reuse one request ID if a network error leaves the outcome unknown.
    const serialized=JSON.stringify(payload.answers);if(d._retry?.serialized===serialized)payload.request_id=d._retry.id;
    d._retry={id:payload.request_id,serialized};saving=true;controls();
    try{const result=await config.api('/api/setup/answers',payload);answers=result.answers;const current=known(q);d.expected_answer_id=current.answer_id;delete d._retry;memory();status('답변을 저장했어요.');return true}
    catch(e){status(e.message,true);return false}finally{saving=false;controls()}
  }
  function resume(){resuming=true;controls();config.submit()}
  async function next(){if(saving||resuming)return;if(!await save())return;if(editing){editing=null;index=0;render();status('답변을 수정했어요. 다음 분석부터 반영돼요.');return}if(index<qs().length-1){index++;render(true)}else resume()}
  function complete(){if(!job||job.status!=='needs_input')return true;return qs().every(q=>answers.some(a=>a.question_id===q.id&&a.source_output_id===source()))}
  function memory(){
    const sig=JSON.stringify([answers,history,job?.status]);if(sig===memorySignature)return;memorySignature=sig;
    $('context-memory').hidden=!answers.length&&!history.length;$('context-memory-title').textContent=`기억하고 있는 답변 ${answers.length}개 · 추가 설명 ${history.length}개`;
    const root=$('context-memory-list');root.replaceChildren();
    for(const a of answers){const box=el('div','context-memory-item');box.append(el('strong','',a.question.prompt),el('p','',a.answer));const edit=el('button','rowbutton','답변 수정');edit.type='button';edit.disabled=saving||resuming||job?.status==='running';edit.onclick=()=>{if(saving||resuming)return;remember();editing=a;index=0;drafts.delete(key(a.question));render(true)};box.append(edit);root.append(box)}
    for(const n of history){const box=el('div','context-memory-item');box.append(el('small','hint',n.recorded_at.slice(0,10)+' 추가 설명'),el('p','',n.text));root.append(box)}
  }
  function update(nextJob,nextAnswers=[],notes=[]){
    answers=[...nextAnswers];history=notes;const sig=JSON.stringify([nextJob?.id,nextJob?.status,nextJob?.context_output_id,nextJob?.structured_questions]);
    const changed=sig!==signature;if(changed){remember();signature=sig;job=nextJob;editing=null;index=0;
      if(job?.status==='needs_input'){const unanswered=qs().findIndex(q=>!answers.some(a=>a.question_id===q.id&&a.source_output_id===source()));index=Math.max(0,unanswered)}
      render(false)
    }else job=nextJob;
    memory();controls();
  }
  function init(options){config=options;$('context-recheck').onclick=()=>{if(saving||resuming)return;remember();recheck=true;resume()};$('context-next').onclick=next;$('context-back').onclick=()=>{if(saving||resuming)return;remember();index=Math.max(0,index-1);render(true)}}
  function beforeGenerate(){if(recheck){recheck=false;return true}if(complete())return true;status('확인 질문에 답변을 저장한 뒤 분석을 계속해주세요.',true);return false}
  function resumeFinished(){resuming=false;controls()}
  return {init,update,beforeGenerate,resumeFinished};
})();
