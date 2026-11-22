"use strict";
/* Semáforo Solidario — cliente web.
   Sin dependencias externas: compatible con la política CSP del servidor (solo recursos propios). */

const $ = (s, raiz = document) => raiz.querySelector(s);
const $$ = (s, raiz = document) => [...raiz.querySelectorAll(s)];
const soles = (n) => "S/ " + Number(n).toFixed(2);
const HORARIOS = { manana: "mañana", tarde: "tarde", noche: "noche" };
const fecha = (iso, conHora = true) => {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString("es-PE", conHora
    ? { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "long", year: "numeric" });
};

/* ---------- Sesiones (se guardan solo en esta pestaña) ---------- */
const sesion = {
  get(clave) { try { return sessionStorage.getItem(clave); } catch { return null; } },
  set(clave, valor) { try { sessionStorage.setItem(clave, valor); } catch { /* sin almacenamiento */ } },
  borrar(clave) { try { sessionStorage.removeItem(clave); } catch { /* sin almacenamiento */ } },
};

async function api(ruta, { metodo = "GET", datos, token } = {}) {
  const headers = {};
  if (datos !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = "Bearer " + token;
  let r;
  try {
    r = await fetch(ruta, { method: metodo, headers, body: datos === undefined ? undefined : JSON.stringify(datos) });
  } catch {
    throw Object.assign(new Error("Sin conexión. Revisa tu internet e inténtalo otra vez."), { status: 0 });
  }
  const cuerpo = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) {
    const det = cuerpo?.detail;
    const texto = Array.isArray(det)
      ? "Revisa estos datos: " + [...new Set(det.map((d) => CAMPOS[d.loc.at(-1)] || d.loc.at(-1)))].join(", ")
      : det || "No se pudo completar la acción.";
    throw Object.assign(new Error(texto), { status: r.status });
  }
  return cuerpo;
}
const CAMPOS = { numero_documento: "número de documento", nombres: "nombres", celular: "celular",
  fecha_nacimiento: "fecha de nacimiento", cruce: "cruce", codigo: "código", password: "contraseña",
  usuario: "usuario", monto: "monto", qr_token: "código del trabajador", elementos: "elementos" };

function avisar(el, texto, ok = true) {
  el.textContent = texto;
  el.className = "mensaje " + (ok ? "ok" : "error");
}
const datosDe = (form) => Object.fromEntries(new FormData(form).entries());

async function conEnvio(form, accion) {
  const boton = $("button[type=submit]", form);
  if (boton) boton.disabled = true;
  try { await accion(); } finally { if (boton) boton.disabled = false; }
}

function el(etiqueta, props = {}, ...hijos) {
  const n = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props)) {
    if (k === "on") Object.entries(v).forEach(([ev, fn]) => n.addEventListener(ev, fn));
    else if (k === "class") n.className = v;
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  n.append(...hijos.flat().filter((h) => h !== null && h !== undefined && h !== false));
  return n;
}
const vacio = (texto) => el("li", { class: "vacio" }, texto);

/* Diálogo para pedir un texto (reemplaza prompt()) */
function pedirTexto(titulo, etiqueta, boton) {
  const d = $("#dialogo");
  $("#dialogo-titulo").textContent = titulo;
  $("#dialogo-etiqueta").textContent = etiqueta;
  $("#dialogo-ok").textContent = boton;
  const area = $("textarea", d);
  area.value = "";
  d.showModal();
  return new Promise((resolver) => {
    d.addEventListener("close", () => resolver(d.returnValue === "ok" ? area.value.trim() : null), { once: true });
  });
}

/* Pestañas genéricas: botones con data-sec que muestran un .seccion */
function activarSecciones(nav, alCambiar) {
  $$("button[data-sec]", nav).forEach((b) => b.addEventListener("click", () => {
    $$("button[data-sec]", nav).forEach((o) => {
      o.removeAttribute("aria-current");
      $("#" + o.dataset.sec).hidden = true;
    });
    b.setAttribute("aria-current", "true");
    $("#" + b.dataset.sec).hidden = false;
    alCambiar?.(b.dataset.sec);
  }));
}

