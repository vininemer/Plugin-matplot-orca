"""Conversation helpers for Orchestra Auto's tested, reviewed, open PR endpoint."""

import argparse
from graphlib import CycleError, TopologicalSorter
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
    if args.command == "begin-feature":
        spec = issue(args.repo, args.spec)
        route, source = "ticket-map", spec
        artifacts = {"spec": spec}
    else:
        ticket = issue(args.repo, args.issue)
        if ticket["state"] != "OPEN":
            raise ValueError("The implementation ticket must be open")
        spec = issue(args.repo, args.spec) if args.spec and args.spec != args.issue else ticket
        route, source = "single-impl", ticket
        artifacts = {"ticket": ticket, "spec": spec}
    run_id = str(uuid.uuid4())
    flow = orchestra_flow()
    record = flow.preset_flow_record(route, run_id, goal=source["url"],
                                     endpoint="One tested and reviewed open PR; developer decides merge")
    append(flow, run_id, record)
    return {"run_id": run_id, "route": route, "endpoint": record["endpoint"],
            "ready": read_plan(flow, run_id)["ready"], **artifacts}


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
                            "--json", "url,state,baseRefOid,headRefOid,body,isDraft,headRepositoryOwner,headRefName"))
    expected = f"https://github.com/{args.repo}/pull/{args.pr}"
    if pr["url"].lower() != expected.lower() or pr["state"] != "OPEN":
        raise ValueError("Expected the open PR in the configured tracker")
    if not all(re.fullmatch(r"[0-9a-f]{40}", pr[key]) for key in ("baseRefOid", "headRefOid")):
        raise ValueError("The PR did not provide full commit identities")
    return pr


def read_graph(path):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Expected the approved ticket map")
    graph = {}
    for number, blockers in raw.items():
        if (not re.fullmatch("[1-9][0-9]*", number) or not isinstance(blockers, list)
                or any(type(b) is not int or b < 1 for b in blockers)):
            raise ValueError("Map each positive ticket number to its blocker numbers")
        graph[int(number)] = blockers
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as error:
        raise ValueError("The approved ticket map contains a cycle") from error
    return graph


def passing_check(check):
    return (isinstance(check, dict) and check.get("result") == "pass"
            and all(isinstance(check.get(k), str) and check[k].strip() for k in ("command", "evidence")))


def ancestor(commit, head):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full tested commit SHA")
    command("git", "merge-base", "--is-ancestor", commit, head)


def integrated_tickets(graph, repo, head, checks):
    if not isinstance(checks, list):
        raise ValueError("Expected a list of ticket checks")
    ancestor(head, head)
    tested = {}
    for check in checks:
        if (not passing_check(check) or type(check.get("ticket")) is not int
                or check["ticket"] not in graph):
            raise ValueError("Every ticket check must pass and belong to the approved map")
        ticket, commit = check["ticket"], check.get("commit")
        ancestor(commit, head)
        if tested.setdefault(ticket, commit) != commit:
            raise ValueError("Checks for one ticket must certify the same commit")
    external = {b for blockers in graph.values() for b in blockers if b not in graph}
    resolved = set(tested) | {b for b in external if issue(repo, b)["state"] == "CLOSED"}
    for ticket, commit in tested.items():
        for blocker in graph[ticket]:
            if blocker not in resolved:
                raise ValueError(f"Tested ticket #{ticket} still has unresolved blocker #{blocker}")
            if blocker in tested:
                ancestor(tested[blocker], commit)
    ready = [n for n in graph if n not in tested and resolved.issuperset(graph[n])]
    return {"integrated": sorted(tested), "ready": sorted(ready)}


def frontier(args):
    graph = read_graph(args.map_file)
    report = json.loads(args.tests_file.read_text(encoding="utf-8-sig"))
    return integrated_tickets(graph, args.repo, args.head, report.get("checks"))


