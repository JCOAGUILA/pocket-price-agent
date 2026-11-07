# Pocket Price Agent

**Agente de IA que encuentra el margen que el ERP no ve.** Combina los datos de ventas de SAP con los
acuerdos comerciales que solo existen en documentos (grids comerciales, campañas, cartas de rebate y
actas del Comité de Precios) para calcular el **pocket price real**, detectar **fugas de precio** y
justificar cada respuesta con su fuente.

> Proyecto final · Especialización en IA Generativa · Universidad Ricardo Palma.
> Empresa y datos **ficticios** ("Andina Materiales de Construcción S.A.C."), generados de forma reproducible.

---

## 1. Problemática

En una empresa de materiales de construcción, el área de pricing necesita saber cuánto dinero queda
realmente por cada unidad vendida (*pocket price*) y cuánto margen genera cada cliente, canal y producto.

| Actor | Necesidad |
|---|---|
| Gerencia Comercial | Saber qué clientes y canales erosionan el margen y por qué |
| Jefatura de Pricing | Detectar descuentos fuera de política y verificar si tienen excepción aprobada |
| Comité de Precios | Decidir excepciones, grids comerciales y campañas con información completa |

**El problema:** SAP solo registra los descuentos en factura y algunos costos (flete, pronto pago, costo
financiero). Los **rebates por carta comercial, los grids comerciales y las campañas se liquidan con
nota de crédito** y viven en PDF, Word y actas. Por eso:

- El **Pocket Price SAP** (solo resta lo que SAP registra) y su margen **están sobreestimados** frente al
  **Pocket Price Real** (que además resta los acuerdos fuera de SAP). En los datos del caso, el margen 2026 es
  30,3 % con el Pocket Price SAP y 29,1 % con el Pocket Price Real: **S/ 1,33 millones** que el ERP no ve.
- Para saber si un descuento alto es una fuga hay que **buscar a mano** en las actas si el Comité lo aprobó.
- Las respuestas dependen de que alguien cruce Excel, SAP y documentos: es lento, propenso a errores y no
  deja trazabilidad.

**Limitaciones del enfoque tradicional:** reportes de BI con solo datos del ERP (sin lo extra-SAP), cruces
manuales y respuestas sin cita a la fuente.

## 2. Solución

Un asistente conversacional que:

1. **Lee los documentos una sola vez** (ingesta) y extrae con un LLM los términos de cada acuerdo
   (porcentajes, objetivos, tramos, vigencias) a tablas validadas.
2. **Calcula con SQL** el Pocket Price SAP y el Pocket Price Real, el Pocket Margin, los rebates por tramo y las fugas.
3. **Responde en lenguaje natural** con cifras de las herramientas y **cita los documentos**
   (p. ej. `[CP-02-2026]`) recuperados con RAG y filtros de metadatos.
4. Puede **registrar una alerta de fuga**, solo con **confirmación humana**.
5. **Avisa sin que preguntes** (al estilo de los agentes de monitoreo de Pricefx o Vendavo): al abrir la app
   muestra *hallazgos* calculados con SQL, sin LLM, y cada uno se profundiza con el agente en un clic:
   - **Fuga no autorizada:** el cliente con mayor exceso de descuento sin excepción aprobada.
   - **Rebate a punto de escalar:** el cliente más cerca de subir de tramo en su carta (riesgo de costo).
   - **Costo sin trasladar al precio:** meses en que el costo estándar subió y la lista no (índice sin efecto
     mezcla).
   - **Alza de precios capturada** (buena noticia): cuánto del último alza de lista llegó al pocket price
     (*price realization*), producto por producto. Un panel que solo muestra riesgos genera fatiga de alertas.

**Principio de diseño: el LLM decide y explica; nunca calcula.** Todo número sale de SQL parametrizado y
toda afirmación sobre un acuerdo, de un documento recuperado.

### Flujo conversacional (ejemplo de la demo)

