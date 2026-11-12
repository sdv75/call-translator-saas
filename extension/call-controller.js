'use strict';
const CTCallErrors={
  protocol_error:'Сбой передачи звука. Обновите вкладку Meet и включите перевод снова.',
  provider_error:'Сервис распознавания или перевода прервал обработку. Включите перевод снова.',
  network_error:'Соединение с сервером прервано. Проверьте интернет и включите перевод снова.',
  network_backlog:'Интернет не успевает передавать звук. Перевод остановлен, чтобы не накапливать задержку.',
  translation_backlog:'Озвучка не успевает за разговором. Дождитесь окончания фразы и включите перевод снова.',
  local_voice_failed:'Не удалось озвучить перевод. Проверьте голоса кнопкой «Прослушать» и включите перевод снова.',
  local_voice_lost:'Связь с программой озвучки потеряна. Перезапустите Chrome и проверьте компонент.',
  credential_revoked:'Подключение аккаунта отозвано. Подключите расширение заново через личный кабинет.',
  balance_exhausted:'Закончилось доступное время речи. Откройте личный кабинет.',
  silence_timeout:'Разговор остановлен после 10 минут тишины. При необходимости включите перевод снова.',
  capture_ended:'Захват звука вкладки завершён. Обновите вкладку Meet и включите перевод снова.',
  journal_failed:'Не удалось сохранить стенограмму на компьютере. Проверьте свободное место.',
  runtime_lost:'Связь с расширением потеряна. Обновите вкладку Meet.',
  tab_navigation:'Вкладка Meet обновилась. Войдите в звонок и включите перевод снова.',
  tab_closed:'Вкладка звонка закрыта.',
  'tab-ended':'Звонок Meet завершён.',
  'page-failed':'Meet сменил аудиодорожку. Обновите вкладку и включите перевод снова.'
};
class CTCallController {
  constructor(chrome,voice,journal,api,files=null) {
    Object.assign(this,{chrome,voice,journal,api,files}); this.run=null; this.starting=false;
    this.live={events:[],partial:{},guarded:false,suppressed_ms:0};
    this.state={phase:'stopped',text:'Перевод выключен.'};
    voice.onLost=()=>{if(this.run && !this.run.stopping) this.stop('local_voice_lost').catch(()=>{});};
  }
  status() {return {...this.state};}
  async saveLive(){
    const snapshot=JSON.parse(JSON.stringify(this.live));
    this.liveSaving=(this.liveSaving||Promise.resolve()).catch(()=>{}).then(()=>this.chrome.storage.session.set({liveConversation:snapshot}));
    await this.liveSaving;
  }
  async liveUpdate(event){
    if(!['incoming','outgoing'].includes(event?.direction)||!Number.isSafeInteger(event.sequence)||event.sequence<1)return;
    if(event.type==='interim')this.live.partial[event.direction]=String(event.original||'').slice(0,4000);
    else{
      if(event.type==='recognized')this.live.partial[event.direction]='';
      let row=this.live.events.find(row=>row.direction===event.direction&&row.sequence===event.sequence);
      if(!row){row={direction:event.direction,sequence:event.sequence,received_at:Date.now()};this.live.events.push(row);}
      if(typeof event.original==='string')row.original=event.original.slice(0,4000);
      if(typeof event.uncertain==='boolean')row.uncertain=event.uncertain;
      if(event.type==='translation')row.text=String(event.text||'').slice(0,8000);
      if(event.timing)row.timing={...row.timing,...Object.fromEntries(Object.entries(event.timing).filter(([,value])=>Number.isFinite(value)&&value>=0&&value<3600000))};
      this.live.events=this.live.events.slice(-60);
    }
    await this.saveLive();
  }
  async publish(phase,text,code=null) {
    this.state={phase,text,code}; await this.chrome.storage.session.set({callStatus:this.state}).catch(()=>{});
  }
  async contexts() {return this.chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT'],documentUrls:[this.chrome.runtime.getURL('offscreen.html')]});}
  async ensureOffscreen() {
    if ((await this.contexts()).length) return;
    this.creating ||= this.chrome.offscreen.createDocument({url:'offscreen.html',reasons:['USER_MEDIA'],
      justification:'Capture the selected Meet tab and play local translations outside the captured tab.'});
    try {await this.creating;} finally {this.creating=null;}
  }
  async offscreen(run,type,payload={}) {
    const response=await this.chrome.runtime.sendMessage({target:'offscreen',type,sessionId:run.id,...payload});
    if (!response?.ok || response.error || response.ignored && type==='activate') throw Error('Аудиокомпонент не ответил.');
    return response;
  }
  async page(run,method,payload={}) {
    const results=await this.chrome.scripting.executeScript({target:{tabId:run.tabId},world:'MAIN',
      func:async(command,data)=>{
        if(command==='status') return {senders:window.__callTranslatorProbe?.audioSenders().length || 0};
        if(!['start','stop','audio'].includes(command)) throw Error('Unsupported page operation');
        if(!window.__CTtranslate) {if(command==='stop') return;throw Error('Reload Meet');}
        return window.__CTtranslate[command](data);
      },args:[method,payload]});
    return results?.[0]?.result;
  }
  check(run) {if(this.run!==run || run.cancelled) throw Error('Запуск отменён.');}
  async recover() {
    const {audioSession:previous}=await this.chrome.storage.session.get('audioSession');
    if(!previous) return;
    await Promise.allSettled([this.page(previous,'stop'),this.chrome.offscreen.closeDocument()]);
    if(previous.session) await this.journal.putSession({...previous.session,state:'interrupted',ended_at:Date.now()});
    await this.chrome.storage.session.remove('audioSession');
    await this.publish('error','Расширение перезапустилось. Микрофон восстановлен; запустите перевод вручную.');
  }
  async start(options) {
    if(this.run || this.starting) throw Error('Звонок уже запущен или завершается.');
    if(!globalThis.CTLanguageLibrary[options.source]?.stt || !globalThis.CTLanguageLibrary[options.language]?.stt || options.source===options.language)
      throw Error('Выберите два разных языка.');
    this.starting=true;
    const run={id:crypto.randomUUID(),cancelled:false,native:false}; this.run=run;
    try {
      await this.publish('starting','Проверяем аккаунт, Meet и локальные голоса…'); this.check(run);
      const config=await this.chrome.storage.local.get(['service','credential']); this.check(run);
      if(config.service!==CTService.url || !config.credential) throw Error('Подключите аккаунт.');
      const service=CTService.url;
      const tabs=await this.chrome.tabs.query({active:true,currentWindow:true}); this.check(run);
      const tab=tabs[0];
      if(!tab?.id || !/^https:\/\/meet\.google\.com\/.+/.test(tab.url || '')) throw Error('Откройте вкладку звонка Google Meet.');
      run.tabId=tab.id;
      const bridge=await this.chrome.tabs.sendMessage(tab.id,{type:'bridge-ready'}); this.check(run);
      const page=await this.page(run,'status'); this.check(run);
      if(!bridge?.ok || !page?.senders) throw Error('Войдите в Meet и включите микрофон. После установки расширения обновите вкладку.');
      const health=await this.api(service,'/health'); this.check(run);
      if(!health.audio_enabled) throw Error('Технические звонки на сервере пока выключены.');
      const account=await this.api(service,'/api/account',{headers:{Authorization:'Bearer '+config.credential}}); this.check(run);
      if(account.active_call) throw Error('Этот аккаунт уже используется в другом звонке.');
      if(account.balance_ms<=0) throw Error('Закончился баланс времени речи.');
      const voices=await this.voice.request('status');this.check(run);
      if(!voices.ready) throw Error('Установите и проверьте локальные голоса перед звонком.');
      for(const [direction,language] of [['incoming',options.source],['outgoing',options.language]]) {
        if(!voices.voices?.some(voice=>voice.id===voices.selected?.[direction] && voice.language===language))
          throw Error('Выберите локальные голоса для обоих языков звонка.');
      }
      await this.publish('starting','Подготавливаем два голоса. При первом запуске это может занять до 3 минут…');this.check(run);
      await this.voice.request('begin-call',{source:options.source,target:options.language}); this.check(run); run.native=true;
      run.session={id:run.id,source:options.source,target:options.language,started_at:Date.now(),state:'starting'};
      this.live={session:run.id,source:options.source,target:options.language,events:[],partial:{},guarded:false,suppressed_ms:0};await this.saveLive();this.check(run);
      await this.journal.putSession(run.session); this.check(run);
      await this.chrome.storage.session.set({audioSession:{id:run.id,tabId:run.tabId,session:run.session}}); this.check(run);
      await this.ensureOffscreen(); this.check(run);
      await this.publish('starting','Подключаем звук Meet и сервис перевода…');this.check(run);
      const streamId=await this.chrome.tabCapture.getMediaStreamId({targetTabId:tab.id}); this.check(run);
      await this.offscreen(run,'start',{service,credential:config.credential,streamId,source:options.source,
        language:options.language,hearOwnTranslation:options.hearOwnTranslation===true,echoGuard:options.echoGuard===true}); this.check(run);
      await this.page(run,'start',{workletURL:this.chrome.runtime.getURL('pcm-worklet.js'),sessionId:run.id,echoGuard:options.echoGuard===true}); this.check(run);
      await this.offscreen(run,'activate'); this.check(run);
      run.session.state='active'; await this.journal.putSession(run.session); this.check(run);
      await this.publish('active','Всё готово, начинайте разговор. Перевод работает в обе стороны.'); this.check(run);
      return this.status();
    } catch(error) {
      run.startError=error;
      await this.cleanup(run,'start_failed');
      throw error;
    } finally {this.starting=false;}
  }
  async stop(reason='user_stop') {
    const run=this.run;
    if(!run) return this.status();
    run.cancelled=true;
    if(this.starting) this.voice.close();
    return this.cleanup(run,reason);
  }
  async cleanup(run,reason) {
    if(run.stopping) return run.stopping;
    run.cancelled=true;
    run.stopping=(async()=>{
      await this.publish('stopping','Останавливаем перевод и возвращаем микрофон…');
      // Restoration runs immediately, independently of the bounded STT drain.
      const restored=Number.isInteger(run.tabId)?this.page(run,'stop'):Promise.resolve();
      const remote=this.offscreen(run,'stop').catch(()=>({complete:false}));
      const result=await Promise.allSettled([restored,remote]);
      if(this.creating) await this.creating.catch(()=>{});
      if(this.run===run) await this.chrome.offscreen.closeDocument().catch(()=>{});
      if(run.native) {
        let timer;
        await Promise.race([this.voice.request('end-call'),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('timeout')),5000);})])
          .catch(()=>this.voice.close()).finally(()=>clearTimeout(timer));
      }
      let saved=true;
      if(run.session){
        const session={...run.session,state:reason==='user_stop'?'stopped':'error',reason,ended_at:Date.now()};
        await this.journal.putSession(session).catch(()=>{saved=false;});
        if(saved&&this.files)await this.files.exportSession(session).catch(()=>{});
      }
      if(this.run===run) {this.run=null;await this.chrome.storage.session.remove('audioSession').catch(()=>{});}
      const failed=reason!=='user_stop' || result[0].status==='rejected' || !saved;
      const complete=result[1].status==='fulfilled' && result[1].value?.complete!==false;
      this.live.guarded=false;await this.saveLive().catch(()=>{});
      await this.publish(failed?'error':'stopped',result[0].status==='rejected' ?
        'Не удалось подтвердить восстановление микрофона. Обновите вкладку Meet.' :
        !saved ? 'Микрофон возвращён. Локальная стенограмма сохранилась не полностью.' :
        failed ? (run.startError?.message || CTCallErrors[reason] || 'Перевод остановлен из-за сбоя. Обновите вкладку Meet и повторите запуск.') :
        !complete ? 'Перевод выключен. Стенограмма сохранена; последние фрагменты могли не поступить.' : 'Перевод выключен. Стенограмма сохранена на этом устройстве.',failed?reason:null);
      return this.status();
    })();
    return run.stopping;
  }
  async event(message,sender) {
    const run=this.run;
    if(sender.tab) {
      if(sender.tab.id!==run?.tabId || message.sessionId!==run?.id) return {ok:true,ignored:true};
      if(message.type==='pcm') {
        if(!run.cancelled) await this.offscreen(run,'pcm',{samples:message.samples});
        return {ok:true};
      }
      if(message.type==='microphone-state'){
        this.live.guarded=message.guarded===true;
        this.live.suppressed_ms=Number.isSafeInteger(message.suppressed_ms)&&message.suppressed_ms>=0?message.suppressed_ms:0;
        await this.saveLive();return {ok:true};
      }
      if(['tab-ended','page-failed'].includes(message.type)) {await this.stop(message.type);return {ok:true};}
      throw Error('Недопустимый запрос страницы.');
    }
    if(sender.url!==this.chrome.runtime.getURL('offscreen.html') || message.sessionId!==run?.id) throw Error('Сеанс аудио не найден.');
    if(message.type==='audio-heartbeat') return {ok:!!run && !run.cancelled};
    if(message.type==='audio-failed') {await this.stop(message.reason || 'audio_failed');return {ok:true};}
    if(message.type==='audio-balance') {
      if(!Number.isSafeInteger(message.balance_ms) || message.balance_ms<0) throw Error('Некорректное состояние баланса.');
      this.state.balance_ms=message.balance_ms;
      await this.chrome.storage.session.set({callStatus:{...this.state}}).catch(()=>{});return {ok:true};
    }
    if(message.type==='audio-journal') {await this.liveUpdate(message.event);await this.journal.record(run.id,message.event);return {ok:true};}
    if(['audio-live','audio-metrics'].includes(message.type)){await this.liveUpdate(message.event);if(message.type==='audio-metrics')await this.journal.record(run.id,message.event);return {ok:true};}
    if(message.type==='native-synthesize') {
      if(run.cancelled) throw Error('Звонок остановлен.');
      return this.voice.request('synthesize',{direction:message.direction,text:message.text});
    }
    if(message.type==='page-audio') {
      if(!run.cancelled) await this.page(run,'audio',{audio:message.audio});
      return {ok:true};
    }
    if(message.type==='local-playback') {
      if(!Number.isFinite(message.delayMs)||!Number.isFinite(message.durationMs)||message.delayMs<0||message.delayMs>30000||message.durationMs<=0||message.durationMs>360000)
        throw Error('Некорректная длительность озвучки.');
      if(!run.cancelled)await this.page(run,'guard',{delayMs:message.delayMs,durationMs:message.durationMs});
      return {ok:true};
    }
    throw Error('Недопустимое аудиосообщение.');
  }
}
globalThis.CTCallController=CTCallController;
if(typeof module!=='undefined') module.exports=CTCallController;
