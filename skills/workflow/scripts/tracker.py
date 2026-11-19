"""GitHub issue read-back shared by design and delivery."""

import json
import re
import shutil
import subprocess


def command(executable, *args):
    label = executable if executable in ("gh", "git") else "Orca"
    binary = shutil.which(executable)
    if not binary:
        raise ValueError(f"Executable unavailable: {label}")
    result = subprocess.run([binary, *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"{label} failed (exit {result.returncode}). Inspect the local command diagnostics.")
    return result.stdout


def repository(value):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value, re.ASCII):
        raise ValueError("Expected owner/repository")
    return value


def issue(repo, number):
    if number < 1:
        raise ValueError("Issue number must be positive")
    result = json.loads(command("gh", "issue", "view", number, "--repo", repo,
                                "--json", "number,title,body,state,url,labels"))
    expected = f"https://github.com/{repo}/issues/{number}"
    if result["url"].lower() != expected.lower() or not result["body"].strip():
        raise ValueError("Expected a scoped issue in the configured tracker")
    pages = json.loads(command("gh", "api", "--paginate", "--slurp",
                               f"repos/{repo}/issues/{number}/comments"))
    result["comments"] = [{"url": entry["html_url"], "author": (entry.get("user") or {}).get("login"),
                           "body": entry["body"]} for page in pages for entry in page]
    return result
