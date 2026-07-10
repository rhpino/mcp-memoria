#!/usr/bin/env node
/**
 * Bibliotecario — mini agente de Omni-MCP
 * Responsabilidades:
 *   1. Compactar conflictos wiki: merge semántico vía LLM
 *   2. Archivar: escribir merged + registro en sync_notifications
 *   3. Notificar: deja registro para que nodos clientes tiren pull
 *
 * Corre como cron en el nodo activo (GCP). Modo sombra = watch + no compacta.
 */

const mysql = require('mysql2/promise');

// Config — leer de env o defaults
const DB_HOST = process.env.BIBLIOTECA_DB_HOST || '127.0.0.1';
const DB_PORT = process.env.BIBLIOTECA_DB_PORT || 3307;
const DB_USER = process.env.BIBLIOTECA_DB_USER || 'mcp_user';
const DB_PASS = process.env.BIBLIOTECA_DB_PASS || 'mcp_password';
const DB_NAME = process.env.BIBLIOTECA_DB_NAME || 'llm_memory';
const BIBLIOTECA_MODE = process.env.BIBLIOTECA_MODE || 'shadown'; // 'active' o 'shadown'
const BIBLIOTECA_SIGNATURE = process.env.BIBLIOTECA_SIGNATURE || 'bibliotecario';
const MINIMAX_ENABLED = process.env.MINIMAX_ENABLED === 'true';

// MiniMax M3 para merge — key de proyecto-geo/.env
const MINIMAX_API = process.env.MINIMAX_API || 'https://api.minimaxi.com/v1/text/chatcompletion_v2';
const MINIMAX_KEY = process.env.MINIMAX_KEY || '';
const MINIMAX_MODEL = process.env.MINIMAX_MODEL || 'MiniMax-M3';
// Fallback a Gemini si MiniMax no disponible
const GEMINI_API = process.env.GEMINI_API || 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent';
const GEMINI_KEY = process.env.GEMINI_KEY || '';

async function getDb() {
  return mysql.createPool({
    host: DB_HOST, port: DB_PORT, user: DB_USER, password: DB_PASS, database: DB_NAME,
    waitForConnections: true, connectionLimit: 5, queueLimit: 0,
  });
}

/** Llama a MiniMax M3 o Gemini para merge semántico */
async function mergeContent(contentA, contentB, slug) {
  const prompt = `Eres un bibliotecario que consolida información de dos fuentes sobre el mismo tema "${slug}".
Ambas describen información relacionada pero desde perspectivas o fuentes diferentes.
Tu tarea: combinarlas en un solo texto coherente, conservando TODA la información de ambas.
No pierdas detalles. No resumas ni recortes — fusiona.

## Fuente A:
${contentA}

## Fuente B:
${contentB}

## Resultado consolidado (texto completo fusionado):`;

  // Intentar MiniMax primero
  if (MINIMAX_ENABLED && MINIMAX_KEY) {
    try {
      const res = await fetch(MINIMAX_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${MINIMAX_KEY}` },
        body: JSON.stringify({
          model: MINIMAX_MODEL,
          messages: [{ role: 'user', content: prompt }],
          max_tokens: 8192, temperature: 0.3,
        }),
      });
      const data = await res.json();
      if (data.choices?.[0]?.message?.content) return data.choices[0].message.content;
      console.error(`[bibliotecario] MiniMax error: ${JSON.stringify(data).substring(0, 200)}`);
    } catch (e) { console.error(`[bibliotecario] MiniMax fetch fail: ${e.message}`); }
  }

  // Fallback Gemini
  if (GEMINI_KEY) {
    try {
      const res = await fetch(`${GEMINI_API}?key=${GEMINI_KEY}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ role: 'user', parts: [{ text: prompt }] }],
          generationConfig: { maxOutputTokens: 8192, temperature: 0.3 },
          safetySettings: [
            { category: 'HARM_CATEGORY_HARASSMENT', threshold: 'BLOCK_NONE' },
            { category: 'HARM_CATEGORY_HATE_SPEECH', threshold: 'BLOCK_NONE' },
            { category: 'HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold: 'BLOCK_NONE' },
            { category: 'HARM_CATEGORY_DANGEROUS_CONTENT', threshold: 'BLOCK_NONE' },
          ],
        }),
      });
      const data = await res.json();
      if (data.candidates?.[0]?.content?.parts?.[0]?.text) return data.candidates[0].content.parts[0].text;
      console.error(`[bibliotecario] Gemini error: ${JSON.stringify(data).substring(0, 200)}`);
    } catch (e) { console.error(`[bibliotecario] Gemini fetch fail: ${e.message}`); }
  }

  return null; // no se pudo mergear
}

