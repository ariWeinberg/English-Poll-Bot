from pathlib import Path


def test_react_ui_and_nginx_proxy_are_configured():
    app = Path("web/src/App.tsx").read_text()
    entry = Path("web/src/main.tsx").read_text()
    nginx = Path("web/nginx.conf").read_text()
    package = Path("web/package.json").read_text()

    assert 'const API_BASE = "/api/v1"' in app
    assert "localStorage" in app
    assert "Authorization" in app
    assert '"/register"' in app
    assert "Workspace Settings" in app
    assert "Poll Events" in app
    assert "Current Vote Status" in app
    assert "formatVoteContact" in app
    assert "phone_number" in app
    assert "voter_name" in app
    assert "changed" in app
    assert "retracted vote from" in app
    assert "Change window minutes" in app
    assert "Auto-lock minutes" in app
    assert "Poll Pool" in app
    assert "Refill pool" in app
    assert "Pool threshold percent used" in app
    assert "Preview next poll" in app
    assert "Lock poll manually" in app
    assert "Edit Text" in app
    assert "Edit Poll" in app
    assert "Edit Workspace" in app
    assert "Leave blank to keep current password" in app
    assert 'import { App } from "./App"' in entry
    assert "proxy_pass http://api:8000/api/" in nginx
    assert "proxy_pass http://api:8000/webhooks/" in nginx
    assert '"build": "tsc && vite build"' in package
