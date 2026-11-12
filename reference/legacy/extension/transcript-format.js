globalThis.CTtranscript = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const css = 'body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:16px}article{border-left:5px solid;padding:12px;margin:12px 0;white-space:pre-wrap}.speaker0{border-color:#175dc5;background:#edf4ff}.speaker1{border-color:#ad4616;background:#fff1e8}small{display:block;color:#444}';
  function entries(events) {
    return [...events].sort((a,b) => a.received_at-b.received_at || a.direction-b.direction || a.sequence-b.sequence).map(event => {
      const warning = event.uncertain ? ' [распознано неуверенно]' : '';
      const partial = event.partial ? ' [фраза ещё не завершена]' : '';
      const audit = event.segments?.length ? '<details><summary>Исходные фрагменты распознавания</summary>' + event.segments.map(segment => `<small>${escape(segment.start)} с: ${escape(segment.text)} · уверенность ${escape(segment.confidence)}</small>`).join('') + '</details>' : '';
      return `<article class="speaker${event.direction === 0 ? 0 : 1}"><small>${escape(new Date(event.received_at).toLocaleString())} · ${event.direction === 0 ? 'Вы' : 'Собеседник'} · реплика ${escape(event.sequence)}</small>${escape(event.text)}${warning}${partial} → ${escape(event.translation || '[перевод ещё не получен]')}${audit}</article>`;
    }).join('');
  }
  function html(session, events) {
    return `<!doctype html><html lang="ru"><meta charset="utf-8"><title>Стенограмма беседы</title><style>${css}</style><h1>Стенограмма беседы</h1><p>${escape(new Date(session.started_at).toLocaleString())}${session.ended_at ? ' — ' + escape(new Date(session.ended_at).toLocaleString()) : ''}</p><p>Беседа ${escape(session.id)}</p>${session.finish_warning ? '<p>' + escape(session.finish_warning) + '</p>' : ''}${entries(events)}</html>`;
  }
  function filename(session) {
    const date = new Date(session.started_at);
    const pad = value => String(value).padStart(2, '0');
    const day = `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`;
    return `CallTranslator/${day}/${day}_${pad(date.getHours())}-${pad(date.getMinutes())}-${pad(date.getSeconds())}.html`;
  }
  return {entries, html, filename};
})();
