(function(){ if(typeof Element!=='undefined'){ if(!Element.prototype.append){ Element.prototype.append=function(){ for(var i=0;i<arguments.length;i++){ var n=arguments[i]; this.appendChild(n && n.nodeType? n : document.createTextNode(n)); } }; } if(!Element.prototype.replaceChildren){ Element.prototype.replaceChildren=function(){ while(this.firstChild) this.removeChild(this.firstChild); for(var i=0;i<arguments.length;i++){ var n=arguments[i]; this.appendChild(n && n.nodeType? n : document.createTextNode(n)); } }; } } })();
(function () {
  // Bootstrap web session token for POST requests (kept in memory only).
  window.__netscope = window.__netscope || { token: null, sessionId: null, ready: false };
  async function boot() {
    try {
      const r = await fetch('/__session__', { credentials: 'same-origin' });
      if (r.ok) {
        const data = await r.json();
        window.__netscope.token = data.token || null;
        window.__netscope.sessionId = data.session_id || null;
        window.__netscope.ready = true;
      }
    } catch (e) { /* server may be booting */ }
  }
  boot();

  const _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    const method = ((init.method || (typeof input === 'object' && input && input.method) || 'GET') + '').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
      const headers = new Headers(init.headers || (typeof input === 'object' && input && input.headers) || {});
      if (window.__netscope && window.__netscope.token) {
        headers.set('X-NetScope-Token', window.__netscope.token);
      }
      if (!headers.has('Content-Type') && init.body && !(init.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json');
      }
      init.headers = headers;
      init.credentials = init.credentials || 'same-origin';
    }
    return _fetch(input, init);
  };

  function heartbeat() {
    if (!window.__netscope || !window.__netscope.ready) return;
    fetch('/api/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(function(){});
  }
  setInterval(heartbeat, 20000);
  // Keep heartbeating while the tab is hidden/backgrounded as well; Chrome
  // throttles timers but the dedicated endpoint plus any API activity keeps the
  // server alive. Also pulse on lifecycle events.
  document.addEventListener('visibilitychange', function(){ heartbeat(); });
  document.addEventListener('pageshow', function(){ heartbeat(); });
  window.addEventListener('focus', function(){ heartbeat(); });
  document.addEventListener('freeze', function(){ /* no-op: connection stays open */ });
  document.addEventListener('resume', function(){ heartbeat(); });
})();

(function () {
  // Mobile navigation drawer: toggles the sidebar overlay on small screens.
  // Guarded so it is a no-op when the shell markup is absent.
  function bindDrawer() {
    var toggle = document.getElementById('nav-toggle');
    var sidebar = document.querySelector('aside.sidebar');
    var backdrop = document.getElementById('sidebar-backdrop');
    if (!toggle || !sidebar || toggle.dataset.bound) return;

    function setOpen(open) {
      sidebar.classList.toggle('open', open);
      document.body.classList.toggle('nav-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (backdrop) {
        if (open) backdrop.removeAttribute('hidden');
        else backdrop.setAttribute('hidden', '');
      }
    }

    toggle.addEventListener('click', function () {
      setOpen(!sidebar.classList.contains('open'));
    });
    if (backdrop) backdrop.addEventListener('click', function () { setOpen(false); });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') setOpen(false);
    });
    Array.prototype.forEach.call(sidebar.querySelectorAll('.nav-item'), function (item) {
      item.addEventListener('click', function () { setOpen(false); });
    });
    var mq = window.matchMedia('(min-width: 651px)');
    var onChange = function (e) { if (e.matches) setOpen(false); };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
    toggle.dataset.bound = '1';
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindDrawer, { once: true });
  else bindDrawer();
})();


(function () {
  var storageKey = 'netscope-theme';

  function preferredTheme() {
    try {
      var saved = localStorage.getItem(storageKey);
      if (saved === 'light' || saved === 'dark') return saved;
    } catch (e) { }
    return 'dark';
  }

  function applyTheme(theme, persist) {
    var light = theme === 'light';
    document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute('content', light ? 'light dark' : 'dark light');
    var button = document.getElementById('theme-toggle');
    if (button) {
      var label = light ? 'Switch to dark mode' : 'Switch to light mode';
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
      var text = button.querySelector('.theme-toggle-label');
      if (text) text.textContent = light ? 'Dark mode' : 'Light mode';
    }
    if (persist) {
      try { localStorage.setItem(storageKey, light ? 'light' : 'dark'); } catch (e) { }
    }
  }

  applyTheme(preferredTheme(), false);

  function bindThemeToggle() {
    var button = document.getElementById('theme-toggle');
    if (!button || button.dataset.bound) return;
    button.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      applyTheme(current === 'light' ? 'dark' : 'light', true);
      if (window.NetScope && typeof window.NetScope.refreshChartTheme === 'function') {
        window.NetScope.refreshChartTheme();
      }
    });
    button.dataset.bound = '1';
    applyTheme(document.documentElement.getAttribute('data-theme') || 'dark', false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindThemeToggle, { once: true });
  else bindThemeToggle();

  window.NetScope = window.NetScope || {};
  window.NetScope.applyTheme = applyTheme;
  window.NetScope.currentTheme = function () {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  };
})();