/* ---------- Navegación por vistas ---------- */
function mostrarVista() {
  const ruta = (location.hash.slice(1) || "inicio").split("?")[0];
  const vista = $$(".vista").some((v) => v.dataset.vista === ruta) ? ruta : "inicio";
  $$(".vista").forEach((v) => { v.hidden = v.dataset.vista !== vista; });
  $$(".roles a").forEach((a) => {
    if (a.dataset.ruta === vista) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  if (vista === "inicio") cargarCifras();
  if (vista === "trabajador") iniciarTrabajador();
  if (vista === "equipo") iniciarEquipo();
  $("#contenido").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", mostrarVista);

async function cargarCifras() {
  try {
    const e = await api("/api/estadisticas");
    $("#cifras").textContent = e.trabajadores_validados
      ? `Hoy acompañamos a ${e.trabajadores_validados} ${e.trabajadores_validados === 1 ? "persona" : "personas"} en `
        + `${e.cruces} ${e.cruces === 1 ? "cruce" : "cruces"}, con ${soles(e.propinas_total)} en propinas digitales `
        + `y ${e.alertas_atendidas} ${e.alertas_atendidas === 1 ? "alerta atendida" : "alertas atendidas"}.`
      : "El piloto empieza ahora: los primeros registros se están validando.";
  } catch { $("#cifras").textContent = ""; }
}

/* =====================================================================
   TRABAJADOR — HU01 registro, HU02 OTP, HU04 cruce, HU05 QR, HU07 propinas,
   HU09 programas, HU10 cursos y empleo, HU14 emergencia
   ===================================================================== */
let celularOtp = null;

$$(".pestanas button").forEach((b) => b.addEventListener("click", () => {
  $$(".pestanas button").forEach((o) => {
    o.setAttribute("aria-selected", String(o === b));
    $("#" + o.dataset.pestana).hidden = o !== b;
  });
}));

$("#form-registro").addEventListener("submit", (e) => {
  e.preventDefault();
  const msj = $("#t-registro-msj");
  conEnvio(e.target, async () => {
    try {
      const datos = datosDe(e.target);
      await api("/api/trabajadores", { metodo: "POST", datos });
      avisar(msj, "Listo, recibimos tu registro. Un promotor social revisará tus datos; mientras tanto ya puedes ingresar con tu celular.");
      $("#form-otp-pedir [name=celular]").value = datos.celular;
      e.target.reset();
    } catch (err) { avisar(msj, err.message, false); }
  });
});

$("#form-otp-pedir").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      celularOtp = datosDe(e.target).celular;
      const r = await api("/api/auth/otp/solicitar", { metodo: "POST", datos: { celular: celularOtp } });
      $("#otp-aviso").textContent = r.codigo_demo
        ? `Modo demostración (sin SMS): tu código es ${r.codigo_demo}. Vence en 5 minutos.`
        : `${r.mensaje} Vence en 5 minutos.`;
      e.target.hidden = true;
      $("#form-otp-verificar").hidden = false;
      $("#form-otp-verificar [name=codigo]").focus();
      avisar($("#t-ingresar-msj"), "");
    } catch (err) { avisar($("#t-ingresar-msj"), err.message, false); }
  });
});

$("#otp-otro").addEventListener("click", () => {
  $("#form-otp-verificar").hidden = true;
  $("#form-otp-verificar").reset();
  $("#form-otp-pedir").hidden = false;
});

$("#form-otp-verificar").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      const r = await api("/api/auth/otp/verificar",
        { metodo: "POST", datos: { celular: celularOtp, codigo: datosDe(e.target).codigo } });
      sesion.set("trabajador", r.access_token);
      e.target.reset();
      e.target.hidden = true;
      $("#form-otp-pedir").hidden = false;
      avisar($("#t-ingresar-msj"), "");
      iniciarTrabajador();
    } catch (err) { avisar($("#t-ingresar-msj"), err.message, false); }
  });
});

$("#t-salir").addEventListener("click", () => { sesion.borrar("trabajador"); iniciarTrabajador(); });

const tTok = () => sesion.get("trabajador");
let perfil = null;

async function iniciarTrabajador() {
  const hay = Boolean(tTok());
  $("#t-acceso").hidden = hay;
  $("#t-app").hidden = !hay;
  if (!hay) return;
  try {
    perfil = await api("/api/mi/perfil", { token: tTok() });
  } catch (err) {
    if (err.status === 401) { sesion.borrar("trabajador"); return iniciarTrabajador(); }
    return avisar($("#t-msj"), err.message, false);
  }
  $("#t-nombre").textContent = "Hola, " + perfil.nombres.split(" ")[0];
  const estado = $("#t-estado");
  estado.dataset.estado = perfil.estado;
  estado.textContent = {
    validado: `Cuenta validada. Trabajas en ${perfil.cruce}, turno ${HORARIOS[perfil.horario]}.`,
    pendiente: "Tu registro está en revisión. Cuando un promotor lo valide se activará tu QR.",
    rechazado: "Tu registro fue observado: " + (perfil.motivo_rechazo || ""),
  }[perfil.estado];
  const validado = perfil.estado === "validado";
  $$("#t-app .secciones button").forEach((b) => { b.disabled = !validado && b.dataset.sec !== "sec-qr"; });
  $("#sos").hidden = false;
  pintarQr();
  cargarSeccionTrabajador($("#t-app .secciones [aria-current]").dataset.sec);
}

activarSecciones($("#t-app .secciones"), cargarSeccionTrabajador);

async function cargarSeccionTrabajador(sec) {
  if (!perfil) return;
  try {
    if (sec === "sec-qr") await pintarResumen();
    if (sec === "sec-propinas") await pintarPropinas();
    if (sec === "sec-programas") await pintarProgramas();
    if (sec === "sec-cursos") await pintarCursos();
    if (sec === "sec-cruce") pintarCruce();
  } catch (err) { avisar($("#t-msj"), err.message, false); }
}

