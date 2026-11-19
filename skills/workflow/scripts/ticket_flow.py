"""Conversation helpers for Orchestra Auto's tested, reviewed, open PR endpoint."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from spec_flow import append, orchestra_flow, read_plan


def command(executable, *args):
    binary = shutil.which(executable)
    if not binary:
        raise ValueError(f"Executable unavailable: {executable}")
    result = subprocess.run([binary, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or f"{executable} failed")
    return result.stdout


def repository(value):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value, re.ASCII):
        raise ValueError("Expected owner/repository")
    return value


def issue(repo, number):
    if number < 1:
        raise ValueError("Issue number must be positive")
    result = json.loads(command("gh", "issue", "view", number, "--repo", repo,
                                "--json", "number,title,body,state,url"))
    expected = f"https://github.com/{repo}/issues/{number}"
    if result["url"].lower() != expected.lower() or not result["body"].strip():
        raise ValueError("Expected a scoped issue in the configured tracker")
    return result


def begin(args):
    ticket = issue(args.repo, args.issue)
    if ticket["state"] != "OPEN":
        raise ValueError("The implementation ticket must be open")
    spec = issue(args.repo, args.spec) if args.spec and args.spec != args.issue else ticket
    run_id = str(uuid.uuid4())
    flow = orchestra_flow()
    record = flow.preset_flow_record("single-impl", run_id, goal=ticket["url"],
                                     endpoint="One tested and reviewed open PR; developer decides merge")
    append(flow, run_id, record)
    return {"run_id": run_id, "route": "single-impl", "endpoint": record["endpoint"],
            "ready": read_plan(flow, run_id)["ready"], "ticket": ticket, "spec": spec}


def assigned_agent(step, override):
    default = {"implement": "codex", "review": "claude"}[step]
    agent = override or os.environ.get(f"ORCA_WORKFLOW_{step.upper()}_CLI", default)
    if agent not in ("codex", "claude"):
        raise ValueError(f"Choose codex or claude for {step}")
    return agent


def dispatch(args):
    agent = assigned_agent(args.step, args.agent)
    if not args.spec_file.read_text(encoding="utf-8-sig").strip():
        raise ValueError("The worker brief is empty")
    argv = ["orchestration", "worker-start", "--spec-file", args.spec_file.resolve(),
            "--worktree", "new-top-level", "--repo", args.repo, "--name", args.name,
            "--base-branch", args.base, "--setup", "run", "--agent", agent,
            "--retry-request", args.request, "--json"]
    if args.run:
        argv.extend(["--run", args.run])
    if args.model:
        argv.extend(["--model", args.model])
    return json.loads(command(os.environ.get("ORCA_CLI_COMMAND", "orca"), *argv))


def pr_snapshot(args):
    pr = json.loads(command("gh", "pr", "view", args.pr, "--repo", args.repo,
                            "--json", "url,state,baseRefOid,headRefOid,body"))
    expected = f"https://github.com/{args.repo}/pull/{args.pr}"
    if pr["url"].lower() != expected.lower() or pr["state"] != "OPEN":
        raise ValueError("Expected the open PR in the configured tracker")
    if not all(re.fullmatch(r"[0-9a-f]{40}", pr[key]) for key in ("baseRefOid", "headRefOid")):
        raise ValueError("The PR did not provide full commit identities")
    return pr


def ticket_checks(path, head, tickets):
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if report.get("head") != head:
        raise ValueError("The tested head differs from the open PR")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("Expected ticket check evidence")
    for check in checks:
        if (not isinstance(check, dict) or check.get("result") != "pass"
                or type(check.get("ticket")) is not int or check["ticket"] < 1
                or not all(isinstance(check.get(k), str) and check[k].strip()
                           for k in ("command", "evidence"))):
            raise ValueError("Every ticket check needs a passing result, command and evidence")
    if {c['ticket'] for c in checks} != set(tickets):
        raise ValueError('The check report has different ticket coverage from the assignment')
    return checks


def check_lines(checks):
    return [f"- #{check['ticket']} | {check['command']} | PASS | {check['evidence']}" for check in checks]


def review_brief(args):
    pr = pr_snapshot(args)
    base, head = pr["baseRefOid"], pr["headRefOid"]
    checks = ticket_checks(args.tests_file, head, args.ticket)
    numbers = dict.fromkeys([args.spec, *(c["ticket"] for c in checks)])
    scope = []
    for number in numbers:
        item = issue(args.repo, number)
        scope.extend([item["url"], item["title"], item["body"]])
    diff = f"{base}...{head}"
    changed = command("git", "diff", "--no-ext-diff", "--no-textconv", "--stat", diff, "--")
    if not changed.strip():
        raise ValueError("No local change to review for these PR commits")
    brief = "\n".join([
        f"Review {pr['url']}. Verify git rev-parse HEAD equals {head}.",
        f"Inspect the actual change with git diff --no-ext-diff --no-textconv {diff} --",
        "Read the affected callers and tests. Apply Matt Pocock's code-review skill on both axes.",
        "Return the base and head, assigned CLI, dispatch ID, standards and spec findings,",
        "and an approve or request-changes verdict. Leave the pull request open.",
        "", "Agreed scope", *scope, "", "Changed files", changed.strip(), "",
        "Ticket check evidence", *check_lines(checks),
    ])
    return {"base": base, "head": head, "brief": brief}


def delivery(args):
    pr = pr_snapshot(args)
    head, base = pr["headRefOid"], pr["baseRefOid"]
    checks = ticket_checks(args.tests_file, head, args.ticket)
    review = json.loads(args.review_file.read_text(encoding="utf-8-sig"))
    agent = assigned_agent("review", args.agent)
    expected = {"base": base, "head": head, "dispatch": args.dispatch, "agent": agent,
                "result": "approve"}
    if not all(review.get(k) == v for k, v in expected.items()):
        raise ValueError("An approval from the assigned review dispatch must match the PR base and head")
    if not all(isinstance(review.get(k), str) and review[k].strip() for k in ("standards", "spec")):
        raise ValueError("The reviewer must report both standards and spec findings")
    markdown = "\n".join(["## Workflow evidence", "", f"Tested head: {head}", *check_lines(checks),
                          "", f"Approved by {agent} (Orca dispatch {args.dispatch})",
                          f"Reviewed change: {base}...{head}", f"Standards: {review['standards']}",
                          f"Spec: {review['spec']}"])
    if args.command == "evidence":
        return {"markdown": markdown}
    if markdown not in pr["body"].replace("\r\n", "\n"):
        raise ValueError("The PR body lacks the verified test and review evidence")
    return {"pull_request": pr["url"], "state": pr["state"], "head": head, "reviewer": agent}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("begin")
    start.add_argument("--repo", type=repository, required=True)
    start.add_argument("--issue", type=int, required=True)
    start.add_argument("--spec", type=int)
    start.set_defaults(function=begin)
    worker = commands.add_parser("dispatch")
    worker.add_argument("--step", choices=["implement", "review"], required=True)
    worker.add_argument("--agent", choices=["codex", "claude"])
    worker.add_argument("--spec-file", type=Path, required=True)
    for flag in ("repo", "base", "name", "request"):
        worker.add_argument("--" + flag, required=True)
    worker.add_argument("--run")
    worker.add_argument("--model")
    worker.set_defaults(function=dispatch)
    review = commands.add_parser("review-brief")
    review.add_argument("--repo", type=repository, required=True)
    review.add_argument("--pr", type=int, required=True)
    review.add_argument("--ticket", type=int, action="append", required=True)
    review.add_argument("--spec", type=int, required=True)
    review.add_argument("--tests-file", type=Path, required=True)
    review.set_defaults(function=review_brief)
    for name in ("evidence", "verify-pr"):
        proof = commands.add_parser(name)
        proof.add_argument("--repo", type=repository, required=True)
        proof.add_argument("--pr", type=int, required=True)
        proof.add_argument("--ticket", type=int, action="append", required=True)
        proof.add_argument("--agent", choices=["codex", "claude"])
        proof.add_argument("--dispatch", required=True)
        proof.add_argument("--tests-file", type=Path, required=True)
        proof.add_argument("--review-file", type=Path, required=True)
        proof.set_defaults(function=delivery)
    args = parser.parse_args()
    print(json.dumps(args.function(args)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
