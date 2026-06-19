# Refonte des prompts de veille IA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refondre le prompt de veille quotidien (`TECHNICAL_PROMPT`) vers une ossature « décision d'abord » avec couverture élargie et moins de bruit, corriger le renderer PDF pour les titres `### `, et mettre en cohérence la note CODIR et les prompts inline.

**Architecture:** Tout vit dans `backend/app/main.py` (app FastAPI mono-fichier). Les prompts sont des constantes/f-strings dans ce fichier. Le rendu PDF se fait via ReportLab dans `append_markdown_pdf_elements`. Le rendu .docx CODIR gère déjà tous les niveaux de titre `#`. Les tests sont des fichiers à la racine du repo (convention du projet), avec un `conftest.py` racine qui place `backend/` sur `sys.path` et isole la base SQLite.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / ReportLab / python-docx / Gemini ; pytest pour les tests ; copie 100 % française.

## Global Constraints

- Toute la copie utilisateur et le contenu des prompts sont en **français**. Conserver la langue exacte.
- Le sous-ensemble markdown rendu par le PDF (`append_markdown_pdf_elements`) et le front est : `## `, `### ` (après ce plan), `- `, `|` (tables), images `![alt](url)`. **Pas** de listes imbriquées, pas de `####`, pas de blocs de code clôturés.
- Le renderer .docx CODIR (`build_codir_docx`) gère déjà tout préfixe `#` via `clean_markdown_text` — ne pas y toucher.
- Ne pas introduire Alembic ni de migration de schéma (aucun changement de données).
- Garder la logique dans `main.py` ; ne pas éclater en modules (convention projet).
- Les endpoints restent protégés par `_=Depends(verify_token)` — ne pas modifier les signatures.
- Spec de référence : `docs/superpowers/specs/2026-06-19-prompts-veille-ia-design.md`.

---

## File Structure

- `backend/app/main.py` — modifié : `append_markdown_pdf_elements` (branche `### `), `TECHNICAL_PROMPT`, `CODIR_NOTE_PROMPT`, prompt inline `summary_prompt` (+ lissage `detail_prompt` / `definition_prompt`).
- `conftest.py` (racine) — créé : bootstrap `sys.path` + `DATABASE_URL` de test.
- `test_prompts_renderer.py` (racine) — créé : tests du renderer et des prompts.

---

### Task 1: Bootstrap de test + support `### ` dans le renderer PDF

**Files:**
- Create: `conftest.py`
- Create: `test_prompts_renderer.py`
- Modify: `backend/app/main.py:812` (fonction `append_markdown_pdf_elements`, lignes 781–825)

**Interfaces:**
- Consumes: `app.main.append_markdown_pdf_elements(elements: list, content: str, styles) -> None`, `app.main.build_pdf_styles() -> StyleSheet1` (style `WatchH3` déjà défini, ligne 674).
- Produces: après ce task, une ligne markdown `### Titre` produit un `reportlab.platypus.Paragraph` de style `WatchH3` ; rien d'autre ne change.

- [ ] **Step 1: Créer le bootstrap `conftest.py` à la racine**

Place `backend/` sur le path et isole la base SQLite pour ne pas polluer `sql_app.db`.

```python
import os
import sys

# Isoler la base SQLite des tests AVANT d'importer app.main (qui crée le schéma à l'import).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_app.db")

# Permettre "from app.main import ..." comme en exécution (uvicorn app.main:app lancé depuis backend/).
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
```

- [ ] **Step 2: Écrire le test qui échoue (renderer `### `)**

Créer `test_prompts_renderer.py` :

```python
from app.main import append_markdown_pdf_elements, build_pdf_styles


def test_h3_line_renders_as_watch_h3():
    styles = build_pdf_styles()
    elements = []
    append_markdown_pdf_elements(elements, "### À tester maintenant", styles)
    assert len(elements) == 1
    para = elements[0]
    assert para.style.name == "WatchH3"
    # le préfixe "### " doit être retiré du texte rendu
    assert "À tester maintenant" in para.text
    assert "###" not in para.text


def test_h2_still_renders_as_watch_h2():
    styles = build_pdf_styles()
    elements = []
    append_markdown_pdf_elements(elements, "## TL;DR", styles)
    assert elements[0].style.name == "WatchH2"
    assert "###" not in elements[0].text
```

- [ ] **Step 3: Lancer le test pour vérifier l'échec**

Run (depuis la racine, venv backend actif) :
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -v
```
Expected: `test_h3_line_renders_as_watch_h3` FAIL — le `### ` tombe dans la branche générique `WatchBody` (style `Normal`/`WatchBody`, pas `WatchH3`), donc `para.style.name != "WatchH3"`. `test_h2_still_renders_as_watch_h2` PASS.

