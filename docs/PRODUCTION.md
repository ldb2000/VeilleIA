# Production (NAS)

[← Sommaire](README.md)

VeilleIA tourne en production sur le NAS Synology `diskstation`, publié sur **https://veilleia-app.deberti.fr**. Cette page décrit l'installation, la mise en production, la vérification après déploiement, les crons, la surveillance, la sauvegarde et le retour arrière. La validation avant mise en production est décrite dans [RECETTE.md](RECETTE.md).

## Vue d'ensemble

```text
navigateur ──► Cloudflare Access (code par mail, application « NAS apps »)
           ──► Cloudflare Tunnel « diskstation » (*.deberti.fr)
           ──► cloudflared (conteneur) ──► Traefik (conteneur, entrypoint web)
                 ├─ Host(veilleia-app.deberti.fr)                 ──► veilleia-frontend :80 (nginx, build statique)
                 └─ Host(veilleia-app.deberti.fr) && /api (retiré) ──► veilleia-backend :8000 (uvicorn, 1 worker)
                                                                        ├─ data/sql_app.db (SQLite)
                                                                        └─ codex/ (authentification Codex)
DSM Planificateur (root) ──► nas-cron.sh ──► docker exec veilleia-backend ──► POST http://localhost:8000/cron/…
```

| Élément | Où | Rôle |
| --- | --- | --- |
| Compose principal | `/volume1/services/docker-compose.yml` (hors dépôt) | Lance Traefik et cloudflared, déclare le réseau `proxy` et `include:` `veilleIA/compose.yml`. Jeton du tunnel dans `/volume1/services/.env`. |
| `compose.yml` | dépôt → `/volume1/services/veilleIA/compose.yml` | Services `veilleia-backend` et `veilleia-frontend`, labels Traefik. Ne se lance pas seul (le réseau `proxy` vient du compose principal). |
| `backend/Dockerfile` | dépôt | Python 3.12-slim, Node.js et Codex CLI (`npm install -g @openai/codex`, dernière version au moment du build), dépendances Python, **code copié dans l'image**. |
| `frontend/Dockerfile.prod` + `frontend/nginx.conf` | dépôt | Build Vite avec `VITE_API_URL=/api`, servi par nginx ; `/assets/` en cache long (fichiers versionnés), `index.html` en `no-cache`, repli SPA sur `index.html`. |
| `deploy-nas.sh` | dépôt | Envoie la copie de travail sur le NAS et reconstruit les deux conteneurs. |
| `nas-cron.sh` | dépôt | Appelle une route cron depuis le conteneur backend, journalise dans `data/cron.log`. |
| `backend/.env`, `data/`, `codex/` | NAS uniquement | Configuration, base SQLite, journal des crons et authentification Codex. Un déploiement ne les écrase pas tant que la copie locale n'en contient pas (voir [Mise en production](#mise-en-production)). |

Différences avec le développement local :

- Pas d'`API_TOKEN` : il serait intégré au JavaScript public. Cloudflare Access est la seule barrière ; ne jamais publier le backend par un autre chemin (port ouvert, autre Host Traefik) sans définir `API_TOKEN`.
- Frontend et API sur le même domaine (`/api`) : CORS n'intervient pas, `ALLOWED_ORIGINS` peut rester à sa valeur par défaut.
- Le code du backend est dans l'image (pas de montage de `backend/app`) : toute modification passe par un déploiement, qui reconstruit l'image.
- Cloudflare coupe une requête restée sans réponse **125 s**. Les générations longues lancées depuis l'interface (veille, veille Copilot, note CODIR) répondent donc tout de suite 202 avec une tâche, suivie par `GET /jobs/{id}` ; les crons passent par `nas-cron.sh`, en local dans le conteneur, sans cette limite. Les autres appels LLM (chat, résumé, détail, définition, chat avec recherche web) restent synchrones : avec un délai LLM long, ils peuvent dépasser 125 s en production (voir [Limites connues](#limites-connues)).

## Installation initiale

À faire une fois, ou pour reconstruire le NAS.

1. **Compose principal** : `/volume1/services/docker-compose.yml` doit déclarer le réseau `proxy`, Traefik (entrypoint `web`), cloudflared, et inclure `veilleIA/compose.yml` :

   ```yaml
   include:
     - veilleIA/compose.yml
   ```

   Docker Compose 2.20 (fourni par DSM) refuse qu'un fichier inclus redéclare `proxy` : seul le compose principal le déclare.
