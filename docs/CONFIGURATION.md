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

## Reddit

Signaux communautaires ajoutés au prompt de veille (voir [ARCHITECTURE.md](ARCHITECTURE.md#signaux-communautaires-reddit)). Toutes ces variables sont lues à chaque appel.

| Variable | Défaut | Effet |
| --- | --- | --- |
| `REDDIT_ENABLED` | `false` | `true` : la veille (bouton et cron) lit les subreddits et ajoute les posts retenus au prompt. `false` : aucune requête vers Reddit, veille inchangée. `GET /reddit/preview` fonctionne dans les deux cas. |
| `REDDIT_SUBREDDITS` | `LocalLLaMA,ClaudeAI,OpenAI,ChatGPTCoding,MachineLearning,singularity` | Subreddits lus, séparés par des virgules (préfixe `r/` accepté, noms invalides ignorés). Tous sont lus en une seule requête. |
| `REDDIT_MAX_POSTS` | `15` | Nombre maximal de posts ajoutés au prompt, tous subreddits confondus (les mieux classés). |
| `REDDIT_MAX_POSTS_PER_SUB` | `5` | Nombre maximal de posts par subreddit, pour que les plus gros subreddits ne prennent pas toute la place. |
| `REDDIT_USER_AGENT` | `linux:veille-ia:1.0 (veille technique IA interne)` | User-Agent envoyé à Reddit. Garder un agent descriptif : un User-Agent de navigateur est davantage limité. |
| `REDDIT_TIMEOUT_SECONDS` | `10` | Délai de la requête Reddit. |

Pas d'identifiants : Reddit n'accorde pas d'application et refuse son API JSON sans compte (403). L'application lit donc le **flux RSS public** `https://www.reddit.com/r/A+B+C/top/.rss?t=day&limit=100`, en une requête pour tous les subreddits, car Reddit n'accepte qu'environ **une requête anonyme par minute** par adresse IP (au-delà : 429 ; l'application réessaie une fois si Reddit annonce une attente de 65 s au plus). Limites du RSS :

- pas de score ni de nombre de commentaires : le rang dans le top (trié par score par Reddit) en tient lieu ;
- pas de flair ni d'indicateurs épinglé / NSFW : les mèmes sont écartés par heuristique (mot-clé dans le titre, ou image / vidéo au titre de moins de 5 mots) ;
- 100 posts au plus pour l'ensemble des subreddits : les petits subreddits (ChatGPTCoding, MachineLearning) peuvent être absents un jour où les gros sont très actifs.

## Mail (SMTP)

Envoi de la newsletter par mail (`POST /reports/{id}/send`, bouton « Envoyer par mail », envoi automatique du cron). Sans ces variables, l'application fonctionne normalement : le bouton est grisé et l'envoi renvoie 503. Toutes sont lues à chaque appel.

| Variable | Défaut | Effet |
| --- | --- | --- |
| `SMTP_HOST` | *(vide)* | Serveur SMTP (ex. `smtp.office365.com`, `smtp.gmail.com`, relais interne). Obligatoire. |
| `SMTP_PORT` | `587` | Port. `465` active le SSL implicite (voir `SMTP_SSL`). |
| `SMTP_USER` | *(vide)* | Identifiant d'authentification. Vide : pas d'authentification (relais interne). |
| `SMTP_PASSWORD` | *(vide)* | Mot de passe (ou mot de passe d'application). Obligatoire si `SMTP_USER` est défini. Jamais renvoyé par l'API ni écrit dans les logs. |
| `SMTP_STARTTLS` | `true` | Passe la connexion en TLS (`STARTTLS`) avant l'authentification. Ignoré en SSL implicite. |
| `SMTP_SSL` | `true` si `SMTP_PORT=465`, sinon `false` | SSL implicite (`SMTP_SSL`) dès la connexion. |
| `SMTP_TIMEOUT_SECONDS` | `30` | Délai de connexion et d'échange avec le serveur. |
| `MAIL_FROM` | valeur de `SMTP_USER` | Expéditeur, avec ou sans nom affiché (`Veille IA <veille@april.fr>`). Obligatoire si `SMTP_USER` est vide. |
| `MAIL_TO` | *(vide)* | Destinataires, séparés par des virgules (doublons et adresses invalides ignorés). Obligatoire. |
| `MAIL_AUTO_SEND` | `false` | `true` : `POST /cron/daily` envoie la newsletter du jour si elle ne l'a pas encore été. |

Microsoft 365 et Gmail exigent en général un mot de passe d'application (ou l'activation de l'authentification SMTP) pour un compte avec double authentification.

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

# SMTP_HOST=smtp.office365.com
# SMTP_USER=veille@april.fr
# SMTP_PASSWORD=…
# MAIL_FROM=Veille IA <veille@april.fr>
# MAIL_TO=equipe-stti@april.fr
# MAIL_AUTO_SEND=true

# REDDIT_ENABLED=true
# REDDIT_SUBREDDITS=LocalLLaMA,ClaudeAI,OpenAI

API_TOKEN=change-me
VITE_API_TOKEN=change-me
ALLOWED_ORIGINS=http://localhost:5173
```
