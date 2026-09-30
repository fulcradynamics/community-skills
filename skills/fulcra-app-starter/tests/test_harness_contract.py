"""Credential-free checks for the app-starter's mandatory harness contract.

Run: python -m unittest discover -s skills/fulcra-app-starter/tests -v
Live CLI verification is documented in references/record-command-verification.md.
"""
import json
from pathlib import Path
import re
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HarnessContractTests(unittest.TestCase):
    def test_harness_starts_before_clone(self):
        skill = (ROOT / "SKILL.md").read_text()
        self.assertLess(skill.index("### 5. Start the First Harness Run"),
                        skill.index("git clone"))
        self.assertIn("M1 — Working baseline and harness dashboard", skill)
        self.assertNotIn("### 10. Run Harness", skill)

    def test_resume_instructions_require_harness(self):
        skill = (ROOT / "SKILL.md").read_text()
        agents = skill.split("# Agent Information", 1)[1].split("```", 1)[0]
        for required in ("decisions.md", "harness", "evaluation", "history"):
            self.assertIn(required, agents)

    def test_dashboard_handoff_gate(self):
        setup = (ROOT / "references/harness-dashboard-setup.md").read_text()
        for required in ("M1", "RUN_START", "REVIEW", "RUN_COMPLETE",
                         "non-owner", "Do not present an empty dashboard"):
            self.assertIn(required, setup)

    def test_record_example_is_explicit_stdin_with_string_note(self):
        flow = (ROOT / "references/harness-control-flow.md").read_text()
        section = flow.split("## Recording Run Events", 1)[1].split("### Run Start", 1)[0]
        match = re.search(r"```bash\n(.*?)\n```", section, re.S)
        assert match is not None, "Missing executable record example"
        command = match.group(1)
        tokens = shlex.split(command.replace("\\\n", ""))
        self.assertEqual(tokens[:2], ["printf", "%s\\n"])
        record = json.loads(tokens[2])
        self.assertIsInstance(record["note"], str)
        event = json.loads(record["note"])
        self.assertEqual(set(event), {"run_id", "step", "status", "detail"})
        self.assertEqual(event["step"], "RUN_START")
        self.assertEqual(tokens[3:6], ["|", "uvx", "fulcra-api"])
        self.assertNotIn("--note", tokens[6:])

    def test_workspace_retains_run_evidence(self):
        workspace = (ROOT / "references/workspace.md").read_text()
        for required in ("M1 — Working baseline and harness dashboard", "run_id",
                         "evidence", "annotation", "failed"):
            self.assertIn(required, workspace)

    def test_all_event_shapes_use_json_string_notes(self):
        flow = (ROOT / "references/harness-control-flow.md").read_text()
        examples = re.findall(r"```json\n(.*?)\n```", flow, re.S)
        self.assertTrue(examples)
        for example in examples:
            record = json.loads(example)
            self.assertIsInstance(record["note"], str)
            self.assertEqual(set(json.loads(record["note"])),
                             {"run_id", "step", "status", "detail"})

    def test_relative_markdown_links_resolve(self):
        for path in [ROOT / "SKILL.md", *(ROOT / "references").glob("*.md")]:
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" in target or target.startswith("#"):
                    continue
                self.assertTrue((path.parent / target.split("#")[0]).exists(),
                                f"{path}: missing {target}")


if __name__ == "__main__":
    unittest.main()
