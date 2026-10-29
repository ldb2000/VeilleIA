# Recette

[← Sommaire](README.md)

La recette valide une version **avant** sa mise en production sur le NAS ([PRODUCTION.md](PRODUCTION.md)). Elle se fait sur un poste de développement, avec une copie des données de production, en trois temps : contrôles automatiques, cas fonctionnels, procès-verbal. Une version n'est déployée que si le procès-verbal conclut « bon pour la production ».

## Quand la faire

| Changement livré | Recette à dérouler |
| --- | --- |
| Toute version déployée | Contrôles automatiques + [socle](#socle-à-chaque-version) (R01 à R12). |
| Prompts, génération de veille, Reddit, Roadmap | + [génération](#génération-des-veilles) avec un vrai appel LLM (R20 à R27). |
| Mail, newsletter | + [newsletter et mail](#newsletter-et-mail) (R40 à R46). |
| Schéma de base (nouvelle colonne, migration) | + [données de production](#données-de-production) (R60 à R62), sur une copie de la base de production. |
| Déploiement, Docker, nginx, Traefik | + [build de production](#build-de-production) (R70 à R72). |

## Environnement de recette

Il n'y a pas de serveur de recette dédié : la recette tourne en local (`./dev.sh`) avec la même configuration LLM que la production et, si besoin, une copie de sa base.

1. **Version à recetter** : copie de travail propre sur le commit à déployer (`git status` vide, `git log -1` noté dans le PV).
2. **Configuration** : `backend/.env` local avec le même fournisseur que la production (`LLM_PROVIDER=codex`, `CODEX_WEB_SEARCH=true`, `codex login` fait sur le poste). Précautions :
   - `MAIL_TO` = **votre seule adresse** (jamais la liste de diffusion), `MAIL_AUTO_SEND=false` ;
   - `API_TOKEN` vide, comme en production (ou défini, pour tester R12).
3. **Copie de la base de production** (pour R60 à R62, facultative sinon) :

   ```bash
   ssh -p 2222 laurent@diskstation 'sudo docker exec veilleia-backend python -c "
   import sqlite3; sqlite3.connect(\"data/sql_app.db\").backup(sqlite3.connect(\"data/recette.db\"))"'
   scp -P 2222 laurent@diskstation:/volume1/services/veilleIA/data/recette.db /tmp/veilleia-recette.db
   ssh -p 2222 laurent@diskstation 'sudo rm /volume1/services/veilleIA/data/recette.db'
   ```

   puis dans `backend/.env` : `DATABASE_URL=sqlite:////tmp/veilleia-recette.db` (quatre `/` pour un chemin absolu). Ne jamais pointer la recette sur la base de production elle-même.
4. **Serveur SMTP de test** (pour R40 à R46) : les mails sont affichés dans le terminal au lieu d'être envoyés.

   ```bash
   backend/venv/bin/pip install aiosmtpd          # pas dans requirements.txt : outil de recette
   backend/venv/bin/python -m aiosmtpd -n -l 127.0.0.1:8025
   ```

   Chaque mail reçu s'affiche entre `MESSAGE FOLLOWS` et `END MESSAGE`. Configuration correspondante dans `backend/.env` : `SMTP_HOST=127.0.0.1`, `SMTP_PORT=8025`, `SMTP_STARTTLS=false`, `SMTP_USER=` vide, `MAIL_FROM=Veille IA <recette@example.org>`, `MAIL_TO=vous@example.org`.
5. **Lancement** : `./dev.sh`, puis http://localhost:5173.

Revenir ensuite à la configuration habituelle (retirer `DATABASE_URL`, les réglages SMTP de test) et supprimer `/tmp/veilleia-recette.db`.

## Contrôles automatiques

Bloquants : tout doit passer.

```bash
backend/venv/bin/python -m pytest -q \
  test_llm_providers.py test_news_items.py test_prompts_renderer.py test_chat_and_watch.py \
  test_newsletter.py test_reddit.py test_mailer.py test_copilot_watch.py
cd frontend && npm run build && npm run lint
```

| # | Contrôle | Attendu |
| --- | --- | --- |
| A1 | pytest | Tous les tests passent (87 au 29/10/2026), sans accès réseau nécessaire. |
| A2 | `npm run build` | Typage TypeScript et build Vite sans erreur. |
| A3 | `npm run lint` | Aucune erreur ; pas de nouvel avertissement par rapport à la version en production. |
| A4 | Documentation | Un endpoint ou une variable d'environnement ajouté figure dans [API.md](API.md) / [CONFIGURATION.md](CONFIGURATION.md). |

## Cas fonctionnels

Chaque cas : résultat OK / KO / non testé, avec une remarque en cas de KO. Les cas notés **LLM** consomment un vrai appel au fournisseur (quelques minutes pour une veille).

### Socle (à chaque version)

| # | Cas | Étapes | Attendu |
| --- | --- | --- | --- |
| R01 | Démarrage | `./dev.sh` | Backend et frontend démarrent ; pas d'erreur dans le terminal (migrations comprises). |
| R02 | Tableau de bord | Ouvrir l'application | Bandeau avec le TL;DR de la dernière veille quotidienne, 4 indicateurs, radar de la semaine, projets suivis. Une veille Copilot n'apparaît pas dans le bandeau. |
| R03 | Lecture d'une veille | Rapports → une veille quotidienne | Vue structurée : TL;DR, radar en 3 colonnes, une carte par nouveauté avec badge de maturité et « Action recommandée », sommaire cliquable. |
| R04 | Lecture d'une veille Copilot | Rapports → une « Veille Microsoft Copilot » | Badge « 7 jours » dans l'historique, titre « Microsoft Copilot : la semaine », champs Identifiant Roadmap, Statut, Licence requise, Disponibilité UE / tenant FR, Impact admin M365. |
| R05 | Ancien rapport | Ouvrir un rapport au format « ## 1. Nouveautés majeures » s'il en existe | Affiché en markdown simple, sans erreur. |
| R06 | Sauvegarder une news | « Sauvegarder » sur une carte, puis onglet News sauvegardées | La news apparaît ; « Retirer » la retire. |
| R07 | Notes | Sélectionner un passage → « Ajouter aux notes » | Note visible dans le rapport et dans l'onglet Notes ; suppression possible. |
| R08 | Export PDF | « Exporter en PDF » sur une veille et sur une veille Copilot | PDF téléchargé, titre « AI Technical Watch » ou « Veille Microsoft Copilot », titres et tableaux lisibles. |
| R09 | Newsletter | « Newsletter » | Onglet avec la newsletter (bandeau bleu nuit, executive summary, cartes colorées par acteur, encadré sécurité) ; « La veille Microsoft Copilot » pour une veille Copilot. |
| R10 | Recherches | Recherches → poser « Que faut-il tester cette semaine ? » | Réponse en français avec citations « (Rapport N · section) » ; les rapports proposés par défaut incluent la dernière veille Copilot. **LLM** |
| R11 | Suppression | Supprimer un rapport de test | Disparaît de l'historique ; ses news sauvegardées restent avec « rapport supprimé ». |
| R12 | Jeton d'API (si `API_TOKEN` testé) | `curl -i localhost:8000/reports` sans en-tête | 401 ; l'interface fonctionne avec `VITE_API_TOKEN` identique. |

### Génération des veilles

| # | Cas | Étapes | Attendu |
| --- | --- | --- | --- |
| R20 | Veille quotidienne | « Lancer la veille » | Le bouton passe en « Analyse en cours… » ; après quelques minutes le rapport s'ouvre. Toutes les sections présentes, une source datée par nouveauté, dates dans les dernières 24 h. **LLM** |
| R21 | Une génération à la fois | Pendant R20 : les deux boutons de génération sont grisés ; `curl -i -X POST localhost:8000/reports/copilot/trigger` | Boutons inactifs ; l'API répond 409 « Une génération de veille est déjà en cours ». |
| R22 | Pas de répétition | Relancer une veille le même jour | Les sujets déjà couverts ne reviennent pas, sauf préfixés « Mise à jour : ». **LLM** |
| R23 | Veille Microsoft Copilot | « Veille Microsoft Copilot » | Rapport sur 7 jours, items Microsoft 365 Copilot / Copilot Studio / Work IQ / Cowork quand il y a de l'actualité, identifiants Roadmap, sources Microsoft datées. Log `Roadmap : N éléments Copilot ajoutés au prompt`. **LLM** |
| R24 | Roadmap indisponible | `COPILOT_ROADMAP_ENABLED=false`, relancer R23 | La veille se génère (recherche web seule), sans section Roadmap dans le prompt. **LLM** |
| R25 | Reddit (si activé en production) | `GET http://localhost:8000/reddit/preview` puis une veille avec `REDDIT_ENABLED=true` | L'aperçu liste des posts ou une erreur claire (429 / 403) ; la veille se génère dans les deux cas. |
| R26 | Cron quotidien | `curl -X POST --max-time 900 localhost:8000/cron/daily` deux fois | 1er appel : `created: true` (ou `false` si R20 a déjà tourné) ; 2e : `created: false`, même `report_id`. |
| R27 | Cron hebdomadaire | `curl -X POST --max-time 900 localhost:8000/cron/copilot-weekly` deux fois | Ne regénère pas une veille Copilot de moins de 7 jours (`created: false`). |
| R28 | Note CODIR | « Générer la note CODIR » sur une veille, puis « Exporter en Word » | Note d'une page (synthèse, décisions, vigilance) ; le .docx s'ouvre correctement. **LLM** |
| R29 | Résumé, détail, définition | « Résumé exécutif » ; sélectionner un terme → « Approfondir », « Définir » | Résumé de 5 points avec « Décision suggérée » ; détail et définition enregistrés comme notes. **LLM** |

### Newsletter et mail

Avec le serveur SMTP de test.

| # | Cas | Étapes | Attendu |
| --- | --- | --- | --- |
| R40 | Mail non configuré | `SMTP_HOST` vide, relancer le backend | « Envoyer par mail » grisé, info-bulle listant les variables manquantes ; `POST /reports/{id}/send` → 503. |
| R41 | Envoi manuel | Configuration de test, « Envoyer par mail » → confirmer | Message de succès ; le terminal aiosmtpd affiche un mail `multipart/alternative` (texte + HTML), objet « Veille IA – <date> ». Le bouton devient « Renvoyer par mail ». |
| R42 | Veille Copilot | Envoyer une veille Copilot | Objet « Veille Microsoft Copilot – <date> ». |
| R43 | Rendu réel | Envoyer à une vraie boîte (votre adresse, vrai SMTP) et ouvrir dans Outlook et Gmail | Mise en page conservée (couleurs, cartes, largeur), accents corrects. |
| R44 | Envoi automatique | `MAIL_AUTO_SEND=true`, `POST /cron/daily?force=true` puis `POST /cron/daily` | 1er : nouvelle veille et `mail_sent: true` ; 2e : `created: false`, `mail_sent: false`, aucun second mail. **LLM** |
| R45 | Échec SMTP | Arrêter aiosmtpd, envoyer | Erreur claire (502) ; `newsletter_sent_at` inchangé. |
| R46 | Secret | `GET /mail/info`, logs du backend | Ni mot de passe ni adresses des destinataires. |

### Données de production

Sur la copie de la base de production.

| # | Cas | Étapes | Attendu |
| --- | --- | --- | --- |
| R60 | Migration | Démarrer le backend sur la copie | Démarrage sans erreur ; les nouvelles colonnes existent (`PRAGMA table_info(reports)`). |
| R61 | Données conservées | Parcourir rapports, news sauvegardées, notes, historique des recherches | Tout est présent et s'affiche, y compris les anciens rapports. |
| R62 | Fonctionnement | Dérouler R03, R08, R09 sur des rapports de production | Identique à la base de test. |

### Build de production

Quand les fichiers de déploiement changent (`compose.yml`, `frontend/Dockerfile.prod`, `frontend/nginx.conf`, `backend/Dockerfile`).

| # | Cas | Étapes | Attendu |
| --- | --- | --- | --- |
| R70 | Image frontend | `docker build -f frontend/Dockerfile.prod -t veilleia-frontend-recette frontend` | Build sans erreur. |
| R71 | Service statique | `docker run --rm -p 8080:80 veilleia-frontend-recette`, ouvrir http://localhost:8080 | L'interface se charge ; un rechargement sur une URL profonde renvoie `index.html` (pas de 404 nginx). Les appels partent vers `/api` (onglet Réseau). |
| R72 | Image backend | `docker build -t veilleia-backend-recette backend` puis `docker run --rm veilleia-backend-recette codex --version` | Build sans erreur ; version de Codex notée dans le PV (elle sera celle de la production). |

## Procès-verbal de recette

À recopier dans la PR ou dans la carte du board avant la mise en production.

```text
Recette VeilleIA
Version : <sha court> — <titre du commit>      Date : AAAA-MM-JJ      Recetteur : <nom>
Fournisseur LLM : codex <version>               Base : test / copie de production du AAAA-MM-JJ

Contrôles automatiques : A1 OK (N tests)  A2 OK  A3 OK  A4 OK
Cas : R01 OK  R02 OK  R03 OK  … (KO et non testés listés ci-dessous)

Anomalies :
- <cas> — <constat> — bloquante / non bloquante

Décision : bon pour la production / ajourné
```

Règles de décision :

- **Bloquant** : un contrôle automatique KO, une donnée de production perdue ou illisible (R60 à R62), un mail parti vers une mauvaise adresse, une génération de veille impossible, un secret exposé.
- **Non bloquant** : défaut d'affichage mineur, contenu LLM perfectible (à reprendre dans le prompt), fonction optionnelle désactivée en production.

Après la décision « bon pour la production » : [mise en production](PRODUCTION.md#mise-en-production), puis [vérification après déploiement](PRODUCTION.md#vérification-après-déploiement).
