from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR / "SKILL.md"


def test_every_documented_template_source_exists():
    sources = (
        "templates/dashboard-data.json.template",
        "templates/harness-dashboard-components.js.template",
        "templates/harness-dashboard-components.css.template",
        "templates/harness-dashboard-theme.css.template",
        "templates/public/noindex-head.html.template",
        "templates/publish_surge.sh.template",
    )
    skill = SKILL.read_text(encoding="utf-8")
    for source in sources:
        assert source in skill
        assert (SKILL_DIR / source).is_file()
