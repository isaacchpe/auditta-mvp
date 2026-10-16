import os

os.environ["MONGODB_URI"] = "mongomock://localhost"

from fastapi.testclient import TestClient

from app.db import obtener_db
from app.main import app

cliente = TestClient(app)


def sesion(correo="ana@ips-ejemplo.com.co", perfil="auditor_medico"):
    respuesta = cliente.post("/api/auth/registro", json={"nombre": "Ana Prueba", "correo": correo, "clave": "clave12345", "perfil": perfil})
    assert respuesta.status_code == 201
    return {"Authorization": "Bearer " + respuesta.json()["token"]}


def sembrar():
    db = obtener_db()
    for coleccion in ("historias", "hallazgos", "revisiones", "eventos"):
        db[coleccion].delete_many({})
    db.historias.insert_one({"_id": "HC-T1", "estado": "pendiente_confirmacion", "plantilla": "B", "paginas": 3, "puntaje": 72, "nivel": "alto", "secciones": [], "entidades": []})
    db.hallazgos.insert_many([
        {"_id": "HC-T1-H01", "historia_id": "HC-T1", "orden": 1, "criterio_id": "COMP-05", "criterio": "Diagnóstico codificado", "familia": "COMP", "severidad": "alta", "descripcion": "x", "evidencia": "y", "sustento": "z", "confianza": 0.9},
        {"_id": "HC-T1-H02", "historia_id": "HC-T1", "orden": 2, "criterio_id": "SOP-02", "criterio": "Orden médica", "familia": "SOP", "severidad": "alta", "descripcion": "x", "evidencia": "y", "sustento": "z", "confianza": 0.8},
    ])


def test_sin_sesion():
    assert cliente.get("/api/historias").status_code == 401


def test_registro_valida_campos():
    assert cliente.post("/api/auth/registro", json={"nombre": "A", "correo": "malcorreo", "clave": "corta", "perfil": "otro"}).status_code == 422


def test_ingreso_incorrecto():
    sesion("luis@ips-ejemplo.com.co")
    assert cliente.post("/api/auth/ingreso", json={"correo": "luis@ips-ejemplo.com.co", "clave": "incorrecta"}).status_code == 401


def test_flujo_completo_del_auditor():
    sembrar()
    cabeceras = sesion("maria@ips-ejemplo.com.co")
    assert cliente.get("/api/historias", headers=cabeceras).json()["historias"][0]["estado"] == "pendiente_confirmacion"
    assert cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "aceptado"}).status_code == 409
    assert cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cabeceras).status_code == 200
    assert cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cabeceras).status_code == 409
    assert cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "reclasificado"}).status_code == 422
    assert cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "aceptado", "segundos_desde_apertura": 40}).status_code == 200
    assert cliente.post("/api/historias/HC-T1/cerrar-revision", headers=cabeceras, json={"segundos_revision": 90}).status_code == 409
    respuesta = cliente.post("/api/hallazgos/HC-T1-H02/decision", headers=cabeceras, json={"decision": "reclasificado", "severidad_nueva": "media", "motivo": "La orden está en enfermería."})
    assert respuesta.status_code == 200
    cierre = cliente.post("/api/historias/HC-T1/cerrar-revision", headers=cabeceras, json={"segundos_revision": 185}).json()
    assert cierre["aceptados"] == 1 and cierre["reclasificados"] == 1
    historia = cliente.get("/api/historias/HC-T1", headers=cabeceras).json()
    assert historia["estado"] == "revisada" and historia["hallazgos"][1]["severidad_revisada"] == "media"
    metricas = cliente.get("/api/metricas", headers=cabeceras).json()
    assert metricas["tasa_aceptacion"] == 0.5 and metricas["tiempo_medio_revision"] == 185 and metricas["participantes"] == 1
    assert obtener_db().eventos.count_documents({"tipo": "cta_decision"}) == 2


def test_revisiones_independientes_por_usuario():
    sembrar()
    primera = sesion("carlos@ips-ejemplo.com.co")
    segunda = sesion("lucia@ips-ejemplo.com.co", "facturacion")
    cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=primera)
    cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=primera, json={"decision": "descartado"})
    assert cliente.get("/api/historias", headers=segunda).json()["historias"][0]["estado"] == "pendiente_confirmacion"
    assert cliente.get("/api/historias/HC-T1", headers=segunda).json()["hallazgos"][0]["estado_revision"] == "pendiente"
    assert cliente.get("/api/historias/HC-T1", headers=primera).json()["hallazgos"][0]["estado_revision"] == "descartado"
    assert cliente.post("/api/hallazgos/HC-T1-H01/deshacer", headers=primera).json()["estado_revision"] == "pendiente"


def test_cuenta_de_prueba_fuera_de_metricas():
    sembrar()
    from app.semilla import sembrar_usuario_demo

    sembrar_usuario_demo()
    demo = cliente.get("/api/configuracion").json()["cuenta_prueba"]
    respuesta = cliente.post("/api/auth/ingreso", json={"correo": demo["correo"], "clave": demo["clave"]})
    assert respuesta.status_code == 200 and respuesta.json()["perfil"] == "evaluador"
    cabeceras = {"Authorization": "Bearer " + respuesta.json()["token"]}
    cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cabeceras)
    cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "aceptado"})
    metricas = cliente.get("/api/metricas", headers=cabeceras).json()
    assert metricas["hallazgos_revisados"] == 0 and metricas["participantes"] == 0
    assert sembrar_usuario_demo() is False


