import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.auth import emitir_token, hashear, usuario_actual, verificar
from app.config import DEMO_CLAVE, DEMO_CORREO, FORMULARIO_RETROALIMENTACION, RAIZ, VERSION_APP
from app.db import obtener_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("auditta")

@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    from app.semilla import sembrar_si_vacio, sembrar_usuario_demo

    try:
        sembrar_si_vacio()
        sembrar_usuario_demo()
    except Exception:
        log.exception("No fue posible sembrar los datos iniciales")
    yield


app = FastAPI(title="Auditta MVP", version=VERSION_APP, docs_url=None, redoc_url=None, lifespan=ciclo_de_vida)
WEB = RAIZ / "web"
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERFILES = ("auditor_medico", "facturacion", "coordinador", "desarrollador", "otro")


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
    if request.url.path.startswith("/api"):
        log.info("%s %s %d %.0fms", request.method, request.url.path, respuesta.status_code, (time.perf_counter() - inicio) * 1000)
    return respuesta


class Ingreso(BaseModel):
    correo: str
    clave: str


class Registro(BaseModel):
    nombre: str = Field(min_length=3, max_length=80)
    correo: str
    clave: str = Field(min_length=8, max_length=64)
    perfil: Literal[PERFILES]

    @field_validator("correo")
    @classmethod
    def correo_valido(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if not CORREO.match(valor):
            raise ValueError("Escriba un correo válido.")
        return valor


class Decision(BaseModel):
    decision: Literal["aceptado", "descartado", "reclasificado"]
    severidad_nueva: Literal["alta", "media", "baja"] | None = None
    motivo: str = Field(default="", max_length=500)
    segundos_desde_apertura: float | None = Field(default=None, ge=0)


class Cierre(BaseModel):
    segundos_revision: float = Field(ge=0)


class Evento(BaseModel):
    tipo: str = Field(max_length=40)
    detalle: dict = {}


@app.get("/api/salud")
def salud():
    obtener_db().command("ping")
    return {"estado": "ok", "version": VERSION_APP}


@app.get("/api/configuracion")
def configuracion():
    demo = {"correo": DEMO_CORREO, "clave": DEMO_CLAVE} if DEMO_CORREO and DEMO_CLAVE else None
    return {"formulario_retroalimentacion": FORMULARIO_RETROALIMENTACION, "cuenta_prueba": demo}


@app.post("/api/auth/ingreso")
def ingreso(datos: Ingreso):
    usuario = obtener_db().usuarios.find_one({"_id": datos.correo.strip().lower()})
    if not usuario or not verificar(datos.clave, usuario["hash"]):
        raise HTTPException(401, "Correo o contraseña incorrectos.")
    registrar_evento("ingreso", usuario["_id"])
    return {"token": emitir_token(usuario["_id"], usuario["nombre"], usuario["perfil"]), "nombre": usuario["nombre"], "perfil": usuario["perfil"]}


@app.post("/api/auth/registro", status_code=201)
def registro(datos: Registro):
    db = obtener_db()
    if db.usuarios.find_one({"_id": datos.correo}):
        raise HTTPException(409, "Ya existe una cuenta con ese correo.")
    db.usuarios.insert_one({"_id": datos.correo, "nombre": datos.nombre.strip(), "perfil": datos.perfil, "hash": hashear(datos.clave), "fecha_creacion": ahora()})
    registrar_evento("registro", datos.correo, {"perfil": datos.perfil})
    return {"token": emitir_token(datos.correo, datos.nombre, datos.perfil), "nombre": datos.nombre, "perfil": datos.perfil}


def resumen_historia(historia: dict, hallazgos: list[dict]) -> dict:
    revisados = [h for h in hallazgos if h.get("estado_revision", "pendiente") != "pendiente"]
    return {
        "_id": historia["_id"],
        "plantilla": historia.get("plantilla"),
        "paginas": historia.get("paginas"),
        "estado": historia.get("estado"),
        "puntaje": historia.get("puntaje"),
        "nivel": historia.get("nivel"),
        "num_hallazgos": len(hallazgos),
        "revisados": len(revisados),
        "error": historia.get("error"),
        "fecha_carga": historia.get("fecha_carga"),
    }


@app.get("/api/historias")
def listar_historias(usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    conteo: dict[str, list[dict]] = {}
    for hallazgo in db.hallazgos.find({}, {"historia_id": 1, "estado_revision": 1}):
        conteo.setdefault(hallazgo["historia_id"], []).append(hallazgo)
    historias = [limpiar(resumen_historia(h, conteo.get(h["_id"], []))) for h in db.historias.find({}, {"texto_anonimizado": 0, "entidades": 0, "secciones": 0})]
    historias.sort(key=lambda h: (h["puntaje"] is None, -(h["puntaje"] or 0)))
    return {"historias": historias}


@app.get("/api/historias/{historia_id}")
def ver_historia(historia_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    historia = db.historias.find_one({"_id": historia_id})
    if not historia:
        raise HTTPException(404, "Historia no encontrada.")
    hallazgos = [limpiar(h) for h in db.hallazgos.find({"historia_id": historia_id}).sort("orden", 1)]
    registrar_evento("ver_historia", usuario["sub"], {"historia_id": historia_id})
    return {**limpiar(historia), "hallazgos": hallazgos}


@app.post("/api/historias/{historia_id}/confirmar-anonimizacion")
def confirmar_anonimizacion(historia_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    resultado = db.historias.update_one(
        {"_id": historia_id, "estado": "pendiente_confirmacion"},
        {"$set": {"estado": "analizada", "confirmacion": {"usuario": usuario["sub"], "fecha": ahora()}}},
    )
    if resultado.matched_count == 0:
        raise HTTPException(409, "La historia no está pendiente de confirmación.")
    registrar_evento("confirmar_anonimizacion", usuario["sub"], {"historia_id": historia_id})
    return {"estado": "analizada"}


@app.post("/api/hallazgos/{hallazgo_id}/decision")
def decidir(hallazgo_id: str, datos: Decision, usuario: dict = Depends(usuario_actual)):
    if datos.decision == "reclasificado" and not datos.severidad_nueva:
        raise HTTPException(422, "Indique la nueva severidad para reclasificar.")
    if datos.decision == "reclasificado" and not datos.motivo.strip():
        raise HTTPException(422, "Escriba el motivo de la reclasificación.")
    db = obtener_db()
    hallazgo = db.hallazgos.find_one({"_id": hallazgo_id})
    if not hallazgo:
        raise HTTPException(404, "Hallazgo no encontrado.")
    decision = {**datos.model_dump(), "usuario": usuario["sub"], "nombre": usuario.get("nombre"), "fecha": ahora()}
    cambios = {"estado_revision": datos.decision, "ultima_decision": decision}
    if datos.decision == "reclasificado":
        cambios["severidad_revisada"] = datos.severidad_nueva
    db.hallazgos.update_one({"_id": hallazgo_id}, {"$set": cambios, "$push": {"decisiones": decision}})
    registrar_evento("cta_decision", usuario["sub"], {"hallazgo_id": hallazgo_id, "historia_id": hallazgo["historia_id"], "decision": datos.decision})
    return {"estado_revision": datos.decision, "decision": limpiar(decision)}


@app.post("/api/hallazgos/{hallazgo_id}/deshacer")
def deshacer(hallazgo_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    resultado = db.hallazgos.update_one({"_id": hallazgo_id}, {"$set": {"estado_revision": "pendiente"}, "$unset": {"ultima_decision": "", "severidad_revisada": ""}})
    if resultado.matched_count == 0:
        raise HTTPException(404, "Hallazgo no encontrado.")
    registrar_evento("deshacer_decision", usuario["sub"], {"hallazgo_id": hallazgo_id})
    return {"estado_revision": "pendiente"}


@app.post("/api/historias/{historia_id}/cerrar-revision")
def cerrar_revision(historia_id: str, datos: Cierre, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    hallazgos = list(db.hallazgos.find({"historia_id": historia_id}))
    if not hallazgos:
        raise HTTPException(404, "Historia sin hallazgos.")
    pendientes = [h for h in hallazgos if h.get("estado_revision", "pendiente") == "pendiente"]
    if pendientes:
        raise HTTPException(409, f"Faltan {len(pendientes)} hallazgos por decidir.")
    resumen = {"aceptados": 0, "descartados": 0, "reclasificados": 0}
    for h in hallazgos:
        resumen[h["estado_revision"] + "s"] += 1
    cierre = {"usuario": usuario["sub"], "fecha": ahora(), "segundos_revision": datos.segundos_revision, **resumen}
    db.historias.update_one({"_id": historia_id}, {"$set": {"estado": "revisada", "cierre": cierre}})
    registrar_evento("revision_completada", usuario["sub"], {"historia_id": historia_id, **cierre})
    return limpiar(cierre)


@app.get("/api/metricas")
def metricas(usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    hallazgos = list(db.hallazgos.find({}, {"familia": 1, "severidad": 1, "estado_revision": 1, "criterio_id": 1}))
    revisados = [h for h in hallazgos if h.get("estado_revision", "pendiente") != "pendiente"]
    decisiones = {"aceptado": 0, "descartado": 0, "reclasificado": 0}
    for h in revisados:
        decisiones[h["estado_revision"]] += 1
    por_familia: dict[str, int] = {}
    por_severidad: dict[str, int] = {}
    por_criterio: dict[str, dict] = {}
    for h in hallazgos:
        por_familia[h["familia"]] = por_familia.get(h["familia"], 0) + 1
        por_severidad[h["severidad"]] = por_severidad.get(h["severidad"], 0) + 1
        c = por_criterio.setdefault(h["criterio_id"], {"total": 0, "descartados": 0})
        c["total"] += 1
        if h.get("estado_revision") == "descartado":
            c["descartados"] += 1
    estados: dict[str, int] = {}
    tiempos = []
    for h in db.historias.find({}, {"estado": 1, "cierre": 1}):
        estados[h["estado"]] = estados.get(h["estado"], 0) + 1
        if h.get("cierre"):
            tiempos.append(h["cierre"]["segundos_revision"])
    participantes = db.usuarios.count_documents({"perfil": {"$in": ["auditor_medico", "facturacion", "coordinador"]}})
    return {
        "historias_por_estado": estados,
        "hallazgos_total": len(hallazgos),
        "hallazgos_revisados": len(revisados),
        "decisiones": decisiones,
        "tasa_aceptacion": round(decisiones["aceptado"] / len(revisados), 3) if revisados else None,
        "tiempo_medio_revision": round(sum(tiempos) / len(tiempos)) if tiempos else None,
        "historias_cerradas": len(tiempos),
        "participantes": participantes,
        "por_familia": por_familia,
        "por_severidad": por_severidad,
        "por_criterio": por_criterio,
        "pipeline": limpiar(db.metricas_pipeline.find_one({"_id": "ultima_corrida"}) or {}),
    }


@app.post("/api/eventos", status_code=204)
def evento(datos: Evento, usuario: dict = Depends(usuario_actual)):
    registrar_evento(datos.tipo, usuario["sub"], datos.detalle)


@app.get("/", include_in_schema=False)
def raiz():
    return FileResponse(WEB / "index.html")


@app.exception_handler(404)
async def no_encontrado(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "Recurso no encontrado."}, status_code=404)
    return FileResponse(WEB / "404.html", status_code=404)


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
