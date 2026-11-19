---
name: workflow
description: Start an Orchestra Auto development workflow from an idea, agreed spec, or issue in the current Orca repository conversation. Use when the developer asks Orca Workflow to produce a spec or build a feature.
---

# Orca Workflow

Work in the active repository and return decisions and deliverables to this conversation. Read its AGENTS.md, tracker instructions, glossary and relevant ADRs. Verify the target repository with `gh repo view --json nameWithOwner`. Use its configured GitHub repository explicitly for tracker operations.

## From an actionable issue to an open PR

For a build request naming an existing actionable ticket, start directly with [the single-ticket workflow](references/single-ticket.md). Follow it in this conversation for implementation, assigned review and open PR delivery.

## Build an agreed feature

For a build request naming an agreed spec, go directly to the [multi-ticket workflow](references/multi-ticket.md). It starts with the published spec and ends at one open integration PR. An actionable child ticket follows the single-ticket route above.

## From an idea to a published spec

1. Identify the requested endpoint from the developer’s message. For an idea, start the design stage below. If the requested endpoint is unclear, ask the developer here. Retain the original goal and endpoint across replies.
2. Locate `scripts/spec_flow.py` relative to **this installed SKILL.md**. Run `python <script> begin --goal "<developer's request>"` in the target repository. Keep the returned run ID. The command loads Orchestra Auto’s design-only route and reports the absolute skill paths. Read the installed Orchestra Auto skill and its routing reference. Apply its route, human decision and evidence rules in this conversation.
3. Resolve the `interview` assignment as described below. The assigned interviewer follows Matt Pocock’s installed `grill-with-docs` with its `grilling` and `domain-modeling` dependencies. Use native skill invocation where available. For a user-invoked-only wrapper or a host without native invocation, read and follow the reported SKILL.md files and acknowledge that mode if reporting invocation evidence. Answer repository questions by inspecting the project. Ask one unresolved product question here, wait for the developer’s reply, and continue from that answer. Keep scope and the test seam tied to the developer’s actual decisions.
4. When the scope and test seam are agreed, run `python <script> agree --run <id> --agreement "<the developer's scope and test decision>"`. Resolve the `spec` assignment below. The assigned author uses the installed `to-spec` skill and the agreed conversation to produce the final issue title and body. The coordinator owns publication and read-back. Write the final agreed body to a UTF-8 temporary file outside the repository. Create the issue once using `gh issue create --repo <owner/repo> --title "<title>" --body-file <file> --label <configured-ready-for-agent-label>`. If a response is lost, look for the existing issue before retrying. If an agreed spec already exists as an issue, reuse it.
5. With the number from GitHub and that same body file, run `python <script> finish --run <id> --repo <owner/repo> --issue <number> --body-file <file>`. It reads the issue back and checks the scope against the file. Report any failure in the current conversation. For a spec-only request, deliver the verified issue link and stop here. This endpoint dispatches zero implementation workers. For a build request, carry the verified issue, original request, assignments and conversation into the multi-ticket workflow immediately. The spec agreement already recorded in this conversation authorizes proceeding to ticket planning.

## Assign interview, spec and ticket planning

Before each stage, run `python <ticket-helper> assignment --step <step>`, using the installed `scripts/ticket_flow.py`. The steps are `interview`, `spec` and `tickets`. Their default is `conversation`, which runs the stage here. Set `ORCA_WORKFLOW_INTERVIEW_CLI`, `ORCA_WORKFLOW_SPEC_CLI` or `ORCA_WORKFLOW_TICKETS_CLI` to change a default. Pass the developer's per-run choice as `--agent codex`, `--agent claude` or `--agent conversation`.

For a resolved Codex or Claude Code assignment, perform [worker preflight and ledger setup](references/single-ticket.md) and the [routing check](references/routing.md). Prepare the upstream worker brief with the current goal, endpoint, decisions, relevant installed skill paths and the one stage deliverable. Run the following in the target checkout, adding the bound Orca Run ID with `--run` when available.

```text
python <ticket-helper> dispatch --step <step> --agent <resolved-cli> --spec-file <validated-brief> --repo <Orca-repo-selector> --base <verified-base-ref> --name <unique-name> --request <ledger-request-id>
```

Verify the start, assignment and worktree through the receipt and worker-show. Have the interviewer or planner send each unresolved decision using `orca orchestration ask --question "<question>"`. Ask the developer here, wait for their answer, then use `orca orchestration reply --id <message-id> --run <orca-run-id> --body "<answer>"`. Keep this exchange and its scope in the coordinator's record. The worker returns its findings, spec draft or proposed ticket map through worker_done. The coordinator owns tracker writes at the relevant gate. A spec-only endpoint ends at the verified spec issue.
