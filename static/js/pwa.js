// Registra o service worker: permite instalar a escala como app no celular e no computador.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* sem PWA, o site funciona igual */ });
  });
}
