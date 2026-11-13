import hashlib
import logging
import re
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.auth import (BLOQUEO_SEGUNDOS, INTENTOS_MAXIMOS, ahora_ts, cerrar_sesiones, datos_de_token, emitir_token, hashear,
                      problema_de_clave, respuesta_de_ingreso, usuario_actual, verificar)
from app.config import ADMIN_CORREOS, CONTACTO_PRIVACIDAD, DEMO_CORREO, DEMO_HORAS, FORMULARIO_RETROALIMENTACION, RAIZ, VERSION_APP
from app.db import obtener_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("auditta")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    from app.semilla import sembrar_si_vacio

    try:
        sembrar_si_vacio()
        db = obtener_db()
        db.revisiones.create_index([("usuario", 1), ("historia_id", 1)], unique=True)
        db.hallazgos.create_index("historia_id")
        db.eventos.create_index("fecha")
        db.sesiones.create_index("usuario")
        db.historias.create_index([("cargada_por", 1), ("hash", 1)])
        limpiar_demos_vencidas()
    except Exception:
        log.exception("No fue posible preparar los datos iniciales")
    yield


app = FastAPI(title="Auditta MVP", version=VERSION_APP, docs_url=None, redoc_url=None, lifespan=ciclo_de_vida)
WEB = RAIZ / "web"
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERFILES = ("auditor_medico", "facturacion", "coordinador", "desarrollador", "otro")
PERFILES_MEDIDOS = ("auditor_medico", "facturacion", "coordinador")
PREFIJO_AUDITOR = "#auditor_medico#"
DOMINIO_DEMO = "demo.auditta.app"
USUARIO_ELIMINADO = "cuenta-eliminada"


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def registrar_evento(tipo: str, usuario: str | None, detalle: dict | None = None) -> None:
    obtener_db().eventos.insert_one({"tipo": tipo, "usuario": usuario, "detalle": detalle or {}, "fecha": ahora()})


def limpiar(documento: dict) -> dict:
    documento = dict(documento)
    for clave, valor in list(documento.items()):
        if isinstance(valor, datetime):
            documento[clave] = valor.isoformat()
        elif isinstance(valor, dict):
            documento[clave] = limpiar(valor)
        elif isinstance(valor, list):
            documento[clave] = [limpiar(v) if isinstance(v, dict) else v for v in valor]
    return documento


@app.middleware("http")
async def bitacora(request: Request, call_next):
    inicio = time.perf_counter()
    try:
        respuesta = await call_next(request)
    except Exception:
        log.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Error interno. Intente de nuevo."}, status_code=500)
    if not request.url.path.startswith("/api"):
        respuesta.headers["Cache-Control"] = "no-cache"
    else:
        respuesta.headers["Cache-Control"] = "no-store"
        log.info("%s %s %d %.0fms", request.method, request.url.path, respuesta.status_code, (time.perf_counter() - inicio) * 1000)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    return respuesta


def correo_normalizado(valor: str) -> str:
    valor = valor.strip().lower()
    if not CORREO.match(valor):
        raise ValueError("Escriba un correo válido.")
    if valor.endswith("@" + DOMINIO_DEMO):
        raise ValueError("Ese dominio de correo no está permitido.")
    return valor


def clave_valida(valor: str) -> str:
    problema = problema_de_clave(valor)
    if problema:
        raise ValueError(problema)
    return valor


class Ingreso(BaseModel):
    correo: str = Field(max_length=120)
    clave: str = Field(max_length=128)


class Registro(BaseModel):
    nombre: str = Field(min_length=3, max_length=80)
    correo: str = Field(max_length=120)
    clave: str
    perfil: Literal[PERFILES]
    acepta_tratamiento: bool = False

    @field_validator("nombre")
    @classmethod
    def nombre_valido(cls, valor: str) -> str:
        valor = " ".join(valor.split())
        if len(valor) < 3:
            raise ValueError("Escriba su nombre completo.")
        return valor

    @field_validator("correo")
    @classmethod
    def correo_valido(cls, valor: str) -> str:
        return correo_normalizado(valor)

    @field_validator("clave")
    @classmethod
    def clave_segura(cls, valor: str) -> str:
        return clave_valida(valor)


