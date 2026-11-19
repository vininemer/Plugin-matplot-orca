"""Bridge the current conversation to Orchestra Auto's design-only route."""

import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from tracker import issue, repository


def installed_root(variable):
    value = os.environ.get(variable)
    if not value:
        raise ValueError(f"Set {variable} to the installed skill directory (see README.md).")
    return Path(value).resolve()


def orchestra_flow():
    path = installed_root("ORCHESTRA_AUTO_ROOT") / "scripts/flow.py"
    spec = importlib.util.spec_from_file_location("orchestra_flow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def append(flow, run_id, record):
    path = flow.flow_path(run_id)
    try:
        flow.append_record(path, record)
    except PermissionError as error:
        # Upstream fsyncs the file, then opens its directory to fsync the entry.
        # Windows disallows that directory open. Verify the exact record on disk.
        if os.name != "nt" or Path(error.filename or "") != path.parent:
            raise
        records, errors = flow.read_records(path)
        if errors or record not in records:
            raise


def begin(goal):
    orchestra = installed_root("ORCHESTRA_AUTO_ROOT")
    matt = installed_root("MATT_SKILLS_ROOT")
    skills = {"orchestra-auto": orchestra / "SKILL.md"}
    for area, name in [("engineering", "grill-with-docs"), ("productivity", "grilling"),
                       ("engineering", "domain-modeling"), ("engineering", "to-spec")]:
        skills[name] = matt / area / name / "SKILL.md"
    for path in skills.values():
        if not path.is_file():
            raise ValueError(f"Missing installed skill: {path}")
    run_id = str(uuid.uuid4())
    flow = orchestra_flow()
    record = flow.preset_flow_record("design-only", run_id, goal=goal,
                                     endpoint="Agreed spec published to the project issue tracker")
    append(flow, run_id, record)
    return {"run_id": run_id, "route": "design-only", "nodes": [n["id"] for n in record["nodes"]],
            "skills": {name: str(path) for name, path in skills.items()}}


def read_plan(flow, run_id):
    records, errors = flow.read_records(flow.flow_path(run_id))
    plan = flow.plan(records)
    if errors or plan["state"] == "uncertain":
        raise ValueError("; ".join(errors + plan["evidence_gaps"]))
    return plan


def accept(run_id, node, evidence, version):
    flow = orchestra_flow()
    plan = read_plan(flow, run_id)
    stage = next(item for item in plan["nodes"] if item["id"] == node)
    if (stage["state"] == "accepted" and stage["evidence_ref"] == evidence
            and stage["artifact_version"] == version):
        return plan
    if not any(item["node"] == node for item in plan["ready"]):
        raise ValueError(f"{node} is not ready in this conversation run.")
    append(flow, run_id, {
        "schema_version": flow.SCHEMA_VERSION, "kind": "state", "record_id": str(uuid.uuid4()),
        "flow_id": plan["flow_id"], "node": node, "state": "accepted", "attempt": 1,
        "task_id": run_id, "evidence_ref": evidence, "artifact_version": version,
    })
    return read_plan(flow, run_id)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def finish(run_id, repo, number, body_file):
    expected_body = body_file.read_text(encoding="utf-8-sig").strip()
    if not expected_body:
        raise ValueError("The agreed spec is empty.")
    published = issue(repo, number)
    if published["body"].replace("\r\n", "\n").strip() != expected_body:
        raise ValueError("The published issue does not match the agreed spec in the configured tracker.")
    plan = accept(run_id, "to-spec", published["url"], digest(expected_body))
    return {"state": plan["state"], "issue": published["url"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("begin").add_argument("--goal", required=True)
    agree = commands.add_parser("agree")
    agree.add_argument("--run", required=True, type=uuid.UUID)
    agree.add_argument("--agreement", required=True)
    published = commands.add_parser("finish")
    published.add_argument("--run", required=True, type=uuid.UUID)
    published.add_argument("--repo", type=repository, required=True)
    published.add_argument("--issue", required=True, type=int)
    published.add_argument("--body-file", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "begin":
        result = begin(args.goal)
    elif args.command == "agree":
        agreement = args.agreement.strip()
        if not agreement:
            parser.error("--agreement must identify the developer's scope decision")
        result = accept(str(args.run), "grill-with-docs", agreement, digest(agreement))
    else:
        result = finish(str(args.run), args.repo, args.issue, args.body_file)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