def test_traza_anonima_y_con_sesion():
    db = obtener_db()
    db.trazas.delete_many({})
    assert cliente.post("/api/traza", json={"traza": "t-1", "tipo": "pantalla", "ruta": "/index.html", "ms": 0}).status_code == 204
    cab = sesion("dev@ejemplo.com", "desarrollador")
    token = cab["Authorization"].split()[1]
    assert cliente.post("/api/traza", json={"traza": "t-1", "tipo": "clic", "ruta": "/bandeja.html", "ms": 6200, "detalle": {"texto": "Revisar informe"}, "token": token}).status_code == 204
    assert cliente.post("/api/traza", json={"traza": "t-1", "tipo": "otro", "ruta": "/"}).status_code == 422
    trazas = list(db.trazas.find({"traza": "t-1"}).sort("fecha", 1))
    assert len(trazas) == 2 and trazas[0]["usuario"] is None and trazas[1]["usuario"] == "dev@ejemplo.com"


def test_cuenta_compartida_separa_participantes():
    sembrar()
    from app.semilla import sembrar_usuario_demo

    sembrar_usuario_demo()
    demo = cliente.get("/api/configuracion").json()["cuenta_prueba"]

    def entrar(nombre, rol="auditor_medico"):
        r = cliente.post("/api/auth/ingreso", json={**demo, "participante": nombre, "rol": rol})
        assert r.status_code == 200
        return r.json(), {"Authorization": "Bearer " + r.json()["token"]}

    datos_a, a = entrar("Auditora Uno")
    datos_b, b = entrar("Auditor Dos")
    datos_e, e = entrar("Evaluador")
    datos_d, d = entrar("Dev Uno", "desarrollador")
    datos_p, p = entrar("Profesor", "evaluador")
    assert datos_a["perfil"] == "auditor_medico" and datos_a["nombre"] == "Auditora Uno"
    assert datos_e["perfil"] == "evaluador" and datos_p["perfil"] == "evaluador" and datos_d["perfil"] == "desarrollador"
    for cab, decision in ((a, "aceptado"), (b, "descartado"), (e, "aceptado"), (d, "aceptado"), (p, "aceptado")):
        cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cab)
        cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cab, json={"decision": decision})
    assert cliente.get("/api/historias/HC-T1", headers=b).json()["hallazgos"][0]["estado_revision"] == "descartado"
    assert cliente.get("/api/historias/HC-T1", headers=a).json()["hallazgos"][0]["estado_revision"] == "aceptado"
    metricas = cliente.get("/api/metricas", headers=a).json()
    assert metricas["participantes"] == 2 and metricas["hallazgos_revisados"] == 2 and metricas["decisiones"]["aceptado"] == 1


def test_carga_de_historia_nueva():
    from pathlib import Path

    sembrar()
    cabeceras = sesion("pedro@ips-ejemplo.com.co")
    pdf = sorted(Path("corpus/pdf").glob("*.pdf"))[0].read_bytes()
    assert cliente.post("/api/historias/cargar", headers=cabeceras, files={"archivo": ("nota.txt", b"hola", "text/plain")}).status_code == 422
    assert cliente.post("/api/historias/cargar", headers=cabeceras, files={"archivo": ("falso.pdf", b"no es pdf", "application/pdf")}).status_code == 422
    respuesta = cliente.post("/api/historias/cargar", headers=cabeceras, files={"archivo": ("Historia nueva.pdf", pdf, "application/pdf")})
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["id"].startswith("HISTORIA-NUEVA-") and datos["entidades"] > 0
    assert cliente.post("/api/historias/cargar", headers=cabeceras, files={"archivo": ("otra.pdf", pdf, "application/pdf")}).status_code == 409
    historia = cliente.get(f"/api/historias/{datos['id']}", headers=cabeceras).json()
    assert historia["analisis_pendiente"] is True and "[PACIENTE_1]" in historia["texto_anonimizado"]
    confirmacion = cliente.post(f"/api/historias/{datos['id']}/confirmar-anonimizacion", headers=cabeceras).json()
    assert confirmacion["estado"] == "analizada"


def test_historia_cargada_solo_visible_para_quien_la_cargo():
    sembrar()
    db = obtener_db()
    db.historias.insert_one({"_id": "HC-CARGA", "origen": "carga", "cargada_por": "carga.propia@ips-ejemplo.com.co", "estado": "pendiente_confirmacion", "plantilla": None, "paginas": 1, "secciones": [], "entidades": []})
    propio = sesion("carga.propia@ips-ejemplo.com.co")
    ajeno = sesion("carga.ajena@ips-ejemplo.com.co")
    ids = lambda cab: {h["_id"] for h in cliente.get("/api/historias", headers=cab).json()["historias"]}
    assert ids(propio) == {"HC-T1", "HC-CARGA"}
    assert ids(ajeno) == {"HC-T1"}
    assert cliente.get("/api/metricas", headers=ajeno).json()["historias_por_estado"]["pendiente_confirmacion"] == 1


def test_paginas_y_404():
    for ruta in ("/", "/index.html", "/bandeja.html", "/informe.html", "/metricas.html", "/estilos.css", "/app.js"):
        assert cliente.get(ruta).status_code == 200
    assert cliente.get("/no-existe").status_code == 404
    assert cliente.get("/api/no-existe").status_code == 404
