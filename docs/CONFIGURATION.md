# Configuration

[← Sommaire](README.md)

Le backend lit ses variables dans l'environnement et dans `backend/.env` (chargé par `python-dotenv` au démarrage). Le modèle de ce fichier est `.env.example` à la racine ; `dev.sh` et `compose.sh` le copient s'il manque. Le frontend lit les variables `VITE_*` au moment du lancement de Vite.

Les valeurs sont lues **au démarrage** du backend, sauf mention « à chaque appel » : il faut alors seulement modifier `.env` puis relancer.

## Fournisseur LLM

| Variable | Défaut | Effet |
| --- | --- | --- |
| `LLM_PROVIDER` | `codex` | Fournisseur : `codex`, `openrouter` ou `gemini`. Lu à chaque appel. Une autre valeur provoque une erreur 500 explicite. |
| `LLM_TIMEOUT_SECONDS` | valeur de `GEMINI_TIMEOUT_SECONDS` (90) | Délai des appels courts : chat, résumé, détail, définition. |
| `LLM_REPORT_TIMEOUT_SECONDS` | max(`GEMINI_REPORT_TIMEOUT_SECONDS`, 600) → 600 | Délai de génération de la veille et de la note CODIR. |
| `CHAT_REPORT_CONTEXT_MAX_CHARS` | `24000` | Taille maximale du contenu de chaque rapport envoyé au chat. |

### Codex (`LLM_PROVIDER=codex`)

| Variable | Défaut | Effet |
| --- | --- | --- |
| `CODEX_BIN` | `codex` | Binaire Codex CLI (nom dans le PATH ou chemin absolu). |
| `CODEX_MODEL` | *(vide)* | Modèle passé avec `--model` ; vide = modèle par défaut de Codex. Lu à chaque appel. |
| `CODEX_REASONING_EFFORT` | *(vide)* | Passé en `-c model_reasoning_effort="…"` (ex. `low`, `medium`, `high`). Lu à chaque appel. |
| `CODEX_WEB_SEARCH` | `true` | Autorise la recherche web en direct pour la veille et le chat avec option web. `false` : la veille repose sur les connaissances du modèle. Lu à chaque appel. |

L'authentification Codex n'est pas gérée par l'application : elle vient de `codex login`, stockée dans `~/.codex` (ou `CODEX_HOME`, lu par Codex lui-même).

### OpenRouter (`LLM_PROVIDER=openrouter`)

| Variable | Défaut | Effet |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | *(vide)* | Clé d'API, obligatoire. Lue à chaque appel. |
| `OPENROUTER_MODEL` | `openrouter/auto` | Modèle OpenRouter (ex. `anthropic/…`, `openai/…`). Lu à chaque appel. |
| `OPENROUTER_WEB_SEARCH` | `false` | `true` : ajoute le plugin web payant d'OpenRouter pour la veille et le chat avec option web. Sans lui, pas d'accès internet. Lu à chaque appel. |
| `OPENROUTER_API_URL` | `https://openrouter.ai/api/v1/chat/completions` | Point d'accès (compatible OpenAI chat/completions). |

### Gemini (`LLM_PROVIDER=gemini`, historique)

| Variable | Défaut | Effet |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(vide)* | Clé d'API pour le SDK, utilisée si aucun `~/.gemini/oauth_creds.json` n'est présent. |
| `GOOGLE_API_KEY` | *(vide)* | Lue par le SDK Google ; l'application la retire temporairement lors d'une configuration OAuth pour éviter un conflit. |
| `GEMINI_OAUTH_CLIENT_ID`, `GEMINI_OAUTH_CLIENT_SECRET` | *(vides)* | Permettent de rafraîchir le jeton OAuth de `~/.gemini/oauth_creds.json` quand la CLI `gemini` n'est pas installée (conteneurs). `compose.sh` tente de les extraire de la CLI. |
| `GEMINI_MODEL` | `gemini-2.0-flash-lite` | Modèle du SDK ; mappé vers `auto-gemini-3` pour la CLI. |
| `GEMINI_TIMEOUT_SECONDS` | `90` | Ancien délai, sert de défaut à `LLM_TIMEOUT_SECONDS`. |
| `GEMINI_REPORT_TIMEOUT_SECONDS` | max(`GEMINI_TIMEOUT_SECONDS`, 300) | Ancien délai, entre dans le calcul de `LLM_REPORT_TIMEOUT_SECONDS`. |
| `GEMINI_CLI_MODEL` | alias de `GEMINI_MODEL` | Modèle passé à la CLI `gemini --model`. |

Le backend Gemini choisit la CLI si `~/.gemini/oauth_creds.json` (dans `HOME`) **et** le binaire `gemini` existent, sinon le SDK.

## Base de données

| Variable | Défaut | Effet |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./sql_app.db` | URL SQLAlchemy. Chemin relatif au dossier de lancement : `backend/sql_app.db` avec `dev.sh`, `/app/data/sql_app.db` en conteneur (`sqlite:///./data/sql_app.db`), `test_app.db` pendant les tests (`conftest.py`). |

## Sécurité et réseau

| Variable | Défaut | Effet |
| --- | --- | --- |
| `API_TOKEN` | *(vide)* | Vide : API ouverte. Défini : chaque requête doit envoyer `Authorization: Bearer <API_TOKEN>` (y compris le cron). |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | Origines CORS autorisées, séparées par des virgules. |

## Frontend (Vite)

| Variable | Défaut | Effet |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000` | URL du backend utilisée par `api.ts`. |
| `VITE_API_TOKEN` | *(vide)* | Si défini, `api.ts` ajoute `Authorization: Bearer …` à toutes les requêtes. Doit être égal à `API_TOKEN`. `dev.sh` le dérive de `backend/.env` (`VITE_API_TOKEN`, sinon `API_TOKEN`) ; `compose.sh` l'aligne sur `API_TOKEN`. |

Attention : une variable `VITE_*` est intégrée au code envoyé au navigateur. `API_TOKEN` protège donc l'API contre des appels extérieurs, pas contre quelqu'un qui a accès à l'interface.

## Exemple de `backend/.env`

```dotenv
LLM_PROVIDER=codex
CODEX_WEB_SEARCH=true
LLM_REPORT_TIMEOUT_SECONDS=600

# OPENROUTER_API_KEY=sk-or-…
# OPENROUTER_MODEL=openrouter/auto

API_TOKEN=change-me
VITE_API_TOKEN=change-me
ALLOWED_ORIGINS=http://localhost:5173
```
