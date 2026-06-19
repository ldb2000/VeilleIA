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
        echo -e "${RED}[!] ATTENTION : Vous devez configurer votre GEMINI_API_KEY dans backend/.env${NC}"
    else
        echo -e "${RED}[X] Erreur : .env.example introuvable. Impossible de configurer l'environnement.${NC}"
        exit 1
    fi
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
if [ ! -d "venv" ]; then
    echo -e "${BLUE}[*] Création de l'environnement virtuel...${NC}"
    python3 -m venv venv
fi

source venv/bin/activate
echo -e "${BLUE}[*] Installation/Mise à jour des dépendances Python...${NC}"
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
