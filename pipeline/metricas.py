import json
from pathlib import Path

from pipeline.anonimizar import verificar_fugas


def recall_anonimizacion(verdad: dict, texto_anonimizado: str) -> dict:
    valores = [i["valor"] for i in verdad["identificadores"]]
    fugas = verificar_fugas(texto_anonimizado, valores)
    por_categoria: dict[str, dict] = {}
    for identificador in verdad["identificadores"]:
        c = por_categoria.setdefault(identificador["categoria"], {"total": 0, "detectados": 0})
        c["total"] += 1
        c["detectados"] += identificador["valor"] not in fugas
    return {"total": len(valores), "detectados": len(valores) - len(fugas), "fugas": fugas, "por_categoria": por_categoria}


def concordancia_defectos(verdad: dict, hallazgos: list[dict]) -> dict:
    esperados = set(verdad.get("defectos", []))
    detectados = {h["criterio_id"] for h in hallazgos}
    return {
        "esperados": sorted(esperados),
        "detectados": sorted(detectados),
        "verdaderos_positivos": sorted(esperados & detectados),
        "no_detectados": sorted(esperados - detectados),
        "adicionales": sorted(detectados - esperados),
    }


def consolidar(resultados: list[dict]) -> dict:
    total_ids = sum(r["anonimizacion"]["total"] for r in resultados)
    detectados = sum(r["anonimizacion"]["detectados"] for r in resultados)
    con_fuga = sum(1 for r in resultados if r["anonimizacion"]["fugas"])
    por_categoria: dict[str, dict] = {}
    for r in resultados:
        for categoria, c in r["anonimizacion"]["por_categoria"].items():
            acumulado = por_categoria.setdefault(categoria, {"total": 0, "detectados": 0})
            acumulado["total"] += c["total"]
            acumulado["detectados"] += c["detectados"]
    analizados = [r for r in resultados if r.get("analisis")]
    validos_primer_intento = sum(1 for r in analizados if r["analisis"]["registro"]["valido_primer_intento"])
    hallazgos_total = sum(len(r["analisis"]["hallazgos"]) + len(r["analisis"]["descartados_sin_evidencia"]) for r in analizados)
    con_evidencia = sum(len(r["analisis"]["hallazgos"]) for r in analizados)
    latencias = [r["latencia_total_ms"] for r in analizados]
    tokens_entrada = sum(r["analisis"]["registro"]["tokens_entrada"] for r in analizados)
    tokens_salida = sum(r["analisis"]["registro"]["tokens_salida"] for r in analizados)
    esperados = sum(len(r["concordancia"]["esperados"]) for r in analizados)
    verdaderos = sum(len(r["concordancia"]["verdaderos_positivos"]) for r in analizados)
    return {
        "historias": len(resultados),
        "historias_analizadas": len(analizados),
        "recall_anonimizacion": round(detectados / total_ids, 4) if total_ids else None,
        "identificadores": total_ids,
        "documentos_con_fuga": con_fuga,
        "recall_por_categoria": {k: round(v["detectados"] / v["total"], 4) for k, v in por_categoria.items()},
        "json_valido_primer_intento": round(validos_primer_intento / len(analizados), 4) if analizados else None,
        "hallazgos_con_evidencia": round(con_evidencia / hallazgos_total, 4) if hallazgos_total else None,
        "hallazgos_generados": hallazgos_total,
        "hallazgos_verificados": con_evidencia,
        "sensibilidad_defectos_inducidos": round(verdaderos / esperados, 4) if esperados else None,
        "latencia_media_ms": round(sum(latencias) / len(latencias)) if latencias else None,
        "latencia_maxima_ms": max(latencias) if latencias else None,
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
    }


def guardar(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
