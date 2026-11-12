let selected = new URL(location.href).searchParams.get('conversation');
async function refresh() {
  const sessions = await CTjournal.conversations();
  const saved = await chrome.storage.local.get(['currentConversation', 'transcriptError']);
  if (!selected) selected = saved.currentConversation || sessions[0]?.id;
  const selector = document.getElementById('conversation'); selector.replaceChildren();
  for (const session of sessions) {
    const option = document.createElement('option'); option.value = session.id;
    option.textContent = `${new Date(session.started_at).toLocaleString()}${session.source ? ` · ${session.source} ↔ ${session.target}` : ''} · ${session.state === 'active' ? 'идёт разговор' : 'завершена'} · ${session.id.slice(0,8)}`;
    selector.append(option);
  }
  selector.value = selected || '';
  const info = sessions.find(session => session.id === selected);
  document.getElementById('details').textContent = info
    ? `Беседа ${info.id}. ${info.state === 'active' ? 'Запись начата; файл сохранится после остановки.' : 'Разговор завершён.'}${info.export_file ? ' Файл: ' + info.export_file : ''}${info.finish_warning ? ' ' + info.finish_warning : ''}`
    : 'Пока нет бесед. Включите перевод, чтобы начать запись.';
  document.getElementById('entries').innerHTML = selected ? CTtranscript.entries(await CTjournal.entries(selected)) : '';
  document.getElementById('save').disabled = !info;
  if (saved.transcriptError) document.getElementById('error').textContent = saved.transcriptError;
}
const report = error => { document.getElementById('error').textContent = error.message; };
document.getElementById('refresh').onclick = () => refresh().catch(report);
document.getElementById('conversation').onchange = event => {
  selected = event.target.value;
  history.replaceState(null, '', '?conversation=' + encodeURIComponent(selected));
  refresh().catch(report);
};
document.getElementById('save').onclick = async () => {
  try {
    await refresh();
    const response = await chrome.runtime.sendMessage({type: 'export-conversation', conversation: selected});
    if (response?.error) throw Error(response.error);
    document.getElementById('error').textContent = 'Файл выбранной беседы сохранён в Загрузки / CallTranslator.';
  } catch (error) { report(error); }
};
refresh().catch(report);
chrome.storage.onChanged.addListener(changes => {
  if (changes.currentConversation) selected = changes.currentConversation.newValue;
  if (changes.speech0 || changes.speech1 || changes.currentConversation || changes.lastTranscriptFile) refresh().catch(report);
});
