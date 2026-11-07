// Previsão do tempo no topo da página, pela API pública da Open-Meteo (sem chave).
// Sempre a previsão de Tubarão-SC.

const CIDADE = { nome: "Tubarão-SC", lat: -28.4667, lon: -49.0069 };
const ATUALIZAR_MS = 30 * 60 * 1000;

const el = document.getElementById("clima");

// Códigos WMO usados pela Open-Meteo.
const TEMPO = {
  0: ["Céu limpo", "☀️", "🌙"], 1: ["Poucas nuvens", "🌤️", "🌙"], 2: ["Parcialmente nublado", "⛅", "☁️"],
  3: ["Nublado", "☁️"], 45: ["Neblina", "🌫️"], 48: ["Neblina", "🌫️"],
  51: ["Garoa fraca", "🌦️"], 53: ["Garoa", "🌦️"], 55: ["Garoa forte", "🌧️"],
  56: ["Garoa congelante", "🌧️"], 57: ["Garoa congelante", "🌧️"],
  61: ["Chuva fraca", "🌦️"], 63: ["Chuva", "🌧️"], 65: ["Chuva forte", "🌧️"],
  66: ["Chuva congelante", "🌧️"], 67: ["Chuva congelante", "🌧️"],
  71: ["Neve fraca", "🌨️"], 73: ["Neve", "🌨️"], 75: ["Neve forte", "🌨️"], 77: ["Neve", "🌨️"],
  80: ["Pancadas de chuva", "🌦️"], 81: ["Pancadas de chuva", "🌧️"], 82: ["Pancadas fortes", "⛈️"],
  85: ["Neve", "🌨️"], 86: ["Neve forte", "🌨️"],
  95: ["Trovoadas", "⛈️"], 96: ["Trovoadas com granizo", "⛈️"], 99: ["Trovoadas com granizo", "⛈️"],
};
const tempo = (cod, dia = 1) => {
  const [txt, iconeDia, iconeNoite] = TEMPO[cod] || ["—", "🌡️"];
  return { txt, icone: !dia && iconeNoite ? iconeNoite : iconeDia };
};
const DOW = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const graus = (v) => `${Math.round(v)}°`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function buscar(local) {
  const p = new URLSearchParams({
    latitude: local.lat.toFixed(4), longitude: local.lon.toFixed(4), timezone: "auto", forecast_days: "4",
    current: "temperature_2m,weather_code,is_day",
    daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
  });
  const r = await fetch(`https://api.open-meteo.com/v1/forecast?${p}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function render(local, d) {
  const agora = tempo(d.current.weather_code, d.current.is_day);
  const dd = d.daily;
  const chuva = dd.precipitation_probability_max[0];
  const proximos = dd.time.slice(1, 4).map((t, i) => {
    const k = i + 1;
    const { txt, icone } = tempo(dd.weather_code[k]);
    return `<li title="${esc(txt)}"><span>${DOW[new Date(`${t}T12:00`).getDay()]}</span>
      <span aria-hidden="true">${icone}</span><b>${graus(dd.temperature_2m_max[k])}</b><small>${graus(dd.temperature_2m_min[k])}</small></li>`;
  }).join("");
  el.innerHTML = `
    <div class="clima__agora">
      <span class="clima__icone" aria-hidden="true">${agora.icone}</span>
      <span class="clima__temp">${graus(d.current.temperature_2m)}</span>
      <span class="clima__info">
        <span><span class="clima__local">${esc(local.nome)}</span> · ${esc(agora.txt)}</span>
        <span>Hoje ${graus(dd.temperature_2m_max[0])} / ${graus(dd.temperature_2m_min[0])}${chuva != null ? ` · chuva ${chuva}%` : ""}</span>
      </span>
    </div>
    <ul class="clima__dias" aria-label="Próximos dias">${proximos}</ul>`;
  el.hidden = false;
}

async function atualizar() {
  const local = CIDADE;
  try {
    render(local, await buscar(local));
  } catch {
    // Sem internet ou API fora do ar: o topo continua funcionando sem a previsão.
    if (!el.innerHTML.trim()) el.hidden = true;
  }
}

if (el) {
  atualizar();
  setInterval(atualizar, ATUALIZAR_MS);
}