2. **Cloudflare** : le tunnel `diskstation` envoie `*.deberti.fr` vers Traefik ; l'application Access « NAS apps » couvre `veilleia-app.deberti.fr`.
3. **Dossier** : `/volume1/services/veilleIA` avec les sous-dossiers `data/` et `codex/`.
4. **Authentification Codex** : faire `codex login` sur un poste, puis copier `~/.codex/auth.json` (et `config.toml` si un modèle est imposé) dans `/volume1/services/veilleIA/codex/`. Le dossier est monté en écriture sur `/root/.codex` pour que le jeton se rafraîchisse.
5. **`backend/.env`** sur le NAS, à partir de `.env.example`. Valeurs de production recommandées :

   ```dotenv
   LLM_PROVIDER=codex
   CODEX_WEB_SEARCH=true
   LLM_REPORT_TIMEOUT_SECONDS=600

   # Pas d'API_TOKEN ni de VITE_API_TOKEN : Cloudflare Access protège l'accès.
   API_TOKEN=
   VITE_API_TOKEN=

   # Mail (optionnel) : voir CONFIGURATION.md#mail-smtp
   SMTP_HOST=…
   SMTP_USER=…
   SMTP_PASSWORD=…
   MAIL_FROM=Veille IA <…>
   MAIL_TO=…
   MAIL_AUTO_SEND=true

   # Optionnels
   REDDIT_ENABLED=true
   COPILOT_ROADMAP_ENABLED=true
   ```

   Toutes les variables : [CONFIGURATION.md](CONFIGURATION.md). `DATABASE_URL` est fixé par `compose.yml` (`sqlite:///./data/sql_app.db`).
