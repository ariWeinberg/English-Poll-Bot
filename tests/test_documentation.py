from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_architecture_documentation_tracks_quality_gates():
    docs = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    required_commands = [
        "python -m compileall app tests",
        "ruff check app tests",
        "ruff format --check app tests",
        "pytest",
        "npm run typecheck",
        "npm run build",
        "docker compose config --quiet",
    ]
    for command in required_commands:
        assert command in docs


def test_readme_lists_canonical_quality_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "ruff check app tests" in readme
    assert "ruff format --check app tests" in readme
    assert "npm run typecheck" in readme
    assert "docker compose config --quiet" in readme
    assert "POST /api/v1/docs/session" in readme
    assert "/api/v1/readiness" in readme
    assert "provider diagnostics" in readme.lower()
    assert "LOG_REQUEST_BODY_ENABLED" in readme
    assert "/doc" in readme


def test_runbook_documents_operations_surfaces():
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")

    assert "/api/v1/docs/session" in runbook
    assert "/api/v1/readiness" in runbook
    assert "LOG_FILE" in runbook
    assert "scheduler" in runbook.lower()
    assert "/webhooks/greenapi/{tenant_id}" in runbook
    assert "/webhooks" in runbook
    assert "accepted" in runbook
    assert "ignored" in runbook
    assert "error" in runbook
    assert "retried" in runbook.lower()
    assert "provider diagnostics" in runbook.lower()
    assert "question review" in runbook.lower()


def test_roadmap_document_captures_the_execution_tracks():
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")

    required_sections = [
        "Security and Production Hardening",
        "Provider Reliability Lab",
        "Webhook and Scheduler Operations",
        "Question Quality System",
        "Learning Intelligence",
        "Curriculum and Content Model",
        "Teacher Workflow Productization",
        "Scale Architecture",
        "Pilot Readiness and Expansion",
        "Micro-Commit Shape",
    ]
    for section in required_sections:
        assert section in roadmap
