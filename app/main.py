import logging
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.auth import datos_de_token, emitir_token, hashear, usuario_actual, verificar
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
        db = obtener_db()
        db.revisiones.create_index([("usuario", 1), ("historia_id", 1)], unique=True)
        db.hallazgos.create_index("historia_id")
        db.eventos.create_index("fecha")
    except Exception:
        log.exception("No fue posible preparar los datos iniciales")
    yield


app = FastAPI(title="Auditta MVP", version=VERSION_APP, docs_url=None, redoc_url=None, lifespan=ciclo_de_vida)
WEB = RAIZ / "web"
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERFILES = ("auditor_medico", "facturacion", "coordinador", "desarrollador", "otro")
PERFILES_MEDIDOS = ("auditor_medico", "facturacion", "coordinador")
PARTICIPANTES_EXCLUIDOS = {"evaluador", "evaluadora", "docente", "profesor", "profesora", "prueba"}


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
    return respuesta


class Ingreso(BaseModel):
    correo: str
    clave: str
    participante: str | None = Field(default=None, max_length=60)
    rol: Literal["auditor_medico", "desarrollador", "evaluador"] | None = None


def identificador_participante(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plano).strip("-")


def es_participante_compartido(usuario: str) -> bool:
    return bool(DEMO_CORREO) and usuario.startswith(DEMO_CORREO + "#")


PREFIJO_AUDITOR = "#auditor_medico#"


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
    sujeto, nombre, perfil = usuario["_id"], usuario["nombre"], usuario["perfil"]
    if usuario["_id"] == DEMO_CORREO and datos.participante and datos.rol in ("auditor_medico", "desarrollador"):
        identificador = identificador_participante(datos.participante)
        if identificador and identificador not in PARTICIPANTES_EXCLUIDOS:
            sujeto, nombre, perfil = f"{usuario['_id']}#{datos.rol}#{identificador}", datos.participante.strip(), datos.rol
    registrar_evento("ingreso", sujeto)
    return {"token": emitir_token(sujeto, nombre, perfil), "nombre": nombre, "perfil": perfil}


@app.post("/api/auth/registro", status_code=201)
def registro(datos: Registro):
    db = obtener_db()
    if db.usuarios.find_one({"_id": datos.correo}):
        raise HTTPException(409, "Ya existe una cuenta con ese correo.")
    db.usuarios.insert_one({"_id": datos.correo, "nombre": datos.nombre.strip(), "perfil": datos.perfil, "hash": hashear(datos.clave), "fecha_creacion": ahora()})
    registrar_evento("registro", datos.correo, {"perfil": datos.perfil})
    return {"token": emitir_token(datos.correo, datos.nombre, datos.perfil), "nombre": datos.nombre, "perfil": datos.perfil}


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
    conteo: dict[str, int] = {}
    for hallazgo in db.hallazgos.find({}, {"historia_id": 1}):
        conteo[hallazgo["historia_id"]] = conteo.get(hallazgo["historia_id"], 0) + 1
    revisiones = {r["historia_id"]: r for r in db.revisiones.find({"usuario": usuario["sub"]})}
    historias = []
    for h in db.historias.find({}, {"texto_anonimizado": 0, "entidades": 0, "secciones": 0}):
        revision = revisiones.get(h["_id"]) or {"estado": "pendiente_confirmacion", "decisiones": {}}
        historias.append(limpiar(resumen_historia(h, conteo.get(h["_id"], 0), revision)))
    historias.sort(key=lambda h: (h["puntaje"] is None, -(h["puntaje"] or 0)))
    return {"historias": historias}


