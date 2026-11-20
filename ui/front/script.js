
(function () {
  let $ = function (s) { return document.querySelector(s); };
  let shell = $('#shell'), chat = $('#chat'), thread = $('#thread');
  let composer = $('#composer'), sendBtn = $('#sendBtn');
  let composerWrap = composer.closest('.composer-wrap'), composerCount = $('#composerCount'), composerError = $('#composerError');
  let railToggle = $('#railToggle'), railGhost = $('#railGhost'), scrim = $('#scrim') ,railClose = $('#railClose');
  let themeSwitch = $('#themeSwitch'), modelTrigger = $('#modelTrigger'), modelMenu = $('#modelMenu');
  let themeBtn = $('#themeBtn'), iconSun = $('#iconSun'), iconMoon = $('#iconMoon');
  let historySearch = $('#historySearch'), histEmpty = $('#histEmpty'), histGroups = $('#histGroups');
  let attachBtn = $('#attachBtn'), attachMenu = $('#attachMenu'), attachChip = $('#attachChip');
  let attachChipName = $('#attachChipName'), attachChipRemove = $('#attachChipRemove');
  let settingsBtn = $('#settingsBtn'), settingsModal = $('#settingsModal'), settingsClose = $('#settingsClose');
  let knowledgeBtn = $('#knowledgeBtn'), knowledgeModal = $('#knowledgeModal'), knowledgeClose = $('#knowledgeClose');
  let mapsBtn = $('#mapsBtn'), mapsModal = $('#mapsModal'), mapsClose = $('#mapsClose');
  let mapsLastFocus = null, mapsTimer = null, mapsViewer = null, mapsLibPromise = null;
  let mapsUploadJob = null;
  let mapsState = { maps: [], presets: [], jobs: [], uploads: [], info: {}, enabled: true, loaded: false, tab: 'library' };
  let typewriterSwitch = $('#typewriterSwitch');
  let ESC = function (s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); };

  /* rail (retrátil à direita)   */
  function applyRail(state) {
    shell.dataset.rail = state;
    try { localStorage.setItem('drix-rail', state); } catch (e) { }
  }
  function toggleRail() { applyRail(shell.dataset.rail === 'open' ? 'closed' : 'open'); }
  railToggle.addEventListener('click', toggleRail);
  railGhost.addEventListener('click', toggleRail);
  railClose.addEventListener('click', function () { applyRail('closed')});
  scrim.addEventListener('click', function () { applyRail('closed'); });
  let savedRail = null;
  try { savedRail = localStorage.getItem('drix-rail'); } catch (e) { }
  applyRail(savedRail || (window.innerWidth <= 920 ? 'closed' : 'open'));

  /*  tema   */
  function applyTheme(mode) {
    document.documentElement.dataset.theme = mode;
    themeSwitch.checked = (mode === 'dark');
    iconSun.hidden = (mode !== 'light');
    iconMoon.hidden = (mode !== 'dark');
    try { localStorage.setItem('drix-theme', mode); } catch (e) { }
  }
  themeSwitch.addEventListener('change', function () { applyTheme(themeSwitch.checked ? 'dark' : 'light'); });
  themeBtn.addEventListener('click', function () {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  let savedTheme = null;
  try { savedTheme = localStorage.getItem('drix-theme'); } catch (e) { }
  applyTheme(savedTheme || 'dark');

  /*  menu flutuante de anexo   */
  function closeAttach() { attachMenu.hidden = true; }
  attachBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    attachMenu.hidden = !attachMenu.hidden;
  });
  attachMenu.querySelectorAll('.attach-item').forEach(function (item) {
    item.addEventListener('click', function () {
      let name = item.dataset.file;
      attachChipName.textContent = name || 'Arquivo da nuvem';
      attachChip.hidden = false;
      closeAttach();
      composer.focus();
    });
  });
  attachChipRemove.addEventListener('click', function () { attachChip.hidden = true; });

  /*  modal de configurações  */
  let lastFocus = null;
  function openModal() {
    lastFocus = document.activeElement;
    if (!mapsModal.hidden) closeMapsModal();
    settingsModal.hidden = false;
    settingsClose.focus();
    loadSettingsPanel();
    activateSettingsTab(currentTab);
  }
  function closeModal() { settingsModal.hidden = true; stopDownloadPolling(); if (lastFocus) lastFocus.focus(); }
  settingsBtn.addEventListener('click', openModal);
  settingsClose.addEventListener('click', closeModal);
  settingsModal.addEventListener('click', function (e) {
    if (e.target === settingsModal) closeModal();
  });

  /*  painel de configurações  */
  let currentTab = 'general';
  let settingsLoading = false;
  let settingsBusy = false;
  let settingsReady = false;
  let settingsBaseline = {};
  let providerCatalog = [];
  let engineInfo = { host: '127.0.0.1', port: 11434 };
  let downloadTimer = null;

  function setSettingsStatus(message, kind) {
    let el = $('#settingsStatus');
    if (!el) return;
    el.textContent = message || '';
    el.classList.remove('ok', 'err');
    if (kind) el.classList.add(kind);
  }

  function readResponse(res) {
    return res.json().catch(function () { return {}; }).then(function (data) {
      if (!res.ok) {
        if (data && data.errors) {
          let first = Object.keys(data.errors)[0];
          throw new Error((data.detail || 'Valores inválidos') + ': ' + first + ' — ' + data.errors[first]);
        }
        throw new Error((data && data.detail) || ('HTTP ' + res.status));
      }
      return data || {};
    });
  }

  function activateSettingsTab(name) {
    currentTab = name || 'general';
    document.querySelectorAll('#settingsTabs .settings-tab').forEach(function (tab) {
      let on = tab.dataset.tab === currentTab;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.settings-section').forEach(function (section) {
      section.hidden = section.dataset.section !== currentTab;
    });
    if (currentTab !== 'downloads') stopDownloadPolling();
    if (currentTab === 'engine') loadEngineStatus();
    if (currentTab === 'memory') loadMemoryStatus();
    if (currentTab === 'tools') loadToolsPanel();
    if (currentTab === 'downloads') loadDownloadsPanel();
    if (currentTab === 'knowledge') loadKnowledgePanel(true);
    if (currentTab === 'maps') { loadPermissionsPanel(); loadMapsSettingsInfo(); }
    if (currentTab === 'system') { loadSystemStatus(); loadLogs(); }
    if (currentTab === 'model') loadModelsPanel();
  }
  document.querySelectorAll('#settingsTabs .settings-tab').forEach(function (tab) {
    tab.addEventListener('click', function () { activateSettingsTab(tab.dataset.tab); });
  });

  function applySettingField(el, value) {
    if (!el) return;
    if (el.dataset.list === 'lines') {
      el.value = Array.isArray(value) ? value.join('\n') : (value == null ? '' : String(value));
      return;
    }
    if (el.type === 'checkbox') { el.checked = !!value; return; }
    if (el.tagName === 'SELECT') {
      let text = value == null ? '' : String(value);
      let exists = false;
      for (let i = 0; i < el.options.length; i++) {
        if (el.options[i].value === text) { exists = true; break; }
      }
      if (!exists && text) {
        let opt = document.createElement('option');
        opt.value = text;
        opt.textContent = text;
        el.appendChild(opt);
      }
      el.value = text;
      return;
    }
    el.value = value == null ? '' : String(value);
  }

  function readSettingField(el) {
    if (el.dataset.list === 'lines') {
      return el.value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    }
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'number') {
      let raw = el.value.trim();
      if (raw === '') return null;
      return Number(raw);
    }
    return el.value;
  }

  function comparableSetting(value) {
    if (Array.isArray(value)) return JSON.stringify(value.map(function (v) { return String(v); }));
    if (value === null || value === undefined) return '';
    return String(value);
  }

  function collectSettings() {    let payload = {};
    document.querySelectorAll('[data-key]').forEach(function (el) {
      let key = el.dataset.key;
      if (!key) return;
      let value = readSettingField(el);
      if (value === null) return;
      payload[key] = value;
    });
    document.querySelectorAll('[data-tool-permission]').forEach(function (el) {
      payload['tools.permissions.' + el.dataset.toolPermission] = el.value;
    });
    return payload;
  }

  function providerField(name) {
    return document.querySelector('[data-provider="' + name + '"]');
  }

  function loadSettingsPanel() {
    if (settingsLoading) return;
    settingsLoading = true;
    settingsReady = false;
    setSettingsStatus('Carregando configurações…');
    api('/settings')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        engineInfo = data.engine || engineInfo;
        let values = data.settings || {};
        document.querySelectorAll('[data-key]').forEach(function (el) {
          let key = el.dataset.key;
          if (!key) return;
          if (Object.prototype.hasOwnProperty.call(values, key)) {
            applySettingField(el, values[key]);
          }
        });
        settingsBaseline = JSON.parse(JSON.stringify(values));
        return Promise.all([loadProvidersPanel(), loadModelsPanel()]);
      })
      .then(function () {
        settingsReady = true;
        setSettingsStatus('Configurações carregadas.');
        if (currentTab === 'engine') loadEngineStatus();
        if (currentTab === 'memory') loadMemoryStatus();
        if (currentTab === 'tools') loadToolsPanel();
        if (currentTab === 'system') { loadSystemStatus(); loadLogs(); }
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Não foi possível carregar as configurações.', 'err');
      })
      .then(function () { settingsLoading = false; });
  }

  function loadProvidersPanel() {
    return api('/providers')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        providerCatalog = data.catalog || [];
        let current = data.current || {};
        let select = $('#set-provider');
        select.innerHTML = '';
        providerCatalog.forEach(function (p) {
          let opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.label || p.id;
          select.appendChild(opt);
        });
        let hasCurrent = providerCatalog.some(function (p) { return p.id === current.provider; });
        if (current.provider && !hasCurrent) {
          let opt = document.createElement('option');
          opt.value = current.provider;
          opt.textContent = current.provider;
          select.appendChild(opt);
        }
        select.value = current.provider || 'local';

        applySettingField(providerField('model'), current.model || '');
        applySettingField(providerField('base_url'), current.base_url || '');
        applySettingField(providerField('temperature'), current.temperature);
        applySettingField(providerField('max_tokens'), current.max_tokens);
        applySettingField(providerField('timeout'), current.timeout);
        applySettingField(providerField('keep_alive'), current.keep_alive);
        let fallback = providerField('fallback_local');
        if (fallback) fallback.checked = !!current.fallback_local;

        let label = current.provider || 'local';
        providerCatalog.forEach(function (p) {
          if (p.id === current.provider) label = p.label || p.id;
        });
        $('#providerCurrent').textContent = label + (current.model ? ' · ' + current.model : '');
        let badge = $('#providerBadge');
        badge.classList.remove('ok', 'off');
        if (current.provider === 'local') {
          badge.textContent = 'Local';
          badge.classList.add('ok');
        } else if (current.has_key) {
          badge.textContent = 'Chave salva';
          badge.classList.add('ok');
        } else {
          badge.textContent = 'Sem chave';
          badge.classList.add('off');
        }
        $('#apiKeyHint').textContent = current.has_key
          ? 'Chave salva: ' + (current.key_hint || '••••') + ' · criptografia: ' + (data.encryption || 'local')
          : 'Nenhuma chave salva para este provedor.';
      })
      .catch(function (e) {
        $('#providerCurrent').textContent = 'Falha ao carregar provedores.';
        setSettingsStatus(e && e.message ? e.message : 'Falha ao carregar provedores.', 'err');
      });
  }

  function loadModelsPanel() {
    return api('/models')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let select = $('#set-local-model');
        let selected = data.selected || '';
        select.innerHTML = '';
        (data.models || []).forEach(function (name) {
          let opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          select.appendChild(opt);
        });
        if (selected && (data.models || []).indexOf(selected) === -1) {
          let opt = document.createElement('option');
          opt.value = selected;
          opt.textContent = selected;
          select.appendChild(opt);
        }
        select.value = selected;
      })
      .catch(function () { });
  }

  function loadEngineStatus() {
    return api('/engine')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let badge = $('#engineBadge');
        badge.classList.remove('ok', 'off');
        if (data.running) {
          badge.textContent = 'ativo';
          badge.classList.add('ok');
        } else {
          badge.textContent = 'parado';
          badge.classList.add('off');
        }
        $('#engineAddr').textContent = (engineInfo.host || '127.0.0.1') + ':' + (engineInfo.port || 11434);
      })
      .catch(function () {
        $('#engineBadge').textContent = 'indisponível';
      });
  }

  function loadMemoryStatus() {
    return api('/memory/consolidation')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let entries = data.entries || {};
        let state = data.state || {};
        let conf = data.config || {};
        $('#memoryCounts').textContent =
          (entries.facts || 0) + ' fatos · ' +
          (entries.raw || 0) + ' memórias brutas · ' +
          (entries.total || 0) + ' total';
        let badge = $('#memoryStatus');
        badge.classList.remove('ok', 'off');
        if (conf.enabled) {
          badge.textContent = 'ativa';
          badge.classList.add('ok');
        } else {
          badge.textContent = 'desligada';
          badge.classList.add('off');
        }
        badge.title = 'Último estado: ' + (state.last_status || 'nunca') +
          (state.last_error ? ' — ' + state.last_error : '');
      })
      .catch(function (e) {
        $('#memoryCounts').textContent = 'Memória indisponível no momento.';
        setSettingsStatus(e && e.message ? e.message : 'Falha ao consultar memória.', 'err');
      });
  }

  function loadToolsPanel() {
    return api('/tools')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let wrap = $('#toolsPermissions');
        wrap.innerHTML = '';
        let list = data.tools || [];
        if (!list.length) {
          wrap.innerHTML = '<div class="settings-tool"><p class="settings-tool-desc">Nenhuma ferramenta disponível.</p></div>';
          return;
        }
        list.forEach(function (tool) {
          let row = document.createElement('div');
          row.className = 'settings-tool';
          let info = document.createElement('div');
          info.className = 'settings-tool-info';
          let name = document.createElement('p');
          name.className = 'settings-tool-name';
          name.textContent = tool.name;
          let desc = document.createElement('p');
          desc.className = 'settings-tool-desc';
          desc.textContent = tool.description || '';
          desc.title = tool.description || '';
          info.appendChild(name);
          info.appendChild(desc);
          let select = document.createElement('select');
          [['allow', 'Permitir'], ['ask', 'Perguntar'], ['deny', 'Negar']].forEach(function (pair) {
            let opt = document.createElement('option');
            opt.value = pair[0];
            opt.textContent = pair[1];
            select.appendChild(opt);
          });
          select.value = tool.permission || 'allow';
          select.dataset.toolPermission = tool.name;
          row.appendChild(info);
          row.appendChild(select);
          wrap.appendChild(row);
        });
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao carregar ferramentas.', 'err');
      });
  }

  function stopDownloadPolling() {
    if (downloadTimer) { clearInterval(downloadTimer); downloadTimer = null; }
  }

  function formatBytesJs(value) {
    let n = Number(value || 0);
    if (!n || !isFinite(n)) return '';
    let units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return n.toFixed(1) + ' ' + units[i];
  }

  function formatEtaJs(value) {
    let seconds = Number(value);
    if (!isFinite(seconds) || seconds < 0) return '';
    if (seconds < 60) return 'faltam ' + Math.round(seconds) + 's';
    let minutes = Math.floor(seconds / 60);
    if (minutes < 60) return 'faltam ' + minutes + 'min';
    return 'faltam ' + Math.floor(minutes / 60) + 'h';
  }

  function downloadRow(job) {
    let row = document.createElement('div');
    row.className = 'download-row';

    let head = document.createElement('div');
    head.className = 'download-head';
    let title = document.createElement('p');
    title.className = 'download-title';
    title.textContent = job.title || job.filename || job.url;
    title.title = job.filepath || job.url;
    let badge = document.createElement('span');
    badge.className = 'download-badge ' + (job.status || '');
    badge.textContent = ({
      queued: 'na fila', downloading: 'baixando', processing: 'processando',
      cancelling: 'cancelando', done: 'concluído', error: 'falhou', cancelled: 'cancelado'
    })[job.status] || job.status || '—';
    head.appendChild(title);
    head.appendChild(badge);
    row.appendChild(head);

    if (job.status === 'downloading' || job.status === 'processing') {
      let bar = document.createElement('div');
      bar.className = 'download-bar';
      let fill = document.createElement('div');
      fill.className = 'download-fill';
      fill.style.width = Math.max(2, Math.min(100, Number(job.progress) || 0)) + '%';
      bar.appendChild(fill);
      row.appendChild(bar);
    }

    let meta = document.createElement('p');
    meta.className = 'download-meta';
    let bits = [];
    if (job.status === 'downloading') {
      bits.push((Number(job.progress) || 0).toFixed(0) + '%');
      if (job.speed) bits.push(formatBytesJs(job.speed) + '/s');
      bits.push(formatEtaJs(job.eta));
    }
    if (job.status === 'done') bits.push(formatBytesJs(job.bytes));
    if (job.status === 'error') bits.push(job.error || 'erro');
    if (job.status === 'cancelled') bits.push(job.error || 'cancelado');
    if (job.filepath) bits.push(job.filepath);
    meta.textContent = bits.filter(Boolean).join(' · ');
    row.appendChild(meta);

    if (['queued', 'downloading', 'processing', 'cancelling'].indexOf(job.status) !== -1) {
      let cancel = document.createElement('button');
      cancel.className = 'btn btn-ghost download-cancel';
      cancel.type = 'button';
      cancel.textContent = 'Cancelar';
      cancel.addEventListener('click', function () {
        cancel.disabled = true;
        api('/downloads/' + encodeURIComponent(job.id), { method: 'DELETE' })
          .then(function (r) { return readResponse(r); })
          .then(loadDownloadsPanel)
          .catch(function (e) {
            setSettingsStatus(e && e.message ? e.message : 'Falha ao cancelar.', 'err');
            cancel.disabled = false;
          });
      });
      row.appendChild(cancel);
    }
    return row;
  }

  function loadDownloadsPanel() {
    return api('/downloads')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let box = $('#downloadList');
        if (!box) return;
        let jobs = data.jobs || [];
        box.innerHTML = '';
        if (!jobs.length) {
          let empty = document.createElement('p');
          empty.className = 'settings-note';
          empty.textContent = 'Nenhum download ainda.';
          box.appendChild(empty);
        } else {
          jobs.forEach(function (job) { box.appendChild(downloadRow(job)); });
        }
        let info = data.info || {};
        let engine = $('#dlEngineInfo');
        if (engine) {
          engine.textContent =
            (info.engine || 'yt-dlp') +
            (info.ffmpeg ? ' · ffmpeg pronto' : ' · sem ffmpeg (qualidade limitada)') +
            ' · pasta: ' + (info.dir || '—') +
            ' · ativos: ' + (info.active || 0);
        }
        if (currentTab === 'downloads' && !settingsModal.hidden && !downloadTimer) {
          downloadTimer = setInterval(loadDownloadsPanel, 2000);
        }
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao carregar downloads.', 'err');
      });
  }

  function loadSystemStatus() {
    return api('/status')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let hw = data.hardware || {};
        let rows = [
          ['Versão', data.version || '—'],
          ['Modo', data.mode || '—'],
          ['Motor', data.engine_running ? 'ativo' : 'parado'],
          ['RAM', hw.ram_gb ? hw.ram_gb + ' GB' : '—'],
          ['Núcleos', hw.cpu_cores || '—'],
          ['Modelo', hw.selected_model || '—']
        ];
        let box = $('#systemInfo');
        box.innerHTML = '';
        rows.forEach(function (row) {
          let item = document.createElement('div');
          item.className = 'settings-info-item';
          let label = document.createElement('span');
          label.textContent = row[0];
          let value = document.createElement('strong');
          value.textContent = row[1];
          item.appendChild(label);
          item.appendChild(value);
          box.appendChild(item);
        });
      })
      .catch(function () {
        $('#systemInfo').textContent = 'Estado indisponível.';
      });
  }

  function loadLogs() {
    return api('/logs?lines=120')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let lines = data.logs || [];
        let box = $('#systemLogs');
        box.textContent = lines.length ? lines.join('\n') : 'Sem logs.';
        box.scrollTop = box.scrollHeight;
      })
      .catch(function () {
        $('#systemLogs').textContent = 'Não foi possível carregar os logs.';
      });
  }

  function saveSettingsPanel() {
    if (settingsBusy) return;
    if (!settingsReady) {
      setSettingsStatus('Aguarde o carregamento das configurações antes de salvar.', 'err');
      return;
    }
    settingsBusy = true;
    let saveBtn = $('#settingsSave');
    saveBtn.disabled = true;
    setSettingsStatus('Salvando…');

    let allSettings = collectSettings();
    let payload = {};
    Object.keys(allSettings).forEach(function (key) {
      let before = settingsBaseline[key];
      let after = allSettings[key];
      if (comparableSetting(before) !== comparableSetting(after)) payload[key] = after;
    });
    let provider = $('#set-provider').value;
    let providerPayload = { provider: provider };
    ['model', 'base_url', 'temperature', 'max_tokens', 'timeout', 'keep_alive'].forEach(function (name) {
      let el = providerField(name);
      if (!el) return;
      let raw = String(el.value == null ? '' : el.value).trim();
      if (name === 'base_url' && provider === 'local') {
        let defaultUrl = 'http://' + (engineInfo.host || '127.0.0.1') + ':' + (engineInfo.port || 11434);
        if (raw === defaultUrl) raw = '';
      }
      if (raw === '') {
        if (name === 'model' || name === 'base_url') providerPayload[name] = '';
        return;
      }
      if (name === 'temperature' || name === 'max_tokens' || name === 'timeout') {
        providerPayload[name] = Number(raw);
      } else {
        providerPayload[name] = raw;
      }
    });
    let fallback = providerField('fallback_local');
    providerPayload.fallback_local = !!(fallback && fallback.checked);
    let apiKey = $('#set-api-key').value.trim();
    if (apiKey) providerPayload.api_key = apiKey;

    let settingsRequest = Object.keys(payload).length
      ? api('/settings', { method: 'POST', body: JSON.stringify({ settings: payload }) })
      : Promise.resolve(null);

    settingsRequest
      .then(function (r) { return r ? readResponse(r) : null; })
      .then(function () {
        return api('/providers/config', { method: 'POST', body: JSON.stringify(providerPayload) });
      })
      .then(function (r) { return readResponse(r); })
      .then(function () {
        $('#set-api-key').value = '';
        Object.keys(allSettings).forEach(function (key) { settingsBaseline[key] = allSettings[key]; });
        let needsRestart = Object.keys(payload).some(function (key) {
          return ['engine.', 'history.', 'brain.', 'web.', 'mcp.', 'local_resources.'].some(function (prefix) {
            return key.indexOf(prefix) === 0;
          });
        });
        setSettingsStatus(
          needsRestart
            ? 'Salvo. Algumas mudanças valem no próximo reinício do serviço.'
            : 'Salvo com sucesso.',
          'ok'
        );
        loadProvidersPanel();
        loadEngineStatus();
        loadKnowledgePanel(true);
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao salvar.', 'err');
      })
      .then(function () {
        settingsBusy = false;
        saveBtn.disabled = false;
      });
  }

  function engineAction(path, label, body) {
    setSettingsStatus(label + '…');
    let opts = { method: 'POST' };
    if (body) opts.body = JSON.stringify(body);
    return api(path, opts)
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        if (data && data.status === 'failed') throw new Error('O motor não iniciou.');
        if (data && data.preloaded === false) throw new Error('O modelo não foi pré-carregado.');
        setSettingsStatus(label + ': concluído.', 'ok');
        setTimeout(function () { loadEngineStatus(); loadModelsPanel(); }, 900);
      })
      .catch(function (e) {
        setSettingsStatus(label + ': ' + (e && e.message ? e.message : 'falhou'), 'err');
      });
  }

  /* botões do painel */
  $('#settingsSave').addEventListener('click', saveSettingsPanel);
  $('#settingsRefresh').addEventListener('click', function () {
    loadSettingsPanel();
    activateSettingsTab(currentTab);
  });
  $('#providerTest').addEventListener('click', function () {
    setSettingsStatus('Testando conexão…');
    api('/providers/test', { method: 'POST' })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        if (data.ok === false) throw new Error(data.error || 'sem resposta');
        setSettingsStatus('Conexão OK · ' + (data.model || '') + ' · ' + (data.latency_ms || 0) + ' ms', 'ok');
      })
      .catch(function (e) {
        setSettingsStatus('Falha na conexão: ' + (e && e.message ? e.message : 'erro'), 'err');
      });
  });
  $('#providerKeyDelete').addEventListener('click', function () {
    let provider = $('#set-provider').value;
    if (!provider) return;
    if (!confirm('Remover a chave de API salva para "' + provider + '"?')) return;
    api('/providers/' + encodeURIComponent(provider) + '/key', { method: 'DELETE' })
      .then(function (r) { return readResponse(r); })
      .then(function () {
        setSettingsStatus('Chave removida.', 'ok');
        loadProvidersPanel();
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao remover a chave.', 'err');
      });
  });
  $('#localModelApply').addEventListener('click', function () {
    let name = $('#set-local-model').value;
    if (!name) return;
    setSettingsStatus('Trocando modelo para ' + name + '…');
    api('/models/select', { method: 'POST', body: JSON.stringify({ name: name }) })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        if (data && data.warming === false) {
          setSettingsStatus(
            (data && data.warning) ||
            ('Modelo ' + name + ' selecionado. Ele será carregado na primeira mensagem.'),
            'ok'
          );
        } else {
          setSettingsStatus('Modelo ' + name + ' selecionado. Aquecendo com o histórico…', 'ok');
        }
        loadModelsPanel();
        loadProvidersPanel();
        setTimeout(loadEngineStatus, 800);
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao trocar o modelo.', 'err');
      });
  });
  $('#engineStart').addEventListener('click', function () { engineAction('/engine/start', 'Iniciando motor'); });
  $('#engineStop').addEventListener('click', function () { engineAction('/engine/stop', 'Parando motor'); });
  $('#engineRestart').addEventListener('click', function () { engineAction('/engine/restart', 'Reiniciando motor'); });
  $('#enginePreload').addEventListener('click', function () {
    let name = $('#set-local-model').value;
    if (!name) { setSettingsStatus('Escolha um modelo local primeiro.', 'err'); return; }
    engineAction('/models/preload', 'Pré-carregando ' + name, { name: name });
  });
  $('#memoryRefresh').addEventListener('click', loadMemoryStatus);
  $('#memoryRun').addEventListener('click', function () {
    setSettingsStatus('Solicitando consolidação…');
    api('/memory/consolidation/run', { method: 'POST', body: JSON.stringify({ force: true }) })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        if (data.started) {
          setSettingsStatus('Consolidação iniciada em segundo plano.', 'ok');
          setTimeout(loadMemoryStatus, 3500);
        } else {
          let reasons = {
            chat_active: 'Há um chat ativo. Tente novamente quando estiver ocioso.',
            disabled: 'A consolidação está desligada. Ative e salve antes.',
            stopping: 'O serviço está parando.'
          };
          setSettingsStatus(reasons[data.reason] || 'Não foi possível iniciar agora.', 'err');
        }
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao iniciar a consolidação.', 'err');
      });
  });
  $('#memoryReset').addEventListener('click', function () {
    if (!confirm('Limpar todas as memórias da Drix? Esta ação não pode ser desfeita.')) return;
    setSettingsStatus('Limpando memória…');
    api('/memory/reset', { method: 'POST' })
      .then(function (r) { return readResponse(r); })
      .then(function () {
        setSettingsStatus('Memória limpa.', 'ok');
        loadMemoryStatus();
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao limpar a memória.', 'err');
      });
  });
  $('#syncNow').addEventListener('click', function () {
    setSettingsStatus('Sincronizando modelos e configuração…');
    api('/sync', { method: 'POST' })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let count = (data.changes || []).length;
        setSettingsStatus(count ? count + ' mudança(s) sincronizada(s).' : 'Tudo já estava sincronizado.', 'ok');
        loadModelsPanel();
        loadProvidersPanel();
        loadSystemStatus();
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao sincronizar.', 'err');
      });
  });
  $('#logsRefresh').addEventListener('click', loadLogs);

  /* downloads */
  $('#dlStart').addEventListener('click', function () {
    let url = $('#dlUrl').value.trim();
    if (!url) { setSettingsStatus('Cole um link para baixar.', 'err'); return; }
    let payload = { url: url, audio_only: $('#dlAudioOnly').checked };
    let quality = $('#dlQuality').value;
    if (quality) payload.quality = Number(quality);
    setSettingsStatus('Iniciando download…');
    api('/downloads', { method: 'POST', body: JSON.stringify(payload) })
      .then(function (r) { return readResponse(r); })
      .then(function (job) {
        $('#dlUrl').value = '';
        setSettingsStatus('Download iniciado: ' + (job.title || job.url), 'ok');
        loadDownloadsPanel();
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao iniciar o download.', 'err');
      });
  });
  $('#dlUrl').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); $('#dlStart').click(); }
  });
  $('#dlRefresh').addEventListener('click', loadDownloadsPanel);
  $('#dlClearDone').addEventListener('click', function () {
    api('/downloads', { method: 'DELETE' })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        setSettingsStatus((data.removed || 0) + ' item(ns) removido(s).', 'ok');
        loadDownloadsPanel();
      })
      .catch(function (e) {
        setSettingsStatus(e && e.message ? e.message : 'Falha ao limpar a lista.', 'err');
      });
  });

  /*  base de conhecimento  */
  let knowledgeTimer = null;
  let knowledgeBusy = false;
  let knowledgeDocs = [];
  let knowledgeInfo = {};
  let knowledgeLastFocus = null;

  function stopKnowledgePolling() {
    if (knowledgeTimer) { clearInterval(knowledgeTimer); knowledgeTimer = null; }
  }

  function setKnowledgeStatus(message, kind) {
    let el = $('#knowledgeStatus');
    if (!el) return;
    el.textContent = message || '';
    el.classList.remove('ok', 'err');
    if (kind) el.classList.add(kind);
    let footer = $('#knowledgeFooter');
    if (footer) footer.textContent = message || '';
  }

  function knowledgeMeta(doc) {
    let bits = [];
    let ext = String(doc.ext || '').replace('.', '').toUpperCase();
    if (ext) bits.push(ext);
    if (doc.size) bits.push(formatBytesJs(doc.size));
    if (doc.status === 'ready') bits.push((doc.chunks || 0) + ' trecho(s)');
    if (doc.added_at) {
      let when = String(doc.added_at).replace('T', ' ').slice(0, 16);
      if (when) bits.push(when);
    }
    return bits.join(' · ');
  }

  function knowledgeRow(doc) {
    let row = document.createElement('div');
    row.className = 'knowledge-row';

    let ext = document.createElement('span');
    ext.className = 'knowledge-file';
    ext.textContent = (String(doc.ext || '').replace('.', '') || 'doc').slice(0, 4);
    row.appendChild(ext);

    let info = document.createElement('div');
    info.className = 'knowledge-info';
    let name = document.createElement('p');
    name.className = 'knowledge-name';
    name.textContent = doc.name || 'documento';
    name.title = doc.name || '';
    info.appendChild(name);
    let meta = document.createElement('p');
    meta.className = 'knowledge-meta';
    meta.textContent = knowledgeMeta(doc) || 'aguardando indexação';
    info.appendChild(meta);
    if (doc.error) {
      let err = document.createElement('p');
      err.className = 'knowledge-error';
      err.textContent = doc.error;
      info.appendChild(err);
    }
    row.appendChild(info);

    let state = document.createElement('span');
    state.className = 'knowledge-state ' + (doc.status || '');
    state.textContent = ({
      queued: 'na fila', indexing: 'indexando', ready: 'pronto', error: 'erro'
    })[doc.status] || doc.status || '—';
    row.appendChild(state);

    let actions = document.createElement('div');
    actions.className = 'knowledge-actions-row';

    let reindex = document.createElement('button');
    reindex.className = 'knowledge-act';
    reindex.type = 'button';
    reindex.title = 'Reindexar documento';
    reindex.setAttribute('aria-label', 'Reindexar ' + (doc.name || 'documento'));
    reindex.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>';
    reindex.disabled = knowledgeBusy || doc.status === 'queued' || doc.status === 'indexing';
    reindex.addEventListener('click', function () {
      reindex.disabled = true;
      setKnowledgeStatus('Reenfileirando ' + (doc.name || 'documento') + '…');
      api('/knowledge/reindex', { method: 'POST', body: JSON.stringify({ id: doc.id }) })
        .then(function (r) { return readResponse(r); })
        .then(function () { setKnowledgeStatus('Reindexação agendada.', 'ok'); loadKnowledgePanel(true); })
        .catch(function (e) {
          setKnowledgeStatus(e && e.message ? e.message : 'Falha ao reindexar.', 'err');
          reindex.disabled = false;
        });
    });
    actions.appendChild(reindex);

    let del = document.createElement('button');
    del.className = 'knowledge-act danger';
    del.type = 'button';
    del.title = 'Excluir documento';
    del.setAttribute('aria-label', 'Excluir ' + (doc.name || 'documento'));
    del.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"/><path d="M10 11v6M14 11v6"/></svg>';
    del.disabled = knowledgeBusy;
    del.addEventListener('click', function () {
      if (!confirm('Excluir "' + (doc.name || 'documento') + '" da base de conhecimento?')) return;
      del.disabled = true;
      setKnowledgeStatus('Excluindo ' + (doc.name || 'documento') + '…');
      api('/knowledge/' + encodeURIComponent(doc.id), { method: 'DELETE' })
        .then(function (r) { return readResponse(r); })
        .then(function () {
          setKnowledgeStatus('Documento excluído.', 'ok');
          $('#knowledgeResults').hidden = true;
          loadKnowledgePanel(true);
        })
        .catch(function (e) {
          setKnowledgeStatus(e && e.message ? e.message : 'Falha ao excluir.', 'err');
          del.disabled = false;
        });
    });
    actions.appendChild(del);
    row.appendChild(actions);
    return row;
  }

  function renderKnowledgeStats() {
    let info = knowledgeInfo || {};
    let stats = $('#knowledgeStats');
    if (stats) {
      let parts = [
        (info.documents || 0) + ' documento(s)',
        (info.ready || 0) + ' pronto(s)',
        (info.chunks || 0) + ' trecho(s)'
      ];
      if (info.pending) parts.push(info.pending + ' indexando');
      parts.push(info.available ? 'busca local ativa' : 'busca indisponível');
      stats.textContent = parts.join(' · ');
    }
    let badge = $('#knowledgeBadge');
    if (badge) {
      let ready = Number(info.ready) || 0;
      badge.hidden = ready <= 0;
      badge.textContent = ready > 99 ? '99+' : String(ready);
    }
    let cfg = $('#knowledgeSettingsInfo');
    if (cfg) {
      let readers = '';
      if (info.pdf === false) readers += ' PDF';
      if (info.docx === false) readers += ' DOCX';
      cfg.textContent = 'Pasta: ' + (info.dir || '—') +
        ' · Índice: ' + (info.db || '—') +
        ' · ' + (info.documents || 0) + ' documento(s)' +
        ((info.pending || 0) ? ' · ' + info.pending + ' indexando' : '') +
        (readers ? ' · leitores ausentes:' + readers : '');
    }
  }

  function renderKnowledgeList() {
    let box = $('#knowledgeList');
    if (!box) return;
    box.innerHTML = '';
    if (!knowledgeDocs.length) {
      let empty = document.createElement('p');
      empty.className = 'settings-note';
      empty.textContent = knowledgeInfo && knowledgeInfo.enabled === false
        ? 'A base está desligada nas configurações.'
        : 'Nenhum documento na base ainda. Envie um arquivo acima.';
      box.appendChild(empty);
      return;
    }
    knowledgeDocs.forEach(function (doc) { box.appendChild(knowledgeRow(doc)); });
  }

  function scheduleKnowledgePolling() {
    let pending = knowledgeDocs.some(function (doc) {
      return doc.status === 'queued' || doc.status === 'indexing';
    });
    if (pending && !knowledgeModal.hidden && !knowledgeTimer) {
      knowledgeTimer = setInterval(function () { loadKnowledgePanel(true); }, 2000);
    } else if (!pending) {
      stopKnowledgePolling();
    }
  }

  function loadKnowledgePanel(silent) {
    if (!silent) setKnowledgeStatus('Carregando base de conhecimento…');
    return api('/knowledge')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        knowledgeDocs = data.documents || [];
        knowledgeInfo = data.info || {};
        renderKnowledgeStats();
        renderKnowledgeList();
        scheduleKnowledgePolling();
        if (!silent) setKnowledgeStatus('');
      })
      .catch(function (e) {
        if (!silent) setKnowledgeStatus(e && e.message ? e.message : 'Falha ao carregar a base.', 'err');
      });
  }

  function openKnowledgeModal() {
    knowledgeLastFocus = document.activeElement;
    if (!mapsModal.hidden) closeMapsModal();
    if (!settingsModal.hidden) {
      settingsModal.hidden = true;
      stopDownloadPolling();
    }
    knowledgeModal.hidden = false;
    knowledgeClose.focus();
    loadKnowledgePanel();
  }

  function closeKnowledgeModal() {
    if (knowledgeModal.hidden) return;
    knowledgeModal.hidden = true;
    stopKnowledgePolling();
    if (knowledgeLastFocus && knowledgeLastFocus.focus) knowledgeLastFocus.focus();
  }

  function uploadKnowledgeFiles(fileList) {
    let files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    if (knowledgeBusy) { setKnowledgeStatus('Aguarde o envio atual terminar.', 'err'); return; }
    knowledgeBusy = true;
    let ok = 0;
    let dup = 0;
    let errors = [];
    let chain = Promise.resolve();
    files.forEach(function (file) {
      chain = chain.then(function () {
        setKnowledgeStatus('Enviando ' + file.name + '…');
        let form = new FormData();
        form.append('file', file, file.name);
        return api('/knowledge/upload', { method: 'POST', body: form })
          .then(function (r) { return readResponse(r); })
          .then(function (doc) {
            if (doc && doc.duplicate) dup += 1; else ok += 1;
          })
          .catch(function (e) {
            errors.push(file.name + ': ' + (e && e.message ? e.message : 'falhou'));
          });
      });
    });
    chain.then(function () {
      knowledgeBusy = false;
      let parts = [];
      if (ok) parts.push(ok + ' enviado(s)');
      if (dup) parts.push(dup + ' já estava(m) na base');
      if (errors.length) parts.push(errors.length + ' falhou(aram)');
      let message = parts.join(' · ') || 'Nenhum arquivo enviado.';
      if (errors.length) message += ' — ' + errors[0];
      setKnowledgeStatus(message, errors.length ? 'err' : 'ok');
      loadKnowledgePanel(true);
    });
  }

  function renderKnowledgeResults(query, results) {
    let box = $('#knowledgeResults');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = '';
    let head = document.createElement('p');
    head.className = 'settings-note';
    head.style.margin = '0';
    head.textContent = results.length
      ? results.length + ' trecho(s) para "' + query + '"'
      : 'Nenhum trecho encontrado para "' + query + '". Verifique se os documentos já foram indexados.';
    box.appendChild(head);
    results.forEach(function (item) {
      let card = document.createElement('div');
      card.className = 'knowledge-result';
      let top = document.createElement('div');
      top.className = 'knowledge-result-head';
      let source = document.createElement('p');
      source.className = 'knowledge-source';
      source.textContent = item.source || 'documento';
      source.title = item.source || '';
      top.appendChild(source);
      let score = document.createElement('span');
      score.className = 'knowledge-score';
      let similarity = Math.max(0, Math.min(1, 1 - (Number(item.distance) || 0) / 2));
      score.textContent = 'relevância ' + Math.round(similarity * 100) + '%';
      score.title = 'distância: ' + item.distance;
      top.appendChild(score);
      card.appendChild(top);
      let snippet = document.createElement('p');
      snippet.className = 'knowledge-snippet';
      snippet.textContent = item.text || '';
      card.appendChild(snippet);
      box.appendChild(card);
    });
  }

  function runKnowledgeSearch() {
    let query = $('#knowledgeQuery').value.trim();
    if (!query) { $('#knowledgeQuery').focus(); return; }
    let box = $('#knowledgeResults');
    box.hidden = false;
    box.innerHTML = '<p class="settings-note" style="margin:0">Buscando na base…</p>';
    api('/knowledge/search', { method: 'POST', body: JSON.stringify({ query: query }) })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        renderKnowledgeResults(query, data.results || []);
      })
      .catch(function (e) {
        box.innerHTML = '';
        let err = document.createElement('p');
        err.className = 'settings-note';
        err.style.margin = '0';
        err.textContent = e && e.message ? e.message : 'Falha na busca.';
        box.appendChild(err);
      });
  }

  knowledgeBtn.addEventListener('click', openKnowledgeModal);
  knowledgeClose.addEventListener('click', closeKnowledgeModal);
  $('#knowledgeDone').addEventListener('click', closeKnowledgeModal);
  knowledgeModal.addEventListener('click', function (e) {
    if (e.target === knowledgeModal) closeKnowledgeModal();
  });
  $('#knowledgeRefresh').addEventListener('click', function () { loadKnowledgePanel(); });
  $('#knowledgeSearchBtn').addEventListener('click', runKnowledgeSearch);
  $('#knowledgeQuery').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); runKnowledgeSearch(); }
  });
  $('#knowledgeReindexAll').addEventListener('click', function () {
    if (!confirm('Reindexar todos os documentos da base? Isso pode levar alguns minutos.')) return;
    setKnowledgeStatus('Reindexando todos os documentos…');
    api('/knowledge/reindex', { method: 'POST', body: JSON.stringify({}) })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        setKnowledgeStatus((data.queued || 0) + ' documento(s) na fila de indexação.', 'ok');
        loadKnowledgePanel(true);
      })
      .catch(function (e) {
        setKnowledgeStatus(e && e.message ? e.message : 'Falha ao reindexar.', 'err');
      });
  });

  (function () {
    let drop = $('#knowledgeDrop');
    let input = $('#knowledgeFile');
    if (!drop || !input) return;
    drop.addEventListener('click', function () { input.click(); });
    drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    ['dragenter', 'dragover'].forEach(function (name) {
      drop.addEventListener(name, function (e) {
        e.preventDefault();
        drop.classList.add('dragover');
      });
    });
    ['dragleave', 'dragend', 'drop'].forEach(function (name) {
      drop.addEventListener(name, function (e) {
        e.preventDefault();
        drop.classList.remove('dragover');
      });
    });
    drop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files) uploadKnowledgeFiles(e.dataTransfer.files);
    });
    input.addEventListener('change', function () {
      uploadKnowledgeFiles(input.files);
      input.value = '';
    });
  })();

  $('#knowledgeOpenBtn').addEventListener('click', function () {
    settingsModal.hidden = true;
    stopDownloadPolling();
    openKnowledgeModal();
  });
  $('#knowledgeSettingsBtn').addEventListener('click', function () {
    closeKnowledgeModal();
    currentTab = 'knowledge';
    openModal();
  });
  $('#knowledgeSettingsRefresh').addEventListener('click', function () {
    loadKnowledgePanel(true).then(function () { setSettingsStatus('Estado da base atualizado.', 'ok'); });
  });

  /* ─── mapas offline ─────────────────────────────────────────── */

  function mapsFmtBytes(value) {
    let n = Number(value) || 0;
    let units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let index = 0;
    while (n >= 1024 && index < units.length - 1) { n /= 1024; index += 1; }
    return (index === 0 ? Math.round(n) : n.toFixed(1)) + ' ' + units[index];
  }

  function mapsNorm(text) {
    return String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-zA-Z0-9]+/g, ' ').trim().toLowerCase();
  }

  function mapsStatus(text, kind) {
    let el = $('#mapsFooter');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'settings-status' + (kind ? ' ' + kind : '');
  }

  function mapsDownloadStatus(text, kind) {
    let el = $('#mapsDownloadStatus');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'maps-status' + (kind ? ' ' + kind : '');
  }

  function setMapsUploadStatus(text, kind) {
    let el = $('#mapsUploadStatus');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'maps-status' + (kind ? ' ' + kind : '');
  }

  function activateMapsTab(name) {
    mapsState.tab = name || 'library';
    document.querySelectorAll('#mapsTabs .maps-tab').forEach(function (tab) {
      let on = tab.dataset.mapsTab === mapsState.tab;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('[data-maps-section]').forEach(function (section) {
      section.hidden = section.dataset.mapsSection !== mapsState.tab;
    });
  }

  function mapsHasActive() {
    return mapsState.jobs.some(function (job) { return !!job.active; });
  }

  function stopMapsPolling() {
    if (mapsTimer) { clearInterval(mapsTimer); mapsTimer = null; }
  }

  function scheduleMapsPolling() {
    stopMapsPolling();
    if (mapsModal.hidden || !mapsHasActive()) return;
    mapsTimer = setInterval(function () { loadMapsPanel(true); }, 1800);
  }

  function renderMapsStats() {
    let box = $('#mapsStats');
    if (!box) return;
    let info = mapsState.info || {};
    let active = mapsState.jobs.filter(function (job) { return !!job.active; }).length;
    box.innerHTML = '';
    let entries = [
      ['Mapas', String(info.count || 0)],
      ['Tamanho', info.size_label || '0 B'],
      ['Espaço livre', info.free_label || '—'],
    ];
    if (active) entries.push(['Em andamento', String(active)]);
    entries.forEach(function (entry) {
      let span = document.createElement('span');
      span.className = 'maps-stat';
      let strong = document.createElement('strong');
      strong.textContent = entry[1];
      span.appendChild(strong);
      span.appendChild(document.createTextNode(' ' + entry[0]));
      box.appendChild(span);
    });
  }

  function mapItemCard(item) {
    let card = document.createElement('article');
    card.className = 'map-item';
    card.dataset.mapId = item.id;

    let main = document.createElement('div');
    main.className = 'map-item-main';
    let title = document.createElement('div');
    title.className = 'map-item-title';
    let name = document.createElement('strong');
    name.textContent = item.name || 'Mapa';
    title.appendChild(name);
    let zoom = document.createElement('span');
    zoom.className = 'map-zoom';
    zoom.textContent = item.zoom_label || '—';
    title.appendChild(zoom);
    main.appendChild(title);

    let meta = document.createElement('p');
    meta.className = 'map-meta';
    meta.textContent = (item.size_label || '—') + ' · cobertura ' + (item.bounds_label || '—');
    main.appendChild(meta);

    if (item.source_url) {
      let source = document.createElement('p');
      source.className = 'map-source';
      source.textContent = item.source_url;
      source.title = item.source_url;
      main.appendChild(source);
    }
    card.appendChild(main);

    let actions = document.createElement('div');
    actions.className = 'map-actions';
    let open = document.createElement('button');
    open.type = 'button';
    open.className = 'btn settings-save';
    open.textContent = 'Abrir';
    open.addEventListener('click', function () { openMapsViewer(item.id); });
    actions.appendChild(open);
    let del = document.createElement('button');
    del.type = 'button';
    del.className = 'btn btn-secondary map-delete';
    del.textContent = 'Excluir';
    del.addEventListener('click', function () { deleteMap(item.id); });
    actions.appendChild(del);
    card.appendChild(actions);
    return card;
  }

  function renderMapsList() {
    let box = $('#mapsList');
    if (!box) return;
    box.innerHTML = '';
    let filterInput = $('#mapsFilter');
    let filter = mapsNorm(filterInput ? filterInput.value : '');
    let items = mapsState.maps.filter(function (item) {
      if (!filter) return true;
      return mapsNorm(item.name + ' ' + item.id + ' ' + (item.source_url || '')).indexOf(filter) !== -1;
    });
    if (!items.length) {
      let note = document.createElement('p');
      note.className = 'settings-note';
      note.textContent = mapsState.maps.length
        ? 'Nenhum mapa corresponde ao filtro.'
        : 'Nenhum mapa instalado. Use as abas Baixar ou Importar para adicionar.';
      box.appendChild(note);
      return;
    }
    items.forEach(function (item) { box.appendChild(mapItemCard(item)); });
  }

  function renderMapsPresets() {
    let box = $('#mapsPresets');
    if (!box) return;
    box.innerHTML = '';
    if (!mapsState.presets.length) {
      box.innerHTML = '<p class="settings-note">Presets indisponíveis.</p>';
      return;
    }
    mapsState.presets.forEach(function (preset) {
      let card = document.createElement('article');
      card.className = 'maps-preset';
      card.dataset.preset = preset.key;

      let head = document.createElement('div');
      head.className = 'maps-preset-head';
      let name = document.createElement('strong');
      name.textContent = preset.name || preset.key;
      head.appendChild(name);
      if (preset.maxzoom != null) {
        let zoom = document.createElement('span');
        zoom.className = 'map-zoom';
        zoom.textContent = 'z0–' + preset.maxzoom;
        head.appendChild(zoom);
      }
      card.appendChild(head);

      let note = document.createElement('p');
      note.className = 'maps-preset-note';
      note.textContent = preset.note || 'Recorte pronto para uso offline.';
      card.appendChild(note);

      let meta = document.createElement('p');
      meta.className = 'maps-preset-meta';
      let estimate = document.createElement('span');
      estimate.className = 'maps-estimate';
      estimate.textContent = preset.estimate ? '≈ ' + preset.estimate : 'tamanho sob consulta';
      meta.appendChild(estimate);
      card.appendChild(meta);

      let actions = document.createElement('div');
      actions.className = 'maps-preset-actions';
      let measure = document.createElement('button');
      measure.type = 'button';
      measure.className = 'btn btn-secondary';
      measure.textContent = 'Estimar';
      measure.addEventListener('click', function () { estimatePreset(preset, estimate, measure); });
      actions.appendChild(measure);
      let download = document.createElement('button');
      download.type = 'button';
      download.className = 'btn settings-save';
      download.textContent = 'Baixar';
      download.addEventListener('click', function () { startPresetDownload(preset); });
      actions.appendChild(download);
      card.appendChild(actions);
      box.appendChild(card);
    });
  }

  function renderMapsJobs() {
    let box = $('#mapsJobs');
    if (!box) return;
    let jobs = mapsState.jobs.filter(function (job) {
      return job.active || job.status === 'error' || job.status === 'interrupted' ||
        job.status === 'cancelled';
    });
    box.innerHTML = '';
    box.hidden = !jobs.length;
    if (!jobs.length) return;
    let head = document.createElement('p');
    head.className = 'settings-group';
    head.textContent = 'Em andamento';
    box.appendChild(head);

    jobs.forEach(function (job) {
      let row = document.createElement('div');
      row.className = 'maps-job';
      let top = document.createElement('div');
      top.className = 'maps-job-top';
      let title = document.createElement('strong');
      title.textContent = (job.kind === 'extract' ? 'Recorte · ' : 'Download · ') + (job.name || job.id);
      top.appendChild(title);
      let state = document.createElement('span');
      state.className = 'maps-job-state';
      state.textContent = job.active
        ? (job.status === 'verifying' || job.status === 'saving' ? job.status : (job.progress || 0) + '%')
        : job.status;
      top.appendChild(state);
      row.appendChild(top);

      if (job.active) {
        let bar = document.createElement('div');
        bar.className = 'maps-progress';
        let fill = document.createElement('span');
        fill.style.width = Math.max(0, Math.min(100, Number(job.progress) || 0)) + '%';
        bar.appendChild(fill);
        row.appendChild(bar);
        let details = document.createElement('p');
        details.className = 'maps-job-meta';
        let parts = [];
        if (job.bytes_total) parts.push(mapsFmtBytes(job.bytes_done) + ' de ' + mapsFmtBytes(job.bytes_total));
        if (job.speed_label) parts.push(job.speed_label);
        if (job.eta_label) parts.push('resta ' + job.eta_label);
        details.textContent = parts.join(' · ') || 'preparando…';
        row.appendChild(details);
      } else if (job.error) {
        let err = document.createElement('p');
        err.className = 'maps-job-meta maps-error';
        err.textContent = job.error;
        row.appendChild(err);
      }

      let actions = document.createElement('div');
      actions.className = 'maps-job-actions';
      if (job.active) {
        let cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'btn btn-secondary';
        cancel.textContent = 'Cancelar';
        cancel.addEventListener('click', function () { cancelMapJob(job.id); });
        actions.appendChild(cancel);
      } else if (job.kind === 'download' &&
        (job.status === 'interrupted' || job.status === 'cancelled' || job.status === 'error')) {
        let resume = document.createElement('button');
        resume.type = 'button';
        resume.className = 'btn btn-secondary';
        resume.textContent = 'Retomar';
        resume.addEventListener('click', function () { resumeMapJob(job.id); });
        actions.appendChild(resume);
      }
      if (actions.childNodes.length) row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function renderMapsUploads() {
    let box = $('#mapsUploads');
    if (!box) return;
    let uploads = mapsState.uploads || [];
    box.innerHTML = '';
    box.hidden = !uploads.length;
    if (!uploads.length) return;
    let head = document.createElement('p');
    head.className = 'settings-group';
    head.textContent = 'Importações anteriores';
    box.appendChild(head);
    uploads.forEach(function (upload) {
      let row = document.createElement('div');
      row.className = 'maps-upload-row';
      let text = document.createElement('span');
      let percent = upload.size ? Math.round((upload.offset || 0) * 100 / upload.size) : 0;
      text.textContent = (upload.filename || upload.name || 'arquivo') + ' · ' + percent + '%';
      row.appendChild(text);
      let discard = document.createElement('button');
      discard.type = 'button';
      discard.className = 'btn btn-secondary';
      discard.textContent = 'Descartar';
      discard.addEventListener('click', function () { discardUpload(upload.upload_id); });
      row.appendChild(discard);
      box.appendChild(row);
    });
  }

  function loadMapsPanel(silent) {
    if (!silent) mapsStatus('Carregando mapas…');
    return api('/maps')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        mapsState.maps = data.maps || [];
        mapsState.presets = data.presets || [];
        mapsState.jobs = data.jobs || [];
        mapsState.uploads = data.uploads || [];
        mapsState.info = data.info || {};
        mapsState.enabled = data.enabled !== false;
        mapsState.loaded = true;
        renderMapsStats();
        renderMapsList();
        renderMapsPresets();
        renderMapsJobs();
        renderMapsUploads();
        scheduleMapsPolling();
        if (!silent) mapsStatus('');
      })
      .catch(function (e) {
        if (!silent) mapsStatus(e && e.message ? e.message : 'Falha ao carregar mapas.', 'err');
      });
  }

  function openMapsModal(view) {
    mapsLastFocus = document.activeElement;
    if (knowledgeModal && !knowledgeModal.hidden) {
      knowledgeModal.hidden = true;
      stopKnowledgePolling();
    }
    if (!settingsModal.hidden) {
      settingsModal.hidden = true;
      stopDownloadPolling();
    }
    mapsModal.hidden = false;
    activateMapsTab(view === 'download' || view === 'import' ? view : 'library');
    mapsClose.focus();
    loadMapsPanel();
  }

  function closeMapsModal() {
    if (mapsModal.hidden) return;
    closeMapsViewer();
    mapsModal.hidden = true;
    stopMapsPolling();
    if (mapsLastFocus && mapsLastFocus.focus) mapsLastFocus.focus();
  }

  function highlightPreset(key) {
    setTimeout(function () {
      let card = document.querySelector('.maps-preset[data-preset="' + key + '"]');
      if (!card) return;
      card.classList.add('maps-preset-focus');
      card.scrollIntoView({ block: 'center' });
    }, 260);
  }

  function startPresetDownload(preset) {
    let label = preset.name || preset.key;
    let size = preset.estimate ? ' (~' + preset.estimate + ')' : '';
    if (!confirm('Baixar o preset "' + label + '"' + size + '? A extração usa a internet e pode levar alguns minutos.')) return;
    mapsDownloadStatus('Iniciando ' + label + '…');
    api('/maps/extract', { method: 'POST', body: JSON.stringify({ preset: preset.key }) })
      .then(function (r) { return readResponse(r); })
      .then(function (job) {
        mapsDownloadStatus('Job ' + job.id + ' iniciado.', 'ok');
        activateMapsTab('library');
        loadMapsPanel();
      })
      .catch(function (e) { mapsDownloadStatus(e && e.message ? e.message : 'Falha ao iniciar.', 'err'); });
  }

  function estimatePreset(preset, labelEl, button) {
    if (!confirm('Medir o tamanho real de "' + (preset.name || preset.key) +
      '"? A medição baixa os dados necessários e pode consumir centenas de MB.')) return;
    let previous = button.textContent;
    button.disabled = true;
    button.textContent = 'Medindo…';
    labelEl.textContent = 'medindo…';
    api('/maps/extract/estimate', { method: 'POST', body: JSON.stringify({ preset: preset.key }) })
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        labelEl.textContent = '≈ ' + (data.size_label || '—');
        labelEl.title = data.transferred_label ? 'transferência estimada: ' + data.transferred_label : '';
      })
      .catch(function (e) {
        labelEl.textContent = 'falha ao medir';
        labelEl.title = e && e.message ? e.message : '';
      })
      .then(function () {
        button.disabled = false;
        button.textContent = previous;
      });
  }

  function startUrlDownload() {
    let url = $('#mapsUrl').value.trim();
    let name = $('#mapsUrlName').value.trim();
    if (!url) { $('#mapsUrl').focus(); return; }
    if (!confirm('Baixar o mapa de "' + url + '"? O arquivo será salvo em data/maps.')) return;
    mapsDownloadStatus('Iniciando download…');
    api('/maps/downloads', { method: 'POST', body: JSON.stringify({ url: url, name: name }) })
      .then(function (r) { return readResponse(r); })
      .then(function (job) {
        $('#mapsUrl').value = '';
        $('#mapsUrlName').value = '';
        mapsDownloadStatus('Download iniciado: ' + job.name, 'ok');
        activateMapsTab('library');
        loadMapsPanel();
      })
      .catch(function (e) { mapsDownloadStatus(e && e.message ? e.message : 'Falha ao baixar.', 'err'); });
  }

  function cancelMapJob(id) {
    if (!confirm('Cancelar este download? O arquivo parcial fica salvo para retomar depois.')) return;
    api('/maps/jobs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', body: '{}' })
      .then(function (r) { return readResponse(r); })
      .then(function () { loadMapsPanel(true); })
      .catch(function (e) { mapsStatus(e && e.message ? e.message : 'Falha ao cancelar.', 'err'); });
  }

  function resumeMapJob(id) {
    api('/maps/jobs/' + encodeURIComponent(id) + '/resume', { method: 'POST', body: '{}' })
      .then(function (r) { return readResponse(r); })
      .then(function () { loadMapsPanel(); })
      .catch(function (e) { mapsStatus(e && e.message ? e.message : 'Falha ao retomar.', 'err'); });
  }

  function deleteMap(id) {
    let item = mapsState.maps.filter(function (map) { return map.id === id; })[0];
    let label = item ? item.name : id;
    if (!confirm('Apagar o mapa "' + label + '"? O arquivo será removido do armazenamento da Drix.')) return;
    api('/maps/' + encodeURIComponent(id), { method: 'DELETE' })
      .then(function (r) { return readResponse(r); })
      .then(function () {
        if (mapsState.openMapId === id) closeMapsViewer();
        mapsStatus('Mapa apagado.', 'ok');
        loadMapsPanel(true);
      })
      .catch(function (e) { mapsStatus(e && e.message ? e.message : 'Falha ao apagar.', 'err'); });
  }

  function loadMapsScript(src) {
    return new Promise(function (resolve, reject) {
      let existing = document.querySelector('script[data-drix-src="' + src + '"]');
      if (existing) {
        if (existing.dataset.loaded === '1') { resolve(); return; }
        existing.addEventListener('load', function () { resolve(); });
        existing.addEventListener('error', function () { reject(new Error('falha ao carregar ' + src)); });
        return;
      }
      let script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.dataset.drixSrc = src;
      script.addEventListener('load', function () { script.dataset.loaded = '1'; resolve(); });
      script.addEventListener('error', function () { reject(new Error('falha ao carregar ' + src)); });
      document.head.appendChild(script);
    });
  }

  function loadMapsCss(href) {
    return new Promise(function (resolve) {
      if (document.querySelector('link[data-drix-src="' + href + '"]')) { resolve(); return; }
      let link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = href;
      link.dataset.drixSrc = href;
      link.addEventListener('load', function () { resolve(); });
      link.addEventListener('error', function () { resolve(); });
      document.head.appendChild(link);
    });
  }

  function ensureMapLibre() {
    if (window.maplibregl && window.pmtiles) return Promise.resolve();
    if (mapsLibPromise) return mapsLibPromise;
    mapsLibPromise = loadMapsCss('/vendor/maplibre/maplibre-gl.css')
      .then(function () { return loadMapsScript('/vendor/maplibre/maplibre-gl.js'); })
      .then(function () { return loadMapsScript('/vendor/pmtiles/pmtiles.js'); })
      .then(function () {
        if (!window.__drixPmtiles) {
          let protocol = new window.pmtiles.Protocol();
          window.maplibregl.addProtocol('pmtiles', protocol.tile);
          window.__drixPmtiles = protocol;
        }
      })
      .catch(function (error) {
        mapsLibPromise = null;
        throw error;
      });
    return mapsLibPromise;
  }

  function closeMapsViewer() {
    if (mapsViewer) {
      try { mapsViewer.remove(); } catch (e) { }
      mapsViewer = null;
    }
    let viewer = $('#mapsViewer');
    if (viewer) viewer.hidden = true;
    mapsState.openMapId = '';
  }

  function openMapsViewer(mapId, retried) {
    let item = mapsState.maps.filter(function (map) { return map.id === mapId; })[0];
    if (!item) {
      if (retried) { mapsStatus('Mapa não encontrado.', 'err'); return; }
      loadMapsPanel(true).then(function () { openMapsViewer(mapId, true); });
      return;
    }
    mapsState.openMapId = mapId;
    let viewer = $('#mapsViewer');
    viewer.hidden = false;
    $('#mapsViewerTitle').textContent = item.name || 'Mapa';
    let meta = [];
    if (item.zoom_label) meta.push(item.zoom_label);
    if (item.size_label) meta.push(item.size_label);
    $('#mapsViewerMeta').textContent = meta.join(' · ');
    $('#mapsViewerStatus').textContent = 'Carregando mapa…';

    ensureMapLibre().then(function () {
      closeMapsViewer();
      $('#mapsViewer').hidden = false;
      let theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      let center = Array.isArray(item.center) ? item.center : [];
      let lon = Number(center[0]);
      let lat = Number(center[1]);
      if (!isFinite(lon) || !isFinite(lat)) { lon = 0; lat = 0; }
      let zoom = Number(item.center_zoom);
      if (!isFinite(zoom) || zoom <= 0) zoom = 2;
      mapsViewer = new window.maplibregl.Map({
        container: 'mapsCanvas',
        style: '/api/maps/' + encodeURIComponent(mapId) + '/style.json?theme=' + theme,
        center: [lon, lat],
        zoom: zoom,
        maxZoom: 18,
        attributionControl: true,
      });
      mapsViewer.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      mapsViewer.on('load', function () {
        $('#mapsViewerStatus').textContent = '';
        try { mapsViewer.resize(); } catch (e) { }
      });
      mapsViewer.on('error', function (event) {
        let message = event && event.error && event.error.message ? event.error.message : '';
        if (message && !/404|Failed to fetch|Not Found/i.test(message)) {
          $('#mapsViewerStatus').textContent = message;
        }
      });
    }).catch(function (error) {
      $('#mapsViewerStatus').textContent = error && error.message ? error.message : 'Falha ao carregar o visualizador.';
    });
  }

  function updateUploadProgress() {
    let job = mapsUploadJob;
    if (!job) return;
    let size = job.file.size || job.session.size || 1;
    let percent = Math.max(0, Math.min(100, Math.round((job.session.offset || 0) * 100 / size)));
    $('#mapsUpload').hidden = false;
    $('#mapsUploadBar').style.width = percent + '%';
    $('#mapsUploadLabel').textContent = percent + '% · ' + mapsFmtBytes(job.session.offset || 0) + ' de ' + mapsFmtBytes(size);
  }

  function startMapsUpload(file) {
    if (!file) return;
    if (!/\.pmtiles$/i.test(file.name)) {
      setMapsUploadStatus('Escolha um arquivo .pmtiles.', 'err');
      return;
    }
    if (mapsUploadJob) {
      setMapsUploadStatus('Já existe uma importação em andamento.', 'err');
      return;
    }
    setMapsUploadStatus('Preparando importação…');
    mapsUploadJob = { file: file, session: null, offset: 0, retries: 0, cancelled: false, done: false };
    api('/maps/uploads', { method: 'POST', body: JSON.stringify({ filename: file.name, size: file.size }) })
      .then(function (r) { return readResponse(r); })
      .then(function (session) {
        mapsUploadJob.session = session;
        mapsUploadJob.session.offset = Number(session.offset) || 0;
        if (mapsUploadJob.session.offset > 0) {
          setMapsUploadStatus('Retomando de ' + mapsFmtBytes(mapsUploadJob.session.offset) + '…');
        } else {
          setMapsUploadStatus('Enviando ' + file.name + '…');
        }
        updateUploadProgress();
        return uploadNextChunk();
      })
      .catch(function (error) {
        setMapsUploadStatus(error && error.message ? error.message : 'Falha na importação.', 'err');
        mapsUploadJob = null;
      });
  }

  function uploadNextChunk() {
    let job = mapsUploadJob;
    if (!job || job.cancelled) return Promise.resolve();
    let offset = Number(job.session.offset) || 0;
    let size = job.file.size;
    if (offset >= size) return finishMapsUpload();
    let chunkSize = Number(job.session.chunk_size) || 4 * 1024 * 1024;
    let end = Math.min(size, offset + chunkSize);
    let blob = job.file.slice(offset, end);
    return api('/maps/uploads/' + encodeURIComponent(job.session.upload_id) + '?offset=' + offset, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: blob
    }).then(function (res) {
      if (res.status === 409) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          job.session.offset = Number(data.offset) || 0;
          return uploadNextChunk();
        });
      }
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          throw new Error((data && data.detail) || ('HTTP ' + res.status));
        });
      }
      return res.json().then(function (data) {
        job.session.offset = Number(data.bytes_done) || end;
        job.retries = 0;
        updateUploadProgress();
        return uploadNextChunk();
      });
    }).catch(function (error) {
      if (job.cancelled) return;
      if (job.retries < 4) {
        job.retries += 1;
        setMapsUploadStatus('Conexão instável; retomando bloco (' + job.retries + '/4)…', 'err');
        return new Promise(function (resolve) { setTimeout(resolve, 700 * job.retries); })
          .then(uploadNextChunk);
      }
      throw error;
    });
  }

  function finishMapsUpload() {
    let job = mapsUploadJob;
    if (!job) return;
    setMapsUploadStatus('Validando SHA-256 e salvando o mapa…');
    let name = job.file.name.replace(/\.pmtiles$/i, '');
    api('/maps/uploads/' + encodeURIComponent(job.session.upload_id) + '/finish', {
      method: 'POST',
      body: JSON.stringify({ name: name })
    }).then(function (r) { return readResponse(r); })
      .then(function (item) {
        job.done = true;
        mapsUploadJob = null;
        setMapsUploadStatus('Mapa "' + (item.name || name) + '" importado.', 'ok');
        $('#mapsUpload').hidden = true;
        activateMapsTab('library');
        loadMapsPanel();
      })
      .catch(function (error) {
        job.retries = 0;
        setMapsUploadStatus(error && error.message ? error.message : 'Falha ao finalizar a importação.', 'err');
        mapsUploadJob = null;
      });
  }

  function cancelMapsUpload() {
    let job = mapsUploadJob;
    if (!job || !job.session) return;
    job.cancelled = true;
    if (!confirm('Cancelar a importação? O arquivo parcial fica salvo para retomar depois.')) {
      job.cancelled = false;
      return;
    }
    api('/maps/uploads/' + encodeURIComponent(job.session.upload_id), { method: 'DELETE' })
      .catch(function () { })
      .then(function () {
        mapsUploadJob = null;
        $('#mapsUpload').hidden = true;
        setMapsUploadStatus('Importação cancelada.', 'err');
        loadMapsPanel(true);
      });
  }

  function discardUpload(uploadId) {
    if (!confirm('Descartar esta importação parcial? O arquivo já enviado será apagado.')) return;
    api('/maps/uploads/' + encodeURIComponent(uploadId) + '?purge=1', { method: 'DELETE' })
      .then(function () { loadMapsPanel(true); })
      .catch(function (e) { mapsStatus(e && e.message ? e.message : 'Falha ao descartar.', 'err'); });
  }

  function loadPermissionsPanel() {
    let box = $('#permCacheList');
    if (box) box.innerHTML = '<p class="settings-note">Carregando decisões…</p>';
    return api('/permissions/cache')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        renderPermissionsPanel(data.entries || [], data.path || '');
      })
      .catch(function (error) {
        if (box) box.innerHTML = '<p class="settings-note">Falha ao carregar o cache.</p>';
        console.warn(error);
      });
  }

  function loadMapsSettingsInfo() {
    let el = $('#mapsSettingsInfo');
    if (!el) return;
    api('/maps')
      .then(function (r) { return readResponse(r); })
      .then(function (data) {
        let info = data.info || {};
        el.textContent = (info.count || 0) + ' mapa(s) · ' + (info.size_label || '0 B') +
          ' em ' + (info.dir || 'data/maps') + ' · espaço livre ' + (info.free_label || '—');
      })
      .catch(function () { el.textContent = 'Falha ao consultar mapas.'; });
  }

  function renderPermissionsPanel(entries, path) {
    let box = $('#permCacheList');
    if (!box) return;
    box.innerHTML = '';
    let pathEl = $('#permCachePath');
    if (pathEl) pathEl.textContent = path ? 'Arquivo: ' + path : '—';
    if (!entries.length) {
      let note = document.createElement('p');
      note.className = 'settings-note';
      note.textContent = 'Nenhuma decisão lembrada.';
      box.appendChild(note);
      return;
    }
    entries.forEach(function (entry) {
      let row = document.createElement('div');
      row.className = 'settings-tool';
      let info = document.createElement('div');
      info.className = 'settings-tool-info';
      let name = document.createElement('p');
      name.className = 'settings-tool-name';
      name.textContent = entry.tool || 'ferramenta';
      info.appendChild(name);
      let preview = document.createElement('p');
      preview.className = 'settings-note';
      preview.style.margin = '2px 0 0';
      preview.textContent = entry.preview || '';
      info.appendChild(preview);
      row.appendChild(info);

      let badge = document.createElement('span');
      badge.className = 'settings-badge ' + (entry.decision === 'allow' ? 'ok' : 'deny');
      badge.textContent = entry.decision === 'allow' ? 'permitir' : 'negar';
      row.appendChild(badge);

      let remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'btn btn-secondary';
      remove.textContent = 'Remover';
      remove.addEventListener('click', function () {
        api('/permissions/cache/' + encodeURIComponent(entry.key), { method: 'DELETE' })
          .then(function () { loadPermissionsPanel(); })
          .catch(function (e) { setSettingsStatus(e && e.message ? e.message : 'Falha ao remover.', 'err'); });
      });
      row.appendChild(remove);
      box.appendChild(row);
    });
  }

  function clearPermissionsCache() {
    if (!confirm('Limpar todas as decisões lembradas? As próximas ações voltam a pedir confirmação.')) return;
    api('/permissions/cache', { method: 'DELETE' })
      .then(function () { loadPermissionsPanel(); })
      .catch(function (e) { setSettingsStatus(e && e.message ? e.message : 'Falha ao limpar.', 'err'); });
  }

  function handleMapUi(ui) {
    if (!ui || !ui.action) return;
    if (ui.action === 'open_panel') {
      openMapsModal(ui.view || 'library');
      if (ui.preset) highlightPreset(ui.preset);
      if (ui.query) {
        let filter = $('#mapsFilter');
        if (filter) { filter.value = ui.query; renderMapsList(); }
      }
      return;
    }
    if (ui.action === 'open_map') {
      openMapsModal('library');
      setTimeout(function () { openMapsViewer(ui.map_id); }, 180);
      return;
    }
    if (ui.action === 'confirm_delete') {
      openMapsModal('library');
      setTimeout(function () { deleteMap(ui.map_id); }, 220);
    }
  }

  mapsBtn.addEventListener('click', function () { openMapsModal('library'); });
  mapsClose.addEventListener('click', closeMapsModal);
  $('#mapsDone').addEventListener('click', closeMapsModal);
  mapsModal.addEventListener('click', function (e) {
    if (e.target === mapsModal) closeMapsModal();
  });
  $('#mapsRefresh').addEventListener('click', function () { loadMapsPanel(); loadPermissionsPanel(); });
  document.querySelectorAll('#mapsTabs .maps-tab').forEach(function (tab) {
    tab.addEventListener('click', function () { activateMapsTab(tab.dataset.mapsTab); });
  });
  $('#mapsFilter').addEventListener('input', renderMapsList);
  $('#mapsUrlDownload').addEventListener('click', startUrlDownload);
  $('#mapsViewerBack').addEventListener('click', closeMapsViewer);
  $('#mapsUploadCancel').addEventListener('click', cancelMapsUpload);
  $('#mapsSettingsBtn').addEventListener('click', function () {
    closeMapsModal();
    currentTab = 'maps';
    openModal();
  });
  $('#mapsOpenBtn').addEventListener('click', function () {
    settingsModal.hidden = true;
    stopDownloadPolling();
    openMapsModal('library');
  });
  $('#mapsPermRefresh').addEventListener('click', loadPermissionsPanel);
  $('#permCacheClear').addEventListener('click', clearPermissionsCache);

  (function () {
    let drop = $('#mapsDrop');
    let input = $('#mapsFile');
    if (!drop || !input) return;
    drop.addEventListener('click', function () { input.click(); });
    drop.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    ['dragenter', 'dragover'].forEach(function (name) {
      drop.addEventListener(name, function (e) {
        e.preventDefault();
        drop.classList.add('dragover');
      });
    });
    ['dragleave', 'dragend', 'drop'].forEach(function (name) {
      drop.addEventListener(name, function (e) {
        e.preventDefault();
        drop.classList.remove('dragover');
      });
    });
    drop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
        startMapsUpload(e.dataTransfer.files[0]);
      }
    });
    input.addEventListener('change', function () {
      if (input.files && input.files[0]) startMapsUpload(input.files[0]);
      input.value = '';
    });
  })();

  /* fecha menus/modal com clique fora ou Escape */
  document.addEventListener('click', function (e) {
    modelMenu.classList.remove('open');
    if (!e.target.closest('.attach-wrap')) closeAttach();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeMapsModal();
      closeKnowledgeModal();
      closeModal();
      closeAttach();
      modelMenu.classList.remove('open');
    }
  });

  /*  seletor de modelo   */
  modelTrigger.addEventListener('click', function (e) { e.stopPropagation(); modelMenu.classList.toggle('open'); });
  modelMenu.querySelectorAll('.model-opt').forEach(function (o) {
    o.addEventListener('click', function () {
      $('#modelName').textContent = o.dataset.name;
      modelMenu.querySelectorAll('.model-opt').forEach(function (x) { x.classList.toggle('active', x === o); });
      modelMenu.classList.remove('open');
    });
  });

  /*  estado   */
  let currentWorkspace = null;
  let streaming = false;

  /*  efeito de digitação (preferência local)   */
  let typewriter = true;
  try {
    let savedTypewriter = localStorage.getItem('drix-typewriter');
    if (savedTypewriter !== null) typewriter = savedTypewriter === '1';
  } catch (e) { }
  if (typewriterSwitch) {
    typewriterSwitch.checked = typewriter;
    typewriterSwitch.addEventListener('change', function () {
      typewriter = typewriterSwitch.checked;
      try { localStorage.setItem('drix-typewriter', typewriter ? '1' : '0'); } catch (e) { }
    });
  }

  function api(path, opts) {
    opts = opts || {};
    let headers = Object.assign({}, opts.headers || {});
    // FormData precisa que o navegador defina o boundary do multipart.
    if (!(opts.body instanceof FormData) && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }
    if (window.__DRIX_KEY__) headers['X-Drix-Key'] = window.__DRIX_KEY__;
    opts.headers = headers;
    return fetch('/api' + path, opts);
  }

  /*  troca de visão (boas-vindas / thread)   */
  function setView(isThread) { chat.dataset.view = isThread ? 'thread' : 'welcome'; }

  /*  modelo   */
  function loadModels() {
    api('/models').then(function (r) { return r.json(); }).then(function (data) {
      modelMenu.innerHTML = '';
      (data.models || []).forEach(function (m) {
        let b = document.createElement('button');
        b.className = 'model-opt' + (m === data.selected ? ' active' : '');
        b.type = 'button';
        b.innerHTML = '<span>' + ESC(m) + '</span>';
        b.addEventListener('click', function () {
          selectModel(m);
        });
        modelMenu.appendChild(b);
      });
      $('#modelName').textContent = data.selected || 'Drix';
      $('#modelName').dataset.name = data.selected || '';
    }).catch(function () { });
  }
  function selectModel(name) {
    modelMenu.classList.remove('open');
    api('/models/select', { method: 'POST', body: JSON.stringify({ name: name }) })
      .then(function (r) { return r.json(); })
      .then(function () { loadModels(); })
      .catch(function () { });
  }

  /*  histórico (workspaces)  */
  function loadHistory() {
    api('/workspaces').then(function (r) { return r.json(); }).then(function (data) {
      histGroups.innerHTML = '';
      (data.workspaces || []).forEach(function (ws) {
        let g = document.createElement('div');
        g.className = 'hist-group';
        let label = document.createElement('p');
        label.className = 'hist-label';
        label.textContent = 'Conversas';
        g.appendChild(label);
        let ul = document.createElement('ul');
        ul.className = 'hist-list';
        let li = document.createElement('li');
        li.className = 'hist-item' + (ws.name === currentWorkspace ? ' active' : '');
        li.dataset.title = ws.name;
        let main = document.createElement('div');
        main.className = 'hist-main';
        let t = document.createElement('span');
        t.className = 'hist-title';
        t.textContent = ws.name;
        let time = document.createElement('span');
        time.className = 'hist-time';
        time.textContent = ws.updated_at || ws.created_at || '';
        main.appendChild(t);
        main.appendChild(time);
        li.appendChild(main);
        let ren = document.createElement('button');
        ren.className = 'hist-rename';
        ren.type = 'button';
        ren.title = 'Renomear conversa';
        ren.setAttribute('aria-label', 'Renomear conversa');
        ren.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20h4L18 10l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/></svg>';
        ren.addEventListener('click', function (e) {
          e.stopPropagation();
          renameWorkspace(ws.name);
        });
        li.appendChild(ren);
        let del = document.createElement('button');
        del.className = 'hist-del';
        del.type = 'button';
        del.setAttribute('aria-label', 'Excluir conversa');
        del.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>';
        del.addEventListener('click', function (e) {
          e.stopPropagation();
          deleteWorkspace(ws.name);
        });
        li.appendChild(del);
        li.addEventListener('click', function () {
          openWorkspace(ws.name);
          if (window.innerWidth <= 920) applyRail('closed');
        });
        ul.appendChild(li);
        g.appendChild(ul);
        histGroups.appendChild(g);
      });
      histEmpty.hidden = (data.workspaces || []).length !== 0;
    }).catch(function () { });
  }
  function deleteWorkspace(name) {
    api('/workspaces/' + encodeURIComponent(name), { method: 'DELETE' })
      .then(function () {
        if (currentWorkspace === name) { currentWorkspace = null; thread.innerHTML = ''; setView(false); }
        loadHistory();
      })
      .catch(function () { });
  }
  function renameWorkspace(name) {
    let next = window.prompt('Novo nome da conversa:', name);
    if (next === null) return;
    next = next.trim();
    if (!next || next === name) return;
    api('/workspaces/' + encodeURIComponent(name), {
      method: 'PUT',
      body: JSON.stringify({ new_name: next })
    }).then(function (r) {
      if (!r.ok) throw new Error('rename');
      return r.json();
    }).then(function (data) {
      if (currentWorkspace === name) currentWorkspace = data.new_name || next;
      loadHistory();
    }).catch(function () {
      alert('Não foi possível renomear. Verifique se o nome não está vazio, não contém / ou \\ e não repete outra conversa.');
    });
  }
  function openWorkspace(name) {
    currentWorkspace = name;
    setView(true);
    thread.innerHTML = '';
    document.querySelectorAll('.hist-item').forEach(function (x) {
      x.classList.toggle('active', x.dataset.title === name);
    });
    api('/workspaces/' + encodeURIComponent(name) + '/messages')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        thread.innerHTML = '';
        (data.messages || []).forEach(function (m) {
          renderMsg(m.role, m.content, false);
        });
        setView((data.messages || []).length > 0);
      })
      .catch(function () { });
  }

  /*  renderização de mensagens   */
  function renderMsg(role, content, live) {
    let m = document.createElement('div');
    m.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-ai');
    if (role === 'user') {
      m.innerHTML = '<span class="avatar" aria-label="Você">EU</span><div class="bubble"><p>' + ESC(content).replace(/\n/g, '<br>') + '</p></div>';
      thread.appendChild(m);
      scrollThread();
      return null;
    }
    m.innerHTML = '<span class="avatar-ai"><img src="/ia_system/icon/logo_drix2.png" alt="Drix"></span><div class="ai-content"><p class="ai-text">' + ESC(content).replace(/\n/g, '<br>') + '</p></div>';
    thread.appendChild(m);
    scrollThread();
    return m.querySelector('.ai-text');
  }

  function addTyping() {
    let m = document.createElement('div');
    m.className = 'msg msg-ai typing';
    m.innerHTML =
      '<span class="avatar-ai"><img src="/ia_system/icon/logo_drix2.png" alt="Drix"></span>' +
      '<div class="ai-content">' +
        '<div class="typing-dots"><span></span><span></span><span></span></div>' +
        '<p class="ai-text" hidden></p>' +
        '<div class="ai-status">' +
          '<span class="ai-status-text">preparando resposta · 0s</span>' +
          '<button class="ai-stop" type="button" title="Interromper resposta" hidden>Parar</button>' +
        '</div>' +
      '</div>';
    thread.appendChild(m);
    scrollThread();
    return m;
  }

  function streamChat(text, typingEl, workspace) {
    streaming = true;
    refreshSend();

    let full = '';
    let shown = 0;
    let revealTimer = null;
    let lastTick = 0;
    let streamDone = false;
    let finished = false;
    let aborted = false;
    let firstTokenAt = 0;
    let startedAt = performance.now();

    let dots = typingEl.querySelector('.typing-dots');
    let textEl = typingEl.querySelector('.ai-text');
    let statusEl = typingEl.querySelector('.ai-status');
    let statusText = typingEl.querySelector('.ai-status-text');
    let stopBtn = typingEl.querySelector('.ai-stop');
    let controller = new AbortController();

    stopBtn.hidden = false;
    stopBtn.addEventListener('click', function () {
      if (finished) return;
      aborted = true;
      stopBtn.hidden = true;
      statusText.textContent = 'interrompendo…';
      try { controller.abort(); } catch (e) { }
    });

    let statusTimer = setInterval(function () {
      if (finished) return;
      let secs = Math.max(0, Math.round((performance.now() - startedAt) / 1000));
      if (!firstTokenAt) {
        statusText.textContent = (secs >= 6 ? 'carregando modelo' : 'preparando resposta') + ' · ' + secs + 's';
      } else {
        statusText.textContent = 'gerando · ' + secs + 's';
      }
    }, 500);

    function nearBottom() {
      return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 140;
    }

    function finish() {
      if (finished) return;
      finished = true;
      clearInterval(statusTimer);
      if (revealTimer) { clearTimeout(revealTimer); revealTimer = null; }
      shown = full.length;
      if (full) {
        textEl.hidden = false;
        dots.style.display = 'none';
        textEl.textContent = full;
      }
      stopBtn.hidden = true;
      let secs = Math.max(0, Math.round((performance.now() - startedAt) / 1000));
      if (aborted) {
        statusText.textContent = 'interrompido · ' + secs + 's';
      } else if (full) {
        statusText.textContent = 'pronto em ' + secs + 's';
        setTimeout(function () { if (statusEl.parentNode) statusEl.remove(); }, 4000);
      } else {
        statusText.textContent = 'sem resposta';
      }
      streaming = false;
      refreshSend();
      loadHistory();
    }

    function revealTick() {
      revealTimer = null;
      if (finished) return;
      let now = performance.now();
      if (!lastTick) lastTick = now;
      let dt = Math.min(0.1, (now - lastTick) / 1000);
      lastTick = now;

      let pending = full.length - shown;
      if (!typewriter) {
        shown = full.length;
      } else if (pending > 0) {
        // Reveal bursts smoothly, but never get far behind the model.
        let cps = 55;
        if (pending > 120) cps = 140;
        if (pending > 400) cps = 420;
        if (streamDone) cps = Math.max(cps, 700);
        let step = Math.max(1, Math.round(cps * dt));
        shown = Math.min(full.length, shown + step);
      }
      if (shown > 0) {
        textEl.hidden = false;
        dots.style.display = 'none';
        textEl.textContent = full.slice(0, shown);
        if (nearBottom()) scrollThread();
      }
      if (shown < full.length && typewriter) {
        // A timer (not rAF) keeps working when the tab is backgrounded.
        revealTimer = setTimeout(revealTick, 40);
      } else if (streamDone) {
        finish();
      } else {
        lastTick = 0;
      }
    }

    function ensureReveal() {
      if (revealTimer === null && !finished) {
        if (!lastTick) lastTick = performance.now();
        revealTimer = setTimeout(revealTick, 40);
      }
    }

    function appendToken(token) {
      if (!token) return;
      if (!firstTokenAt) firstTokenAt = performance.now();
      full += token;
      ensureReveal();
    }

    function handleEvent(block) {
      block.split('\n').forEach(function (line) {
        if (line.indexOf('data: ') !== 0) return;
        let payload = line.slice(6);
        if (payload === '[DONE]') { streamDone = true; return; }
        let token = null;
        try {
          let obj = JSON.parse(payload);
          if (obj && typeof obj.error === 'string') throw new Error(obj.error);
          // Eventos de interface (ex.: abrir o painel de mapas) não são texto.
          if (obj && obj.type === 'ui' && obj.ui) { handleMapUi(obj.ui); return; }
          // /api/chat sends {"t": "..."}; /api/agent/stream sends
          // {"type": "token", "text": "..."}.  Accept both shapes and never
          // render a JSON event (tool calls, finals, errors) as the answer.
          if (obj && typeof obj.t === 'string') token = obj.t;
          else if (obj && obj.type === 'token' && typeof obj.text === 'string') token = obj.text;
          else if (obj && obj.t && typeof obj.t.text === 'string') token = obj.t.text;
          else if (obj && obj.t && typeof obj.t.content === 'string') token = obj.t.content;
          else if (obj && !obj.type && typeof obj.text === 'string') token = obj.text;
          else if (obj && !obj.type && typeof obj.content === 'string') token = obj.content;
        } catch (e) {
          // Plain-text SSE from an older server still works.
          if (e instanceof SyntaxError) token = payload;
          else { full = 'Erro: ' + e.message; streamDone = true; return; }
        }
        if (token) appendToken(token);
      });
    }

    function fail(message) {
      if (aborted) {
        streamDone = true;
        ensureReveal();
        return;
      }
      if (!full) full = 'Erro: ' + message;
      else full += '\n\n[conexão interrompida]';
      streamDone = true;
      ensureReveal();
    }

    api('/chat', {
      method: 'POST',
      signal: controller.signal,
      body: JSON.stringify({ message: text, workspace: workspace || currentWorkspace || 'default', stream: true })
    }).then(function (res) {
      if (!res.ok || !res.body) throw new Error('Falha na requisição.');
      let reader = res.body.getReader();
      let decoder = new TextDecoder();
      let sseBuf = '';

      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            sseBuf += decoder.decode();
            if (sseBuf.trim()) handleEvent(sseBuf);
            streamDone = true;
            ensureReveal();
            return;
          }
          sseBuf += decoder.decode(r.value, { stream: true });
          let blocks = sseBuf.split('\n\n');
          sseBuf = blocks.pop() || '';
          blocks.forEach(handleEvent);
          return pump();
        });
      }
      return pump();
    }).catch(function (e) {
      if (e && e.name === 'AbortError') {
        aborted = true;
        streamDone = true;
        ensureReveal();
        return;
      }
      fail(e && e.message ? e.message : 'falha de rede');
    });
  }

  /*  compositor  */
  let MAX_LEN = 4000;
  function refreshComposerState() {
    let n = composer.value.length;
    let over = n > MAX_LEN;
    composerCount.textContent = n.toLocaleString('pt-BR') + ' / ' + MAX_LEN.toLocaleString('pt-BR');
    composerCount.classList.toggle('over', over);
    composerWrap.classList.toggle('error', over);
    composerError.hidden = !over;
    refreshSend();
  }
  function refreshSend() { sendBtn.disabled = streaming || !composer.value.trim(); }
  composer.addEventListener('input', function () {
    composer.style.height = 'auto';
    composer.style.height = Math.min(composer.scrollHeight, 220) + 'px';
    refreshComposerState();
  });
  composer.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  sendBtn.addEventListener('click', send);

  function scrollThread() { thread.scrollTop = thread.scrollHeight; }

  function newWorkspaceName() {
    let stamp = new Date().toLocaleString('pt-BR')
      .replace(/[^\w\- .]/g, '-')
      .replace(/\s+/g, ' ')
      .trim();
    return 'Conversa ' + stamp;
  }

  function ensureWorkspace() {
    if (currentWorkspace) return Promise.resolve(currentWorkspace);
    // The workspace name becomes part of an API path, so keep it to the
    // characters accepted by the backend (letters, digits, space, - and .).
    let name = newWorkspaceName();
    return api('/workspaces', { method: 'POST', body: JSON.stringify({ name: name }) })
      .then(function (r) { return r.json(); })
      .then(function (r) {
        if (r && r.name) currentWorkspace = r.name;
        return currentWorkspace || 'default';
      })
      .catch(function () { return 'default'; });
  }

  function send() {
    let text = composer.value.trim();
    if (!text || streaming) return;
    if (composer.value.length > MAX_LEN) { composerWrap.classList.add('error'); composer.focus(); return; }
    if (chat.dataset.view === 'welcome') thread.innerHTML = '';
    renderMsg('user', text, true);
    composer.value = ''; composer.style.height = 'auto'; refreshComposerState();
    setView(true);
    let typingEl = addTyping();
    // Hold the send button while the workspace is created, otherwise a
    // fast second Enter could post to 'default' and split the conversation.
    streaming = true;
    refreshSend();
    ensureWorkspace().then(function (ws) {
      streamChat(text, typingEl, ws);
      loadHistory();
    });
  }

  /*  sugestões   */
  function fillComposer(promptText) {
    composer.value = promptText;
    composer.dispatchEvent(new Event('input'));
    composer.focus();
    if (window.innerWidth <= 920) applyRail('closed');
  }
  document.querySelectorAll('.sugg').forEach(function (s) {
    s.addEventListener('click', function () { fillComposer(s.dataset.prompt); });
  });

  /*  novo chat   */
  $('#newChatBtn').addEventListener('click', function () {
    let name = newWorkspaceName();
    api('/workspaces', { method: 'POST', body: JSON.stringify({ name: name }) })
      .then(function (r) { return r.json(); })
      .then(function (r) {
        currentWorkspace = r.name;
        thread.innerHTML = '';
        setView(false);
        loadHistory();
      })
      .catch(function () { });
    if (window.innerWidth <= 920) applyRail('closed');
  });

  /*  histórico: busca  */
  historySearch.addEventListener('input', function () {
    let q = historySearch.value.toLowerCase();
    let visible = 0;
    document.querySelectorAll('.hist-item').forEach(function (li) {
      let hit = (li.dataset.title || '').toLowerCase().indexOf(q) !== -1;
      li.style.display = hit ? '' : 'none';
      if (hit) visible++;
    });
    histEmpty.hidden = visible !== 0;
  });

  /*  inicialização   */
  loadModels();
  loadHistory();
  loadKnowledgePanel(true);
  composer.focus();

  /*  ciclo de vida: se o serviço parar, substitui a página   */
  (function () {
    let fails = 0;
    let stopped = false;
    function showStopped() {
      if (stopped) return;
      stopped = true;
      document.title = 'Drix · Parado';
      document.body.innerHTML =
        '<div style="position:fixed;inset:0;background:#0e0e1a;color:#e0e0e0;' +
        'display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;z-index:99999">' +
        '<div style="background:#151525;padding:2.5rem 3rem;border-radius:14px;text-align:center;max-width:420px">' +
        '<h1 style="font-size:1.6rem;margin:0 0 .6rem;color:#ff5c5c">Drix parado</h1>' +
        '<p style="color:#aaa;margin:0 0 .4rem">O motor e os serviços foram encerrados.</p>' +
        '<p style="color:#ff8080;margin:0 0 1.2rem;font-size:.85rem">Nenhum serviço ativo</p>' +
        '<button id="closeDrixTab" style="background:#4f8cff;color:#fff;border:0;border-radius:9px;' +
        'padding:.65rem 1.2rem;font-size:.95rem;cursor:pointer">Fechar esta aba</button>' +
        '</div></div>';
      let btn = document.getElementById('closeDrixTab');
      if (btn) btn.addEventListener('click', function () {
        try { window.open('', '_self'); window.close(); } catch (e) { }
        setTimeout(function () { window.location.href = 'about:blank'; }, 250);
      });
      try { window.open('', '_self'); window.close(); } catch (e) { }
    }
    setInterval(function () {
      if (stopped) return;
      fetch('/api/runtime', { cache: 'no-store', headers: { 'Accept': 'application/json' } })
        .then(function (r) {
          if (r.status === 401 || r.status === 403 || r.status === 429) return null;
          if (!r.ok) throw new Error('offline');
          return r.json();
        })
        .then(function (data) {
          if (!data) { fails = 0; return; }
          fails = 0;
          // Se recebemos resposta do /api/runtime, o servidor web está vivo.
          // Fechar automaticamente só em parada explícita ou falhas repetidas
          // de conexão, evitando falso positivo por checagem de portas.
          if (data.stopping === true) showStopped();
        })
        .catch(function () {
          fails += 1;
          if (fails >= 3) showStopped();
        });
    }, 1000);
  })();
})();
