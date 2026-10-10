import json
import re
import unicodedata
from pathlib import Path

VERSION_REGLAS = "1.0.0"
DATOS = Path(__file__).resolve().parent / "datos"

PATRONES = [
    ("CORREO", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("TELEFONO", re.compile(r"(?<!\d)(?:\+57\s?)?(?:3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}|60\d[\s.-]?\d{3}[\s.-]?\d{4}|\(?60\d\)?[\s.-]?\d{7})(?!\d)")),
    ("DOCUMENTO", re.compile(r"(?i)\b(?:c\.?c\.?|t\.?i\.?|c\.?e\.?|r\.?c\.?|p\.?a\.?|nuip|pasaporte|c[eé]dula(?: de ciudadan[ií]a)?|tarjeta de identidad|documento(?: de identidad)?)\s*(?:n[o°º.]*\s*)?:?\s*([\d][\d.]{5,14}\d)")),
    ("DOCUMENTO", re.compile(r"(?i)(?:identificaci[oó]n|documento|n[uú]mero de documento)\s*:\s*(?:[A-Z]{2,3}\s*)?([\d][\d.]{5,14}\d)")),
    ("REGISTRO", re.compile(r"(?i)\b(?:registro m[eé]dico|registro profesional|rethus|r\.?m\.?)\s*(?:n[o°º.]*\s*)?:?\s*((?=[\w-]*\d)[\w-]{4,20})")),
    ("HISTORIA", re.compile(r"(?i)\b(?:historia cl[ií]nica|n[uú]mero de historia|historia|hc)\s*(?:n[o°º.]*\s*)?:?\s*((?=[A-Z0-9-]*\d)[A-Z0-9-]{4,20})")),
    ("FACTURA", re.compile(r"(?i)(?:factura|admisi[oó]n|ingreso|episodio|afiliaci[oó]n|atenci[oó]n|cuenta|radicado)\s*(?:n[o°º.]*\s*)?:?\s*([A-Z]{0,4}-?\d{4,12})")),
    ("FACTURA", re.compile(r"\b([A-Z]{2,4}-\d{5,10})\b")),
    ("FECHA", re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4})\b", re.I)),
    ("DIRECCION", re.compile(r"(?i)\b(?:calle|carrera|cra\.?|cl\.?|kr\.?|diagonal|dg\.?|transversal|tv\.?|avenida|av\.?|manzana|mz\.?)\s*\d+[A-Za-z]?\s*(?:bis)?\s*(?:#|n[o°º.]*|-)?\s*\d+[A-Za-z]?\s*(?:-\s*\d+)?(?:\s*(?:apto|apartamento|casa|torre|interior|int\.?|barrio|b\.?)\s*[\w .-]{1,40})?")),
]

PALABRA = r"[A-ZÁÉÍÓÚÑ](?:[a-záéíóúñ]+|[A-ZÁÉÍÓÚÑ]+)"
NOMBRE_PROPIO = rf"{PALABRA}(?:\s(?:(?:de|del|la|DE|DEL|LA)\s)?{PALABRA}(?!\s*:)){{1,4}}"
ETIQUETAS_PERSONA = re.compile(
    rf"(?i:paciente|nombre(?:s)? y apellidos|nombre completo|nombre del (?:paciente|usuario)|usuario|acompa[ñn]ante|responsable|acudiente|madre|padre|familiar|hijo|hija|esposo|esposa|c[oó]nyuge)\s*:\s*({NOMBRE_PROPIO})"
)
ETIQUETAS_MEDICO = re.compile(
    rf"(?i:atendido por|m[eé]dico(?: tratante)?|profesional|dra?\.|doctora?|enfermera?|especialista|responsable de la atenci[oó]n|firma)\s*:?\s*((?:Dra?\.?\s)?{NOMBRE_PROPIO})"
)
ETIQUETAS_LUGAR = re.compile(
    rf"(?i:municipio|ciudad|residencia|procedencia|lugar de residencia|barrio|vereda|corregimiento)\s*(?i:de residencia)?\s*:\s*({PALABRA}(?:\s{PALABRA}(?!\s*:)){{0,3}})"
)


def _cargar_lista(nombre: str) -> set[str]:
    ruta = DATOS / nombre
    if not ruta.exists():
        return set()
    return {l.strip().lower() for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()}


NOMBRES = _cargar_lista("nombres.txt")
APELLIDOS = _cargar_lista("apellidos.txt")
LUGARES = _cargar_lista("lugares.txt")


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


VOCALES = {"a": "[aá]", "e": "[eé]", "i": "[ií]", "o": "[oó]", "u": "[uúü]", "n": "[nñ]"}


def _con_tildes_opcionales(texto: str) -> str:
    return "".join(VOCALES.get(c, re.escape(c)) if c != " " else r"\s+" for c in texto)