function pintarQr() {
  const marco = $("#qr-marco");
  const descargar = $("#qr-descargar");
  if (perfil.qr_token) {
    const url = `/api/qr/${encodeURIComponent(perfil.qr_token)}.svg`;
    marco.replaceChildren(el("img", { src: url, alt: "Código QR para recibir propinas" }));
    descargar.href = url;
    descargar.hidden = false;
  } else {
    marco.replaceChildren(el("p", {}, "Tu QR aparecerá aquí cuando tu registro sea validado."));
    descargar.hidden = true;
  }
}

async function pintarResumen() {
  const caja = $("#t-resumen");
  if (perfil.estado !== "validado") return caja.replaceChildren();
  const h = await api("/api/mi/propinas", { token: tTok() });
  const dato = (t, v) => el("div", {}, el("dt", {}, t), el("dd", {}, v));
  caja.replaceChildren(
    dato("Hoy", soles(h.total_hoy)),
    dato("Esta semana", soles(h.total_semana)),
    dato("Propinas recibidas", String(h.propinas.length)),
    dato("Calificación", perfil.calificacion_promedio ? `${perfil.calificacion_promedio} ★` : "Sin calificar"),
  );
}

async function pintarPropinas() {
  const h = await api("/api/mi/propinas", { token: tTok() });
  $("#t-propinas").replaceChildren(...(h.propinas.length
    ? h.propinas.map((p) => el("li", {},
      el("span", {}, `${fecha(p.creado_en)}, por ${p.billetera === "yape" ? "Yape" : "Plin"}`),
      el("b", {}, soles(p.monto))))
    : [vacio("Aún no hay movimientos. Muestra tu QR a los conductores para recibir tu primera propina digital.")]));
}

async function pintarProgramas() {
  const lista = await api("/api/mi/programas", { token: tTok() });
  $("#t-programas").replaceChildren(...(lista.length ? lista.map((p) => el("li", {},
    el("h3", {}, p.nombre),
    el("p", {}, p.descripcion),
    el("p", { class: "nota" }, `Requisitos: ${p.requisitos} Dónde: ${p.lugar}.`),
    p.solicitado
      ? el("span", { class: "etiqueta", dataset: { tono: "verde" } }, "Orientación solicitada")
      : el("div", { class: "acciones" }, el("button", { class: "secundario", type: "button", on: { click: async (ev) => {
        ev.target.disabled = true;
        try {
          const r = await api(`/api/mi/programas/${p.id}/solicitud`, { metodo: "POST", token: tTok() });
          avisar($("#t-msj"), r.mensaje);
          await pintarProgramas();
        } catch (err) { ev.target.disabled = false; avisar($("#t-msj"), err.message, false); }
      } } }, "Quiero inscribirme")),
  )) : [vacio("Por ahora no hay programas para tu perfil.")]));
}

async function pintarCursos() {
  const [cursos, empleos] = await Promise.all([
    api("/api/mi/capacitaciones", { token: tTok() }), api("/api/mi/empleos", { token: tTok() })]);
  $("#t-cursos").replaceChildren(...cursos.map((c) => {
    let accion;
    if (c.mi_estado === "inscrito") accion = el("span", { class: "etiqueta", dataset: { tono: "verde" } }, "Inscrito");
    else if (c.mi_estado === "espera") accion = el("span", { class: "etiqueta", dataset: { tono: "ambar" } }, "En lista de espera");
    else {
      const lleno = c.cupos_disponibles === 0;
      accion = el("div", { class: "acciones" }, el("button", { class: "secundario", type: "button", on: { click: async (ev) => {
        ev.target.disabled = true;
        try {
          const r = await api(`/api/mi/capacitaciones/${c.id}/inscripcion`,
            { metodo: "POST", datos: { lista_espera: lleno }, token: tTok() });
          avisar($("#t-msj"), r.mensaje);
          await pintarCursos();
        } catch (err) { ev.target.disabled = false; avisar($("#t-msj"), err.message, false); }
      } } }, lleno ? "Anotarme en lista de espera" : "Inscribirme"));
    }
    return el("li", { dataset: { tono: c.mi_estado === "inscrito" ? "verde" : "" } },
      el("h3", {}, c.nombre),
      el("p", {}, `${fecha(c.fecha)} en ${c.lugar}`),
      el("p", { class: "nota" }, c.cupos_disponibles
        ? `Quedan ${c.cupos_disponibles} de ${c.cupos} cupos` : "Sin cupos disponibles"),
      accion);
  }));
  $("#t-empleos").replaceChildren(...empleos.map((o) => el("li", {},
    el("h3", {}, o.puesto),
    el("p", {}, `${o.empresa}, ${o.distrito}. Sueldo de S/ ${o.sueldo.toLocaleString("es-PE")} al mes.`),
    o.postulado
      ? el("span", { class: "etiqueta", dataset: { tono: "verde" } }, "Postulación enviada")
      : el("div", { class: "acciones" }, el("button", { class: "secundario", type: "button", on: { click: async (ev) => {
        ev.target.disabled = true;
        try {
          const r = await api(`/api/mi/empleos/${o.id}/postulacion`, { metodo: "POST", token: tTok() });
          avisar($("#t-msj"), r.mensaje);
          await pintarCursos();
        } catch (err) { ev.target.disabled = false; avisar($("#t-msj"), err.message, false); }
      } } }, "Postular")))));
}

