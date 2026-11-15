// Service worker do app instalável (PWA).
// - Nunca guarda a API (/api/...): escala, login e auditoria vêm sempre do servidor.
// - Páginas: sempre da rede; sem conexão, mostra offline.html.
// - CSS, JS e imagens: da rede, com cópia guardada para abrir rápido e funcionar sem sinal.
const CACHE = "escala-v2";
const ESSENCIAIS = ["offline.html", "css/style.css", "img/samu-logo.png", "img/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ESSENCIAIS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("offline.html")));
    return;
  }
  e.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok) {
          const copia = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copia));
        }
        return resp;
      })
      .catch(() => caches.match(req, { ignoreSearch: true })),
  );
});
