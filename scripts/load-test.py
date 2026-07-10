"""load-test.py — Tests de carga concurrentes contra mcp-memoria."""
import asyncio
import os
import sys
import time

import httpx

TOKEN = os.environ.get("BEARER_TOKEN", "")
URL = "http://127.0.0.1:9092"


async def initialize(client):
    r = await client.post(
        f"{URL}/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json,text/event-stream",
            "Authorization": f"Bearer {TOKEN}",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "load-test", "version": "1.0"},
            },
        },
    )
    sid = r.headers.get("mcp-session-id")
    return sid


async def call_tool(client, sid, name, args, idx):
    r = await client.post(
        f"{URL}/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json,text/event-stream",
            "Authorization": f"Bearer {TOKEN}",
            "mcp-session-id": sid,
        },
        json={
            "jsonrpc": "2.0",
            "id": idx,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
    )
    return r.status_code, len(r.content), r.elapsed.total_seconds() * 1000


async def run_burst(client, sid, n, concurrent):
    sem = asyncio.Semaphore(concurrent)

    async def one(i):
        async with sem:
            return await call_tool(client, sid, "kag_buscar",
                                   {"query": f"test {i}", "limit": 5}, i)
    t0 = time.time()
    results = await asyncio.gather(*[one(i) for i in range(n)])
    elapsed = (time.time() - t0) * 1000
    return results, elapsed


async def main():
    if not TOKEN:
        print("ERROR: set BEARER_TOKEN env var")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        sid = await initialize(client)
        print(f"Session: {sid[:16]}...")

        for concurrent in [1, 5, 10]:
            for n in [10, 50]:
                results, elapsed = await run_burst(client, sid, n, concurrent)
                ok = sum(1 for s, _, _ in results if s == 200)
                avg_ms = sum(t for _, _, t in results) / len(results)
                p95 = sorted(t for _, _, t in results)[int(len(results) * 0.95)]
                print(
                    f"  N={n:3d} concurrent={concurrent:2d} → "
                    f"{ok}/{n} OK  avg={avg_ms:6.1f}ms  p95={p95:6.1f}ms  "
                    f"total={elapsed/1000:.2f}s"
                )


if __name__ == "__main__":
    asyncio.run(main())