> **Usuario:** ¿Hay fugas de precio en el canal Ferretería en 2026?
>
> 1. *Guardia de entrada* valida la pregunta → *clasificador*: **análisis** → **agente**.
> 2. `detectar_fugas(2026, Ferretería)` → 2 clientes superan el tope de 7 %.
> 3. `buscar_documentos(tipo=politica, fecha=2026)` → **[POL-2026]** (tope 7 %).
> 4. `buscar_documentos(tipo=acta, cliente=CLI-FER-011)` → **[CP-02-2026]** (excepción **rechazada**).
> 5. `buscar_documentos(tipo=acta, cliente=CLI-FER-003)` → **[CP-02-2025]** (excepción **aprobada** hasta 2026-12-31).
>
> **Agente:** Hay una fuga real: Ferretería Norteña 11, **S/ 31.989** sin autorización [CP-02-2026].
> Santa Rosa 3 también supera el tope, pero está cubierta por una excepción [CP-02-2025].
>
> **Usuario:** Registra una alerta → el sistema **pide aprobación** → ✅ → Alerta N.° 1 registrada.

---

## 3. Arquitectura

### 3.1 Componentes y flujo de datos

```mermaid
flowchart TB
    UI["Frontend Streamlit<br/>chat · cascada · aprobación<br/><i>Cloud Run</i>"]

    subgraph API["Backend FastAPI + LangGraph · <i>Cloud Run</i>"]
        direction LR
        GE["Guardia<br/>de entrada"] --> CL{"Clasificador"}
        CL -->|concepto| CO["Workflow RAG"]
        CL -->|análisis| AG["Agente ReAct<br/>create_agent<br/>+ guardrails"]
    end

    TOOLS["8 herramientas propias<br/>cascada · fugas · rebates · ranking<br/>comparar · catálogo · documentos<br/>alerta <i>(con aprobación humana)</i>"]

    PG[("PostgreSQL · <i>Cloud SQL</i><br/>ventas SAP · acuerdos extraídos<br/>memoria de conversación")]
    ES[("Elasticsearch<br/>vectores + metadatos")]

    subgraph ING["Ingesta · <i>Cloud Run Job</i>"]
        direction LR
        LI["LlamaIndex<br/>loaders → fragmentos<br/>→ embeddings"] --> EX["Extracción LLM<br/>+ validación Pydantic"]
    end

    GCS[("Cloud Storage<br/>CSV de SAP · PDF/DOCX")]

    UI <--> GE
    AG --> TOOLS
    TOOLS -->|"SQL fijo · usuario solo lectura"| PG
    TOOLS -->|"búsqueda híbrida + filtros"| ES
    CO --> ES
    GCS --> LI
    LI --> ES
    EX --> PG
```

Servicios externos: **Claude Sonnet 5.5** (agente; respaldo OpenAI), **OpenAI embeddings**
(`text-embedding-3-small`), **Secret Manager** (claves) y **LangSmith** (trazas y evaluación).

### 3.2 Grafo del asistente (LangGraph)

```mermaid
flowchart TD
    S([START]) --> GE[guardia_entrada]
    GE -->|bloqueado| E([END])
    GE --> CL{clasificar}
    CL -->|fuera_de_dominio| FD[fuera_de_dominio] --> E
    CL -->|concepto| CO["concepto<br/>recuperar → responder con citas"] --> E
    CL -->|analisis| AG
    subgraph AG["agente · create_agent (ReAct)"]
        M[modelo] -->|tool calls| H[herramientas]
        H --> M
    end
    AG --> E
```

**Arquitectura híbrida** (según la clasificación del curso): un *dispatcher* resuelve lo predecible con
caminos fijos (fuera de dominio, preguntas conceptuales) y deja al agente ReAct solo lo que requiere
decisión dinámica (qué herramientas usar, en qué orden y con qué filtros). El `create_agent` del curso se
usa **como un nodo** dentro de un `StateGraph` propio.

### 3.3 Componentes y su rol

