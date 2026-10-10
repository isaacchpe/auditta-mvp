import argparse
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import fitz

AQUI = Path(__file__).resolve().parent
DATOS = AQUI.parent / "pipeline" / "datos"
SALIDA_PDF = AQUI / "pdf"
SALIDA_VERDAD = AQUI / "verdad"

NOMBRES = [l.strip().title() for l in (DATOS / "nombres.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
APELLIDOS = [l.strip().title() for l in (DATOS / "apellidos.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
MUNICIPIOS = ["Montería", "Cereté", "Lorica", "Sahagún", "Planeta Rica", "Montelíbano", "Sincelejo", "Corozal", "Magangué", "Valledupar"]
BARRIOS = ["La Castellana", "Buenavista", "El Recreo", "La Pradera", "Los Ángeles", "Mocarí", "Villa Olímpica", "El Prado", "San José", "Santa Fe"]
VIAS = ["Calle", "Carrera", "Diagonal", "Transversal", "Avenida"]
ASEGURADORAS = ["Nueva EPS", "Mutual Ser", "Coosalud", "Salud Total", "Sanitas"]
ESPECIALIDADES = ["Medicina general", "Medicina de urgencias", "Medicina interna", "Pediatría", "Ginecología"]
INSTITUCIONES = {
    "A": ("IPS Centro Médico Sinú Sintético", "230010999901"),
    "B": ("Clínica Sintética del Caribe", "230010999902"),
    "C": ("ESE Hospital Sintético San Jerónimo", "230010999903"),
    "D": ("Centro de Salud Sintético de Mocarí", "230010999904"),
}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

CASOS = {
    "A": [
        {"sexo": "femenino", "edad": 46, "motivo": "«Dolor de cabeza frecuente desde hace un mes».",
         "enfermedad": "Cefalea pulsátil hemicraneana derecha, de predominio vespertino, 3 a 4 episodios por semana, intensidad 7/10, con fotofobia y náuseas. Sin fiebre ni déficit neurológico. Empeora con el estrés laboral.",
         "antecedentes": "Personales: hipertensión arterial en manejo con losartán. Familiares: madre con migraña. Alérgicos: niega.",
         "examen": "TA 138/88 mmHg, FC 76 lpm, FR 16 rpm, T 36,6 °C, peso 68 kg. Pupilas isocóricas normorreactivas, fondo de ojo sin papiledema, examen neurológico sin déficit.",
         "analisis": "Cuadro compatible con migraña sin aura, en paciente hipertensa controlada.",
         "diagnosticos": [("G430", "Migraña sin aura"), ("I10X", "Hipertensión esencial")],
         "plan": ["Naproxeno 500 mg vía oral cada 12 horas por 5 días.", "Metoclopramida 10 mg vía oral cada 8 horas si hay náuseas, por 3 días.", "Continuar losartán 50 mg cada 12 horas.", "Recomendaciones de higiene del sueño y diario de cefalea.", "Control en 30 días."],
         "ordenes": [("laboratorio", "Perfil lipídico y glicemia en ayunas", "Control de riesgo cardiovascular en paciente hipertensa.")],
         "resultados": [("Perfil lipídico y glicemia", "colesterol total 212 mg/dL, LDL 134 mg/dL, glicemia 96 mg/dL", "Dislipidemia leve; se refuerza dieta y se revalora en el control.")]},
        {"sexo": "masculino", "edad": 58, "motivo": "«Vengo a control de la diabetes».",
         "enfermedad": "Paciente con diabetes mellitus tipo 2 diagnosticada hace 6 años, en manejo con metformina. Refiere adherencia parcial y polidipsia leve en las últimas dos semanas. Niega hipoglucemias.",
         "antecedentes": "Personales: diabetes mellitus tipo 2, dislipidemia. Familiares: padre con diabetes. Alérgicos: penicilina.",
         "examen": "TA 130/84 mmHg, FC 80 lpm, FR 18 rpm, T 36,5 °C, peso 84 kg, IMC 29,4. Pies sin lesiones, pulsos pedios presentes, sensibilidad conservada con monofilamento.",
         "analisis": "Diabetes mellitus tipo 2 con control metabólico por evaluar; sobrepeso.",
         "diagnosticos": [("E119", "Diabetes mellitus tipo 2 sin complicaciones"), ("E780", "Hipercolesterolemia pura")],
         "plan": ["Metformina 850 mg vía oral cada 12 horas con las comidas, por 90 días.", "Atorvastatina 20 mg vía oral cada noche por 90 días.", "Plan de alimentación y actividad física 150 minutos por semana.", "Control en 90 días con resultados."],
         "ordenes": [("laboratorio", "Hemoglobina glicosilada, creatinina y microalbuminuria", "Seguimiento del control metabólico y tamizaje de nefropatía diabética.")],
         "resultados": [("Hemoglobina glicosilada", "7,9 %", "Control subóptimo; se ajusta dosis de metformina.")]},
        {"sexo": "femenino", "edad": 32, "motivo": "«Dolor al orinar y ganas frecuentes de ir al baño».",
         "enfermedad": "Disuria, polaquiuria y urgencia miccional de dos días de evolución, sin fiebre ni dolor lumbar. Niega flujo vaginal. Último periodo menstrual hace 10 días.",
         "antecedentes": "Personales: infección urinaria hace un año. Familiares: sin relevancia. Alérgicos: niega.",
         "examen": "TA 110/70 mmHg, FC 82 lpm, FR 16 rpm, T 37,1 °C. Abdomen blando, dolor leve suprapúbico, puño percusión lumbar negativa.",
         "analisis": "Infección urinaria baja no complicada.",
         "diagnosticos": [("N390", "Infección de vías urinarias, sitio no especificado")],
         "plan": ["Nitrofurantoína 100 mg vía oral cada 6 horas por 5 días.", "Hidratación abundante.", "Signos de alarma: fiebre, dolor lumbar o vómito.", "Control si no mejora en 72 horas."],
         "ordenes": [("laboratorio", "Uroanálisis y urocultivo", "Confirmación del diagnóstico y orientación del antibiótico.")],
         "resultados": [("Uroanálisis", "leucocitos 25 por campo, nitritos positivos", "Compatible con infección urinaria.")]},
    ],
    "B": [
        {"sexo": "masculino", "edad": 54, "motivo": "«Dolor en el pecho desde hace dos horas».",
         "enfermedad": "Dolor torácico opresivo de dos horas de evolución, irradiado al brazo izquierdo, asociado a sudoración. Niega episodios previos.",
         "antecedentes": "Personales: hipertensión arterial en manejo con losartán 50 mg cada 12 horas. Familiares: hermano con infarto a los 60 años. Alérgicos: niega.",
         "examen": "TA 150/95 mmHg, FC 98 lpm, FR 20 rpm, SatO2 94 % al aire ambiente, T 36,8 °C. Ruidos cardíacos rítmicos sin soplos, pulmones bien ventilados.",
         "analisis": "Síndrome coronario agudo a descartar; se inicia protocolo de dolor torácico.",
         "diagnosticos": [("I200", "Angina inestable"), ("I10X", "Hipertensión esencial")],
         "plan": ["Ácido acetilsalicílico 300 mg vía oral dosis única.", "Oxígeno por cánula nasal a 2 litros por minuto.", "Monitoreo continuo y control de signos vitales cada hora.", "Valoración por medicina interna."],
         "ordenes": [("procedimiento", "Electrocardiograma de 12 derivaciones", "Dolor torácico con sospecha de síndrome coronario agudo."), ("laboratorio", "Troponina I seriada", "Descartar necrosis miocárdica.")],
         "resultados": [("Electrocardiograma", "ritmo sinusal, infradesnivel del ST en DII, DIII y aVF", "Isquemia de cara inferior."), ("Troponina I", "0,08 ng/mL", "Elevada; se confirma síndrome coronario agudo.")],
         "interconsulta": ("Medicina interna", "Síndrome coronario agudo con troponina elevada para definir manejo.")},
        {"sexo": "femenino", "edad": 7, "motivo": "«La niña tiene fiebre y le cuesta respirar».",
         "enfermedad": "Fiebre de 39 °C de tres días, tos productiva y dificultad respiratoria progresiva desde hace 12 horas. Vacunación completa para la edad según la madre.",
         "antecedentes": "Personales: asma leve intermitente. Familiares: sin relevancia. Alérgicos: niega.",
         "examen": "FC 128 lpm, FR 38 rpm, T 38,9 °C, SatO2 91 % al aire ambiente, peso 23 kg. Tirajes subcostales, crépitos en base pulmonar derecha.",
         "analisis": "Neumonía adquirida en la comunidad con dificultad respiratoria.",
         "diagnosticos": [("J189", "Neumonía, no especificada"), ("J459", "Asma, no especificada")], "especialidad": "Pediatría",
         "plan": ["Oxígeno por cánula nasal a 2 litros por minuto.", "Amoxicilina 90 mg/kg/día vía oral dividida cada 12 horas por 7 días.", "Acetaminofén 15 mg/kg vía oral cada 6 horas si hay fiebre.", "Observación por 12 horas con control de saturación."],
         "ordenes": [("imagen", "Radiografía de tórax", "Confirmar consolidación y descartar derrame."), ("laboratorio", "Hemograma y proteína C reactiva", "Orientar la etiología bacteriana.")],
         "resultados": [("Radiografía de tórax", "consolidación en lóbulo inferior derecho sin derrame", "Confirma neumonía lobar."), ("Hemograma", "leucocitos 16.200, neutrófilos 78 %", "Respuesta inflamatoria compatible con infección bacteriana.")],
         "acompanante": "madre"},
        {"sexo": "masculino", "edad": 27, "motivo": "«Me caí de la moto y me duele el brazo».",
         "enfermedad": "Caída de motocicleta a baja velocidad hace una hora, con trauma en antebrazo derecho, dolor intenso y deformidad. Sin pérdida de conciencia ni otros traumas.",
         "antecedentes": "Personales: niega. Familiares: sin relevancia. Alérgicos: niega.",
         "examen": "TA 124/78 mmHg, FC 92 lpm, FR 18 rpm, T 36,7 °C. Deformidad en tercio medio de antebrazo derecho, pulso radial presente, llenado capilar menor de 2 segundos, sensibilidad conservada.",
         "analisis": "Fractura cerrada de antebrazo derecho; se requiere reducción.",
         "diagnosticos": [("S522", "Fractura de la diáfisis del cúbito"), ("V280", "Motociclista lesionado en accidente de transporte")],
         "plan": ["Diclofenaco 75 mg intramuscular dosis única.", "Inmovilización con férula braquiopalmar.", "Reducción cerrada bajo sedación."],
         "ordenes": [("imagen", "Radiografía de antebrazo derecho AP y lateral", "Trauma con deformidad para caracterizar la fractura."), ("procedimiento", "Reducción cerrada de fractura e inmovilización", "Fractura desplazada confirmada en radiografía.")],
         "resultados": [("Radiografía de antebrazo", "fractura diafisaria de cúbito con desplazamiento de 20 grados", "Indica reducción cerrada.")],
         "consentimiento": "Reducción cerrada de fractura bajo sedación"},
    ],
    "C": [
        {"sexo": "femenino", "edad": 71, "motivo": "«No puedo respirar bien y tengo las piernas hinchadas».",
         "enfermedad": "Disnea progresiva de una semana hasta hacerse de reposo, ortopnea de tres almohadas y edema de miembros inferiores. Ganancia de 4 kg en 10 días.",
         "antecedentes": "Personales: insuficiencia cardíaca con fracción de eyección reducida, hipertensión arterial. Familiares: sin relevancia. Alérgicos: niega.",
         "examen": "TA 160/100 mmHg, FC 104 lpm, FR 26 rpm, SatO2 89 % al aire ambiente, T 36,4 °C. Ingurgitación yugular, crépitos bibasales, edema grado III en miembros inferiores.",
         "analisis": "Falla cardíaca descompensada con congestión pulmonar y sistémica. Se hospitaliza.",
         "diagnosticos": [("I500", "Insuficiencia cardíaca congestiva"), ("I10X", "Hipertensión esencial")], "especialidad": "Medicina interna",
         "plan": ["Furosemida 40 mg intravenosa cada 8 horas.", "Oxígeno por cánula nasal a 3 litros por minuto.", "Restricción hídrica a 1.200 mL por día y control de peso diario.", "Enalapril 10 mg vía oral cada 12 horas."],
         "ordenes": [("laboratorio", "Péptido natriurético, creatinina, electrolitos", "Confirmar descompensación y vigilar función renal con diurético."), ("imagen", "Radiografía de tórax", "Evaluar congestión pulmonar y derrame.")],
         "resultados": [("Péptido natriurético tipo B", "1.850 pg/mL", "Confirma falla cardíaca descompensada."), ("Radiografía de tórax", "cardiomegalia y redistribución de flujo", "Congestión pulmonar.")],
         "evoluciones": [("Día 2", "Mejoría de la disnea, diuresis 2.400 mL en 24 horas, peso 2 kg menos. Se continúa diurético intravenoso."), ("Día 3", "Sin ortopnea, SatO2 94 % al aire ambiente, edema grado I. Se pasa furosemida a vía oral.")],
         "egreso": ("Día 4", "Egreso con mejoría clínica. Diagnósticos de egreso: insuficiencia cardíaca congestiva descompensada e hipertensión arterial. Plan: furosemida 40 mg vía oral cada 12 horas, enalapril 10 mg cada 12 horas, control por cardiología en 15 días, signos de alarma explicados.")},
        {"sexo": "masculino", "edad": 63, "motivo": "«Dolor fuerte en la barriga del lado derecho».",
         "enfermedad": "Dolor en hipocondrio derecho de 24 horas, intensidad 8/10, irradiado a la espalda, con vómito en tres ocasiones y fiebre subjetiva. Intolerancia a grasas de larga data.",
         "antecedentes": "Personales: colelitiasis conocida hace dos años. Familiares: sin relevancia. Alérgicos: niega.",
         "examen": "TA 132/86 mmHg, FC 102 lpm, FR 20 rpm, T 38,4 °C. Signo de Murphy positivo, sin signos de irritación peritoneal generalizada.",
         "analisis": "Colecistitis aguda litiásica; se hospitaliza para manejo quirúrgico.",
         "diagnosticos": [("K810", "Colecistitis aguda"), ("K802", "Cálculo de la vesícula biliar sin colecistitis")], "especialidad": "Cirugía general",
         "plan": ["Nada vía oral.", "Lactato de Ringer 1.000 mL intravenoso cada 8 horas.", "Ampicilina sulbactam 3 g intravenoso cada 6 horas.", "Colecistectomía laparoscópica."],
         "ordenes": [("imagen", "Ecografía hepatobiliar", "Dolor en hipocondrio derecho con Murphy positivo."), ("laboratorio", "Hemograma, bilirrubinas, transaminasas", "Evaluar respuesta inflamatoria y descartar colestasis."), ("procedimiento", "Colecistectomía laparoscópica", "Colecistitis aguda litiásica confirmada por ecografía.")],
         "resultados": [("Ecografía hepatobiliar", "vesícula distendida, pared de 6 mm, cálculo de 18 mm en el cuello", "Confirma colecistitis aguda litiásica."), ("Hemograma", "leucocitos 14.800", "Respuesta inflamatoria.")],
         "consentimiento": "Colecistectomía laparoscópica bajo anestesia general",
         "evoluciones": [("Día 2", "Colecistectomía laparoscópica sin complicaciones, sangrado de 30 mL. Tolera vía oral líquida."), ("Día 3", "Dolor controlado, deambula, heridas limpias.")],
         "egreso": ("Día 3", "Egreso. Diagnóstico de egreso: colecistitis aguda litiásica, posoperatorio de colecistectomía laparoscópica. Plan: acetaminofén 1 g cada 8 horas por 5 días, curación de heridas, control en 8 días con patología.")},
        {"sexo": "femenino", "edad": 29, "motivo": "«Tengo contracciones y estoy de 39 semanas».",
         "enfermedad": "Gestante de 39,2 semanas por ecografía temprana, con actividad uterina regular desde hace 5 horas, sin sangrado ni pérdida de líquido. Movimientos fetales presentes. Controles prenatales completos.",
         "antecedentes": "Obstétricos: G2 P1, parto vaginal previo sin complicaciones. Personales: niega. Alérgicos: niega.",
         "examen": "TA 118/76 mmHg, FC 88 lpm, FR 18 rpm, T 36,7 °C. Altura uterina 34 cm, fetocardia 142 lpm, cérvix 5 cm, borrado 80 %, cefálico, membranas íntegras.",
         "analisis": "Trabajo de parto en fase activa, embarazo a término de bajo riesgo.",
         "diagnosticos": [("O80", "Parto único espontáneo"), ("Z370", "Nacido vivo único")], "especialidad": "Ginecología y obstetricia",
         "plan": ["Ingreso a sala de partos, monitoreo fetal intermitente.", "Analgesia según solicitud.", "Atención del parto por el equipo de turno."],
         "ordenes": [("laboratorio", "Hemograma, hemoclasificación y VIH", "Protocolo de ingreso a trabajo de parto.")],
         "resultados": [("Hemoglobina", "11,8 g/dL", "Sin anemia.")],
         "evoluciones": [("Día 1, 06:40", "Parto vaginal eutócico, recién nacido vivo de sexo masculino, 3.250 g, Apgar 8 y 9. Alumbramiento completo, sangrado estimado 350 mL."), ("Día 2", "Puerperio normal, lactancia establecida, útero involucionado.")],
         "egreso": ("Día 2", "Egreso materno. Diagnóstico de egreso: parto vaginal a término sin complicaciones. Plan: sulfato ferroso 300 mg cada día por 30 días, control de puerperio en 7 días, signos de alarma explicados.")},
    ],
    "D": [
        {"sexo": "femenino", "edad": 3, "motivo": "Consulta de valoración integral de primera infancia.",
         "enfermedad": "Niña de 3 años traída por su madre para la valoración de la ruta de promoción y mantenimiento. Asintomática. Alimentación variada, duerme 10 horas.",
         "antecedentes": "Perinatales: parto a término, peso al nacer 3.100 g. Vacunación: esquema completo para la edad según carné. Alérgicos: niega.",
         "examen": "Peso 14,2 kg, talla 95 cm, perímetro cefálico 49 cm, FC 104 lpm, FR 24 rpm, T 36,5 °C. Desarrollo acorde a la edad en las cuatro áreas de la escala abreviada.",
         "analisis": "Niña sana con crecimiento y desarrollo adecuados.",
         "diagnosticos": [("Z001", "Control de salud de rutina del niño")],
         "plan": ["Continuar alimentación balanceada.", "Próximo control a los 4 años."],
         "intervenciones": ["Valoración del desarrollo con escala abreviada.", "Valoración nutricional con curvas de la OMS.", "Verificación del esquema de vacunación.", "Educación en salud a la cuidadora.", "Aplicación de flúor barniz y valoración por odontología."],
         "acompanante": "madre"},
        {"sexo": "masculino", "edad": 48, "motivo": "Consulta de valoración integral del adulto.",
         "enfermedad": "Hombre de 48 años que asiste a la valoración de la ruta. Refiere sedentarismo y consumo ocasional de alcohol. Niega síntomas.",
         "antecedentes": "Personales: niega. Familiares: padre hipertenso. Alérgicos: niega.",
         "examen": "TA 134/86 mmHg, FC 74 lpm, FR 16 rpm, T 36,4 °C, peso 88 kg, talla 172 cm, IMC 29,7, perímetro abdominal 101 cm. Examen por sistemas sin hallazgos.",
         "analisis": "Adulto con sobrepeso y riesgo cardiovascular por evaluar.",
         "diagnosticos": [("Z000", "Examen médico general"), ("E660", "Obesidad debida a exceso de calorías")],
         "plan": ["Plan de actividad física y alimentación.", "Control en 12 meses con resultados."],
         "intervenciones": ["Tamizaje de riesgo cardiovascular y metabólico.", "Tamizaje de consumo de alcohol con cuestionario AUDIT.", "Educación en estilos de vida saludables.", "Valoración por odontología."],
         "ordenes": [("laboratorio", "Glicemia en ayunas y perfil lipídico", "Tamizaje de riesgo cardiovascular y metabólico de la ruta.")],
         "resultados": [("Glicemia y perfil lipídico", "glicemia 104 mg/dL, colesterol total 228 mg/dL, triglicéridos 190 mg/dL", "Glicemia alterada en ayunas y dislipidemia; se indica cambio de hábitos y control.")]},
        {"sexo": "femenino", "edad": 24, "motivo": "Control prenatal de segundo trimestre.",
         "enfermedad": "Gestante de 22 semanas, primigestante, asintomática, con movimientos fetales presentes. Toma el ácido fólico y el sulfato ferroso.",
         "antecedentes": "Obstétricos: G1 P0. Personales: niega. Alérgicos: niega.",
         "examen": "TA 108/68 mmHg, FC 84 lpm, FR 18 rpm, T 36,6 °C, peso 61 kg, altura uterina 21 cm, fetocardia 148 lpm.",
         "analisis": "Embarazo de curso normal, bajo riesgo.",
         "diagnosticos": [("Z340", "Supervisión de primer embarazo normal")],
         "plan": ["Continuar micronutrientes.", "Próximo control en 4 semanas."],
         "intervenciones": ["Clasificación del riesgo obstétrico.", "Curso de preparación para la maternidad.", "Vacunación con toxoide tetánico e influenza.", "Valoración por odontología y nutrición."],
         "ordenes": [("imagen", "Ecografía obstétrica de detalle", "Tamizaje de anomalías estructurales entre las semanas 18 y 24."), ("laboratorio", "Prueba de tolerancia a la glucosa", "Tamizaje de diabetes gestacional de la ruta.")],
         "resultados": [("Ecografía obstétrica", "feto único vivo, biometría acorde, anatomía normal", "Sin alteraciones."), ("Prueba de tolerancia a la glucosa", "basal 82 mg/dL, 1 hora 148 mg/dL, 2 horas 126 mg/dL", "Sin diabetes gestacional.")]},
    ],
}

DEFECTOS_POSIBLES = {
    "COMP-03": lambda c: True,
    "COMP-04": lambda c: True,
    "COMP-05": lambda c: True,
    "COMP-06": lambda c: True,
    "COH-03": lambda c: any(" mg" in p for p in c["plan"]),
    "COH-04": lambda c: c["sexo"] == "masculino" and c["edad"] >= 18,
    "PERT-01": lambda c: True,
    "PERT-02": lambda c: bool(c.get("ordenes")),
    "PERT-03": lambda c: "interconsulta" in c,
    "PERT-04": lambda c: "intervenciones" in c,
    "OPO-01": lambda c: True,
    "OPO-02": lambda c: "evoluciones" in c,
    "SOP-01": lambda c: "consentimiento" in c,
    "SOP-03": lambda c: bool(c.get("resultados")),
    "SOP-04": lambda c: "egreso" in c,
    "IDP-01": lambda c: True,
    "IDP-02": lambda c: True,
}


class Generador:
    def __init__(self, semilla: int) -> None:
        self.azar = random.Random(semilla)

    def persona(self, sexo: str) -> str:
        femeninos = [n for n in NOMBRES if n.endswith("a") or n in ("Carmen", "Luz", "Mercedes", "Dolores", "Beatriz")]
        masculinos = [n for n in NOMBRES if n not in femeninos]
        nombres = femeninos if sexo == "femenino" else masculinos
        return f"{self.azar.choice(nombres)} {self.azar.choice(nombres)} {self.azar.choice(APELLIDOS)} {self.azar.choice(APELLIDOS)}"

    def documento(self, edad: int) -> tuple[str, str]:
        if edad < 7:
            return "RC", str(self.azar.randint(1_040_000_000, 1_049_999_999))
        if edad < 18:
            return "TI", str(self.azar.randint(1_060_000_000, 1_069_999_999))
        return "CC", str(self.azar.choice([self.azar.randint(10_000_000, 99_999_999), self.azar.randint(1_000_000_000, 1_099_999_999)]))

    def telefono(self) -> str:
        return f"3{self.azar.randint(0, 2)}{self.azar.randint(0, 9)} {self.azar.randint(100, 999)} {self.azar.randint(1000, 9999)}"

    def direccion(self) -> str:
        return f"{self.azar.choice(VIAS)} {self.azar.randint(10, 60)} # {self.azar.randint(5, 40)}-{self.azar.randint(10, 99)}"

    def fecha_nacimiento(self, edad: int, referencia: date) -> date:
        return referencia.replace(year=referencia.year - edad) - timedelta(days=self.azar.randint(0, 364))


def formato_fecha(fecha: date, estilo: str) -> str:
    if estilo == "A":
        return fecha.strftime("%d/%m/%Y")
    if estilo == "B":
        return fecha.isoformat()
    if estilo == "C":
        return fecha.strftime("%d-%m-%Y")
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def construir(plantilla: str, caso: dict, defectos: list[str], g: Generador, numero: int) -> tuple[list, dict, dict]:
    institucion, habilitacion = INSTITUCIONES[plantilla]
    fecha = date(2026, g.azar.randint(1, 9), g.azar.randint(1, 28))
    hora = f"{g.azar.randint(7, 21):02d}:{g.azar.randint(0, 59):02d}"
    nombre = g.persona(caso["sexo"])
    tipo_doc, num_doc = g.documento(caso["edad"])
    nacimiento = g.fecha_nacimiento(caso["edad"], fecha)
    telefono = g.telefono()
    direccion = g.direccion()
    municipio = g.azar.choice(MUNICIPIOS)
    barrio = g.azar.choice(BARRIOS)
    aseguradora = g.azar.choice(ASEGURADORAS)
    medico = g.persona(g.azar.choice(["femenino", "masculino"]))
    registro = f"RM-{g.azar.randint(10000, 99999)}"
    especialidad = caso.get("especialidad") or {"A": "Medicina general", "B": "Medicina de urgencias", "C": "Medicina interna", "D": "Medicina familiar"}[plantilla]
    numero_hc = f"HC-{fecha.year}-{g.azar.randint(1000, 9999)}"
    numero_admision = f"ADM-{g.azar.randint(100000, 999999)}"
    correo = f"{nombre.split()[0].lower()}.{nombre.split()[2].lower()}{g.azar.randint(1, 99)}@correo-ejemplo.co"
    acompanante = g.persona("femenino") if caso.get("acompanante") else None
    familiar = g.persona(g.azar.choice(["femenino", "masculino"]))

    identificadores = [
        {"categoria": "PACIENTE", "valor": nombre}, {"categoria": "DOCUMENTO", "valor": num_doc},
        {"categoria": "FECHA", "valor": formato_fecha(nacimiento, plantilla)}, {"categoria": "TELEFONO", "valor": telefono},
        {"categoria": "DIRECCION", "valor": direccion}, {"categoria": "LUGAR", "valor": municipio}, {"categoria": "LUGAR", "valor": barrio},
        {"categoria": "MEDICO", "valor": medico}, {"categoria": "REGISTRO", "valor": registro},
        {"categoria": "HISTORIA", "valor": numero_hc}, {"categoria": "FACTURA", "valor": numero_admision},
        {"categoria": "FECHA", "valor": formato_fecha(fecha, plantilla)},
    ]
    if plantilla == "A":
        identificadores.append({"categoria": "CORREO", "valor": correo})
    if acompanante:
        identificadores.append({"categoria": "PACIENTE", "valor": acompanante})
    if plantilla == "C":
        identificadores.append({"categoria": "PACIENTE", "valor": familiar})

    L: list[tuple[str, str]] = []
    titulo = {"A": "HISTORIA CLÍNICA DE CONSULTA EXTERNA", "B": "HISTORIA CLÍNICA DE URGENCIAS", "C": "HISTORIA CLÍNICA DE HOSPITALIZACIÓN", "D": "REGISTRO DE ATENCIÓN DE PROMOCIÓN Y MANTENIMIENTO DE LA SALUD"}[plantilla]
    L.append(("titulo", institucion))
    L.append(("sub", f"Código de habilitación {habilitacion} · {titulo}"))
    edad_txt = f"{caso['edad']} años"
    if plantilla == "A":
        L += [("h", "DATOS DE IDENTIFICACIÓN"),
              ("p", f"Nombre completo: {nombre}    Documento de identidad: {tipo_doc} {num_doc}"),
              ("p", f"Fecha de nacimiento: {formato_fecha(nacimiento, 'A')}    Edad: {edad_txt}    Sexo: {caso['sexo']}"),
              ("p", f"Dirección: {direccion}, barrio {barrio}    Municipio: {municipio}    Teléfono: {telefono}    Correo: {correo}"),
              ("p", f"Aseguradora: {aseguradora}    Historia clínica No. {numero_hc}    Admisión: {numero_admision}"),
              ("p", f"Fecha de atención: {formato_fecha(fecha, 'A')}    Hora: {hora}")]
    elif plantilla == "B":
        L += [("h", "IDENTIFICACIÓN DEL PACIENTE"),
              ("p", f"Paciente: {nombre}  CC: {num_doc}  Edad: {edad_txt}  Sexo: {caso['sexo']}"),
              ("p", f"Nacimiento: {formato_fecha(nacimiento, 'B')}  Residencia: {municipio}, barrio {barrio}  Tel: {telefono}"),
              ("p", f"EPS: {aseguradora}  HC {numero_hc}  Ingreso {numero_admision}: {formato_fecha(fecha, 'B')} {hora}")]
        if acompanante:
            L.append(("p", f"Acompañante: {acompanante} ({caso['acompanante']})"))
    elif plantilla == "C":
        L += [("h", "DATOS DEL PACIENTE"),
              ("p", f"USUARIO: {nombre.upper()}    DOCUMENTO: {tipo_doc} {num_doc}    EDAD: {edad_txt}    SEXO: {caso['sexo'].upper()}"),
              ("p", f"FECHA DE NACIMIENTO: {formato_fecha(nacimiento, 'C')}    PROCEDENCIA: {municipio}    DIRECCIÓN: {direccion}"),
              ("p", f"TELÉFONO: {telefono}    ASEGURADORA: {aseguradora}    HISTORIA: {numero_hc}    EPISODIO: {numero_admision}"),
              ("p", f"FECHA DE INGRESO: {formato_fecha(fecha, 'C')} {hora}    SERVICIO: HOSPITALIZACIÓN")]
    else:
        L += [("h", "IDENTIFICACIÓN DEL USUARIO"),
              ("p", f"Nombre del usuario: {nombre}"),
              ("p", f"Tipo y número de documento: {tipo_doc} {num_doc}    Fecha de nacimiento: {formato_fecha(nacimiento, 'D')}    Edad: {edad_txt}    Sexo: {caso['sexo']}"),
              ("p", f"Municipio de residencia: {municipio}    Barrio: {barrio}    Teléfono de contacto: {telefono}"),
              ("p", f"Aseguradora: {aseguradora}    Historia clínica: {numero_hc}    Atención: {numero_admision}"),
              ("p", f"Fecha de la atención: {formato_fecha(fecha, 'D')}, {hora}    Curso de vida: {'primera infancia' if caso['edad'] < 6 else ('juventud' if caso['edad'] < 29 else 'adultez')}")]
        if acompanante:
            L.append(("p", f"Acompañante: {acompanante} ({caso['acompanante']})"))

    L += [("h", "MOTIVO DE CONSULTA"), ("p", caso["motivo"]), ("h", "ENFERMEDAD ACTUAL"), ("p", caso["enfermedad"])]
    if plantilla == "C":
        L.append(("p", f"Según refiere su familiar {familiar}, el cuadro empeoró en las últimas horas."))
    if "COMP-03" not in defectos:
        L += [("h", "ANTECEDENTES"), ("p", caso["antecedentes"])]
    examen = caso["examen"]
    if "COMP-04" in defectos:
        examen = examen.split(". ", 1)[1] if ". " in examen else "Sin hallazgos relevantes."
    L += [("h", "EXAMEN FÍSICO"), ("p", examen), ("h", "ANÁLISIS"), ("p", caso["analisis"])]
    if "COH-04" in defectos:
        L.append(("p", "Se realiza citología cervicouterina de tamizaje durante la consulta."))
    L.append(("h", "DIAGNÓSTICOS"))
    for codigo, nombre_dx in caso["diagnosticos"]:
        L.append(("p", f"- {nombre_dx}" if "COMP-05" in defectos else f"- {codigo} {nombre_dx}"))
    if caso.get("ordenes"):
        L.append(("h", "ÓRDENES"))
        for tipo, orden, justificacion in caso["ordenes"]:
            if "PERT-02" in defectos and tipo in ("laboratorio", "imagen"):
                L.append(("p", f"- {orden}."))
            else:
                L.append(("p", f"- {orden}. Justificación: {justificacion}"))
    if "PERT-01" in defectos:
        if not caso.get("ordenes"):
            L.append(("h", "ÓRDENES"))
        L.append(("p", {"A": "- Terapia física, 10 sesiones.", "B": "- Nebulizaciones con solución salina, 3 sesiones.", "C": "- Toracentesis diagnóstica.", "D": "- Terapia respiratoria, 5 sesiones."}[plantilla]))
    if caso.get("resultados") and "SOP-03" not in defectos:
        L.append(("h", "RESULTADOS"))
        for prueba, valor, interpretacion in caso["resultados"]:
            L.append(("p", f"- {prueba}: {valor}. Interpretación: {interpretacion}"))
    if "interconsulta" in caso:
        servicio, motivo_ic = caso["interconsulta"]
        L.append(("p", f"Interconsulta a {servicio}." if "PERT-03" in defectos else f"Interconsulta a {servicio}. Motivo: {motivo_ic}"))
    if caso.get("consentimiento") and "SOP-01" not in defectos:
        L += [("h", "CONSENTIMIENTO INFORMADO"), ("p", f"El paciente o su representante recibe información sobre el procedimiento {caso['consentimiento']}, sus riesgos y alternativas, y firma el consentimiento, que se anexa a la historia.")]
    if "COMP-06" not in defectos:
        L.append(("h", "PLAN DE MANEJO"))
        for item in caso["plan"]:
            if "COH-03" in defectos and " mg" in item:
                item = item.split(" mg")[0] + " mg."
            L.append(("p", f"- {item}"))
    if "intervenciones" in caso:
        L.append(("h", "INTERVENCIONES DE LA RUTA"))
        if "PERT-04" in defectos:
            L.append(("p", "- Educación en salud."))
        else:
            for item in caso["intervenciones"]:
                L.append(("p", f"- {item}"))
    if "evoluciones" in caso:
        L.append(("h", "EVOLUCIÓN"))
        for i, (dia, texto) in enumerate(caso["evoluciones"]):
            desfase = -2 if ("OPO-02" in defectos and i == 0) else i + 1
            fecha_ev = fecha + timedelta(days=desfase)
            L.append(("p", f"{formato_fecha(fecha_ev, plantilla)} {g.azar.randint(6, 19):02d}:{g.azar.randint(0, 59):02d} · {dia}: {texto}"))
    if "egreso" in caso and "SOP-04" not in defectos:
        dia, texto = caso["egreso"]
        L += [("h", "EPICRISIS"), ("p", f"{formato_fecha(fecha + timedelta(days=len(caso.get('evoluciones', [])) + 1), plantilla)} {g.azar.randint(8, 16):02d}:{g.azar.randint(0, 59):02d} · {dia}: {texto}")]
    elif "egreso" in caso:
        L.append(("p", f"{formato_fecha(fecha + timedelta(days=3), plantilla)} {g.azar.randint(8, 16):02d}:{g.azar.randint(0, 59):02d}: Egreso hospitalario."))
    L.append(("h", "PROFESIONAL"))
    if "IDP-01" in defectos:
        L.append(("p", f"Especialidad: {especialidad}. Firma electrónica registrada."))
    elif "IDP-02" in defectos:
        L.append(("p", f"Atendido por: {medico}. Firma electrónica registrada."))
    else:
        L.append(("p", f"Atendido por: {medico}. Registro médico: {registro}. Especialidad: {especialidad}. Firma electrónica registrada."))
    if "OPO-01" in defectos:
        L.append(("p", f"Fecha de la anotación: {formato_fecha(fecha, plantilla)}"))
    else:
        L.append(("p", f"Fecha y hora de la anotación: {formato_fecha(fecha, plantilla)} {hora}"))

    pie = f"{institucion} · Paciente: {nombre} · {tipo_doc} {num_doc}" if plantilla == "C" else f"{institucion} · Historia {numero_hc}"
    contexto = {"promocion_mantenimiento": plantilla == "D", "egreso": "egreso" in caso}
    verdad = {
        "id": f"HC-SINT-{numero:03d}", "plantilla": plantilla, "sexo": caso["sexo"], "edad": caso["edad"],
        "defectos": defectos, "contexto": contexto, "identificadores": identificadores,
    }
    return L, {"pie": pie}, verdad


def escribir_pdf(ruta: Path, lineas: list, pie: str) -> int:
    documento = fitz.open()
    ancho, alto = 595, 842
    margen = 56
    y = margen
    pagina = documento.new_page(width=ancho, height=alto)
    estilos = {"titulo": ("hebo", 13), "sub": ("helv", 9), "h": ("hebo", 10.5), "p": ("helv", 10)}

    def pie_pagina(p):
        p.insert_text((margen, alto - 30), pie, fontsize=7.5, fontname="helv", color=(0.35, 0.35, 0.35))
        p.insert_text((ancho - margen - 40, alto - 30), f"Página {p.number + 1}", fontsize=7.5, fontname="helv", color=(0.35, 0.35, 0.35))

    def envolver(texto, fuente, tam):
        palabras = texto.split()
        filas, actual = [], ""
        for palabra in palabras:
            prueba = (actual + " " + palabra).strip()
            if fitz.get_text_length(prueba, fontname=fuente, fontsize=tam) <= ancho - 2 * margen:
                actual = prueba
            else:
                filas.append(actual)
                actual = palabra
        if actual:
            filas.append(actual)
        return filas

    for estilo, texto in lineas:
        fuente, tam = estilos[estilo]
        if estilo == "h":
            y += 6
        for fila in envolver(texto, fuente, tam):
            if y > alto - margen - 20:
                pie_pagina(pagina)
                pagina = documento.new_page(width=ancho, height=alto)
                y = margen
            pagina.insert_text((margen, y), fila, fontsize=tam, fontname=fuente)
            y += tam * 1.45
        y += 2
    pie_pagina(pagina)
    documento.save(ruta)
    paginas = documento.page_count
    documento.close()
    return paginas


def generar(por_caso: int, semilla: int) -> None:
    SALIDA_PDF.mkdir(parents=True, exist_ok=True)
    SALIDA_VERDAD.mkdir(parents=True, exist_ok=True)
    g = Generador(semilla)
    numero = 1
    indice = []
    for plantilla, casos in CASOS.items():
        for caso in casos:
            for variante in range(por_caso):
                posibles = [d for d, condicion in DEFECTOS_POSIBLES.items() if condicion(caso)]
                defectos = [] if variante == 0 else sorted(g.azar.sample(posibles, k=min(len(posibles), g.azar.randint(2, 3))))
                lineas, extra, verdad = construir(plantilla, caso, defectos, g, numero)
                ruta = SALIDA_PDF / f"{verdad['id']}.pdf"
                verdad["paginas"] = escribir_pdf(ruta, lineas, extra["pie"])
                verdad["archivo"] = ruta.name
                (SALIDA_VERDAD / f"{verdad['id']}.json").write_text(json.dumps(verdad, ensure_ascii=False, indent=2), encoding="utf-8")
                indice.append({"id": verdad["id"], "plantilla": plantilla, "paginas": verdad["paginas"], "defectos": defectos})
                numero += 1
    (AQUI / "indice.json").write_text(json.dumps({"generado": datetime.now().isoformat(timespec="seconds"), "semilla": semilla, "historias": indice}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(indice)} historias generadas en {SALIDA_PDF}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--por-caso", type=int, default=2)
    parser.add_argument("--semilla", type=int, default=2026)
    argumentos = parser.parse_args()
    generar(argumentos.por_caso, argumentos.semilla)