def _es_nombre_persona(candidato: str) -> bool:
    partes = [_sin_tildes(p) for p in candidato.split()]
    partes = [p for p in partes if p not in ("de", "del", "la", "los", "las", "dr", "dra", "dr.", "dra.")]
    if len(partes) < 2:
        return False
    conocidos = sum(1 for p in partes if p in NOMBRES or p in APELLIDOS)
    return conocidos >= max(1, len(partes) - 1)


class Anonimizador:
    def __init__(self) -> None:
        self.mapa: dict[str, str] = {}
        self.contadores: dict[str, int] = {}
        self.entidades: list[dict] = []

    def _token(self, categoria: str, valor: str) -> str:
        clave = f"{categoria}:{_sin_tildes(valor.strip())}"
        if clave not in self.mapa:
            self.contadores[categoria] = self.contadores.get(categoria, 0) + 1
            self.mapa[clave] = f"[{categoria}_{self.contadores[categoria]}]"
        return self.mapa[clave]

    def _sustituir_valor(self, texto: str, categoria: str, valor: str) -> str:
        valor = valor.strip()
        if len(valor) < 3:
            return texto
        token = self._token(categoria, valor)
        patron = re.compile(re.escape(valor), re.I)
        texto, n = patron.subn(token, texto)
        if n:
            self.entidades.append({"categoria": categoria, "token": token, "ocurrencias": n})
        return texto

    def _por_etiquetas(self, texto: str) -> str:
        for patron, categoria in ((ETIQUETAS_MEDICO, "MEDICO"), (ETIQUETAS_PERSONA, "PACIENTE")):
            for coincidencia in list(patron.finditer(texto)):
                valor = coincidencia.group(1)
                if categoria == "MEDICO":
                    valor = re.sub(r"(?i)^dra?\.?\s+", "", valor)
                if _es_nombre_persona(valor) or categoria == "PACIENTE":
                    texto = self._sustituir_valor(texto, categoria, valor)
        for coincidencia in list(ETIQUETAS_LUGAR.finditer(texto)):
            valor = coincidencia.group(1)
            if _sin_tildes(valor) in LUGARES or len(valor.split()) <= 3:
                texto = self._sustituir_valor(texto, "LUGAR", valor)
        return texto

    def _por_patrones(self, texto: str) -> str:
        for categoria, patron in PATRONES:
            for coincidencia in list(patron.finditer(texto)):
                valor = coincidencia.group(1) if coincidencia.groups() else coincidencia.group(0)
                texto = self._sustituir_valor(texto, categoria, valor)
        return texto

    def _por_gazetteer(self, texto: str) -> str:
        candidatos = re.finditer(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+(?:de\s+|del\s+|la\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){1,3})\b", texto)
        for coincidencia in list(candidatos):
            valor = coincidencia.group(1)
            if valor.startswith("[") or re.match(r"\[[A-Z]+_\d+\]", valor):
                continue
            partes = [_sin_tildes(p) for p in valor.split() if _sin_tildes(p) not in ("de", "del", "la")]
            if partes and all(p in NOMBRES or p in APELLIDOS for p in partes) and any(p in NOMBRES for p in partes):
                texto = self._sustituir_valor(texto, "PACIENTE", valor)
        for lugar in sorted(LUGARES, key=len, reverse=True):
            if len(lugar) < 5:
                continue
            patron = re.compile(r"\b" + _con_tildes_opcionales(lugar) + r"\b", re.I)
            if patron.search(texto):
                token = self._token("LUGAR", lugar)
                texto, n = patron.subn(token, texto)
                self.entidades.append({"categoria": "LUGAR", "token": token, "ocurrencias": n})
        return texto

    def _edades_extremas(self, texto: str) -> str:
        return re.sub(r"(?i)\b(9\d|1[0-2]\d)\s*años\b", "[EDAD_MAYOR_90] años", texto)

    def procesar(self, texto: str) -> dict:
        texto = self._por_etiquetas(texto)
        texto = self._por_patrones(texto)
        texto = self._por_gazetteer(texto)
        texto = self._edades_extremas(texto)
        resumen: dict[str, dict] = {}
        for entidad in self.entidades:
            r = resumen.setdefault(entidad["token"], {"categoria": entidad["categoria"], "token": entidad["token"], "ocurrencias": 0})
            r["ocurrencias"] += entidad["ocurrencias"]
        return {
            "texto_anonimizado": texto,
            "entidades": sorted(resumen.values(), key=lambda e: (e["categoria"], e["token"])),
            "mapa": {v: k.split(":", 1)[1] for k, v in self.mapa.items()},
            "version_reglas": VERSION_REGLAS,
        }


def anonimizar(texto: str) -> dict:
    return Anonimizador().procesar(texto)


def verificar_fugas(texto_anonimizado: str, valores: list[str]) -> list[str]:
    fugas = []
    plano = _sin_tildes(texto_anonimizado)
    for valor in valores:
        v = _sin_tildes(valor.strip())
        if len(v) >= 3 and v in plano:
            fugas.append(valor)
    return fugas


if __name__ == "__main__":
    import sys

    resultado = anonimizar(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps({k: v for k, v in resultado.items() if k != "mapa"}, ensure_ascii=False, indent=2))
