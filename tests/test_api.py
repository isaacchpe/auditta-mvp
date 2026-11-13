import os

os.environ["MONGODB_URI"] = "mongomock://localhost"

from pathlib import Path

from fastapi.testclient import TestClient

from app.db import obtener_db
from app.main import app

cliente = TestClient(app)


def ficha(respuesta):
    assert respuesta.status_code in (200, 201), respuesta.text
    return {"Authorization": "Bearer " + respuesta.json()["token"]}


def sesion(correo="ana@ips-ejemplo.com.co", perfil="auditor_medico"):
    return ficha(cliente.post("/api/auth/registro", json={"nombre": "Ana Prueba", "correo": correo, "clave": "clave12345", "perfil": perfil, "acepta_tratamiento": True}))


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


def test_registro_exige_clave_segura_y_consentimiento():
    base = {"nombre": "Rosa Prueba", "correo": "rosa@ips-ejemplo.com.co", "perfil": "auditor_medico", "acepta_tratamiento": True}
    assert cliente.post("/api/auth/registro", json={**base, "clave": "soloLetras"}).status_code == 422
    assert cliente.post("/api/auth/registro", json={**base, "clave": "12345678"}).status_code == 422
    assert cliente.post("/api/auth/registro", json={**base, "clave": "clave12345", "acepta_tratamiento": False}).status_code == 422
    assert cliente.post("/api/auth/registro", json={**base, "correo": "x@demo.auditta.app", "clave": "clave12345"}).status_code == 422
    respuesta = cliente.post("/api/auth/registro", json={**base, "correo": " ROSA@ips-ejemplo.com.co ", "clave": "clave12345"})
    assert respuesta.status_code == 201 and respuesta.json()["correo"] == "rosa@ips-ejemplo.com.co"
    assert cliente.post("/api/auth/registro", json={**base, "clave": "clave12345"}).status_code == 409


def test_ingreso_incorrecto():
    sesion("luis@ips-ejemplo.com.co")
    assert cliente.post("/api/auth/ingreso", json={"correo": "luis@ips-ejemplo.com.co", "clave": "incorrecta"}).status_code == 401
    assert cliente.post("/api/auth/ingreso", json={"correo": "nadie@ips-ejemplo.com.co", "clave": "clave12345"}).status_code == 401


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
    assert cliente.get("/api/metricas", headers=segunda).json()["hallazgos_revisados"] == 0
    assert cliente.post("/api/hallazgos/HC-T1-H01/deshacer", headers=primera).json()["estado_revision"] == "pendiente"


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


def test_carga_de_historia_nueva():
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
    db.hallazgos.insert_one({"_id": "HC-CARGA-H01", "historia_id": "HC-CARGA", "orden": 1, "criterio_id": "COMP-05", "familia": "COMP", "severidad": "alta"})
    propio = sesion("carga.propia@ips-ejemplo.com.co")
    ajeno = sesion("carga.ajena@ips-ejemplo.com.co")
    ids = lambda cab: {h["_id"] for h in cliente.get("/api/historias", headers=cab).json()["historias"]}
    assert ids(propio) == {"HC-T1", "HC-CARGA"}
    assert ids(ajeno) == {"HC-T1"}
    metricas_ajeno = cliente.get("/api/metricas", headers=ajeno).json()
    assert metricas_ajeno["historias_por_estado"]["pendiente_confirmacion"] == 1 and metricas_ajeno["hallazgos_total"] == 2
    assert cliente.get("/api/historias/HC-CARGA", headers=ajeno).status_code == 404
    assert cliente.post("/api/historias/HC-CARGA/confirmar-anonimizacion", headers=ajeno).status_code == 404
    assert cliente.post("/api/hallazgos/HC-CARGA-H01/decision", headers=ajeno, json={"decision": "aceptado"}).status_code == 404
    assert cliente.post("/api/hallazgos/HC-CARGA-H01/deshacer", headers=ajeno).status_code == 404
    assert cliente.post("/api/historias/HC-CARGA/cerrar-revision", headers=ajeno, json={"segundos_revision": 1}).status_code == 404
    historia = cliente.get("/api/historias/HC-CARGA", headers=propio).json()
    assert historia["_id"] == "HC-CARGA" and "cargada_por" not in historia


def test_mismo_pdf_cargado_por_dos_usuarios():
    sembrar()
    pdf = sorted(Path("corpus/pdf").glob("*.pdf"))[0].read_bytes()
    uno = sesion("pdf.uno@ips-ejemplo.com.co")
    dos = sesion("pdf.dos@ips-ejemplo.com.co")
    id_uno = cliente.post("/api/historias/cargar", headers=uno, files={"archivo": ("Igual.pdf", pdf, "application/pdf")}).json()["id"]
    respuesta = cliente.post("/api/historias/cargar", headers=dos, files={"archivo": ("Igual.pdf", pdf, "application/pdf")})
    assert respuesta.status_code == 201 and respuesta.json()["id"] != id_uno
    assert cliente.get(f"/api/historias/{id_uno}", headers=dos).status_code == 404


