'use strict';
globalThis.CTConversation=(()=>{
  const seconds=value=>Number.isFinite(value)?(value/1000).toFixed(2)+' с':'—';
  const labels={translation_queue_ms:'Очередь перевода',translation_ms:'Перевод',voice_queue_ms:'Очередь озвучки',tts_ms:'Озвучка и связь с программой',synthesis_ms:'Синтез голоса',native_transfer_ms:'Обмен с локальной программой',decode_ms:'Подготовка звука',routing_ms:'Передача звука и защита от эха',playback_queue_ms:'Ожидание воспроизведения',after_recognition_ms:'От распознанного текста до звука',stt_backlog_ms:'Отставание распознанного аудио'};
  let latest={events:[],partial:{}};
  function text(tag,value,className){const node=document.createElement(tag);node.textContent=value;if(className)node.className=className;if(['original','translated','interim'].includes(className))node.dir='auto';return node;}
  function render(data){
    latest=data||{events:[],partial:{}};
    const names=globalThis.CTVoiceSetup?.names||{};
    for(const direction of ['outgoing','incoming']){
      const feed=document.getElementById(direction+'-feed');if(!feed)continue;
      const atBottom=feed.scrollHeight-feed.scrollTop-feed.clientHeight<45,scroll=feed.scrollTop;
      feed.replaceChildren();
      const own=direction==='outgoing',originalLanguage=names[own?latest.source:latest.target]||'',targetLanguage=names[own?latest.target:latest.source]||'';
      for(const row of (latest.events||[]).filter(row=>row.direction===direction).slice(-15)){
        const article=document.createElement('article');article.className='utterance';
        article.append(text('span',(own?'Вы сказали':'Собеседник сказал')+(originalLanguage?' · '+originalLanguage:''),'utterance-label'),text('p',row.original||'Распознаём речь…','original'));
        article.append(text('span',(own?'Перевод собеседнику':'Перевод для вас')+(targetLanguage?' · '+targetLanguage:''),'utterance-label translated-label'),text('p',row.text||'Переводим…',row.text?'translated':'pending'));
        if(row.uncertain)article.append(text('small','Распознано неуверенно — проверьте оригинал.','pending'));
        feed.append(article);
      }
      if(latest.partial?.[direction])feed.append(text('p',latest.partial[direction]+' …','interim'));
      if(!feed.children.length)feed.append(text('p',own?'Здесь появятся ваши слова и перевод для собеседника.':'Здесь появятся слова собеседника и перевод для вас.','empty'));
      feed.scrollTop=atBottom?feed.scrollHeight:scroll;
    }
    const warning=document.getElementById('microphone-warning');
    if(warning){warning.hidden=!latest.guarded;warning.textContent='Сейчас звучит перевод. Защита от эха временно не передаёт вашу речь — дождитесь окончания озвучки.';}
    const metrics=document.getElementById('latency-values');
    if(metrics){
      metrics.replaceChildren();
      for(const direction of ['outgoing','incoming']){
        const row=[...(latest.events||[])].reverse().find(row=>row.direction===direction&&row.timing?.after_recognition_ms!==undefined);
        const section=document.createElement('div');section.className='metric-direction';section.append(text('strong',direction==='outgoing'?'Ваш перевод':'Перевод собеседника'));
        if(row){for(const [key,label]of Object.entries(labels))if(row.timing[key]!==undefined){const line=document.createElement('p');line.append(text('span',label),text('b',seconds(row.timing[key])));section.append(line);}}
        else section.append(text('p','Замеры появятся после первой озвученной фразы.','empty'));
        metrics.append(section);
      }
      const suppressed=document.getElementById('suppressed-time');if(suppressed)suppressed.textContent='Защита от эха не передавала микрофон: '+seconds(latest.suppressed_ms||0)+'.';
    }
  }
  function exportMetrics(){
    const report={schema:1,generated_at:new Date().toISOString(),guard_suppressed_ms:latest.suppressed_ms||0,
      samples:(latest.events||[]).filter(row=>row.timing).map(row=>({direction:row.direction,sequence:row.sequence,...row.timing}))};
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='CallTranslator-diagnostics.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return {render,exportMetrics};
})();
