import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/workflow/scripts/spec_flow.py"


@unittest.skipUnless(os.environ.get("ORCHESTRA_AUTO_ROOT") and os.environ.get("MATT_SKILLS_ROOT"),
                     "Set the two upstream skill roots described in README.md")
class SpecConversation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = dict(os.environ, ORCA_FLOW_HOME=self.temp.name)

    def call(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def test_idea_starts_the_design_only_route_using_installed_skills(self):
        run = self.call("begin", "--goal", "Spec only: let me filter overdue tasks")
        self.assertEqual(run["nodes"], ["grill-with-docs", "to-spec"])
        self.assertEqual(run["route"], "design-only")
        for name in ("orchestra-auto", "grill-with-docs", "grilling", "domain-modeling", "to-spec"):
            self.assertTrue(Path(run["skills"][name]).is_file(), name)


    def test_agreed_scope_is_the_only_handoff_to_the_spec_stage(self):
        run = self.call("begin", "--goal", "Let me filter overdue tasks")
        plan = self.call("agree", "--run", run["run_id"], "--agreement",
                         "Developer approved overdue only, including the conversation test.")
        self.assertEqual([item["node"] for item in plan["ready"]], ["to-spec"])

    def test_published_issue_completes_the_run_and_returns_the_link(self):
        run = self.call("begin", "--goal", "Spec only: overdue tasks")
        run_id = run["run_id"]
        self.call("agree", "--run", run_id, "--agreement", "Developer chose overdue tasks.")
        directory = Path(self.temp.name)
        body = directory / "agreed.md"
        body.write_text("## Solution\n\nFilter by overdue tasks.\n", encoding="utf-8")
        url = "https://github.com/acme/tasks/issues/42"
        snapshot = directory / "published.json"
        snapshot.write_text(json.dumps({"url": url, "body": body.read_text(encoding="utf-8")}),
                            encoding="utf-8")
        # A fake external gh accepts only the read-back operation.
        if os.name == "nt":
            gh = directory / "gh.cmd"
            gh.write_text('@if not "%1 %2"=="issue view" exit /b 3\n@type "%FAKE_ISSUE%"\n')
        else:
            gh = directory / "gh"
            gh.write_text('#!/bin/sh\n[ "$1 $2" = "issue view" ] || exit 3\ncat "$FAKE_ISSUE"\n')
            gh.chmod(0o755)
        self.env.update(PATH=str(directory) + os.pathsep + self.env["PATH"], FAKE_ISSUE=str(snapshot))
        result = self.call("finish", "--run", run_id, "--repo", "acme/tasks",
                           "--issue", "42", "--body-file", str(body))
        self.assertEqual(result, {"state": "complete", "issue": url})
        resumed = self.call("finish", "--run", run_id, "--repo", "acme/tasks",
                            "--issue", "42", "--body-file", str(body))
        self.assertEqual(resumed, result)


class PluginEntry(unittest.TestCase):
    def test_both_cli_marketplaces_expose_the_same_conversation_workflow(self):
        for host in (".claude-plugin", ".codex-plugin"):
            manifest = json.loads((ROOT / host / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "orca-workflow")
        marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        entry, = marketplace["plugins"]
        self.assertEqual(entry["name"], "orca-workflow")
        skill = ROOT / entry["source"] / "skills/workflow/SKILL.md"
        self.assertTrue(skill.is_file())
