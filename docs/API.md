# API HTTP

[← Sommaire](README.md)

Base URL en local : `http://localhost:8000`. Format JSON sauf mention contraire. La documentation interactive générée par FastAPI est disponible sur `/docs` (Swagger) et `/openapi.json`.

## Authentification

Tous les endpoints passent par `verify_token` :

- `API_TOKEN` **non défini** (défaut en développement) : aucune vérification.
- `API_TOKEN` **défini** : chaque requête doit envoyer `Authorization: Bearer <API_TOKEN>`, sinon **401** `{"detail": "Invalid or missing token"}`.

Le frontend envoie cet en-tête si `VITE_API_TOKEN` est défini (voir [CONFIGURATION.md](CONFIGURATION.md)).

## Codes d'erreur communs

| Code | Cas |
| --- | --- |
| 401 | Jeton absent ou invalide (seulement si `API_TOKEN` est défini). |
| 404 | Ressource introuvable (`Report not found`, `News not found`, `Note not found`, `Summary not found`, `No reports available`). |
| 409 | Une génération de veille est déjà en cours. |
| 502 | Le serveur SMTP a refusé ou échoué l'envoi (connexion, authentification, destinataires). |
| 503 | Envoi de mail non configuré (la réponse liste les variables manquantes). |
| 422 | Paramètres ou corps invalides (validation FastAPI / Pydantic). |
| 500 | Erreur du fournisseur LLM ou de configuration (message dans `detail`, ex. « Binaire Codex introuvable », « OPENROUTER_API_KEY manquant », délai dépassé). |

## Tableau des endpoints

| # | Méthode | Chemin | Entrée | Sortie | Erreurs |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/reports` | query `skip` (0), `limit` (100) | `Report[]`, du plus récent au plus ancien | 401 |
| 2 | GET | `/reports/{report_id}` | — | `Report` | 404 |
| 3 | DELETE | `/reports/{report_id}` | — | 204 | 404 |
| 4 | POST | `/reports/trigger` | — | 202 `Job` (génère une `technical_watch` en tâche de fond) | 409 |
| 5 | POST | `/cron/daily` | query `force` (bool, `false`) | `DailyRunResponse` | 409, 500 |
| 6 | POST | `/reports/copilot/trigger` | — | 202 `Job` (génère une `copilot_watch` en tâche de fond) | 409 |
| 7 | POST | `/cron/copilot-weekly` | query `force` (bool, `false`) | `DailyRunResponse` | 409, 500 |
| 8 | POST | `/reports/{report_id}/codir` | — | 202 `Job` (génère une `codir_note` en tâche de fond) | 404 |
| 9 | GET | `/reports/{report_id}/summary` | — | `ReportSummaryResponse` | 404 (pas encore de résumé) |
| 10 | POST | `/reports/{report_id}/summary` | — | `ReportSummaryResponse` (généré ou régénéré) | 404, 500 |
| 11 | POST | `/reports/{report_id}/detail` | query `selected_text` | `{"detail": str}` | 404, 422, 500 |
| 12 | POST | `/reports/{report_id}/definition` | query `selected_text` | `{"definition": str}` | 404, 422, 500 |
| 13 | GET | `/reports/{report_id}/news` | — | `NewsItem[]` du rapport (extraites si besoin) | 404 |
| 14 | GET | `/news` | query `saved` (bool, optionnel), `report_id` (int, optionnel) | `NewsItem[]` | 401 |
| 15 | PATCH | `/news/{news_id}` | `{"saved": bool}` | `NewsItem` | 404 |
| 16 | GET | `/notes` | — | `Note[]`, plus récentes d'abord | 401 |
| 17 | POST | `/reports/{report_id}/notes` | `{"kind": str, "source_text": str, "content": str}` | `Note` | 404, 422 |
| 18 | DELETE | `/notes/{note_id}` | — | 204 | 404 |
| 19 | GET | `/chat/messages` | — | `ChatMessage[]`, ordre chronologique | 401 |
| 20 | POST | `/chat` | `ChatRequest` | `{"answer": str}` | 400, 404, 500 |
| 21 | GET | `/llm/info` | — | `LLMInfo` | 401 |
| 22 | GET | `/reports/{report_id}/pdf` | — | `application/pdf` (pièce jointe `ai_watch_<date>.pdf`) | 404 |
| 23 | GET | `/reports/{report_id}/docx` | — | `.docx` (pièce jointe `note_codir_veille_ia_<date>.docx`) | 400 si pas une note CODIR, 404 |
| 24 | GET | `/reports/{report_id}/newsletter` | — | `text/html` : corps d'email commençant par `<table>` | 404 |
| 25 | GET | `/reddit/preview` | query `subreddit` (optionnel), `period` (`day`) | `RedditPreview` (aucun appel LLM) | 400 |
| 26 | GET | `/mail/info` | — | `MailInfo` (sans mot de passe) | 401 |
| 27 | POST | `/reports/{report_id}/send` | — | `SendNewsletterResult` | 404, 502, 503 |
| 28 | GET | `/jobs/{job_id}` | — | `Job` | 404 (inconnue ou serveur redémarré) |

