// ===================================================================
// Escala de Plantão · SAMU 192 — frontend (vanilla JS, sem build)
// ===================================================================

// Valores internos ENFERMEIRO/MOTORISTA; na tela, Enfermagem e Socorrista.
const CARGOS = { ENFERMEIRO: "Enfermagem", MOTORISTA: "Socorrista" };
const CARGO_CURTO = { ENFERMEIRO: "E", MOTORISTA: "S" };
const GRUPOS = { ENFERMEIRO: "Enfermagem", MOTORISTA: "Socorristas" };
const PESSOAS = { ENFERMEIRO: ["profissional de enfermagem", "profissionais de enfermagem"],
                  MOTORISTA: ["socorrista", "socorristas"] };
const pessoas = (cargo, n) => PESSOAS[cargo][n === 1 ? 0 : 1];
const STATUS_LABEL = { DISPONIVEL: "Disponível", INDISPONIVEL: "Indisponível", PREFERENCIAL: "Preferencial", FERIAS: "Férias" };
const DOW = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const TURNOS = ["DIA", "NOITE"];
const STEPS = ["periodo", "equipe", "disponibilidade", "revisao", "escala"];
const VIEWS = [...STEPS, "auditoria"];
const MAX_DIAS = 92;
// Versão dos arquivos desta página (o servidor marca o app.js com ?v=...).
const VERSAO_TELA = new URL(import.meta.url).searchParams.get("v");
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
               "Setembro", "Outubro", "Novembro", "Dezembro"];
const PAPEIS = { atual: "Escala atual", seguinte: "Escala do mês seguinte", anterior: "Anterior", futura: "Futura" };
const INTERVALO_ATUALIZACAO = 3000; // ms entre consultas de mudanças feitas por outras pessoas

const state = {
  usuario: null,        // { nome, papel, admin }
  recentes: new Set(),  // posições alteradas agora há pouco por outra pessoa (piscam)
  periodo: null,
  funcionarios: [],
  step: "periodo",
  editingId: null,
  filtroCargo: "",
  busca: "",
  dispSelId: null,
  brush: "INDISPONIVEL",
  rascunho: null,       // escala em revisão (editável)
  escala: null,         // escala confirmada que está na tela (uma das `escalas`)
  escalas: [],          // escalas confirmadas visíveis: atual, mês seguinte (e anteriores, para o ADM)
  escalaSel: null,      // início (AAAA-MM-DD) da escala escolhida nas abas
  origem: null,         // de onde veio o rascunho: { tipo: "editar" | "importar", arquivo }
  historico: [],        // ajustes da revisão, para desfazer
  dadosMudaram: false,  // equipe ou disponibilidade mudou depois da proposta
  recarregar: false,    // escalas precisam ser reavaliadas pelo servidor
  modo: matchMedia("(max-width: 640px)").matches ? "lista" : "calendario",
  cores: "profissional",
  destaque: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const icon = (id, cls = "ic") => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

// ---------- datas (sempre em UTC para não sofrer com horário de verão) ----------

const parseISO = (iso) => new Date(iso + "T00:00:00Z");
const toISO = (d) => d.toISOString().slice(0, 10);
const addDias = (d, n) => new Date(d.getTime() + n * 86400000);
const diaSemana = (d) => (d.getUTCDay() + 6) % 7; // 0 = segunda
const fmtCurta = (iso) => { const [, m, d] = iso.split("-"); return `${d}/${m}`; };
const fmtLonga = (iso) => { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; };
const fmtDataHora = (iso) => `${fmtLonga(iso.slice(0, 10))} às ${iso.slice(11, 16)}`;

function diasEntre(inicio, fim) {
  const out = [];
  for (let d = parseISO(inicio); d <= parseISO(fim); d = addDias(d, 1)) out.push(toISO(d));
  return out;
}
const diasDoPeriodo = () => (state.periodo ? diasEntre(state.periodo.inicio, state.periodo.fim) : []);
const ehFds = (iso) => diaSemana(parseISO(iso)) >= 5;

// ---------- infraestrutura ----------

let gravacoesPendentes = 0; // a atualização automática espera as gravações terminarem

async function api(method, url, body) {
  const opts = { method, headers: { "X-Requested-With": "fetch" } };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const grava = method !== "GET";
  if (grava) gravacoesPendentes++;
  let res;
  try {
    res = await fetch(url, opts);
  } finally {
    if (grava) gravacoesPendentes--;
  }
  if (res.status === 401 && !url.endsWith("api/login")) {
    location.replace("login?expirou=1");
    return new Promise(() => {}); // a página está saindo
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.erro || (res.status === 413 ? "Arquivo grande demais." : `Erro ${res.status}`));
    err.status = res.status;
    throw err;
  }
  return data;
}

/** `acao` opcional: { rotulo, fn } vira um botão no aviso (ex.: Desfazer). */
function toast(msg, tipo = "ok", acao = null) {
  const el = document.createElement("div");
  el.className = `toast toast--${tipo}`;
  el.innerHTML = `${icon(tipo === "ok" ? "check" : "alert")}<span>${esc(msg)}</span>`;
  if (acao) {
    const b = document.createElement("button");
    b.className = "toast__acao";
    b.textContent = acao.rotulo;
    b.addEventListener("click", () => { el.remove(); acao.fn(); });
    el.append(b);
  }
  $("#toasts").append(el);
  setTimeout(() => el.remove(), acao ? 6000 : tipo === "ok" ? 2600 : 5000);
}

function confirmar(titulo, texto, ok = "Confirmar", tom = "danger") {
  const dlg = $("#modal-confirm");
  $("#modal-titulo").textContent = titulo;
  $("#modal-texto").textContent = texto;
  $("#modal-ok").textContent = ok;
  $("#modal-ok").className = `btn btn--${tom}`;
  dlg.showModal();
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true });
  });
}

const iniciais = (nome) => {
  const partes = nome.split(" ").filter(Boolean);
  return (partes[0][0] + (partes.length > 1 ? partes.at(-1)[0] : "")).toUpperCase();
};
const avatar = (f) => `<span class="avatar c-${f.cargo}" aria-hidden="true">${iniciais(f.nome)}</span>`;
const avatarCor = (nome, cor) => `<span class="avatar avatar--pc pc-${cor}" aria-hidden="true">${iniciais(nome)}</span>`;
const porId = (id) => state.funcionarios.find((f) => f.id === id);

function marcarDadosAlterados() {
  state.recarregar = true;
  if (state.rascunho) state.dadosMudaram = true;
}

function aplicarEstado(d) {
  // Período trocado por importação/edição: o formulário da etapa 1 precisa refletir.
  if (JSON.stringify(d.periodo) !== JSON.stringify(state.periodo)) formPeriodo.inicio.value = "";
  state.periodo = d.periodo;
  state.funcionarios = d.funcionarios;
  if ("rascunho" in d) state.rascunho = d.rascunho;
  if ("escalas" in d) {
    state.escalas = d.escalas;
    escolherEscala(state.escalaSel, d.escala?.periodo.inicio);
  }
}

/** Mostra a escala com início `inicio`; se ela não existir, a `padrao` do servidor (atual ou mês seguinte). */
function escolherEscala(inicio, padrao = null) {
  const achar = (i) => i && state.escalas.find((e) => e.periodo.inicio === i);
  state.escala = achar(inicio) || achar(padrao) || state.escalas[0] || null;
  state.escalaSel = state.escala?.periodo.inicio ?? null;
}

/** Atualiza a escala escolhida com a resposta do servidor, mantendo o papel dela. */
function substituirEscala(r) {
  const i = state.escalas.findIndex((e) => e.periodo.inicio === r.periodo.inicio);
  if (i >= 0) state.escalas[i] = { ...r, papel: state.escalas[i].papel };
  escolherEscala(r.periodo.inicio);
}

const comEscala = (url) => (state.escalaSel ? `${url}${url.includes("?") ? "&" : "?"}inicio=${state.escalaSel}` : url);

function nomeDoPeriodo(p) {
  const [ai, mi, di] = p.inicio.split("-").map(Number);
  const [af, mf, df] = p.fim.split("-").map(Number);
  const ultimoDia = new Date(Date.UTC(af, mf, 0)).getUTCDate();
  if (ai === af && mi === mf && di === 1 && df === ultimoDia) return `${MESES[mi - 1]} ${ai}`;
  return `${fmtCurta(p.inicio)} a ${fmtCurta(p.fim)}`;
}

async function carregarEstado() {
  aplicarEstado(await api("GET", "api/estado"));
  state.recarregar = false;
}

// ---------- navegação ----------

const ehAdmin = () => !!state.usuario?.admin;

