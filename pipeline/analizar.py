import json
import os
import re
import time
import unicodedata

import httpx

from pipeline import catalogo as cat

VERSION_PROMPT = "1.0.0"
URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
MODELO = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_INTENTOS = 3
SEVERIDADES = ("alta", "media", "baja")

INSTRUCCIONES = """Eres un auditor médico de cuentas en Colombia. Recibes el texto de una historia clínica ya anonimizado: los datos personales aparecen como tokens entre corchetes, por ejemplo [PACIENTE_1] o [FECHA_2]. Trata cada token como un valor presente y válido.

Tu tarea es contrastar el contenido clínico contra el catálogo de criterios que se te entrega y reportar únicamente los incumplimientos que puedas sustentar con una cita literal del texto.

Reglas:
1. Usa solo los criterios del catálogo, con su identificador exacto.
2. Cada hallazgo debe incluir una cita literal y exacta del texto fuente en el campo "evidencia". Si no existe un fragmento literal que lo sustente, no reportes el hallazgo.
3. No inventes normas ni artículos: el sustento normativo lo aporta el sistema a partir del catálogo.
4. Reporta como máximo 8 hallazgos, ordenados de mayor a menor severidad.
5. "confianza" es un número entre 0 y 1 que expresa qué tan seguro estás del incumplimiento.
6. Responde únicamente con un objeto JSON válido, sin texto adicional ni marcas de código, con esta estructura exacta:
{"hallazgos": [{"criterio_id": "COMP-05", "severidad": "alta", "descripcion": "...", "evidencia": "...", "seccion": "...", "recomendacion": "...", "confianza": 0.9}], "no_evaluables": ["..."]}
Si no encuentras incumplimientos, responde {"hallazgos": [], "no_evaluables": []}."""


class RespuestaInvalida(Exception):
    pass


def _plano(texto: str) -> str:
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    texto = texto.lower().replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", texto).strip()


def evidencia_localizable(evidencia: str, texto: str) -> bool:
    e = _plano(evidencia).strip('"\' .')
    return len(e) >= 8 and e in _plano(texto)


def construir_mensajes(texto_anonimizado: str, criterios: list[dict], familias: dict) -> list[dict]:
    usuario = f"CATÁLOGO DE CRITERIOS (versión del sistema):\n{cat.como_texto(criterios, familias)}\n\nHISTORIA CLÍNICA ANONIMIZADA:\n{texto_anonimizado}"
    return [{"role": "system", "content": INSTRUCCIONES}, {"role": "user", "content": usuario}]


def _extraer_json(contenido: str) -> dict:
    contenido = contenido.strip()
    contenido = re.sub(r"^```(?:json)?\s*|\s*```$", "", contenido)
    inicio = contenido.find("{")
    fin = contenido.rfind("}")
    if inicio < 0 or fin < 0:
        raise RespuestaInvalida("sin objeto JSON")
    try:
        return json.loads(contenido[inicio:fin + 1])
    except json.JSONDecodeError as e:
        raise RespuestaInvalida(f"JSON inválido: {e}")


def validar_esquema(datos: dict, ids_validos: set[str]) -> list[dict]:
    if not isinstance(datos, dict) or not isinstance(datos.get("hallazgos"), list):
        raise RespuestaInvalida("falta la lista hallazgos")
    limpios = []
    for h in datos["hallazgos"]:
        if not isinstance(h, dict):
            raise RespuestaInvalida("hallazgo no es objeto")
        for campo in ("criterio_id", "severidad", "descripcion", "evidencia"):
            if not isinstance(h.get(campo), str) or not h[campo].strip():
                raise RespuestaInvalida(f"campo {campo} ausente")
        if h["criterio_id"] not in ids_validos:
            raise RespuestaInvalida(f"criterio desconocido {h['criterio_id']}")
        if h["severidad"] not in SEVERIDADES:
            raise RespuestaInvalida(f"severidad inválida {h['severidad']}")
        try:
            confianza = float(h.get("confianza", 0.5))
        except (TypeError, ValueError):
            raise RespuestaInvalida("confianza no numérica")
        limpios.append({
            "criterio_id": h["criterio_id"],
            "severidad": h["severidad"],
            "descripcion": h["descripcion"].strip(),
            "evidencia": h["evidencia"].strip(),
            "seccion": str(h.get("seccion", "")).strip(),
            "recomendacion": str(h.get("recomendacion", "")).strip(),
            "confianza": max(0.0, min(1.0, confianza)),
        })
    return limpios


def llamar_modelo(mensajes: list[dict], clave: str) -> tuple[str, dict]:
    cuerpo = {"model": MODELO, "messages": mensajes, "temperature": 0.1, "max_tokens": 2500, "response_format": {"type": "json_object"}}
    with httpx.Client(timeout=120) as cliente:
        respuesta = cliente.post(URL, headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"}, json=cuerpo)
    respuesta.raise_for_status()
    datos = respuesta.json()
    return datos["choices"][0]["message"]["content"], datos.get("usage", {})


def analizar(texto_anonimizado: str, contexto: dict, clave: str | None = None) -> dict:
    clave = clave or os.environ.get("DEEPSEEK_API_KEY", "")
    if not clave:
        raise RuntimeError("Falta DEEPSEEK_API_KEY")
    catalogo = cat.cargar()
    criterios = cat.aplicables(catalogo, contexto)
    ids_validos = {c["id"] for c in criterios}
    mensajes = construir_mensajes(texto_anonimizado, criterios, catalogo["familias"])
    registro = {"intentos": 0, "valido_primer_intento": False, "tokens_entrada": 0, "tokens_salida": 0, "latencia_ms": 0, "errores": []}
    inicio = time.perf_counter()
    hallazgos = []
    no_evaluables = []
    for intento in range(1, MAX_INTENTOS + 1):
        registro["intentos"] = intento
        try:
            contenido, uso = llamar_modelo(mensajes, clave)
            registro["tokens_entrada"] += int(uso.get("prompt_tokens", 0))
            registro["tokens_salida"] += int(uso.get("completion_tokens", 0))
            datos = _extraer_json(contenido)
            hallazgos = validar_esquema(datos, ids_validos)
            no_evaluables = [str(x) for x in datos.get("no_evaluables", []) if isinstance(x, str)]
            registro["valido_primer_intento"] = intento == 1
            break
        except RespuestaInvalida as e:
            registro["errores"].append(str(e))
            mensajes = mensajes[:2] + [{"role": "user", "content": f"La respuesta anterior no cumplió el formato ({e}). Responde de nuevo solo con el objeto JSON exigido."}]
            time.sleep(2 ** intento)
        except httpx.HTTPError as e:
            registro["errores"].append(f"http: {e}")
            time.sleep(2 ** intento)
    else:
        raise RuntimeError(f"Sin respuesta válida tras {MAX_INTENTOS} intentos: {registro['errores']}")
    registro["latencia_ms"] = round((time.perf_counter() - inicio) * 1000)
    verificados = []
    descartados = []
    for h in hallazgos:
        if evidencia_localizable(h["evidencia"], texto_anonimizado):
            verificados.append(h)
        else:
            descartados.append(h)
    return {
        "hallazgos": verificados,
        "descartados_sin_evidencia": descartados,
        "no_evaluables": no_evaluables,
        "version_prompt": VERSION_PROMPT,
        "version_catalogo": catalogo["version"],
        "modelo": MODELO,
        "registro": registro,
    }
