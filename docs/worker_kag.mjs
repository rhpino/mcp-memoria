import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import mysql from "mysql2/promise";

const pool = mysql.createPool({
  host: "localhost",
  user: "mcp_user",
  password: "mcp_password",
  database: "llm_memory",
});

async function getUnindexedSlugs() {
  const [rows] = await pool.execute(
    `SELECT DISTINCT w.slug
     FROM wiki_pages w
     LEFT JOIN entity_chunks c ON w.slug = c.page_slug
     WHERE c.page_slug IS NULL`
  );
  return rows.map(r => r.slug);
}

async function callKagIndex(slug) {
  const transport = new SSEClientTransport(new URL("http://localhost:3456/sse"));
  const client = new Client({ name: "worker-kag", version: "1.0.0" });
  await client.connect(transport);
  const result = await client.callTool({ name: "kag_index", arguments: { slug } });
  await client.close();
  return result.content[0].text;
}

async function run() {
  const ts = new Date().toISOString();
  console.log(`[KAG-Worker] ${ts} - Iniciando...`);

  const slugs = await getUnindexedSlugs();
  console.log(`[KAG-Worker] Paginas sin indexar: ${slugs.length}`);

  for (const slug of slugs) {
    const result = await callKagIndex(slug);
    console.log(`[KAG-Worker] ${slug} → ${result}`);
  }

  if (slugs.length === 0) {
    console.log(`[KAG-Worker] No hay paginas nuevas.`);
  }

  await pool.end();
  console.log(`[KAG-Worker] ${ts} - Terminado.`);
}

run().catch(e => { console.error(e); process.exit(1); });
