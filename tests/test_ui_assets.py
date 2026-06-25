from pathlib import Path


def test_ui_template_contains_core_controls():
    html = Path("app/templates/index.html").read_text()

    assert "English WhatsApp Poll Bot" in html
    assert 'action="/tenants/save"' in html
    assert 'action="/texts/save"' in html
    assert 'action="/polls/send-now"' in html
    assert 'action="/summaries/send-now"' in html
