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