async function irPara(step) {
  if (!VIEWS.includes(step)) step = "periodo";
  if (!ehAdmin()) step = "escala"; // o perfil USUARIO só trabalha na escala confirmada
  state.step = step;
  if (location.hash !== `#${step}`) history.replaceState(null, "", `#${step}`);
  VIEWS.forEach((s) => ($(`#view-${s}`).hidden = s !== step));
  if (step === "auditoria") $("#btn-auditoria").setAttribute("aria-current", "page");
  else $("#btn-auditoria").removeAttribute("aria-current");
  if (step === "auditoria") carregarAuditoria();
  window.scrollTo({ top: Math.min(window.scrollY, $(".hero").offsetHeight), behavior: "smooth" });
  render();
  if ((step === "revisao" || step === "escala") && state.recarregar) {
    // Equipe ou disponibilidade mudou: o servidor reavalia conflitos e estatísticas.
    try { await carregarEstado(); } catch (err) { toast(err.message, "error"); }
    if (state.step === step) render();
  }
  if (step === "revisao" && !state.rascunho && !state.escala && prontoParaGerar()) gerarProposta();
}

function prontoParaGerar() {
  return state.periodo && Object.keys(CARGOS).every((c) => state.funcionarios.some((f) => f.cargo === c));
}

function renderStepper() {
  const feito = {
    periodo: !!state.periodo,
    equipe: prontoParaGerar(),
    disponibilidade: state.funcionarios.some((f) => Object.keys(f.disponibilidade).length),
    revisao: !!state.escala && !state.rascunho,
    escala: !!state.escala,
  };
  $$(".step").forEach((b) => {
    const s = b.dataset.step;
    b.classList.toggle("is-done", feito[s] && s !== state.step);
    if (s === state.step) b.setAttribute("aria-current", "step");
    else b.removeAttribute("aria-current");
  });
}

function renderHero() {
  const chips = [];
  const periodoChip = ehAdmin() ? state.periodo : state.escala?.periodo;
  if (periodoChip) {
    const n = diasEntre(periodoChip.inicio, periodoChip.fim).length;
    chips.push(`${icon("calendar")}${fmtCurta(periodoChip.inicio)} – ${fmtCurta(periodoChip.fim)} · ${n} dias`);
  }
  const n = (c) => state.funcionarios.filter((f) => f.cargo === c).length;
  if (state.funcionarios.length) chips.push(`${icon("users")}${n("ENFERMEIRO")} de enfermagem · ${plural(n("MOTORISTA"), "socorrista", "socorristas")}`);
  if (state.rascunho) chips.push(`${icon("review")}Revisão em andamento`);
  if (state.escala) chips.push(`${icon("ambulance")}Escala final · cobertura ${Math.round(state.escala.cobertura * 100)}%`);
  $("#hero-chips").innerHTML = chips.map((c) => `<span class="hero__chip">${c}</span>`).join("");
}

function render() {
  renderStepper();
  renderHero();
  ({ periodo: renderPeriodo, equipe: renderEquipe, disponibilidade: renderDisponibilidade,
     revisao: renderRevisao, escala: renderEscala, auditoria: renderAuditoria })[state.step]();
}

// ===================================================================
// 1. PERÍODO
// ===================================================================

const formPeriodo = $("#form-periodo");

function renderPeriodo() {
  if (!formPeriodo.inicio.value) {
    const p = state.periodo || presetPeriodo("proximo-mes");
    formPeriodo.inicio.value = p.inicio;
    formPeriodo.fim.value = p.fim;
  }
  renderResumoPeriodo();
}

function presetPeriodo(tipo) {
  const hoje = new Date();
  const y = hoje.getFullYear(), m = hoje.getMonth();
  const utc = (yy, mm, dd) => toISO(new Date(Date.UTC(yy, mm, dd)));
  if (tipo === "mes-atual") return { inicio: utc(y, m, 1), fim: utc(y, m + 1, 0) };
  if (tipo === "proximo-mes") return { inicio: utc(y, m + 1, 1), fim: utc(y, m + 2, 0) };
  // próximas 4 semanas a partir da próxima segunda
  const ini = new Date(Date.UTC(y, m, hoje.getDate()));
  const seg = addDias(ini, (7 - diaSemana(ini)) % 7 || 7);
  return { inicio: toISO(seg), fim: toISO(addDias(seg, 27)) };
}

function validarPeriodo(inicio, fim) {
  if (!inicio || !fim) return "Informe as duas datas.";
  if (fim < inicio) return "A data de fim deve ser igual ou posterior ao início.";
  if (diasEntre(inicio, fim).length > MAX_DIAS) return `O período máximo é de ${MAX_DIAS} dias.`;
  return null;
}

function renderResumoPeriodo() {
  const { inicio, fim } = formPeriodo;
  const erro = validarPeriodo(inicio.value, fim.value);
  const box = $("#periodo-resumo");
  if (erro) {
    box.innerHTML = `<div class="is-error">${esc(erro)}</div>`;
    return;
  }
  const dias = diasEntre(inicio.value, fim.value).length;
  const fds = diasEntre(inicio.value, fim.value).filter(ehFds).length;
  box.innerHTML = `
    <div><b>${dias}</b><span>dias</span></div>
    <div><b>${dias * 2}</b><span>turnos (dia + noite)</span></div>
    <div><b>${fds}</b><span>dias de fim de semana</span></div>`;
}

formPeriodo.addEventListener("input", renderResumoPeriodo);
$$("[data-preset]").forEach((b) =>
  b.addEventListener("click", () => {
    const p = presetPeriodo(b.dataset.preset);
    formPeriodo.inicio.value = p.inicio;
    formPeriodo.fim.value = p.fim;
    renderResumoPeriodo();
  })
);

formPeriodo.addEventListener("submit", async (e) => {
  e.preventDefault();
  const inicio = formPeriodo.inicio.value, fim = formPeriodo.fim.value;
  if (validarPeriodo(inicio, fim)) return renderResumoPeriodo();
  try {
    const dados = await api("PUT", "api/periodo", { inicio, fim });
    const mudou = JSON.stringify(dados.periodo) !== JSON.stringify(state.periodo);
    state.periodo = dados.periodo;
    if (mudou) novoRascunho(null); // o servidor descarta o rascunho de outro período
    toast("Período salvo");
    irPara(state.funcionarios.length ? "disponibilidade" : "equipe");
  } catch (err) {
    toast(err.message, "error");
  }
});

// ===================================================================
// 2. EQUIPE
// ===================================================================

const formFunc = $("#form-func");

function renderEquipe() {
  const contagem = (c) => state.funcionarios.filter((f) => !c || f.cargo === c).length;
  $$("[data-count]").forEach((el) => (el.textContent = contagem(el.dataset.count)));
  $$("#filtro-cargo .tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.cargo === state.filtroCargo)));

  const termo = state.busca.trim().toUpperCase();
  const lista = state.funcionarios
    .filter((f) => !state.filtroCargo || f.cargo === state.filtroCargo)
    .filter((f) => !termo || f.nome.includes(termo))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));

  $("#lista-func").innerHTML = lista.length
    ? lista.map((f) => {
        const marcados = Object.keys(f.disponibilidade).length;
        return `
        <li class="person ${f.id === state.editingId ? "is-editing" : ""}">
          ${avatar(f)}
          <div class="person__info">
            <div class="person__name">${esc(f.nome)}</div>
            <div class="person__meta"><span class="badge c-${f.cargo}">${CARGOS[f.cargo]}</span>
              ${marcados ? ` · ${marcados} turno${marcados > 1 ? "s" : ""} marcado${marcados > 1 ? "s" : ""}` : ""}</div>
          </div>
          <button class="icon-btn" data-acao="disp" data-id="${f.id}" title="Disponibilidade" aria-label="Disponibilidade de ${esc(f.nome)}">${icon("calendar")}</button>
          <button class="icon-btn" data-acao="editar" data-id="${f.id}" title="Editar" aria-label="Editar ${esc(f.nome)}">${icon("edit")}</button>
          <button class="icon-btn icon-btn--danger" data-acao="remover" data-id="${f.id}" title="Remover" aria-label="Remover ${esc(f.nome)}">${icon("trash")}</button>
        </li>`;
      }).join("")
    : `<li class="empty-list">${state.funcionarios.length ? "Nenhum resultado para o filtro." : "Ninguém cadastrado ainda. Use o formulário ao lado."}</li>`;

  renderSaudeEquipe();
}

