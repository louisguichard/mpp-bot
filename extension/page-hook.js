(() => {
  const emit = (url, data) => {
    if (!url || !url.includes("mpp.football")) return;
    window.dispatchEvent(new CustomEvent("mpp-esperance-api", { detail: { url, data } }));
  };

  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const url = String(args[0]?.url || args[0] || response.url || "");
    if (url.includes("api.mpp.football")) {
      response.clone().json().then((data) => emit(url, data)).catch(() => {});
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this.__mppEsperanceUrl = String(url);
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    this.addEventListener("load", () => {
      if (!this.__mppEsperanceUrl?.includes("api.mpp.football")) return;
      try { emit(this.__mppEsperanceUrl, JSON.parse(this.responseText)); } catch {}
    });
    return originalSend.apply(this, args);
  };
})();