def test_cerrar_sesion_invalida_el_token():
    cab = sesion("salida@ips-ejemplo.com.co")
    assert cliente.get("/api/cuenta", headers=cab).status_code == 200
    assert cliente.post("/api/auth/salir", headers=cab).status_code == 204
    assert cliente.get("/api/cuenta", headers=cab).status_code == 401
    assert cliente.get("/api/historias", headers={"Authorization": "Bearer basura"}).status_code == 401


def test_sesiones_independientes_y_cierre_remoto():
    correo = "multi@ips-ejemplo.com.co"
    sesion(correo)
    entrar = lambda agente: ficha(cliente.post("/api/auth/ingreso", headers={"User-Agent": agente}, json={"correo": correo, "clave": "clave12345"}))
    portatil = entrar("Mozilla/5.0 (Windows NT 10.0) Chrome/130.0")
    celular = entrar("Mozilla/5.0 (Linux; Android 14) Chrome/130.0")
    lista = cliente.get("/api/cuenta/sesiones", headers=portatil).json()["sesiones"]
    assert len(lista) == 3 and lista[0]["actual"] and lista[0]["dispositivo"] == "Chrome en Windows"
    ref_celular = next(s["ref"] for s in lista if s["dispositivo"] == "Chrome en Android")
    assert cliente.delete(f"/api/cuenta/sesiones/{ref_celular}", headers=portatil).status_code == 204
    assert cliente.get("/api/cuenta", headers=celular).status_code == 401
    assert cliente.delete("/api/cuenta/sesiones/noexiste", headers=portatil).status_code == 404
    ajeno = sesion("otro.multi@ips-ejemplo.com.co")
    ref_portatil = cliente.get("/api/cuenta/sesiones", headers=portatil).json()["sesiones"][0]["ref"]
    assert cliente.delete(f"/api/cuenta/sesiones/{ref_portatil}", headers=ajeno).status_code == 404
    assert cliente.post("/api/cuenta/sesiones/cerrar-otras", headers=portatil).json()["sesiones_cerradas"] == 1
    assert len(cliente.get("/api/cuenta/sesiones", headers=portatil).json()["sesiones"]) == 1


def test_bloqueo_tras_intentos_fallidos():
    correo = "bloqueo@ips-ejemplo.com.co"
    sesion(correo)
    for _ in range(5):
        assert cliente.post("/api/auth/ingreso", json={"correo": correo, "clave": "malamala1"}).status_code == 401
    respuesta = cliente.post("/api/auth/ingreso", json={"correo": correo, "clave": "clave12345"})
    assert respuesta.status_code == 429 and "15 minutos" in respuesta.json()["detail"]
    obtener_db().usuarios.update_one({"_id": correo}, {"$set": {"bloqueo_ts": 0}})
    assert cliente.post("/api/auth/ingreso", json={"correo": correo, "clave": "clave12345"}).status_code == 200


def test_cambio_de_clave_cierra_las_demas_sesiones():
    correo = "clave@ips-ejemplo.com.co"
    actual = sesion(correo)
    otra = ficha(cliente.post("/api/auth/ingreso", json={"correo": correo, "clave": "clave12345"}))
    assert cliente.post("/api/cuenta/clave", headers=actual, json={"actual": "incorrecta1", "nueva": "nueva12345"}).status_code == 403
    assert cliente.post("/api/cuenta/clave", headers=actual, json={"actual": "clave12345", "nueva": "corta"}).status_code == 422
    assert cliente.post("/api/cuenta/clave", headers=actual, json={"actual": "clave12345", "nueva": "nueva12345"}).json()["sesiones_cerradas"] == 1
    assert cliente.get("/api/cuenta", headers=otra).status_code == 401
    assert cliente.get("/api/cuenta", headers=actual).status_code == 200
    assert cliente.post("/api/auth/ingreso", json={"correo": correo, "clave": "clave12345"}).status_code == 401
    assert cliente.post("/api/auth/ingreso", json={"correo": correo, "clave": "nueva12345"}).status_code == 200


def test_actualizar_datos_de_la_cuenta():
    cab = sesion("datos@ips-ejemplo.com.co")
    respuesta = cliente.put("/api/cuenta", headers=cab, json={"nombre": "  Ana   María Prueba ", "perfil": "coordinador"})
    assert respuesta.status_code == 200 and respuesta.json()["nombre"] == "Ana María Prueba"
    nuevo = {"Authorization": "Bearer " + respuesta.json()["token"]}
    cuenta = cliente.get("/api/cuenta", headers=nuevo).json()
    assert cuenta["perfil"] == "coordinador" and cuenta["correo"] == "datos@ips-ejemplo.com.co" and cuenta["demo"] is False


