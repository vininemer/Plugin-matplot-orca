# Deliver an actionable ticket

Use the current conversation as Orchestra Auto's coordinator. The endpoint is one tested and reviewed open PR. Keep the developer's role assignments and merge decision. Use the workflow's installed `scripts/ticket_flow.py` from the target repository. In the commands below, `<helper>` means the absolute path to that file.

## Start at the ticket

1. Confirm the repo, ticket, and its agreed scope from the tracker, including linked parent spec, comments, blockers and the agreed test seam. If the ticket itself carries the spec, use its number for both. Resolve any genuinely new product decision in this conversation.
2. Run `python <helper> begin --repo OWNER/REPO --issue NUMBER --spec SPEC_NUMBER`. Retain the returned ticket, spec and flow ID. The installed Orchestra Auto single-impl graph starts at implementation. Link the flow ID to the actual Orca Run ID from the session or first dispatch receipt in the external ledger. Use the Orca ID for later `--run` calls.
3. Read `$ORCHESTRA_AUTO_ROOT/SKILL.md` and its preflight, dispatch, acceptance, ledger and dashboard references. Read the local version-matched guides from `orca skills get orchestration` and `orca skills get orca-cli`. Use the coordinator's actual executable (`ORCA_CLI_COMMAND`, default `orca`) throughout. Follow upstream Channel B init-check, dashboard, preflight, intent/result, native wake, acceptance, closeout and release procedures. Record the human-merge endpoint. Keep briefs, evidence files and run state outside repository worktrees.
4. Run upstream supervision scripts in a POSIX Python environment. The pinned ledger uses `fcntl`. On Windows, use WSL with the mounted checkout, skill roots and an executable Orca CLI connected to this same conversation. Verify the session ID against `orca status --json`, or the TUI handle and pane against `orca terminal list --json`, from that host. Pass inherited binding values through the WSL process environment. A separate shell login or matching repository path alone does not establish the binding. Use paths the consuming process can open: a WSL Python path for its own reads and a Windows-readable path for a Windows Orca executable. If the native CLI cannot read a POSIX brief path, run this dispatch helper with Windows Python against the same brief on a shared filesystem. Run its Git/gh queries from the same target checkout. Verify worker access to the specified skill files during preflight. Report an unavailable preflight receipt, messaging capability or session binding before launch.

## Dispatch the selected implementer

Read per-step defaults from `ORCA_WORKFLOW_IMPLEMENT_CLI` and `ORCA_WORKFLOW_REVIEW_CLI` in the conversation's execution environment. The built-ins are `codex` for implementation and `claude` for review. Apply a developer's per-run or per-ticket assignment using `--agent` for that dispatch. Both values work for either step. Keep the resolved reviewer and dispatch ID for the final comparison.

Write the upstream worker spec with its required behavior rules and preflight elements. Give the implementer the ticket and parent scope, allowed files, base ref, expected repository checks and open-PR endpoint. Use the installed Matt Pocock `engineering/implement` and its `tdd` dependency at the agreed seam. Specify the independent reviewer handoff for code-review. The worker edits only its assigned worktree, runs the checks, commits, pushes, and creates or updates this ticket's single PR with a body file. Ask it to return the PR, full tested commit, exact commands, results/log references and a clean-worktree reading.

After upstream preflight passes and the ledger intent is written, dispatch with:

```text
python <helper> dispatch --step implement --spec-file <validated-brief> --repo <Orca-repo-selector> --base <verified-base-ref> --name <unique-name> --request <ledger-request-id>
```

For an existing bound Run, include `--run <orca-run-id>`. Supply the run's selected route alias using `--model` when configured. Save the raw receipt as the ledger result for that intent. Inspect worker identity, worktree and branch against the assignment using the receipt and `orca orchestration worker-show --dispatch <id> --json`. Prove start with `turnStart: observed` or the upstream attempt evidence. If the launch or result is uncertain, reconcile the original request before retrying. Wait for native messages. Handle `ask`, `reply`, `worker_done` and follow-ups through the version-matched orchestration guide.

## Hand off the actual PR change

1. Verify the implementer's settled output, PR and test log through the worker transcript/CI. Fetch the PR head and base objects into the coordinator's target Git repository. Store the verified ticket results in a UTF-8 JSON file. Its `head` is the full tested PR head and every check identifies its ticket, command, result and evidence. For example:

   ```json
   {"head":"<full-tested-commit>","checks":[{"ticket":7,"command":"python -m unittest","result":"pass","evidence":"14 tests passed; <run log reference>"}]}
   ```

2. Run `python <helper> review-brief --repo OWNER/REPO --pr PR --spec SPEC_NUMBER --ticket NUMBER --tests-file <checks.json>`. It reads the open PR, pins the base and head, resolves the Git diff locally and includes the scope and checks. Insert its `brief` text in a fresh upstream worker spec alongside the required preflight elements and installed `engineering/code-review/SKILL.md` path. Record the implementation result in the upstream flow with the tested head as its artifact version.
3. Run preflight and ledger intent for the review assignment. Use the same dispatch command with `--step review --base <packet.head> --run <orca-run-id>`, a new worktree name, validated review spec file, review override if chosen and distinct request ID. The selected reviewer owns the standards and spec axes, including the skill's subsidiary reviews. It confirms `HEAD`, inspects the diff and affected code, considers the test evidence, and returns findings for the exact base and head without pushing code changes or opening another PR.
4. At settlement, match the review message to that actual dispatch, agent identity and worktree using the ledger receipts and worker transcript. Store its result in a UTF-8 file. The coordinator records the reviewing worker's findings verbatim. A request for changes goes back to implementation on the same PR. Invalidate the previous artifact in the upstream flow, rerun relevant checks, and repeat independent review against the updated head or base.

   ```json
   {"base":"<full-base>","head":"<full-head>","agent":"claude","dispatch":"<actual-review-dispatch>","result":"approve","standards":"<reviewer's standards findings>","spec":"<reviewer's spec findings>"}
   ```

## Deliver the open PR

Run `python <helper> evidence --repo OWNER/REPO --pr PR --ticket NUMBER --agent <assigned-reviewer> --dispatch <ledger-review-dispatch> --tests-file <checks.json> --review-file <review.json>`. This compares the review, tests and current PR. Have a worker preserve the existing PR description and append the returned `markdown` using `gh pr edit PR --repo OWNER/REPO --body-file <updated-body>`. Refresh the body before editing, reuse this PR, and refresh older evidence when a review repeats.

Run `verify-pr` with the same arguments to read back the open PR and its evidence. Record the actual acceptance, flow and closeout under Orchestra Auto's PR-only procedure with `pending_type: human_merge`. Deliver the verified PR link, tested/reviewed SHA, checks and reviewer findings in the original conversation. The developer decides whether to merge.
