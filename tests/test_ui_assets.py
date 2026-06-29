from pathlib import Path


def test_react_ui_and_nginx_proxy_are_configured():
    entry = Path("web/src/main.tsx").read_text()
    nginx = Path("web/nginx.conf").read_text()
    package = Path("web/package.json").read_text()
    api = Path("web/src/lib/api.ts").read_text()
    src_bundle = (
        "\n".join(path.read_text() for path in Path("web/src").rglob("*.tsx"))
        + "\n"
        + "\n".join(path.read_text() for path in Path("web/src").rglob("*.ts"))
    )

    assert 'const API_BASE = "/api/v1"' in api
    assert "localStorage" in api
    assert "Authorization" in api
    assert '"/register"' in src_bundle
    assert "Workspace Settings" in src_bundle
    assert "Chat Allowlist / Blocklist" in src_bundle
    assert "Refresh chats" in src_bundle
    assert "Select a group chat" in src_bundle
    assert "Learner Progress Dashboard" in src_bundle
    assert "Recent Answer History" in src_bundle
    assert "Recent Missed Polls" in src_bundle
    assert "Participation and accuracy" in src_bundle
    assert "Group Roster" in src_bundle
    assert "Participation Coverage" in src_bundle
    assert "Coverage membership" in src_bundle
    assert "Assigned vs responded" in src_bundle
    assert "Poll Events" in src_bundle
    assert "Current Vote Status" in src_bundle
    assert "formatVoteContact" in src_bundle
    assert "phone_number" in src_bundle
    assert "voter_name" in src_bundle
    assert "changed" in src_bundle
    assert "retracted vote from" in src_bundle
    assert "Change window minutes" in src_bundle
    assert "Auto-lock minutes" in src_bundle
    assert "Poll Pool" in src_bundle
    assert '"/doc"' in src_bundle
    assert "Operations Docs" in src_bundle
    assert "Open Swagger" in src_bundle
    assert "/docs/session" in src_bundle
    assert "LOG_REQUEST_BODY_ENABLED" in src_bundle
    assert "Refill pool" in src_bundle
    assert "Pool threshold percent used" in src_bundle
    assert "Preview next poll" in src_bundle
    assert "Lock poll manually" in src_bundle
    assert "Edit Text" in src_bundle
    assert "Schedule rules" in src_bundle
    assert "Reusable Rules" in src_bundle
    assert "Assign existing rule" in src_bundle
    assert "Auto-create matching summary rule" in src_bundle
    assert "Manual only" in src_bundle
    assert "Edit Poll" in src_bundle
    assert "Edit Workspace" in src_bundle
    assert "Leave blank to keep current password" in src_bundle
    assert 'import { App } from "./App"' in entry
    assert "proxy_pass http://api:8000/api/" in nginx
    assert "proxy_pass http://api:8000/webhooks/" in nginx
    assert '"build": "tsc && vite build"' in package
