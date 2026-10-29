# Architecture

[← Sommaire](README.md)

## Vue d'ensemble

```text
                 navigateur (http://localhost:5173)
                 ┌──────────────────────────────────┐
                 │  Frontend React 19 + Vite        │
                 │  App.tsx (vues) · api.ts (axios) │
                 └───────────────┬──────────────────┘
                                 │ HTTP JSON (+ Bearer API_TOKEN si défini)
                 ┌───────────────▼──────────────────┐        cron externe
                 │  Backend FastAPI (uvicorn :8000) │◄────── POST /cron/daily
                 │  main.py · newsletter.py         │      Reddit (optionnel)
                 │  reddit.py · models · schemas    │─────► flux RSS www.reddit.com
                 └──────┬───────────────────┬───────┘
                        │ SQLAlchemy        │ generate_llm_content()
              ┌─────────▼────────┐   ┌──────▼───────────────────────────────┐
              │ SQLite           │   │ Fournisseur LLM (LLM_PROVIDER)       │
              │ sql_app.db       │   │ · codex   → `codex exec` (web live)  │
              │ (DATABASE_URL)   │   │ · openrouter → API chat/completions  │
              └──────────────────┘   │ · gemini  → CLI `gemini` ou SDK      │
                                     └──────────────────────────────────────┘
```

- Le **frontend** est une application monopage : tout l'état d'interface vit dans `App.tsx`, tous les appels réseau dans `api.ts`.
- Le **backend** est volontairement concentré dans `main.py` (endpoints, prompts, couche LLM, rendus PDF / DOCX). Deux modules autonomes, sans dépendance au reste de l'application, en sont sortis : le rendu de la newsletter (`newsletter.py`) et la lecture de Reddit (`reddit.py`).
- La **base** est un fichier SQLite ; le schéma est créé au démarrage, sans Alembic.
- Le **LLM** est appelé uniquement par le backend, via un point d'entrée unique (`generate_llm_content`).

## Rôle des fichiers

### `backend/app/`

| Fichier | Rôle |
| --- | --- |
| `main.py` | Application FastAPI : CORS, authentification (`verify_token`), migrations légères, couche LLM (Codex, OpenRouter, Gemini), prompts (`TECHNICAL_PROMPT`, `COPILOT_WATCH_PROMPT`, `CODIR_NOTE_PROMPT`, prompts inline de résumé / détail / définition / chat), extraction des news, rendu PDF (ReportLab) et DOCX (python-docx), les 28 endpoints. |
| `newsletter.py` | Rendu déterministe d'un rapport en corps d'email HTML compatible Gmail / Outlook (`render_newsletter`). Aucun appel LLM. |
| `mailer.py` | Envoi d'emails par SMTP (`send_html_email`, smtplib + `email.message`, multipart/alternative texte + HTML). Configuration lue dans l'environnement à chaque appel (`load_mail_config`) ; `describe_mail_config` ne renvoie jamais le mot de passe. |
| `m365_roadmap.py` | Lecture de l'API JSON publique du Microsoft 365 Roadmap pour la veille Microsoft Copilot (`collect_copilot_roadmap`, `filter_copilot_items`, `build_roadmap_prompt_section`). Ne lève jamais d'exception. |
| `reddit.py` | Signaux communautaires Reddit (optionnels, `REDDIT_ENABLED`) : lecture du top des subreddits par le flux RSS public, en une requête (`fetch_subreddit_posts`), filtrage (`filter_posts`), section ajoutée au prompt de veille (`build_reddit_prompt_section`). Ne lève jamais d'exception. |
| `models.py` | Modèles SQLAlchemy : `Report`, `ReportSummary`, `Note`, `ChatMessage`, `NewsItem`. |
| `schemas.py` | Schémas Pydantic des entrées / sorties d'API. |
| `database.py` | Moteur SQLAlchemy et `SessionLocal`, à partir de `DATABASE_URL`. |

### `frontend/src/`

| Fichier | Rôle |
| --- | --- |
| `main.tsx` | Point d'entrée React (monte `<App />`). |
| `App.tsx` | Toute l'interface : barre de navigation, Tableau de bord, Rapports (lecture structurée, résumé, sommaire, barre d'outils de sélection), News sauvegardées, Notes, Recherches (« Interroger la veille »). Contient aussi le parsing côté client des rapports (`parseReportContent`, `splitNewsField`…). |
| `api.ts` | Client axios : `API_URL` (lu depuis `VITE_API_URL`), en-tête `Authorization` ajouté si `VITE_API_TOKEN` est défini, une fonction par endpoint, types TypeScript. |
| `index.css` | Jetons de la charte APRIL (couleurs, rayons, ombres, police Poppins) et styles de base. |
| `App.css` | Styles des composants et des vues, points de rupture responsive (1280, 900, 560 px). |
| `assets/` | Ressources statiques. |