class DatosCuenta(BaseModel):
    nombre: str = Field(min_length=3, max_length=80)
    perfil: Literal[PERFILES]


class CambioClave(BaseModel):
    actual: str = Field(max_length=128)
    nueva: str

    @field_validator("nueva")
    @classmethod
    def clave_segura(cls, valor: str) -> str:
        return clave_valida(valor)


class Eliminacion(BaseModel):
    clave: str = Field(max_length=128)


class Decision(BaseModel):
    decision: Literal["aceptado", "descartado", "reclasificado"]
    severidad_nueva: Literal["alta", "media", "baja"] | None = None
    motivo: str = Field(default="", max_length=500)
    segundos_desde_apertura: float | None = Field(default=None, ge=0)


class Cierre(BaseModel):
    segundos_revision: float = Field(ge=0)


class Traza(BaseModel):
    traza: str = Field(min_length=1, max_length=64)
    tipo: Literal["pantalla", "clic", "validacion", "error_js", "salida"]
    ruta: str = Field(default="", max_length=300)
    ms: int = Field(default=0, ge=0)
    detalle: dict = {}
    token: str | None = Field(default=None, max_length=2000)


class Evento(BaseModel):
    tipo: str = Field(max_length=40)
    detalle: dict = {}


def es_admin(usuario: dict) -> bool:
    return usuario.get("sub", "").lower() in ADMIN_CORREOS


def cuenta_de(usuario: dict) -> dict:
    cuenta = obtener_db().usuarios.find_one({"_id": usuario["sub"]})
    if not cuenta:
        raise HTTPException(401, "La cuenta ya no existe.")
    return cuenta


def exigir_cuenta_registrada(cuenta: dict) -> None:
    if cuenta.get("demo_individual"):
        raise HTTPException(403, "Esta acción requiere una cuenta registrada. Cree su cuenta para continuar.")


def borrar_datos_de(usuario_id: str) -> dict:
    db = obtener_db()
    historias = [h["_id"] for h in db.historias.find({"origen": "carga", "cargada_por": usuario_id}, {"_id": 1})]
    resultado = {
        "historias": db.historias.delete_many({"_id": {"$in": historias}}).deleted_count,
        "hallazgos": db.hallazgos.delete_many({"historia_id": {"$in": historias}}).deleted_count,
        "revisiones": db.revisiones.delete_many({"usuario": usuario_id}).deleted_count,
        "sesiones": db.sesiones.delete_many({"usuario": usuario_id}).deleted_count,
    }
    db.revisiones.delete_many({"historia_id": {"$in": historias}})
    db.eventos.update_many({"usuario": usuario_id}, {"$set": {"usuario": USUARIO_ELIMINADO}})
    db.trazas.update_many({"usuario": usuario_id}, {"$set": {"usuario": USUARIO_ELIMINADO}})
    db.usuarios.delete_one({"_id": usuario_id})
    return resultado


def limpiar_demos_vencidas() -> int:
    db = obtener_db()
    vencidas = [u["_id"] for u in db.usuarios.find({"demo_individual": True, "expira_ts": {"$lt": ahora_ts()}}, {"_id": 1})]
    for usuario_id in vencidas:
        borrar_datos_de(usuario_id)
    return len(vencidas)


@app.get("/api/salud")
def salud():
    obtener_db().command("ping")
    return {"estado": "ok", "version": VERSION_APP}


@app.get("/api/configuracion")
def configuracion():
    return {"formulario_retroalimentacion": FORMULARIO_RETROALIMENTACION, "demo_horas": DEMO_HORAS, "contacto_privacidad": CONTACTO_PRIVACIDAD or None}