function renderSaudeEquipe() {
  const dias = diasDoPeriodo().length;
  const linhas = Object.keys(CARGOS).map((cargo) => {
    const n = state.funcionarios.filter((f) => f.cargo === cargo).length;
    const media = n && dias ? ` · ≈ ${Math.round((dias * 2) / n)} plantões cada` : "";
    if (n >= 3) return `<div class="health__row ok">${icon("check")}${n} ${pessoas(cargo, n)}${media}</div>`;
    const msg = n === 0 ? `Nenhum ${pessoas(cargo, 1)} — turnos ficarão vagos` : `Só ${n} ${pessoas(cargo, n)} — recomendado 3 ou mais para garantir descanso`;
    return `<div class="health__row warn">${icon("alert")}${msg}</div>`;
  });
  $("#equipe-saude").innerHTML = linhas.join("");
}

function editar(f) {
  state.editingId = f?.id ?? null;
  formFunc.nome.value = f?.nome ?? "";
  formFunc.cargo.value = f?.cargo ?? formFunc.cargo.value;
  $("#form-func-titulo").textContent = f ? "Editar profissional" : "Novo profissional";
  $("#btn-salvar-func").textContent = f ? "Salvar alterações" : "Adicionar";
  $("#btn-cancelar-edicao").hidden = !f;
  setErroNome("");
  if (f) formFunc.nome.focus();
  renderEquipe();
}

function setErroNome(msg) {
  $("#nome-erro").textContent = msg;
  formFunc.nome.setAttribute("aria-invalid", String(!!msg));
}

formFunc.addEventListener("submit", async (e) => {
  e.preventDefault();
  const nome = formFunc.nome.value.replace(/\s+/g, " ").trim();
  if (!nome) return setErroNome("Informe o nome.");
  if (!/^[A-Za-zÀ-ÿ]+( [A-Za-zÀ-ÿ]+)*$/.test(nome)) return setErroNome("Use apenas letras e espaços.");
  const corpo = { nome, cargo: formFunc.cargo.value };
  try {
    if (state.editingId) {
      const f = await api("PUT", `api/funcionarios/${state.editingId}`, corpo);
      state.funcionarios = state.funcionarios.map((x) => (x.id === f.id ? f : x));
      toast(`${f.nome} atualizado(a)`);
    } else {
      const f = await api("POST", "api/funcionarios", corpo);
      state.funcionarios.push(f);
      toast(`${f.nome} adicionado(a)`);
    }
    marcarDadosAlterados();
    editar(null);
    formFunc.nome.focus();
    renderStepper(); renderHero();
  } catch (err) {
    setErroNome(err.message);
  }
});

formFunc.nome.addEventListener("input", () => setErroNome(""));
$("#btn-cancelar-edicao").addEventListener("click", () => editar(null));
$("#busca-func").addEventListener("input", (e) => { state.busca = e.target.value; renderEquipe(); });
$("#filtro-cargo").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (tab) { state.filtroCargo = tab.dataset.cargo; renderEquipe(); }
});

$("#lista-func").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-acao]");
  if (!btn) return;
  const f = porId(btn.dataset.id);
  if (btn.dataset.acao === "editar") return editar(f);
  if (btn.dataset.acao === "disp") { state.dispSelId = f.id; return irPara("disponibilidade"); }
  if (btn.dataset.acao === "remover") {
    const ok = await confirmar(`Remover ${f.nome}?`, "As marcações de disponibilidade dessa pessoa também serão apagadas.", "Remover");
    if (!ok) return;
    try {
      await api("DELETE", `api/funcionarios/${f.id}`);
      state.funcionarios = state.funcionarios.filter((x) => x.id !== f.id);
      if (state.editingId === f.id) editar(null);
      if (state.dispSelId === f.id) state.dispSelId = null;
      marcarDadosAlterados();
      toast(`${f.nome} removido(a)`);
      render();
    } catch (err) {
      toast(err.message, "error");
    }
  }
});

// ===================================================================
// 3. DISPONIBILIDADE
// ===================================================================

const calDisp = $("#cal-disp");
let pintura = null; // { status, alteracoes: Map }

function renderDisponibilidade() {
  if (!porId(state.dispSelId)) state.dispSelId = state.funcionarios[0]?.id ?? null;
  renderListaDisp();
  renderBrushes();
  renderCalDisp();
}

function renderListaDisp() {
  const grupos = Object.keys(CARGOS).map((cargo) => {
    const itens = state.funcionarios.filter((f) => f.cargo === cargo).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
    if (!itens.length) return "";
    return `<li class="group-title" role="presentation">${GRUPOS[cargo]}</li>` + itens.map((f) => {
      const vals = Object.values(f.disponibilidade);
      const bloq = vals.filter((s) => s === "INDISPONIVEL" || s === "FERIAS").length;
      const pref = vals.filter((s) => s === "PREFERENCIAL").length;
      const meta = [bloq && `${bloq} bloqueado${bloq > 1 ? "s" : ""}`, pref && `${pref} pref.`].filter(Boolean).join(" · ") || "Disponível sempre";
      return `<li class="person" role="option" tabindex="0" data-id="${f.id}" aria-selected="${f.id === state.dispSelId}">
        ${avatar(f)}<div class="person__info"><div class="person__name">${esc(f.nome)}</div><div class="person__meta">${meta}</div></div></li>`;
    }).join("");
  });
  $("#lista-disp").innerHTML = grupos.join("") || `<li class="empty-list">Cadastre a equipe primeiro.</li>`;
}

function renderBrushes() {
  $$(".brush").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.status === state.brush)));
}

function slotHTML(f, dia, turno) {
  const s = f.disponibilidade[`${dia}|${turno}`] || "DISPONIVEL";
  return `<button class="slot s-${s}" data-dia="${dia}" data-turno="${turno}" data-status="${s}"
    aria-label="${fmtLonga(dia)} ${turno}: ${STATUS_LABEL[s]}">${icon(turno === "DIA" ? "sun" : "moon")}${turno}</button>`;
}

function renderCalDisp() {
  const f = porId(state.dispSelId);
  if (!state.periodo || !f) {
    calDisp.innerHTML = `<div class="cal-hint">${!state.periodo ? "Defina o período na etapa 1." : "Selecione um profissional."}</div>`;
    return;
  }
  const dias = diasDoPeriodo();
  const vazios = diaSemana(parseISO(dias[0]));
  calDisp.innerHTML = `<div class="cal" style="touch-action: pan-y">
    ${DOW.map((d, i) => `<button class="cal__dow ${i >= 5 ? "is-weekend" : ""}" data-dow="${i}" title="Aplicar a todas as ${d.toLowerCase()}s">${d}</button>`).join("")}
    ${'<div class="day day--out"></div>'.repeat(vazios)}
    ${dias.map((dia) => `
      <div class="day ${ehFds(dia) ? "is-weekend" : ""}">
        <button class="day__date" data-dia="${dia}" title="Aplicar ao dia inteiro">${fmtCurta(dia)}<small>${DOW[diaSemana(parseISO(dia))]}</small></button>
        ${TURNOS.map((t) => slotHTML(f, dia, t)).join("")}
      </div>`).join("")}
  </div>`;
}

function aplicarNoSlot(f, el, status, alteracoes) {
  const chave = `${el.dataset.dia}|${el.dataset.turno}`;
  if (alteracoes.has(chave) || el.dataset.status === status) return;
  if (status === "DISPONIVEL") delete f.disponibilidade[chave];
  else f.disponibilidade[chave] = status;
  el.className = `slot s-${status}`;
  el.dataset.status = status;
  el.setAttribute("aria-label", `${fmtLonga(el.dataset.dia)} ${el.dataset.turno}: ${STATUS_LABEL[status]}`);
  alteracoes.set(chave, { data: el.dataset.dia, turno: el.dataset.turno, status });
}

/** Aplica o pincel a vários slots; se todos já têm o status do pincel, "apaga" (volta a Disponível). */
function aplicarEmLote(slots) {
  const f = porId(state.dispSelId);
  if (!f || !slots.length) return;
  const status = slots.every((s) => s.dataset.status === state.brush) ? "DISPONIVEL" : state.brush;
  const alteracoes = new Map();
  slots.forEach((s) => aplicarNoSlot(f, s, status, alteracoes));
  salvarAlteracoes(f, alteracoes);
}

let filaSalvar = Promise.resolve();
function salvarAlteracoes(f, alteracoes) {
  if (!alteracoes.size) return;
  const lista = [...alteracoes.values()];
  marcarDadosAlterados();
  renderListaDisp();
  renderStepper();
  const estado = $("#save-state");
  estado.textContent = "Salvando…";
  filaSalvar = filaSalvar.then(async () => {
    try {
      await api("PATCH", `api/funcionarios/${f.id}/disponibilidade`, lista);
      estado.innerHTML = `${icon("check")} Alterações salvas`;
    } catch (err) {
      estado.textContent = "";
      toast(`Não foi possível salvar: ${err.message}`, "error");
      await carregarEstado();
      render();
    }
  });
}

