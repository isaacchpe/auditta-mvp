import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline import analizar, anonimizar, catalogo, extraer, puntaje

SALIDA = Path(__file__).resolve().parent / "salida"
TAMANO_MAXIMO = 20 * 1024 * 1024


def identificador(nombre_archivo: str, hash_archivo: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", Path(nombre_archivo).stem).strip("-").upper()[:32]
    return f"{base or 'HC'}-{hash_archivo[:6].upper()}"


def secciones_para_interfaz(texto: str) -> list[dict]:
    bloques = []
    for parrafo in texto.split("\n\n"):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        lineas = parrafo.split("\n")
        titulo = lineas[0] if lineas[0].isupper() and len(lineas[0]) < 60 else None
        bloques.append({"titulo": titulo, "texto": "\n".join(lineas[1:]) if titulo else parrafo})
    return bloques


def preparar(ruta_pdf: Path, nombre_original: str, cargada_por: str | None) -> dict:
    inicio = time.perf_counter()
    extraccion = extraer.extraer(ruta_pdf)
    t_extraccion = time.perf_counter()
    anonimizacion = anonimizar.anonimizar(extraccion["texto"])
    t_anonimizacion = time.perf_counter()
    hid = identificador(nombre_original, extraccion["hash"])
    (SALIDA / "mapas").mkdir(parents=True, exist_ok=True)
    (SALIDA / "mapas" / f"{hid}.json").write_text(json.dumps(anonimizacion["mapa"], ensure_ascii=False, indent=2), encoding="utf-8")
    texto_bajo = extraccion["texto"].lower()
    return {
        "_id": hid,
        "archivo": nombre_original,
        "hash": extraccion["hash"],
        "paginas": extraccion["paginas"],
        "plantilla": None,
        "origen": "carga",
        "cargada_por": cargada_por,
        "secciones_reconocidas": extraccion["secciones_reconocidas"],
        "texto_anonimizado": anonimizacion["texto_anonimizado"],
        "entidades": anonimizacion["entidades"],
        "secciones": secciones_para_interfaz(anonimizacion["texto_anonimizado"]),
        "version_extractor": extraccion["version_extractor"],
        "version_reglas": anonimizacion["version_reglas"],
        "contexto": {"promocion_mantenimiento": "ruta" in texto_bajo or "promoción y mantenimiento" in texto_bajo, "egreso": "epicrisis" in extraccion["secciones_reconocidas"]},
        "estado": "pendiente_confirmacion",
        "analisis_pendiente": True,
        "tiempos_ms": {"extraccion": round((t_extraccion - inicio) * 1000), "anonimizacion": round((t_anonimizacion - t_extraccion) * 1000)},
        "fecha_carga": datetime.now(timezone.utc),
    }


def modelo_disponible() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def analizar_historia(historia: dict) -> dict:
    inicio = time.perf_counter()
    cat = catalogo.cargar()
    por_id = catalogo.por_id(cat)
    analisis = analizar.analizar(historia["texto_anonimizado"], historia.get("contexto", {}))
    hid = historia["_id"]
    hallazgos = []
    for orden, h in enumerate(analisis["hallazgos"], start=1):
        criterio = por_id[h["criterio_id"]]
        hallazgos.append({
            "_id": f"{hid}-H{orden:02d}",
            "historia_id": hid,
            "orden": orden,
            "criterio_id": h["criterio_id"],
            "criterio": criterio["nombre"],
            "familia": criterio["familia"],
            "familia_nombre": cat["familias"][criterio["familia"]],
            "severidad": h["severidad"],
            "descripcion": h["descripcion"],
            "evidencia": h["evidencia"],
            "seccion": h["seccion"],
            "sustento": criterio["sustento"],
            "recomendacion": h["recomendacion"],
            "confianza": h["confianza"],
        })
    resultado = puntaje.calcular(hallazgos, cat["familias"])
    resultado.update({
        "hallazgos": hallazgos,
        "num_hallazgos": len(hallazgos),
        "no_evaluables": analisis["no_evaluables"],
        "version_prompt": analisis["version_prompt"],
        "version_catalogo": analisis["version_catalogo"],
        "modelo": analisis["modelo"],
        "registro": analisis["registro"],
        "latencia_analisis_ms": round((time.perf_counter() - inicio) * 1000),
    })
    return resultado
