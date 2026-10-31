// ===================================================================
// Escala de Plantão · SAMU 192 — frontend (vanilla JS, sem build)
// ===================================================================

const CARGOS = { ENFERMEIRO: "Enfermeiro(a)", MOTORISTA: "Motorista" };
const STATUS_LABEL = { DISPONIVEL: "Disponível", INDISPONIVEL: "Indisponível", PREFERENCIAL: "Preferencial", FERIAS: "Férias" };
const DOW = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const TURNOS = ["DIA", "NOITE"];
const STEPS = ["periodo", "equipe", "disponibilidade", "escala"];
const MAX_DIAS = 92;

const state = {
  periodo: null,
  funcionarios: [],
  step: "periodo",
  editingId: null,
  filtroCargo: "",
  busca: "",
  dispSelId: null,
  brush: "INDISPONIVEL",
  escala: null,
  escalaStale: false,
  modo: "calendario",
  destaque: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const icon = (id, cls = "ic") => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------- datas (sempre em UTC para não sofrer com horário de verão) ----------

const parseISO = (iso) => new Date(iso + "T00:00:00Z");
const toISO = (d) => d.toISOString().slice(0, 10);
const addDias = (d, n) => new Date(d.getTime() + n * 86400000);
const diaSemana = (d) => (d.getUTCDay() + 6) % 7; // 0 = segunda
const fmtCurta = (iso) => { const [, m, d] = iso.split("-"); return `${d}/${m}`; };
const fmtLonga = (iso) => { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; };

function diasEntre(inicio, fim) {
  const out = [];
  for (let d = parseISO(inicio); d <= parseISO(fim); d = addDias(d, 1)) out.push(toISO(d));
  return out;
}
const diasDoPeriodo = () => (state.periodo ? diasEntre(state.periodo.inicio, state.periodo.fim) : []);
const ehFds = (iso) => diaSemana(parseISO(iso)) >= 5;

// ---------- infraestrutura ----------

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.erro || `Erro ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, tipo = "ok") {
  const el = document.createElement("div");
  el.className = `toast toast--${tipo}`;
  el.innerHTML = `${icon(tipo === "error" ? "alert" : "check")}<span>${esc(msg)}</span>`;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), tipo === "error" ? 5000 : 2600);
}

function confirmar(titulo, texto, ok = "Confirmar") {
  const dlg = $("#modal-confirm");
  $("#modal-titulo").textContent = titulo;
  $("#modal-texto").textContent = texto;
  $("#modal-ok").textContent = ok;
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
const porId = (id) => state.funcionarios.find((f) => f.id === id);

function marcarEscalaDesatualizada() {
  if (state.escala) state.escalaStale = true;
}

// ---------- navegação ----------

function irPara(step) {
  if (!STEPS.includes(step)) step = "periodo";
  state.step = step;
  if (location.hash !== `#${step}`) history.replaceState(null, "", `#${step}`);
  STEPS.forEach((s) => ($(`#view-${s}`).hidden = s !== step));
  window.scrollTo({ top: Math.min(window.scrollY, $(".hero").offsetHeight), behavior: "smooth" });
  if (step === "escala" && !state.escala && prontoParaGerar()) gerarEscala();
  render();
}

function prontoParaGerar() {
  return state.periodo && Object.keys(CARGOS).every((c) => state.funcionarios.some((f) => f.cargo === c));
}

