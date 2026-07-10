# omni-mcp — Dónde vive

> **Privacidad:** omni-mcp es privado de Geo. NO es parte del MCP público. La info de este doc es referencia operativa del equipo, no para exposición vía MCP.

## Ubicación

- **Máquina:** vps-geo-noc (la misma donde corre OpenClaw)
- **Hostname Tailscale:** geo
- **Tailscale IP:** 100.112.255.59
- **IP pública:** 129.146.133.145
- **SSH:** `geo@100.112.255.59` (id_ed25519, sudo NOPASSWD)
- **Owner del proceso:** usuario `cloudops`
- **Path del server:** `/home/cloudops/omni-mcp/`
- **Working directory:** `/home/cloudops/omni-mcp/`

## Endpoint

- **Bind:** `127.0.0.1:3456` (local only)
- **UFW allow:** Tailscale + VPN-10.255.255.0/24
- **Acceso desde afuera:** vía Tailscale, NO vía IP pública directamente
- **Transporte:** HTTP/SSE (MCP standard)

## Cómo arranca

```bash
ssh geo@100.112.255.59
cd /home/cloudops/omni-mcp
node start.mjs
# o directo:
node server.js
```

**Systemd unit:** no confirmado (puede correr bajo nohup o screen). Verificar con `ps aux | grep omni` o `systemctl list-units | grep omni`.

## Status actual (julio 2026)

- Server v1.0.0
- Modo bibliotecario: activo (observación pasiva, ver `bibliotecario.log`)
- 584+ chunks indexados (per snapshot anterior de TOOLS.md)
- Sin cambios estructurales grandes desde la auditoría de junio 2026
- Owner operacional: Geo

## Quién opera

- **Operador primario:** Geo (vía SSH + herramientas MCP locales)
- **Otros operadores:** ninguno — privado
- **No es accesible** desde otros agentes MCP

## Privacidad (resumen)

- omni-mcp es **privado de Geo**, no se comparte con mop-mcp ni mcp-monitoreo ni mcp-memoria
- El MCP público `mcp-memoria` (en secops) NUNCA lee `/home/cloudops/omni-mcp/`
- El nombre "omni" **no aparece** en `/opt/mcps/README.md` (decisión Rodrigo 2026-07-01)
- Esta carpeta `docs/` es referencia técnica operativa, accesible solo por SSH al server
