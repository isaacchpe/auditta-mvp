import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def variable(nombre: str, predeterminado: str = "") -> str:
    return os.environ.get(nombre, predeterminado).strip()


MONGODB_URI = variable("MONGODB_URI", "mongomock://localhost")
MONGODB_DB = variable("MONGODB_DB", "auditta")
JWT_SECRETO = variable("JWT_SECRETO", "solo-desarrollo")
JWT_HORAS = int(variable("JWT_HORAS", "12"))
FORMULARIO_RETROALIMENTACION = variable("FORMULARIO_RETROALIMENTACION")
DEMO_CORREO = variable("DEMO_CORREO", "evaluador@auditta.test").lower()
DEMO_HORAS = int(variable("DEMO_HORAS", "24"))
ADMIN_CORREOS = {c.strip().lower() for c in variable("ADMIN_CORREOS").split(",") if c.strip()}
CONTACTO_PRIVACIDAD = variable("CONTACTO_PRIVACIDAD")
VERSION_APP = "0.2.0"
