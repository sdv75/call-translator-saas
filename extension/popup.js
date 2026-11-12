'use strict';
const el=id=>document.getElementById(id);
el('open-account').href=CTService.url+'/account';
el('open-account-connected').href=CTService.url+'/account';
const status=text=>{el('status').textContent=text;};
let linked=false,componentAvailable=false,setupBusy=false,catalogLoaded=false,phase='stopped',previewAudio;
let voices=[],installed={voices:[],selected:{}},preferences={};
let genders={},legacyGenders={};
const source=()=>el('source-language').value.split(':')[0],target=()=>el('target-language').value.split(':')[0];
const callBusy=()=>['starting','active','stopping'].includes(phase);
function showView(name){
  for(const view of ['conversation','settings']){
    el(view+'-panel').hidden=view!==name;el('view-'+view).classList.toggle('selected',view===name);el('view-'+view).setAttribute('aria-selected',String(view===name));
  }
}
for(const view of ['conversation','settings'])el('view-'+view).addEventListener('click',()=>showView(view));
function syncSetup(){
  const busy=callBusy()||setupBusy;
  el('transcript-folder').disabled=busy;
  el('setup-state').hidden=callBusy();
  el('native-check').disabled=busy;
  el('catalog-refresh').disabled=busy||!linked||!componentAvailable;
  for(const id of ['source-language','target-language'])el(id).disabled=busy||!catalogLoaded;
  for(const button of document.querySelectorAll('[data-voice-action]'))button.disabled=busy||button.dataset.locked==='true';
  el('call-start').disabled=busy||!linked||!componentAvailable||!CTVoiceSetup.ready(voices,installed,source(),target(),genders);
  el('call-stop').disabled=!['starting','active'].includes(phase);
  el('catalog-help').textContent=!linked?'Сначала подключите аккаунт в разделе «Настройка».':!componentAvailable?
    'Сначала нажмите «Проверить компонент» в разделе «Программа озвучки».':'Эта кнопка загружает список голосов, которые можно установить.';
  el('setup-state').textContent=!linked?'Подключите аккаунт в разделе «Настройка».':!componentAvailable?'Проверьте программу озвучки в разделе «Программа озвучки».':
    !catalogLoaded?'Нажмите «Обновить каталог» в разделе «Языки разговора».':!CTVoiceSetup.pair(voices,source(),target())?'Выберите два разных доступных языка в разделе «Языки разговора».':
    !CTVoiceSetup.ready(voices,installed,source(),target(),genders)?'Установите выбранные голоса в пункте 3 «Голоса».':'Готово. Откройте звонок Meet и нажмите «Включить перевод».';
}
function callStatus(state){
  if(!state)return;
  const previous=phase;
  phase=state.phase;el('call-state').textContent=state.text||'Перевод выключен.';
  el('call-panel').dataset.phase=phase;
  el('call-heading').textContent=({starting:'Подготовка перевода…',active:'Перевод работает',stopping:'Останавливаем перевод…',error:'Перевод остановлен: ошибка',stopped:'Перевод выключен'})[phase]||'Состояние перевода';
  el('call-error-code').hidden=!state.code;
  el('call-error-code').textContent=state.code?'Код ошибки: '+state.code:'';
  el('call-start').textContent=phase==='starting'?'Подготовка…':phase==='active'?'Перевод включён':'Включить перевод';
  if(callBusy())el('setup-details').open=false;
  if(phase==='active'&&previous!=='active')showView('conversation');
  if(['stopped','error'].includes(phase)&&['starting','active','stopping'].includes(previous)&&!catalogLoaded)restoreSetup();
  if(Number.isSafeInteger(state.balance_ms)){const seconds=Math.floor(state.balance_ms/1000);el('balance').textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
  syncSetup();
}
async function request(type,extra={}){
  const response=await chrome.runtime.sendMessage({type,...extra});
  if(!response?.ok)throw Error(response?.error||'Расширение не ответило.');
  return response.result;
}
async function refresh(){
  try{
    const state=await request('state');linked=state.connected;
    el('pairing').hidden=linked;el('account').hidden=!linked;
    if(linked){const seconds=Math.floor(state.balance_ms/1000);el('balance').textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
      el('call').textContent=state.active_call?'Есть активный звонок.':'Нет активного звонка.';status('Аккаунт подключён.');}
    else status('Откройте личный кабинет и создайте код подключения.');
  }catch(error){status(error.message);}finally{syncSetup();}
}
async function setupAction(action,output='voice-state'){
  setupBusy=true;syncSetup();
  try{await action();}catch(error){el(output).textContent=error.message;}finally{setupBusy=false;syncSetup();}
}
function languageOptions(restore=false){
  const options=CTVoiceSetup.variants(voices),selected={};
  for(const [which,direction]of [['source','incoming'],['target','outgoing']])selected[which]=el(which+'-language').value||(restore?(preferences[which+'Variant']||
    CTVoiceSetup.restoreVariant(voices,preferences[which],legacyGenders[direction],installed.selected?.[direction])):'');
  for(const [which,other] of [['source','target'],['target','source']]){
    const select=el(which+'-language');select.replaceChildren(new Option('Выберите язык и пол голоса',''));
    const otherLanguage=selected[other]?.split(':')[0];
    for(const item of options){const option=new Option(item.label+(item.available?'':' — '+item.reason),item.value);
      option.disabled=!item.available||item.language===otherLanguage;select.append(option);}
    select.value=options.some(item=>item.value===selected[which]&&item.available&&item.language!==otherLanguage)?selected[which]:'';
  }
  genders={incoming:el('source-language').value.split(':')[1],outgoing:el('target-language').value.split(':')[1]};
  el('language-availability').textContent='';
}
function chosenVoice(direction){const language=direction==='incoming'?source():target();return voices.find(voice=>voice.language===language&&voice.gender===genders[direction]&&voice.compatible!==false);}
async function applyInstalledChoices(){
  let changed=false;
  for(const direction of ['incoming','outgoing']){const voice=chosenVoice(direction);
    if(voice&&installed.voices.some(item=>item.id===voice.id&&item.version===voice.version)&&installed.selected?.[direction]!==voice.id){
      await request('voice-select',{direction,voice_id:voice.id});changed=true;
    }
  }
  if(changed)installed=await request('native-status');
}
function renderVoices(){
  el('voices').replaceChildren();
  const valid=CTVoiceSetup.pair(voices,source(),target());
  el('voice-pair-help').textContent=valid?'Здесь только два варианта, выбранные в пункте 2. Установленные голоса скачивать заново не нужно.':
    'Выберите язык и пол голоса в пункте 2. Здесь появится голос для выбранной стороны.';
  for(const direction of ['incoming','outgoing']){
    const chosen=chosenVoice(direction);
    for(const voice of chosen?[chosen]:[]){
      const isInstalled=installed.voices.some(item=>item.id===voice.id&&item.version===voice.version);
      const row=document.createElement('div');row.className='voice';row.dataset.direction=direction;
      const name=document.createElement('strong');name.textContent=CTVoiceSetup.variants(voices).find(item=>item.language===voice.language&&item.gender===voice.gender)?.label||voice.display_name;
      const sexLabel=({male:'Мужской',female:'Женский',unspecified:'Пол не указан'})[voice.gender]||'Пол не указан';
      const details=document.createElement('p');details.textContent=`${sexLabel} · ${direction==='incoming'?'Будет читать перевод вам':'Будет читать перевод собеседнику'} · ${Math.ceil(voice.download_bytes/1024/1024)} МБ`;
      const button=document.createElement('button');button.dataset.voiceAction='install';button.dataset.locked=String(isInstalled||voice.compatible===false);
      button.textContent=voice.compatible===false?'Обновите программу озвучки':isInstalled?'Установлен':'Установить';
      button.addEventListener('click',()=>setupAction(async()=>{
        el('voice-state').textContent='Скачиваем голос. Дождитесь окончания и не закрывайте расширение.';
        await request('voice-install',{voice_id:voice.id});await request('voice-select',{direction,voice_id:voice.id});installed=await request('native-status');renderVoices();
        el('voice-state').textContent='Голос установлен и используется для выбранной стороны разговора.';
      }));row.append(name,details,button);
      if(isInstalled&&installed.selected?.[direction]!==voice.id){const use=document.createElement('button');use.textContent='Использовать';use.dataset.voiceAction='select';
        use.addEventListener('click',()=>setupAction(async()=>{await request('voice-select',{direction,voice_id:voice.id});installed=await request('native-status');renderVoices();}));row.append(use);}
      if(isInstalled){const preview=document.createElement('button');preview.className='secondary';preview.textContent='Прослушать';preview.dataset.voiceAction='preview';
        preview.addEventListener('click',()=>setupAction(async()=>{previewAudio?.pause();const result=await request('voice-preview',{voice_id:voice.id});previewAudio=new Audio('data:audio/wav;base64,'+result.audio);await previewAudio.play();}));row.append(preview);}
      if(isInstalled){const remove=document.createElement('button');remove.className='danger';remove.textContent='Удалить';remove.dataset.voiceAction='remove';
        const supported=installed.capabilities?.includes('remove-voice');remove.dataset.locked=String(!supported);remove.disabled=!supported;
        if(!supported)remove.title='Обновите программу озвучки установщиком из кабинета.';
        remove.addEventListener('click',()=>{if(!confirm('Удалить «'+voice.display_name+'» с этого компьютера? Выбор этого голоса будет очищен. Голос можно установить снова.'))return;
          setupAction(async()=>{previewAudio?.pause();try{await request('voice-remove',{voice_id:voice.id});el('voice-state').textContent='Голос удалён с компьютера. При необходимости установите его снова.';}finally{installed=await request('native-status');renderVoices();}});
        });row.append(remove);}
      el('voices').append(row);
    }
  }
  syncSetup();
}
el('connect').addEventListener('click',async()=>{el('connect').disabled=true;try{await request('pair',{code:el('code').value.trim()});el('code').value='';await refresh();}catch(error){status(error.message);}finally{el('connect').disabled=false;}});
el('unlink').addEventListener('click',async()=>{try{await request('unlink');await refresh();}catch(error){status(error.message);}});
async function checkComponent(){
  el('native-help').hidden=true;el('native-state').textContent='Проверяем установленную программу…';
  try{installed=await request('native-status');componentAvailable=installed.reason!=='local_dependencies_missing'&&installed.capabilities?.includes('language-variants');
    el('native-state').textContent=componentAvailable?(installed.voices.length?'Программа озвучки найдена. Нажмите «Обновить каталог» в разделе «Языки разговора».':'Программа озвучки найдена. Голоса ещё не установлены. Теперь нажмите «Обновить каталог» в разделе «Языки разговора».'):
      'Программу озвучки нужно обновить. Скачайте установщик в личном кабинете и запустите его.';
    el('native-help').hidden=componentAvailable;
  }catch{componentAvailable=false;el('native-state').textContent='Расширение не смогло связаться с программой озвучки.';el('native-help').hidden=false;}
}
el('native-check').addEventListener('click',()=>setupAction(checkComponent,'native-state'));
async function loadVoices(){
  const result=await request('voice-catalog');installed=await request('native-status');voices=result.voices;catalogLoaded=true;
  languageOptions(true);await applyInstalledChoices();renderVoices();el('voice-state').textContent='Каталог обновлён. В пункте 2 выберите язык вместе с полом голоса.';
}
async function restoreSetup(){
  if(!linked||!preferences.source||!preferences.target||callBusy()||setupBusy)return;
  await setupAction(async()=>{await checkComponent();if(componentAvailable){await loadVoices();if(CTVoiceSetup.ready(voices,installed,source(),target(),genders))el('setup-details').open=false;}});
}
el('catalog-refresh').addEventListener('click',()=>setupAction(loadVoices));
for(const which of ['source','target'])el(which+'-language').addEventListener('change',()=>setupAction(async()=>{
  languageOptions();preferences={source:source(),target:target(),sourceVariant:el('source-language').value,targetVariant:el('target-language').value};
  await chrome.storage.local.set({callLanguages:preferences});await applyInstalledChoices();renderVoices();
}));
el('call-start').addEventListener('click',async()=>{
  if(callBusy())return;
  previewAudio?.pause();callStatus({phase:'starting',text:'Начинаем подготовку. Дождитесь сообщения «Всё готово, начинайте разговор».'});
  try{callStatus(await request('call-start',{source:source(),language:target(),hearOwnTranslation:el('hear-own').checked,echoGuard:el('echo-guard').checked}));}
  catch(error){const state=await request('call-state').catch(()=>null);callStatus(state?.phase==='error'?state:{phase:'error',text:error.message,code:'start_failed'});}
});
el('call-stop').addEventListener('click',async()=>{callStatus({phase:'stopping',text:'Останавливаем перевод и возвращаем обычный микрофон…'});try{callStatus(await request('call-stop'));}catch(error){callStatus({phase:'error',text:error.message,code:'stop_failed'});}});
el('hear-own').addEventListener('change',()=>request('call-monitor',{enabled:el('hear-own').checked}).catch(error=>status(error.message)));
el('echo-guard').addEventListener('change',()=>request('call-echo-guard',{enabled:el('echo-guard').checked}).catch(error=>status(error.message)));
el('transcript-folder').addEventListener('click',async()=>{try{const folder=await request('transcript-folder-choose');el('transcript-path').textContent=folder.name;}catch(error){fileStatus({ok:false,text:error.message});}});
el('transcripts').addEventListener('click',()=>request('open-transcripts').catch(error=>fileStatus({ok:false,text:error.message})));
el('open-conversation').addEventListener('click',()=>request('open-conversation').catch(error=>status(error.message)));
el('export-metrics').addEventListener('click',CTConversation.exportMetrics);
function fileStatus(value){const node=el('transcript-file-status');if(node){node.textContent=value?.ok===false?value.text||'':'';node.hidden=!node.textContent;node.classList.toggle('error',value?.ok===false);}}
async function initialize(){
  const folder=await request('transcript-destination').catch(()=>null);
  if(folder){el('transcript-path').textContent=folder.name;el('transcript-path').title=folder.path;}
  fileStatus((await chrome.storage.local.get('transcriptFileStatus')).transcriptFileStatus);
  el('extension-version').textContent='Версия '+chrome.runtime.getManifest().version;
  const data=await chrome.storage.local.get(['hearOwnTranslation','callLanguages','echoGuard','voiceGenders']);
  legacyGenders=data.voiceGenders||{};
  el('echo-guard').checked=data.echoGuard!==false;
  el('hear-own').checked=data.hearOwnTranslation===true;preferences=data.callLanguages||{};
  await refresh();callStatus(await request('call-state'));
  CTConversation.render(await request('conversation-state').catch(()=>null));
  if(linked&&preferences.source&&preferences.target&&!callBusy())await setupAction(async()=>{
    await checkComponent();if(componentAvailable){await loadVoices();if(CTVoiceSetup.ready(voices,installed,source(),target(),genders)){el('voice-state').textContent='Языки и голоса восстановлены. Можно включать перевод.';el('setup-details').open=false;}}
  });
  if(!callBusy()&&!CTVoiceSetup.ready(voices,installed,source(),target(),genders))showView('settings');
}
initialize().catch(error=>status(error.message));
chrome.storage.onChanged.addListener((changes,area)=>{if(area==='local'&&changes.transcriptFileStatus)fileStatus(changes.transcriptFileStatus.newValue);if(area==='session'&&changes.callStatus)callStatus(changes.callStatus.newValue);if(area==='session'&&changes.liveConversation)CTConversation.render(changes.liveConversation.newValue);});
syncSetup();
