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
