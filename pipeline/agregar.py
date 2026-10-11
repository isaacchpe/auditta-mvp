import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

from app.db import obtener_db
from pipeline import ejecutar

CORPUS_PDF = RAIZ / "corpus" / "pdf"
SALIDA = Path(__file__).resolve().parent / "salida"


def identificador(ruta: Path) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", ruta.stem).strip("-").upper()[:40]
    return base or f"HC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def agregar(ruta: Path, con_modelo: bool = True) -> dict:
    if not ruta.exists() or ruta.suffix.lower() != ".pdf":
        raise SystemExit(f"No es un PDF válido: {ruta}")
    hid = identificador(ruta)
    destino = CORPUS_PDF / f"{hid}.pdf"
    CORPUS_PDF.mkdir(parents=True, exist_ok=True)
    if ruta.resolve() != destino.resolve():
        shutil.copy2(ruta, destino)
    medicion = ejecutar.procesar(destino, None, con_modelo)
    datos = json.loads((SALIDA / "historias" / f"{hid}.json").read_text(encoding="utf-8"))
    lista = datos.pop("hallazgos_lista", [])
    db = obtener_db()
    datos["fecha_carga"] = datetime.now(timezone.utc)
    db.historias.replace_one({"_id": hid}, datos, upsert=True)
    db.hallazgos.delete_many({"historia_id": hid})
    for hallazgo in lista:
        hallazgo.pop("estado_revision", None)
        db.hallazgos.replace_one({"_id": hallazgo["_id"]}, hallazgo, upsert=True)
    db.revisiones.delete_many({"historia_id": hid})
    return {"id": hid, "paginas": datos["paginas"], "entidades": len(datos["entidades"]), "hallazgos": len(lista), "puntaje": datos.get("puntaje"), "ms": medicion["latencia_total_ms"]}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python pipeline/agregar.py <ruta del PDF> [--sin-modelo]")
        sys.exit(1)
    print(agregar(Path(sys.argv[1]), "--sin-modelo" not in sys.argv))
