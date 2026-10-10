import os

os.environ["MONGODB_URI"] = "mongomock://localhost"

from fastapi.testclient import TestClient

from app.db import obtener_db
from app.main import app

cliente = TestClient(app)


def sesion(correo="ana@ips-ejemplo.com.co"):
    respuesta = cliente.post("/api/auth/registro", json={"nombre": "Ana Prueba", "correo": correo, "clave": "clave12345", "perfil": "auditor_medico"})
    assert respuesta.status_code == 201
    return {"Authorization": "Bearer " + respuesta.json()["token"]}


def sembrar():
    db = obtener_db()
    db.historias.delete_many({})
    db.hallazgos.delete_many({})
    db.historias.insert_one({"_id": "HC-T1", "estado": "pendiente_confirmacion", "plantilla": "B", "paginas": 3, "puntaje": 72, "nivel": "alto", "secciones": [], "entidades": []})
    db.hallazgos.insert_many([
        {"_id": "HC-T1-H01", "historia_id": "HC-T1", "orden": 1, "criterio_id": "COMP-05", "criterio": "Diagnóstico codificado", "familia": "COMP", "severidad": "alta", "descripcion": "x", "evidencia": "y", "sustento": "z", "confianza": 0.9, "estado_revision": "pendiente"},
        {"_id": "HC-T1-H02", "historia_id": "HC-T1", "orden": 2, "criterio_id": "SOP-02", "criterio": "Orden médica", "familia": "SOP", "severidad": "alta", "descripcion": "x", "evidencia": "y", "sustento": "z", "confianza": 0.8, "estado_revision": "pendiente"},
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
    assert cliente.get("/api/historias", headers=cabeceras).json()["historias"][0]["_id"] == "HC-T1"
    assert cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cabeceras).status_code == 200
    assert cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cabeceras).status_code == 409
    assert cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "reclasificado"}).status_code == 422
    assert cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "aceptado", "segundos_desde_apertura": 40}).status_code == 200
    assert cliente.post("/api/historias/HC-T1/cerrar-revision", headers=cabeceras, json={"segundos_revision": 90}).status_code == 409
    respuesta = cliente.post("/api/hallazgos/HC-T1-H02/decision", headers=cabeceras, json={"decision": "reclasificado", "severidad_nueva": "media", "motivo": "La orden está en enfermería."})
    assert respuesta.status_code == 200
    cierre = cliente.post("/api/historias/HC-T1/cerrar-revision", headers=cabeceras, json={"segundos_revision": 185}).json()
    assert cierre["aceptados"] == 1 and cierre["reclasificados"] == 1
    metricas = cliente.get("/api/metricas", headers=cabeceras).json()
    assert metricas["tasa_aceptacion"] == 0.5 and metricas["tiempo_medio_revision"] == 185
    assert obtener_db().eventos.count_documents({"tipo": "cta_decision"}) == 2
    assert cliente.get("/api/historias/HC-T1", headers=cabeceras).json()["estado"] == "revisada"


def test_deshacer():
    sembrar()
    cabeceras = sesion("jorge@ips-ejemplo.com.co")
    cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=cabeceras, json={"decision": "descartado"})
    assert cliente.post("/api/hallazgos/HC-T1-H01/deshacer", headers=cabeceras).json()["estado_revision"] == "pendiente"


def test_paginas_y_404():
    for ruta in ("/", "/index.html", "/bandeja.html", "/informe.html", "/metricas.html", "/estilos.css", "/app.js"):
        assert cliente.get(ruta).status_code == 200
    assert cliente.get("/no-existe").status_code == 404
    assert cliente.get("/api/no-existe").status_code == 404