calDisp.addEventListener("pointerdown", (e) => {
  const el = e.target.closest(".slot");
  if (!el || e.button !== 0) return;
  e.preventDefault();
  pintura = {
    status: el.dataset.status === state.brush ? "DISPONIVEL" : state.brush,
    alteracoes: new Map(),
  };
  aplicarNoSlot(porId(state.dispSelId), el, pintura.status, pintura.alteracoes);
});

document.addEventListener("pointermove", (e) => {
  if (!pintura) return;
  const el = document.elementFromPoint(e.clientX, e.clientY)?.closest(".slot");
  if (el && calDisp.contains(el)) aplicarNoSlot(porId(state.dispSelId), el, pintura.status, pintura.alteracoes);
});

function finalizarPintura() {
  if (!pintura) return;
  salvarAlteracoes(porId(state.dispSelId), pintura.alteracoes);
  pintura = null;
}
document.addEventListener("pointerup", finalizarPintura);
document.addEventListener("pointercancel", finalizarPintura);

calDisp.addEventListener("click", (e) => {
  const slot = e.target.closest(".slot");
  if (slot && e.detail === 0) return aplicarEmLote([slot]); // teclado (Enter/Espaço)
  const data = e.target.closest(".day__date");
  if (data) return aplicarEmLote($$(`.slot[data-dia="${data.dataset.dia}"]`, calDisp));
  const dow = e.target.closest(".cal__dow");
  if (dow) {
    const alvo = Number(dow.dataset.dow);
    aplicarEmLote($$(".slot", calDisp).filter((s) => diaSemana(parseISO(s.dataset.dia)) === alvo));
  }
});

$("#lista-disp").addEventListener("click", (e) => {
  const li = e.target.closest(".person");
  if (li) { state.dispSelId = li.dataset.id; renderDisponibilidade(); }
});
$("#lista-disp").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches(".person")) {
    e.preventDefault();
    e.target.click();
  }
});
$("#brushes").addEventListener("click", (e) => {
  const b = e.target.closest(".brush");
  if (b) { state.brush = b.dataset.status; renderBrushes(); }
});
document.addEventListener("keydown", (e) => {
  if (state.step !== "disponibilidade" || e.target.matches("input, textarea") || e.ctrlKey || e.metaKey) return;
  const idx = ["1", "2", "3", "4"].indexOf(e.key);
  if (idx >= 0) { state.brush = Object.keys(STATUS_LABEL)[idx]; renderBrushes(); }
});


// ===================================================================
// 4. REVISÃO e 5. ESCALA — painel compartilhado
// ===================================================================
// As duas etapas mostram a escala do mesmo jeito; na revisão cada posição
// é um botão que abre o editor. As cores vêm do servidor (`cor`, 0–11) e
// são as mesmas do PDF.

const chavePos = (data, turno, cargo) => `${data}|${turno}|${cargo}`;
const membroDe = (p, cargo) => p[cargo.toLowerCase()];
const quando = (data, turno) => `${DOW[diaSemana(parseISO(data))]}, ${fmtCurta(data)} · ${turno}`;
const plantaoDe = (r, data, turno) => r.plantoes.find((p) => p.data === data && p.turno === turno);

function conflitosPorPosicao(r) {
  const mapa = new Map();
  r.conflitos.forEach((c) => {
    const k = chavePos(c.data, c.turno, c.cargo);
    mapa.set(k, [...(mapa.get(k) || []), c.motivo]);
  });
  return mapa;
}

function equilibrio(r) {
  return Math.max(0, ...Object.keys(CARGOS).map((c) => {
    const t = r.estatisticas.filter((s) => s.cargo === c).map((s) => s.total);
    return t.length ? Math.max(...t) - Math.min(...t) : 0;
  }));
}

function kpisHTML(r, editavel) {
  const cob = Math.round(r.cobertura * 100);
  const eq = equilibrio(r);
  const nc = r.conflitos.length;
  const kpi = (rotulo, valor, dica, tom) =>
    `<div class="kpi ${tom}"><div class="kpi__label">${rotulo}</div><div class="kpi__value">${valor}</div><div class="kpi__hint">${dica}</div></div>`;
  const basicos = [
    kpi("Cobertura", `${cob}%`, "posições preenchidas", cob === 100 ? "is-good" : "is-bad"),
    kpi("Vagas em aberto", r.vagas.length,
      r.vagas.length ? (editavel ? "clique na vaga para preencher" : "precisam de ajuste") : "nenhuma",
      r.vagas.length ? "is-bad" : "is-good"),
  ];
  if (!ehAdmin()) return basicos.join(""); // conflitos e equilíbrio são do ADM
  return [
    ...basicos,
    kpi("Conflitos", nc, nc ? "regras quebradas por ajustes" : "todas as regras respeitadas", nc ? "is-warn" : "is-good"),
    kpi("Equilíbrio", eq <= 1 ? "Ótimo" : `±${eq}`, "diferença máx. de plantões no cargo", eq <= 1 ? "is-good" : eq <= 3 ? "is-warn" : "is-bad"),
  ].join("");
}

function alertasHTML(r, editavel, alvo) {
  const item = (x, texto) => {
    const rotulo = `<strong>${quando(x.data, x.turno)}</strong> — ${CARGOS[x.cargo]}: ${texto}`;
    return `<li>${editavel ? `<button class="link" data-editar="${chavePos(x.data, x.turno, x.cargo)}">${rotulo}</button>` : rotulo}</li>`;
  };
  const out = [];
  if (r.conflitos.length) {
    const dica = editavel
      ? (alvo === "escala" ? "Clique para corrigir, se a exceção não foi combinada com a equipe."
                           : "Clique para corrigir, ou confirme assim mesmo se a exceção foi combinada com a equipe.")
      : "A escala foi confirmada com exceções ou a disponibilidade mudou depois. Use <strong>Editar</strong> para ajustar.";
    out.push(`<div class="alert alert--warn">${icon("alert")}<div><strong>${plural(r.conflitos.length, "conflito", "conflitos")} com as regras.</strong> ${dica}
      <ul>${r.conflitos.map((c) => item(c, `${esc(c.nome)} · ${esc(c.motivo)}`)).join("")}</ul></div></div>`);
  }
  if (r.vagas.length) {
    const dica = editavel ? "Clique para escolher alguém." : "Revise as indisponibilidades ou amplie a equipe.";
    out.push(`<div class="alert">${icon("alert")}<div><strong>${plural(r.vagas.length, "posição sem profissional", "posições sem profissional")}.</strong> ${dica}
      <ul>${r.vagas.map((v) => item(v, esc(v.motivo))).join("")}</ul></div></div>`);
  }
  if (!out.length) out.push(`<div class="alert alert--ok">${icon("check")}Todos os turnos têm enfermagem e socorrista${ehAdmin() ? ", sem conflitos" : ""}.</div>`);
  const ociosos = ehAdmin() ? r.estatisticas.filter((s) => s.total === 0) : [];
  if (ociosos.length) {
    out.push(`<div class="alert alert--warn">${icon("alert")}<div><strong>Sem plantões no período:</strong> ${ociosos.map((s) => esc(s.nome)).join(", ")}</div></div>`);
  }
  return out.join("");
}

function legendaHTML(r, editavel) {
  const grupos = Object.keys(CARGOS).map((cargo) => {
    const pessoas = r.estatisticas.filter((s) => s.cargo === cargo).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
    if (!pessoas.length) return "";
    return `<div class="legend__group" role="group" aria-label="${GRUPOS[cargo]}">
      <span class="legend__title">${GRUPOS[cargo]}</span>
      ${pessoas.map((s) => `<button class="lchip c-${s.cargo} pc-${s.cor}" data-destacar="${s.id}" aria-pressed="${state.destaque === s.id}"
          title="Destacar os plantões de ${esc(s.nome)}"><i></i>${esc(s.nome)}${s.total != null ? `<span class="lchip__n">${s.total}</span>` : ""}</button>`).join("")}
    </div>`;
  });
  const chaves = [
    editavel && `<span>${icon("edit", "ic pos__mark")}alterado</span>`,
    r.conflitos.length && `<span>${icon("alert", "ic pos__flag")}conflito</span>`,
    r.vagas.length && `<span><span class="pos is-vago pos--chave">VAGO</span></span>`,
  ].filter(Boolean);
  return `<div class="legend">${grupos.join("")}${chaves.length ? `<div class="legend__keys">${chaves.join("")}</div>` : ""}</div>`;
}

