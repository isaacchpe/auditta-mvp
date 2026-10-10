import hashlib
import re
from pathlib import Path

import fitz

VERSION_EXTRACTOR = "1.0.0"
MAX_PAGINAS = 60

ENCABEZADOS = [
    ("identificacion", r"^(datos de identificaci[oó]n|identificaci[oó]n del (usuario|paciente)|datos del paciente)"),
    ("motivo_consulta", r"^motivo de (la )?consulta"),
    ("enfermedad_actual", r"^enfermedad actual"),
    ("antecedentes", r"^antecedentes"),
    ("revision_sistemas", r"^revisi[oó]n por sistemas"),
    ("examen_fisico", r"^examen f[ií]sico"),
    ("analisis", r"^(an[aá]lisis|impresi[oó]n diagn[oó]stica)"),
    ("diagnosticos", r"^diagn[oó]sticos?"),
    ("plan", r"^(plan( de manejo)?|conducta|tratamiento)"),
    ("evolucion", r"^(evoluci[oó]n|notas? de evoluci[oó]n)"),
    ("ordenes", r"^([oó]rdenes|solicitudes)"),
    ("procedimientos", r"^procedimientos"),
    ("notas_enfermeria", r"^notas? de enfermer[ií]a"),
    ("epicrisis", r"^epicrisis"),
    ("egreso", r"^(egreso|resumen de egreso)"),
    ("consentimiento", r"^consentimiento informado"),
    ("intervenciones_ruta", r"^(intervenciones|actividades) de la ruta"),
    ("profesional", r"^(profesional|atendido por|responsable de la atenci[oó]n)"),
]


class DocumentoSinTexto(Exception):
    pass


def hash_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def normalizar(texto: str) -> str:
    texto = texto.replace("­", "")
    texto = re.sub(r"-\n(?=[a-záéíóúñ])", "", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def clasificar_linea(linea: str) -> str | None:
    limpia = linea.strip().rstrip(":").lower()
    if len(limpia) > 60:
        return None
    for nombre, patron in ENCABEZADOS:
        if re.match(patron, limpia):
            return nombre
    return None


def extraer(ruta: Path) -> dict:
    documento = fitz.open(ruta)
    if documento.page_count > MAX_PAGINAS:
        raise ValueError(f"El documento supera las {MAX_PAGINAS} páginas")
    paginas = []
    total_caracteres = 0
    for numero, pagina in enumerate(documento, start=1):
        bloques = []
        for x0, y0, x1, y1, texto, *_ in pagina.get_text("blocks"):
            texto = texto.strip()
            if texto:
                bloques.append({"pagina": numero, "bbox": [round(x0), round(y0), round(x1), round(y1)], "texto": texto})
                total_caracteres += len(texto)
        paginas.append(bloques)
    documento.close()
    if total_caracteres < 200:
        raise DocumentoSinTexto("El PDF no tiene capa de texto suficiente")
    secciones = []
    actual = {"nombre": "encabezado", "pagina": 1, "lineas": []}
    for bloques in paginas:
        for bloque in bloques:
            for linea in bloque["texto"].split("\n"):
                nombre = clasificar_linea(linea)
                if nombre:
                    if actual["lineas"]:
                        secciones.append(actual)
                    actual = {"nombre": nombre, "pagina": bloque["pagina"], "lineas": [linea.strip()]}
                else:
                    actual["lineas"].append(linea)
    if actual["lineas"]:
        secciones.append(actual)
    for seccion in secciones:
        seccion["texto"] = normalizar("\n".join(seccion.pop("lineas")))
    texto = "\n\n".join(s["texto"] for s in secciones)
    reconocidas = {s["nombre"] for s in secciones if s["nombre"] != "encabezado"}
    return {
        "hash": hash_archivo(ruta),
        "nombre_archivo": ruta.name,
        "paginas": len(paginas),
        "secciones": secciones,
        "secciones_reconocidas": sorted(reconocidas),
        "texto": texto,
        "version_extractor": VERSION_EXTRACTOR,
    }
