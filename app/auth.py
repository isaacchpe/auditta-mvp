import hashlib
import hmac
import os
import re
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import JWT_HORAS, JWT_SECRETO
from app.db import obtener_db

ITERACIONES = 200_000
INTENTOS_MAXIMOS = 5
BLOQUEO_SEGUNDOS = 15 * 60
ACTUALIZAR_ACTIVIDAD_CADA = 60
HASH_FICTICIO = "00" * 16 + "$" + "00" * 32
portador = HTTPBearer(auto_error=False)


def hashear(clave: str) -> str:
    sal = os.urandom(16)
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, ITERACIONES)
    return f"{sal.hex()}${derivada.hex()}"


def verificar(clave: str, almacenado: str | None) -> bool:
    sal_hex, derivada_hex = (almacenado or HASH_FICTICIO).split("$")
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal_hex), ITERACIONES)
    return bool(almacenado) and hmac.compare_digest(derivada.hex(), derivada_hex)


def problema_de_clave(clave: str) -> str | None:
    if len(clave) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if len(clave) > 64:
        return "La contraseña no puede superar 64 caracteres."
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", clave) or not re.search(r"\d", clave):
        return "La contraseña debe combinar letras y números."
    return None


def ahora_ts() -> int:
    return int(time.time())


def describir_agente(agente: str) -> str:
    agente = agente or ""
    navegador = next((n for clave, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if clave in agente), "Navegador")
    sistema = next((n for clave, n in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Mac OS", "macOS"), ("Linux", "Linux")) if clave in agente), "")
    return f"{navegador} en {sistema}" if sistema else navegador


def crear_sesion(usuario: dict, request: Request | None, duracion: int | None = None) -> str:
    sid = secrets.token_urlsafe(24)
    inicio = ahora_ts()
    agente = request.headers.get("user-agent", "") if request else ""
    obtener_db().sesiones.insert_one({
        "_id": sid,
        "usuario": usuario["_id"],
        "creada_ts": inicio,
        "actividad_ts": inicio,
        "expira_ts": inicio + (duracion or JWT_HORAS * 3600),
        "dispositivo": describir_agente(agente),
        "agente": agente[:200],
        "activa": True,
    })
    return sid


def emitir_token(usuario: dict, sid: str) -> str:
    sesion = obtener_db().sesiones.find_one({"_id": sid}, {"expira_ts": 1})
    carga = {"sub": usuario["_id"], "nombre": usuario["nombre"], "perfil": usuario["perfil"], "sid": sid, "exp": sesion["expira_ts"]}
    return jwt.encode(carga, JWT_SECRETO, algorithm="HS256")


def respuesta_de_ingreso(usuario: dict, request: Request | None, duracion: int | None = None) -> dict:
    sid = crear_sesion(usuario, request, duracion)
    return {"token": emitir_token(usuario, sid), "nombre": usuario["nombre"], "perfil": usuario["perfil"], "correo": usuario["_id"], "demo": bool(usuario.get("demo"))}


def cerrar_sesiones(usuario_id: str, excepto: str | None = None) -> int:
    filtro = {"usuario": usuario_id, "activa": True}
    if excepto:
        filtro["_id"] = {"$ne": excepto}
    return obtener_db().sesiones.update_many(filtro, {"$set": {"activa": False, "cerrada_ts": ahora_ts()}}).modified_count


def datos_de_token(token: str | None) -> dict:
    if not token:
        return {}
    try:
        return jwt.decode(token, JWT_SECRETO, algorithms=["HS256"])
    except jwt.PyJWTError:
        return {}


def usuario_actual(credencial: HTTPAuthorizationCredentials | None = Depends(portador)) -> dict:
    if credencial is None:
        raise HTTPException(401, "Inicie sesión para continuar.")
    try:
        carga = jwt.decode(credencial.credentials, JWT_SECRETO, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "La sesión expiró. Inicie sesión de nuevo.")
    db = obtener_db()
    momento = ahora_ts()
    sesion = db.sesiones.find_one({"_id": carga.get("sid"), "usuario": carga.get("sub"), "activa": True}) if carga.get("sid") else None
    if not sesion or sesion["expira_ts"] <= momento:
        raise HTTPException(401, "La sesión fue cerrada. Inicie sesión de nuevo.")
    if momento - sesion.get("actividad_ts", 0) >= ACTUALIZAR_ACTIVIDAD_CADA:
        db.sesiones.update_one({"_id": sesion["_id"]}, {"$set": {"actividad_ts": momento}})
    return carga
