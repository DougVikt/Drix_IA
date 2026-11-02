
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
  function openModal() { lastFocus = document.activeElement; settingsModal.hidden = false; settingsClose.focus(); }
  function closeModal() { settingsModal.hidden = true; if (lastFocus) lastFocus.focus(); }
  settingsBtn.addEventListener('click', openModal);
  settingsClose.addEventListener('click', closeModal);
  settingsModal.addEventListener('click', function (e) {
    if (e.target === settingsModal) closeModal();
  });

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
    m.innerHTML = '<span class="avatar-ai"><svg class="ic" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/></svg></span><div class="ai-content"><p class="ai-text">' + ESC(content).replace(/\n/g, '<br>') + '</p></div>';
    thread.appendChild(m);
    scrollThread();
    return m.querySelector('.ai-text');
  }

  function addTyping() {
    let m = document.createElement('div');
    m.className = 'msg msg-ai typing';
    m.innerHTML = '<span class="avatar-ai"><svg class="ic" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/></svg></span><div class="ai-content"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    thread.appendChild(m);
    scrollThread();
    return m;
  }

  function streamChat(text, typingEl) {
    streaming = true;
    refreshSend();
    let buf = '';
    api('/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, workspace: currentWorkspace || 'default', stream: true })
    }).then(function (res) {
      if (!res.ok || !res.body) throw new Error('Falha na requisição.');
      let reader = res.body.getReader();
      let decoder = new TextDecoder();
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            typingEl.remove();
            let p = renderMsg('assistant', buf, true);
            return;
          }
          buf += decoder.decode(r.value, { stream: true });
          let parts = buf.split('\n');
          buf = parts.pop() || '';
          parts.forEach(function (line) {
            if (line.indexOf('data: ') !== 0) return;
            let token = line.slice(6);
            if (token === '[DONE]') return;
            let p = typingEl.querySelector('.ai-text');
            if (!p) {
              typingEl.querySelector('.typing-dots').style.display = 'none';
              p = document.createElement('p');
              p.className = 'ai-text';
              typingEl.querySelector('.ai-content').appendChild(p);
            }
            p.textContent += token;
            scrollThread();
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (e) {
      typingEl.remove();
      renderMsg('assistant', 'Erro: ' + e.message, true);
    }).finally(function () {
      streaming = false;
      refreshSend();
      loadHistory();
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

  function send() {
    let text = composer.value.trim();
    if (!text || streaming) return;
    if (composer.value.length > MAX_LEN) { composerWrap.classList.add('error'); composer.focus(); return; }
    if (chat.dataset.view === 'welcome') thread.innerHTML = '';
    renderMsg('user', text, true);
    composer.value = ''; composer.style.height = 'auto'; refreshComposerState();
    setView(true);
    if (!currentWorkspace) {
      let name = 'Conversa ' + new Date().toLocaleString('pt-BR');
      api('/workspaces', { method: 'POST', body: JSON.stringify({ name: name }) })
        .then(function (r) { return r.json(); })
        .then(function (r) { currentWorkspace = r.name; loadHistory(); })
        .catch(function () { });
    }
    streamChat(text, addTyping());
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
})();
