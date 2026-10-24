#!/bin/bash

# Script de lancement pour AI Technical Watch (Veille IA)

# Couleurs pour le terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Lancement de AI Technical Watch ===${NC}\n"

# 1. Vérification du fichier .env
if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}[!] Le fichier backend/.env est manquant.${NC}"
    if [ -f ".env.example" ]; then
        echo -e "${BLUE}[*] Création de backend/.env à partir de .env.example...${NC}"
        cp .env.example backend/.env
        echo -e "${RED}[!] ATTENTION : vérifiez LLM_PROVIDER dans backend/.env (codex par défaut, ou OPENROUTER_API_KEY)${NC}"
    else
        echo -e "${RED}[X] Erreur : .env.example introuvable. Impossible de configurer l'environnement.${NC}"
        exit 1
    fi
fi

# Vérification du fournisseur LLM
LLM_PROVIDER_VALUE=$(grep -E '^LLM_PROVIDER=' backend/.env 2>/dev/null | tail -n 1 | cut -d '=' -f 2-)
LLM_PROVIDER_VALUE=${LLM_PROVIDER_VALUE:-codex}
if [ "$LLM_PROVIDER_VALUE" = "codex" ] && ! command -v codex >/dev/null 2>&1; then
    echo -e "${YELLOW}[!] Codex CLI introuvable : installez-le avec 'npm install -g @openai/codex' puis 'codex login'.${NC}"
fi

# Fonction de nettoyage à l'arrêt du script
cleanup() {
    echo -e "\n${BLUE}=== Arrêt des services... ===${NC}"
    # Tue tous les processus dans le groupe de processus actuel
    kill $(jobs -p) 2>/dev/null
    exit
}
trap cleanup SIGINT

# 2. Configuration du Backend
echo -e "${GREEN}[1/2] Configuration du Backend...${NC}"
cd backend

# Choix de l'interpréteur : python3.11 (version du projet) en priorité, sinon une version récente.
PYTHON_BIN=""
for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}[X] Aucun interpréteur Python 3 trouvé. Installez Python 3.11 (brew install python@3.11).${NC}"
    exit 1
fi
PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ "$PYTHON_VERSION" != "3.11" ]; then
    echo -e "${YELLOW}[!] Python 3.11 introuvable, utilisation de $PYTHON_BIN ($PYTHON_VERSION). Recommandé : brew install python@3.11${NC}"
fi

# Recrée le venv s'il a été construit avec une autre version de Python.
if [ -x "venv/bin/python" ]; then
    VENV_VERSION=$(venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
    if [ "$VENV_VERSION" != "$PYTHON_VERSION" ]; then
        echo -e "${YELLOW}[!] venv en Python ${VENV_VERSION:-inconnu}, recréation avec Python $PYTHON_VERSION...${NC}"
        rm -rf venv
    fi
fi

if [ ! -d "venv" ]; then
    echo -e "${BLUE}[*] Création de l'environnement virtuel (Python $PYTHON_VERSION)...${NC}"
    "$PYTHON_BIN" -m venv venv
fi

source venv/bin/activate
echo -e "${BLUE}[*] Installation/Mise à jour des dépendances Python...${NC}"
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

# Lancement du backend en arrière-plan
echo -e "${GREEN}[*] Démarrage du serveur FastAPI...${NC}"
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# 3. Configuration du Frontend
echo -e "${GREEN}[2/2] Configuration du Frontend...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    echo -e "${BLUE}[*] Installation des dépendances Node.js (cela peut prendre un moment)...${NC}"
    npm install --silent
fi

if [ -f "../backend/.env" ]; then
    BACKEND_VITE_API_TOKEN=$(grep -E '^VITE_API_TOKEN=' ../backend/.env | tail -n 1 | cut -d '=' -f 2-)
    BACKEND_API_TOKEN=$(grep -E '^API_TOKEN=' ../backend/.env | tail -n 1 | cut -d '=' -f 2-)

    if [ -n "$BACKEND_VITE_API_TOKEN" ]; then
        export VITE_API_TOKEN="$BACKEND_VITE_API_TOKEN"
    elif [ -n "$BACKEND_API_TOKEN" ]; then
        export VITE_API_TOKEN="$BACKEND_API_TOKEN"
    fi
fi

# Lancement du frontend au premier plan
echo -e "${GREEN}[*] Démarrage du serveur Vite (React)...${NC}"
echo -e "${YELLOW}Une fois lancé, accédez à : http://localhost:5173${NC}\n"
npm run dev
