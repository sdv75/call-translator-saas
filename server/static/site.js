'use strict';
(() => {
  const base = document.documentElement.dataset.base || '';
  const status = document.getElementById('account-status');
  if (!status) return;
  let csrf = '';
  let codeExpiryTimer;
  const el = id => document.getElementById(id);
  const duration = ms => {
    const seconds = Math.floor(ms / 1000);
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };
  async function api(path, method = 'GET') {
    const response = await fetch(base + path, {method, credentials: 'same-origin',
      headers: method === 'GET' ? {} : {'X-CSRF-Token': csrf}});
    if (response.status === 401) throw new Error('Войдите в аккаунт ещё раз.');
    if (!response.ok) throw new Error('Не удалось выполнить запрос. Попробуйте позже.');
    return response.json();
  }
  async function loadDevices() {
    const data = await api('/api/devices');
    const list = el('devices');
    list.replaceChildren();
    if (!data.devices.length) { list.textContent = 'Подключённых устройств пока нет.'; return; }
    for (const device of data.devices) {
      const row = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `Устройство ${device.id.slice(0, 8)} · до ${new Date(device.expires_at * 1000).toLocaleDateString()}`;
      const button = document.createElement('button');
      button.className = 'secondary'; button.textContent = 'Отключить';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try { await api('/api/devices/' + encodeURIComponent(device.id), 'DELETE'); await loadDevices(); }
        catch (error) { status.textContent = error.message; button.disabled = false; }
      });
      row.append(label, button); list.append(row);
    }
  }
  async function loadHistory() {
    const data = await api('/api/calls');
    const list = el('history'); list.replaceChildren();
    if (!data.calls.length) { list.textContent = 'История пока пуста.'; return; }
    for (const call of data.calls) {
      const row = document.createElement('li');
      row.textContent = `${call.state === 'active' ? 'Активный' : 'Завершённый'} звонок · ${duration(call.speech_ms)} речи`;
      list.append(row);
    }
  }
  el('pair-device').addEventListener('click', async () => {
    const button = el('pair-device'); button.disabled = true;
    try {
      const data = await api('/api/devices/pair', 'POST');
      clearTimeout(codeExpiryTimer);
      el('pair-code').textContent = data.code; el('pair-code').hidden = false; el('copy-code').hidden = false;
      status.textContent = 'Код действует 5 минут. Передавайте его только своему расширению.';
      codeExpiryTimer = setTimeout(() => { el('pair-code').textContent = ''; el('pair-code').hidden = true; el('copy-code').hidden = true; }, data.expires_in * 1000);
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  el('copy-code').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(el('pair-code').textContent); status.textContent = 'Код скопирован.'; }
    catch { status.textContent = 'Выделите и скопируйте код вручную.'; }
  });
  el('logout').addEventListener('click', async () => {
    try { await api('/auth/logout', 'POST'); location.assign(base + '/account'); }
    catch (error) { status.textContent = error.message; }
  });
  (async () => {
    try {
      const health = await api('/health');
      if (!health.google_login_configured) {
        status.textContent = 'Google-вход ещё не настроен. Версия находится в разработке.';
        return;
      }
      const response = await fetch(base + '/api/account', {credentials: 'same-origin'});
      if (response.status === 401) { status.textContent = ''; el('signed-out').hidden = false; return; }
      if (!response.ok) throw new Error('Кабинет временно недоступен.');
      const data = await response.json(); csrf = data.csrf_token;
      if (el('installer-download')) el('installer-download').hidden = !health.installer_available;
      el('balance').textContent = duration(data.balance_ms);
      el('active-call').textContent = data.active_call ? 'Есть активный звонок' : 'Нет активного звонка';
      el('signed-in').hidden = false; status.textContent = 'Вы вошли через Google.';
      await Promise.all([loadDevices(), loadHistory()]);
    } catch (error) { status.textContent = error.message; }
  })();
})();
