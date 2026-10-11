# Auditta · MVP

Producto mínimo viable de Auditta, un sistema de apoyo a la auditoría de historias clínicas para instituciones prestadoras de servicios de salud en Colombia. Anonimiza localmente los datos del paciente, contrasta el contenido clínico contra un catálogo versionado de criterios normativos mediante un modelo de lenguaje y entrega al auditor médico un informe de hallazgos con evidencia citada, para que acepte, descarte o reclasifique cada uno.

Auditta emite recomendaciones. La decisión de auditoría es siempre del profesional.

Práctica Profesional 2026-2, modalidad emprendimiento. Corporación Universitaria Iberoamericana, Ingeniería de Software. Autor: Isaac David Chávez Pérez.

## Hipótesis que valida el MVP

Si un auditor médico recibe una historia clínica con los hallazgos de riesgo de glosa ya marcados, cada uno con su evidencia textual y su sustento normativo, revisará solo lo señalado en lugar de leer la historia completa, tardará menos que en la revisión manual y aceptará como pertinente la mayoría de los hallazgos.

## Estructura

| Carpeta | Contenido |
|---|---|
| `app/` | API REST en FastAPI: autenticación, historias, hallazgos, decisiones del auditor, métricas y eventos. Sirve también la interfaz. |
| `web/` | Interfaz en HTML, CSS y JavaScript sin framework: ingreso, inicio, bandeja, confirmación de anonimización, informe con el llamado a la acción, revisión completada y métricas. |
| `pipeline/` | Procesamiento fuera de línea: extracción de PDF, anonimización por reglas, análisis con el modelo de lenguaje, verificación de evidencia, puntaje, métricas y carga a la base de datos. |
| `criterios/` | Catálogo versionado de criterios de auditoría en seis familias. |
| `corpus/` | Generador de historias clínicas sintéticas con su verdad de referencia. No contiene datos de pacientes reales. |
| `tests/` | Pruebas de la API. |

## Datos

Todo el contenido que procesa el MVP es sintético. Las historias clínicas se generan con `corpus/generar_corpus.py` a partir de plantillas de cuatro tipos de prestador y casos clínicos escritos para el proyecto, con identificadores inventados. Cada historia tiene un archivo de verdad de referencia con los identificadores insertados y los defectos documentales inducidos, que permiten medir el recall de la anonimización y la sensibilidad del análisis.

## Requisitos

- Python 3.11
- Una base de datos MongoDB en la nube para el despliegue. En desarrollo se usa una base en memoria.
- Una clave de la API de DeepSeek para la etapa de análisis del pipeline.

## Instalación local

```
pip install -r requirements-pipeline.txt
copy .env.example .env
```

Edite `.env` con sus valores. Sin `MONGODB_URI` la aplicación usa una base en memoria que se llena al arrancar con los resultados del pipeline.

## Pipeline

```
python corpus/generar_corpus.py --por-caso 2
python pipeline/ejecutar.py --sin-modelo
python pipeline/ejecutar.py
python pipeline/cargar.py
```

El primer comando genera el corpus en `corpus/pdf` y `corpus/verdad`. El segundo extrae y anonimiza sin llamar al modelo y mide el recall de la anonimización. El tercero ejecuta el análisis completo con el modelo de lenguaje, verifica que cada evidencia exista literalmente en el texto y calcula el puntaje de riesgo. El cuarto carga los resultados a la base de datos indicada en `MONGODB_URI`. Las métricas de cada corrida quedan en `pipeline/salida/metricas_pipeline.json`.

Para agregar una historia clínica nueva en un solo paso:

```
python pipeline/agregar.py "ruta\a\la\historia.pdf"
```

El comando copia el PDF al corpus, lo extrae, lo anonimiza, lo analiza con el modelo y lo carga a la base de datos con el nombre del archivo como identificador. Con `--sin-modelo` solo extrae y anonimiza. El PDF debe tener capa de texto.

El texto que recibe el proveedor externo es únicamente el texto anonimizado. Los mapas de re-identificación se guardan en `pipeline/salida/mapas` y no se versionan.

## Aplicación

```
uvicorn app.main:app --reload
```

Abra `http://127.0.0.1:8000`. Entre con la cuenta de prueba que se muestra en el ingreso o cree una cuenta, confirme la anonimización de una historia, revise sus hallazgos y registre una decisión por cada uno. Al finalizar se registra el tiempo de revisión.

Desde la pantalla «Cargar historia» se puede subir una historia clínica nueva en PDF con capa de texto (hasta 20 MB). Al subirla, el servidor la extrae y la anonimiza; el análisis con el modelo se ejecuta solo cuando el usuario confirma la anonimización. El PDF original no se conserva.

## Pruebas

```
python -m pytest tests
```

## Despliegue

El servicio se despliega en Render desde este repositorio con el archivo `render.yaml`. Configure en Render las variables `MONGODB_URI` y `FORMULARIO_RETROALIMENTACION`. La instancia gratuita se apaga tras 15 minutos sin tráfico y tarda hasta un minuto en reactivarse.

## Variables de entorno

| Variable | Uso |
|---|---|
| `MONGODB_URI` | Cadena de conexión de MongoDB. Si falta, se usa una base en memoria. |
| `MONGODB_DB` | Nombre de la base de datos. Por defecto `auditta`. |
| `JWT_SECRETO` | Clave para firmar las sesiones. |
| `JWT_HORAS` | Duración de la sesión en horas. Por defecto 12. |
| `DEEPSEEK_API_KEY` | Clave de la API del modelo de lenguaje, solo para el pipeline. |
| `DEEPSEEK_MODEL` | Modelo a usar. Por defecto `deepseek-chat`. |
| `FORMULARIO_RETROALIMENTACION` | Enlace al formulario de retroalimentación que se muestra al terminar una revisión. |

## Marco normativo del catálogo

Resolución 1995 de 1999, Resolución 3280 de 2018, Resolución 2284 de 2023, Resolución 948 de 2026 y Ley 23 de 1981. La protección de datos personales se rige por la Ley 1581 de 2012.
