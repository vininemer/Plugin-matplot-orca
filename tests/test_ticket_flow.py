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


    def configure_routes(self):
        self.policy = self.directory / "routing.json"
        self.gateway = self.directory / "gateway.json"
        examples = ROOT / "skills/workflow/references"
        self.gateway.write_bytes((examples / "gateway.example.json").read_bytes())
        self.routes = json.loads((examples / "routing.example.json").read_text())
        for agent, binding in self.routes.items():
            binding.update(worker_host_verified=True, gateway_url="https://proxy.test",
                           gateway_config=self.gateway.name,
                           cli_config="config.toml" if agent == "codex" else "settings.json")
        (self.directory / "config.toml").write_text(
            'model_provider = "gateway"\n[model_providers.gateway]\nname = "LiteLLM"\n'
            'base_url = "https://proxy.test/v1"\nwire_api = "responses"\nsupports_websockets = false\n'
            'requires_openai_auth = true\nenv_http_headers = {"x-litellm-api-key"="GATEWAY_KEY"}\n')
        (self.directory / "settings.json").write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": "https://proxy.test",
            "ANTHROPIC_CUSTOM_HEADERS": "x-litellm-api-key: Bearer fixture-secret"}}))
        self.policy.write_text(json.dumps(self.routes))
        self.env = {k: v for k, v in self.env.items()
                    if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "OPENAI_", "CODEX_API_"))}
        self.env["GATEWAY_KEY"] = "test-virtual-key"
        self.env["ORCA_WORKFLOW_ROUTING"] = str(self.policy)

    def test_step_defaults_and_overrides_reach_the_isolated_orca_worker(self):
        self.configure_routes()
        orca = self.fake_command("orca", """import json, sys
from pathlib import Path
args = sys.argv[1:]
assert args[:2] == ["orchestration", "worker-start"]
def option(name): return args[args.index(name) + 1]
assert option("--worktree") == "new-top-level" and option("--setup") == "run"
assert option("--repo") == "path:fixture" and option("--retry-request") == "request-id"
assert option("--name") == "ticket-7" and option("--base-branch") == "f" * 40
assert Path(option("--spec-file")).read_text(encoding="utf-8") == "Assigned scope\\nChecks"
assert option("--model") == option("--agent") + "-auto" and option("--run") == "orca-run"
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
                                    "--repo", "path:fixture",
                                    "--run", "orca-run", *override)
                self.assertEqual(receipt["result"]["agent"], expected)


    def test_missing_routing_policy_stops_before_any_worker_is_started(self):
        self.env["ORCA_WORKFLOW_ROUTING"] = ""
        self.env["ORCA_CLI_COMMAND"] = self.fake_command("orca", "raise SystemExit('worker started')")
        brief = self.directory / "brief.md"
        brief.write_text("Ticket scope")
        args = ("dispatch", "--step", "implement", "--spec-file", brief, "--name", "impl",
                "--request", "id", "--base", "main", "--repo", "path:fixture")
        self.assertIn("ORCA_WORKFLOW_ROUTING", self.call(*args, ok=False))

    def test_router_must_only_reach_enabled_compatible_models(self):
        self.configure_routes()
        args = ("route-check", "--agent", "codex")
        checked = self.call(*args)
        self.assertEqual(checked["enabled_models"], ["chatgpt/gpt-6-astra", "chatgpt/gpt-6-luna"])
        original = self.gateway.read_text()
        for defect in ["alternate", "paid classifier", "bad default", "global fallback", "stale tier",
                       "unknown provider", "wrong protocol", "unlisted model", "opaque config"]:
            with self.subTest(defect=defect):
                deployed = json.loads(original)
                entries = deployed["model_list"]
                params = entries[0]["litellm_params"]
                if defect == "alternate":
                    entries.append({"model_name": "gpt-6-luna", "litellm_params": {"model": "openai/gpt-6-luna"}})
                elif defect == "paid classifier":
                    params["complexity_router_config"]["classifier_type"] = "llm"
                elif defect == "bad default":
                    params["complexity_router_default_model"] = "claude-haiku-4-5"
                elif defect == "global fallback":
                    deployed["router_settings"] = {"fallbacks": [{"codex-auto": ["claude-auto"]}]}
                elif defect == "stale tier":
                    params["complexity_router_config"]["tiers"]["COMPLEX"] = "missing"
                elif defect == "unknown provider":
                    entries[1]["litellm_params"]["model"] = "openai/gpt-6-luna"
                elif defect == "wrong protocol":
                    entries[1]["model_info"]["mode"] = "chat"
                elif defect == "unlisted model":
                    entries[1]["litellm_params"]["model"] = "chatgpt/other"
                else:
                    deployed["include"] = ["additional-routes.yaml"]
                self.gateway.write_text(json.dumps(deployed))
                self.call(*args, ok=False)

    def test_preflight_reads_the_active_cli_profile_and_blocks_conflicts(self):
        self.configure_routes()
        for agent, file, edits in [
            ("codex", "config.toml", [
                ("https://proxy.test", "https://unrelated.test"),
                ('model_provider = "gateway"', 'model_provider = "other"'),
                ("requires_openai_auth = true", 'requires_openai_auth = true\nenv_key = "OTHER_KEY"'),
                ("supports_websockets = false", "supports_websockets = true")]),
            ("claude", "settings.json", [
                ("https://proxy.test", "https://unrelated.test"),
                ('{"env":', '{"apiKeyHelper":"helper","env":'),
                ('{"env":', '{"availableModels":["sonnet"],"env":'),
                ('"ANTHROPIC_BASE_URL":', '"ANTHROPIC_API_KEY":"secret","ANTHROPIC_BASE_URL":'),
                ("x-litellm-api-key:", "authorization:")])]:
            args = ("route-check", "--agent", agent)
            file = self.directory / file
            original = file.read_text()
            self.call(*args)
            for old, new in edits:
                with self.subTest(agent=agent, replacement=new):
                    file.write_text(original.replace(old, new))
                    output = self.call(*args, ok=False)
                    self.assertNotIn("fixture-secret", output)
            file.write_text(original)

    def test_api_route_names_the_models_and_needs_per_dispatch_opt_in(self):
        self.configure_routes()
        route = self.routes["claude"]
        route["billing"] = "api"
        self.policy.write_text(json.dumps(self.routes))
        (self.directory / "settings.json").write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": route["gateway_url"], "ANTHROPIC_AUTH_TOKEN": "scoped-gateway-key"}}))
        args = ("route-check", "--agent", "claude")
        self.assertIn("--allow-api-model", self.call(*args, ok=False))
        partial = ("--allow-api-model", route["enabled_models"][0])
        self.assertIn("--allow-api-model", self.call(*args, *partial, ok=False))
        consent = (*partial, "--allow-api-model", route["enabled_models"][1])
        self.assertEqual(self.call(*args, *consent)["billing"], "api")
        self.env["ORCA_CLI_COMMAND"] = self.fake_command("orca", "raise SystemExit('worker started')")
        brief = self.directory / "brief.md"
        brief.write_text("Scope")
        launch = ("dispatch", "--step", "review", "--spec-file", brief, "--name", "review",
                  "--request", "review", "--base", "main", "--repo", "path:fixture")
        self.assertIn("--allow-api-model", self.call(*launch, ok=False))
        self.assertIn("verified alias", self.call(*launch, *consent, "--model", "other", ok=False))

    def test_existing_gateway_can_keep_logging_settings_and_unrelated_models(self):
        self.configure_routes()
        deployed = json.loads(self.gateway.read_text())
        deployed["general_settings"] = {"master_key": "os.environ/MASTER", "disable_spend_logs": False}
        deployed["litellm_settings"] = {"drop_params": True}
        deployed["router_settings"] = {"num_retries": 1}
        deployed["model_list"].append({"model_name": "unrelated-*", "litellm_params": {"model": "openai/*"}})
        self.gateway.write_text(json.dumps(deployed))
        self.assertEqual(self.call("route-check", "--agent", "codex")["alias"], "codex-auto")

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
