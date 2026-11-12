'use strict';
globalThis.CTTranscriptFiles=(()=>{
  let opening,queue=Promise.resolve();
  const database=()=>opening||=new Promise((resolve,reject)=>{
    const request=indexedDB.open('ct-saas-transcript-files',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('settings');
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(Error('Не удалось прочитать настройки папки.'));
  });
  async function read(key){
    const db=await database();return new Promise((resolve,reject)=>{
      const request=db.transaction('settings').objectStore('settings').get(key);
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(Error('Не удалось прочитать настройки папки.'));
    });
  }
  async function write(key,value){
    const db=await database();return new Promise((resolve,reject)=>{
      const tx=db.transaction('settings','readwrite');tx.objectStore('settings').put(value,key);
      tx.oncomplete=resolve;tx.onerror=tx.onabort=()=>reject(Error('Не удалось сохранить настройки папки.'));
    });
  }
  const rootName='Call_Translator_Stennograms';
  let native;
  function configure(client){native=client;}
  async function command(type,data={}){
    if(!native)throw Error('Обновите программу озвучки установщиком из кабинета.');
    return native.request(type,data);
  }
  async function destination(){
    const value=await command('transcript-folder-status');
    const legacy=await read('directory');
    if(legacy&&!value.custom&&!await read('native-configured'))return {
      name:legacy.name+'\\'+rootName,path:legacy.name+'\\'+rootName,custom:true,requiresFolderChoice:true};
    const previous=await read('default-download');
    const index=previous?.lastIndexOf(rootName);
    const path=value.path||(index>=0?previous.slice(0,index+rootName.length):'Загрузки Chrome\\'+rootName);
    return {name:path.split(/[\\/]/).slice(-2).join('\\'),path,custom:value.custom,allowed:true};
  }
  async function choose(){
    const current=await command('transcript-folder-status');
    const downloaded=current.custom?undefined:await defaultDownload();
    const value=await command('transcript-folder-choose',{downloaded});
    if(value.custom)await write('native-configured',true);return destination();
  }
  async function defaults(){await command('transcript-folder-default');await write('native-configured',true);return destination();}
  async function waitDownload(id){
    for(let attempt=0;attempt<40;attempt++){
      const [item]=await chrome.downloads.search({id});
      if(item?.state==='complete')return item;
      if(!item||item.state==='interrupted')throw Error('Не удалось записать файл стенограммы. Текст сохранён в истории.');
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    throw Error('Файл ещё не сохранён. Проверьте загрузки Chrome и повторите сохранение из истории.');
  }
  async function defaultDownload(){
    let downloaded=await read('default-download');
    if(!downloaded){
      const html='<!doctype html><html lang="ru"><meta charset="utf-8"><title>Стенограммы</title><p>Стенограммы Call Translator находятся в папках по дням.</p></html>';
      const id=await chrome.downloads.download({url:'data:text/html;charset=utf-8,'+encodeURIComponent(html),filename:rootName+'/_index.html',saveAs:false,conflictAction:'overwrite'});
      downloaded=(await waitDownload(id)).filename;await write('default-download',downloaded);
    }
    return downloaded;
  }
  async function open(){
    const value=await destination();
    if(value.requiresFolderChoice)throw Error('Подтвердите прежнюю папку кнопкой «Изменить». Существующие файлы остаются на месте.');
    await command('transcript-folder-open',value.custom?{}:{downloaded:await defaultDownload()});
  }
  async function status(value){await chrome.storage.local.set({transcriptFileStatus:value});}
  async function save(session,entries,force){
    if(!entries.length)return;
    if((await destination()).requiresFolderChoice)throw Error('Подтвердите прежнюю папку кнопкой «Изменить». Текст сохранён в истории.');
    const folderStatus=await command('transcript-folder-status'),target='layout2:'+(folderStatus.path||'downloads');
    const html=CTTranscript.html(session,entries);
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(html))),b=>b.toString(16).padStart(2,'0')).join('');
    const key='export:'+session.id,previous=await read(key);
    if(!force&&previous?.digest===digest&&previous.target===target&&previous.complete)return;
    const filename='CallTranslator_'+CTTranscript.filename(session.started_at).replace('.html','')+'_'+session.id.replace(/[^a-zA-Z0-9_-]/g,'').slice(0,16)+'.html';
    const day=CTTranscript.filename(session.started_at).slice(0,10);
    if(folderStatus.custom){
      await command('transcript-write',{day,filename,html});
    }else{
      let id=previous?.digest===digest&&previous.target===target?previous.downloadId:undefined;
      if(id!==undefined){const [item]=await chrome.downloads.search({id});if(!item||item.state==='interrupted')id=undefined;}
      if(id===undefined){
        id=await chrome.downloads.download({url:'data:text/html;charset=utf-8,'+encodeURIComponent(html),filename:rootName+'/'+day+'/'+filename,saveAs:false,conflictAction:'overwrite'});
        await write(key,{digest,target,downloadId:id,complete:false});
      }
      const item=await waitDownload(id);await write('default-download',item.filename);
    }
    await write(key,{digest,target,complete:true});
    await status({ok:true,text:''});
  }
  function exportSession(session,{force=false}={}){
    const task=queue.catch(()=>{}).then(async()=>{
      try{await save(session,await CTJournal.entries(session.id),force);}
      catch(error){await status({ok:false,text:error.name==='NotAllowedError'?'Нет доступа к папке стенограмм. Подтвердите доступ в истории.':error.message});throw error;}
    });queue=task;return task;
  }
  async function recover(sessions){
    for(let session of sessions){
      if(['active','starting'].includes(session.state)){
        session={...session,state:'interrupted',ended_at:Date.now()};await CTJournal.putSession(session);
      }
      await exportSession(session).catch(()=>{});
    }
  }
  return {configure,destination,choose,defaults,open,exportSession,recover};
})();
