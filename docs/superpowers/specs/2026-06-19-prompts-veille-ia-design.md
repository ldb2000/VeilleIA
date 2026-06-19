# Refonte des prompts de veille techno IA

Date : 2026-06-19
Statut : validé (design), prêt pour planification d'implémentation

## Contexte

L'app « Veille IA » génère un rapport de veille technique quotidien via Gemini
(`TECHNICAL_PROMPT`), une note hebdomadaire CODIR (`CODIR_NOTE_PROMPT`), et
expose des prompts inline (résumé, détail, définition, chat) qui exploitent un
rapport déjà généré. Tous ces prompts vivent dans `backend/app/main.py`.

Problèmes constatés sur les rapports actuels :

1. **Trop de bruit / pas assez pertinent** — annonces marketing développées au
   même titre que les vraies nouveautés techniques.
2. **Format / structure inadapté** — la structure en 5 sections (dont « Détail
   par catégorie » A/B/C et un gros tableau de synthèse) ne correspond pas à un
   usage « décision rapide ».
3. **Couverture incomplète** — plafond rigide de 10 éléments, acteurs/outils
   manquants, pas de veille recherche (arXiv / blogs eng), pas d'ancrage sur la
   stack et les cas d'usage April.

Objectif : refonte réelle du prompt quotidien, et mise en cohérence des autres
prompts pour qu'ils ne renvoient plus à des sections disparues.

## Contrainte technique découverte (renderer)

Le renderer PDF ReportLab (`build_pdf_story` ~ligne 847, et
`append_markdown_pdf_elements` ~ligne 786) ne reconnaît que les préfixes
`## `, `- `, `|` et les images. Il **ne gère pas `### `** : les lignes `### …`
sont actuellement rendues littéralement dans le PDF (les `###` apparaissent).
La nouvelle ossature s'appuyant fortement sur `### `, il faut corriger ce point.

Les sous-listes imbriquées (`  - x`) sont déjà aplaties en puce simple après
`.strip()` (perte d'indentation, sans casse). On conçoit donc le prompt **sans
imbrication** : chaque item = un titre `### ` suivi de puces plates.

Le front (react-markdown + remark-gfm) gère déjà `###` nativement — aucun
changement UI nécessaire.

## Décisions

### 1. `TECHNICAL_PROMPT` — nouvelle ossature « décision d'abord »

Structure de sortie cible (sous-ensemble markdown supporté : `## `, `### `,
`- `, `|`) :

```
## TL;DR
- 3 puces max, l'essentiel du jour

## Radar décisionnel
### À tester maintenant
### À surveiller
### À ignorer

## Nouveautés détaillées        (triées par impact, plus par catégorie)
### <Titre de la nouveauté>     (un ### par item ; pas de plafond fixe)
- Ce qui sort
- Pourquoi c'est important techniquement
- Pour qui / impact architecture-plateforme-sécurité
- Maturité (prototype / alpha / bêta / GA / production-ready)
- Ancrage April (lien stack Dagster/Snowflake/Azure/M365 ou cas assurance, si pertinent)
- Action recommandée

## Signaux faibles & recherche
- repos GitHub qui montent, papers/blogs engineering marquants, sujets à recontrôler
```

Changements de fond :

- **Plafond « 10 max » supprimé.** Nombre d'items variable, piloté par l'impact
  réel. Règle explicite : « mieux vaut 4 items solides que 12 dilués ».
- **Anti-bruit renforcé.** Tout ce qui est purement marketing est écarté en une
  ligne, jamais développé. Priorité maintenue aux sources officielles,
  changelogs, releases GitHub, notes de version, billets engineering ; médias
  généralistes en source secondaire ; faits confirmés séparés des suppositions.
- **Couverture élargie** : ajout explicite des modèles open-weight et d'outils
  coding/agents émergents non listés ; intégration d'une veille recherche
  (arXiv / blogs engineering) dans « Signaux faibles & recherche », au-delà des
  seules releases produit.
- **Ancrage April** : chaque item détaillé peut relier la nouveauté à la stack
  (Dagster, Snowflake, Azure, M365) et aux usages assurance — sans forcer quand
  ce n'est pas pertinent.
- **Suppression** de la section « Détail par catégorie » (A/B/C) et du gros
  tableau de synthèse, remplacés par le flux priorisé par impact.
- Conserver les listes de surveillance existantes (labs/providers, outils
  coding, écosystème MCP/agents) comme **périmètre de recherche** en tête de
  prompt, mais elles ne dictent plus la structure de sortie.
- Toute la copie reste en français.

### 2. Renderer — support de `### `

- Ajouter la gestion de `### ` dans `append_markdown_pdf_elements` et
  `build_pdf_story`, mappé sur le style `WatchH3` déjà défini (utilisé pour les
  notes). Tester `### ` **avant** `## ` dans chaque fonction (une branche par
  fonction), pour éviter toute ambiguïté de préfixe.
- Aucune gestion d'imbrication ajoutée (prompt conçu sans listes imbriquées).
- Aucun changement front.

### 3. `CODIR_NOTE_PROMPT` — mise en cohérence

- Mettre à jour les renvois de structure vers la nouvelle ossature (« à
  surveiller » → « Signaux faibles & recherche »).
- Conserver intacts : audience CODIR, contrainte 1 page A4 stricte, règles de
  traduction technique→business, contraintes visuelles et rendu .docx.
- Pas de refonte de fond.

### 4. Prompts inline — alignement ciblé

- **summary** : caler l'executive summary sur la logique « décision d'abord »
  (s'appuyer sur le TL;DR et le radar décisionnel du rapport). Garder : 5 points
  max, ligne `Décision suggérée : …`, pas de recherche externe.
- **detail** : inchangé sur le fond, léger lissage de formulation.
- **definition** : inchangé sur le fond, léger lissage de formulation.
- **chat** : inchangé (déjà robuste à la structure).

## Hors périmètre (YAGNI)

- Pas d'Alembic / migration de schéma (aucun changement de données).
- Pas de refonte du backend Gemini ni des endpoints.
- Pas de tableau de synthèse réintroduit (sauf demande ultérieure explicite).
- Pas de gestion de listes markdown imbriquées dans le renderer.

## Critères de réussite

- Le rapport quotidien généré suit la nouvelle ossature et se rend correctement
  en PDF (titres `### ` rendus comme sous-titres, pas littéralement) et dans le
  front.
- Aucun item purement marketing développé ; nombre d'items proportionné à
  l'actualité.
- La note CODIR ne renvoie plus à une section inexistante.
- Les prompts inline fonctionnent sur un rapport à la nouvelle structure.
- `npm run build` (typecheck front) et démarrage backend OK ; pas de régression
  de rendu.
