#!/bin/bash
# Lifecycle wrapper for podman-compose with auto OAuth + token bootstrap.
# Usage: ./compose.sh {start|stop|restart|logs|status}

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$ROOT_DIR/backend/.env"
COMPOSE_FILE="$ROOT_DIR/podman-compose.yml"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${BLUE}[*]${NC} $1"; }
ok()   { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[X]${NC} $1"; }

# --- helpers ---

set_env_var() {
    local key="$1" value="$2"
    if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
        # macOS sed needs ''
        sed -i.bak -E "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

is_placeholder() {
    local v="$1"
    [[ -z "$v" || "$v" == your_* ]]
}

ensure_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "$ROOT_DIR/.env.example" ]; then
            log "Création de backend/.env depuis .env.example"
            cp "$ROOT_DIR/.env.example" "$ENV_FILE"
        else
            err "Pas de .env.example pour amorcer backend/.env"
            exit 1
        fi
    fi
}

bootstrap_api_token() {
    local current
    current=$(grep -E '^API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
    if is_placeholder "$current"; then
        local new_token
        new_token=$(openssl rand -hex 32)
        set_env_var "API_TOKEN" "$new_token"
        set_env_var "VITE_API_TOKEN" "$new_token"
        ok "API_TOKEN généré (frontend + backend synchronisés)"
        return
    fi
    # Force VITE_API_TOKEN to mirror API_TOKEN
    local vite_current
    vite_current=$(grep -E '^VITE_API_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
    if [ "$vite_current" != "$current" ]; then
        set_env_var "VITE_API_TOKEN" "$current"
        ok "VITE_API_TOKEN aligné sur API_TOKEN"
    fi
}

bootstrap_gemini_oauth() {
    local gemini_bin
    gemini_bin=$(command -v gemini || true)
    if [ -z "$gemini_bin" ]; then
        warn "Binaire 'gemini' introuvable sur l'hôte — extraction OAuth ignorée"
        warn "Renseigne GEMINI_API_KEY ou les GEMINI_OAUTH_* manuellement dans $ENV_FILE"
        return
    fi

    local resolved oauth2_path
    resolved=$(readlink -f "$gemini_bin" 2>/dev/null || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$gemini_bin")
    oauth2_path=$(find "$(dirname "$(dirname "$resolved")")" -name oauth2.js -path '*code_assist*' 2>/dev/null | head -1)

    if [ -z "$oauth2_path" ] || [ ! -f "$oauth2_path" ]; then
        warn "oauth2.js du gemini-cli introuvable — extraction OAuth ignorée"
        return
    fi

    local extracted_cid extracted_csec
    extracted_cid=$(grep -oE '[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com' "$oauth2_path" | head -1)
    extracted_csec=$(grep -oE 'GOCSPX-[A-Za-z0-9_-]+' "$oauth2_path" | head -1)

    if [ -z "$extracted_cid" ] || [ -z "$extracted_csec" ]; then
        warn "Impossible d'extraire client_id/secret depuis $oauth2_path"
        return
    fi

    set_env_var "GEMINI_OAUTH_CLIENT_ID" "$extracted_cid"
    set_env_var "GEMINI_OAUTH_CLIENT_SECRET" "$extracted_csec"
    ok "GEMINI_OAUTH_CLIENT_ID/SECRET extraits depuis $oauth2_path"
}

cmd_start() {
    ensure_env_file
    bootstrap_api_token
    bootstrap_gemini_oauth
    log "Démarrage des conteneurs (build si besoin)"
    podman-compose -f "$COMPOSE_FILE" up --build -d
    ok "Backend: http://localhost:8000  |  Frontend: http://localhost:5173"
    log "Logs: ./compose.sh logs   |  Stop: ./compose.sh stop"
}

cmd_stop() {
    log "Arrêt des conteneurs"
    podman-compose -f "$COMPOSE_FILE" down
    ok "Stoppé"
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_logs() {
    podman-compose -f "$COMPOSE_FILE" logs -f
}

cmd_status() {
    podman-compose -f "$COMPOSE_FILE" ps
}

case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    logs)    cmd_logs ;;
    status)  cmd_status ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|status}"
        exit 1
        ;;
esac