### Racine du dépôt

| Fichier | Rôle |
| --- | --- |
| `dev.sh` | Lancement local des deux services (voir [EXPLOITATION.md](EXPLOITATION.md)). |
| `compose.sh`, `podman-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` | Exécution en conteneurs. |
| `.env.example` | Modèle de `backend/.env`. |
| `conftest.py`, `test_*.py` | Tests pytest (voir [EXPLOITATION.md](EXPLOITATION.md#tests)). |
| `list_models.py`, `test_gemini_auth.py` | Scripts manuels hérités de l'époque Gemini (non intégrés à la suite de tests). |

## Modèle de données

Cinq tables SQLite. Il n'y a **pas de clé étrangère déclarée** : les liens se font par la colonne `report_id`, et la cohérence est maintenue par le code (notamment `DELETE /reports/{id}`).

```text
reports 1 ─── 0..1 report_summaries   (report_id unique)
reports 1 ─── 0..n notes              (report_id)
reports 1 ─── 0..n news_items         (report_id, NULL si le rapport a été supprimé)
reports n ─── n    chat_messages      (report_ids : liste JSON sérialisée)
```

### `reports`

| Colonne | Type | Description |
| --- | --- | --- |
| `id` | Integer PK | Identifiant (SQLite peut réutiliser l'id du dernier rapport supprimé). |
| `date` | String (AAAA-MM-JJ) | Date de la veille, au fuseau Europe/Paris pour les rapports générés. |
| `report_type` | String | `technical_watch` (veille quotidienne, défaut), `copilot_watch` (veille Microsoft Copilot, 7 jours) ou `codir_note` (note CODIR). Les deux premiers sont des « veilles » (`WATCH_REPORT_TYPES`) : même format, news extraites, vue structurée, newsletter. |
| `content` | Text | Markdown produit par le LLM. |
| `created_at` | DateTime (UTC) | Horodatage de création ; sert au tri. |
| `newsletter_sent_at` | DateTime (UTC), nullable | Dernier envoi réussi de la newsletter par mail (`POST /reports/{id}/send` ou cron). Ajoutée par `ensure_reports_schema()`. |

### `report_summaries`

Résumé exécutif d'un rapport, au plus un par rapport (`report_id` unique). Colonnes : `id`, `report_id`, `content`, `created_at`, `updated_at`. Régénérer le résumé met à jour la ligne existante.

### `notes`

Annotations attachées à un rapport : `id`, `report_id`, `kind` (`note`, `detail` ou `definition`), `source_text` (extrait sélectionné), `content` (texte de la note ou réponse générée), `created_at`.

### `chat_messages`

Historique de l'onglet Recherches : `id`, `role` (`user` / `assistant`), `content`, `report_ids` (texte JSON, ex. `[12, 11]` : rapports réellement consultés), `created_at`. Une question et sa réponse sont enregistrées ensemble, seulement si l'appel LLM réussit.

### `news_items`

Une ligne par nouveauté de la section « Nouveautés détaillées » d'une veille quotidienne ou Microsoft Copilot (`### titre` + puces).

| Colonne | Description |
| --- | --- |
| `id`, `report_id` | `report_id` passe à `NULL` quand le rapport est supprimé et que la news est sauvegardée. |
| `source_report_date` | Date du rapport d'origine, conservée après suppression. |
| `position`, `title`, `maturity`, `content` | Ordre dans le rapport, titre, maturité (puce « Maturité »), markdown des puces. |
| `saved`, `saved_at` | Sauvegarde par l'utilisateur. |
| `created_at` | Date d'extraction. |

Règles :
- l'extraction (`extract_news_items` / `sync_news_items`) est **idempotente** et ne concerne que les `technical_watch` ; elle a lieu à la génération, à la lecture de `GET /reports/{id}/news` et au démarrage (`backfill_news_items`) ;
- à la suppression d'un rapport, les news non sauvegardées sont supprimées, les sauvegardées sont détachées (`report_id = NULL`) ;
- retirer la sauvegarde d'une news détachée la supprime.

### Création du schéma et migrations légères

Au chargement de `main.py` :

1. `models.Base.metadata.create_all(bind=engine)` crée les tables manquantes ;
2. `ensure_reports_schema()` ajoute la colonne `reports.report_type` aux anciennes bases (valeur `technical_watch`) ;
3. `ensure_news_items_schema()` ajoute `news_items.source_report_date` et la remplit depuis `reports` ;
4. `backfill_news_items()` extrait les news des veilles qui n'en ont pas encore.

Toute nouvelle colonne doit suivre ce modèle : une fonction `ensure_*_schema()` qui teste la présence de la colonne puis exécute `ALTER TABLE`.

## Couche LLM

### Point d'entrée unique

```python
ensure_llm_ready()                         # vérifie la configuration du fournisseur actif
content = generate_llm_content(prompt,     # renvoie toujours une chaîne
                               timeout_seconds=LLM_TIMEOUT_SECONDS,
                               web_search=False)
```

`get_llm_provider()` lit `LLM_PROVIDER` à chaque appel (`codex` par défaut, `openrouter`, `gemini`). Une valeur inconnue lève une erreur explicite. Les endpoints qui appellent le LLM sont des fonctions **synchrones** : FastAPI les exécute dans son pool de threads, et un appel de plusieurs minutes ne bloque pas les autres requêtes.

### Fournisseurs

| Fournisseur | Implémentation | Recherche web | Pré-requis |
| --- | --- | --- | --- |
| `codex` (défaut) | `generate_codex_content` : `codex exec --skip-git-repo-check --ephemeral --sandbox read-only --color never --output-last-message <fichier> -c web_search="live"\|"disabled" [--model …] [-c model_reasoning_effort=…] -`. Le prompt passe par l'entrée standard (un argument est limité à 128 Ko), la réponse est lue dans le fichier `--output-last-message`. Exécution dans un dossier temporaire. | Oui si `web_search=True` et `CODEX_WEB_SEARCH` vrai (défaut). | Binaire `codex` (ou `CODEX_BIN`) et `codex login`. |
| `openrouter` | `generate_openrouter_content` : `POST OPENROUTER_API_URL` (format OpenAI chat/completions) via httpx. | Seulement si `OPENROUTER_WEB_SEARCH=true` : ajoute le plugin payant `{"id": "web"}`. | `OPENROUTER_API_KEY`. |
| `gemini` (historique) | CLI `gemini --output-format json` si `~/.gemini/oauth_creds.json` et le binaire existent ; sinon SDK `google.generativeai` (OAuth rafraîchi ou `GEMINI_API_KEY`). Le SDK est importé à la demande (`import_genai()`). | Oui avec la CLI, non avec le SDK. | Compte Gemini éligible (l'offre gratuite « Code Assist for individuals » n'est plus acceptée par la CLI). |

`llm_supports_web_search()` indique si le fournisseur actif peut chercher sur le web ; `describe_llm_backend()` produit le libellé affiché dans les logs ; `GET /llm/info` expose ces informations au frontend.

### Qui utilise la recherche web

| Appel | `web_search` | Délai |
| --- | --- | --- |
| Génération de veille (`/reports/trigger`, `/cron/daily`, `/reports/copilot/trigger`, `/cron/copilot-weekly`) | `True` | `LLM_REPORT_TIMEOUT_SECONDS` (600 s) |
| Note CODIR | `False` | `LLM_REPORT_TIMEOUT_SECONDS` |
| Chat avec « Chercher aussi sur le web » coché | `True` | max(`LLM_TIMEOUT_SECONDS`, 300 s) |
| Chat, résumé, détail, définition | `False` | `LLM_TIMEOUT_SECONDS` (90 s) |

Si le fournisseur n'a pas accès au web, la génération de veille continue mais un avertissement est écrit dans les logs ; le chat avec option web est refusé (400).

## Flux clés

### Génération de la veille quotidienne

```text
POST /reports/trigger  ─┐                                                   (interface : 202 + tâche, voir ci-dessous)
POST /cron/daily       ─┴► WATCH_GENERATION_LOCK.acquire(blocking=False) ──► 409 si déjà pris
                           generate_watch_report(db)
                             ├─ ensure_llm_ready()
                             ├─ build_technical_prompt(db)
                             │    « Date du jour … Période couverte : du J-1 HH:MM au J HH:MM (Paris) »
                             │    + TECHNICAL_PROMPT
                             │    + « Déjà couvert » : titres des news des 5 dernières veilles (60 max)
                             │    + « # Signaux communautaires Reddit » si REDDIT_ENABLED et des posts passent les filtres
                             ├─ generate_llm_content(…, LLM_REPORT_TIMEOUT_SECONDS, web_search=True)
                             ├─ INSERT reports (date = today_paris(), technical_watch)
                             └─ sync_news_items() → news_items
                           release du verrou
```

- Le verrou est un `threading.Lock` en mémoire : il protège un processus uvicorn unique, pas plusieurs instances.
- **Tâches de fond** : `/reports/trigger`, `/reports/copilot/trigger` et `/reports/{id}/codir` prennent le verrou puis lancent la génération dans un thread (`start_report_job()`) et répondent tout de suite **202** avec une tâche `{id, kind, status, report_id, error}`. Le frontend interroge `GET /jobs/{id}` (`waitForJobReport()` dans `api.ts`) jusqu'à `done` ou `error`, puis charge le rapport. Raison : en production, Cloudflare coupe toute requête sans réponse après 125 s. Le registre `JOBS` est en mémoire (perdu au redémarrage). Les routes `/cron/*`, appelées en local par `nas-cron.sh`, restent synchrones.
- `/cron/daily` ne génère rien si une `technical_watch` existe déjà pour la date du jour (sauf `force=true`), ce qui rend le cron rejouable.
- `TECHNICAL_PROMPT` impose la méthode (recherches web ciblées, vérification des sources primaires et des dates), le périmètre, les axes d'analyse et le format de sortie décrit dans [FONCTIONNEL.md](FONCTIONNEL.md#structure-dun-rapport-de-veille).

### Signaux communautaires Reddit

Optionnels (`REDDIT_ENABLED=true`, désactivés par défaut ; variables dans [CONFIGURATION.md](CONFIGURATION.md#reddit)).

1. `collect_reddit_posts()` joint les subreddits de `REDDIT_SUBREDDITS` et `fetch_subreddit_posts("A+B+C", "day")` lit **en une seule requête** le flux RSS public `www.reddit.com/r/A+B+C/top/.rss?t=day&limit=100` (Atom), avec un User-Agent descriptif et un délai court (`REDDIT_TIMEOUT_SECONDS`, 10 s). Pas d'OAuth : Reddit n'accorde pas d'application et refuse son API JSON sans compte (403) ; le RSS est la seule page lisible sans authentification, à raison d'environ une requête par minute. Après un 429, un seul nouvel essai si Reddit annonce une attente de 65 s au plus (`x-ratelimit-reset` / `Retry-After`).
2. `parse_feed()` extrait de chaque entrée : titre, subreddit (`category`), rang dans le top (1 = le plus voté), auteur, lien du thread, lien partagé (lien `[link]` du contenu, s'il ne pointe pas vers Reddit), extrait du texte (280 caractères), date de publication. Le RSS n'a ni score, ni commentaires, ni flair, ni indicateurs épinglé / NSFW.
3. `filter_posts()` garde les posts de la période (24 h pour `day`), écarte les mèmes par heuristique (mot-clé dans le titre, ou image / vidéo au titre de moins de 5 mots), dédoublonne par lien du thread et par URL externe (paramètres `utm_*` et `www.` ignorés, le mieux classé gagne), garde au plus `REDDIT_MAX_POSTS_PER_SUB` posts par subreddit et `REDDIT_MAX_POSTS` au total, dans l'ordre du top.
4. `build_technical_prompt()` ajoute la section « # Signaux communautaires Reddit » (titre, subreddit, rang, lien du thread, lien partagé, extrait) avec la consigne de les traiter comme des pistes à vérifier sur une source primaire. Le rapport ne gagne aucune section `##` : une discussion marquante non confirmée va au plus dans « Signaux faibles & recherche » et dans la « Note de méthode ».

Reddit ne peut pas faire échouer la veille : toute erreur (HTTP, 403, 429, délai, XML invalide, subreddit inconnu) est journalisée (`Reddit : r/<subs> indisponible (…)`) et donne une liste vide ; le prompt est alors identique à celui sans Reddit. `GET /reddit/preview` montre les posts retenus, sans appel LLM.

### Veille Microsoft Copilot

Veille hebdomadaire dédiée à Microsoft 365 Copilot, Copilot Studio, Work IQ et Copilot Cowork (rapport `copilot_watch`), déclenchée par le bouton « Veille Microsoft Copilot » (`POST /reports/copilot/trigger`) ou par un cron hebdomadaire (`POST /cron/copilot-weekly`).

```text
generate_watch_report(db, report_type="copilot_watch", prompt_builder=build_copilot_prompt)
  build_copilot_prompt(db)
    « Date du jour … Période couverte : du J-7 HH:MM au J HH:MM (Paris) »
    + COPILOT_WATCH_PROMPT  (périmètre, sources primaires à interroger une à une, questions par item, format)
    + « Déjà couvert » : titres des news des 5 dernières veilles copilot_watch
    + « Éléments du Microsoft 365 Roadmap créés ou modifiés pendant la période » (API publique, 40 max)
  generate_llm_content(…, web_search=True) → INSERT reports (copilot_watch) → sync_news_items()
```

- Même verrou (`WATCH_GENERATION_LOCK`) que la veille quotidienne : une seule génération à la fois (409).
- `/cron/copilot-weekly` ne génère rien si une `copilot_watch` existe sur les 7 derniers jours (date du rapport ≥ J-6), sauf `force=true` ; même envoi automatique par mail que `/cron/daily` (`MAIL_AUTO_SEND`).
- `COPILOT_WATCH_PROMPT` garde exactement les sections `##` de `TECHNICAL_PROMPT` ; chaque nouveauté ajoute les puces **Produit**, **Identifiant Roadmap**, **Statut** (In development / Rolling out / Launched), **Licence requise**, **Disponibilité UE / tenant FR** et **Impact admin M365**.
- `m365_roadmap.py` télécharge la Roadmap (≈ 2 200 éléments, 3 Mo, sans compte), garde les éléments du cloud mondial dont le produit est Microsoft Copilot (Microsoft 365), Copilot Studio ou Work IQ, ou dont le titre cite Cowork / Work IQ / Copilot Studio (sans les applications Dynamics 365 / Power Platform qui n'en parlent pas), créés ou modifiés dans la fenêtre ; nouveaux éléments d'abord. Erreur ou délai : liste vide, journalisée, et le LLM s'appuie sur sa recherche web.
- Libellés par type : chat (« Veille Microsoft Copilot du … »), titre du PDF, en-tête de la newsletter (« La veille Microsoft Copilot ») et objet du mail (« Veille Microsoft Copilot – <date> »).

Sources que le prompt fait interroger :

| Source | Adresse | Rôle |
| --- | --- | --- |
| Microsoft 365 Roadmap (filtre Copilot) | https://www.microsoft.com/microsoft-365/roadmap?filters=Microsoft%20Copilot%20(Microsoft%20365) | Identifiant, statut, date prévue. Son **API JSON publique** (`https://www.microsoft.com/releasecommunications/api/v1/m365`, sans compte) est lue par l'application et injectée dans le prompt. |
| What's new in Microsoft 365 Copilot | https://learn.microsoft.com/microsoft-365/copilot/release-notes | Notes de version. |
| What's new in Copilot Studio | https://learn.microsoft.com/microsoft-copilot-studio/whats-new | Notes de version Copilot Studio. |
| Microsoft 365 Blog | https://www.microsoft.com/microsoft-365/blog/ | Annonces. |
| Tech Community, blog Microsoft Copilot | https://techcommunity.microsoft.com/category/microsoft-copilot/blog/microsoft-copilot-blog | Billet mensuel « What's new in Microsoft 365 Copilot ». |
| Documentation Work IQ | https://learn.microsoft.com/microsoft-iq/ et https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/add-work-iq | Work IQ, serveur MCP, administration. |
| Documentation Copilot Cowork | https://learn.microsoft.com/microsoft-365/copilot/cowork/ | Cowork. |

### Chat sur les rapports (onglet Recherches)

1. Le frontend envoie `question`, `report_ids` (3 au plus ; par défaut les 3 dernières veilles), `history` (6 derniers messages de la conversation en cours), `web_search` et `persist`.
2. `build_report_chat_context()` assemble, pour chaque rapport : en-tête, résumé exécutif s'il existe, contenu complet (tronqué à `CHAT_REPORT_CONTEXT_MAX_CHARS`), notes de l'équipe.
3. `build_chat_prompt()` ajoute la date, les règles (citer `(Rapport <id> · <section>)`, séparer « D'après les rapports » / « Sur le web » si recherche web), l'historique et la question.
4. Si `persist` est vrai et l'appel réussi, question et réponse sont enregistrées dans `chat_messages`. Les synthèses « Projets suivis » du tableau de bord utilisent `persist=false`.

### Résumé, détail, définition

Prompts inline dans leurs endpoints, appliqués au rapport complet, sans recherche web. Le résumé est enregistré dans `report_summaries` ; le détail et la définition sont renvoyés au frontend, qui les enregistre comme notes (`kind = detail` / `definition`).

### Note CODIR

`POST /reports/{id}/codir` assemble le rapport, son résumé et ses notes, les injecte dans `CODIR_NOTE_PROMPT` (note business d'une page pour le comité de direction) et enregistre le résultat comme nouveau rapport `codir_note`. L'export Word (`GET /reports/{id}/docx`) met ensuite en page ce markdown avec python-docx (`build_codir_docx` : Calibri, bleu #1F4E79, rouge d'alerte #C0504D, tableaux à en-tête bleu).

### Export PDF

`GET /reports/{id}/pdf` construit un PDF ReportLab (`build_pdf_story`) : en-tête, résumé exécutif s'il existe, rapport complet, puis notes, détails et définitions. Le rendu interprète un sous-ensemble markdown limité (voir [FONCTIONNEL.md](FONCTIONNEL.md#sous-ensemble-markdown-supporté-par-le-pdf)).

### Newsletter

`GET /reports/{id}/newsletter` appelle `render_newsletter(content, date)` :

1. `parse_sections` découpe le markdown en sections `##` et sous-sections `###` ;
2. TL;DR → bloc « Executive summary » ; Radar → trois blocs colorés ; Nouveautés détaillées → une carte par nouveauté, avec l'acteur détecté (`detect_actor`) et sa couleur ; Sécurité & gouvernance → encadré rouge ; tableau de synthèse construit à partir des champs des nouveautés ; autres sections ; Note de méthode en grisé ;
3. le HTML respecte les contraintes des clients mail : commence par `<table>`, uniquement des tables et styles inline, `bgcolor` doublé de `background-color`, barres latérales en cellules de 4 px, largeur 720 px, caractères non ASCII convertis en entités (`to_entities`).

La route renvoie le HTML ; le bouton « Newsletter » l'ouvre dans un onglet.

### Envoi par mail

```text
POST /reports/{id}/send ──┐
POST /cron/daily ─────────┤ (si MAIL_AUTO_SEND=true et newsletter_sent_at vide)
                          ▼
send_report_newsletter(db, report)        MAIL_SEND_LOCK : un envoi à la fois
  ├─ build_newsletter_email_html()        render_newsletter() dans un document HTML complet
  ├─ mailer.send_html_email(« Veille IA – <date> », html, text = markdown du rapport)
  │    SMTP (STARTTLS) ou SMTP_SSL (port 465) → login si SMTP_USER → send_message(MAIL_TO)
  └─ reports.newsletter_sent_at = maintenant (UTC), seulement si l'envoi a réussi
```

- Configuration incomplète (`SMTP_HOST`, `MAIL_FROM`, `MAIL_TO`, ou `SMTP_PASSWORD` quand `SMTP_USER` est défini) : `MailNotConfigured` → 503. Échec SMTP (connexion, authentification, refus) : `MailSendError` → 502. L'application démarre normalement sans configuration mail.
- Le mot de passe n'apparaît ni dans les réponses (`GET /mail/info` donne seulement l'état, l'expéditeur et le nombre de destinataires), ni dans les logs, ni dans les messages d'erreur.
- Le cron n'envoie qu'une fois par rapport : `newsletter_sent_at` est relu sous verrou avant l'envoi. Un échec n'empêche pas la réponse du cron (`mail_error`), et l'envoi est retenté au prochain appel. Le bouton « Envoyer par mail », lui, permet de renvoyer après confirmation.

## Authentification et CORS

- `verify_token` est appliqué à **tous** les endpoints. Si `API_TOKEN` n'est pas défini, il ne vérifie rien (mode développement). Sinon chaque requête doit porter `Authorization: Bearer <API_TOKEN>` ; le frontend l'ajoute automatiquement si `VITE_API_TOKEN` est défini.
- CORS : origines de `ALLOWED_ORIGINS`, `allow_credentials=False` (pas de cookies).
