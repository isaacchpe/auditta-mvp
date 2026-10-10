PESOS = {"alta": 20, "media": 10, "baja": 4}


def calcular(hallazgos: list[dict], familias: dict) -> dict:
    por_familia: dict[str, int] = {}
    total = 0
    for h in hallazgos:
        peso = round(PESOS[h["severidad"]] * (0.6 + 0.4 * h.get("confianza", 0.5)))
        total += peso
        familia = h["criterio_id"].split("-")[0]
        por_familia[familia] = por_familia.get(familia, 0) + peso
    total = min(100, total)
    nivel = "alto" if total >= 60 else ("medio" if total >= 30 else "bajo")
    composicion = [{"familia": f, "nombre": familias.get(f, f), "puntos": p} for f, p in sorted(por_familia.items(), key=lambda x: -x[1])]
    return {"puntaje": total, "nivel": nivel, "composicion": composicion}
