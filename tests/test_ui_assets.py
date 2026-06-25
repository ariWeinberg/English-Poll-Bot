from pathlib import Path


def test_ui_template_contains_core_controls():
    dashboard = Path("app/templates/dashboard.html").read_text()
    texts = Path("app/templates/texts.html").read_text()
    login = Path("app/templates/login.html").read_text()
    landing = Path("app/templates/landing.html").read_text()

    assert "English WhatsApp Poll Bot" in landing
    assert 'action="/login"' in login
    assert 'action="/tenants/save"' in dashboard
    assert 'action="/texts/save"' in texts
    assert 'action="/polls/send-now"' in texts
    assert 'action="/summaries/send-now"' in texts
