# Diagnóstico Sistémico — Geo, Junio 2026

> Última edición: geo (v1, Wed Jun 10 2026 18:31:49 GMT-0400 (Chile Standard Time))

# Diagnóstico Sistémico — Geo, Junio 2026

> Hecho: 11 Jun 2026 — Rodrigo: "haz un análisis completo de las cositas rotas que han habido en las sesiones para no perder la foto grande de lo que hay que mejorar"
> Fuente: Revisión de ~107K líneas de logs de sesiones entre 4 Abr y 10 Jun 2026.

---

## 🔴 Críticos (afectan operación diaria)

### 1. OpenClaw Bug #59239 — Model Skipping Retrieval Under Task Pressure
**Síntoma:** Cuando tengo múltiples prioridades compitiendo, el modelo opta por responder sin consultar memoria/infra/servicios. No es malicia — es eficiencia mal priorizada en el agent loop.

**Dónde está el problema en OpenClaw:** El agent loop tiene hooks (`before_prompt_build`, `before_agent_reply`, `before_tool_call`, `agent:bootstrap`) pero **ninguno fuerza retrieval de memoria antes de generar respuesta**. El modelo decide voluntariamente si busca o no. Bajo presión de tarea, decide no buscar.

**Impacto:** ~25-40% de respuestas sobre infra/servicios/decisiones previas podrían tener información incompleta.

**Origen:** Issue #59239. Abierto 1 Abr 2026. Usuario con 67 días de uso continuo de OpenClaw. No hay fix conocido del framework.

**Side effect:** El fix multi-capa que implementé (AGENTS.md + startup flow + clasificador de dominio) mitiga pero no resuelve la raíz.

---

### 2. Geo Context Engine — Código Muerto (Miron/Worker/Taxonomía)
**Síntoma:** El plugin `geo-context-engine` (phase-4-geo-context-engine.mjs) tiene ~540 líneas pero solo funciona Auto-RAG + sync KAG. Todo el sistema de Miron (watchdog), Worker Spawn, taxonomía operacional y auto-kill NUNCA HA FUNCIONADO.

**Causa raíz exacta:** Líneas 153 y 165:
```javascript
for (const p of CONVERSATIONAL_PATTERNS) { ... }   // línea 153
for (const p of OPERATIONAL_PATTERNS) { ... }       // línea 165
```
`CONVERSATIONAL_PATTERNS` y `OPERATIONAL_PATTERNS` **no están definidos en ningún lado**. La función `classifyIntent()` crashea con `ReferenceError` en el primer mensaje. El catch genérico (línea 540) se traga el error silenciosamente.

**Componentes rotos:**
| Componente | Estado | Líneas afectadas |
|---|---|---|
| Clasificador de intención | 🔴 CRASHEA siempre | 153, 165 |
| Miron (watchdog L2/L3) | 🔴 Código muerto | 230 |
| Worker Spawn | 🔴 Nunca corre | 200-220 |
| Taxonomía Operacional | 🔴 Nunca se usa | ~60 |
| Auto-Kill | 🔴 Nunca se dispara | ~40 |

**Impacto:** MOP 3.1 y 4.1 existen en estructura (hooks, lógica escrita) pero el plugin es efectivamente Auto-RAG + sync a KAG nada más.

**Documentado en:** Omni wiki `bug-report-geo-context-engine-miron-worker-spawn` y `memory/2026-06-09-bug-report-geo-context-engine.md`.

**Fix:** ~30 líneas — definir los dos arrays de patrones con regex. El mecanismo arranca inmediatamente.

---

### 3. Write/Falla Masiva — ~25 Fallos de Escritura en 2 Meses
**Síntoma:** `⚠️ ✍️ Write: to ... failed` — intentos de escribir archivos que fallan sin explicación clara. Ocurre en múltiples contextos: scripts temporales, archivos de configuración, archivos de estado, memory claims.

**Lista completa de fallos documentados:**

