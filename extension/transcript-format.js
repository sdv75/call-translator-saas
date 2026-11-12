'use strict';
(() => {
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function filename(started) {
    const d=new Date(started),pad=value=>String(value).padStart(2,'0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}.html`;
  }
  function html(session,entries) {
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Call Translator — стенограмма</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#243042}h1{font-size:24px}h2{font-size:15px;color:#64748b}article{padding:16px 0;border-top:1px solid #ddd}p{white-space:pre-wrap;overflow-wrap:anywhere}.translation{color:#215c83}</style><body><h1>Стенограмма Call Translator</h1><p>'+escape(new Date(session.started_at).toLocaleString())+'</p>'+entries.map(item=>
      '<article><h2>'+escape(item.direction==='incoming'?'Собеседники':'Я')+(item.uncertain?' · неуверенное распознавание':'')+'</h2><p dir="auto">'+escape(item.original)+'</p><p class="translation" dir="auto">'+escape(item.text || 'Перевод не получен')+'</p></article>').join('')+'</body></html>';
  }
  globalThis.CTTranscript={escape,filename,html};
  if(typeof module!=='undefined') module.exports=globalThis.CTTranscript;
})();
