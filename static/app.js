'use strict';
const app=document.querySelector('#app');
let knowledge, category=null, answers={}, state=null, busy=false;
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body){
  const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Не удалось выполнить запрос');
  return data;
}
function error(message){const box=document.querySelector('#error');box.textContent=message;box.hidden=false;}
function clearError(){document.querySelector('#error').hidden=true;}
function focusHeading(){const h=app.querySelector('h1');if(h){h.tabIndex=-1;h.focus({preventScroll:true});}}
function home(){
  category=null;answers={};state=null;clearError();
  app.innerHTML=`<p class="eyebrow">Проверка автомобиля</p><h1>Что происходит<br>с вашим автомобилем?</h1><p class="intro">Выберите основную проблему. Ответьте на несколько вопросов — система сопоставит признаки с правилами и назовёт возможные причины.</p><div class="category-list">${knowledge.categories.map((c,i)=>`<button class="category" data-category="${esc(c.id)}"><span class="number">${String(i+1).padStart(2,'0')}</span><span><strong>${esc(c.title)}</strong><small>${esc(c.description)}</small></span><span class="arrow" aria-hidden="true">→</span></button>`).join('')}</div><p class="scope">Используйте уже известные наблюдения. Если признак незнаком, отвечайте «Не знаю». Результат помогает сузить поиск причины и требует подтверждения диагностикой.</p>`;
  app.querySelectorAll('[data-category]').forEach(button=>button.addEventListener('click',()=>start(button.dataset.category)));
}
async function start(id){if(busy)return;category=id;answers={};await refresh();}
async function refresh(){
  if(busy)return;busy=true;app.classList.add('busy');clearError();
  try{state=await api('/api/consult',{category,answers});render();focusHeading();}
  catch(e){error(e.message);}finally{busy=false;app.classList.remove('busy');}
}
async function answer(value){
  if(busy||!state.question)return;
  const previous={...answers};answers[state.question.id]=value;
  busy=true;app.classList.add('busy');clearError();
  try{state=await api('/api/consult',{category,answers});render();focusHeading();}
  catch(e){answers=previous;error(e.message);}finally{busy=false;app.classList.remove('busy');}
}
async function back(){if(busy)return;const keys=Object.keys(answers);if(!keys.length){home();return;}delete answers[keys[keys.length-1]];await refresh();}
function history(){return `<aside class="history"><h2>Ваши ответы</h2>${state.history.length?`<ol>${state.history.map(h=>`<li>${esc(h.question)}<strong>${esc(h.answer)}</strong></li>`).join('')}</ol>`:'<p class="history-empty">Ответы появятся здесь. К предыдущему вопросу можно вернуться.</p>'}</aside>`;}
function render(){
  if(state.status==='question'){
    const q=state.question;
    app.innerHTML=`<div class="consult-layout"><section class="question-panel"><p class="eyebrow">${esc(state.category.title)}</p><p class="question-meta">Вопрос ${state.history.length+1}</p><h1>${esc(q.text)}</h1><p class="hint">${esc(q.hint)}</p><div class="answers">${q.options.map((o,i)=>`<button class="answer" data-option="${i}">${esc(o.label)}</button>`).join('')}<button class="answer unknown" id="unknown">Не знаю</button></div><div class="back-row"><button class="text-button" id="back">← Назад</button><button class="text-button" id="restart">Другая проблема</button></div></section>${history()}</div>`;
    app.querySelectorAll('[data-option]').forEach(b=>b.addEventListener('click',()=>answer(q.options[Number(b.dataset.option)].value)));
    document.querySelector('#unknown').addEventListener('click',()=>answer(null));
  }else{
    const matched=state.results.length>0;
    app.innerHTML=`<div class="consult-layout"><section class="question-panel"><p class="eyebrow">${esc(state.category.title)} · Результат</p><h1>${matched?'Возможные причины':state.status==='insufficient'?'Нужны дополнительные сведения':'Причина не определена'}</h1>${matched?state.results.map(r=>`<article class="result"><h3>${esc(r.text)}</h3><p class="component">${r.kind==='normal_variant'?'Возможное обычное явление':'Узел или система'}: ${esc(r.component)}</p><details><summary>Почему получен этот вывод · правило №${r.rule_id}</summary><ul class="evidence">${r.evidence.map(e=>`<li>${esc(e.question)} <strong>${esc(e.answer)}</strong></li>`).join('')}</ul><p class="rule-text">${esc(r.rule_text)}</p></details></article>`).join(''):`<div class="empty-state"><p>${esc(state.message)}</p><p class="hint">${state.status==='insufficient'?'Часть признаков осталась неизвестной. Можно вернуться и уточнить ответы.':'Выбранное сочетание признаков не описано в базе знаний. Это не означает, что автомобиль исправен.'}</p></div>`}<p class="result-note">${matched?'Это предварительные гипотезы по вашим ответам. Они не подтверждают неисправность конкретной детали.':''}${state.pending_rule_ids.length&&matched?' Для части других правил не хватило данных.':''}</p><div class="actions"><button class="primary" id="restart">Новая проверка</button><button class="secondary" id="back">Изменить ответы</button><button class="secondary" id="download">Сохранить результат</button></div></section>${history()}</div>`;
    document.querySelector('#download').addEventListener('click',download);
  }
  document.querySelector('#back').addEventListener('click',back);
  document.querySelector('#restart').addEventListener('click',()=>{home();focusHeading();});
}
function download(){
  const lines=['Автодиагностика — результат проверки',state.category.title,'',...state.history.map(h=>`${h.question} ${h.answer}`),'',state.message,...state.results.map(r=>`Правило №${r.rule_id}: ${r.text}. Узел: ${r.component}.`),'','Предварительные гипотезы требуют подтверждения.'];
  const blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/plain;charset=utf-8'});
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='diagnosis.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function renderRules(){
  const query=document.querySelector('#rule-search').value.toLocaleLowerCase('ru');
  const found=knowledge.rules.filter(r=>r.text.toLocaleLowerCase('ru').includes(query));
  document.querySelector('#rule-list').innerHTML=found.length?found.map(r=>`<article class="rule"><small>№${r.id} · ${r.type==='routing'?'Переход по ветке':'Вывод'}</small>${esc(r.text)}</article>`).join(''):'<p>Правила не найдены.</p>';
}
document.querySelector('#knowledge-toggle').addEventListener('click',()=>{if(!knowledge)return;renderRules();document.querySelector('#knowledge-dialog').showModal();});
document.querySelector('#close-dialog').addEventListener('click',()=>document.querySelector('#knowledge-dialog').close());
document.querySelector('#rule-search').addEventListener('input',renderRules);
app.innerHTML='<p>Загрузка базы знаний…</p>';
api('/api/knowledge').then(data=>{knowledge=data;home();}).catch(e=>{app.innerHTML='<h1>Не удалось загрузить систему</h1><p>Проверьте, что Python-сервер запущен, и обновите страницу.</p>';error(e.message);});
