"use strict";

const $ = (s) => document.querySelector(s);
let token = null;
let ultimaPropina = null;

function mostrar(el, texto, ok = true) {
  el.textContent = texto;
  el.className = "resultado " + (ok ? "ok" : "error");
}

async function api(ruta, opciones = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  const r = await fetch(ruta, { ...opciones, headers });
  const datos = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) {
    const det = datos?.detail;
    throw new Error(Array.isArray(det) ? "Revisa los datos: " + det.map((d) => d.loc.at(-1)).join(", ") : det || "Error");
  }
  return datos;
}

function datosForm(form) {
  return Object.fromEntries(new FormData(form).entries());
}

// Pestañas
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab, .panel").forEach((e) => e.classList.remove("activo"));
    b.classList.add("activo");
    $("#" + b.dataset.tab).classList.add("activo");
  })
);

// HU01 – Registro
$("#form-registro").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/trabajadores", { method: "POST", body: JSON.stringify(datosForm(e.target)) });
    mostrar($("#resultado-registro"), `${r.mensaje} Tu código personal es: ${r.qr_token} (guárdalo).`);
    e.target.reset();
  } catch (err) { mostrar($("#resultado-registro"), err.message, false); }
});

// HU05 + HU07 – Mi QR e historial
$("#form-mi-qr").addEventListener("submit", async (e) => {
  e.preventDefault();
  const t = encodeURIComponent(datosForm(e.target).token.trim());
  const cont = $("#mi-qr");
  cont.replaceChildren();
  try {
    const h = await api(`/api/trabajadores/token/${t}/propinas`);
    const qr = document.createElement("div");
    qr.className = "qr";
    const img = document.createElement("img");
    img.alt = "Mi código QR";
    img.src = `/api/qr/${t}.svg`;
    img.onerror = () => { qr.textContent = "Tu QR estará disponible cuando un promotor valide tu registro."; };
    qr.append(img);
    const res = document.createElement("p");
    res.textContent = `${h.trabajador} · Hoy: S/ ${h.total_hoy.toFixed(2)} · Semana: S/ ${h.total_semana.toFixed(2)} · ${h.propinas.length} propinas`;
    cont.append(qr, res);
  } catch (err) { mostrar(cont, err.message, false); }
});

// HU06 – Propina
const inputQr = $("#form-propina [name=qr_token]");
async function cargarTrabajador() {
  const t = inputQr.value.trim();
  if (t.length < 10) return;
  try {
    const d = await api(`/api/qr/${encodeURIComponent(t)}`);
    $("#datos-trabajador").textContent = `Vas a apoyar a ${d.nombre} (${d.cruce})`;
  } catch { $("#datos-trabajador").textContent = "El código no es válido."; }
}
inputQr.addEventListener("change", cargarTrabajador);

$("#form-propina").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = datosForm(e.target);
  try {
    const r = await api("/api/propinas", { method: "POST", body: JSON.stringify({ ...d, monto: Number(d.monto) }) });
    ultimaPropina = r.id;
    mostrar($("#resultado-propina"), r.mensaje);
    $("#calificar").classList.remove("oculto");
  } catch (err) { mostrar($("#resultado-propina"), err.message, false); }
});

// HU08 – Calificación
document.querySelectorAll(".estrellas button").forEach((b) =>
  b.addEventListener("click", async () => {
    if (!ultimaPropina) return;
    try {
      await api(`/api/propinas/${ultimaPropina}/calificacion`, { method: "POST", body: JSON.stringify({ estrellas: Number(b.dataset.e) }) });
      mostrar($("#resultado-propina"), "¡Gracias por tu calificación!");
    } catch (err) { mostrar($("#resultado-propina"), err.message, false); }
    $("#calificar").classList.add("oculto");
  })
);