- [ ] **Step 4: Ajouter la branche `### ` dans `append_markdown_pdf_elements`**

Dans `backend/app/main.py`, juste **avant** le bloc `if stripped.startswith("## "):` (ligne 812), insérer :

```python
        if stripped.startswith("### "):
            elements.append(Paragraph(pdf_text(stripped[4:]), styles["WatchH3"]))
            index += 1
            continue

```

(Le bloc existant `if stripped.startswith("## "):` qui suit reste inchangé. `"### x".startswith("## ")` vaut `False`, mais on teste `### ` en premier par clarté et robustesse.)

- [ ] **Step 5: Lancer les tests pour vérifier le succès**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -v
```
Expected: les 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add conftest.py test_prompts_renderer.py backend/app/main.py
git commit -m "fix(pdf): support des titres ### dans le renderer + bootstrap de test"
```

---

### Task 2: Réécrire `TECHNICAL_PROMPT` (ossature « décision d'abord »)

**Files:**
- Modify: `backend/app/main.py:394-514` (constante `TECHNICAL_PROMPT`)
- Modify: `test_prompts_renderer.py` (ajout d'un test de structure)

**Interfaces:**
- Consumes: rien (constante string).
- Produces: `app.main.TECHNICAL_PROMPT: str` contenant les sections `## TL;DR`, `## Radar décisionnel`, `## Nouveautés détaillées`, `## Signaux faibles & recherche`, et ne contenant plus `## 5. Filtre décisionnel`, `### A. Labs`, ni `## 3. Tableau de synthèse`.

- [ ] **Step 1: Écrire le test de structure qui échoue**

Ajouter dans `test_prompts_renderer.py` :

```python
from app.main import TECHNICAL_PROMPT


def test_technical_prompt_uses_decision_first_structure():
    for section in [
        "## TL;DR",
        "## Radar décisionnel",
        "### À tester maintenant",
        "### À surveiller",
        "### À ignorer",
        "## Nouveautés détaillées",
        "## Signaux faibles & recherche",
    ]:
        assert section in TECHNICAL_PROMPT, f"section manquante: {section}"


def test_technical_prompt_drops_legacy_sections():
    for legacy in [
        "## 2. Détail par catégorie",
        "### A. Labs / modèles",
        "## 3. Tableau de synthèse",
        "## 5. Filtre décisionnel",
        "10 éléments maximum",
    ]:
        assert legacy not in TECHNICAL_PROMPT, f"section legacy encore présente: {legacy}"
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -k technical -v
```
Expected: les 2 nouveaux tests FAIL (l'ancien prompt contient encore `## 2. Détail par catégorie`, etc.).

- [ ] **Step 3: Remplacer la constante `TECHNICAL_PROMPT`**

Dans `backend/app/main.py`, remplacer l'intégralité de la constante `TECHNICAL_PROMPT = """ … """` (lignes 394–514) par :

```python
TECHNICAL_PROMPT = """Tu produis une veille technique IA quotidienne couvrant les nouveautés publiées dans les dernières 24h.

# Périmètre de recherche

## Labs / model providers
OpenAI, Anthropic, Google, Meta, Mistral, Microsoft, AWS, xAI, Cohere, NVIDIA, DeepSeek, Alibaba (Qwen), et tout autre lab publiant un modèle marquant — y compris les modèles open-weight.

## AI coding / vibe coding / agents dev / open source
Cursor, Claude Code, Gemini CLI, Windsurf, Codeium, Cline, Continue, Aider, OpenHands, OpenCode, Roo Code, Bolt.new, Void, et tout outil coding/agent émergent (CLI, plugin IDE, agent de terminal, assistant self-hosted) qui monte vite, même immature.

## Écosystème connexe
MCP (Model Context Protocol), tool use / function calling, browse / search / computer use, plugins VS Code / JetBrains, local-first, self-hosted, Ollama, OpenRouter, frameworks d'orchestration d'agents, sandboxing / permissions / sécurité des agents, mémoire / long context / retrieval.

## Recherche
Publications de recherche marquantes (arXiv, blogs engineering des labs) ayant un impact pratique, pas seulement les releases produit.

# Objectif
Veille utile pour un profil architecture / plateforme / infra / sécurité / développement. Détecter vite les sorties réellement importantes, y compris l'open source émergent qui change les usages de développement, de prototypage ou de « vibe coding ».

# Consignes anti-bruit (strictes)
- Priorise les sources officielles : changelogs, documentation, releases GitHub, notes de version, billets engineering. Médias généralistes en source secondaire seulement.
- Sépare clairement les faits confirmés des suppositions ou annonces vagues.
- Ne retiens que ce qui a un impact technique réel et une disponibilité réelle (pas seulement annoncé).
- Ce qui est purement marketing : écarte-le en une seule ligne, ne le développe jamais.
- Indique toujours le niveau de maturité réel : prototype / alpha / bêta / GA / production-ready / expérimental.
- Mieux vaut 4 items solides que 12 dilués : le nombre d'items s'adapte à l'actualité du jour, sans plafond fixe.

# Ancrage April (quand c'est pertinent)
Quand une nouveauté touche notre stack (Dagster, Snowflake, Azure, M365) ou un cas d'usage assurance, relie-la explicitement. Ne force pas ce lien quand il n'existe pas.

# Format de sortie obligatoire
N'utilise que ce sous-ensemble markdown : titres `## ` et `### `, puces `- `, tableaux `|`. Pas de listes imbriquées, pas de `####`, pas de blocs de code.

## TL;DR
- 3 puces maximum : l'essentiel du jour, formulé pour décider vite.

## Radar décisionnel

### À tester maintenant
- ce qui est dispo et mérite un essai immédiat (1 ligne par item)

### À surveiller
- ce qui n'est pas encore mûr mais potentiellement structurant

### À ignorer
- ce qui est du bruit / marketing, écarté en une ligne avec la raison

## Nouveautés détaillées
Trie les items par impact réel (pas par catégorie). Un `### ` par nouveauté, puis des puces plates :

### <Titre court de la nouveauté>
- Ce qui sort
- Pourquoi c'est important techniquement
- Pour qui / impact architecture - plateforme - sécurité
- Maturité (prototype / alpha / bêta / GA / production-ready)
- Ancrage April (lien stack Dagster / Snowflake / Azure / M365 ou cas assurance, si pertinent)
- Action recommandée

## Signaux faibles & recherche
- repos GitHub qui montent vite
- publications de recherche / blogs engineering marquants (avec l'apport pratique)
- sujets à recontrôler dans les prochains jours
"""
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -v
```
Expected: tous les tests PASS (structure + legacy absente + renderer du Task 1).

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py test_prompts_renderer.py
git commit -m "feat(prompt): ossature décision-d-abord pour la veille quotidienne"
```

---

### Task 3: Mettre `CODIR_NOTE_PROMPT` en cohérence

**Files:**
- Modify: `backend/app/main.py:517-567` (constante `CODIR_NOTE_PROMPT`)
- Modify: `test_prompts_renderer.py` (ajout d'un test)

**Interfaces:**
- Consumes: `app.main.CODIR_NOTE_PROMPT: str` (contient `{watch_document}`, utilisé via `.format(watch_document=…)` ligne 1389 — ne pas casser ce placeholder).
- Produces: `CODIR_NOTE_PROMPT` qui référence « Signaux faibles & recherche » au lieu de « à surveiller », `{watch_document}` toujours présent.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter dans `test_prompts_renderer.py` :

```python
from app.main import CODIR_NOTE_PROMPT


def test_codir_prompt_keeps_format_placeholder():
    # le placeholder doit survivre pour .format(watch_document=...)
    assert "{watch_document}" in CODIR_NOTE_PROMPT


def test_codir_prompt_references_new_section_name():
    assert "Signaux faibles" in CODIR_NOTE_PROMPT
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -k codir -v
```
Expected: `test_codir_prompt_references_new_section_name` FAIL (le prompt actuel dit « à surveiller », pas « Signaux faibles ») ; `test_codir_prompt_keeps_format_placeholder` PASS.

- [ ] **Step 3: Mettre à jour la contrainte dure du prompt CODIR**

Dans `backend/app/main.py`, dans `CODIR_NOTE_PROMPT`, remplacer le bloc `# CONTRAINTE DURE` (lignes 557–559) :

Ancien :
```
# CONTRAINTE DURE
1 page A4 stricte. Si dépassement, sacrifier d'abord les "à surveiller", 
puis raccourcir la synthèse. Jamais réduire le tableau de décisions.
```

Nouveau :
```
# CONTRAINTE DURE
1 page A4 stricte. Si dépassement, sacrifier d'abord les éléments « Signaux faibles & recherche » du rapport, 
puis raccourcir la synthèse. Jamais réduire le tableau de décisions.
```

(Le reste du prompt CODIR — rôle, audience, règles de traduction, structure, contraintes visuelles, format de sortie, `{watch_document}` — reste inchangé.)

- [ ] **Step 4: Lancer pour vérifier le succès**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -k codir -v
```
Expected: les 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py test_prompts_renderer.py
git commit -m "chore(prompt): cohérence note CODIR avec la nouvelle ossature"
```

---

### Task 4: Aligner le prompt inline `summary` (+ lissage detail/definition)

**Files:**
- Modify: `backend/app/main.py:1103-1118` (`summary_prompt` dans `summarize_report`)
- Modify: `backend/app/main.py:1154-1170` (`detail_prompt`) — lissage mineur
- Modify: `backend/app/main.py:1193-1210` (`definition_prompt`) — lissage mineur
- Modify: `test_prompts_renderer.py` (ajout d'un test via `inspect`)

**Interfaces:**
- Consumes: `app.main.summarize_report` (endpoint, fonction définie ligne 1097). Le `summary_prompt` est une f-string locale interpolant `{db_report.content}`.
- Produces: la source de `summarize_report` mentionne la logique « décision d'abord » (TL;DR / radar) ; conserve « Décision suggérée : » et « 5 points maximum ».

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter dans `test_prompts_renderer.py` :

```python
import inspect
from app.main import summarize_report


def test_summary_prompt_is_decision_first():
    src = inspect.getsource(summarize_report)
    # toujours présents
    assert "Décision suggérée" in src
    assert "5 points maximum" in src
    # nouvelle logique
    assert "TL;DR" in src
    assert "radar décisionnel" in src.lower()
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -k summary -v
```
Expected: FAIL — la source actuelle ne contient ni « TL;DR » ni « radar décisionnel ».

- [ ] **Step 3: Mettre à jour `summary_prompt`**

Dans `backend/app/main.py`, remplacer la f-string `summary_prompt` (lignes 1103–1118) par :

```python
    summary_prompt = f"""Tu reçois un rapport de veille IA déjà rédigé, structuré « décision d'abord » (TL;DR, radar décisionnel, nouveautés détaillées, signaux faibles).

Ta tâche : produire un executive summary court, sans refaire de recherche.

Contraintes :
- utilise uniquement le contenu fourni ci-dessous
- pas de nouvelles affirmations externes
- appuie-toi en priorité sur le TL;DR et le radar décisionnel du rapport
- 5 points maximum
- ton très concret, orienté architecture / plateforme / sécurité / delivery
- termine par une ligne `Décision suggérée : ...`

Rapport :

{db_report.content}
"""
```

- [ ] **Step 4: Lissage mineur de `detail_prompt`**

Dans `backend/app/main.py`, dans `detail_prompt` (ligne 1154), remplacer la première ligne :

Ancien :
```
Tu reçois un rapport de veille déjà rédigé et un extrait sélectionné par l'utilisateur.
```
Nouveau :
```
Tu reçois un rapport de veille IA déjà rédigé (structuré « décision d'abord ») et un extrait sélectionné par l'utilisateur.
```

- [ ] **Step 5: Lissage mineur de `definition_prompt`**

Dans `backend/app/main.py`, dans `definition_prompt` (ligne 1193), remplacer la première ligne :

Ancien :
```
Tu reçois un rapport de veille IA déjà rédigé et un terme ou extrait sélectionné par l'utilisateur.
```
Nouveau :
```
Tu reçois un rapport de veille IA déjà rédigé (structuré « décision d'abord ») et un terme ou extrait sélectionné par l'utilisateur.
```

- [ ] **Step 6: Lancer toute la suite pour vérifier le succès**

Run:
```bash
cd backend && source venv/bin/activate && cd .. && python -m pytest test_prompts_renderer.py -v
```
Expected: tous les tests PASS.

- [ ] **Step 7: Vérifier qu'`app.main` s'importe toujours sans erreur**

Run:
```bash
cd backend && source venv/bin/activate && python -c "from app.main import app; print('import OK')"
```
Expected: `import OK` (aucune erreur de syntaxe dans les f-strings modifiées).

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py test_prompts_renderer.py
git commit -m "feat(prompt): aligner résumé/détail/définition sur la nouvelle ossature"
```

---

## Nettoyage

- [ ] **Étape finale : retirer la base de test si créée**

Run:
```bash
rm -f test_app.db
```
(Ne pas committer `test_app.db`. Si besoin, l'ajouter à `.gitignore`.)

---

## Notes de vérification manuelle (hors TDD)

Le contenu produit par Gemini ne peut pas être testé unitairement (sortie LLM non déterministe). Après implémentation, vérification manuelle recommandée :
1. Déclencher un rapport (`POST /reports/trigger`) et vérifier que la sortie suit l'ossature `## TL;DR` / `## Radar décisionnel` / `## Nouveautés détaillées` / `## Signaux faibles & recherche`.
2. Exporter le PDF du rapport et confirmer que les `### ` s'affichent comme sous-titres (style WatchH3) et non en littéral `### …`.
3. Générer une note CODIR et confirmer qu'elle reste sur 1 page A4.
