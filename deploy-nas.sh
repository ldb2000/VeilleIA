#!/bin/bash
# Déploie VeilleIA sur le NAS (/volume1/services/veilleIA) puis reconstruit les conteneurs.
# Le code local (commité ou non) est envoyé tel quel, sans passer par GitHub.
# Usage: ./deploy-nas.sh
# Les fichiers propres au NAS (backend/.env, data/, codex/) ne sont jamais écrasés.

set -e

NAS_SSH="ssh -p 2222"
NAS_HOST="laurent@diskstation"
NAS_DIR="/volume1/services/veilleIA"
COMPOSE="sudo /usr/local/bin/docker compose -f /volume1/services/docker-compose.yml"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# tar via SSH (rsync sur Synology exige le service rsync DSM). Envoie les fichiers suivis
# et non ignorés par git ; les fichiers supprimés localement restent sur le NAS.
cd "$ROOT_DIR"
git ls-files -co --exclude-standard -z \
    | grep -zvE '^(\.scion|\.vcm)/' \
    | COPYFILE_DISABLE=1 tar --no-xattrs -czf - --null -T - \
    | $NAS_SSH "$NAS_HOST" "mkdir -p $NAS_DIR && tar -xzf - -C $NAS_DIR"

$NAS_SSH "$NAS_HOST" "$COMPOSE up -d --build veilleia-backend veilleia-frontend"

echo "Déployé : https://veilleia-app.deberti.fr"
