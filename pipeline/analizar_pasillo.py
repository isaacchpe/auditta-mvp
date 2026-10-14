import json
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.db import obtener_db

UMBRAL_MS = 5000


def recorridos(perfiles=("desarrollador",)):
    db = obtener_db()
    perfil_de = {u["_id"]: u.get("perfil") for u in db.usuarios.find({}, {"perfil": 1})}
    por_traza = defaultdict(list)
    for t in db.trazas.find({}).sort("fecha", 1):
        por_traza[t["traza"]].append(t)
    resultado = []
    for traza, eventos in por_traza.items():
        usuario = next((e["usuario"] for e in reversed(eventos) if e.get("usuario")), None)
        if not usuario or perfil_de.get(usuario) not in perfiles:
            continue
        visitas, actual = [], None
        for e in eventos:
            if e["tipo"] == "pantalla":
                actual = {"ruta": e["ruta"], "inicio": e["fecha"], "eventos": []}
                visitas.append(actual)
            elif actual is not None and e["ruta"] == actual["ruta"]:
                actual["eventos"].append(e)
        dudas = []
        for v in visitas:
            anterior = 0
            for e in v["eventos"]:
                if e["tipo"] in ("clic", "validacion") and e["ms"] - anterior > UMBRAL_MS:
                    dudas.append({"pantalla": v["ruta"].split("?")[0], "segundos": round((e["ms"] - anterior) / 1000, 1), "antes_de": e["detalle"].get("texto") or e["detalle"].get("mensaje") or e["tipo"]})
                if e["tipo"] in ("clic", "validacion"):
                    anterior = e["ms"]
        resultado.append({
            "usuario": usuario,
            "inicio": str(eventos[0]["fecha"])[:19],
            "minutos": round((eventos[-1]["fecha"] - eventos[0]["fecha"]).total_seconds() / 60, 1),
            "pantallas": [v["ruta"].split("?")[0] for v in visitas],
            "clics": sum(1 for e in eventos if e["tipo"] == "clic"),
            "dudas_mayores_5s": dudas,
            "validaciones": [e["detalle"].get("mensaje") for e in eventos if e["tipo"] == "validacion"],
            "errores_js": [e["detalle"].get("mensaje") for e in eventos if e["tipo"] == "error_js"],
        })
    return resultado


if __name__ == "__main__":
    perfiles = tuple(sys.argv[1:]) or ("desarrollador",)
    print(json.dumps(recorridos(perfiles), ensure_ascii=False, indent=1))
