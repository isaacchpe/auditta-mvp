import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from pipeline import analizar, anonimizar, catalogo, extraer, metricas, puntaje

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
CORPUS = RAIZ / "corpus"
SALIDA = Path(__file__).resolve().parent / "salida"
EXTRACTO = 2800


def secciones_para_interfaz(texto: str, hallazgos: list[dict]) -> list[dict]:
    bloques = []
    for parrafo in texto.split("\n\n"):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        lineas = parrafo.split("\n")
        titulo = lineas[0] if lineas[0].isupper() and len(lineas[0]) < 60 else None
        cuerpo = "\n".join(lineas[1:]) if titulo else parrafo
        bloques.append({"titulo": titulo, "texto": cuerpo})
    return bloques


def procesar(ruta_pdf: Path, verdad: dict | None, con_modelo: bool) -> dict:
    inicio = time.perf_counter()
    cat = catalogo.cargar()
    por_id = catalogo.por_id(cat)
    extraccion = extraer.extraer(ruta_pdf)
    t_extraccion = time.perf_counter()
    anonimizacion = anonimizar.anonimizar(extraccion["texto"])
    t_anonimizacion = time.perf_counter()
    historia_id = verdad["id"] if verdad else ruta_pdf.stem
    contexto = verdad["contexto"] if verdad else {"promocion_mantenimiento": "ruta" in extraccion["texto"].lower(), "egreso": "epicrisis" in extraccion["secciones_reconocidas"]}
    resultado = {
        "_id": historia_id,
        "archivo": ruta_pdf.name,
        "hash": extraccion["hash"],
        "paginas": extraccion["paginas"],
        "plantilla": verdad.get("plantilla") if verdad else None,
        "secciones_reconocidas": extraccion["secciones_reconocidas"],
        "texto_anonimizado": anonimizacion["texto_anonimizado"],
        "entidades": anonimizacion["entidades"],
        "version_extractor": extraccion["version_extractor"],
        "version_reglas": anonimizacion["version_reglas"],
        "contexto": contexto,
        "estado": "pendiente_confirmacion",
        "tiempos_ms": {"extraccion": round((t_extraccion - inicio) * 1000), "anonimizacion": round((t_anonimizacion - t_extraccion) * 1000)},
    }
    (SALIDA / "mapas").mkdir(parents=True, exist_ok=True)
    (SALIDA / "mapas" / f"{historia_id}.json").write_text(json.dumps(anonimizacion["mapa"], ensure_ascii=False, indent=2), encoding="utf-8")
    medicion = {"anonimizacion": metricas.recall_anonimizacion(verdad, anonimizacion["texto_anonimizado"]) if verdad else None}
    if con_modelo:
        analisis = analizar.analizar(anonimizacion["texto_anonimizado"], contexto)
        t_analisis = time.perf_counter()
        resultado["tiempos_ms"]["analisis"] = round((t_analisis - t_anonimizacion) * 1000)
        hallazgos = []
        for orden, h in enumerate(analisis["hallazgos"], start=1):
            criterio = por_id[h["criterio_id"]]
            hallazgos.append({
                "_id": f"{historia_id}-H{orden:02d}",
                "historia_id": historia_id,
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
                "estado_revision": "pendiente",
            })
        resultado.update(puntaje.calcular(hallazgos, cat["familias"]))
        resultado["hallazgos_lista"] = hallazgos
        resultado["num_hallazgos"] = len(hallazgos)
        resultado["no_evaluables"] = analisis["no_evaluables"]
        resultado["version_prompt"] = analisis["version_prompt"]
        resultado["version_catalogo"] = analisis["version_catalogo"]
        resultado["modelo"] = analisis["modelo"]
        medicion["analisis"] = analisis
        medicion["concordancia"] = metricas.concordancia_defectos(verdad, hallazgos) if verdad else None
        (SALIDA / "crudo").mkdir(parents=True, exist_ok=True)
        (SALIDA / "crudo" / f"{historia_id}.json").write_text(json.dumps(analisis, ensure_ascii=False, indent=2), encoding="utf-8")
    resultado["secciones"] = secciones_para_interfaz(anonimizacion["texto_anonimizado"], resultado.get("hallazgos_lista", []))
    resultado["tiempos_ms"]["total"] = round((time.perf_counter() - inicio) * 1000)
    medicion["latencia_total_ms"] = resultado["tiempos_ms"]["total"]
    (SALIDA / "historias").mkdir(parents=True, exist_ok=True)
    (SALIDA / "historias" / f"{historia_id}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return medicion


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-modelo", action="store_true")
    parser.add_argument("--solo", nargs="*", default=[])
    parser.add_argument("--limite", type=int, default=0)
    argumentos = parser.parse_args()
    verdades = {v.stem: json.loads(v.read_text(encoding="utf-8")) for v in (CORPUS / "verdad").glob("*.json")}
    rutas = sorted((CORPUS / "pdf").glob("*.pdf"))
    if argumentos.solo:
        rutas = [r for r in rutas if r.stem in argumentos.solo]
    if argumentos.limite:
        rutas = rutas[: argumentos.limite]
    mediciones = []
    for ruta in rutas:
        try:
            medicion = procesar(ruta, verdades.get(ruta.stem), not argumentos.sin_modelo)
            mediciones.append(medicion)
            fugas = medicion["anonimizacion"]["fugas"] if medicion["anonimizacion"] else "n/a"
            print(f"{ruta.stem}: ok, {medicion['latencia_total_ms']} ms, fugas {fugas}")
        except Exception as e:
            print(f"{ruta.stem}: error {type(e).__name__}: {e}")
    resumen = metricas.consolidar(mediciones)
    resumen["fecha"] = datetime.now(timezone.utc).isoformat()
    resumen["version_reglas"] = anonimizar.VERSION_REGLAS
    resumen["version_prompt"] = analizar.VERSION_PROMPT
    resumen["version_catalogo"] = catalogo.cargar()["version"]
    metricas.guardar(SALIDA / "metricas_pipeline.json", resumen)
    metricas.guardar(SALIDA / "mediciones_detalle.json", mediciones)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