## Détail des endpoints

### Rapports

**`GET /reports`** — liste paginée (`skip`, `limit`), triée par `created_at` décroissant, tous types confondus.

**`GET /reports/{report_id}`** — un rapport.

**`DELETE /reports/{report_id}`** — supprime le rapport, son résumé, ses notes et ses news non sauvegardées. Les news sauvegardées sont conservées et détachées (`report_id = null`, `report_date` conservée).

**`POST /reports/trigger`** — génère une veille maintenant (bouton « Lancer la veille »). Appel LLM avec recherche web, plusieurs minutes, donc lancé en tâche de fond : la réponse 202 est une `Job` à suivre avec `GET /jobs/{job_id}` (le proxy Cloudflare coupe toute requête sans réponse après 125 s). 409 si une génération (bouton ou cron) est déjà en cours.

**`GET /jobs/{job_id}`** — état d'une génération en tâche de fond (veilles, note CODIR). `status` vaut `running`, `done` (`report_id` du rapport créé) ou `error` (`error` contient le message, par exemple une erreur du fournisseur LLM). Registre en mémoire : une tâche est perdue si le backend redémarre (404).

```json
{"id": "3f2c…", "kind": "technical_watch", "status": "done", "report_id": 43, "error": null,
 "started_at": "2026-10-27T19:02:11"}
```

**`POST /cron/daily`** — route destinée au cron. Si une `technical_watch` existe déjà pour la date du jour (Europe/Paris) et que `force` est faux, la renvoie sans rien générer (`created: false`). Sinon génère comme `/reports/trigger`. Avec `MAIL_AUTO_SEND=true`, envoie ensuite la newsletter du rapport si elle ne l'a pas encore été (`newsletter_sent_at` vide) : `mail_sent` vaut `true` si l'envoi a eu lieu pendant cet appel ; en cas d'échec ou de configuration incomplète, la réponse reste 200 avec la cause dans `mail_error`, et le prochain appel retente l'envoi.

```json
{"report_id": 42, "date": "2026-10-25", "created": true, "newsletter_url": "/reports/42/newsletter",
 "mail_sent": true, "mail_error": null}
```

**`POST /reports/copilot/trigger`** — génère maintenant une veille Microsoft Copilot (`copilot_watch`) sur les 7 derniers jours : Microsoft 365 Copilot, Copilot Studio, Work IQ, Copilot Cowork. Appel LLM avec recherche web, plus les éléments récents du Microsoft 365 Roadmap. Tâche de fond (202 `Job`) comme `/reports/trigger`, même verrou que la veille quotidienne (409).

