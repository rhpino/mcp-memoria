#!/bin/bash
set -euo pipefail

# Crear una DB de test para restore (no rompe mcp_memoria)
sudo mysql -e "CREATE DATABASE IF NOT EXISTS mcp_memoria_restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Hacer restore desde el backup remoto
sshpass -f /tmp/.geo_key ssh -o StrictHostKeyChecking=accept-new cloudops@100.112.255.59 'cat /tmp/mcp-memoria-backup-test/mcp-memoria-backup-2026-07-02.sql' > /tmp/restore-input.sql

sudo mysql mcp_memoria_restore_test < /tmp/restore-input.sql

# Verificar
TABLES=$(sudo mysql mcp_memoria_restore_test -e "SHOW TABLES" | tail -n +2 | wc -l)
echo "Restored tables: $TABLES (expected 6)"
CHUNKS=$(sudo mysql mcp_memoria_restore_test -e "SELECT COUNT(*) FROM mm_entity_chunks;" | tail -1)
echo "Restored chunks: $CHUNKS (expected ~76)"

if [ "$TABLES" -ge 6 ] && [ "$CHUNKS" -ge 50 ]; then
    echo "RESTORE OK"
else
    echo "RESTORE FAIL"
fi

# Cleanup
sudo mysql -e "DROP DATABASE mcp_memoria_restore_test;"