def test_demo_individual_aislada_y_fuera_del_estudio():
    sembrar()
    uno = ficha(cliente.post("/api/auth/demo"))
    dos = ficha(cliente.post("/api/auth/demo"))
    cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=uno)
    cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=uno, json={"decision": "aceptado"})
    assert cliente.get("/api/historias/HC-T1", headers=dos).json()["hallazgos"][0]["estado_revision"] == "pendiente"
    cuenta = cliente.get("/api/cuenta", headers=uno).json()
    assert cuenta["demo"] is True and cuenta["correo"] is None and cuenta["expira_ts"]
    assert cliente.put("/api/cuenta", headers=uno, json={"nombre": "Cambio", "perfil": "otro"}).status_code == 403
    assert cliente.post("/api/cuenta/clave", headers=uno, json={"actual": "x", "nueva": "nueva12345"}).status_code == 403
    assert cliente.get("/api/metricas", headers=uno).json()["hallazgos_revisados"] == 1
    assert cliente.get("/api/metricas?alcance=estudio", headers=uno).status_code == 403
    assert cliente.post("/api/auth/ingreso", json={"correo": "evaluador@auditta.test", "clave": "Auditta2026"}).status_code == 403


def test_demos_vencidas_se_borran():
    from app.main import limpiar_demos_vencidas

    sembrar()
    demo = cliente.post("/api/auth/demo").json()
    cab = {"Authorization": "Bearer " + demo["token"]}
    cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cab)
    db = obtener_db()
    db.usuarios.update_one({"_id": demo["correo"]}, {"$set": {"expira_ts": 1}})
    assert limpiar_demos_vencidas() == 1
    assert db.usuarios.find_one({"_id": demo["correo"]}) is None
    assert db.revisiones.count_documents({"usuario": demo["correo"]}) == 0
    assert db.sesiones.count_documents({"usuario": demo["correo"]}) == 0
    assert cliente.get("/api/cuenta", headers=cab).status_code == 401


def test_eliminar_cuenta_borra_sus_datos():
    sembrar()
    db = obtener_db()
    correo = "borrar@ips-ejemplo.com.co"
    cab = sesion(correo)
    db.historias.insert_one({"_id": "HC-BORRAR", "origen": "carga", "cargada_por": correo, "paginas": 1, "secciones": [], "entidades": []})
    db.hallazgos.insert_one({"_id": "HC-BORRAR-H01", "historia_id": "HC-BORRAR", "familia": "COMP", "severidad": "alta", "criterio_id": "COMP-05"})
    cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=cab)
    assert cliente.post("/api/cuenta/eliminar", headers=cab, json={"clave": "otra12345"}).status_code == 403
    resultado = cliente.post("/api/cuenta/eliminar", headers=cab, json={"clave": "clave12345"}).json()
    assert resultado["historias"] == 1 and resultado["hallazgos"] == 1 and resultado["revisiones"] == 1
    assert db.usuarios.find_one({"_id": correo}) is None and db.hallazgos.find_one({"_id": "HC-T1-H01"})
    assert db.eventos.count_documents({"usuario": correo}) == 0
    assert cliente.get("/api/cuenta", headers=cab).status_code == 401


def test_metricas_del_estudio_para_administrador(monkeypatch):
    import app.main as principal

    sembrar()
    monkeypatch.setattr(principal, "ADMIN_CORREOS", {"admin@auditta.co"})
    auditor = sesion("auditor.estudio@ips-ejemplo.com.co")
    admin = sesion("admin@auditta.co", "desarrollador")
    cliente.post("/api/historias/HC-T1/confirmar-anonimizacion", headers=auditor)
    cliente.post("/api/hallazgos/HC-T1-H01/decision", headers=auditor, json={"decision": "aceptado"})
    obtener_db().revisiones.insert_one({"usuario": "evaluador@auditta.test#auditor_medico#historico", "historia_id": "HC-T1", "estado": "analizada", "decisiones": {"HC-T1-H02": {"decision": "descartado"}}})
    personal = cliente.get("/api/metricas", headers=admin).json()
    assert personal["alcance"] == "personal" and personal["puede_ver_estudio"] is True and personal["hallazgos_revisados"] == 0
    estudio = cliente.get("/api/metricas?alcance=estudio", headers=admin).json()
    assert estudio["participantes"] == 2 and estudio["decisiones"]["aceptado"] == 1 and estudio["decisiones"]["descartado"] == 1


def test_paginas_y_404():
    for ruta in ("/", "/index.html", "/bandeja.html", "/informe.html", "/metricas.html", "/cuenta.html", "/privacidad.html", "/estilos.css", "/app.js"):
        assert cliente.get(ruta).status_code == 200
    assert cliente.get("/no-existe").status_code == 404
    assert cliente.get("/api/no-existe").status_code == 404
