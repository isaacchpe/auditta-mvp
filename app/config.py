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
DEMO_CLAVE = variable("DEMO_CLAVE", "Auditta2026")
DEMO_NOMBRE = variable("DEMO_NOMBRE", "Evaluador de prueba")
VERSION_APP = "0.1.0"