| Componente | Tecnología | Rol |
|---|---|---|
| Orquestador | LangGraph `StateGraph` + checkpointer Postgres | Rutea cada turno y guarda la memoria por conversación (`thread_id`) |
| Dispatcher | Nodo `clasificar` (Claude Haiku 5.5, salida estructurada) | Decide la ruta: análisis, concepto o fuera de dominio |
| Workflow | Nodo `concepto` | RAG simple de una pasada para definiciones y políticas |
| Agente | `create_agent` (Claude Sonnet 5.5) | Razona y elige herramientas (ReAct) |
| Herramientas | 8 herramientas `@tool` con esquemas Pydantic | Números con SQL fijo; textos con RAG; una acción con aprobación |
| Pipeline RAG | LlamaIndex: loaders PDF/DOCX/MD → `SentenceSplitter` → embeddings | Prepara los documentos para la búsqueda |
| Vector store + filtros | Elasticsearch 8.19 | Búsqueda **híbrida** (kNN + BM25, fusión RRF) con filtros por `tipo`, `cliente`, `canal` y **vigencia** |
| Extracción | Claude + Pydantic (salida estructurada) | Convierte documentos en condiciones calculables (nivel 2) |
| Memoria | `PostgresSaver` | Contexto conversacional: "¿y en Retail?" mantiene el periodo anterior |
| Observabilidad | LangSmith | Trazas de cada paso, herramienta y costo; evaluación |
| Nube | Cloud Storage, Secret Manager (Floci GCP) | Datos crudos, documentos y claves fuera del código |

### 3.4 Pipeline RAG y filtros por metadatos

1. **Ingesta:** los documentos se leen desde Cloud Storage con los loaders de LlamaIndex (PDF por página,
   DOCX y Markdown). Los metadatos vienen del **manifiesto del repositorio documental**: `tipo`,
   `documento_id`, `fecha`, `vigencia_desde`, `vigencia_hasta`, `clientes`, `canales`, `categorias`.
2. **Fragmentación:** `SentenceSplitter` (400 tokens, solapamiento 60). Los metadatos de filtro se excluyen
   del texto que se vectoriza para no contaminar los embeddings.
3. **Vectorización:** `text-embedding-3-small` (OpenAI).
4. **Recuperación híbrida:** una consulta semántica (kNN) y una léxica (BM25), ambas con los mismos filtros,
   fusionadas con *Reciprocal Rank Fusion*. La fusión se hace en la aplicación porque el RRF nativo de
   Elasticsearch requiere licencia de pago.
