# Documentation — Veille IA

Veille IA (« AI Technical Watch ») génère chaque jour une veille technique sur l'IA à l'aide d'un LLM capable de chercher sur le web (Codex CLI par défaut), la stocke en SQLite et la présente dans une interface React : lecture structurée, résumés, notes, news sauvegardées, recherche conversationnelle sur les rapports, note CODIR, exports PDF / Word et newsletter HTML.

## Sommaire

| Page | Contenu | Pour qui |
| --- | --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Vue d'ensemble, rôle de chaque fichier, modèle de données, couche LLM, flux clés | Développeurs |
| [API.md](API.md) | Les 28 endpoints HTTP, authentification, codes d'erreur | Développeurs, intégrateurs (cron) |
| [CONFIGURATION.md](CONFIGURATION.md) | Toutes les variables d'environnement, défauts et effets | Développeurs, exploitation |
| [FONCTIONNEL.md](FONCTIONNEL.md) | Les vues de l'application, les cas d'usage, la structure d'un rapport | Utilisateurs, product owner |
| [RECETTE.md](RECETTE.md) | Validation d'une version avant mise en production : environnement, contrôles automatiques, cas fonctionnels, procès-verbal | Recetteurs, développeurs |
| [PRODUCTION.md](PRODUCTION.md) | Production sur le NAS : architecture Cloudflare / Traefik, installation, mise en production, vérification, crons, sauvegarde, retour arrière | Exploitation |
| [EXPLOITATION.md](EXPLOITATION.md) | Lancement local, conteneurs, cron quotidien, tests, dépannage | Exploitation, développeurs |

## Démarrage rapide

```bash
npm install -g @openai/codex && codex login   # fournisseur LLM par défaut
./dev.sh                                       # backend :8000 + frontend :5173
```

Puis ouvrir http://localhost:5173 et cliquer sur « Lancer la veille ». Détails dans [EXPLOITATION.md](EXPLOITATION.md).

## Specs et plans existants

Historique des décisions de conception (rédigés avant certaines évolutions ; le code fait foi en cas d'écart) :

- [docs/superpowers/specs/2026-04-01-dark-tech-redesign-design.md](superpowers/specs/2026-04-01-dark-tech-redesign-design.md) — ancien thème « dark tech », remplacé depuis par la charte APRIL.
- [docs/superpowers/plans/2026-04-01-dark-tech-redesign.md](superpowers/plans/2026-04-01-dark-tech-redesign.md) — plan d'implémentation du thème dark tech.
- [docs/superpowers/specs/2026-06-19-prompts-veille-ia-design.md](superpowers/specs/2026-06-19-prompts-veille-ia-design.md) — refonte « décision d'abord » des prompts de veille.
- [docs/superpowers/plans/2026-06-19-prompts-veille-ia.md](superpowers/plans/2026-06-19-prompts-veille-ia.md) — plan d'implémentation de cette refonte.

## Autres références

- [README.md](../README.md) à la racine : présentation courte et installation.
- [CLAUDE.md](../CLAUDE.md) : consignes pour les agents de code (conventions, pièges connus).
- Documentation OpenAPI générée par FastAPI : http://localhost:8000/docs (backend lancé).