function pintarCruce() {
  const f = $("#form-cruce");
  f.cruce.value = perfil.cruce;
  $(`[name=horario][value=${perfil.horario}]`, f).checked = true;
  $("#t-historial").replaceChildren(...perfil.historial_cruces.map((h) =>
    el("li", {}, `Hasta el ${fecha(h.hasta, false)}: ${h.cruce}, turno ${HORARIOS[h.horario]}`)));
  const c = $("#form-contacto");
  c.nombre.value = perfil.contacto_emergencia?.nombre || "";
  c.celular.value = perfil.contacto_emergencia?.celular || "";
}

$("#form-cruce").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      const r = await api("/api/mi/cruce", { metodo: "PUT", datos: datosDe(e.target), token: tTok() });
      avisar($("#t-msj"), r.mensaje);
      perfil = await api("/api/mi/perfil", { token: tTok() });
      pintarCruce();
      iniciarTrabajador();
    } catch (err) { avisar($("#t-msj"), err.message, false); }
  });
});

$("#form-contacto").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      const r = await api("/api/mi/contacto-emergencia", { metodo: "PUT", datos: datosDe(e.target), token: tTok() });
      avisar($("#t-msj"), r.mensaje);
      perfil = await api("/api/mi/perfil", { token: tTok() });
    } catch (err) { avisar($("#t-msj"), err.message, false); }
  });
});

/* HU14 — Mantener 3 segundos; luego 10 segundos para cancelar antes de enviar */
(() => {
  const boton = $("#sos-boton");
  const dialogo = $("#sos-dialogo");
  let espera = null;
  let cuenta = null;

  const soltar = () => { clearTimeout(espera); boton.classList.remove("presionando"); };
  const presionar = (ev) => {
    ev.preventDefault();
    boton.classList.add("presionando");
    espera = setTimeout(() => { soltar(); iniciarCuenta(); }, 3000);
  };
  boton.addEventListener("pointerdown", presionar);
  ["pointerup", "pointerleave", "pointercancel"].forEach((t) => boton.addEventListener(t, soltar));
  boton.addEventListener("keydown", (ev) => { if ((ev.key === " " || ev.key === "Enter") && !ev.repeat) presionar(ev); });
  boton.addEventListener("keyup", (ev) => { if (ev.key === " " || ev.key === "Enter") soltar(); });
  boton.addEventListener("contextmenu", (ev) => ev.preventDefault());

  function iniciarCuenta() {
    let s = 10;
    $("#sos-segundos").textContent = s;
    dialogo.showModal();
    cuenta = setInterval(async () => {
      s -= 1;
      $("#sos-segundos").textContent = s;
      if (s > 0) return;
      clearInterval(cuenta);
      dialogo.close();
      try {
        const r = await api("/api/mi/emergencia", { metodo: "POST", datos: {}, token: tTok() });
        avisar($("#t-msj"), `${r.mensaje} Avisamos a: ${r.avisados.join(" y ")}. Código ${r.codigo_seguimiento}.`);
      } catch (err) { avisar($("#t-msj"), err.message, false); }
    }, 1000);
  }
  $("#sos-cancelar").addEventListener("click", () => {
    clearInterval(cuenta);
    dialogo.close();
    avisar($("#t-msj"), "Alerta cancelada. No se envió nada.");
  });
  dialogo.addEventListener("cancel", () => { clearInterval(cuenta); avisar($("#t-msj"), "Alerta cancelada. No se envió nada."); });
})();

/* =====================================================================
   CONDUCTOR — HU06 propina, HU08 calificación, HU12 reporte de menor
   ===================================================================== */
let ultimaPropina = null;
const formPropina = $("#form-propina");

function montoElegido() {
  const d = datosDe(formPropina);
  return d.monto === "otro" ? Number(d.monto_otro) : Number(d.monto);
}
function actualizarBotonPropina() {
  const d = datosDe(formPropina);
  const otro = d.monto === "otro";
  $("#c-otro").hidden = !otro;
  formPropina.monto_otro.required = otro;
  const monto = montoElegido();
  const texto = monto > 0 ? soles(monto).replace(".00", "") : "la propina";
  $("#c-enviar").textContent = `Enviar ${texto} con ${d.billetera === "yape" ? "Yape" : "Plin"}`;
}
formPropina.addEventListener("input", actualizarBotonPropina);
formPropina.addEventListener("change", actualizarBotonPropina);

