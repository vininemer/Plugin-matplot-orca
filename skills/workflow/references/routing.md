# Route the assigned CLI through LiteLLM

Each `dispatch` keeps Orca’s selected CLI and supplies its verified LiteLLM alias as `--model`. The gateway classifies each request in that session. The helper reads local configuration and never changes accounts, starts a proxy, or sends model requests during preflight.

## Use the existing worker account

1. Determine which host, CLI account, managed settings and execution surface Orca uses **for the worker**. Check the effective profile for the target repository, including project and managed overrides. Native chat, Terminal, WSL and a coordinator shell can use different profiles. Orca’s top-level worker launch has no per-launch environment or profile switch. If you cannot verify which settings the worker uses, report the limitation before dispatch.
2. Get the configuration of the running LiteLLM gateway from its operator. Use version 1.109.0 or later for ChatGPT subscription routing. Confirm that it matches the running model list, dynamic settings and key permissions. Check that the worker key is restricted to its alias and the selected models are available to the account. If the gateway or effective credential source is opaque, stop. `GET /v1/models` can confirm key access, but cannot establish where a model group sends requests.
3. For a gateway you operate, [gateway.example.json](gateway.example.json) shows two subscription routers in JSON, which LiteLLM also accepts as YAML. Substitute enabled model IDs and retain your existing key and database setup. Each tier and default names a real model group. The heuristic classifier runs locally on every request (`classification_mode: every_request`, the LiteLLM default) and context compaction is off. A repeated tier target is valid. Verify the gateway has no API credentials or saved upstream login available as a substitute for the subscription worker. Claude token-count requests can use configured credentials. Keep the subscription route free of paid alternatives. [LiteLLM Auto Router setup](https://docs.litellm.ai/docs/auto_router/setup)
4. Copy [routing.example.json](routing.example.json) outside the target repo. Set `cli_config` to the actual active CLI file and `gateway_config` to the running configuration or its complete equivalent JSON export. Relative paths resolve beside the policy. Read YAML with a Python environment containing PyYAML (for example the gateway’s), or supply JSON with the same fields. Reading Codex TOML requires Python 3.11+ or `tomli` on 3.10. Set the gateway URL, public alias, billing choice and exact enabled provider/model IDs per CLI.
5. Confirm the worker’s authentication, effective model/provider settings, alias access, absence of conflicting overrides, and gateway configuration on its host. For Codex include the actual background server, which may retain older settings. For Claude include user, project, local and managed settings and external provider environment overrides. Set `worker_host_verified` to `true` for that verified binding only. Invalidate it when the account, execution host, config, key permissions or gateway changes. The flag records the operator’s checks. The helper also reads the referenced client and gateway files every time.

### Codex with ChatGPT

Keep the active ChatGPT login. A provider in its active `config.toml` can look like the following. Use the worker's real gateway URL. Set the referenced virtual key in the worker environment or its Codex home’s private `.env`. Leave `env_key` unset. If Orca's worker model selector needs catalog discovery, register the router alias in that CLI’s model catalog as described upstream. Check the active provider on the worker, including any named profile. [Codex subscription connection](https://docs.litellm.ai/docs/tutorials/openai_codex_byok) · [Codex Auto Router and catalog](https://docs.litellm.ai/docs/tutorials/codex_chatgpt_auto_router)

```toml
model_provider = "litellm_subscription"
[model_providers.litellm_subscription]
name = "LiteLLM subscription"
base_url = "https://gateway.example.com/v1"
wire_api = "responses"
supports_websockets = false
requires_openai_auth = true
env_http_headers = { "x-litellm-api-key" = "LITELLM_API_KEY" }
```

### Claude Code with a subscription

Keep Claude Code's subscription OAuth login. Use the LiteLLM gateway root as `ANTHROPIC_BASE_URL`. A provider pass-through path such as `/anthropic` bypasses the subscription-aware route. Set the following values in the active worker environment or the `env` object of its settings. Resolve conflicting `apiKeyHelper`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY` or alternate-provider settings with the developer. The helper checks the specified settings file plus its process environment. Verify any other layers separately. Allow the exact public alias in managed `availableModels` when the organization uses that list. Use a virtual key scoped to the router to prevent a background model override from reaching another route. [Claude subscription connection](https://docs.litellm.ai/docs/tutorials/claude_code_max_subscription) · [Claude Auto Router](https://docs.litellm.ai/docs/tutorials/claude_code_autorouter)

```text
ANTHROPIC_BASE_URL=https://gateway.example.com
ANTHROPIC_CUSTOM_HEADERS=x-litellm-api-key: Bearer <scoped-virtual-key>
ANTHROPIC_MODEL=claude-auto
```

### Separately billed models

Report any subscription limitation in the conversation first. Proceed only if the developer explicitly chooses the provider and models. Use a separate configured gateway route and scoped key for that choice. The plugin never selects another profile automatically. For Codex, point the active Responses provider at the API gateway, use `env_key` for its virtual key, disable `requires_openai_auth` and remove the subscription header. For Claude Code, configure the API gateway root and its scoped key in `ANTHROPIC_AUTH_TOKEN` without a subscription custom header. The gateway tier uses a direct `openai/` or `anthropic/` model and the gateway’s approved provider credential.

Set the binding to `"billing": "api"` with the selected alias and models. Add `--allow-api-model PROVIDER/MODEL` for **each** approved model on both preflight and each dispatch. A saved policy alone cannot opt in. A failing subscription dispatch returns the limitation to the coordinator.

## Check and launch

From the coordinator, set the path to the verified policy and run the installed helper for each assigned CLI. For example, from the plugin checkout in PowerShell:

```powershell
$env:ORCA_WORKFLOW_ROUTING = 'C:\private\orca-routing.json'
python skills/workflow/scripts/ticket_flow.py route-check --agent codex
python skills/workflow/scripts/ticket_flow.py route-check --agent claude
```

Use the same policy environment (or `--routing-file PATH`) for the real dispatch. Read preflight output for the selected CLI, billing type, alias and enabled model IDs. If a required profile, route or consent is missing, report it in the conversation. Confirm the actual worker received the alias in the Orca receipt or transcript. A successful preflight establishes local configuration only.

## Record real requests

For the first live check, start one ten-minute clock in the original Orca conversation **before any setup or authentication**. Resolve one small ticket through the ordinary single-ticket path, with Codex implementing and Claude Code reviewing the tested PR change. Use the actual Orca dispatch IDs, observed worker session/time windows, and distinct scoped key identities or gateway request IDs visible from the worker to disambiguate the logs. An alias and an overlapping timestamp alone are insufficient when other sessions share the key.

Open Logs on the verified gateway. Match a successful model request to each worker, inspect its router model group, selected upstream model, credential source and routing decision. Claude subscription rows must show `metadata.used_client_oauth_token=true`; for Codex verify a direct `chatgpt/` model and the confirmed client ChatGPT login on the profile-only gateway. A classifier prediction and a model list cannot substitute for a served request. [LiteLLM spend logs](https://docs.litellm.ai/docs/proxy/cost_tracking) · [Codex log fields](https://docs.litellm.ai/docs/tutorials/codex_chatgpt_auto_router#step-4-verify-routing)

Transcribe only the run ID, dispatch ID, CLI, UTC request time, gateway request ID, router alias, selected provider/model and credential type into the evidence. Keep raw logs, headers, keys, session prompts, account IDs and responses out of the PR. Report the actual ticket/test, review of its head, open PR link and both sanitized routing records in the original conversation. A model switch is optional. When time expires, stop, state the last verified step, and identify each missing artifact.
