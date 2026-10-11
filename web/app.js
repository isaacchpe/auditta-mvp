const Auditta = (() => {
  const ICONOS = {
    inicio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
    carga: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
    bandeja: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
    metricas: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    salir: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
    candado: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    documento: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    aceptar: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    descartar: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    reclasificar: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
    escudo: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  };
  const ESTADOS = { pendiente_confirmacion: "Pendiente de confirmar", analizada: "Analizada", revisada: "Revisada", error: "Error" };
  const PERFILES = { auditor_medico: "Auditor médico", facturacion: "Facturación", coordinador: "Coordinador de auditoría", desarrollador: "Desarrollador", evaluador: "Cuenta de prueba", otro: "Otro" };

  const almacen = {
    leer(clave) { try { return localStorage.getItem(clave); } catch { return null; } },
    escribir(clave, valor) { try { localStorage.setItem(clave, valor); } catch {} },
    borrar(clave) { try { localStorage.removeItem(clave); } catch {} },
  };

  function token() { return almacen.leer("auditta_token"); }
  function guardarSesion(datos) { almacen.escribir("auditta_token", datos.token); almacen.escribir("auditta_nombre", datos.nombre); almacen.escribir("auditta_perfil", datos.perfil); }
  function cerrarSesion() { ["auditta_token", "auditta_nombre", "auditta_perfil"].forEach(almacen.borrar); location.href = "/index.html"; }
  function exigirSesion() { if (!token()) { location.href = "/index.html"; return false; } return true; }

  function mensajeDe(datos) {
    if (typeof datos.detail === "string") return datos.detail;
    if (Array.isArray(datos.detail)) return datos.detail.map(d => String(d.msg || "").replace("Value error, ", "")).join(" ");
    return "No fue posible completar la acción.";
  }

  async function api(ruta, opciones = {}) {
    const cabeceras = { "Content-Type": "application/json" };
    const t = token();
    if (t) cabeceras.Authorization = "Bearer " + t;
    const respuesta = await fetch("/api" + ruta, { ...opciones, headers: cabeceras });
    if (respuesta.status === 401 && t) { cerrarSesion(); throw new Error("Sesión expirada"); }
    if (respuesta.status === 204) return null;
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(mensajeDe(datos));
    return datos;
  }

  function evento(tipo, detalle = {}) {
    if (token()) api("/eventos", { method: "POST", body: JSON.stringify({ tipo, detalle }) }).catch(() => {});
  }

  function ocupado(boton, activo, texto) {
    boton.disabled = activo;
    boton.classList.toggle("cargando", activo);
    const etiqueta = boton.querySelector(".etiqueta");
    if (etiqueta) { if (activo) { etiqueta.dataset.original = etiqueta.textContent; etiqueta.textContent = texto || "Procesando…"; } else if (etiqueta.dataset.original) etiqueta.textContent = etiqueta.dataset.original; }
  }

  function iniciales(nombre) { return (nombre || "").split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join("") || "AU"; }

  function lateral(activa) {
    const nombre = almacen.leer("auditta_nombre") || "Usuario";
    const perfil = PERFILES[almacen.leer("auditta_perfil")] || "Participante";
    const enlace = (clave, href, texto) => `<a href="${href}" ${activa === clave ? 'aria-current="page"' : ""}>${ICONOS[clave]}${texto}</a>`;
    const aside = document.createElement("aside");
    aside.className = "lateral";
    aside.innerHTML = `<div class="marca">Auditta<small>MVP</small></div><nav aria-label="Navegación principal">${enlace("inicio", "/inicio.html", "Inicio")}${enlace("carga", "/carga.html", "Cargar historia")}${enlace("bandeja", "/bandeja.html", "Bandeja de historias")}${enlace("metricas", "/metricas.html", "Métricas")}</nav><div class="espacio"></div><div class="usuario"><div class="avatar">${iniciales(nombre)}</div><div><b>${escapar(nombre)}</b><span>${perfil}</span></div></div><button class="salir" type="button">${ICONOS.salir}Cerrar sesión</button>`;
    aside.querySelector(".salir").addEventListener("click", () => { evento("cerrar_sesion"); cerrarSesion(); });
    document.querySelector(".marco").prepend(aside);
  }

  function escapar(texto) { return String(texto ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function resaltarTokens(texto) { return escapar(texto).replace(/\[([A-ZÁÉÍÓÚÑ_]+_\d+|EDAD_MAYOR_90)\]/g, '<span class="token">[$1]</span>'); }
  function chip(severidad) { return `<span class="chip ${severidad}">${{ alta: "Alta", media: "Media", baja: "Baja" }[severidad] || severidad}</span>`; }
  function estado(valor) { return `<span class="estado ${valor}">${ESTADOS[valor] || valor}</span>`; }
  function puntaje(valor, nivel) {
    if (valor == null) return '<span style="color:var(--color-neutro-texto-tenue)">—</span>';
    return `<span class="puntaje ${nivel || "bajo"}"><span class="pista"><span class="barra" style="width:${valor}%"></span></span>${valor}</span>`;
  }
  function parametro(nombre) { return new URLSearchParams(location.search).get(nombre); }
  function segundos(total) { total = Math.round(total || 0); const m = Math.floor(total / 60), s = total % 60; return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`; }
  function insignia() { return `<span class="insignia">${ICONOS.candado}Corpus sintético · sin datos reales</span>`; }

  let temporizadorNotificacion;
  function notificar(texto, accion) {
    let caja = document.querySelector(".notificacion");
    if (!caja) { caja = document.createElement("div"); caja.className = "notificacion"; document.body.appendChild(caja); }
    caja.innerHTML = `${ICONOS.aceptar}<span>${escapar(texto)}</span>`;
    if (accion) { const b = document.createElement("button"); b.type = "button"; b.textContent = accion.texto; b.addEventListener("click", () => { caja.classList.remove("visible"); accion.al(); }); caja.appendChild(b); }
    caja.classList.add("visible");
    clearTimeout(temporizadorNotificacion);
    temporizadorNotificacion = setTimeout(() => caja.classList.remove("visible"), 6000);
  }

  function sinHistoria(contenedor, mensaje) {
    const destino = document.querySelector(contenedor) || document.querySelector(".contenido");
    const caja = `<section class="tarjeta exito" style="margin:40px auto"><span style="font-size:40px;font-weight:700;color:var(--color-marca-primario)">!</span><h1 style="font-size:20px">${escapar(mensaje || "No encontramos esta historia")}</h1><p style="margin:0;color:var(--color-neutro-texto-secundario)">Elija una historia desde la bandeja para continuar.</p><a class="btn" href="/bandeja.html">Ir a la bandeja</a></section>`;
    const principal = document.querySelector(".contenido");
    if (principal) { [...principal.children].forEach(n => { if (!n.classList.contains("encabezado")) n.remove(); }); principal.insertAdjacentHTML("beforeend", caja); }
    else if (destino) destino.innerHTML = caja;
  }

  function historiaSolicitada() {
    const id = parametro("id");
    if (!id) { sinHistoria(null, "No se indicó qué historia abrir"); return null; }
    return id;
  }

  return { sinHistoria, historiaSolicitada, ICONOS, ESTADOS, PERFILES, api, evento, ocupado, lateral, escapar, resaltarTokens, chip, estado, puntaje, parametro, segundos, insignia, notificar, guardarSesion, cerrarSesion, exigirSesion, token, almacen };
})();
