import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/workflow/scripts/ticket_flow.py"


class TicketConversation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = dict(os.environ, ORCA_FLOW_HOME=str(self.directory / "flow"),
                        PATH=str(self.directory) + os.pathsep + os.environ["PATH"])

    def fake_command(self, name, python):
        source = self.directory / (name + "_fake.py")
        source.write_text(python, encoding="utf-8")
        if os.name == "nt":
            launcher = self.directory / (name + ".cmd")
            launcher.write_text(f'@"{sys.executable}" "{source}" %*\n')
        else:
            launcher = self.directory / name
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{source}" "$@"\n')
            launcher.chmod(0o755)
        return str(launcher)

    def call(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                                cwd=self.directory, env=self.env, capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(os.environ.get("ORCHESTRA_AUTO_ROOT"), "Set ORCHESTRA_AUTO_ROOT")
    def test_actionable_ticket_starts_at_implementation_with_the_agreed_scope(self):
        self.fake_command("gh", """import json, sys
assert sys.argv[1:3] == ["issue", "view"]
assert sys.argv[4:6] == ["--repo", "acme/tasks"]
n = int(sys.argv[3])
print(json.dumps({"number": n, "url": f"https://github.com/acme/tasks/issues/{n}",
                  "title": f"Issue {n}", "body": {7: "Ticket acceptance", 2: "Agreed scope"}[n],
                  "state": "OPEN"}))""")
        result = self.call("begin", "--repo", "acme/tasks", "--issue", 7, "--spec", 2)
        self.assertEqual([n["node"] for n in result["ready"]], ["implement"])
        self.assertEqual(result["ticket"]["body"], "Ticket acceptance")
        self.assertEqual(result["spec"]["body"], "Agreed scope")
        self.assertIn("open PR", result["endpoint"])


    def test_step_defaults_and_overrides_reach_the_isolated_orca_worker(self):
        orca = self.fake_command("orca", """import json, sys
from pathlib import Path
args = sys.argv[1:]
assert args[:2] == ["orchestration", "worker-start"]
def option(name): return args[args.index(name) + 1]
assert option("--worktree") == "new-top-level" and option("--setup") == "run"
assert option("--repo") == "path:fixture" and option("--retry-request") == "request-id"
assert option("--name") == "ticket-7" and option("--base-branch") == "f" * 40
assert Path(option("--spec-file")).read_text(encoding="utf-8") == "Assigned scope\\nChecks"
assert option("--model") == "fixture-route" and option("--run") == "orca-run"
print(json.dumps({"ok": True, "result": {"dispatchId": "test-dispatch",
      "agent": option("--agent"), "turnStart": "observed"}}))""")
        self.env.update(ORCA_CLI_COMMAND=orca, ORCA_WORKFLOW_IMPLEMENT_CLI="claude",
                        ORCA_WORKFLOW_REVIEW_CLI="codex")
        brief = self.directory / "worker brief.md"
        brief.write_text("Assigned scope\nChecks", encoding="utf-8")
        for step, override, expected in [("implement", [], "claude"), ("review", [], "codex"),
                                         ("implement", ["--agent", "codex"], "codex"),
                                         ("review", ["--agent", "claude"], "claude")]:
            with self.subTest(step=step, override=override):
                receipt = self.call("dispatch", "--step", step, "--spec-file", brief, "--name",
                                    "ticket-7", "--request", "request-id", "--base", "f" * 40,
                                    "--repo", "path:fixture", "--model", "fixture-route",
                                    "--run", "orca-run", *override)
                self.assertEqual(receipt["result"]["agent"], expected)


    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.directory, text=True).strip()

    def review_fixture(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        base = self.git("rev-parse", "HEAD")
        (self.directory / "feature.txt").write_text("Reviewed code\n", encoding="utf-8")
        self.git("add", "feature.txt")
        self.git("commit", "-q", "-m", "implementation")
        head = self.git("rev-parse", "HEAD")
        pr = {"url": "https://github.com/acme/tasks/pull/12", "state": "OPEN",
              "baseRefOid": base, "headRefOid": head, "body": "Summary"}
        self.pr_path = self.directory / "pr.json"
        self.pr_path.write_text(json.dumps(pr), encoding="utf-8")
        self.fake_command("gh", """import json, sys
from pathlib import Path
if sys.argv[1:4] == ["pr", "view", "12"]:
    print(Path("pr.json").read_text(encoding="utf-8"))
elif sys.argv[1:3] == ["issue", "view"]:
    n = int(sys.argv[3])
    print(json.dumps({"url": f"https://github.com/acme/tasks/issues/{n}",
                      "body": {2: "Agreed feature", 7: "Ticket checks"}[n],
                      "number": n, "title": f"Issue {n}", "state": "OPEN"}))
else: sys.exit("unexpected gh arguments")""")
        self.checks = self.directory / "checks.json"
        self.checks.write_text(json.dumps({"head": head, "checks": [
            {"ticket": 7, "command": "make test", "result": "pass", "evidence": "7 tests passed"}]}))
        return pr

    def test_reviewer_can_inspect_the_pr_change_spec_and_passing_ticket_evidence(self):
        pr = self.review_fixture()
        args = ("review-brief", "--repo", "acme/tasks", "--pr", 12, "--spec", 2,
                "--ticket", 7, "--tests-file", self.checks)
        packet = self.call(*args)
        self.assertEqual(packet["head"], pr["headRefOid"])
        for evidence in [pr["baseRefOid"], pr["headRefOid"], "feature.txt", "Agreed feature",
                         "Ticket checks", "make test", "7 tests passed"]:
            self.assertIn(evidence, packet["brief"])
        stale = json.loads(self.checks.read_text())
        self.assertIn("ticket coverage", self.call(*args, "--ticket", 8, ok=False))
        stale["head"] = pr["baseRefOid"]
        self.checks.write_text(json.dumps(stale))
        self.assertIn("tested head", self.call(*args, ok=False))


    def test_only_an_open_pr_with_matching_review_and_evidence_can_be_delivered(self):
        pr = self.review_fixture()
        review_file = self.directory / "review.json"
        review = {"base": pr["baseRefOid"], "head": pr["headRefOid"], "agent": "claude",
                  "dispatch": "review-dispatch", "result": "approve",
                  "standards": "Conforms to the documented rules.", "spec": "All criteria met."}
        review_file.write_text(json.dumps(review))
        args = ("--repo", "acme/tasks", "--pr", 12, "--review-file", review_file,
                "--ticket", 7, "--tests-file", self.checks, "--agent", "claude", "--dispatch", "review-dispatch")
        evidence = self.call("evidence", *args)["markdown"]
        self.assertIn("7 tests passed", evidence)
        self.assertIn("All criteria met.", evidence)
        self.assertIn("review-dispatch", evidence)
        self.assertIn("PR body", self.call("verify-pr", *args, ok=False))
        pr["body"] += "\r\n" + evidence.replace("\n", "\r\n")
        self.pr_path.write_text(json.dumps(pr))
        self.assertEqual(self.call("verify-pr", *args)["pull_request"], pr["url"])
        for key, wrong in [("head", "9" * 40), ("base", "8" * 40), ("agent", "codex"),
                           ("dispatch", "other"), ("result", "request-changes")]:
            with self.subTest(key=key):
                review_file.write_text(json.dumps(dict(review, **{key: wrong})))
                self.call("verify-pr", *args, ok=False)
        review_file.write_text(json.dumps(review))
        pr["state"] = "MERGED"
        self.pr_path.write_text(json.dumps(pr))
        self.assertIn("open PR", self.call("verify-pr", *args, ok=False))
