# Informe de Auditoría de Código: `mcp-memoria`

**Fecha:** 2026-07-10
**Alcance:** Código fuente (`src/memoria_mcp/`, 18 módulos). No contenido de datos.
**Servidor:** FastAPI + FastMCP + MariaDB local (PyMySQL). 22 tools MCP.
**Tests:** 85 → 84 pass, 1 skip (7.17s).

---

## Resumen Ejecutivo

El servidor funciona y su suite de pruebas pasa, pero hay **tres problemas estructurales**:

1. **La búsqueda semántica usa un modelo ONNX local**, contradiciendo el constraint de RAM de CLAUDE.md (que manda Vertex AI `text-embedding-004`).
2. **`config.py` (validación de arranque) es código muerto** — el guard que protegería contra arranques con defaults peligrosos (`DB_USER=root`, `DB_PASS=""`) nunca ejecuta.
3. **El modelo de autorización es inconsistente** — `actor` se valida y se descarta, los writes de wiki/grafo no se auditan, y el bibliotecario bloquea el event loop con HTTP síncrono.

---

## CRÍTICO / ALTO

### C1. `embed.py` viola el constraint de hardware de CLAUDE.md
- **Archivo:** `src/memoria_mcp/embed.py:13,30`
- CLAUDE.md ordena explícitamente: *"Evitar fastembed/ONNX… Usar Vertex AI `text-embedding-004` con credenciales ADC"*. El código hace exactamente lo opuesto: carga un modelo ONNX local (`paraphrase-multilingual-MiniLM-L12-v2`) en RAM.
- El `.env` confirma `EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- En un server de ~11.6GB RAM (swap 3.8GB), la primera llamada a `kag_buscar`/`wiki_escribir` (vía chunker) carga el modelo ONNX sin warmup controlado → pico de memoria.
- **Severidad:** ALTA. Es la discrepancia más grave entre reglas declaradas e implementación.

### C2. `config.py` es código muerto — validación de arranque nunca ejecuta
- **Archivo:** `src/memoria_mcp/config.py` (148 líneas completas); `server.py:20`
- `load_dotenv()`, `validate_required_env()` y `require_env()` **nunca son importados** por `server.py` ni ningún módulo.
- El server arranca leyendo `os.environ.get()` con defaults. Si se corre manualmente (`python -m memoria_mcp.server`, como sugiere el propio CLAUDE.md), sin `EnvironmentFile=`, aplican los defaults peligrosos de `db.py:36-37`: **`DB_USER="root"`, `DB_PASS=""`**.
- En producción systemd sí carga `.env` (vía `EnvironmentFile=`), pero no hay fail-fast si falta una variable crítica.
- **Severidad:** ALTA (latent). Default root/sin-password sin guard.

### C3. `link_add` valida `actor` pero lo descarta
- **Archivo:** `src/memoria_mcp/tools/links.py:101-116`; `src/memoria_mcp/db.py:196-207`
- La tabla `mm_relations` **no tiene columna `actor`** y el `INSERT` no la guarda.
- El chequeo `actor not in ALLOWED_ACTORS` es teatro: valida un campo que después descarta.
- No hay auditoría de quién creó una relación. El `dict` retornado incluye `"actor"` pero la DB nunca lo registra.
- **Severidad:** ALTA (seguridad/auditoría).

### C4. LLM calls bloquean el event loop
- **Archivo:** `src/memoria_mcp/bibliotecario.py:50-104`
- `_call_minimax`/`_call_gemini` son `async def` pero usan `urllib.request.urlopen` **síncrono** (timeout 30s).
- Cada llamada bloquea el loop único durante hasta 30s, congelando **todos** los requests concurrentes.
- Debería usar `httpx` async o `asyncio.to_thread`.
- **Severidad:** ALTA (disponibilidad).

---

## MEDIO

### M1. Modelo de autorización inconsistente / all-or-nothing
- **Archivo:** `server.py`, `auth.py`, `tools/*.py`
- El middleware autentica *identidad* pero no *autorización*.
- `entity_añadir` y `wiki_escribir` aceptan `author`/`id` libres sin validación (vs `link_add` que sí valida `actor`).
- Cualquier cliente autenticado puede escribir wiki arbitraria con cualquier autor, o crear entidades con cualquier ID.
- `kag_buscar`/`kag_evaluar` no exponen `agent_signature` en el wrapper del tool (`server.py:127-137`), así que el log de búsqueda nunca registra quién buscó.
- **Severidad:** MEDIA.

### M2. `hop_depth` es mentira + N+1 queries
- **Archivo:** `src/memoria_mcp/search.py:251-288`
- `hop_depth` se usa solo como booleano (`hop_depth > 0`); siempre hace 1 salto sin importar el valor numérico.
- Por cada chunk en `fused[:limit]` × cada entidad referenciada lanza un `SELECT ... JSON_SEARCH ...` separado → hasta decenas de round-trips DB por búsqueda.
- **Severidad:** MEDIA.

### M3. `cosine_search` carga TODO a memoria + I/O desperdiciado
- **Archivo:** `src/memoria_mcp/search.py:66-76`
- `SELECT id,...,chunk_text,embedding FROM mm_entity_chunks WHERE embedding IS NOT NULL` trae **todos** los BLOBs de embedding **y** todo el `chunk_text` (MEDIUMTEXT) de cada fila, para devolver solo `limit`.
- Debería: puntuar embeddings primero, luego fetch de texto solo del top-N.
- **Severidad:** MEDIA (escala).

### M4. Pool de conexiones sin tope superior
- **Archivo:** `src/memoria_mcp/db.py:74-91`
- `acquire()` crea conexiones nuevas sin límite cuando el pool está vacío (`return self._make_conn()` sin chequear `POOL_MAX`).
- `POOL_MAX` solo acota el pool *idle*. Bajo concurrencia las conexiones se multiplican sin cota → agotamiento de conexiones MariaDB.
- **Severidad:** MEDIA (reliability).

### M5. `wiki_escribir_sync` reindex fire-and-forget con excepción swalloweada
- **Archivo:** `src/memoria_mcp/tools/wiki.py:320-335`
- `loop.create_task(_reindex())` sin `except`: si falla, excepción no manejada.
- El chunker hace `DELETE` + re-`INSERT` del `page_slug`: una búsqueda entre medio devuelve resultados vacíos/parciales (race window).
- El path async `wiki_escribir` sí está awaited correctamente.
- **Severidad:** MEDIA.

### M6. `tailscale whois` subprocess por request, sin caché
- **Archivo:** `src/memoria_mcp/auth.py:125-137,171-178`
- Cada request desde IP Tailscale spawnea `tailscale whois` (timeout 2s). Sin caché → overhead de process spawn por request.
- Además `except (FileNotFoundError, subprocess.TimeoutExpired, Exception)` — `Exception` ya cubre los otros; listarlo es engañoso (antipatrón repetido en `instance.py:37`).
- **Severidad:** MEDIA (performance).

---

## BAJO / CALIDAD

- **B1. `parsers.py` totalmente muerto** — nunca importado fuera de sí mismo; los tools consultan `mm_entity_chunks` directo. La dependencia `python-frontmatter` y ~173 líneas son peso muerto. Su `_detect_scope` referencia dirs (`kb/decisions`, `04-decisions`) que no existen en el WORKSPACE real.
- **B2. `grafo.shortest_path`/`entity_stats`** expuestos en `tools/grafo.py:39-46` pero NO registrados como tools MCP en `server.py` — código inalcanzable desde el protocolo.
- **B3. Comentario stale** (`server.py:59`): dice "13 kb-specific" tools; hay **22**.
- **B4. `_tokens_cache` declarado dos veces** (`auth.py:39` y `47`).
- **B5. `created: list[str] = []` sin uso** en `init_schema` (`db.py:333`); retorna `"tables": 6` hardcodeado.
- **B6. `docs/embed_local.py`** script suelto en el repo.
- **B7. `pytest.mark.db` no registrado** en `pyproject.toml` → `PytestUnknownMarkWarning` (test_wiki_db.py:9).
- **B8. Race de version wiki** (`wiki.py:286-290`): `MAX(version)+1` + INSERT — dos writes concurrentes al mismo slug colisionan en PK sin handler/retry (no corrompe, pero `IntegrityError` al cliente).
- **B9. `rrf_fuse` muta `SearchResult.score`** (`search.py:205`) de objetos compartidos con los rankings de entrada — side effect; frágil aunque no corrompe el cálculo RRF.
- **B10. f-string en DDL** (`db.py:315`): `f"CREATE DATABASE IF NOT EXISTS {DB_NAME}"` — DB_NAME viene de env (trusted), pero patrón de inyección a evitar.

---

## Recomendaciones priorizadas

1. **C2 → fix inmediato**: importar y llamar `config.load_dotenv()` + `validate_required_env()` en `server.py:main()`, o eliminar `config.py` si systemd basta. (30 min)
2. **C3 → fix inmediato**: agregar columna `actor` a `mm_relations` + persistirla en el INSERT, o eliminar la validación teatral. (1h)
3. **C4**: migrar `_call_minimax`/`_call_gemini` a `httpx.AsyncClient`. (1h)
4. **C1**: decisión arquitectónica — o cambiar a Vertex AI (cumple CLAUDE.md) o corregir CLAUDE.md para reflejar la realidad ONNX. Requiere alineación.
5. **B3/B4/B5/B7**: limpieza rápida de código muerto/stale. (15 min)
6. **M1-M6**: backlog de hardening (autorización por tool, BFS real, lazy-load de chunk_text, cap de pool, caché whois).

---

*Generado por auditoría estática independiente (opencode, 2026-07-10).*