// HU12 – Reporte de menor
$("#form-alerta").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/alertas", { method: "POST", body: JSON.stringify({ tipo: "menor", ...datosForm(e.target) }) });
    mostrar($("#resultado-alerta"), `${r.mensaje} Código de seguimiento: ${r.codigo_seguimiento}`);
    e.target.reset();
  } catch (err) { mostrar($("#resultado-alerta"), err.message, false); }
});

// Promotor – login, panel (HU15), validación (HU03), alertas (HU13)
$("#form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/auth/login", { method: "POST", body: JSON.stringify(datosForm(e.target)) });
    token = r.access_token;
    e.target.classList.add("oculto");
    $("#zona-promotor").classList.remove("oculto");
    await refrescar();
  } catch (err) { mostrar($("#resultado-promotor"), err.message, false); }
});

function boton(texto, accion, clase = "") {
  const b = document.createElement("button");
  b.textContent = texto;
  if (clase) b.className = clase;
  b.addEventListener("click", accion);
  return b;
}

async function refrescar() {
  const [p, pend, alertas] = await Promise.all([
    api("/api/panel"), api("/api/trabajadores?estado=pendiente"), api("/api/alertas"),
  ]);
  const kpis = [["Trabajadores", p.total_trabajadores], ["Pendientes", p.pendientes_validacion],
    ["Alertas abiertas", p.alertas_abiertas], ["Propinas (S/)", p.propinas_total.toFixed(2)]];
  $("#kpis").replaceChildren(...kpis.map(([t, v]) => {
    const d = document.createElement("div"); d.className = "kpi";
    const b = document.createElement("b"); b.textContent = v;
    d.append(b, t); return d;
  }));
  $("#tabla-cruces tbody").replaceChildren(...p.por_cruce.map((c) => {
    const tr = document.createElement("tr");
    [c.cruce, c.trabajadores, c.validados, c.alertas_abiertas, c.propinas_total.toFixed(2)].forEach((v) => {
      const td = document.createElement("td"); td.textContent = v; tr.append(td);
    });
    return tr;
  }));
  $("#pendientes").replaceChildren(...pend.map((t) => {
    const li = document.createElement("li");
    li.append(`${t.nombres} · ${t.tipo_documento} ${t.documento_enmascarado} · ${t.cruce}`);
    const acciones = document.createElement("div");
    acciones.append(
      boton("Aprobar", () => validar(t.id, true)),
      boton("Rechazar", () => validar(t.id, false), "alerta"));
    li.append(acciones);
    return li;
  }));
  $("#alertas").replaceChildren(...alertas.map((a) => {
    const li = document.createElement("li");
    li.append(`${a.codigo_seguimiento} · ${a.tipo} · ${a.cruce} · ${a.estado}${a.derivada_por ? " por " + a.derivada_por : ""}`);
    if (a.estado !== "derivada") li.append(boton("Derivar a DEMUNA", () => derivar(a.id)));
    return li;
  }));
}

async function validar(id, aprobar) {
  const motivo = aprobar ? null : prompt("Motivo del rechazo:");
  if (!aprobar && !motivo) return;
  try {
    await api(`/api/trabajadores/${id}/validacion`, { method: "POST", body: JSON.stringify({ aprobar, motivo }) });
    await refrescar();
  } catch (err) { mostrar($("#resultado-promotor"), err.message, false); }
}

async function derivar(id) {
  const observaciones = prompt("Observaciones para la DEMUNA:");
  if (!observaciones) return;
  try {
    await api(`/api/alertas/${id}/derivar`, { method: "POST", body: JSON.stringify({ observaciones }) });
    await refrescar();
  } catch (err) { mostrar($("#resultado-promotor"), err.message, false); }
}

// Si el QR se escaneó (/?t=...), abrir directamente la pestaña de propina.
const t = new URLSearchParams(location.search).get("t");
if (t) {
  document.querySelector('[data-tab="conductor"]').click();
  inputQr.value = t;
  cargarTrabajador();
}
