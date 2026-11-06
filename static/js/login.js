// Tela de login: nome + matrícula.
const $ = (s) => document.querySelector(s);
const form = $("#form-login");
const erro = $("#login-erro");
const aviso = $("#login-aviso");
const botao = $("#entrar");

const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sem armazenamento */ } };
const lembrar = (k) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } };

const params = new URLSearchParams(location.search);
if (params.has("expirou")) mostrarAviso("Sua sessão expirou. Entre novamente para continuar.");
if (params.has("saiu")) mostrarAviso("Você saiu do sistema.");

function mostrarAviso(texto) {
  aviso.textContent = texto;
  aviso.hidden = false;
}

function setErro(msg, campo) {
  erro.textContent = msg;
  for (const el of [form.nome, form.matricula]) el.setAttribute("aria-invalid", String(!!msg && (!campo || el === campo)));
  if (campo) campo.focus();
}

// Quem já entrou neste aparelho só precisa digitar a matrícula.
const ultimoNome = lembrar("escala:nome");
if (ultimoNome) { form.nome.value = ultimoNome; form.matricula.focus(); } else form.nome.focus();

for (const el of [form.nome, form.matricula]) el.addEventListener("input", () => setErro(""));

$("#mostrar").addEventListener("click", (e) => {
  const visivel = form.matricula.type === "password";
  form.matricula.type = visivel ? "text" : "password";
  e.currentTarget.setAttribute("aria-pressed", String(visivel));
  e.currentTarget.setAttribute("aria-label", visivel ? "Ocultar matrícula" : "Mostrar matrícula");
  form.matricula.focus();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const nome = form.nome.value.replace(/\s+/g, " ").trim();
  const matricula = form.matricula.value.trim();
  if (!nome) return setErro("Informe seu nome.", form.nome);
  if (!matricula) return setErro("Informe sua matrícula.", form.matricula);

  botao.classList.add("is-loading");
  botao.disabled = true;
  $("#entrar-texto").textContent = "Entrando…";
  try {
    const res = await fetch("api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ nome, matricula }),
    });
    const dados = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(dados.erro || "Não foi possível entrar. Tente novamente.");
    guardar("escala:nome", nome);
    location.replace(dados.admin ? "./" : "./#escala");
  } catch (err) {
    form.matricula.value = "";
    setErro(err.message === "Failed to fetch" ? "Sem conexão com o servidor. Verifique sua internet." : err.message, form.matricula);
    botao.classList.remove("is-loading");
    botao.disabled = false;
    $("#entrar-texto").textContent = "Entrar";
  }
});