/** Inserta slug en sync_notifications y actualiza la cabeza del wiki */
async function saveMerged(db, slug, mergedContent, mergedVersion, sourceA, sourceB, agentSigA, agentSigB) {
  const conn = await db.getConnection();
  try {
    await conn.beginTransaction();

    // Escribir la versión mergeada
    await conn.execute(
      `INSERT INTO wiki_pages (slug, title, content, agent_signature, version, last_modified_by)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [slug, `Merged ${slug}`, mergedContent, BIBLIOTECA_SIGNATURE, mergedVersion, BIBLIOTECA_SIGNATURE]
    );

    // Asegurar el index
    try {
      // Reuse KAG indexing via server's HTTP endpoint
      await fetch(`http://127.0.0.1:3456/mcp/wiki_indexed`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug }), signal: AbortSignal.timeout(10000) }).catch(() => {});
    } catch(e) { console.error(`[bibliotecario] index falló: ${e.message}`); }

    // Registrar en sync_notifications
    await conn.execute(
      `INSERT INTO sync_notifications (slug, merged_version, merged_from, merged_by, archived_versions, notifications_sent)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [slug, mergedVersion, JSON.stringify({ sourceA: sourceA.substring(0, 100), sourceB: sourceB.substring(0, 100) }),
       BIBLIOTECA_SIGNATURE, JSON.stringify([agentSigA, agentSigB]), '[]']
    );

    await conn.commit();
    console.log(`[bibliotecario] ✅ ${slug} v${mergedVersion} mergeado y notificado`);
    return true;
  } catch (e) {
    await conn.rollback();
    console.error(`[bibliotecario] saveMerged fail: ${e.message}`);
    return false;
  } finally { conn.release(); }
}

/** Rutina principal del bibliotecario */
async function run() {
  const db = await getDb();
  try {
    if (BIBLIOTECA_MODE !== 'active') {
      console.log(`[bibliotecario] Modo sombra — solo check de salud`);
      // Modo sombra: verificar que el activo existe
      const [notifs] = await db.execute(
        `SELECT COUNT(*) AS c FROM sync_notifications WHERE created_at > NOW() - INTERVAL 1 HOUR`
      );
      if (notifs[0].c === 0) {
        console.log(`[bibliotecario] sombra: sin actividad en última hora`);
      } else {
        console.log(`[bibliotecario] sombra: ${notifs[0].c} notificaciones en última hora — todo ok`);
      }
      return;
    }

    // Modo activo: buscar conflictos pending
    const [conflicts] = await db.execute(
      `SELECT id, entity_type, entity_id, gcp_content, node_content, gcp_node, node_node
       FROM conflict_queue WHERE entity_type = 'wiki_pages' AND resolution = 'pending'
       ORDER BY created_at ASC LIMIT 5`
    );

    if (conflicts.length === 0) {
      console.log(`[bibliotecario] Sin conflictos pendientes — todo en orden`);
      return;
    }

    console.log(`[bibliotecario] ${conflicts.length} conflictos por compactar`);

    for (const c of conflicts) {
      console.log(`[bibliotecario] Procesando ${c.entity_type}/${c.entity_id} (conflicto #${c.id})`);

      // Identificar cuál contenido es GCP y cuál nodo
      const contentA = c.gcp_content || '';
      const contentB = c.node_content || '';
      if (!contentA || !contentB) {
        console.log(`[bibliotecario] ⏭ conflicto #${c.id}: contenido vacío, marcando gcp_wins`);
        await db.execute(
          `UPDATE conflict_queue SET resolution = 'gcp_wins', resolved_by = ?, resolved_at = NOW(), notes = 'Contenido vacío en un lado' WHERE id = ?`,
          [BIBLIOTECA_SIGNATURE, c.id]
        );
        continue;
      }

      // Merge via LLM
      const merged = await mergeContent(contentA, contentB, c.entity_id);
      if (!merged) {
        console.log(`[bibliotecario] ⏭ conflicto #${c.id}: merge falló, dejando pendiente`);
        continue;
      }

      // Leer la versión actual máxima
      const [existing] = await db.execute(
        `SELECT MAX(version) AS max_v FROM wiki_pages WHERE slug = ?`, [c.entity_id]
      );
      const mergedVersion = (existing[0]?.max_v || 0) + 1;

      // Guardar merged
      const ok = await saveMerged(db, c.entity_id, merged, mergedVersion, contentA, contentB, c.gcp_node, c.node_node);
      if (!ok) {
        console.log(`[bibliotecario] ⏭ conflicto #${c.id}: save falló`);
        continue;
      }

      // Marcar conflicto como resuelto
      await db.execute(
        `UPDATE conflict_queue SET resolution = 'manual_merge', resolved_by = ?, resolved_at = NOW(), notes = ? WHERE id = ?`,
        [BIBLIOTECA_SIGNATURE, `Merged v${mergedVersion} from ${c.gcp_node} + ${c.node_node}`, c.id]
      );
      console.log(`[bibliotecario] ✅ conflicto #${c.id} resuelto → ${c.entity_id} v${mergedVersion}`);
    }
  } catch (e) {
    console.error(`[bibliotecario] error: ${e.message}`);
  } finally {
    await db.end();
  }
}

// CLI: `node bibliotecario.js [active|shadown]`
const mode = process.argv[2];
if (mode === 'active' || mode === 'shadown') {
  process.env.BIBLIOTECA_MODE = mode;
}

run().then(() => { process.exit(0); }).catch(e => { console.error(e); process.exit(1); });