6. **Premier déploiement** : `./deploy-nas.sh` depuis un poste qui a le dépôt et l'accès SSH (voir ci-dessous).
7. **Crons** : créer les deux tâches DSM (voir [Crons](#crons)).
8. **Vérification** : dérouler la [vérification après déploiement](#vérification-après-déploiement).

## Mise en production

Préalable : la [recette](RECETTE.md) est passée sur la version à déployer.

```bash
git switch main && git pull            # déployer la version recettée, pas un travail en cours
git status                             # la copie de travail doit être propre
./deploy-nas.sh
```

Le script :

1. liste les fichiers suivis et non ignorés par git (`git ls-files -co --exclude-standard`, hors `.scion/` et `.vcm/`) et les envoie par `tar` sur SSH (`ssh -p 2222 laurent@diskstation`) dans `/volume1/services/veilleIA` ;
2. lance `sudo docker compose -f /volume1/services/docker-compose.yml up -d --build veilleia-backend veilleia-frontend`.

Points d'attention :

- **Ce qui est envoyé est la copie de travail locale**, commitée ou non, et non GitHub : un fichier modifié mais non commité part en production. D'où `git status` avant.
- **Fichiers propres au NAS** : le script envoie tout fichier non ignoré par git. `backend/.env` et les `*.db` sont ignorés, donc jamais envoyés ; en revanche `codex/` et `data/cron.log` ne le sont pas. Ne jamais créer de dossier `codex/` (ni de `data/cron.log`) dans la copie locale : il remplacerait celui du NAS et casserait l'authentification Codex. Vérifier avec `git status --ignored`.
- Un fichier **supprimé** localement reste sur le NAS (tar n'efface rien). Après une suppression ou un renommage, le retirer à la main sur le NAS.
- Les builds utilisent le réseau hôte (`network: host`) : le bridge Docker par défaut du NAS ne joint pas le DNS local.
- Le build du backend réinstalle la **dernière version de Codex CLI** : un déploiement peut changer de version de Codex sans changement de code. En cas de régression LLM juste après un déploiement, regarder d'abord de ce côté.
- Une génération en cours est **interrompue** par le redémarrage du backend, et les tâches suivies par `/jobs` sont perdues (registre en mémoire) : déployer hors des créneaux des crons (7 h – 7 h 45 en semaine) et quand personne ne génère de veille.
- Les migrations de schéma sont automatiques au démarrage (`ensure_reports_schema()`, `ensure_news_items_schema()`) et uniquement additives (ajout de colonnes).

## Vérification après déploiement

À faire juste après chaque déploiement (5 minutes). Les commandes s'exécutent depuis le poste ; le NAS est joint par SSH.

| # | Vérification | Commande / action | Attendu |
| --- | --- | --- | --- |
| P1 | Conteneurs démarrés | `ssh -p 2222 laurent@diskstation 'sudo docker ps --filter name=veilleia'` | `veilleia-backend` et `veilleia-frontend` « Up », sans redémarrage en boucle. |
| P2 | Démarrage du backend | `ssh -p 2222 laurent@diskstation 'sudo docker logs --tail 50 veilleia-backend'` | `Application startup complete`, aucune trace d'erreur (migrations comprises). |
| P3 | API joignable dans le conteneur | `ssh -p 2222 laurent@diskstation 'sudo docker exec veilleia-backend python -c "import urllib.request;print(urllib.request.urlopen(\"http://localhost:8000/llm/info\").read().decode())"'` | `{"provider":"codex","web_search":true,…}` |
| P4 | Accès public protégé | navigation privée sur https://veilleia-app.deberti.fr | Page Cloudflare Access (code par mail), puis l'application. |
| P5 | Interface | après connexion | Tableau de bord avec la dernière veille ; les rapports existants sont listés (données conservées). |
| P6 | Version servie | recharger la page (Ctrl+F5 inutile : `index.html` n'est pas mis en cache) | La fonctionnalité livrée est visible. |
| P7 | Lecture d'un rapport | onglet Rapports, ouvrir une veille | Vue structurée, sommaire, export PDF et « Newsletter » fonctionnent. |
| P8 | Mail (si configuré) | info-bulle du bouton « Envoyer par mail », ou `GET /api/mail/info` dans le navigateur | `configured: true`, bon expéditeur, bon nombre de destinataires. |
| P9 | Codex authentifié | si une génération est prévue : « Lancer la veille » (ou attendre le cron du lendemain et lire `data/cron.log`) | Le rapport apparaît après quelques minutes ; pas d'erreur `401` / « Not logged in » dans les logs. |

Si P1 à P5 échouent : [retour arrière](#retour-arrière).

## Crons

Deux tâches du Planificateur de tâches DSM (Panneau de configuration → Planificateur de tâches → Créer → Tâche planifiée → Script défini par l'utilisateur), utilisateur **root** :

| Tâche | Planification | Commande |
| --- | --- | --- |
| VeilleIA – veille quotidienne | lundi à vendredi, 7 h 30 | `sh /volume1/services/veilleIA/nas-cron.sh /cron/daily` |
| VeilleIA – veille Copilot | lundi, 7 h 00 | `sh /volume1/services/veilleIA/nas-cron.sh /cron/copilot-weekly` |

- `nas-cron.sh` fait un `docker exec` dans `veilleia-backend` et appelle `http://localhost:8000<route>` avec 900 s de délai : ni Cloudflare, ni jeton, ni limite des 125 s.
- Journal : `/volume1/services/veilleIA/data/cron.log` (une ligne de début, la réponse JSON, une ligne de fin avec le code de sortie). Le code est 1 sur une réponse HTTP d'erreur, ce que DSM peut signaler par mail (option « Envoyer les détails d'exécution par e-mail » de la tâche).
- Les routes sont rejouables : relancer la tâche à la main ne regénère pas une veille déjà faite (`created: false`). Pour forcer : `sh nas-cron.sh "/cron/daily?force=true"`.
- Les deux générations partagent un verrou : la veille Copilot (7 h 00) doit avoir fini avant 7 h 30, sinon la veille quotidienne reçoit 409. Si c'est le cas, relancer la tâche quotidienne à la main.
- Avec `MAIL_AUTO_SEND=true`, chaque cron envoie la newsletter du rapport une seule fois (`mail_sent` / `mail_error` dans `cron.log`).

## Surveillance et logs

| Besoin | Commande |
| --- | --- |
| Logs du backend en direct | `ssh -p 2222 laurent@diskstation 'sudo docker logs -f veilleia-backend'` |
| Dernières exécutions des crons | `ssh -p 2222 laurent@diskstation 'tail -n 40 /volume1/services/veilleIA/data/cron.log'` |
| Veille du jour faite ? | dans `cron.log`, `"created": true` (ou `false` si déjà faite) avec la date du jour |
| Routage Traefik | dashboard sur le réseau local : http://diskstation:8081 |
| Logs Traefik / tunnel | `sudo docker logs traefik`, `sudo docker logs cloudflared` (noms définis dans le compose principal) |

Messages à connaître dans les logs du backend : `Sending technical_watch request to codex …` puis `LLM response received in …s` (génération normale) ; `ATTENTION : le fournisseur LLM actif n'a pas accès à internet` ; `Reddit : … indisponible (…)` et `Roadmap : … indisponible (…)` (sans gravité : la veille se génère sans ces signaux) ; `Mail : envoi automatique … impossible : …`.

## Sauvegarde et restauration

Toutes les données sont dans `data/sql_app.db`. Une copie à chaud cohérente, sans arrêter le service :

```bash
ssh -p 2222 laurent@diskstation 'sudo docker exec veilleia-backend python -c "
import sqlite3, datetime
dst = f\"data/backup-{datetime.date.today()}.db\"
sqlite3.connect(\"data/sql_app.db\").backup(sqlite3.connect(dst))
print(dst)"'
```

La copie arrive dans `/volume1/services/veilleIA/data/`. À prévoir aussi : inclure `/volume1/services/veilleIA/data` et `codex/` dans Hyper Backup (ou l'outil de sauvegarde du NAS), et faire une copie avant chaque déploiement qui modifie le schéma.

Restauration : arrêter le backend (`sudo docker stop veilleia-backend`), remplacer `data/sql_app.db` par la copie, redémarrer (`sudo docker start veilleia-backend`).

## Retour arrière

Le déploiement envoie une copie de travail : revenir en arrière, c'est déployer la version précédente.

```bash
git log --oneline -10                         # repérer le dernier commit sain
git worktree add ../veilleia-rollback <sha>   # copie propre de cette version
cd ../veilleia-rollback && ./deploy-nas.sh    # le script déploie le dossier où il se trouve
cd - && git worktree remove ../veilleia-rollback
```

- La base n'a pas besoin d'être restaurée : les migrations n'ajoutent que des colonnes, que l'ancienne version ignore.
- Les fichiers ajoutés par la version retirée restent sur le NAS (tar n'efface rien) ; ils sont sans effet tant que le code ne les référence pas.
- Si la régression vient de Codex (nouvelle version installée au build), le retour arrière du code ne suffit pas : épingler la version dans `backend/Dockerfile` (`npm install -g @openai/codex@<version>`) et redéployer.

## Renouveler l'authentification Codex

Symptôme : générations en erreur avec `401 Unauthorized` / « Not logged in » dans les logs ou dans `cron.log`.

1. Sur un poste : `codex login` (ou `codex logout` puis `codex login`).
2. Copier le nouveau `~/.codex/auth.json` vers `/volume1/services/veilleIA/codex/auth.json` (`scp -P 2222`, puis `sudo mv` si besoin).
3. Redémarrer le backend : `sudo docker restart veilleia-backend`.
4. Vérifier avec une génération (P9).

## Limites connues

- **Un seul worker uvicorn** : le verrou de génération, le registre des tâches `/jobs` et le verrou d'envoi de mail sont en mémoire. Ne pas augmenter le nombre de workers ni lancer deux instances.
- **Redémarrage = tâches perdues** : une génération en cours est interrompue et son suivi renvoie 404 « Tâche inconnue ». Relancer la génération.
- **Appels synchrones et limite de 125 s** : chat (surtout avec « Chercher aussi sur le web »), résumé, détail et définition restent synchrones. Un appel plus long que 125 s est coupé par Cloudflare (erreur 524 dans le navigateur) même si le backend finit le travail ; le résumé est alors enregistré quand même et réapparaît au rechargement.
- **SQLite** : adapté à un usage d'équipe ; pas d'accès concurrent depuis plusieurs machines.

## Dépannage en production

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| Page Cloudflare « 502 Bad Gateway » / « 1033 » | Traefik ou cloudflared arrêté, tunnel déconnecté | `sudo docker ps` ; redémarrer le compose principal. |
| 404 Traefik sur le domaine | Conteneurs VeilleIA absents du réseau `proxy` ou labels non pris en compte | `sudo docker ps --filter name=veilleia` ; vérifier le dashboard Traefik (:8081) ; redéployer. |
| Interface affichée mais « Network Error » sur toutes les actions | Backend arrêté ou en échec au démarrage | `sudo docker logs veilleia-backend` (P2). |
| Erreur 524 sur une action | Appel synchrone de plus de 125 s (voir Limites) | Réessayer ; pour une veille ou une note CODIR, passer par le bouton (tâche de fond). |
| « La génération a échoué » après plusieurs minutes | Erreur LLM (Codex non connecté, délai dépassé) | Message exact dans `docker logs` ; [renouveler Codex](#renouveler-lauthentification-codex) si 401. |
| « Tâche inconnue (le serveur a peut-être redémarré) » | Backend redémarré pendant la génération | Relancer la génération. |
| Pas de veille le matin | Tâche DSM désactivée, 409 (veille Copilot pas finie), erreur LLM | Lire `data/cron.log` ; relancer la tâche à la main. |
| Ancienne interface après un déploiement | Build frontend non reconstruit | Relancer `./deploy-nas.sh` ; vérifier que `veilleia-frontend` a été recréé (`docker ps`, colonne « Created »). |

Dépannage général (Codex, Reddit, mail, Roadmap) : [EXPLOITATION.md](EXPLOITATION.md#dépannage).
