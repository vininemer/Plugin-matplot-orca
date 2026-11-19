# Orca Workflow

Run a repository workflow from the Codex or Claude Code conversation you already have open in Orca. A spec-only request interviews you there and ends with a GitHub issue containing the agreed scope.

## Install

This package installs in the CLI hosting the Orca conversation. It requires Python 3.10+, Git, an authenticated GitHub CLI with access to the target issue tracker, and local copies of Orchestra Auto and Matt Pocock’s skills. In a directory outside your target repository, prepare the upstream dependencies once. The commands below use PowerShell.

```powershell
git clone https://github.com/whutlichao/orchestra-auto.git
git -C orchestra-auto checkout c27067aa7f00121c71e2d1456ef439db657c3fef
git clone https://github.com/mattpocock/skills.git matt-skills
git -C matt-skills checkout abeeaf95660ba9e8b7c753eb38f441ca707a8823
$env:ORCHESTRA_AUTO_ROOT = (Resolve-Path orchestra-auto/skills/orchestra-auto).Path
$env:MATT_SKILLS_ROOT = (Resolve-Path matt-skills/skills).Path
```

Existing checkouts of these revisions work too. Make both environment variables available to the CLI in Orca. For an already-running conversation, the agent can set them in the shell command that runs the helper. Orchestra Auto stores its run records outside the repository in its normal flow home. Set `ORCA_FLOW_HOME` to choose a different external directory.

From this plugin checkout, install it for the host you use. Replace `<absolute-plugin-checkout>` with the path to this directory.

| Host | Add marketplace | Install |
| --- | --- | --- |
| Codex | `codex plugin marketplace add <absolute-plugin-checkout>` | `codex plugin add orca-workflow@orca-workflow-local` |
| Claude Code | `claude plugin marketplace add <absolute-plugin-checkout>` | `claude plugin install orca-workflow@orca-workflow-local` |

Reload plugins in the host or resume the same conversation after restarting its CLI if the skill picker has not refreshed. Configure the target repository’s GitHub tracker and triage labels in its agent instructions.

## Request a spec

In the target repository’s Orca conversation, select the **workflow** skill from **orca-workflow** in Codex, or type `/orca-workflow:workflow` in Claude Code. For example, ask “Spec only. Let team leads filter overdue tasks by owner.” Answer the interview in that conversation. You receive the issue link after the plugin reads the published body back from GitHub.

## Build a feature

Ask ?Build the feature in spec #12 and leave one reviewed PR open,? or describe a new feature and request a build. The workflow carries the agreed spec into ticket planning, shows the proposed tickets and blockers in the original conversation, and starts implementation as each dependency passes its checks and lands on the integration branch. Your assigned reviewer receives the combined change, individual ticket results and integration suite. You receive one open PR and decide when to merge. [Multi-ticket workflow](skills/workflow/references/multi-ticket.md)

## Build an existing ticket

Configure the selected CLI profiles and point `ORCA_WORKFLOW_ROUTING` at their verified policy before dispatch. The [LiteLLM routing guide](skills/workflow/references/routing.md) includes working gateway and CLI configuration examples, read-only preflight commands and the evidence needed to verify a real worker request.

In the same workflow skill, ask "Build #7 and leave the tested and reviewed PR open." The default implementer is Codex and the default reviewer is Claude Code. Set `ORCA_WORKFLOW_IMPLEMENT_CLI` and `ORCA_WORKFLOW_REVIEW_CLI` in the conversation environment to change the defaults (`codex` or `claude`). For a single run you can say "Have Claude Code implement #7 and have Codex review it." The conversation returns the PR with the ticket checks and the review of its exact change. You decide when to merge.

Worker supervision uses the local Orca CLI and Orchestra Auto's POSIX tools. On Windows, use WSL for the upstream ledger/preflight scripts with a verified binding to the existing Orca conversation. The workflow includes path and binding checks in the [single-ticket instructions](skills/workflow/references/single-ticket.md).

## Verify

With the two upstream roots configured, run `python -m unittest discover -s tests -v` in this checkout. The spec-flow tests execute Orchestra Auto’s real design-only route against temporary run storage. They simulate the tracker read-back. A live Orca conversation and permission to publish an issue are needed to verify the interview and actual publication.