function posHTML(p, cargo, conflitos, editavel) {
  const f = membroDe(p, cargo);
  const k = chavePos(p.data, p.turno, cargo);
  const motivos = conflitos.get(k);
  const editado = editavel && p.editados.includes(cargo);
  const cls = ["pos", `c-${cargo}`, f ? `pc-${f.cor}` : "is-vago", motivos && "has-conflict", editado && "is-edited",
    state.recentes.has(k) && "is-recent"].filter(Boolean).join(" ");
  const desc = [`${quando(p.data, p.turno)}, ${CARGOS[cargo]}: ${f ? f.nome : "vaga em aberto"}`,
    motivos && `Conflito: ${motivos.join("; ")}`, editado && "Alterado manualmente"].filter(Boolean).join(". ");
  const conteudo = `<span class="pos__role" aria-hidden="true">${CARGO_CURTO[cargo]}</span>
    <span class="pos__name">${f ? esc(f.nome) : "VAGO"}</span>${editado ? icon("edit", "ic pos__mark") : ""}${motivos ? icon("alert", "ic pos__flag") : ""}`;
  const attrs = `class="${cls}" ${f ? `data-pid="${f.id}"` : ""} title="${esc(desc)}"`;
  return editavel
    ? `<button type="button" ${attrs} data-editar="${k}" aria-label="${esc(desc)}. Alterar">${conteudo}</button>`
    : `<span ${attrs}>${conteudo}</span>`;
}

function calendarioHTML(r, conflitos, editavel) {
  const porDia = new Map();
  r.plantoes.forEach((p) => porDia.set(p.data, [...(porDia.get(p.data) || []), p]));
  const dias = [...porDia.keys()];
  const vazios = diaSemana(parseISO(dias[0]));
  return `<div class="sched">
    ${DOW.map((d, i) => `<div class="cal__dow ${i >= 5 ? "is-weekend" : ""}">${d}</div>`).join("")}
    ${"<div></div>".repeat(vazios)}
    ${dias.map((dia) => `
      <div class="sday ${ehFds(dia) ? "is-weekend" : ""}">
        <div class="sday__date">${fmtCurta(dia)}<small class="muted">${DOW[diaSemana(parseISO(dia))]}</small></div>
        ${porDia.get(dia).map((p) => `
          <div class="shift shift--${p.turno}">
            <span class="shift__h">${icon(p.turno === "DIA" ? "sun" : "moon")}${p.turno}</span>
            ${Object.keys(CARGOS).map((c) => posHTML(p, c, conflitos, editavel)).join("")}
          </div>`).join("")}
      </div>`).join("")}
  </div>`;
}

function listaHTML(r, conflitos, editavel) {
  return `<div class="table-wrap"><table class="table-escala">
    <thead><tr><th>Data</th><th>Turno</th><th>Enfermagem</th><th>Socorrista</th></tr></thead>
    <tbody>${r.plantoes.map((p) => `
      <tr class="${ehFds(p.data) ? "is-weekend" : ""} ${p.turno === "DIA" ? "is-new-day" : ""}">
        <td>${p.turno === "DIA" ? `${fmtLonga(p.data)} · ${DOW[diaSemana(parseISO(p.data))]}` : ""}</td>
        <td><span class="turno-pill turno-pill--${p.turno}">${icon(p.turno === "DIA" ? "sun" : "moon")}${p.turno}</span></td>
        ${Object.keys(CARGOS).map((c) => `<td>${posHTML(p, c, conflitos, editavel)}</td>`).join("")}
      </tr>`).join("")}</tbody></table></div>`;
}

function estatisticasHTML(r) {
  const max = Math.max(1, ...r.estatisticas.map((s) => s.total));
  return `<div class="table-wrap"><table>
    <thead><tr><th>Profissional</th><th>Plantões</th>
      <th><span class="legend-inline"><span><i style="background:var(--orange)"></i>Dia</span><span><i style="background:var(--navy-700)"></i>Noite</span></span></th>
      <th>Fins de semana</th><th>Preferências atendidas</th></tr></thead>
    <tbody>${r.estatisticas.map((s) => `
      <tr class="stats-row" data-id="${s.id}" tabindex="0">
        <td><div class="person" style="padding:0">${avatarCor(s.nome, s.cor)}<div class="person__info"><div class="person__name">${esc(s.nome)}</div>
          <div class="person__meta"><span class="badge c-${s.cargo}">${CARGOS[s.cargo]}</span></div></div></div></td>
        <td><strong>${s.total}</strong></td>
        <td><div class="bar" style="width:${Math.max(30, (s.total / max) * 100)}%" title="${s.dias} dia · ${s.noites} noite">
          <span class="bar__d" style="flex:${s.dias}"></span><span class="bar__n" style="flex:${s.noites}"></span></div>
          <span class="muted small">${s.dias} dia · ${s.noites} noite</span></td>
        <td>${s.fins_de_semana}</td>
        <td>${s.preferenciais_atendidas}</td>
      </tr>`).join("")}</tbody></table></div>`;
}

function renderPainel(el, r, editavel, alvo = "rascunho") {
  const conflitos = conflitosPorPosicao(r);
  const tabs = (attr, aria, opcoes, atual) => opcoes.map(([v, t]) =>
    `<button role="${aria === "selected" ? "tab" : "radio"}" class="tab" data-${attr}="${v}" aria-${aria}="${atual === v}">${t}</button>`).join("");
  el.innerHTML = `
    <div class="kpis ${ehAdmin() ? "" : "kpis--2"}">${kpisHTML(r, editavel)}</div>
    <div class="alerts">${alertasHTML(r, editavel, alvo)}</div>
    <div class="card card--flush">
      <div class="toolbar">
        <div class="tabs" role="tablist" aria-label="Visualização">${tabs("modo", "selected", [["calendario", "Calendário"], ["lista", "Lista"]], state.modo)}</div>
        <div class="toolbar__tools">
          <div class="tabs" role="radiogroup" aria-label="Colorir por">
            <span class="tabs__label" aria-hidden="true">Cores</span>
            ${tabs("cores", "checked", [["profissional", "Por profissional"], ["funcao", "Por função"]], state.cores)}
          </div>
          ${editavel && alvo === "rascunho" ? `<button class="btn btn--ghost btn--sm" data-acao="desfazer" ${state.historico.length ? "" : "disabled"}
            title="Desfazer o último ajuste (Ctrl+Z)">${icon("undo")}Desfazer</button>` : ""}
        </div>
      </div>
      <div class="escala-area cores-${state.cores}" data-escala>
        ${legendaHTML(r, editavel)}
        ${state.modo === "calendario" ? calendarioHTML(r, conflitos, editavel) : listaHTML(r, conflitos, editavel)}
      </div>
    </div>
    ${ehAdmin() ? `<div class="card card--flush card--stats">
      <div class="toolbar"><h3>Distribuição por profissional</h3><span class="muted small">Clique para destacar na escala</span></div>
      ${estatisticasHTML(r)}
    </div>` : ""}`;
  aplicarDestaque(el);
}

function aplicarDestaque(painel) {
  const id = state.destaque;
  const area = $("[data-escala]", painel);
  if (!area) return;
  area.classList.toggle("has-highlight", !!id);
  $$(".pos", area).forEach((el) => el.classList.toggle("is-highlighted", !!id && el.dataset.pid === id));
  $$("[data-destacar]", painel).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.destacar === id)));
  $$(".stats-row", painel).forEach((tr) => tr.classList.toggle("is-active", tr.dataset.id === id));
}

/** `qual`: "rascunho" (revisão, só ADM) ou "escala" (confirmada, editável por todos com auditoria). */
function ligarPainel(el, qual) {
  el.addEventListener("click", (e) => {
    const t = e.target;
    const modo = t.closest("[data-modo]");
    if (modo) { state.modo = modo.dataset.modo; return render(); }
    const cores = t.closest("[data-cores]");
    if (cores) { state.cores = cores.dataset.cores; return render(); }
    const alvo = t.closest("[data-destacar], .stats-row");
    if (alvo) {
      const id = alvo.dataset.destacar || alvo.dataset.id;
      state.destaque = state.destaque === id ? null : id;
      aplicarDestaque(el);
      if (state.destaque && alvo.matches(".stats-row")) $("[data-escala]", el).scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (t.closest('[data-acao="desfazer"]')) return desfazer();
    const pos = t.closest("[data-editar]");
    if (pos) abrirEditor(qual, ...pos.dataset.editar.split("|"));
  });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches(".stats-row")) e.target.click();
  });
}
ligarPainel($("#revisao-painel"), "rascunho");
ligarPainel($("#escala-painel"), "escala");

// ---------- 4. Revisão ----------

function novoRascunho(r, origem = null) {
  state.rascunho = r;
  state.origem = r ? origem : null;
  state.historico = [];
  state.dadosMudaram = false;
  state.destaque = null;
  state.finalMudou = null;
}

