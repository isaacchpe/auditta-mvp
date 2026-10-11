import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.auth import hashear, verificar
from app.config import DEMO_CLAVE, DEMO_CORREO, DEMO_NOMBRE, RAIZ
from app.db import obtener_db

log = logging.getLogger("auditta.semilla")
SALIDA = RAIZ / "pipeline" / "salida"


def sembrar_usuario_demo() -> bool:
    if not DEMO_CORREO or not DEMO_CLAVE:
        return False
    db = obtener_db()
    existente = db.usuarios.find_one({"_id": DEMO_CORREO})
    if existente and verificar(DEMO_CLAVE, existente["hash"]):
        return False
    db.usuarios.update_one(
        {"_id": DEMO_CORREO},
        {"$set": {"nombre": DEMO_NOMBRE, "perfil": "evaluador", "hash": hashear(DEMO_CLAVE), "demo": True}, "$setOnInsert": {"fecha_creacion": datetime.now(timezone.utc)}},
        upsert=True,
    )
    log.info("Usuario de prueba disponible: %s", DEMO_CORREO)
    return True


def sembrar_si_vacio() -> int:
    db = obtener_db()
    if db.historias.count_documents({}) > 0:
        return 0
    carpeta = SALIDA / "historias"
    if not carpeta.exists():
        return 0
    ahora = datetime.now(timezone.utc)
    cargadas = 0
    for ruta in sorted(carpeta.glob("*.json")):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        hallazgos = datos.pop("hallazgos_lista", [])
        datos["fecha_carga"] = ahora
        db.historias.replace_one({"_id": datos["_id"]}, datos, upsert=True)
        for hallazgo in hallazgos:
            hallazgo.setdefault("estado_revision", "pendiente")
            db.hallazgos.replace_one({"_id": hallazgo["_id"]}, hallazgo, upsert=True)
        cargadas += 1
    resumen = SALIDA / "metricas_pipeline.json"
    if resumen.exists():
        datos = json.loads(resumen.read_text(encoding="utf-8"))
        datos["_id"] = "ultima_corrida"
        db.metricas_pipeline.replace_one({"_id": "ultima_corrida"}, datos, upsert=True)
    log.info("Semilla inicial: %d historias cargadas", cargadas)
    return cargadas
