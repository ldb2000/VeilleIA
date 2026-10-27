#!/bin/sh
# Tâche planifiée DSM (utilisateur root) : appelle une route cron du backend VeilleIA depuis
# son conteneur, sans passer par Cloudflare (pas de limite des 125 s).
# Usage: sh /volume1/services/veilleIA/nas-cron.sh /cron/daily | /cron/copilot-weekly
# Journal : /volume1/services/veilleIA/data/cron.log

ROUTE="${1:?route attendue, ex. /cron/daily}"
DOCKER="${DOCKER:-/usr/local/bin/docker}"
LOG="$(dirname "$0")/data/cron.log"

{
    echo "$(date '+%Y-%m-%d %H:%M:%S') POST $ROUTE"
    $DOCKER exec veilleia-backend python -c '
import sys, urllib.request, urllib.error
request = urllib.request.Request("http://localhost:8000" + sys.argv[1], method="POST")
try:
    with urllib.request.urlopen(request, timeout=900) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode())
    sys.exit(1)
' "$ROUTE"
    STATUS=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') fin (code $STATUS)"
} >> "$LOG" 2>&1

exit $STATUS