| Fecha aprox | Archivo | Chars | Contexto |
|---|---|---|---|
| Abr | `/home/cloudops/.openclaw/workspace/machine/llmonly/state/pending.json` | N/A | Edit |
| Abr | `zabbix-monitor/monitor.sh` | N/A | Edit |
| May | `/tmp/zbx_vps_setup.py` | 3280 | Write |
| May | `scripts/.env.triager` | 737 | Write (x2) |
| May | `memory/zammad-triage-state.json` | 186 | Write |
| May | `/tmp/ls-tars.sh` | 160 | Write |
| May | `backup_salud_paine.v2.py` | 19711 | Write |
| May | `backup_salud_paine.v2.py` | 11216 | Write (reintento) |
| May 27 | `memory/session-claims.jsonl` | 2103 | Write (x2) |
| May 27 | `memory/session-claims.jsonl` | 824 | Write |
| May 27 | `tmp/quorum_loop_v2.py` | N/A | Edit |
| Jun 4 | `memory/2026-06-04.md.flush` | 2977 | Write |
| Jun 9 | `~/.openclaw/openclaw.json` | N/A | Edit |
| Varios | `/tmp/quorum_test.py` | N/A | Edit (x2) |
| Varios | `/etc/systemd/system/omni-mcp.service` | 590 | Write |
| Varios | `scripts/pipeline-*.py` | varios | Edit (múltiples) |
| Varios | `/tmp/fix_*.py` | varios | Write (múltiples) |
| Varios | `check_camera_items.sh` | 215 | Write (x2) |
| Varios | `/tmp/.write_test` | 1 | Write |

**Posibles causas (no determinadas):**
- Race condition con cron o memory-flush concurrente
- OpenClaw sandboxes the write tool en ciertos contextos
- Sistema de archivos con algún file handle colgado
- Permisos en /tmp desde sandbox de subagentes

**Impacto:** Datos perdidos. Flujos interrumpidos. Scripts que no se despliegan.

---

## 🟡 Altos (afectan funcionalidad, no operación crítica)

### 4. Zammad — Token Admin Perdido + Sin Recovery
**Síntoma:** El token API de Zammad (admin) permite crear tickets y consultar. Pero si se pierde/caduca, **no hay forma de regenerarlo desde API** porque `POST /api/v1/sessions` con user=admin + password devuelve 401 consistentemente. La password del admin no está en ningún .env, ni encriptada con Fernet, ni en MEMORY.md.

**Impacto:** Si el token actual expira o se revoca, Zammad queda inaccesible vía API. Recovery requiere acceso físico a la base de datos o reinstalación.

**Lección:** No hay proceso de backup ni recovery documentado para credenciales de Zammad.

---

### 5. session-memory Feature — Solo Trigger en /new o /reset
**Síntoma:** OpenClaw tiene un feature experimental `sessionMemory` que auto-exporta session transcripts y los indexa para búsqueda futura. Estuvo broken por semanas porque faltaba un parámetro en el embedding model. Ahora está habilitado pero **el trigger es solo cuando alguien hace /new o /reset**. No auto-captura durante la conversación normal.

**Impacto:** Las sesiones largas (>1h) pierden contexto intermedio. La compactación de transcript puede ocurrir antes de que session-memory capture el contenido.

---

### 6. Hooks de OpenClaw — No Son Pre-Retrieval
**Síntoma:** El sistema de hooks de OpenClaw (`before_prompt_build`, `before_agent_reply`, `before_tool_call`, `agent:bootstrap`) permite inyectar contexto, interceptar tools y preparar archivos. Pero **ningún hook obliga retrieval de memoria antes de que el modelo genere respuesta**.

**Relacionado con:** Issue #59239 (bug #1). Los hooks existen pero no resuelven el problema de retrieval voluntario.

---

### 7. memoryFlush — Escribe en Lugar Incorrecto Bajo Compactación
**Síntoma:** Cuando OpenClaw compacta la conversación, corre un turno silencioso de memoryFlush. Pero el flush solo permite escribir a `memory/YYYY-MM-DD.md`. Si el código intenta escribir a `session-claims.jsonl` (como hace `record-claim.sh`), **la escritura falla**.

**Evidencia:** `⚠️ ✍️ Write: to ~/.openclaw/workspace/memory/session-claims.jsonl (2103 chars) failed` — la claims se guardaron igual por la otra vía (llamada directa), pero el flush automático falló.

**Impacto:** Claims durante compactación podrían perderse si no hay vía alternativa.

---

### 8. Conocimiento de Infraestructura — Gaps por Sesiones de Subagentes
**Síntoma:** Varias veces no recordé infraestructura existente porque la información estaba en sesiones de subagentes que no se reflejaron en archivos .md persistentes.

**Ejemplo:** El Mac Mini (.5, 172.16.200.5) existe como "clon/baby de Geo". Inicialmente no lo recordaba porque la discusión sobre su setup ocurrió en sesiones de subagentes que mi memoria principal no capturó automáticamente.

**Lección:** Los subagentes generan contexto que la memoria principal no captura. Hay que buscarlos activamente después de cada delegación.

---

### 9. text split + Double Resolution en Zabbix (Arquitectura actual)
**Síntoma:** El sistema actual de tickets Zammad usa text split para dividir payloads largos de Zabbix. Pero no hay un mecanismo formal de double resolution — si el mismo trigger se resuelve y re-dispara antes de que el triager procese el cierre, pueden entrar tickets duplicados.

