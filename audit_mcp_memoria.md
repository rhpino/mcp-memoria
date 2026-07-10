# Informe de Auditoría Integral del Servidor MCP: `mcp-memoria`

**Fecha de Auditoría:** 2026-07-08  
**Autor:** Antigravity (Superpowers Agent)  
**Permisos Aplicados:** Solo Auditoría (Lectura y Redacción de Informe)  
**Repositorio:** `/opt/mcps/memoria`

---

## Resumen Ejecutivo

Se realizó un análisis estático del código fuente, dependencias, base de datos (conexiones/esquema), y suite de pruebas para el servidor `mcp-memoria`.

A diferencia de `mcp-mop`, el servidor `mcp-memoria` **no presenta fallas críticas de runtime (crashes)** por mezcla de datetimes ni fugas de recursos obvias. Su suite de pruebas es robusta (84/84 aprobadas). Sin embargo, se identificaron **1 limitación lógica en la búsqueda KAG**, **algunas redundancias en el código** y **advertencias menores de pruebas**.

---

## Hallazgos y Análisis Detallado

### 1. Limitación Lógica: `hop_depth` Inactivo en `hybrid_search` (Logic Limitation)
* **Archivo:** [search.py](file:///opt/mcps/memoria/src/memoria_mcp/search.py#L250)  
* **Código Afectado (Línea 250):**
  ```python
  if cross_refs and hop_depth > 0 and fused:
  ```
* **Síntoma:** Aunque el parámetro `hop_depth` sugiere que la expansión de referencias cruzadas en el grafo puede realizarse a múltiples niveles de profundidad (ej. BFS con `depth=N`), el código **solo realiza una única iteración de 1 salto** (1-hop expansion). 
* **Causa Raíz:** El valor entero de `hop_depth` sólo se utiliza como una condición booleana (`hop_depth > 0`). El bucle subsiguiente itera sobre las entidades referenciadas en los chunks del primer nivel (`fused[:limit]`), pero no implementa recursión ni colas para continuar la búsqueda hacia capas más profundas si `hop_depth > 1`.
* **Severidad:** **MEDIA** (Funcionalidad limitada/incorrectamente documentada).

---

### 2. Redundancias y Código Sucio (Code Quality Issues)

* **Variable No Usada en Migraciones:**
  * **Archivo:** [db.py](file:///opt/mcps/memoria/src/memoria_mcp/db.py#L333)
  * **Código:** `created: list[str] = []` se inicializa al inicio de `init_schema()`, pero nunca se utiliza para registrar el resultado de las sentencias ejecutadas. Al final, se retorna un valor de tablas hardcodeado (`"tables": 6`).
* **Declaración Duplicada de Variable Global:**
  * **Archivo:** [auth.py](file:///opt/mcps/memoria/src/memoria_mcp/auth.py#L47)
  * **Código:** `_tokens_cache: Optional[dict[str, str]] = None` se declara en la línea 39 y vuelve a declararse exactamente igual en la línea 47.
* **Comentario Desactualizado de Herramientas:**
  * **Archivo:** [server.py](file:///opt/mcps/memoria/src/memoria_mcp/server.py#L60)
  * **Código:** El comentario dice `# ── Tools (13 kb-specific) ──`. Sin embargo, el archivo expone y registra **22 herramientas** en total.
* **Severidad:** **BAJA**.

---

### 3. Advertencias de Suite de Tests (Test Warnings)
* **Síntoma:** Al ejecutar la suite de pruebas mediante pytest, se obtienen advertencias de marcas desconocidas (`PytestUnknownMarkWarning: Unknown pytest.mark.db - is this a typo?`).
* **Causa Raíz:** En [test_wiki_db.py](file:///opt/mcps/memoria/tests/test_wiki_db.py#L9) se utiliza el decorador `@pytest.mark.db`, pero esta marca personalizada no ha sido registrada en el archivo `pyproject.toml` (sección `[tool.pytest.ini_options]`).
* **Severidad:** **BAJA**.

---

### 4. Robustez frente a Zona Horaria (Offset-Naive vs Offset-Aware)
* **Análisis:** A diferencia de `mcp-mop` (donde `mop_estado_actual` fallaba), en `mcp-memoria` el módulo de fechas solo se utiliza para serializar marcas de tiempo como strings ISO 8601 (ej. en `instance.py` y `wiki.py`). No se realizan operaciones de sustracción directa sobre objetos `datetime` planos de base de datos contra aware datetimes locales, por lo que este componente es **seguro** y está bien resguardado contra este tipo de fallas.

---

## Conclusiones y Recomendaciones de Corrección

1. **Refactorización de `hop_depth`:** Si el sistema requiere una verdadera navegación por el grafo de entidades de N saltos en la búsqueda semántica, se debe reescribir la expansión en `hybrid_search` para que sea recursiva o use una cola BFS que respete el valor numérico de `hop_depth`. De lo contrario, se sugiere documentar o renombrar el parámetro como un flag booleano.
2. **Remover Redundancias:** Limpiar las declaraciones duplicadas de `_tokens_cache` en `auth.py` y la variable `created` sin uso en `db.py`.
3. **Registrar marcas en pytest:** Agregar `markers = ["db"]` en `pyproject.toml` para silenciar las advertencias de pytest.