async function cargarDestinatario(token) {
  const caja = $("#c-trabajador");
  if (!token || token.length < 10) { caja.hidden = true; return; }
  try {
    const d = await api(`/api/qr/${encodeURIComponent(token)}`);
    caja.replaceChildren("Vas a apoyar a", el("b", {}, d.nombre), `en ${d.cruce}`);
    caja.hidden = false;
    avisar($("#c-msj"), "");
  } catch {
    caja.hidden = true;
    avisar($("#c-msj"), "Este código no es válido. Pide al trabajador que te muestre su QR otra vez.", false);
  }
}
formPropina.qr_token.addEventListener("change", (e) => cargarDestinatario(e.target.value.trim()));

formPropina.addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    const d = datosDe(e.target);
    try {
      const r = await api("/api/propinas", { metodo: "POST",
        datos: { qr_token: d.qr_token.trim(), monto: montoElegido(), billetera: d.billetera } });
      ultimaPropina = r.id;
      $("#c-gracias-msj").textContent = r.mensaje;
      formPropina.hidden = true;
      $("#c-gracias").hidden = false;
      avisar($("#c-msj"), "");
    } catch (err) { avisar($("#c-msj"), err.message + " No se registró ningún pago; puedes reintentar.", false); }
  });
});

function terminarPropina(texto) {
  $("#c-gracias").hidden = true;
  formPropina.hidden = false;
  avisar($("#c-msj"), texto);
}
$$(".estrellas button").forEach((b) => {
  b.addEventListener("mouseenter", () => $$(".estrellas button").forEach((o) =>
    o.classList.toggle("encendida", Number(o.dataset.e) <= Number(b.dataset.e))));
  b.addEventListener("click", async () => {
    try {
      await api(`/api/propinas/${ultimaPropina}/calificacion`, { metodo: "POST", datos: { estrellas: Number(b.dataset.e) } });
      terminarPropina("Gracias por tu calificación.");
    } catch (err) { terminarPropina(err.message); }
  });
});
$(".estrellas").addEventListener("mouseleave", () => $$(".estrellas button").forEach((o) => o.classList.remove("encendida")));
$("#c-omitir").addEventListener("click", () => terminarPropina("Propina registrada sin calificación."));

$("#form-alerta").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      const r = await api("/api/alertas", { metodo: "POST", datos: { tipo: "menor", ...datosDe(e.target) } });
      avisar($("#c-alerta-msj"), `${r.mensaje} Tu código de seguimiento es ${r.codigo_seguimiento}.`);
      e.target.reset();
    } catch (err) { avisar($("#c-alerta-msj"), err.message, false); }
  });
});

/* =====================================================================
   EQUIPO SOCIAL — HU03 validar, HU11 kits, HU13 alertas, HU15 panel, HU16 usuarios
   ===================================================================== */
const eTok = () => sesion.get("equipo");
const esAdmin = () => sesion.get("rol") === "admin";

$("#form-login").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      const d = datosDe(e.target);
      const r = await api("/api/auth/login", { metodo: "POST", datos: d });
      sesion.set("equipo", r.access_token);
      sesion.set("rol", r.rol);
      sesion.set("usuario", d.usuario);
      e.target.reset();
      avisar($("#e-login-msj"), "");
      iniciarEquipo();
    } catch (err) { avisar($("#e-login-msj"), err.message, false); }
  });
});
$("#e-salir").addEventListener("click", () => { ["equipo", "rol", "usuario"].forEach(sesion.borrar); iniciarEquipo(); });
$("#e-refrescar").addEventListener("click", () => refrescarEquipo());
activarSecciones($("#e-app .secciones"), () => refrescarEquipo());

function iniciarEquipo() {
  const hay = Boolean(eTok());
  $("#e-acceso").hidden = hay;
  $("#e-app").hidden = !hay;
  if (!hay) return;
  $("#e-usuario").textContent = `Sesión de ${sesion.get("usuario")} (${esAdmin() ? "administrador" : "promotor social"})`;
  $("[data-solo-admin]").hidden = !esAdmin();
  refrescarEquipo();
}

async function refrescarEquipo() {
  try {
    await pintarPanel();
    const sec = $("#e-app .secciones [aria-current]").dataset.sec;
    if (sec === "e-sec-alertas") await pintarAlertas();
    if (sec === "e-sec-validar") await pintarPendientes();
    if (sec === "e-sec-solicitudes") await pintarSolicitudes();
    if (sec === "e-sec-kits") await pintarKits();
    if (sec === "e-sec-usuarios") await pintarUsuarios();
  } catch (err) {
    if (err.status === 401) { ["equipo", "rol", "usuario"].forEach(sesion.borrar); iniciarEquipo();
      return avisar($("#e-login-msj"), "Tu sesión terminó. Ingresa nuevamente.", false); }
    avisar($("#e-msj"), err.message, false);
  }
}

