import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import JWT_HORAS, JWT_SECRETO

ITERACIONES = 200_000
portador = HTTPBearer(auto_error=False)


def hashear(clave: str) -> str:
    sal = os.urandom(16)
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, ITERACIONES)
    return f"{sal.hex()}${derivada.hex()}"


def verificar(clave: str, almacenado: str) -> bool:
    sal_hex, derivada_hex = almacenado.split("$")
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal_hex), ITERACIONES)
    return hmac.compare_digest(derivada.hex(), derivada_hex)


def emitir_token(correo: str, nombre: str, perfil: str) -> str:
    expira = datetime.now(timezone.utc) + timedelta(hours=JWT_HORAS)
    return jwt.encode({"sub": correo, "nombre": nombre, "perfil": perfil, "exp": expira}, JWT_SECRETO, algorithm="HS256")


def sujeto_de_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRETO, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None


def usuario_actual(credencial: HTTPAuthorizationCredentials | None = Depends(portador)) -> dict:
    if credencial is None:
        raise HTTPException(401, "Inicie sesión para continuar.")
    try:
        return jwt.decode(credencial.credentials, JWT_SECRETO, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "La sesión expiró. Inicie sesión de nuevo.")