@app.post("/api/auth/ingreso")
def ingreso(datos: Ingreso, request: Request):
    db = obtener_db()
    correo = datos.correo.strip().lower()
    if correo == DEMO_CORREO or correo.endswith("@" + DOMINIO_DEMO):
        raise HTTPException(403, "La cuenta de prueba compartida ya no está disponible. Use «Probar sin registrarse» o cree su cuenta.")
    usuario = db.usuarios.find_one({"_id": correo})
    momento = ahora_ts()
    if usuario and usuario.get("bloqueo_ts", 0) > momento:
        minutos = -(-(usuario["bloqueo_ts"] - momento) // 60)
        raise HTTPException(429, f"Demasiados intentos fallidos. Intente de nuevo en {minutos} {'minuto' if minutos == 1 else 'minutos'}.")
    if not verificar(datos.clave, usuario.get("hash") if usuario else None):
        if usuario:
            fallos = usuario.get("fallos", 0) + 1
            cambios = {"fallos": 0, "bloqueo_ts": momento + BLOQUEO_SEGUNDOS} if fallos >= INTENTOS_MAXIMOS else {"fallos": fallos}
            db.usuarios.update_one({"_id": correo}, {"$set": cambios})
            registrar_evento("ingreso_fallido", correo, {"bloqueo": fallos >= INTENTOS_MAXIMOS})
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    db.usuarios.update_one({"_id": correo}, {"$set": {"fallos": 0, "bloqueo_ts": 0, "ultimo_ingreso": ahora()}})
    registrar_evento("ingreso", correo)
    return respuesta_de_ingreso(usuario, request)


@app.post("/api/auth/registro", status_code=201)
def registro(datos: Registro, request: Request):
    if not datos.acepta_tratamiento:
        raise HTTPException(422, "Debe aceptar la política de tratamiento de datos para crear la cuenta.")
    db = obtener_db()
    if datos.correo == DEMO_CORREO or db.usuarios.find_one({"_id": datos.correo}):
        raise HTTPException(409, "Ya existe una cuenta con ese correo.")
    usuario = {"_id": datos.correo, "nombre": datos.nombre, "perfil": datos.perfil, "hash": hashear(datos.clave), "fecha_creacion": ahora(), "acepta_tratamiento": ahora()}
    db.usuarios.insert_one(usuario)
    registrar_evento("registro", datos.correo, {"perfil": datos.perfil})
    return respuesta_de_ingreso(usuario, request)


@app.post("/api/auth/demo", status_code=201)
def demo(request: Request):
    limpiar_demos_vencidas()
    duracion = DEMO_HORAS * 3600
    usuario = {
        "_id": f"visitante-{secrets.token_hex(5)}@{DOMINIO_DEMO}",
        "nombre": "Visitante",
        "perfil": "demo",
        "hash": None,
        "demo": True,
        "demo_individual": True,
        "fecha_creacion": ahora(),
        "expira_ts": ahora_ts() + duracion,
    }
    obtener_db().usuarios.insert_one(usuario)
    registrar_evento("demo_iniciada", usuario["_id"])
    return respuesta_de_ingreso(usuario, request, duracion)


@app.post("/api/auth/salir", status_code=204)
def salir(usuario: dict = Depends(usuario_actual)):
    obtener_db().sesiones.update_one({"_id": usuario["sid"]}, {"$set": {"activa": False, "cerrada_ts": ahora_ts()}})
    registrar_evento("cerrar_sesion", usuario["sub"])


def referencia_de(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()[:16]


@app.get("/api/cuenta")
def ver_cuenta(usuario: dict = Depends(usuario_actual)):
    cuenta = cuenta_de(usuario)
    return {
        "correo": None if cuenta.get("demo_individual") else cuenta["_id"],
        "nombre": cuenta["nombre"],
        "perfil": cuenta["perfil"],
        "demo": bool(cuenta.get("demo_individual")),
        "expira_ts": cuenta.get("expira_ts"),
        "fecha_creacion": cuenta["fecha_creacion"].isoformat() if isinstance(cuenta.get("fecha_creacion"), datetime) else None,
        "administrador": es_admin(usuario),
    }


@app.put("/api/cuenta")
def actualizar_cuenta(datos: DatosCuenta, usuario: dict = Depends(usuario_actual)):
    cuenta = cuenta_de(usuario)
    exigir_cuenta_registrada(cuenta)
    nombre = " ".join(datos.nombre.split())
    obtener_db().usuarios.update_one({"_id": cuenta["_id"]}, {"$set": {"nombre": nombre, "perfil": datos.perfil}})
    registrar_evento("cuenta_actualizada", cuenta["_id"], {"perfil": datos.perfil})
    cuenta.update(nombre=nombre, perfil=datos.perfil)
    return {"token": emitir_token(cuenta, usuario["sid"]), "nombre": nombre, "perfil": datos.perfil}


@app.post("/api/cuenta/clave")
def cambiar_clave(datos: CambioClave, usuario: dict = Depends(usuario_actual)):
    cuenta = cuenta_de(usuario)
    exigir_cuenta_registrada(cuenta)
    if not verificar(datos.actual, cuenta.get("hash")):
        raise HTTPException(403, "La contraseña actual no es correcta.")
    if datos.actual == datos.nueva:
        raise HTTPException(422, "La nueva contraseña debe ser distinta de la actual.")
    obtener_db().usuarios.update_one({"_id": cuenta["_id"]}, {"$set": {"hash": hashear(datos.nueva), "clave_cambiada": ahora()}})
    cerradas = cerrar_sesiones(cuenta["_id"], excepto=usuario["sid"])
    registrar_evento("clave_cambiada", cuenta["_id"], {"sesiones_cerradas": cerradas})
    return {"sesiones_cerradas": cerradas}


@app.get("/api/cuenta/sesiones")
def listar_sesiones(usuario: dict = Depends(usuario_actual)):
    momento = ahora_ts()
    sesiones = []
    for s in obtener_db().sesiones.find({"usuario": usuario["sub"], "activa": True}):
        if s["expira_ts"] <= momento:
            continue
        sesiones.append({"ref": referencia_de(s["_id"]), "dispositivo": s.get("dispositivo", "Navegador"), "creada_ts": s["creada_ts"],
                         "actividad_ts": s.get("actividad_ts", s["creada_ts"]), "expira_ts": s["expira_ts"], "actual": s["_id"] == usuario["sid"]})
    sesiones.sort(key=lambda s: (not s["actual"], -s["actividad_ts"]))
    return {"sesiones": sesiones}


@app.delete("/api/cuenta/sesiones/{ref}", status_code=204)
def cerrar_una_sesion(ref: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    for s in db.sesiones.find({"usuario": usuario["sub"], "activa": True}, {"_id": 1}):
        if referencia_de(s["_id"]) == ref:
            db.sesiones.update_one({"_id": s["_id"]}, {"$set": {"activa": False, "cerrada_ts": ahora_ts()}})
            registrar_evento("sesion_cerrada_remota", usuario["sub"])
            return
    raise HTTPException(404, "Sesión no encontrada.")


@app.post("/api/cuenta/sesiones/cerrar-otras")
def cerrar_otras_sesiones(usuario: dict = Depends(usuario_actual)):
    cerradas = cerrar_sesiones(usuario["sub"], excepto=usuario["sid"])
    registrar_evento("cerrar_otras_sesiones", usuario["sub"], {"cerradas": cerradas})
    return {"sesiones_cerradas": cerradas}


@app.post("/api/cuenta/eliminar")
def eliminar_cuenta(datos: Eliminacion, usuario: dict = Depends(usuario_actual)):
    cuenta = cuenta_de(usuario)
    if not cuenta.get("demo_individual") and not verificar(datos.clave, cuenta.get("hash")):
        raise HTTPException(403, "La contraseña no es correcta.")
    resultado = borrar_datos_de(cuenta["_id"])
    registrar_evento("cuenta_eliminada", USUARIO_ELIMINADO, resultado)
    return resultado


def revision_de(usuario: str, historia_id: str) -> dict:
    revision = obtener_db().revisiones.find_one({"usuario": usuario, "historia_id": historia_id})
    return revision or {"usuario": usuario, "historia_id": historia_id, "estado": "pendiente_confirmacion", "decisiones": {}}


def fusionar_hallazgo(hallazgo: dict, decision: dict | None) -> dict:
    hallazgo = dict(hallazgo)
    if decision:
        hallazgo["estado_revision"] = decision["decision"]
        hallazgo["ultima_decision"] = decision
        if decision.get("severidad_nueva"):
            hallazgo["severidad_revisada"] = decision["severidad_nueva"]
    else:
        hallazgo["estado_revision"] = "pendiente"
    return hallazgo


def filtro_visibles(sujeto: str) -> dict:
    return {"$or": [{"origen": {"$ne": "carga"}}, {"cargada_por": {"$in": [sujeto, None]}}]}


def es_visible(historia: dict, sujeto: str) -> bool:
    return historia.get("origen") != "carga" or historia.get("cargada_por") in (sujeto, None)


def historia_visible(historia_id: str, sujeto: str, proyeccion: dict | None = None) -> dict:
    if proyeccion is not None:
        proyeccion = {**proyeccion, "origen": 1, "cargada_por": 1}
    historia = obtener_db().historias.find_one({"_id": historia_id}, proyeccion)
    if not historia or not es_visible(historia, sujeto):
        raise HTTPException(404, "Historia no encontrada.")
    return historia


def hallazgo_visible(hallazgo_id: str, sujeto: str) -> dict:
    hallazgo = obtener_db().hallazgos.find_one({"_id": hallazgo_id})
    if not hallazgo:
        raise HTTPException(404, "Hallazgo no encontrado.")
    try:
        historia_visible(hallazgo["historia_id"], sujeto, {"_id": 1})
    except HTTPException:
        raise HTTPException(404, "Hallazgo no encontrado.")
    return hallazgo


def resumen_historia(historia: dict, total_hallazgos: int, revision: dict) -> dict:
    return {
        "_id": historia["_id"],
        "plantilla": historia.get("plantilla"),
        "paginas": historia.get("paginas"),
        "estado": revision["estado"],
        "puntaje": historia.get("puntaje"),
        "nivel": historia.get("nivel"),
        "num_hallazgos": total_hallazgos,
        "revisados": len(revision.get("decisiones", {})),
        "error": historia.get("error"),
        "origen": historia.get("origen", "corpus"),
        "analisis_pendiente": historia.get("analisis_pendiente", False),
        "fecha_carga": historia.get("fecha_carga"),
    }


@app.get("/api/historias")
def listar_historias(usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    historias_visibles = list(db.historias.find(filtro_visibles(usuario["sub"]), {"texto_anonimizado": 0, "entidades": 0, "secciones": 0}))
    ids = [h["_id"] for h in historias_visibles]
    conteo: dict[str, int] = {}
    for hallazgo in db.hallazgos.find({"historia_id": {"$in": ids}}, {"historia_id": 1}):
        conteo[hallazgo["historia_id"]] = conteo.get(hallazgo["historia_id"], 0) + 1
    revisiones = {r["historia_id"]: r for r in db.revisiones.find({"usuario": usuario["sub"]})}
    historias = []
    for h in historias_visibles:
        revision = revisiones.get(h["_id"]) or {"estado": "pendiente_confirmacion", "decisiones": {}}
        historias.append(limpiar(resumen_historia(h, conteo.get(h["_id"], 0), revision)))
    historias.sort(key=lambda h: (h["puntaje"] is None, -(h["puntaje"] or 0)))
    return {"historias": historias}


@app.get("/api/historias/{historia_id}")
def ver_historia(historia_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    historia = historia_visible(historia_id, usuario["sub"])
    revision = revision_de(usuario["sub"], historia_id)
    decisiones = revision.get("decisiones", {})
    hallazgos = [limpiar(fusionar_hallazgo(h, decisiones.get(h["_id"]))) for h in db.hallazgos.find({"historia_id": historia_id}).sort("orden", 1)]
    for campo in ("estado", "confirmacion", "cierre"):
        if campo in revision:
            historia[campo] = revision[campo]
    historia["estado"] = revision["estado"]
    historia.pop("cargada_por", None)
    registrar_evento("ver_historia", usuario["sub"], {"historia_id": historia_id})
    return {**limpiar(historia), "hallazgos": hallazgos}


@app.post("/api/historias/cargar", status_code=201)
async def cargar_historia(archivo: UploadFile = File(...), usuario: dict = Depends(usuario_actual)):
    from pipeline import servicio
    from pipeline.extraer import DocumentoSinTexto

    nombre = archivo.filename or "historia.pdf"
    if not nombre.lower().endswith(".pdf") or (archivo.content_type or "").lower() not in ("application/pdf", "application/octet-stream", ""):
        raise HTTPException(422, "Solo se aceptan archivos PDF.")
    contenido = await archivo.read()
    if len(contenido) > servicio.TAMANO_MAXIMO:
        raise HTTPException(422, "El archivo supera los 20 MB permitidos.")
    if not contenido.startswith(b"%PDF"):
        raise HTTPException(422, "El archivo no es un PDF válido.")
    db = obtener_db()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporal:
        temporal.write(contenido)
        ruta = Path(temporal.name)
    try:
        historia = servicio.preparar(ruta, nombre, usuario["sub"])
    except DocumentoSinTexto:
        raise HTTPException(422, "El PDF no tiene capa de texto. Los documentos escaneados no se procesan en esta versión.")
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        ruta.unlink(missing_ok=True)
    propia = db.historias.find_one({"hash": historia["hash"], "cargada_por": usuario["sub"]}, {"_id": 1})
    if propia:
        raise HTTPException(409, f"Usted ya cargó este documento como {propia['_id']}.")
    base = historia["_id"]
    while db.historias.find_one({"_id": historia["_id"]}, {"_id": 1}):
        historia["_id"] = f"{base}-{secrets.token_hex(2).upper()}"
    db.historias.insert_one(historia)
    registrar_evento("cargar_historia", usuario["sub"], {"historia_id": historia["_id"], "paginas": historia["paginas"], "entidades": len(historia["entidades"])})
    return {"id": historia["_id"], "paginas": historia["paginas"], "entidades": len(historia["entidades"]), "secciones_reconocidas": historia["secciones_reconocidas"], "tiempos_ms": historia["tiempos_ms"]}


def analizar_si_pendiente(historia: dict) -> dict | None:
    from pipeline import servicio

    db = obtener_db()
    if not historia.get("analisis_pendiente"):
        return None
    if not servicio.modelo_disponible():
        return {"aviso": "El análisis con el modelo no está configurado en este servidor; la historia queda sin hallazgos."}
    resultado = servicio.analizar_historia(historia)
    hallazgos = resultado.pop("hallazgos")
    db.hallazgos.delete_many({"historia_id": historia["_id"]})
    if hallazgos:
        db.hallazgos.insert_many(hallazgos)
    db.historias.update_one({"_id": historia["_id"]}, {"$set": {**resultado, "analisis_pendiente": False, "fecha_analisis": ahora()}})
    return {"hallazgos": len(hallazgos), "puntaje": resultado["puntaje"], "latencia_analisis_ms": resultado["latencia_analisis_ms"]}


@app.post("/api/historias/{historia_id}/confirmar-anonimizacion")
def confirmar_anonimizacion(historia_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    historia = historia_visible(historia_id, usuario["sub"])
    revision = revision_de(usuario["sub"], historia_id)
    if revision["estado"] != "pendiente_confirmacion":
        raise HTTPException(409, "La historia no está pendiente de confirmación.")
    analisis = None
    try:
        analisis = analizar_si_pendiente(historia)
    except Exception:
        log.exception("Falló el análisis de %s", historia_id)
        raise HTTPException(502, "No fue posible analizar la historia con el modelo. Intente de nuevo en unos segundos.")
    db.revisiones.update_one(
        {"usuario": usuario["sub"], "historia_id": historia_id},
        {"$set": {"estado": "analizada", "confirmacion": {"fecha": ahora()}, "perfil": usuario.get("perfil")}, "$setOnInsert": {"decisiones": {}, "fecha_inicio": ahora()}},
        upsert=True,
    )
    registrar_evento("confirmar_anonimizacion", usuario["sub"], {"historia_id": historia_id, **(analisis or {})})
    return {"estado": "analizada", "analisis": analisis}


@app.post("/api/hallazgos/{hallazgo_id}/decision")
def decidir(hallazgo_id: str, datos: Decision, usuario: dict = Depends(usuario_actual)):
    if datos.decision == "reclasificado" and not datos.severidad_nueva:
        raise HTTPException(422, "Indique la nueva severidad para reclasificar.")
    if datos.decision == "reclasificado" and not datos.motivo.strip():
        raise HTTPException(422, "Escriba el motivo de la reclasificación.")
    db = obtener_db()
    hallazgo = hallazgo_visible(hallazgo_id, usuario["sub"])
    revision = revision_de(usuario["sub"], hallazgo["historia_id"])
    if revision["estado"] == "pendiente_confirmacion":
        raise HTTPException(409, "Confirme la anonimización antes de decidir.")
    if revision["estado"] == "revisada":
        raise HTTPException(409, "La revisión de esta historia ya fue cerrada.")
    decision = {**datos.model_dump(), "usuario": usuario["sub"], "nombre": usuario.get("nombre"), "fecha": ahora()}
    db.revisiones.update_one({"usuario": usuario["sub"], "historia_id": hallazgo["historia_id"]}, {"$set": {f"decisiones.{hallazgo_id}": decision}})
    registrar_evento("cta_decision", usuario["sub"], {"hallazgo_id": hallazgo_id, "historia_id": hallazgo["historia_id"], "decision": datos.decision})
    return {"estado_revision": datos.decision, "decision": limpiar(decision)}


@app.post("/api/hallazgos/{hallazgo_id}/deshacer")
def deshacer(hallazgo_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    hallazgo = hallazgo_visible(hallazgo_id, usuario["sub"])
    revision = revision_de(usuario["sub"], hallazgo["historia_id"])
    if revision["estado"] == "revisada":
        raise HTTPException(409, "La revisión de esta historia ya fue cerrada.")
    db.revisiones.update_one({"usuario": usuario["sub"], "historia_id": hallazgo["historia_id"]}, {"$unset": {f"decisiones.{hallazgo_id}": ""}})
    registrar_evento("deshacer_decision", usuario["sub"], {"hallazgo_id": hallazgo_id})
    return {"estado_revision": "pendiente"}


@app.post("/api/historias/{historia_id}/cerrar-revision")
def cerrar_revision(historia_id: str, datos: Cierre, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    historia_visible(historia_id, usuario["sub"], {"_id": 1})
    hallazgos = list(db.hallazgos.find({"historia_id": historia_id}, {"_id": 1}))
    if not hallazgos:
        raise HTTPException(404, "Historia sin hallazgos.")
    revision = revision_de(usuario["sub"], historia_id)
    if revision["estado"] == "revisada":
        return limpiar(revision["cierre"])
    decisiones = revision.get("decisiones", {})
    pendientes = [h["_id"] for h in hallazgos if h["_id"] not in decisiones]
    if pendientes:
        raise HTTPException(409, f"Faltan {len(pendientes)} hallazgos por decidir.")
    resumen = {"aceptados": 0, "descartados": 0, "reclasificados": 0}
    for d in decisiones.values():
        resumen[d["decision"] + "s"] += 1
    cierre = {"fecha": ahora(), "segundos_revision": datos.segundos_revision, **resumen}
    db.revisiones.update_one({"usuario": usuario["sub"], "historia_id": historia_id}, {"$set": {"estado": "revisada", "cierre": cierre}})
    registrar_evento("revision_completada", usuario["sub"], {"historia_id": historia_id, **cierre})
    return limpiar(cierre)


def resumir_revisiones(revisiones, hallazgos: dict) -> dict:
    decisiones = {"aceptado": 0, "descartado": 0, "reclasificado": 0}
    por_criterio: dict[str, dict] = {}
    tiempos = []
    participantes = set()
    for r in revisiones:
        for hid, d in r.get("decisiones", {}).items():
            decisiones[d["decision"]] += 1
            participantes.add(r["usuario"])
            criterio = hallazgos.get(hid, {}).get("criterio_id", "?")
            c = por_criterio.setdefault(criterio, {"total": 0, "descartados": 0})
            c["total"] += 1
            c["descartados"] += d["decision"] == "descartado"
        if r.get("cierre"):
            tiempos.append(r["cierre"]["segundos_revision"])
    revisados = sum(decisiones.values())
    return {
        "hallazgos_revisados": revisados,
        "decisiones": decisiones,
        "tasa_aceptacion": round(decisiones["aceptado"] / revisados, 3) if revisados else None,
        "tiempo_medio_revision": round(sum(tiempos) / len(tiempos)) if tiempos else None,
        "historias_cerradas": len(tiempos),
        "participantes": len(participantes),
        "por_criterio": por_criterio,
    }


@app.get("/api/metricas")
def metricas(alcance: Literal["personal", "estudio"] = "personal", usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    administrador = es_admin(usuario)
    if alcance == "estudio" and not administrador:
        raise HTTPException(403, "Las métricas del estudio solo están disponibles para administradores.")
    visibles = [h["_id"] for h in db.historias.find(filtro_visibles(usuario["sub"]), {"_id": 1})]
    filtro_hallazgos = {} if alcance == "estudio" else {"historia_id": {"$in": visibles}}
    hallazgos = {h["_id"]: h for h in db.hallazgos.find(filtro_hallazgos, {"familia": 1, "severidad": 1, "criterio_id": 1})}
    if alcance == "estudio":
        medidos = [u["_id"] for u in db.usuarios.find({"perfil": {"$in": list(PERFILES_MEDIDOS)}}, {"_id": 1})]
        revisiones = db.revisiones.find({"$or": [{"usuario": {"$in": medidos}}, {"usuario": {"$regex": "^" + re.escape(DEMO_CORREO + PREFIJO_AUDITOR)}}]})
    else:
        revisiones = db.revisiones.find({"usuario": usuario["sub"], "historia_id": {"$in": visibles}})
    resumen = resumir_revisiones(revisiones, hallazgos)
    por_familia: dict[str, int] = {}
    por_severidad: dict[str, int] = {}
    for h in hallazgos.values():
        por_familia[h["familia"]] = por_familia.get(h["familia"], 0) + 1
        por_severidad[h["severidad"]] = por_severidad.get(h["severidad"], 0) + 1
    propias = {r["historia_id"]: r["estado"] for r in db.revisiones.find({"usuario": usuario["sub"], "historia_id": {"$in": visibles}}, {"historia_id": 1, "estado": 1})}
    estados = {"analizada": sum(1 for e in propias.values() if e == "analizada"), "revisada": sum(1 for e in propias.values() if e == "revisada")}
    estados["pendiente_confirmacion"] = len(visibles) - estados["analizada"] - estados["revisada"]
    return {
        "alcance": alcance,
        "puede_ver_estudio": administrador,
        "historias_por_estado": estados,
        "hallazgos_total": len(hallazgos),
        **resumen,
        "por_familia": por_familia,
        "por_severidad": por_severidad,
        "pipeline": limpiar(db.metricas_pipeline.find_one({"_id": "ultima_corrida"}) or {}),
    }


@app.post("/api/traza", status_code=204)
def traza(datos: Traza):
    detalle = {str(k)[:40]: str(v)[:200] for k, v in list(datos.detalle.items())[:8]}
    sesion = datos_de_token(datos.token)
    obtener_db().trazas.insert_one({"traza": datos.traza, "usuario": sesion.get("sub"), "perfil": sesion.get("perfil"), "tipo": datos.tipo, "ruta": datos.ruta, "ms": datos.ms, "detalle": detalle, "fecha": ahora()})


@app.post("/api/eventos", status_code=204)
def evento(datos: Evento, usuario: dict = Depends(usuario_actual)):
    registrar_evento(datos.tipo, usuario["sub"], datos.detalle)


@app.get("/", include_in_schema=False)
def raiz():
    return FileResponse(WEB / "index.html")


@app.exception_handler(404)
async def no_encontrado(request: Request, exc):
    if request.url.path.startswith("/api"):
        detalle = getattr(exc, "detail", None)
        if not isinstance(detalle, str) or detalle == "Not Found":
            detalle = "Recurso no encontrado."
        return JSONResponse({"detail": detalle}, status_code=404)
    return FileResponse(WEB / "404.html", status_code=404)


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
