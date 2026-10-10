import json
import os
import re
import time
import unicodedata

import httpx

from pipeline import catalogo as cat

VERSION_PROMPT = "1.2.0"
URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
MODELO = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_INTENTOS = 3
SEVERIDADES = ("alta", "media", "baja")

INSTRUCCIONES = """Eres un auditor médico de cuentas en Colombia. Recibes el texto de una historia clínica ya anonimizado: los datos personales aparecen como tokens entre corchetes, por ejemplo [PACIENTE_1] o [FECHA_2]. Trata cada token como un valor presente y válido.

Tu tarea es contrastar el contenido clínico contra el catálogo de criterios que se te entrega y reportar únicamente los incumplimientos que puedas sustentar con una cita literal del texto.

Reglas:
1. Usa solo los criterios del catálogo, con su identificador exacto, y como máximo un hallazgo por criterio.
2. Cada hallazgo debe incluir una cita literal y exacta del texto fuente en el campo "evidencia". Si no existe un fragmento literal que lo sustente, no reportes el hallazgo.
3. No inventes normas ni artículos: el sustento normativo lo aporta el sistema a partir del catálogo.
4. Reporta solo incumplimientos claros que un auditor de cuentas médicas sostendría ante el prestador. Ante la duda, no reportes. Máximo 6 hallazgos, ordenados de mayor a menor severidad.
5. "confianza" es un número entre 0 y 1 que expresa qué tan seguro estás del incumplimiento.
6. Criterios de interpretación:
   - Las abreviaturas clínicas de uso estándar (TA, FC, FR, T, SatO2, IMC, CC, EPS, G2P1, CIE-10, mg, mL, lpm, rpm) no son un incumplimiento de legibilidad.
   - Un medicamento o procedimiento que figura en el plan de manejo o en las órdenes cuenta como ordenado; SOP-02 aplica solo cuando algo se administró o realizó sin figurar en el plan ni en las órdenes.
   - SOP-01 (consentimiento informado) aplica solo a procedimientos quirúrgicos, invasivos o con anestesia o sedación; no aplica a electrocardiogramas, laboratorios, imágenes ni medicamentos.
   - COH-03 no aplica a dosis únicas ni a esquemas intrahospitalarios con dosis, vía y frecuencia explícitas.
   - COH-04 aplica solo a contradicciones reales entre sexo o edad y la atención registrada, como un procedimiento ginecológico en un hombre o un control prenatal en un hombre; los diagnósticos comunes no contradicen el sexo.
   - OPO-01 aplica solo cuando una anotación carece de fecha y hora; un token [FECHA_n] cuenta como fecha presente.
   - IDP-01 aplica solo cuando no hay nombre del profesional; la firma manuscrita no se evalúa en el texto.
   - PERT-03 aplica solo a interconsultas o remisiones explícitas, no a controles ni a citas de seguimiento.
   - Un criterio con token presente, por ejemplo [DOCUMENTO_1] o [MEDICO_1], se considera cumplido en ese campo.
   - COMP-03 aplica cuando la historia no tiene una sección de antecedentes personales, familiares y alérgicos, aunque la enfermedad actual mencione alguno.
   - IDP-02 aplica cuando no aparece el registro médico del profesional, es decir, ni la palabra registro con su número ni un token [REGISTRO_n].
   - SOP-03 aplica cuando se ordenaron exámenes o imágenes y la historia no registra su resultado ni su interpretación, salvo que indique expresamente que están pendientes.
   - PERT-01 se refiere a procedimientos terapéuticos o servicios prestados sin justificación clínica; PERT-02 se refiere a laboratorios e imágenes ordenados sin indicación.
   - COH-03 aplica solo si falta la dosis, la vía o la frecuencia; la duración no es exigible en esquemas intrahospitalarios ni en dosis únicas.
7. Responde únicamente con un objeto JSON válido, sin texto adicional ni marcas de código, con esta estructura exacta:
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