function filtrosPanel() {
  const q = new URLSearchParams();
  Object.entries(datosDe($("#form-filtros"))).forEach(([k, v]) => { if (v) q.set(k, v); });
  return q.toString() ? "?" + q : "";
}
$("#form-filtros").addEventListener("submit", (e) => { e.preventDefault(); refrescarEquipo(); });
$("#form-filtros").addEventListener("reset", () => setTimeout(refrescarEquipo));

const SVG = "http://www.w3.org/2000/svg";
function svgEl(etiqueta, attrs = {}, texto) {
  const n = document.createElementNS(SVG, etiqueta);
  Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
  if (texto !== undefined) n.textContent = texto;
  return n;
}
function pintarMapa(cruces) {
  const mapa = $("#e-mapa");
  const ubicados = cruces.filter((c) => c.lat !== null && c.lng !== null);
  const sinUbicar = cruces.length - ubicados.length;
  $("#e-sin-ubicar").textContent = sinUbicar
    ? `${sinUbicar} ${sinUbicar === 1 ? "cruce no está" : "cruces no están"} en el catálogo y solo aparece${sinUbicar === 1 ? "" : "n"} en la tabla.` : "";
  if (!ubicados.length) {
    mapa.replaceChildren(svgEl("text", { x: 360, y: 150, "text-anchor": "middle" }, "No hay cruces ubicados para este filtro."));
    return;
  }
  // Encuadre fijo de Lima centro-sur para que los puntos no salten al filtrar
  const lng0 = -77.10, lng1 = -77.00, lat0 = -12.145, lat1 = -12.06;
  const X = (lng) => 40 + (lng - lng0) / (lng1 - lng0) * 640;
  const Y = (lat) => 20 + (lat1 - lat) / (lat1 - lat0) * 260;
  const max = Math.max(1, ...ubicados.map((c) => c.trabajadores));
  const hijos = [];
  [-77.08, -77.06, -77.04, -77.02].forEach((l) => hijos.push(svgEl("line", { class: "calle", x1: X(l), x2: X(l), y1: 10, y2: 290 })));
  [-12.08, -12.10, -12.12].forEach((l) => hijos.push(svgEl("line", { class: "calle", x1: 20, x2: 700, y1: Y(l), y2: Y(l) })));
  // Etiquetas alternadas arriba/abajo (ordenadas de oeste a este) para que no se encimen
  [...ubicados].sort((a, b) => a.lng - b.lng).forEach((c, i) => {
    const g = svgEl("g");
    const r = 8 + 14 * Math.sqrt(c.trabajadores / max);
    const cx = X(c.lng), cy = Y(c.lat);
    const punto = svgEl("circle", { class: "punto" + (c.alertas_abiertas ? " alerta" : ""), cx, cy, r });
    punto.append(svgEl("title", {}, `${c.cruce}: ${c.trabajadores} trabajadores, ${c.alertas_abiertas} alertas abiertas`));
    const tx = Math.min(Math.max(cx, 130), 590);
    const arriba = i % 2 === 0;
    const y1 = arriba ? cy - r - 22 : cy + r + 16;
    g.append(punto,
      svgEl("text", { x: tx, y: y1, "text-anchor": "middle" }, c.cruce),
      svgEl("text", { class: "distrito", x: tx, y: y1 + 14, "text-anchor": "middle" },
        `${c.distrito}: ${c.trabajadores} trab., ${c.alertas_abiertas} ${c.alertas_abiertas === 1 ? "alerta" : "alertas"}`));
    hijos.push(g);
  });
  mapa.replaceChildren(...hijos);
}

async function pintarPanel() {
  const p = await api("/api/panel" + filtrosPanel(), { token: eTok() });
  const sel = $("#f-distrito");
  const elegido = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "Todos"), ...p.distritos.map((d) => el("option", { value: d }, d)));
  sel.value = elegido;
  pintarMapa(p.por_cruce);
  const dato = (t, v, tono) => el("div", { dataset: { tono: tono || "" } }, el("dt", {}, t), el("dd", {}, String(v)));
  $("#e-kpis").replaceChildren(
    dato("Trabajadores", p.total_trabajadores),
    dato("Por validar", p.pendientes_validacion, p.pendientes_validacion ? "ambar" : ""),
    dato("Alertas abiertas", p.alertas_abiertas, p.alertas_abiertas ? "rojo" : ""),
    dato("Emergencias", p.emergencias_abiertas, p.emergencias_abiertas ? "rojo" : ""),
    dato("Solicitudes nuevas", p.solicitudes_nuevas, p.solicitudes_nuevas ? "ambar" : ""),
    dato("Kits entregados", p.kits_entregados),
    dato("Propinas digitales", soles(p.propinas_total)),
  );
  const max = Math.max(1, ...p.por_cruce.map((c) => c.alertas_abiertas));
  $("#e-cruces tbody").replaceChildren(...(p.por_cruce.length ? p.por_cruce.map((c) => {
    const barra = el("span", { class: "barra-cruce", "aria-hidden": "true" });
    barra.style.width = `${(c.alertas_abiertas / max) * 100}%`;
    return el("tr", {},
      el("th", { scope: "row" }, c.cruce, el("br"), el("span", { class: "nota" }, c.distrito)),
      el("td", { class: "num" }, String(c.trabajadores)),
      el("td", { class: "num" }, String(c.validados)),
      el("td", { class: "num" }, String(c.alertas_abiertas), c.alertas_abiertas ? barra : null),
      el("td", { class: "num" }, String(c.kits_entregados)),
      el("td", { class: "num" }, soles(c.propinas_total)));
  }) : [el("tr", {}, el("td", { colspan: "6", class: "vacio" }, "No hay registros para este filtro."))]));
}