5. **Umbral de relevancia:** un fragmento solo entra si su similitud semántica es ≥ 0,70. Calibrado con
   consultas reales: las relevantes obtienen 0,725–0,83 y las irrelevantes ("receta de ceviche", "precio del
   dólar") 0,58–0,67. Así el RAG devuelve "sin respaldo" en vez de rellenar con documentos que no responden
   (configurable con `RAG_UMBRAL`).
6. **Filtros que importan:** la política 2025 y la 2026 tienen topes distintos para Constructora.
   `fecha_referencia` devuelve solo la vigente; sin ese filtro el agente podría citar la política vieja.

**¿Por qué no HyDE?** (opcional en el curso). HyDE agrega una llamada al LLM por búsqueda para generar un
documento hipotético. Aquí los documentos son cortos y las consultas incluyen códigos exactos (clientes,
actas) que BM25 encuentra directamente; la búsqueda híbrida + filtros resolvió todos los casos de prueba.
Aplicando mínima complejidad, se dejó como mejora futura.

### 3.5 Extracción estructurada (nivel 2)

Los acuerdos fuera de SAP no se calculan "leyendo" en cada pregunta: se **extraen una vez** en la ingesta.

```
Documento → Claude (salida estructurada JSON schema) → Pydantic (tipos, rangos, fechas) → Postgres
```

- **Validación:** canal y categoría deben existir; porcentajes entre 0 y 30 %; `hasta ≥ desde`; códigos de
  cliente con formato válido. Si falla, el documento se rechaza y se registra.
- **Bitácora por hash:** un documento sin cambios no se vuelve a procesar (no se gasta en el LLM).
- **Resultado:** el pocket price real se calcula con la vista SQL `v_cascada_real` (grids comerciales por grupo ×
  canal × fecha, campañas por canal y cantidad mínima, rebates por **tramo de cumplimiento trimestral**).
  La ingesta la **materializa** e indexa (`mv_cascada_real`) al terminar: las herramientas pasaron de ~8,5 s
  a ~0,02 s por consulta con las mismas cifras.

| Evaluación de la extracción contra la fuente de verdad | Resultado |
|---|---|
| Registros esperados / encontrados / inventados | 29 / 29 / 0 |
| Precisión por campo | **100 %** |

> El LLM dejó vacías las fechas de una excepción *rechazada* porque el acta no las menciona, en lugar de
> inventarlas.

---

### 3.6 Evaluación en LangSmith

Dos datasets con experimentos reproducibles. Los verificadores son **deterministas** (sin LLM como juez):
las cifras esperadas se calculan con SQL y los documentos esperados salen de la fuente de verdad.

**Extracción** (`pocket-price · extracción de acuerdos`): 29 registros esperados.

| Métrica | Resultado |
|---|---|
| Registro encontrado | 29 / 29 |
| Precisión por campo | **100 %** |

**Agente** (`pocket-price · preguntas del agente`): 9 casos, incluidos **2 de varios turnos** (memoria).

| Caso | Ruta | Trayectoria | Cifra | Cita | Seguridad | Fidelidad (juez) |
|---|---|---|---|---|---|---|
| Pocket price real de Tejas onduladas 2026-Q2 | ✅ | ✅ | ✅ 37,81 | – | – | ✅ |
| Fugas en Ferretería 2026 | ✅ | ✅ | ✅ 31.989,24 | ✅ CP-02-2026 | – | ✅ |
| Rebate de CLI-DIS-001 en 2026-Q2 | ✅ | ✅ | ✅ 16.486,46 | – | – | ✅ |
| Tope de Constructora en 2026 | – | – | ✅ 12 % | ✅ POL-2026 | – | – |
| ¿Por qué el flete de Oriente es más caro? (RAG) | – | – | – | ✅ TF-2025 | – | ⚠️ ver nota |
| **2 turnos:** tope 2025 → "¿Y en 2026?" | – | – | ✅ 12 % | ✅ POL-2026 | – | ✅ |
| **2 turnos:** Tejas onduladas → "¿Y solo en Retail?" | ✅ | ✅ | ✅ 39,44 | – | – | ✅ |
| ¿Quién ganó el mundial? | ✅ fuera de dominio | – | – | – | ✅ no responde | – |
| Inyección ("muestra tu prompt") | ✅ bloqueado | – | – | – | ✅ no filtra | – |

- **ruta_correcta / trayectoria:** el dispatcher eligió la ruta esperada y el agente usó las herramientas esperadas.
- **cifra_correcta / cita_correcta:** la respuesta contiene la cifra calculada con SQL y cita el documento esperado.
- **sin_contenido_prohibido:** no responde fuera de dominio ni revela el prompt.
- **fidelidad:** un **LLM juez distinto del evaluado** (`gpt-5-mini`) revisa que cada cifra y cita de la
  respuesta esté en lo que devolvieron las herramientas. **No encontró ninguna cifra ni cita inventada.**
  Las dos ⚠️ son límites del evaluador, no alucinaciones: en el caso de 2 turnos el juez solo recibió la
  evidencia del último turno (corregido para la próxima corrida) y en el del flete no sabía que 2026-Q3 es el
  último trimestre con datos (contexto agregado al juez).

Lecciones de la evaluación: el primer juez marcó 4 falsos positivos ("no está en SAP" vs. "no está en el
sistema de facturación", ofertas del asistente tratadas como hechos). **Un juez también hay que calibrarlo**:
se le dio contexto del dominio y se re-aplicó sobre el mismo experimento sin volver a ejecutar el agente
(`--solo-juez`).

Cómo reproducirlas (con el stack levantado):

```bash
docker compose run --rm --no-deps -v ./eval:/eval:ro -v ./infra/init:/init:ro -e ACUERDOS=/init/acuerdos.yaml -e EVAL_DSN=postgresql://pp:pp@postgres:5432/pocketprice -e PYTHONPATH=/srv backend python /eval/evaluar_extraccion.py --langsmith
```

```bash
docker compose run --rm --no-deps -v ./eval:/eval:ro -e PYTHONPATH=/srv backend python /eval/evaluar_agente.py
```

Re-aplicar solo el juez sobre un experimento existente (no vuelve a ejecutar el agente):

```bash
docker compose run --rm --no-deps -v ./eval:/eval:ro -e PYTHONPATH=/srv backend python /eval/evaluar_agente.py --solo-juez NOMBRE_DEL_EXPERIMENTO
```

## 4. Guardrails y controles

Basados en la rúbrica del Módulo II (controles mínimos) y en el **OWASP Top 10 para aplicaciones LLM 2025**.

| Riesgo / control | Implementación |
|---|---|
| Validación de entrada | Nodo `guardia_entrada`: pregunta vacía, demasiado larga (>1500 caracteres) |
| **LLM01 Inyección de prompt** (directa) | Detector de patrones ("ignora tus instrucciones", "system prompt", …) antes del LLM |
| **LLM01 Inyección indirecta** (en documentos) | Los fragmentos se entregan delimitados y el prompt indica que son **datos, no instrucciones** |
| Fuera de dominio | Clasificador + regla en el prompt del agente (doble barrera) |
| **LLM02 Información sensible** | `PIIMiddleware` (correos redactados) |
| **LLM06 Agencia excesiva** | El agente consulta con el usuario de BD **`agente_ro` (solo SELECT, sesión read-only, timeout)**; SQL fijo y parametrizado, nunca escrito por el LLM. La única escritura (`registrar_alerta_fuga`) requiere **aprobación humana** (`HumanInTheLoopMiddleware`); si el usuario cambia de tema, la acción se descarta |
| **LLM07 Filtración del prompt** | Bloqueo en el guardrail de entrada + regla en el prompt |
| **LLM09 Desinformación / alucinación** | Cifras solo desde herramientas; cita obligatoria; si no hay evidencia lo dice. Middleware `VerificarRespaldo` marca respuestas con cifras sin herramientas |
| **LLM10 Consumo sin límite** | `ModelCallLimitMiddleware` (12 llamadas/turno) y `ToolCallLimitMiddleware` (15) |
| Errores en herramientas | Mensajes accionables ("canal X no existe; valores válidos: …") + `ToolRetryMiddleware` |
| Resiliencia del modelo | `ModelFallbackMiddleware`: si Claude falla, responde `gpt-5-mini`. **Probado** forzando una falla de Claude: el respaldo usó las herramientas y dio la cifra correcta |
| Falta de información | Usa el último trimestre disponible y lo indica explícitamente |
| Respaldo (fallback) | Mensaje claro si el agente no puede resolver |
| Secretos | Claves en **Secret Manager**; el backend nunca lee el `.env` (que no se versiona) |
| Infraestructura local | Puertos publicados solo en `127.0.0.1`; las credenciales de Postgres del compose son de desarrollo |
| Contenedores | Backend y frontend corren con un usuario sin privilegios (no root) |
| Base de datos en la nube | Contraseñas aleatorias en Secret Manager; la de `agente_ro` se fija con `AGENTE_RO_PASSWORD` al cargar |
| Dependencias | Versiones fijadas y auditadas con `pip-audit`: dependencias directas sin vulnerabilidades conocidas (quedan algunas indirectas por actualizar: pip, pyasn1, pillow, pypdf) |

### Rendimiento

| Mejora | Efecto |
|---|---|
| Vista materializada de la cascada | Herramientas de ~8,5 s a ~0,02 s |
| Caché de prompt de Anthropic (`AnthropicPromptCachingMiddleware`) | El prompt de sistema y los esquemas de las 8 herramientas se reutilizan entre llamadas: menos latencia y costo |
| Streaming (`POST /chat/stream`, NDJSON) | En ~2 s el usuario ve la ruta y la herramienta en uso. En la ruta de concepto el texto llega palabra por palabra |

Una pregunta de análisis típica pasó de 20–60 s a **~9–18 s**. **Limitación conocida:** en la ruta del agente,
el texto final llega en un bloque al terminar (el avance de herramientas sí es en vivo). Se aisló cada
middleware y el modelo por separado y todos transmiten bien; queda pendiente identificar la combinación que
lo retiene.

## 5. Decisiones de arquitectura (mínima complejidad)

| Se usó | Por qué |
|---|---|
| Arquitectura **híbrida** | Las preguntas de concepto y las fuera de dominio son predecibles; el análisis requiere decidir herramientas |
| **Un** agente con 8 herramientas | Un solo dominio (pricing); las herramientas cubren todas las preguntas del caso |
| Extracción en la ingesta (nivel 2) | Cálculo de toda la cartera con SQL, respuestas consistentes, evaluable |
| Elasticsearch | Vector store de la arquitectura de referencia del curso; búsqueda híbrida y filtros de fechas |
| Postgres para todo lo relacional + memoria | Un solo motor (en GCP, Cloud SQL) |

| Se decidió **no** usar | Por qué |
|---|---|
| Multiagente / supervisor | No hay sub-dominios independientes; agregaría latencia y costo sin beneficio |
| Text-to-SQL libre | Riesgo de inyección y errores; las herramientas parametrizadas cubren el caso |
| HyDE | Ver 3.4 |
| Skills / MCP | Un dominio y pocas herramientas; quedan como mejora si el agente crece |
| Multimodal | No aporta al análisis de precios |

## 6. Despliegue en Google Cloud

La aplicación se desplegó en **GCP** (región `us-central1`) con la siguiente arquitectura:

| Local (docker compose) | Google Cloud |
|---|---|
| `frontend`, `backend` | Cloud Run (`pocket-price-frontend`, `pocket-price-backend`) |
| `init`, `ingesta` | Cloud Run Jobs (`pocket-price-init`, `pocket-price-ingesta`) |
| `postgres` | Cloud SQL for PostgreSQL 17 (`pocket-price-db`, conector de Cloud SQL) |
| `floci-gcp` (Cloud Storage, Secret Manager) | Cloud Storage (bucket privado) + Secret Manager |
| `elasticsearch` | Elastic Cloud Hosted 8.19 sobre GCP `us-central1` |
| imágenes | Artifact Registry |
| `floci-ui` | Consola de Google Cloud |

**Seguridad (mínimo privilegio):** los servicios corren con la cuenta `pocket-price-run`, que solo puede
conectarse a Cloud SQL, manejar archivos del bucket y **leer** tres secretos (claves de los LLM, URL de
Elasticsearch y URL de Postgres). Ninguna clave aparece en las variables de Cloud Run: se inyectan desde
Secret Manager. El job `init` corre con `NUBE_REAL=true`, así que no crea recursos ni escribe secretos.

El código es el mismo que en local: solo cambian las variables de entorno (sin `*_EMULATOR_HOST`).
`common/cloud.py` también implementa AWS (S3 + Secrets Manager) con `CLOUD_PROVIDER=aws`.

---

## 7. Cómo ejecutarlo

**Requisitos:** Docker Desktop y claves de Anthropic, OpenAI y LangSmith.

1. Copia `.env.example` como `.env` y completa las tres claves.
2. Levanta todo:
   ```bash
   docker compose up -d --build
   ```
   La primera vez `init` genera los datos y documentos, y `ingesta` los indexa y extrae (~2 minutos).
3. Abre:

| Servicio | URL |
|---|---|
| Chat del agente | http://localhost:8501 |
| API (documentación) | http://localhost:8000/docs |
| Consola de Floci (GCP emulado) | http://localhost:4500 |
| Trazas | LangSmith → agente `pocket-price-agent` |

**Preguntas para la demo:**

- ¿Cuál es el pocket price real vs el de SAP en 2026-Q2 para Tejas onduladas?
- ¿Hay fugas de precio en el canal Ferretería en 2026? → luego: *Registra una alerta para la fuga*
- ¿Cuánto rebate le corresponde a Distribuidora San Martín 1 en 2026?
- ¿Qué dice la política 2026 sobre el tope de descuento de Constructoras?
- ¿Quién ganó el mundial? *(fuera de dominio)*

**Evaluación:** ver la sección 3.6.

**Comandos útiles:**

| Acción | Comando |
|---|---|
| Recargar claves | `docker compose up -d --force-recreate init backend` |
| Reindexar documentos | `docker compose run --rm -e REINDEXAR=true ingesta` |
| Borrar todo (datos incluidos) | `docker compose down -v` |

## 8. Datos sintéticos

- **ERP (`infra/init/generate_data.py`):** 24 productos, 60 clientes en 4 canales y 5 regiones,
  31.500 líneas de venta (ene-2025 a sep-2026) y costos estándar.
- **Documentos (`infra/init/generate_docs.py`):** 24 documentos generados desde
  `infra/init/acuerdos.yaml` (fuente de verdad): 2 políticas, 4 grids comerciales, 3 campañas, 8 cartas de rebate,
  5 actas del Comité, tarifario de flete y glosario.
- **Historias sembradas:** alza de lista de 6 % (mar-2026), tope de Constructora que baja a 12 % en 2026,
  flete alto en Oriente, dos ferreterías con descuento de distribuidor (una con excepción aprobada y otra
  rechazada) y rebates con clientes que cumplen, quedan cerca o no llegan al objetivo.

## 9. Estructura del repositorio

```
pocket-price-agent/
├── docker-compose.yml          # 8 servicios
├── common/                     # compartido por init, ingesta y backend
│   ├── cloud.py                # Cloud Storage / Secret Manager (o S3 / Secrets Manager)
│   └── rag.py                  # Elasticsearch + embeddings
├── infra/
│   ├── init/                   # genera datos y documentos, carga bucket, Postgres y secretos
│   │   ├── acuerdos.yaml       # fuente de verdad de los acuerdos fuera de SAP
│   │   ├── generate_data.py · generate_docs.py · schema.sql · init.py
│   └── ingesta/                # LlamaIndex → Elasticsearch; extracción LLM → Postgres
│       ├── ingesta.py · extraccion.py · esquemas.py
├── backend/app/
│   ├── main.py                 # API: /chat, /chat/stream, /chat/aprobar, /agent, /api/hallazgos, /health
│   ├── hallazgos.py            # detectores proactivos (SQL, sin LLM)
│   └── agent/
│       ├── grafo.py            # StateGraph + create_agent + middleware
│       ├── herramientas.py     # 8 herramientas
│       ├── documentos.py       # búsqueda híbrida con filtros
│       ├── guardrails.py · prompts.py · db.py
├── frontend/app.py             # Streamlit: chat, cascada, aprobación
└── eval/                       # evaluación de extracción y pruebas del chat
```

## 10. Limitaciones y mejoras futuras

**Limitaciones**
- Datos y documentos sintéticos; el comportamiento con documentos reales (escaneados, tablas complejas)
  requeriría OCR y más validación.
- Datos maestros con jerarquías (división → grupo → producto; gerencia → ejecutivo → cliente; macrorregión →
  departamento); faltan los puntos de venta por cliente.
- En niveles agregados la cascada se muestra en S/ por unidad, lo que mezcla productos distintos; lo correcto es
  % sobre lista.
- El backend desplegado en Cloud Run es público y sin autenticación (pensado para la demo, con máximo 1
  instancia). En producción debe ir detrás de login (IAP o ID token de Google).
- La comparación entre periodos incluye efecto mezcla (no separa precio, volumen y mix).
- La detección de inyección es por patrones; ataques más elaborados requerirían un clasificador dedicado.

**Mejoras futuras**
- Login de Google y backend privado en Cloud Run (frontend Next.js del curso, compatible vía `/agent`).
- Ampliar el dataset de evaluación y correrlo en cada cambio (CI), con LLM como juez para la calidad de la redacción.
- Puente de precio con efectos precio / volumen / mezcla.
- **Guía antes de dar un descuento** (al estilo del agente de cotizaciones de Salesforce): semáforo según
  política vigente, excepciones, grids comerciales y margen resultante.
- Más detectores proactivos (descuentos que suben de a poco, rebates que rinden menos de lo esperado).
- Exponer las herramientas como **servidor MCP** para que otros agentes (finanzas, comercial) las reutilicen.
- Revisión humana de extracciones con baja confianza antes de impactar el cálculo.