function renderRevisao() {
  const r = state.rascunho;
  const pronto = prontoParaGerar();
  $("#revisao-vazia").hidden = !!r;
  $("#revisao-painel").hidden = !r;
  $("#btn-proposta").hidden = $("#btn-confirmar").hidden = !r;
  $("#banner-mudancas").hidden = !(r && state.dadosMudaram);
  renderBannerFinalMudou();
  renderBannerOrigem();
  if (r) return renderPainel($("#revisao-painel"), r, true);

  $("#revisao-vazia-texto").textContent = !pronto
    ? "Defina o período e cadastre ao menos um(a) profissional de enfermagem e um(a) socorrista para gerar uma proposta, ou importe uma escala salva."
    : state.escala
      ? "A escala final já foi confirmada. Você pode editá-la, gerar uma nova proposta ou importar uma escala salva."
      : "Gere uma proposta automática para revisar, ou importe uma escala salva antes.";
  $('#revisao-vazia [data-acao="editar-final"]').hidden = !state.escala;
  $('#revisao-vazia [data-acao="nova-proposta"]').disabled = !pronto;
}

/** A escala confirmada recebeu trocas enquanto o ADM revisava uma cópia dela. */
function renderBannerFinalMudou() {
  const b = $("#banner-final-mudou");
  const ev = state.rascunho && state.finalMudou;
  b.hidden = !ev;
  if (!ev) return;
  b.innerHTML = `${icon("alert")}<span><strong>${esc(ev.usuario)}</strong> trocou um plantão na escala confirmada
    enquanto esta revisão estava aberta (${esc(ev.descricao)}). Se você confirmar esta revisão, ela substitui essas trocas.</span>
    <button class="btn btn--small" data-goto-escala>Ver escala</button>`;
}
$("#banner-final-mudou").addEventListener("click", (e) => { if (e.target.closest("[data-goto-escala]")) irPara("escala"); });

function renderBannerOrigem() {
  const b = $("#banner-origem");
  const o = state.rascunho && state.origem;
  b.hidden = !o;
  if (!o) return;
  b.innerHTML = o.tipo === "editar"
    ? `${icon("edit")}<span>Você está editando uma cópia da escala final. Ela só é substituída quando você confirmar.</span>
       <button class="btn btn--small" data-acao="descartar">Descartar edição</button>`
    : `${icon("upload")}<span>Escala importada de <strong>${esc(o.arquivo)}</strong>. Revise e confirme para torná-la a escala final.</span>`;
}