const TONO_ALERTA = { nueva: "rojo", vencida: "rojo", derivada: "verde" };
async function pintarAlertas() {
  const lista = await api("/api/alertas", { token: eTok() });
  $("#e-alertas").replaceChildren(...(lista.length ? lista.map((a) => el("li", { dataset: { tono: TONO_ALERTA[a.estado] } },
    el("h3", {}, `${a.tipo === "emergencia" ? "Emergencia" : "Menor trabajando"} en ${a.cruce}`),
    el("span", { class: "etiqueta", dataset: { tono: TONO_ALERTA[a.estado] } },
      { nueva: "Nueva", vencida: "Vencida: más de 48 h sin atender", derivada: "Derivada a la DEMUNA" }[a.estado]),
    a.descripcion ? el("p", {}, a.descripcion) : null,
    el("p", { class: "nota" }, `Código ${a.codigo_seguimiento}, recibida el ${fecha(a.creado_en)}`
      + (a.derivada_por ? `. Derivada por ${a.derivada_por}: ${a.observaciones}` : "")),
    a.estado !== "derivada" ? el("div", { class: "acciones" }, el("button", { class: "primario", type: "button",
      on: { click: async () => {
        const obs = await pedirTexto("Derivar a la DEMUNA", "Observaciones para la DEMUNA", "Derivar alerta");
        if (!obs) return;
        try {
          await api(`/api/alertas/${a.id}/derivar`, { metodo: "POST", datos: { observaciones: obs }, token: eTok() });
          avisar($("#e-msj"), `Alerta ${a.codigo_seguimiento} derivada.`);
          refrescarEquipo();
        } catch (err) { avisar($("#e-msj"), err.message, false); }
      } } }, "Derivar a la DEMUNA")) : null,
  )) : [vacio("No hay alertas. Las nuevas aparecerán aquí.")]));
}

async function pintarPendientes() {
  const lista = await api("/api/trabajadores?estado=pendiente", { token: eTok() });
  $("#e-pendientes").replaceChildren(...(lista.length ? lista.map((t) => el("li", { dataset: { tono: "ambar" } },
    el("h3", {}, t.nombres),
    el("p", {}, `${t.tipo_documento} ${t.documento_enmascarado}, ${t.cruce}, turno ${HORARIOS[t.horario]}`),
    el("p", { class: "nota" }, `Registrado el ${fecha(t.creado_en)}`),
    el("div", { class: "acciones" },
      el("button", { class: "primario", type: "button", on: { click: () => validar(t, true) } }, "Aprobar"),
      el("button", { class: "secundario", type: "button", on: { click: () => validar(t, false) } }, "Rechazar")),
  )) : [vacio("No hay registros pendientes de validación.")]));
}

async function validar(t, aprobar) {
  const motivo = aprobar ? null : await pedirTexto("Rechazar registro", `Motivo para ${t.nombres}`, "Rechazar registro");
  if (!aprobar && !motivo) return;
  try {
    await api(`/api/trabajadores/${t.id}/validacion`, { metodo: "POST", datos: { aprobar, motivo }, token: eTok() });
    avisar($("#e-msj"), `${t.nombres}: registro ${aprobar ? "aprobado" : "rechazado"}.`);
    refrescarEquipo();
  } catch (err) { avisar($("#e-msj"), err.message, false); }
}

async function pintarSolicitudes() {
  const lista = await api("/api/solicitudes", { token: eTok() });
  $("#e-solicitudes").replaceChildren(...(lista.length ? lista.map((s) => el("li", { dataset: { tono: s.estado === "nueva" ? "ambar" : "verde" } },
    el("h3", {}, `${s.trabajador}: ${s.programa}`),
    el("p", {}, `Celular ${s.celular}, ${s.cruce}. Pedido el ${fecha(s.creado_en)}.`),
    s.estado === "nueva"
      ? el("div", { class: "acciones" }, el("button", { class: "secundario", type: "button", on: { click: async () => {
        try {
          await api(`/api/solicitudes/${s.id}/atender`, { metodo: "POST", token: eTok() });
          refrescarEquipo();
        } catch (err) { avisar($("#e-msj"), err.message, false); }
      } } }, "Marcar como atendida"))
      : el("span", { class: "etiqueta", dataset: { tono: "verde" } }, "Atendida"),
  )) : [vacio("No hay solicitudes de orientación.")]));
}

