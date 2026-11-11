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
  setInterval(heartbeat, 5000);
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

