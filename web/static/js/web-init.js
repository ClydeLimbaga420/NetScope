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
  document.addEventListener('visibilitychange', function(){ if(!document.hidden) heartbeat(); });
})();