async function pintarKits() {
  const select = $("#kit-trabajador");
  const previo = select.value;
  const lista = await api("/api/trabajadores?estado=validado", { token: eTok() });
  select.replaceChildren(...lista.map((t) => el("option", { value: t.id }, `${t.nombres} (${t.cruce})`)));
  if (previo) select.value = previo;
  await pintarHistorialKits();
}
async function pintarHistorialKits() {
  const id = $("#kit-trabajador").value;
  if (!id) return $("#e-kits").replaceChildren(vacio("Valida trabajadores para poder entregarles kits."));
  const kits = await api(`/api/trabajadores/${id}/kits`, { token: eTok() });
  $("#e-kits").replaceChildren(...(kits.length ? kits.map((k) => el("li", {},
    `${fecha(k.entregado_en)}: ${k.elementos.join(", ")}, entregado por ${k.registrado_por}`
    + (k.motivo ? `. Motivo: ${k.motivo}` : ""))) : [vacio("Este trabajador aún no recibió kits.")]));
}
$("#kit-trabajador").addEventListener("change", () => { $("#kit-motivo").hidden = true; pintarHistorialKits(); });

$("#form-kit").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    const elementos = $$("[name=elementos]:checked", e.target).map((c) => c.value);
    const motivo = e.target.motivo.value.trim() || null;
    try {
      await api(`/api/trabajadores/${e.target.trabajador.value}/kits`,
        { metodo: "POST", datos: { elementos, motivo }, token: eTok() });
      avisar($("#e-msj"), "Entrega registrada.");
      e.target.motivo.value = "";
      $("#kit-motivo").hidden = true;
      refrescarEquipo();
    } catch (err) {
      if (err.status === 409) { $("#kit-motivo").hidden = false; e.target.motivo.focus(); }
      avisar($("#e-msj"), err.message, false);
    }
  });
});

async function pintarUsuarios() {
  const [usuarios, cambios] = await Promise.all([
    api("/api/usuarios", { token: eTok() }), api("/api/auditoria", { token: eTok() })]);
  const yo = sesion.get("usuario");
  $("#e-usuarios").replaceChildren(...usuarios.map((u) => el("li", { dataset: { tono: u.activo ? "verde" : "rojo" } },
    el("h3", {}, u.usuario),
    el("p", {}, `${u.rol === "admin" ? "Administrador" : "Promotor social"}, ${u.activo ? "activo" : "desactivado"}`),
    u.usuario === yo ? el("p", { class: "nota" }, "Tu cuenta") : el("div", { class: "acciones" },
      el("button", { class: "secundario", type: "button", on: { click: () => cambiarUsuario(u, { activo: !u.activo }) } },
        u.activo ? "Desactivar" : "Activar"),
      el("button", { class: "enlace", type: "button",
        on: { click: () => cambiarUsuario(u, { rol: u.rol === "admin" ? "promotor" : "admin" }) } },
      u.rol === "admin" ? "Cambiar a promotor social" : "Cambiar a administrador")),
  )));
  $("#e-auditoria").replaceChildren(...(cambios.length
    ? cambios.map((a) => el("li", {}, `${fecha(a.creado_en)}: ${a.actor}, ${a.accion.replace("_", " ")} (${a.detalle})`))
    : [vacio("Sin cambios registrados.")]));
}
async function cambiarUsuario(u, datos) {
  try {
    await api(`/api/usuarios/${u.id}`, { metodo: "PATCH", datos, token: eTok() });
    avisar($("#e-msj"), `Usuario ${u.usuario} actualizado.`);
    refrescarEquipo();
  } catch (err) { avisar($("#e-msj"), err.message, false); }
}
$("#form-usuario").addEventListener("submit", (e) => {
  e.preventDefault();
  conEnvio(e.target, async () => {
    try {
      const r = await api("/api/usuarios", { metodo: "POST", datos: datosDe(e.target), token: eTok() });
      avisar($("#e-msj"), `Usuario ${r.usuario} creado.`);
      e.target.reset();
      refrescarEquipo();
    } catch (err) { avisar($("#e-msj"), err.message, false); }
  });
});

/* ---------- Arranque ---------- */
// Si el conductor escaneó un QR (/?t=CODIGO), abrir directamente la propina.
const qrEscaneado = new URLSearchParams(location.search).get("t");
if (qrEscaneado) {
  history.replaceState(null, "", "/#conductor");
  formPropina.qr_token.value = qrEscaneado;
  $("#c-codigo-campo").hidden = true;
  cargarDestinatario(qrEscaneado);
}
actualizarBotonPropina();
mostrarVista();
