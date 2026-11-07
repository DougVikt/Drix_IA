
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
    settingsModal.hidden = false;
    settingsClose.focus();
    loadSettingsPanel();
    activateSettingsTab(currentTab);
  }
  function closeModal() { settingsModal.hidden = true; if (lastFocus) lastFocus.focus(); }
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
    if (currentTab === 'engine') loadEngineStatus();
    if (currentTab === 'memory') loadMemoryStatus();
    if (currentTab === 'tools') loadToolsPanel();
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
      .then(function () {
        setSettingsStatus('Modelo ' + name + ' selecionado. O motor vai carregá-lo.', 'ok');
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

  /* fecha menus/modal com clique fora ou Escape */
  document.addEventListener('click', function (e) {
    modelMenu.classList.remove('open');
    if (!e.target.closest('.attach-wrap')) closeAttach();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
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
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    if (window.__DRIX_KEY__) opts.headers['X-Drix-Key'] = window.__DRIX_KEY__;
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

  function ensureWorkspace() {
    if (currentWorkspace) return Promise.resolve(currentWorkspace);
    // The workspace name becomes part of an API path, so keep it to the
    // characters accepted by the backend (letters, digits, space, - and .).
    let stamp = new Date().toLocaleString('pt-BR').replace(/[^\w\- .]/g, '-');
    let name = 'Conversa ' + stamp;
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
    let name = 'Conversa ' + new Date().toLocaleString('pt-BR');
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
          if (data.stopping === true || data.any_running === false) showStopped();
        })
        .catch(function () {
          fails += 1;
          if (fails >= 3) showStopped();
        });
    }, 1000);
  })();
})();
