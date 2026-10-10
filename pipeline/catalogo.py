import json
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "criterios" / "criterios_v1.json"


def cargar() -> dict:
    return json.loads(RUTA.read_text(encoding="utf-8"))


def aplicables(catalogo: dict, contexto: dict) -> list[dict]:
    resultado = []
    for criterio in catalogo["criterios"]:
        condicion = criterio.get("aplica_si")
        if condicion and not contexto.get(condicion):
            continue
        resultado.append(criterio)
    return resultado


def como_texto(criterios: list[dict], familias: dict) -> str:
    lineas = []
    for c in criterios:
        lineas.append(f"- {c['id']} ({familias[c['familia']]}, severidad base {c['severidad_base']}): {c['nombre']}. {c['descripcion']}")
    return "\n".join(lineas)


def por_id(catalogo: dict) -> dict:
    return {c["id"]: c for c in catalogo["criterios"]}
