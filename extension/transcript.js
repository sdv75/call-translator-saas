'use strict';
const el=id=>document.getElementById(id);
let sessions=[],entries=[];
async function request(type,extra={}) {
  const response=await chrome.runtime.sendMessage({type,...extra});
  if(!response?.ok) throw Error(response?.error || 'Не удалось прочитать стенограмму.');
  return response.result;
}
async function show() {
  el('export').disabled=true;el('entries').replaceChildren();
  if(!el('session').value) return;
  entries=await request('journal-entries',{session:el('session').value});
  for(const entry of entries) {
    const article=document.createElement('article'),heading=document.createElement('h2'),original=document.createElement('p'),translated=document.createElement('p');
    heading.textContent=(entry.direction==='incoming'?'Собеседники':'Я')+(entry.uncertain?' · неуверенное распознавание':'');
    original.textContent=entry.original;translated.textContent=entry.text || 'Перевод не получен';
    article.append(heading,original,translated);el('entries').append(article);
  }
  el('export').disabled=false;
}
el('session').addEventListener('change',()=>show().catch(error=>{el('status').textContent=error.message;}));
el('export').addEventListener('click',async()=>{
  const session=sessions.find(item=>item.id===el('session').value);
  if(!session) return;
  el('export').disabled=true;
  try{await request('journal-save',{session:session.id});el('status').textContent='Стенограмма сохранена в выбранной папке.';}
  catch(error){el('status').textContent=error.message;}
  finally{el('export').disabled=false;}
});
async function folder(){
  const value=await request('transcript-destination');
  el('folder-name').textContent=value.name;
  el('folder-status').textContent=value.requiresFolderChoice?'Подтвердите прежнюю папку кнопкой «Выбрать папку».':'Автоматическое сохранение после разговора включено.';
}
function action(button,work){el(button).addEventListener('click',async()=>{
  try{await work();await folder();el('folder-status').textContent='Папка сохранена. Следующие стенограммы будут записываться сюда.';}
  catch(error){if(error.name!=='AbortError')el('folder-status').textContent=error.message;}
});}
action('choose-folder',()=>request('transcript-folder-choose'));
action('default-folder',()=>request('transcript-folder-default'));

(async()=>{
  try{
    await folder();
    const saved=(await chrome.storage.local.get('transcriptFileStatus')).transcriptFileStatus;
    if(saved?.ok===false)el('status').textContent=saved.text;
    sessions=await request('journal-sessions');
    if(!sessions.length) el('status').textContent='Сохранённых разговоров пока нет.';
    for(const session of sessions){const option=document.createElement('option');option.value=session.id;option.textContent=`${new Date(session.started_at).toLocaleString()} · ${session.source} → ${session.target}`;el('session').append(option);}
    await show();
  }catch(error){el('status').textContent=error.message;}
})();