(function () {
  // Reusable toast notifications. Text is always inserted as textContent so
  // dynamic values from the API can never become markup.
  function region() {
    var element = document.getElementById('toast-region');
    if (element) return element;
    if (!document.body) return null;
    element = document.createElement('div');
    element.id = 'toast-region';
    element.className = 'toast-region';
    element.setAttribute('role', 'status');
    element.setAttribute('aria-live', 'polite');
    element.setAttribute('aria-atomic', 'true');
    document.body.appendChild(element);
    return element;
  }

  function toast(message, kind) {
    var host = region();
    if (!host || !message) return;
    var item = document.createElement('div');
    item.className = 'toast' + (kind ? ' ' + kind : '');
    item.textContent = String(message);
    host.appendChild(item);
    window.setTimeout(function () {
      item.classList.add('is-leaving');
      window.setTimeout(function () { item.remove(); }, 200);
    }, 3200);
  }

  window.NetScope = window.NetScope || {};
  window.NetScope.toast = toast;
})();

(function () {
  function makeDialog(title, eyebrow) {
    var dialog = document.createElement('dialog');
    dialog.className = 'engine-confirmation';
    var panel = document.createElement('div');
    panel.className = 'engine-confirmation-panel';
    var head = document.createElement('div');
    head.className = 'engine-confirm-head-text';
    if (eyebrow) {
      var eyebrowEl = document.createElement('p');
      eyebrowEl.className = 'eyebrow';
      eyebrowEl.textContent = eyebrow;
      head.appendChild(eyebrowEl);
    }
    var h2 = document.createElement('h2');
    h2.textContent = title || 'Confirm';
    head.appendChild(h2);
    panel.appendChild(head);
    dialog.appendChild(panel);
    return { dialog: dialog, panel: panel };
  }

  function addActions(panel, cancelLabel, confirmLabel, danger) {
    var actions = document.createElement('div');
    actions.className = 'engine-dialog-actions';
    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'ghost-button';
    cancel.textContent = cancelLabel || 'Cancel';
    var confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = danger ? 'step-run' : 'step-run';
    confirm.textContent = confirmLabel || 'Continue';
    actions.appendChild(cancel);
    actions.appendChild(confirm);
    panel.appendChild(actions);
    return { actions: actions, cancel: cancel, confirm: confirm };
  }

  function confirmDialog(options) {
    options = options || {};
    return new Promise(function (resolve) {
      var parts = makeDialog(options.title || 'Confirm', options.eyebrow || 'NOTICE');
      var dialog = parts.dialog;
      var panel = parts.panel;
      if (options.message) {
        var msg = document.createElement('p');
        msg.className = 'diag-desc engine-confirm-intro';
        msg.textContent = String(options.message);
        panel.appendChild(msg);
      }
      var buttons = addActions(panel, options.cancelLabel || 'Cancel', options.confirmLabel || 'Continue', options.danger);
      var done = false;
      function finish(value) {
        if (done) return;
        done = true;
        dialog.close();
        dialog.remove();
        resolve(value);
      }
      buttons.cancel.addEventListener('click', function () { finish(false); });
      buttons.confirm.addEventListener('click', function () { finish(true); });
      dialog.addEventListener('cancel', function (event) {
        event.preventDefault();
        finish(false);
      });
      dialog.addEventListener('close', function () { if (!done) { done = true; resolve(false); } dialog.remove(); }, { once: true });
      document.body.appendChild(dialog);
      dialog.showModal();
      buttons.confirm.focus();
    });
  }

  function promptDialog(options) {
    options = options || {};
    return new Promise(function (resolve) {
      var parts = makeDialog(options.title || 'Input', options.eyebrow || 'EDIT');
      var dialog = parts.dialog;
      var panel = parts.panel;
      if (options.message) {
        var msg = document.createElement('p');
        msg.className = 'diag-desc engine-confirm-intro';
        msg.textContent = String(options.message);
        panel.appendChild(msg);
      }
      var label = document.createElement('label');
      label.className = 'engine-confirm-section';
      var labelText = document.createElement('span');
      labelText.className = 'diag-command-label';
      labelText.textContent = options.label || 'Value';
      var input = document.createElement('input');
      input.type = 'text';
      input.value = options.value || '';
      if (options.placeholder) input.placeholder = options.placeholder;
      input.autocomplete = 'off';
      label.appendChild(labelText);
      label.appendChild(input);
      panel.appendChild(label);
      var buttons = addActions(panel, options.cancelLabel || 'Cancel', options.confirmLabel || 'Save', false);
      var done = false;
      function finish(value) {
        if (done) return;
        done = true;
        dialog.close();
        dialog.remove();
        resolve(value);
      }
      buttons.cancel.addEventListener('click', function () { finish(null); });
      buttons.confirm.addEventListener('click', function () { finish(input.value); });
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          finish(input.value);
        }
      });
      dialog.addEventListener('cancel', function (event) {
        event.preventDefault();
        finish(null);
      });
      dialog.addEventListener('close', function () { if (!done) { done = true; resolve(null); } dialog.remove(); }, { once: true });
      document.body.appendChild(dialog);
      dialog.showModal();
      input.focus();
      input.select();
    });
  }

  window.NetScope = window.NetScope || {};
  window.NetScope.confirmDialog = confirmDialog;
  window.NetScope.promptDialog = promptDialog;
})();