**`POST /cron/copilot-weekly`** — route pour un cron hebdomadaire. Si une `copilot_watch` existe déjà sur les 7 derniers jours et que `force` est faux, la renvoie (`created: false`). Sinon génère comme `/reports/copilot/trigger`. Réponse identique à `/cron/daily` (dont `newsletter_url` et l'envoi automatique `mail_sent` / `mail_error`).

**`POST /reports/{report_id}/codir`** — génère une note CODIR à partir du rapport, de son résumé et de ses notes ; l'enregistre comme nouveau rapport `codir_note`. Tâche de fond (202 `Job`, voir `GET /jobs/{job_id}`) ; 404 immédiat si le rapport source n'existe pas.

### Résumé, détail, définition

**`GET /reports/{report_id}/summary`** / **`POST /reports/{report_id}/summary`** — lecture / génération du résumé exécutif (5 points maximum, terminé par « Décision suggérée »).

```json
{"report_id": 42, "summary": "- …\nDécision suggérée : …", "updated_at": "2026-10-25T07:31:02"}
```

**`POST /reports/{report_id}/detail?selected_text=…`** — explication de l'extrait (6 lignes maximum, uniquement à partir du rapport). Non enregistrée par le backend : le frontend crée ensuite une note `detail`.

**`POST /reports/{report_id}/definition?selected_text=…`** — définition courte du terme sélectionné. Le frontend crée ensuite une note `definition`.

### News

`NewsItem` :

```json
{
  "id": 7, "report_id": 42, "position": 0,
  "title": "OpenAI publie GPT-X", "maturity": "GA",
  "content": "- **Ce qui sort** : …", "saved": true,
  "saved_at": "2026-10-25T08:02:11", "created_at": "2026-10-25T07:31:02",
  "report_date": "2026-10-25"
}
```

`report_id` vaut `null` pour une news sauvegardée dont le rapport a été supprimé ; `report_date` reste renseignée.

**`GET /reports/{report_id}/news`** — news du rapport, par position ; extrait les news si ce n'est pas encore fait (veilles uniquement).

**`GET /news`** — filtrage optionnel par `saved` et `report_id`. Avec `saved=true`, tri par date de sauvegarde décroissante.

**`PATCH /news/{news_id}`** — `{"saved": true}` sauvegarde, `{"saved": false}` retire. Retirer une news détachée la supprime définitivement.

### Notes

`Note` : `{"id", "report_id", "kind", "source_text", "content", "created_at"}` avec `kind` ∈ `note`, `detail`, `definition`.

### Chat

`ChatRequest` :

| Champ | Type | Défaut | Effet |
| --- | --- | --- | --- |
| `question` | str | — | Obligatoire, non vide (sinon 400 `Question cannot be empty`). |
| `report_ids` | int[] | `null` | Rapports de contexte (3 au plus). Vide : les 3 rapports les plus récents. 404 si aucun rapport. |
| `history` | `{role, content}[]` | `null` | Échanges précédents ; seuls les 6 derniers sont utilisés, tronqués à 2 000 caractères. |
| `web_search` | bool | `false` | Active la recherche web. 400 si le fournisseur n'y a pas accès. |
| `persist` | bool | `true` | Enregistre question et réponse dans `chat_messages` (en cas de succès uniquement). |

`ChatMessage` : `{"id", "role": "user"|"assistant", "content", "report_ids": [int]|null, "created_at"}`.

**`GET /llm/info`** — fournisseur actif, utilisé par le frontend pour activer l'option web :

```json
{"provider": "codex", "web_search": true, "backend": "codex model=<défaut codex>"}
```

### Exports

**`GET /reports/{report_id}/pdf`** — PDF : en-tête, résumé exécutif, rapport complet, notes.

**`GET /reports/{report_id}/docx`** — Word mis en page, uniquement pour les rapports `codir_note`.

**`GET /reports/{report_id}/newsletter`** — HTML de newsletter (voir [ARCHITECTURE.md](ARCHITECTURE.md#newsletter)).

### Mail

**`GET /mail/info`** — état de la configuration d'envoi, **sans mot de passe ni adresses des destinataires**. Le frontend s'en sert pour activer le bouton « Envoyer par mail ».

```json
{"configured": true, "missing": [], "host": "smtp.office365.com", "port": 587, "security": "starttls",
 "authenticated": true, "sender": "Veille IA <veille@april.fr>", "recipients_count": 4, "auto_send": false}
```

**`POST /reports/{report_id}/send`** — envoie la newsletter du rapport (objet « Veille IA – <date> », HTML de `render_newsletter` + version texte = markdown du rapport) aux adresses de `MAIL_TO`, puis renseigne `newsletter_sent_at`. Renvoie même si la newsletter a déjà été envoyée. 404 si le rapport n'existe pas, 503 si le mail n'est pas configuré, 502 si l'envoi SMTP échoue (`newsletter_sent_at` inchangé).

```json
{"report_id": 42, "subject": "Veille IA – 2026-10-25", "recipients_count": 4, "newsletter_sent_at": "2026-10-25T05:42:10.123456"}
```

`Report` contient aussi `newsletter_sent_at` (UTC, `null` si jamais envoyée).

### Reddit

**`GET /reddit/preview?subreddit=&period=`** — posts Reddit filtrés, tels qu'ils seraient ajoutés au prompt de veille, **sans appel LLM** (flux RSS public, une seule requête). Sert à régler la configuration ; fonctionne même avec `REDDIT_ENABLED=false` (le champ `enabled` indique si la veille les utilisera).

- `subreddit` : un seul subreddit (avec ou sans `r/`) ; vide ou absent : ceux de `REDDIT_SUBREDDITS`. Nom invalide : 400.
- `period` : `hour`, `day` (défaut), `week`, `month`, `year` ou `all` ; la fenêtre de filtrage suit la période (24 h pour `day`, aucune pour `all`). Autre valeur : 400.
- Reddit indisponible ou limite de requêtes atteinte : 200 avec `posts` vide et la cause dans `errors`. Reddit n'accepte qu'environ une requête anonyme par minute : attendre une minute entre deux appels.
- Le RSS ne donne pas de score : `rank` est la position dans le top de la période (1 = le plus voté, tous subreddits confondus).

```json
{
  "enabled": true, "period": "day",
  "subreddits": ["LocalLLaMA"], "max_posts": 15, "max_posts_per_sub": 5,
  "posts": [{
    "title": "…", "subreddit": "LocalLLaMA", "rank": 1, "author": "/u/…",
    "permalink": "https://www.reddit.com/r/LocalLLaMA/comments/…/",
    "external_url": "https://huggingface.co/…", "excerpt": "Début du texte du post…",
    "created_utc": 1792900000.0, "created_at": "2026-10-25T05:46:40+00:00"
  }],
  "errors": []
}
```

## Exemples

```bash
TOKEN=…   # seulement si API_TOKEN est défini
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/reports
curl -X POST --max-time 900 -H "Authorization: Bearer $TOKEN" "http://localhost:8000/cron/daily"
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"question": "Que faut-il tester cette semaine ?"}' http://localhost:8000/chat
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/reports/42/newsletter > newsletter.html
curl -X POST --max-time 900 -H "Authorization: Bearer $TOKEN" "http://localhost:8000/cron/copilot-weekly"
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/mail/info
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/reports/42/send
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/reddit/preview?subreddit=LocalLLaMA&period=day"
```
