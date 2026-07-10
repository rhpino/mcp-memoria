#!/bin/bash
# backup-memoria.sh — backup diario MariaDB + vectors.db + config a geo + tars.
# Usa IPs Tailscale directamente (hostname no resuelve desde secops).
set -euo pipefail

# SECURITY (H2 audit 2026-07-02): umask 0077 — archivos solo legibles por root.
# Antes: 0022 → archivos 0644 → cualquier user local podía cat /tmp/mcp-memoria-*.sql
# SECURITY (H3 audit 2026-07-02): MYSQL_PWD env var, no --password flag en CLI
#   (que aparece en `ps aux` visible a todos los users locales).
# SECURITY (H3): backup directo a /var/backups/mcp-memoria/ (no /tmp).
#   Evita symlink attack en /tmp (cualquier user podría pre-crear
#   /tmp/mcp-memoria-XYZ.tar.gz → archivo sensible del sistema).
umask 0077

DATE=$(date +%Y-%m-%d)
STAMP=$(date +%Y%m%d-%H%M%S)
DEST=/var/backups/mcp-memoria
LOCAL_TARBALL="/var/backups/mcp-memoria/.tmp-${STAMP}.tar.gz"
GEO_HOST="cloudops@100.112.255.59"   # vps-geo-noc Tailscale
TARS_HOST="cloudops@100.77.242.85"   # vps-canada Tailscale

mkdir -p "$DEST"
chmod 700 "$DEST"

# 1. Dump MariaDB mcp_memoria. Load credentials from /etc/mcp-memoria/db.env (640 root:mcps).
if [ -f /etc/mcp-memoria/db.env ]; then
    set -a; . /etc/mcp-memoria/db.env; set +a
else
    echo "ERROR: /etc/mcp-memoria/db.env not found. Run Stage 5 setup first." >&2
    exit 1
fi
mariadb-dump --user=mcp_memoria \
    --single-transaction --routines --triggers \
    mcp_memoria > "$DEST/.tmp-${STAMP}.sql"
unset MYSQL_PWD

# 2. Tarball con SQL dump (a /var/backups/mcp-memoria/ con 0077 umask → 0600 perms)
cd "$DEST"
tar -czf "$LOCAL_TARBALL" ".tmp-${STAMP}.sql"
rm -f "$DEST/.tmp-${STAMP}.sql"

# 3. Push a geo (Tailscale IP directa)
rsync -az -e "ssh -o StrictHostKeyChecking=accept-new" \
    "$LOCAL_TARBALL" "${GEO_HOST}:${DEST}/${DATE}.tar.gz"

# 4. Push a tars (Tailscale IP directa)
rsync -az -e "ssh -o StrictHostKeyChecking=accept-new" \
    "$LOCAL_TARBALL" "${TARS_HOST}:${DEST}/${DATE}.tar.gz"

# 5. Cleanup local
rm -f "$LOCAL_TARBALL"

echo "[mcp-memoria backup ${DATE}] geo + tars done"