import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import obtener_db

SALIDA = Path(__file__).resolve().parent / "salida"


def cargar(reiniciar_revisiones: bool = False) -> dict:
    db = obtener_db()
    ahora = datetime.now(timezone.utc)
    historias = 0
    hallazgos = 0
    for ruta in sorted((SALIDA / "historias").glob("*.json")):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        lista = datos.pop("hallazgos_lista", [])
        datos["fecha_carga"] = ahora
        db.historias.replace_one({"_id": datos["_id"]}, datos, upsert=True)
        db.hallazgos.delete_many({"historia_id": datos["_id"]})
        historias += 1
        for hallazgo in lista:
            hallazgo.pop("estado_revision", None)
            db.hallazgos.replace_one({"_id": hallazgo["_id"]}, hallazgo, upsert=True)
            hallazgos += 1
        if reiniciar_revisiones:
            db.revisiones.delete_many({"historia_id": datos["_id"]})
    resumen_ruta = SALIDA / "metricas_pipeline.json"
    if resumen_ruta.exists():
        resumen = json.loads(resumen_ruta.read_text(encoding="utf-8"))
        resumen["_id"] = "ultima_corrida"
        resumen["fecha_carga"] = ahora
        db.metricas_pipeline.replace_one({"_id": "ultima_corrida"}, resumen, upsert=True)
    return {"historias": historias, "hallazgos": hallazgos}


if __name__ == "__main__":
    if not os.environ.get("MONGODB_URI"):
        print("Defina MONGODB_URI para cargar a la base de datos")
        sys.exit(1)
    print(cargar(reiniciar_revisiones="--reiniciar" in sys.argv))