function renderStepper() {
  const feito = {
    periodo: !!state.periodo,
    equipe: prontoParaGerar(),
    disponibilidade: state.funcionarios.some((f) => Object.keys(f.disponibilidade).length),
    escala: !!state.escala && !state.escalaStale,
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
  if (state.periodo) {
    const n = diasDoPeriodo().length;
    chips.push(`${icon("calendar")}${fmtCurta(state.periodo.inicio)} – ${fmtCurta(state.periodo.fim)} · ${n} dias`);
  }
  const n = (c) => state.funcionarios.filter((f) => f.cargo === c).length;
  if (state.funcionarios.length) chips.push(`${icon("users")}${n("ENFERMEIRO")} enfermeiros · ${n("MOTORISTA")} motoristas`);
  if (state.escala) chips.push(`${icon("ambulance")}Cobertura ${Math.round(state.escala.cobertura * 100)}%`);
  $("#hero-chips").innerHTML = chips.map((c) => `<span class="hero__chip">${c}</span>`).join("");
}

function render() {
  renderStepper();
  renderHero();
  ({ periodo: renderPeriodo, equipe: renderEquipe, disponibilidade: renderDisponibilidade, escala: renderEscala })[state.step]();
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
    if (mudou) { state.escala = null; state.escalaStale = false; }
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
  const linhas = Object.entries(CARGOS).map(([cargo, rotulo]) => {
    const n = state.funcionarios.filter((f) => f.cargo === cargo).length;
    const media = n && dias ? ` · ≈ ${Math.round((dias * 2) / n)} plantões cada` : "";
    if (n >= 3) return `<div class="health__row ok">${icon("check")}${n} ${rotulo.toLowerCase()}${n > 1 ? "s" : ""}${media}</div>`;
    const msg = n === 0 ? `Nenhum ${rotulo.toLowerCase()} — turnos ficarão vagos` : `Só ${n} ${rotulo.toLowerCase()} — recomendado 3 ou mais para garantir descanso`;
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
    marcarEscalaDesatualizada();
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
      marcarEscalaDesatualizada();
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
  const grupos = Object.entries(CARGOS).map(([cargo, rotulo]) => {
    const itens = state.funcionarios.filter((f) => f.cargo === cargo).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
    if (!itens.length) return "";
    return `<li class="group-title" role="presentation">${rotulo}s</li>` + itens.map((f) => {
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
  marcarEscalaDesatualizada();
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
// 4. ESCALA
// ===================================================================

async function gerarEscala() {
  const btn = $("#btn-gerar");
  btn.classList.add("is-loading");
  try {
    state.escala = await api("POST", "api/escala");
    state.escalaStale = false;
    state.destaque = null;
    const v = state.escala.vagas.length;
    toast(v ? `Escala gerada com ${v} vaga${v > 1 ? "s" : ""} em aberto` : "Escala gerada com cobertura total", v ? "error" : "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.classList.remove("is-loading");
    render();
  }
}

function renderEscala() {
  const r = state.escala;
  $("#escala-vazia").hidden = !!r;
  $("#escala-conteudo").hidden = !r;
  $("#banner-stale").hidden = !(r && state.escalaStale);
  $("#btn-print").disabled = !r;
  $("#btn-pdf").setAttribute("aria-disabled", String(!r));
  if (!r) return;
  renderKpis(r);
  renderAlertas(r);
  $$("#modo-escala .tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.modo === state.modo)));
  $("#escala-view").innerHTML = state.modo === "calendario" ? calendarioEscalaHTML(r) : listaEscalaHTML(r);
  renderEstatisticas(r);
  aplicarDestaque();
}

function equilibrio(r) {
  return Math.max(0, ...Object.keys(CARGOS).map((c) => {
    const t = r.estatisticas.filter((s) => s.cargo === c).map((s) => s.total);
    return t.length ? Math.max(...t) - Math.min(...t) : 0;
  }));
}

function renderKpis(r) {
  const cob = Math.round(r.cobertura * 100);
  const preenchidos = r.plantoes.length * 2 - r.vagas.length;
  const eq = equilibrio(r);
  const kpi = (rotulo, valor, dica, tom) =>
    `<div class="kpi ${tom}"><div class="kpi__label">${rotulo}</div><div class="kpi__value">${valor}</div><div class="kpi__hint">${dica}</div></div>`;
  $("#kpis").innerHTML = [
    kpi("Cobertura", `${cob}%`, "posições preenchidas", cob === 100 ? "is-good" : "is-bad"),
    kpi("Vagas em aberto", r.vagas.length, r.vagas.length ? "precisam de ajuste manual" : "nenhuma", r.vagas.length ? "is-bad" : "is-good"),
    kpi("Plantões escalados", preenchidos, `${r.plantoes.length} turnos × 2 profissionais`, ""),
    kpi("Equilíbrio", eq <= 1 ? "Ótimo" : `±${eq}`, "diferença máx. de plantões no cargo", eq <= 1 ? "is-good" : eq <= 3 ? "is-warn" : "is-bad"),
  ].join("");
}

function renderAlertas(r) {
  const out = [];
  if (r.vagas.length) {
    const itens = r.vagas.map((v) =>
      `<li><strong>${fmtCurta(v.data)} ${DOW[diaSemana(parseISO(v.data))]} · ${v.turno}</strong> — ${CARGOS[v.cargo]}: ${esc(v.motivo)}</li>`).join("");
    out.push(`<div class="alert">${icon("alert")}<div><strong>${r.vagas.length} posição(ões) sem profissional.</strong>
      Revise as indisponibilidades ou amplie a equipe.<ul>${itens}</ul></div></div>`);
  } else {
    out.push(`<div class="alert alert--ok">${icon("check")}Todos os turnos têm enfermeiro(a) e motorista.</div>`);
  }
  const ociosos = r.estatisticas.filter((s) => s.total === 0);
  if (ociosos.length) {
    out.push(`<div class="alert">${icon("alert")}<div><strong>Sem plantões no período:</strong> ${ociosos.map((s) => esc(s.nome)).join(", ")}</div></div>`);
  }
  $("#alertas").innerHTML = out.join("");
}

const pessoaHTML = (p, rotulo) =>
  p ? `<span class="shift__p" data-pid="${p.id}" title="${rotulo}: ${esc(p.nome)}">${rotulo[0]} · ${esc(p.nome)}</span>`
    : `<span class="shift__p vago">${rotulo[0]} · VAGO</span>`;

function calendarioEscalaHTML(r) {
  const porDia = new Map();
  r.plantoes.forEach((p) => {
    if (!porDia.has(p.data)) porDia.set(p.data, []);
    porDia.get(p.data).push(p);
  });
  const dias = [...porDia.keys()];
  const vazios = diaSemana(parseISO(dias[0]));
  return `<div class="sched" id="sched">
    ${DOW.map((d, i) => `<div class="cal__dow ${i >= 5 ? "is-weekend" : ""}">${d}</div>`).join("")}
    ${"<div></div>".repeat(vazios)}
    ${dias.map((dia) => `
      <div class="sday ${ehFds(dia) ? "is-weekend" : ""}">
        <div class="sday__date">${fmtCurta(dia)}<small class="muted">${DOW[diaSemana(parseISO(dia))]}</small></div>
        ${porDia.get(dia).map((p) => `
          <div class="shift shift--${p.turno}">
            <span class="shift__h">${icon(p.turno === "DIA" ? "sun" : "moon")}${p.turno}</span>
            ${pessoaHTML(p.enfermeiro, "Enfermeiro(a)")}
            ${pessoaHTML(p.motorista, "Motorista")}
          </div>`).join("")}
      </div>`).join("")}
  </div>`;
}

function listaEscalaHTML(r) {
  const nome = (p) => (p ? `<span class="shift__p" data-pid="${p.id}">${esc(p.nome)}</span>` : `<span class="vago">VAGO</span>`);
  return `<div class="table-wrap"><table>
    <thead><tr><th>Data</th><th>Turno</th><th>Enfermeiro(a)</th><th>Motorista</th></tr></thead>
    <tbody>${r.plantoes.map((p) => `
      <tr class="${ehFds(p.data) ? "is-weekend" : ""}">
        <td>${fmtLonga(p.data)} · ${DOW[diaSemana(parseISO(p.data))]}</td>
        <td><span class="turno-pill">${icon(p.turno === "DIA" ? "sun" : "moon")}${p.turno}</span></td>
        <td>${nome(p.enfermeiro)}</td><td>${nome(p.motorista)}</td>
      </tr>`).join("")}</tbody></table></div>`;
}

function renderEstatisticas(r) {
  const max = Math.max(1, ...r.estatisticas.map((s) => s.total));
  $("#estatisticas").innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Profissional</th><th>Plantões</th>
      <th><span class="legend-inline"><span><i style="background:var(--orange)"></i>Dia</span><span><i style="background:var(--navy-700)"></i>Noite</span></span></th>
      <th>Fins de semana</th><th>Preferências atendidas</th></tr></thead>
    <tbody>${r.estatisticas.map((s) => `
      <tr class="stats-row ${state.destaque === s.id ? "is-active" : ""}" data-id="${s.id}" tabindex="0">
        <td><div class="person" style="padding:0">${avatar(s)}<div class="person__info"><div class="person__name">${esc(s.nome)}</div>
          <div class="person__meta"><span class="badge c-${s.cargo}">${CARGOS[s.cargo]}</span></div></div></div></td>
        <td><strong>${s.total}</strong></td>
        <td><div class="bar" style="width:${Math.max(30, (s.total / max) * 100)}%" title="${s.dias} dia · ${s.noites} noite">
          <span class="bar__d" style="flex:${s.dias}"></span><span class="bar__n" style="flex:${s.noites}"></span></div>
          <span class="muted small">${s.dias} dia · ${s.noites} noite</span></td>
        <td>${s.fins_de_semana}</td>
        <td>${s.preferenciais_atendidas}</td>
      </tr>`).join("")}</tbody></table></div>`;
}

function aplicarDestaque() {
  const id = state.destaque;
  $("#sched")?.classList.toggle("has-highlight", !!id);
  $$("#escala-view [data-pid]").forEach((el) => el.classList.toggle("is-highlighted", el.dataset.pid === id));
  $$("#escala-view .shift").forEach((el) => el.classList.toggle("has-hit", !!id && !!el.querySelector(`[data-pid="${id}"]`)));
  $$(".stats-row").forEach((tr) => tr.classList.toggle("is-active", tr.dataset.id === id));
  const s = id && state.escala.estatisticas.find((x) => x.id === id);
  $("#destaque-info").textContent = s ? `Destacando ${s.nome} · ${s.total} plantões` : "";
}

$("#btn-gerar").addEventListener("click", gerarEscala);
$("#btn-regerar").addEventListener("click", gerarEscala);
$("#btn-print").addEventListener("click", () => window.print());
$("#modo-escala").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (tab) { state.modo = tab.dataset.modo; renderEscala(); }
});
$("#estatisticas").addEventListener("click", (e) => {
  const tr = e.target.closest(".stats-row");
  if (!tr) return;
  state.destaque = state.destaque === tr.dataset.id ? null : tr.dataset.id;
  aplicarDestaque();
  if (state.destaque) $("#escala-view").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#estatisticas").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches(".stats-row")) e.target.click();
});

// ===================================================================
// Inicialização
// ===================================================================

async function carregarEstado() {
  const dados = await api("GET", "api/estado");
  state.periodo = dados.periodo;
  state.funcionarios = dados.funcionarios;
}

$$(".step").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.step)));
$$("[data-goto]").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.goto)));
window.addEventListener("hashchange", () => irPara(location.hash.slice(1)));

(async function init() {
  try {
    await carregarEstado();
  } catch (err) {
    toast(`Falha ao carregar dados: ${err.message}`, "error");
  }
  const inicial = location.hash.slice(1) || (!state.periodo ? "periodo" : !prontoParaGerar() ? "equipe" : "escala");
  irPara(inicial);
})();
