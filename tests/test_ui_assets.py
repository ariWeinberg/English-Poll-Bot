from pathlib import Path


def test_react_ui_and_nginx_proxy_are_configured():
    app = Path("web/src/main.tsx").read_text()
    nginx = Path("web/nginx.conf").read_text()
    package = Path("web/package.json").read_text()

    assert 'const API_BASE = "/api/v1"' in app
    assert "localStorage" in app
    assert "Authorization" in app
    assert 'type View = "dashboard" | "texts" | "polls" | "settings"' in app
    assert "Poll Stats" in app
    assert "Vote History" in app
    assert "Edit Text" in app
    assert "Edit Poll" in app
    assert "Edit Tenant" in app
    assert "proxy_pass http://api:8000/api/" in nginx
    assert "proxy_pass http://api:8000/webhooks/" in nginx
    assert '"build": "tsc && vite build"' in package
