'use strict';
const app=document.querySelector('#app');
let knowledge, category=null, answers={}, state=null, busy=false;
let graphZoom=1;
let zoomWheelDelta=0;
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body,method='POST'){
  const response=await fetch(path,body?{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Не удалось выполнить запрос');
  return data;
}
function error(message){const box=document.querySelector('#error');box.textContent=message;box.hidden=false;}
function clearError(){document.querySelector('#error').hidden=true;}
function focusHeading(){const h=app.querySelector('h1');if(h){h.tabIndex=-1;h.focus({preventScroll:true});}}
function home(){
  category=null;answers={};state=null;clearError();
  app.innerHTML=`<p class="eyebrow">Проверка автомобиля</p><h1>Что происходит<br>с вашим автомобилем?</h1><p class="intro">Выберите основную проблему. Ответьте на несколько вопросов — система сопоставит признаки с правилами и назовёт возможные причины.</p><div class="category-list">${knowledge.categories.map((c,i)=>`<button class="category" data-category="${esc(c.id)}"><span class="number">${String(i+1).padStart(2,'0')}</span><span><strong>${esc(c.title)}</strong><small>${esc(c.description)}</small></span></button>`).join('')}</div>`;
  app.querySelectorAll('[data-category]').forEach(button=>button.addEventListener('click',()=>start(button.dataset.category)));
  app.scrollTop=0;
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
    app.innerHTML=`<div class="consult-layout"><section class="question-panel"><p class="eyebrow">${esc(state.category.title)}</p><p class="question-meta">Вопрос ${state.history.length+1}</p><h1>${esc(q.text)}</h1><p class="hint">${esc(q.hint)}</p><div class="answers">${q.options.map((o,i)=>`<button class="answer" data-option="${i}">${esc(o.label)}</button>`).join('')}<button class="answer unknown" id="unknown">Не знаю</button></div><div class="back-row"><button class="text-button" id="back">Назад</button><button class="text-button" id="restart">Другая проблема</button></div></section>${history()}</div>`;
    app.querySelectorAll('[data-option]').forEach(b=>b.addEventListener('click',()=>answer(q.options[Number(b.dataset.option)].value)));
    document.querySelector('#unknown').addEventListener('click',()=>answer(null));
  }else{
    const matched=state.results.length>0;
    app.innerHTML=`<div class="consult-layout"><section class="question-panel"><p class="eyebrow">${esc(state.category.title)} · Результат</p><h1>${matched?'Возможные причины':state.status==='insufficient'?'Нужны дополнительные сведения':'Причина не определена'}</h1>${matched?state.results.map(r=>`<article class="result"><h3>${esc(r.text)}</h3><p class="component">${r.kind==='normal_variant'?'Возможное обычное явление':'Узел или система'}: ${esc(r.component)}</p><details class="reasoning" open><summary>Как получен вывод</summary><ol class="reasoning-steps">${r.trace.map(step=>`<li class="reasoning-step"><span class="step-kind">${step.type==='complaint'?'Жалоба':step.type==='answer'?'Ответ':`Правило №${step.rule_id}`}</span><span>${esc(step.type==='answer'?`${step.question} — ${step.answer}`:step.text)}</span></li>`).join('')}</ol></details></article>`).join(''):`<div class="empty-state"><p>${esc(state.message)}</p><p class="hint">${state.status==='insufficient'?'Часть признаков осталась неизвестной. Можно вернуться и уточнить ответы.':'Выбранное сочетание признаков не описано в базе знаний. Это не означает, что автомобиль исправен.'}</p></div>`}<p class="result-note">${matched?'Это предварительные гипотезы по вашим ответам. Они не подтверждают неисправность конкретной детали.':''}${state.pending_rule_ids.length&&matched?' Для части других правил не хватило данных.':''}</p><div class="actions"><button class="primary" id="restart">Новая проверка</button><button class="secondary" id="back">Изменить ответы</button></div></section>${history()}</div>`;
  }
  document.querySelector('#back').addEventListener('click',back);
  document.querySelector('#restart').addEventListener('click',()=>{home();focusHeading();});
  app.scrollTop=0;
}
function conditionFields(condition){
  if(condition.field)return [condition.field];
  return (condition.all||condition.any||[]).flatMap(conditionFields);
}
function conditionText(condition,category,questions,producers){
  if(condition.all||condition.any){
    const key=condition.all?'all':'any';
    return (condition[key]||[]).map(c=>conditionText(c,category,questions,producers)).join(key==='all'?' И ':' ИЛИ ');
  }
  if(condition.field==='complaint')return `Жалоба: ${category.title}`;
  if(producers.has(condition.field))return `Правило №${producers.get(condition.field).id}`;
  const question=questions.get(condition.field);
  if(!question)return condition.field;
  const option=question.options.find(o=>o.value===condition.eq&&typeof o.value===typeof condition.eq);
  return `${question.text} — ${option?option.label:String(condition.eq)}`;
}
function renderRules(){
  const category=knowledge.categories.find(c=>c.id===document.querySelector('#graph-category').value);
  if(!category)return;
  const query=document.querySelector('#rule-search').value.trim().toLocaleLowerCase('ru');
  const questions=new Map(knowledge.questions.map(q=>[q.id,q]));
  const producers=new Map(knowledge.rules.filter(r=>r.then.fact).map(r=>[r.then.fact,r]));
  const rules=knowledge.rules.filter(r=>r.category===category.id);
  const byId=new Map(rules.map(r=>[r.id,r]));
  const parents=new Map(rules.map(r=>[r.id,[...new Set(conditionFields(r.if).map(field=>producers.get(field)?.id).filter(id=>byId.has(id)))]]));
  const levels=new Map();
  function level(rule){
    if(levels.has(rule.id))return levels.get(rule.id);
    const depth=1+Math.max(0,...parents.get(rule.id).map(id=>level(byId.get(id))));
    levels.set(rule.id,depth);
    return depth;
  }
  rules.forEach(level);
  const maxLevel=Math.max(...levels.values());
  const renderNode=rule=>{
    const terminal=rule.type==='terminal';
    const condition=conditionText(rule.if,category,questions,producers);
    const haystack=`${rule.id} ${rule.text} ${rule.then.conclusion||''} ${rule.then.component||''} ${condition}`.toLocaleLowerCase('ru');
    return `<article class="graph-node ${terminal?'terminal':'routing'} ${query&&!haystack.includes(query)?'dimmed':''}" data-node="${rule.id}" data-parents="${parents.get(rule.id).join(',')}"><div class="kb-node-top"><span class="kb-number">№${rule.id}</span><span class="kb-kind">${terminal?'Возможная причина':'Переход'}</span></div><strong>${esc(terminal?rule.then.conclusion:rule.text)}</strong>${terminal?`<small>${esc(rule.then.component)}</small>`:''}<p class="kb-condition">${esc(condition)}</p></article>`;
  };
  const columns=[`<div class="graph-column"><article class="graph-node root" data-node="root"><span class="kb-kind">Жалоба</span><strong>${esc(category.title)}</strong><small>${esc(category.description)}</small></article></div>`];
  for(let depth=1;depth<=maxLevel;depth++)columns.push(`<div class="graph-column">${rules.filter(r=>levels.get(r.id)===depth).map(renderNode).join('')}</div>`);
  document.querySelector('#rule-list').innerHTML=`<div class="graph-canvas" style="--graph-columns:${columns.length};zoom:${graphZoom}"><svg class="graph-edges" aria-hidden="true"></svg>${columns.join('')}</div>`;
  requestAnimationFrame(drawGraphEdges);
}
function drawGraphEdges(){
  const canvas=document.querySelector('.graph-canvas');
  if(!canvas)return;
  const svg=canvas.querySelector('.graph-edges');
  const bounds=canvas.getBoundingClientRect();
  const ratio=canvas.offsetWidth/bounds.width;
  svg.setAttribute('viewBox',`0 0 ${canvas.offsetWidth} ${canvas.offsetHeight}`);
  svg.replaceChildren();
  for(const node of canvas.querySelectorAll('[data-parents]')){
    const ids=node.dataset.parents?node.dataset.parents.split(','):['root'];
    const end=node.getBoundingClientRect();
    for(const id of ids){
      const parent=canvas.querySelector(`[data-node="${id}"]`);
      if(!parent)continue;
      const start=parent.getBoundingClientRect();
      const x1=(start.right-bounds.left)*ratio,y1=(start.top-bounds.top+start.height/2)*ratio;
      const x2=(end.left-bounds.left)*ratio,y2=(end.top-bounds.top+end.height/2)*ratio;
      const bend=Math.max(24,(x2-x1)/2);
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d',`M ${x1} ${y1} C ${x1+bend} ${y1}, ${x2-bend} ${y2}, ${x2} ${y2}`);
      svg.append(path);
    }
  }
}
function setGraphZoom(value){
  graphZoom=Math.max(.5,Math.min(2,Math.round(value*10)/10));
  document.querySelector('#zoom-value').value=`${Math.round(graphZoom*100)}%`;
  document.querySelector('#zoom-out').disabled=graphZoom<=.5;
  document.querySelector('#zoom-in').disabled=graphZoom>=2;
  const canvas=document.querySelector('.graph-canvas');
  if(canvas){canvas.style.zoom=graphZoom;requestAnimationFrame(drawGraphEdges);}
}
document.querySelector('#knowledge-toggle').addEventListener('click',()=>{
  if(!knowledge)return;
  const select=document.querySelector('#graph-category');
  select.innerHTML=knowledge.categories.map(c=>`<option value="${esc(c.id)}">${esc(c.title)}</option>`).join('');
  document.querySelector('#rule-search').value='';
  document.querySelector('#knowledge-dialog').showModal();
  setGraphZoom(graphZoom);
  renderRules();
});
document.querySelector('#close-dialog').addEventListener('click',()=>document.querySelector('#knowledge-dialog').close());
document.querySelector('#zoom-out').addEventListener('click',()=>setGraphZoom(graphZoom-.2));
document.querySelector('#zoom-in').addEventListener('click',()=>setGraphZoom(graphZoom+.2));
document.querySelector('#zoom-reset').addEventListener('click',()=>setGraphZoom(1));
document.querySelector('#rule-list').addEventListener('wheel',event=>{
  event.preventDefault();
  zoomWheelDelta+=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?400:1);
  if(Math.abs(zoomWheelDelta)<45)return;
  const viewport=event.currentTarget;
  const bounds=viewport.getBoundingClientRect();
  const x=event.clientX-bounds.left,y=event.clientY-bounds.top;
  const before=graphZoom;
  setGraphZoom(graphZoom+(zoomWheelDelta<0?.1:-.1));
  zoomWheelDelta=0;
  if(graphZoom===before)return;
  const factor=graphZoom/before;
  viewport.scrollLeft=(viewport.scrollLeft+x)*factor-x;
  viewport.scrollTop=(viewport.scrollTop+y)*factor-y;
},{passive:false});
document.querySelector('#graph-category').addEventListener('change',renderRules);
document.querySelector('#rule-search').addEventListener('input',renderRules);
window.addEventListener('resize',drawGraphEdges);
app.innerHTML='<p>Загрузка базы знаний…</p>';
api('/api/knowledge').then(data=>{knowledge=data;home();}).catch(e=>{app.innerHTML='<h1>Не удалось загрузить систему</h1><p>Проверьте, что Python-сервер запущен, и обновите страницу.</p>';error(e.message);});