@app.get("/api/historias/{historia_id}")
def ver_historia(historia_id: str, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    historia = db.historias.find_one({"_id": historia_id})
    if not historia:
        raise HTTPException(404, "Historia no encontrada.")
    revision = revision_de(usuario["sub"], historia_id)
    decisiones = revision.get("decisiones", {})
    hallazgos = [limpiar(fusionar_hallazgo(h, decisiones.get(h["_id"]))) for h in db.hallazgos.find({"historia_id": historia_id}).sort("orden", 1)]
    for campo in ("estado", "confirmacion", "cierre"):
        if campo in revision:
            historia[campo] = revision[campo]
    historia["estado"] = revision["estado"]
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
    existente = db.historias.find_one({"hash": historia["hash"]}, {"_id": 1})
    if existente:
        raise HTTPException(409, f"Este documento ya fue cargado como {existente['_id']}.")
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
    historia = db.historias.find_one({"_id": historia_id})
    if not historia:
        raise HTTPException(404, "Historia no encontrada.")
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
    hallazgo = db.hallazgos.find_one({"_id": hallazgo_id})
    if not hallazgo:
        raise HTTPException(404, "Hallazgo no encontrado.")
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
    hallazgo = db.hallazgos.find_one({"_id": hallazgo_id}, {"historia_id": 1})
    if not hallazgo:
        raise HTTPException(404, "Hallazgo no encontrado.")
    revision = revision_de(usuario["sub"], hallazgo["historia_id"])
    if revision["estado"] == "revisada":
        raise HTTPException(409, "La revisión de esta historia ya fue cerrada.")
    db.revisiones.update_one({"usuario": usuario["sub"], "historia_id": hallazgo["historia_id"]}, {"$unset": {f"decisiones.{hallazgo_id}": ""}})
    registrar_evento("deshacer_decision", usuario["sub"], {"hallazgo_id": hallazgo_id})
    return {"estado_revision": "pendiente"}


@app.post("/api/historias/{historia_id}/cerrar-revision")
def cerrar_revision(historia_id: str, datos: Cierre, usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
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


@app.get("/api/metricas")
def metricas(usuario: dict = Depends(usuario_actual)):
    db = obtener_db()
    hallazgos = {h["_id"]: h for h in db.hallazgos.find({}, {"familia": 1, "severidad": 1, "criterio_id": 1})}
    medidos = {u["_id"] for u in db.usuarios.find({"perfil": {"$in": list(PERFILES_MEDIDOS)}}, {"_id": 1})}
    decisiones = {"aceptado": 0, "descartado": 0, "reclasificado": 0}
    por_criterio: dict[str, dict] = {}
    tiempos = []
    participantes = set()
    for r in db.revisiones.find({"$or": [{"usuario": {"$in": list(medidos)}}, {"usuario": {"$regex": "^" + re.escape(DEMO_CORREO + PREFIJO_AUDITOR)}}]}):
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
    por_familia: dict[str, int] = {}
    por_severidad: dict[str, int] = {}
    for h in hallazgos.values():
        por_familia[h["familia"]] = por_familia.get(h["familia"], 0) + 1
        por_severidad[h["severidad"]] = por_severidad.get(h["severidad"], 0) + 1
    propias = {r["historia_id"]: r["estado"] for r in db.revisiones.find({"usuario": usuario["sub"]}, {"historia_id": 1, "estado": 1})}
    total_historias = db.historias.count_documents({})
    estados = {"analizada": sum(1 for e in propias.values() if e == "analizada"), "revisada": sum(1 for e in propias.values() if e == "revisada")}
    estados["pendiente_confirmacion"] = total_historias - estados["analizada"] - estados["revisada"]
    return {
        "historias_por_estado": estados,
        "hallazgos_total": len(hallazgos),
        "hallazgos_revisados": revisados,
        "decisiones": decisiones,
        "tasa_aceptacion": round(decisiones["aceptado"] / revisados, 3) if revisados else None,
        "tiempo_medio_revision": round(sum(tiempos) / len(tiempos)) if tiempos else None,
        "historias_cerradas": len(tiempos),
        "participantes": len(participantes),
        "por_familia": por_familia,
        "por_severidad": por_severidad,
        "por_criterio": por_criterio,
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
