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
3. Follow Matt Pocock’s installed `grill-with-docs` with its `grilling` and `domain-modeling` dependencies. Use native skill invocation where available. For a user-invoked-only wrapper or a host without native invocation, read and follow the reported SKILL.md files and acknowledge that mode if reporting invocation evidence. Answer repository questions by inspecting the project. Ask one unresolved product question here, wait for the developer’s reply, and continue from that answer. Keep scope and the test seam tied to the developer’s actual decisions.
4. When the scope and test seam are agreed, run `python <script> agree --run <id> --agreement "<the developer's scope and test decision>"`. Follow the installed `to-spec` skill to synthesize the conversation and publish the issue. Write the final agreed body to a UTF-8 temporary file outside the repository. Create the issue once using `gh issue create --repo <owner/repo> --title "<title>" --body-file <file> --label <configured-ready-for-agent-label>`. If a response is lost, look for the existing issue before retrying. If an agreed spec already exists as an issue, reuse it.
5. With the number from GitHub and that same body file, run `python <script> finish --run <id> --repo <owner/repo> --issue <number> --body-file <file>`. It reads the issue back and checks the scope against the file. Report any failure in the current conversation. For a spec-only request, deliver the verified issue link and stop here. This endpoint dispatches zero implementation workers. For a build request, carry the verified issue, original request, assignments and conversation into the multi-ticket workflow immediately. The spec agreement already recorded in this conversation authorizes proceeding to ticket planning.
