import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

MONGODB_URI = os.environ.get("MONGODB_URI", "mongomock://localhost")
MONGODB_DB = os.environ.get("MONGODB_DB", "auditta")
JWT_SECRETO = os.environ.get("JWT_SECRETO", "solo-desarrollo")
JWT_HORAS = int(os.environ.get("JWT_HORAS", "12"))
FORMULARIO_RETROALIMENTACION = os.environ.get("FORMULARIO_RETROALIMENTACION", "")
VERSION_APP = "0.1.0"
