import inspect

from app.main import append_markdown_pdf_elements, build_pdf_styles, TECHNICAL_PROMPT, CODIR_NOTE_PROMPT
from app.main import summarize_report


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


def test_codir_prompt_keeps_format_placeholder():
    # le placeholder doit survivre pour .format(watch_document=...)
    assert "{watch_document}" in CODIR_NOTE_PROMPT


def test_codir_prompt_references_new_section_name():
    assert "Signaux faibles" in CODIR_NOTE_PROMPT


def test_summary_prompt_is_decision_first():
    src = inspect.getsource(summarize_report)
    # toujours présents
    assert "Décision suggérée" in src
    assert "5 points maximum" in src
    # nouvelle logique
    assert "TL;DR" in src
    assert "radar décisionnel" in src.lower()