def ticket_checks(args, head):
    report = json.loads(args.tests_file.read_text(encoding="utf-8-sig"))
    if report.get("head") != head:
        raise ValueError("The tested head differs from the open PR")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("Expected ticket check evidence")
    for check in checks:
        if (not passing_check(check) or type(check.get("ticket")) is not int or check["ticket"] < 1):
            raise ValueError("Every ticket check needs a passing result, command and evidence")
    graph = read_graph(args.map_file) if args.map_file else None
    tickets = list(graph) if graph else args.ticket
    if {c["ticket"] for c in checks} != set(tickets):
        raise ValueError("The check report has different ticket coverage from the assignment")
    if len(set(tickets)) > 1 and not graph:
        raise ValueError("Supply the approved --map-file for a combined review")
    lines = []
    if graph:
        integrated_tickets(graph, args.repo, head, checks)
    for check in checks:
        label = f"#{check['ticket']}"
        if graph:
            label += f" at {check['commit']}"
        lines.append(f"- {label} | {check['command']} | PASS | {check['evidence']}")
    if graph:
        suite = report.get("integration")
        if not isinstance(suite, list) or not suite or not all(passing_check(c) for c in suite):
            raise ValueError("Expected passing integration checks at the tested PR head")
        lines.extend(f"- Integration at {head} | {c['command']} | PASS | {c['evidence']}" for c in suite)
    return tickets, lines


def review_brief(args):
    pr = pr_snapshot(args)
    base, head = pr["baseRefOid"], pr["headRefOid"]
    tickets, evidence = ticket_checks(args, head)
    numbers = dict.fromkeys([args.spec, *tickets])
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
        "Ticket check evidence", *evidence,
    ])
    return {"base": base, "head": head, "brief": brief}


def delivery(args):
    pr = pr_snapshot(args)
    head, base = pr["headRefOid"], pr["baseRefOid"]
    _, evidence = ticket_checks(args, head)
    review = json.loads(args.review_file.read_text(encoding="utf-8-sig"))
    agent = assigned_agent("review", args.agent)
    expected = {"base": base, "head": head, "dispatch": args.dispatch, "agent": agent,
                "result": "approve"}
    if not all(review.get(k) == v for k, v in expected.items()):
        raise ValueError("An approval from the assigned review dispatch must match the PR base and head")
    if not all(isinstance(review.get(k), str) and review[k].strip() for k in ("standards", "spec")):
        raise ValueError("The reviewer must report both standards and spec findings")
    markdown = "\n".join(["## Workflow evidence", "", f"Tested head: {head}", *evidence,
                          "", f"Approved by {agent} (Orca dispatch {args.dispatch})",
                          f"Reviewed change: {base}...{head}", f"Standards: {review['standards']}",
                          f"Spec: {review['spec']}"])
    if args.command == "evidence":
        return {"markdown": markdown}
    if markdown not in pr["body"].replace("\r\n", "\n"):
        raise ValueError("The PR body lacks the verified test and review evidence")
    if args.map_file:
        if pr["isDraft"]:
            raise ValueError("Mark the integration draft ready for review before delivery")
        selector = f"{pr['headRepositoryOwner']['login']}:{pr['headRefName']}"
        pages = json.loads(command("gh", "api", "--paginate", "--slurp", "--method", "GET",
                                   f"repos/{args.repo}/pulls", "-f", "state=open", "-f", f"head={selector}"))
        matches = [item for page in pages for item in page]
        if (len(matches) != 1 or matches[0]["html_url"] != pr["url"] or matches[0]["draft"]
                or matches[0]["head"]["sha"] != head or matches[0]["base"]["sha"] != base):
            raise ValueError("Expected one open, ready PR at the reviewed integration base and head")
    return {"pull_request": pr["url"], "state": pr["state"], "head": head, "reviewer": agent}


def review_scope(parser):
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--ticket", type=int, action="append")
    scope.add_argument("--map-file", type=Path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("begin")
    start.add_argument("--repo", type=repository, required=True)
    start.add_argument("--issue", type=int, required=True)
    start.add_argument("--spec", type=int)
    start.set_defaults(function=begin)
    feature = commands.add_parser("begin-feature")
    feature.add_argument("--repo", type=repository, required=True)
    feature.add_argument("--spec", type=int, required=True)
    feature.set_defaults(function=begin)
    queue = commands.add_parser("frontier")
    queue.add_argument("--repo", type=repository, required=True)
    queue.add_argument("--map-file", type=Path, required=True)
    queue.add_argument("--tests-file", type=Path, required=True)
    queue.add_argument("--head", required=True)
    queue.set_defaults(function=frontier)
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
    review_scope(review)
    review.add_argument("--spec", type=int, required=True)
    review.add_argument("--tests-file", type=Path, required=True)
    review.set_defaults(function=review_brief)
    for name in ("evidence", "verify-pr"):
        proof = commands.add_parser(name)
        proof.add_argument("--repo", type=repository, required=True)
        proof.add_argument("--pr", type=int, required=True)
        review_scope(proof)
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