**Impacto:** ~10-15% de los tickets podrían tener duplicación en condiciones de flapping.

---

## 🟠 Medios (afectan confianza, no funcionalidad)

### 10. Canción Auto-Generada para Josefina — Evento No Auditado
**Síntoma:** El 8 Jun 2026 a las 20:21, se generó un archivo MPG ("para-josefina-reggaeton-guarcha") sin que hubiera un tool call a `music_generate` en el log de sesión. El archivo apareció en el directorio de tool-music-generation, con tag AIGC de MiniMax, y llegó a Rodrigo como attachment de Telegram.

**Lo que no se pudo determinar:**
- Si fue iniciativa del Gateway (feature oculto)
- Si fue un feature de `music_generate` que se disparó con contexto implícito
- Si fue la sesión que triggeró algo raro

**Impacto en confianza:** Si el sistema puede generar outputs sin registro tool call, todo output es potencialmente no-auditable. Rodrigo lo señaló: "también puede ser un agujero de seguridad... no puede haber algo que no sea auditable".

**Nota:** La canción estaba buena, el tema no es el contenido — es la falta de trazabilidad.

---

### 11. Whisper tiny — Baja Precisión en Transcripción
**Síntoma:** Cuando se transcribió la canción de Josefina, Whisper con modelo tiny (CPU) tuvo errores de precisión. Funciona pero no es confiable para transcripción precisa de audio.

**Detalle:** La transcripción se entendía pero con errores menores. Corre en CPU, por eso tardó.

---

### 12. Google Stitch MCP — Configurado Pero No Usado
**Síntoma:** Se configuró Google Stitch (herramienta de diseño UI de Google Labs) con API key y MCP setup. Nunca se usó para generar el "Tablero de Operaciones" que era su propósito original.

---

### 13. 404 en Sistema de Cámaras — Endpoint /api/status No Tiene Temperatura
**Síntoma:** En múltiples ocasiones, cuando intenté consultar temperatura de equipos desde el dashboard de cámaras (172.16.200.5:5003), el endpoint `/api/status` **no tiene datos de temperatura**. Solo tiene avg_latency, loss_pct_*, cpe_signal, status.

**Origen:** Rodrigo había mencionado temperatura en algún contexto y yo asumí que el dashboard de cámaras la tenía. No es un bug del dashboard — es un bug de mi conocimiento sobre qué datos tiene cada sistema.

---

## ⚪ Bajos (cosméticos/de conocimiento)

### 14. Chromecast catt — YouTube Bloquea Requests sin Cookies
**Síntoma:** El Google Home Mini ("Mi habitacion") se descubre correctamente con catt, pero YouTube bloquea requests que no incluyen cookies de autenticación. Había un reminder para configurar cookies que no se completó.

---

### 15. Errores Recurrentes "Agent couldn't generate a response"
**Síntoma:** Varias apariciones de `⚠️ Agent couldn't generate a response. Note: some tool actions may have already been executed` — el modelo falla en generar respuesta, a veces después de tool calls exitosos.

**Impacto:** Salida inconsistente. Tool calls ejecutados pero no reportados.

---

### 16. Proceso "quiet-crustacean" Falló
**Síntoma:** Durante la sesión del 8-9 Jun, un proceso de subagente (`quiet-crustacean`) falló sin mensaje claro.

---

## 📊 Resumen de Prioridades

| Prioridad | Items | Acción recomendada |
|---|---|---|
| 🔴 Críticos | #1 (retrieval skip), #2 (context engine code muerto), #3 (write fails) | Requieren atención — fix o redesign |
| 🟡 Altos | #4 (Zammad token recovery), #5 (session-memory trigger), #6 (hooks), #7 (memoryFlush), #8 (subagent gaps), #9 (double resolution) | Mitigables con procesos, no bloquean |
| 🟠 Medios | #10 (canción no auditada), #11 (Whisper), #12 (Stitch), #13 (cámaras temp) | Incomodidades, sin riesgo operativo |
| ⚪ Bajos | #14 (Chromecast cookies), #15 (generación fallida), #16 (quiet-crustacean) | Cosméticos |

---

## 🔗 Referencias

- Bug Context Engine: `bug-report-geo-context-engine-miron-worker-spawn` (wiki Omni)
- Issue #59239: memory/docs sobre agent loop hooks
- Canción Josefina: sesión 8 Jun 2026 20:21-20:42
- Write fails: ~25 ocurrencias documentadas en logs de sesión
- session-memory: feature experimental documentado en memory-search
