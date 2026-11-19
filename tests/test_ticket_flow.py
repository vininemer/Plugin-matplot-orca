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


    @unittest.skipUnless(os.environ.get("ORCHESTRA_AUTO_ROOT"), "Set ORCHESTRA_AUTO_ROOT")
    def test_build_from_an_agreed_spec_starts_at_ticket_planning(self):
        self.review_fixture()
        result = self.call("begin-feature", "--repo", "acme/tasks", "--spec", 2)
        self.assertEqual([item["node"] for item in result["ready"]], ["to-tickets"])
        self.assertEqual(result["spec"]["body"], "Agreed feature")
        self.assertEqual(result["route"], "ticket-map")
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
              "baseRefOid": base, "headRefOid": head, "body": "Summary", "isDraft": False,
              "headRefName": "feature/integration", "headRepositoryOwner": {"login": "acme"}}
        self.pr_path = self.directory / "pr.json"
        self.pr_path.write_text(json.dumps(pr), encoding="utf-8")
        self.fake_command("gh", """import json, sys
from pathlib import Path
if sys.argv[1:4] == ["pr", "view", "12"]:
    print(Path("pr.json").read_text(encoding="utf-8"))
elif sys.argv[1:3] == ["api", "--paginate"]:
    assert sys.argv[-5:] == ["repos/acme/tasks/pulls", "-f", "state=open", "-f",
                             "head=acme:feature/integration"]
    matches = json.loads(Path("open.json").read_text())
    print(json.dumps([[{"html_url": p["url"], "head": {"sha": p["headRefOid"]},
                        "base": {"sha": p["baseRefOid"]}, "draft": p["isDraft"]} for p in matches]]))
elif sys.argv[1:3] == ["issue", "view"]:
    n = int(sys.argv[3])
    print(json.dumps({"url": f"https://github.com/acme/tasks/issues/{n}",
                      "body": {2: "Agreed feature", 7: "Ticket checks", 8: "Dependent ticket"}[n],
                      "number": n, "title": f"Issue {n}", "state": "OPEN"}))
else: sys.exit("unexpected gh arguments")""")
        self.checks = self.directory / "checks.json"
        self.checks.write_text(json.dumps({"head": head, "checks": [
            {"ticket": 7, "command": "make test", "result": "pass", "evidence": "7 tests passed"}]}))
        return pr

    def test_an_integrated_passing_ticket_releases_dependents_while_issues_remain_open(self):
        pr = self.review_fixture()
        graph = self.directory / "tickets.json"
        graph.write_text('{"7": [], "8": [7], "9": []}')
        args = ("frontier", "--repo", "acme/tasks", "--map-file", graph,
                "--head", pr["headRefOid"], "--tests-file", self.checks)
        report = json.loads(self.checks.read_text())
        self.checks.write_text('{"checks": []}')
        self.assertEqual(self.call(*args)["ready"], [7, 9])
        report["checks"][0]["commit"] = pr["headRefOid"]
        self.checks.write_text(json.dumps(report))
        self.assertEqual(self.call(*args), {"integrated": [7], "ready": [8, 9]})
        for change in [{"result": "fail"}, {"commit": "1" * 40}]:
            with self.subTest(change=change):
                altered = dict(report["checks"][0], **change)
                self.checks.write_text(json.dumps({"checks": [altered]}))
                self.call(*args, ok=False)
        graph.write_text('{"7": [8], "8": [7]}')
        self.checks.write_text('{"checks": []}')
        self.assertIn("cycle", self.call(*args, ok=False))

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


    def test_combined_review_and_pr_require_every_ticket_and_the_exact_integration_suite(self):
        pr = self.review_fixture()
        first = pr["headRefOid"]
        self.git("commit", "-q", "--allow-empty", "-m", "dependent ticket")
        pr["headRefOid"] = self.git("rev-parse", "HEAD")
        self.pr_path.write_text(json.dumps(pr))
        graph = self.directory / "tickets.json"
        graph.write_text('{"7": [], "8": [7]}')
        args = ("--repo", "acme/tasks", "--pr", 12, "--map-file", graph, "--tests-file", self.checks)
        first_check = dict(json.loads(self.checks.read_text())["checks"][0], commit=first)
        second = dict(first_check, ticket=8, commit=pr["headRefOid"], evidence="dependent check log")
        suite = {"command": "make check", "result": "pass", "evidence": "complete suite log"}
        report = {"checks": [first_check, second], "head": pr["headRefOid"], "integration": [suite]}
        for bad in [dict(report, checks=[first_check]), dict(report, head=first),
                    dict(report, integration=[]), dict(report, integration=[dict(suite, result="fail")])]:
            self.checks.write_text(json.dumps(bad))
            self.call("review-brief", "--spec", 2, *args, ok=False)
        self.checks.write_text(json.dumps(report))
        packet = self.call("review-brief", "--spec", 2, *args)
        for item in ["Agreed feature", "Ticket checks", "Dependent ticket", first, pr["headRefOid"],
                     "dependent check log", "complete suite log"]:
            self.assertIn(item, packet["brief"])
        review_file = self.directory / "review.json"
        review_file.write_text(json.dumps({"base": pr["baseRefOid"], "head": pr["headRefOid"],
            "agent": "claude", "dispatch": "integration-review", "result": "approve",
            "standards": "Conforms.", "spec": "All criteria covered."}))
        final = (*args, "--dispatch", "integration-review", "--agent", "claude", "--review-file", review_file)
        pr["body"] += "\n" + self.call("evidence", *final)["markdown"]
        self.assertIn(first, pr["body"])
        self.assertIn("complete suite log", pr["body"])
        self.pr_path.write_text(json.dumps(pr))
        open_prs = self.directory / "open.json"
        open_prs.write_text(json.dumps([pr, dict(pr, url="https://github.com/acme/tasks/pull/13")]))
        self.assertIn("one open", self.call("verify-pr", *final, ok=False))
        open_prs.write_text(json.dumps([pr]))
        self.pr_path.write_text(json.dumps(dict(pr, isDraft=True)))
        self.assertIn("draft", self.call("verify-pr", *final, ok=False))
        self.pr_path.write_text(json.dumps(pr))
        self.assertEqual(self.call("verify-pr", *final)["head"], pr["headRefOid"])
        pr["headRefOid"] = first
        self.pr_path.write_text(json.dumps(pr))
        self.call("verify-pr", *final, ok=False)

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