async function gerarProposta() {
  const temAjustes = state.historico.length || state.rascunho?.plantoes.some((p) => p.editados.length);
  if (temAjustes && !(await confirmar("Gerar nova proposta?", "Os ajustes manuais desta revisão serão perdidos.", "Gerar nova proposta"))) return;
  const botoes = $$('[data-acao="nova-proposta"]');
  botoes.forEach((b) => b.classList.add("is-loading"));
  try {
    novoRascunho(await api("POST", "api/rascunho"));
    state.recarregar = false;
    const v = state.rascunho.vagas.length;
    toast(v ? `Proposta gerada com ${plural(v, "vaga", "vagas")} em aberto` : "Proposta gerada com cobertura total", v ? "warn" : "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    botoes.forEach((b) => b.classList.remove("is-loading"));
    render();
  }
}

async function confirmarEscala() {
  const r = state.rascunho;
  if (!r) return;
  const pendencias = [r.vagas.length && plural(r.vagas.length, "vaga em aberto", "vagas em aberto"),
    r.conflitos.length && plural(r.conflitos.length, "conflito", "conflitos")].filter(Boolean);
  const sobrepostas = state.escalas.filter((e) => e.periodo.inicio <= r.periodo.fim && r.periodo.inicio <= e.periodo.fim);
  if (pendencias.length || sobrepostas.length) {
    const texto = [pendencias.length && `Ainda há ${pendencias.join(" e ")}. Você pode confirmar assim mesmo e ajustar depois.`,
      sobrepostas.length && `A escala confirmada de ${sobrepostas.map((e) => nomeDoPeriodo(e.periodo)).join(" e ")} será substituída por esta versão. As outras escalas continuam publicadas.`]
      .filter(Boolean).join(" ");
    const titulo = pendencias.length ? "Confirmar com pendências?" : "Substituir a escala final?";
    if (!(await confirmar(titulo, texto, "Confirmar escala", "primary"))) return;
  }
  try {
    const nova = await api("POST", "api/escala");
    novoRascunho(null);
    state.escalaSel = nova.periodo.inicio;
    await carregarEstado();
    toast(`Escala de ${nomeDoPeriodo(nova.periodo)} confirmada`);
    irPara("escala");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function editarFinal() {
  if (state.rascunho && !(await confirmar("Substituir a revisão em andamento?",
    "A revisão atual ainda não foi confirmada e será descartada para abrir a escala final.", "Substituir"))) return;
  try {
    const d = await api("POST", comEscala("api/escala/editar"));
    aplicarEstado(d.estado);
    novoRascunho(d.rascunho, { tipo: "editar" });
    irPara("revisao");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function descartarRevisao() {
  if (!(await confirmar("Descartar a edição?", "Os ajustes feitos nesta revisão serão perdidos. A escala final continua como estava.", "Descartar"))) return;
  try {
    await api("DELETE", "api/rascunho");
    novoRascunho(null);
    irPara(state.escala ? "escala" : "revisao");
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---------- editor de posição ----------

const modalPos = $("#modal-pos");
let editando = null; // { qual, data, turno, cargo, esperado, origem }

async function abrirEditor(qual, data, turno, cargo) {
  const atual = membroDe(plantaoDe(state[qual], data, turno), cargo);
  editando = { qual, data, turno, cargo, esperado: atual?.id ?? null, origem: document.activeElement };
  $("#pos-quando").innerHTML = `${icon(turno === "DIA" ? "sun" : "moon")}${quando(data, turno)}`;
  $("#pos-titulo").textContent = `Escolher ${pessoas(cargo, 1)}`;
  $("#pos-atual").textContent = `Atualmente: ${atual ? atual.nome : "vaga em aberto"}`
    + (qual === "escala" ? " · a troca fica registrada com o seu nome" : "");
  $("#pos-cands").innerHTML = `<p class="cands__title">Carregando…</p>`;
  modalPos.showModal();
  try {
    const url = `${qual === "escala" ? "api/escala/candidatos" : "api/rascunho/candidatos"}?${new URLSearchParams({ data, turno, cargo })}`;
    renderCandidatos(await api("GET", qual === "escala" ? comEscala(url) : url), atual, state[qual]);
  } catch (err) {
    modalPos.close();
    toast(err.message, "error");
  }
}

function renderCandidatos(lista, atual, escala) {
  const cor = new Map(escala.estatisticas.map((s) => [s.id, s.cor]));
  const botao = (c) => {
    const ehAtual = atual?.id === c.id;
    const meta = c.impedimentos.length
      ? `<span class="cand__warn">${icon("alert")}${esc(c.impedimentos.join(" · "))}</span>`
      : `${c.total != null ? plural(c.total, "plantão", "plantões") : "Disponível"}${c.preferencial ? ` · <span class="cand__pref">${icon("star")}turno preferencial</span>` : ""}`;
    return `<button class="cand ${c.impedimentos.length ? "is-blocked" : ""}" data-escolher="${c.id}" ${ehAtual ? 'aria-current="true"' : ""}>
      ${avatarCor(c.nome, cor.get(c.id) ?? 0)}
      <span class="cand__info"><span class="cand__name">${esc(c.nome)}${ehAtual ? ' <span class="badge badge--atual">Atual</span>' : ""}</span>
      <span class="cand__meta">${meta}</span></span></button>`;
  };
  const livres = lista.filter((c) => !c.impedimentos.length);
  const bloqueados = lista.filter((c) => c.impedimentos.length);
  $("#pos-cands").innerHTML = [
    `<p class="cands__title">${livres.length ? "Podem assumir" : "Ninguém está livre neste turno"}</p>`,
    livres.map(botao).join(""),
    bloqueados.length ? `<p class="cands__title">Com impedimento <span class="cands__sub">· pode escalar, mas fica como conflito</span></p>${bloqueados.map(botao).join("")}` : "",
    atual ? `<button class="cand cand--vago" data-escolher="">${icon("x")}<span class="cand__info"><span class="cand__name">Deixar vago</span>
      <span class="cand__meta">A posição fica em aberto</span></span></button>` : "",
  ].join("");
  ($(".cand:not([aria-current])", modalPos) || $("#pos-fechar")).focus();
}

$("#pos-cands").addEventListener("click", (e) => {
  const b = e.target.closest("[data-escolher]");
  if (!b) return;
  const { qual, data, turno, cargo, esperado } = editando;
  modalPos.close();
  if (b.hasAttribute("aria-current")) return;
  const alt = { data, turno, cargo, funcionario_id: b.dataset.escolher || null };
  if (qual === "escala") alterarPlantaoFinal({ ...alt, esperado });
  else alterarPosicao(alt);
});
$("#pos-fechar").addEventListener("click", () => modalPos.close());
modalPos.addEventListener("click", (e) => {
  // Clique no fundo escurecido fecha o editor.
  const r = modalPos.getBoundingClientRect();
  if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) modalPos.close();
});
modalPos.addEventListener("close", () => { if (editando?.origem?.isConnected) editando.origem.focus(); });

const assinatura = (c) => `${c.data}|${c.turno}|${c.cargo}|${c.id}|${c.motivo}`;

async function alterarPosicao(alt, desfazendo = false) {
  const p = plantaoDe(state.rascunho, alt.data, alt.turno);
  const anterior = { data: alt.data, turno: alt.turno, cargo: alt.cargo,
    funcionario_id: membroDe(p, alt.cargo)?.id ?? null, editado: p.editados.includes(alt.cargo) };
  const antes = new Set(state.rascunho.conflitos.map(assinatura));
  try {
    state.rascunho = await api("PATCH", "api/rascunho", [alt]);
  } catch (err) {
    return toast(err.message, "error");
  }
  if (desfazendo) state.historico.pop();
  else state.historico.push(anterior);
  render();
  $(`#revisao-painel [data-editar="${chavePos(alt.data, alt.turno, alt.cargo)}"]`)?.focus();
  if (desfazendo) return toast("Ajuste desfeito");

  const novo = membroDe(plantaoDe(state.rascunho, alt.data, alt.turno), alt.cargo);
  const novos = state.rascunho.conflitos.filter((c) => !antes.has(assinatura(c)));
  const msg = novos.length
    ? `Ajuste gerou ${plural(novos.length, "conflito", "conflitos")}: ${novos.map((c) => `${c.nome}, ${c.motivo.toLowerCase()}`).join("; ")}`
    : `${quando(alt.data, alt.turno)} · ${CARGOS[alt.cargo]}: ${novo ? novo.nome : "vaga em aberto"}`;
  toast(msg, novos.length ? "warn" : "ok", { rotulo: "Desfazer", fn: desfazer });
}

function desfazer() {
  const ultimo = state.historico.at(-1);
  if (ultimo && state.rascunho) alterarPosicao(ultimo, true);
}

/** Troca direto na escala confirmada. `esperado` = quem estava na posição quando a pessoa abriu o editor. */
async function alterarPlantaoFinal(alt, desfazendo = false) {
  const p = plantaoDe(state.escala, alt.data, alt.turno);
  const editadoAntes = p.editados.includes(alt.cargo);
  try {
    substituirEscala(await api("PATCH", comEscala("api/escala"), [alt]));
  } catch (err) {
    if (err.status === 409) { // outra pessoa mexeu primeiro: mostra a versão atual
      await carregarEstado().catch(() => {});
      render();
    }
    return toast(err.message, "error");
  }
  render();
  $(`#escala-painel [data-editar="${chavePos(alt.data, alt.turno, alt.cargo)}"]`)?.focus();
  if (desfazendo) return toast("Troca desfeita");
  const novo = membroDe(plantaoDe(state.escala, alt.data, alt.turno), alt.cargo);
  const voltar = { data: alt.data, turno: alt.turno, cargo: alt.cargo, funcionario_id: alt.esperado,
                   esperado: novo?.id ?? null, editado: editadoAntes };
  toast(`${quando(alt.data, alt.turno)} · ${CARGOS[alt.cargo]}: ${novo ? novo.nome : "vaga em aberto"}. Todos já veem a mudança.`,
    "ok", { rotulo: "Desfazer", fn: () => alterarPlantaoFinal(voltar, true) });
}

document.addEventListener("keydown", (e) => {
  if (state.step !== "revisao" || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.key.toLowerCase() !== "z") return;
  if (e.target.matches("input, textarea") || $("dialog[open]")) return;
  e.preventDefault();
  desfazer();
});

// ---------- importação ----------

const inputImportar = $("#input-importar");

inputImportar.addEventListener("change", async () => {
  const arquivo = inputImportar.files[0];
  inputImportar.value = "";
  if (!arquivo) return;
  if (state.rascunho && !(await confirmar("Substituir a revisão em andamento?",
    `A escala de “${arquivo.name}” vai substituir a revisão atual, que ainda não foi confirmada.`, "Importar"))) return;
  const corpo = new FormData();
  corpo.append("arquivo", arquivo);
  try {
    const d = await api("POST", "api/escala/importar", corpo);
    aplicarEstado(d.estado);
    novoRascunho(d.rascunho, { tipo: "importar", arquivo: arquivo.name });
    const n = d.adicionados.length;
    toast(n ? `Escala importada. ${plural(n, "profissional adicionado", "profissionais adicionados")} à equipe: ${d.adicionados.join(", ")}`
            : "Escala importada para revisão");
    irPara("revisao");
  } catch (err) {
    toast(err.message, "error");
  }
});

// ---------- 5. Escala final ----------

function renderMeses() {
  const el = $("#escala-meses");
  // Usuário: sempre as duas abas (a do mês seguinte aparece desabilitada até ser publicada).
  // ADM: todas as escalas confirmadas guardadas.
  const abas = ehAdmin()
    ? state.escalas.map((e) => ({ papel: e.papel, e }))
    : ["atual", "seguinte"].map((papel) => ({ papel, e: state.escalas.find((x) => x.papel === papel) }));
  el.hidden = !abas.length || (ehAdmin() && abas.length < 2);
  el.innerHTML = abas.map(({ papel, e }) => {
    const sel = e && e.periodo.inicio === state.escalaSel;
    const sub = e ? nomeDoPeriodo(e.periodo) : "ainda não publicada";
    return `<button role="tab" class="mes ${e ? "" : "is-vazio"}" aria-selected="${!!sel}" ${e ? `data-escala-inicio="${e.periodo.inicio}"` : "disabled"}>
      <span class="mes__papel">${PAPEIS[papel]}</span><span class="mes__nome">${sub}</span></button>`;
  }).join("");
}

$("#escala-meses").addEventListener("click", (e) => {
  const b = e.target.closest("[data-escala-inicio]");
  if (!b || b.dataset.escalaInicio === state.escalaSel) return;
  escolherEscala(b.dataset.escalaInicio);
  state.destaque = null;
  render();
});

function renderEscala() {
  renderMeses();
  const r = state.escala;
  $("#link-json").href = comEscala("api/escala.json");
  $("#link-pdf").href = comEscala("api/escala.pdf");
  $("#escala-vazia").hidden = !!r;
  $("#escala-painel").hidden = !r;
  $("#escala-acoes").hidden = !r;
  $("#banner-rascunho").hidden = !(r && state.rascunho);
  $("#escala-sub").textContent = r
    ? `${nomeDoPeriodo(r.periodo)}: ${fmtLonga(r.periodo.inicio)} a ${fmtLonga(r.periodo.fim)} · confirmada em ${fmtDataHora(r.confirmada_em)}. `
      + "Clique em um nome para trocar o profissional do plantão; a troca fica registrada."
    : "A versão confirmada, pronta para imprimir e distribuir.";
  if (!ehAdmin()) {
    $("#escala-vazia-texto").textContent = "A coordenação ainda não publicou a escala. Esta página se atualiza sozinha quando ela for confirmada.";
  }
  if (r) renderPainel($("#escala-painel"), r, true, "escala");
}

// ---------- Auditoria (ADM) ----------

const TIPOS = {
  PLANTAO_ALTERADO: ["Plantão alterado", "plantao"],
  ESCALA_CONFIRMADA: ["Escala confirmada", "plantao"],
  LOGIN: ["Entrada", "acesso"],
  LOGOUT: ["Saída", "acesso"],
  LOGIN_FALHOU: ["Acesso negado", "falha"],
  LOGIN_BLOQUEADO: ["Acesso bloqueado", "falha"],
  PERIODO_DEFINIDO: ["Período", "admin"],
  FUNCIONARIO_ADICIONADO: ["Equipe", "admin"],
  FUNCIONARIO_ALTERADO: ["Equipe", "admin"],
  FUNCIONARIO_REMOVIDO: ["Equipe", "admin"],
  DISPONIBILIDADE_ALTERADA: ["Disponibilidade", "admin"],
  PROPOSTA_GERADA: ["Proposta gerada", "admin"],
  REVISAO_DESCARTADA: ["Revisão descartada", "admin"],
  ESCALA_IMPORTADA: ["Importação", "admin"],
  ESCALA_EXPORTADA: ["Exportação", "admin"],
  PDF_GERADO: ["PDF", "admin"],
};
const auditoria = { eventos: [], usuarios: [], carregado: false };

async function carregarAuditoria() {
  if (!ehAdmin()) return;
  const usuario = $("#audit-usuario").value;
  try {
    const d = await api("GET", `api/auditoria?${new URLSearchParams({ usuario, limite: 3000 })}`);
    Object.assign(auditoria, d, { carregado: true });
  } catch (err) {
    toast(err.message, "error");
  }
  if (state.step === "auditoria") renderAuditoria();
}

function renderAuditoria() {
  const sel = $("#audit-usuario");
  const escolhido = sel.value;
  sel.innerHTML = `<option value="">Todos</option>` + auditoria.usuarios.map((n) => `<option>${esc(n)}</option>`).join("");
  sel.value = escolhido;
  $("#audit-csv").href = `api/auditoria.csv?${new URLSearchParams({ usuario: escolhido, limite: 20000 })}`;

  const cat = $("#audit-categoria").value;
  const lista = auditoria.eventos.filter((ev) => {
    const c = (TIPOS[ev.tipo] || ["", "admin"])[1];
    return !cat || c === cat || (cat === "admin" && ev.tipo === "ESCALA_CONFIRMADA");
  });
  $("#audit-total").textContent = auditoria.carregado ? plural(lista.length, "evento", "eventos") : "Carregando…";
  const quandoEv = (iso) => `${fmtLonga(iso.slice(0, 10))} ${iso.slice(11, 19)}`;
  $("#audit-linhas").innerHTML = lista.length
    ? lista.map((ev) => {
        const [rotulo, c] = TIPOS[ev.tipo] || [ev.tipo, "admin"];
        return `<tr><td>${quandoEv(ev.quando)}</td><td><strong>${esc(ev.usuario || "—")}</strong></td>
          <td><span class="audit-tipo audit-tipo--${c}">${esc(rotulo)}</span></td>
          <td>${esc(ev.descricao)}</td><td class="muted small">${esc(ev.ip || "")}</td></tr>`;
      }).join("")
    : `<tr><td colspan="5" class="audit-vazio">${auditoria.carregado ? "Nenhum evento com esses filtros." : "Carregando…"}</td></tr>`;
}

$("#audit-usuario").addEventListener("change", carregarAuditoria);
$("#audit-categoria").addEventListener("change", renderAuditoria);

// ---------- Atualização automática ----------
// A cada poucos segundos pergunta ao servidor se os dados mudaram (consulta leve).
// Se mudaram, recarrega e avisa quem fez a alteração.

const vivo = { versao: null, ultimoEvento: null, falhas: 0, rodando: false, ocultaDesde: null };
const chaveEvento = (ev) => ev && `${ev.quando}|${ev.usuario}|${ev.descricao}`;
const RECARREGAR_APOS_OCULTA = 2 * 60 * 1000; // aba escondida por mais tempo volta com a página recarregada

function ocupado() {
  const foco = document.activeElement;
  return !!pintura || !!$("dialog[open]") || gravacoesPendentes > 0
    || (state.step !== "escala" && foco?.matches?.("input, textarea, select"));
}

function setAoVivo(ok) {
  $("#live").classList.toggle("is-off", !ok);
  $("#live-texto").textContent = ok ? "Ao vivo" : "Reconectando…";
}

async function verificarAtualizacoes() {
  if (vivo.rodando) return; // intervalo, foco e volta da aba podem disparar juntos
  vivo.rodando = true;
  try {
    await verificar();
  } finally {
    vivo.rodando = false;
  }
}

async function verificar() {
  let v;
  try {
    v = await api("GET", "api/versao");
    vivo.falhas = 0;
    setAoVivo(true);
  } catch {
    if (++vivo.falhas >= 2) setAoVivo(false);
    return;
  }
  // Outra pessoa entrou neste mesmo navegador: a sessão mudou para todas as abas.
  // Recarrega para a tela assumir o nome e o perfil de quem está logado agora.
  if (v.usuario && v.usuario !== state.usuario.nome) {
    location.reload();
    return;
  }
  // Saiu uma versão nova do sistema: recarrega para não ficar com a tela antiga.
  if (v.app && VERSAO_TELA && v.app !== VERSAO_TELA && !ocupado()) {
    location.reload();
    return;
  }
  if (v.versao === vivo.versao || ocupado()) return; // ocupado: tenta de novo na próxima volta
  const primeira = vivo.versao === null;
  try {
    await carregarEstado(); // na primeira volta também: pega trocas feitas enquanto a tela abria
  } catch {
    return;
  }
  vivo.versao = v.versao;
  const ev = v.ultima;
  const chave = chaveEvento(ev);
  if (!primeira && ev && chave !== vivo.ultimoEvento && ev.usuario !== state.usuario.nome) avisarMudanca(ev);
  vivo.ultimoEvento = chave;
  render();
  if (state.step === "auditoria") carregarAuditoria();
}

/** Aviso de troca feita por outra pessoa, com destaque na posição e atalho para a escala. */
function avisarMudanca(ev) {
  const d = ev.detalhes;
  const outraEscala = d?.escala && d.escala !== state.escalaSel && state.escalas.some((e) => e.periodo.inicio === d.escala);
  const ver = () => { if (outraEscala) escolherEscala(d.escala); irPara("escala"); };
  const onde = outraEscala ? ` (${nomeDoPeriodo(state.escalas.find((e) => e.periodo.inicio === d.escala).periodo)})` : "";
  toast(`${ev.usuario} · ${ev.descricao}${onde}`, "warn",
    state.step !== "escala" || outraEscala ? { rotulo: "Ver escala", fn: ver } : null);
  if (d?.data) {
    const k = chavePos(d.data, d.turno, d.cargo);
    state.recentes.add(k);
    setTimeout(() => state.recentes.delete(k), 6000);
  }
  // ADM com uma revisão aberta: a revisão foi copiada antes desta troca.
  if (ehAdmin() && state.rascunho && ev.tipo === "PLANTAO_ALTERADO") state.finalMudou = ev;
}

function iniciarAtualizacaoAutomatica() {
  // Continua rodando com a aba em segundo plano (o navegador só espaça as consultas).
  setInterval(verificarAtualizacoes, INTERVALO_ATUALIZACAO);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { vivo.ocultaDesde = Date.now(); return; }
    const longe = vivo.ocultaDesde && Date.now() - vivo.ocultaDesde > RECARREGAR_APOS_OCULTA;
    vivo.ocultaDesde = null;
    // Aba que ficou muito tempo escondida (ou "adormecida" pelo navegador) volta recarregada.
    if (longe && !ocupado()) location.reload();
    else verificarAtualizacoes();
  });
  window.addEventListener("focus", verificarAtualizacoes);
  window.addEventListener("online", verificarAtualizacoes);
  window.addEventListener("pageshow", (e) => { if (e.persisted) location.reload(); }); // voltou pelo histórico
  verificarAtualizacoes();
}

// ---------- Sessão ----------

function renderUsuario() {
  const u = state.usuario;
  $("#userbar").hidden = false;
  $("#user-nome").textContent = u.nome;
  $("#user-papel").textContent = u.admin ? "ADM" : "";
  $("#user-avatar").textContent = iniciais(u.nome);
  $$("[data-admin]").forEach((el) => (el.hidden = !u.admin));
  if (!u.admin) $("#hero-sub").textContent = "Consulte a escala e troque profissionais nos plantões. As mudanças aparecem para toda a equipe.";
}

$("#btn-auditoria").addEventListener("click", () => irPara(state.step === "auditoria" ? "escala" : "auditoria"));
$("#btn-sair").addEventListener("click", async () => {
  try { await api("POST", "api/logout"); } catch { /* a sessão termina de qualquer jeito */ }
  location.replace("login?saiu=1");
});

// ---------- ações compartilhadas ----------

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-acao], [data-importar]");
  if (!el || el.disabled) return;
  if (el.hasAttribute("data-importar")) return inputImportar.click();
  ({ "nova-proposta": gerarProposta, "editar-final": editarFinal, descartar: descartarRevisao })[el.dataset.acao]?.();
});
$("#btn-confirmar").addEventListener("click", confirmarEscala);
$("#btn-print").addEventListener("click", () => window.print());

// ===================================================================
// Inicialização
// ===================================================================

$$(".step").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.step)));
$$("[data-goto]").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.goto)));
window.addEventListener("hashchange", () => irPara(location.hash.slice(1)));

(async function init() {
  try {
    state.usuario = await api("GET", "api/eu");
    renderUsuario();
    await carregarEstado();
  } catch (err) {
    toast(`Falha ao carregar dados: ${err.message}`, "error");
    if (!state.usuario) return;
  }
  const inicial = location.hash.slice(1)
    || (!state.periodo ? "periodo" : !prontoParaGerar() ? "equipe" : state.escala ? "escala" : "revisao");
  irPara(inicial);
  iniciarAtualizacaoAutomatica();
})();
