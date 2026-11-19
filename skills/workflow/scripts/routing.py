"""Resolve the assigned worker's LiteLLM Auto Router before Orca starts it."""

from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def only_keys(mapping, allowed, reason):
    require(isinstance(mapping, dict) and set(mapping) <= set(allowed), reason)


def name(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)


def gateway_models(config, alias, agent, billing):
    only_keys(config, {"model_list", "general_settings", "litellm_settings", "router_settings"},
              "Unsupported gateway configuration, include or fallback")
    # Billing can change at a scope outside the selected model group.
    for section in ("general_settings", "litellm_settings", "router_settings"):
        settings = config.get(section, {})
        require(isinstance(settings, dict), "Invalid gateway settings")
        for key, value in settings.items():
            if value and re.search(r"fallback|alias|model|provider|router|hook|callback|credential|"
                                   r"pass_through|passthrough|default_team|deployment|prompt_management|"
                                   r"api_base|api_key|mirror", key, re.I):
                raise ValueError(f"Verify gateway routing or credential overrides in {section}")
    entries = config.get("model_list")
    require(isinstance(entries, list) and entries, "Expected deployed LiteLLM model_list")
    groups = {}
    for entry in entries:
        require(isinstance(entry, dict) and isinstance(entry.get("model_name"), str),
                "Expected named LiteLLM deployments")
        groups.setdefault(entry["model_name"], []).append(entry)

    def deployment(group):
        require(name(group) and len(groups.get(group, [])) == 1
                and not any(pattern != group and fnmatchcase(group, pattern) for pattern in groups),
                "Missing or ambiguous Auto Router alias, tier or default deployment")
        row = groups[group][0]
        only_keys(row, {"model_name", "litellm_params", "model_info"}, "Opaque deployment settings")
        return row

    router = deployment(alias)
    params = router.get("litellm_params")
    only_keys(params, {"model", "complexity_router_default_model", "complexity_router_config"},
              "Unexpected Auto Router settings")
    require(params.get("model") == "auto_router/complexity_router", "Alias must select LiteLLM Auto Router")
    classifier = params.get("complexity_router_config")
    only_keys(classifier, {"classifier_type", "tiers", "context_compaction", "classification_mode"},
              "Unsupported classifier, escalation or fallback settings")
    require(classifier.get("classifier_type", "heuristic") == "heuristic"
            and classifier.get("context_compaction") is False
            and classifier.get("classification_mode", "user_turn") == "user_turn",
            "Use the local heuristic per turn with context compaction disabled")
    tiers = classifier.get("tiers")
    require(isinstance(tiers, dict) and set(tiers) == {"SIMPLE", "MEDIUM", "COMPLEX", "REASONING"},
            "Configure all four LiteLLM tiers")
    provider = ("chatgpt" if billing == "subscription" else "openai") if agent == "codex" else "anthropic"
    models = set()
    for group in [*tiers.values(), params.get("complexity_router_default_model")]:
        row = deployment(group)
        cfg = row.get("litellm_params")
        only_keys(cfg, {"model"} if billing == "subscription" else {"model", "api_key"},
                  "Unverified credential or provider override in a tier")
        model = cfg.get("model")
        require(isinstance(model, str) and model.startswith(provider + "/") and name(model.split("/", 1)[1]),
                f"Expected a direct {provider} deployment for {agent}")
        mode = row.get("model_info", {})
        require(isinstance(mode, dict), "Invalid deployment metadata")
        if agent == "codex":
            require(mode.get("mode") == "responses", "Codex needs a Responses deployment")
        else:
            require(mode.get("mode", "chat") in ("chat", "anthropic_messages"), "Claude needs a Messages deployment")
        models.add(model)
    return models


def read_object(path, *, gateway=False):
    source = path.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(source)
    except ValueError:
        if not gateway:
            raise ValueError(f"Invalid JSON in {path.name}") from None
        try:
            import yaml
        except ImportError:
            raise ValueError("Read gateway YAML with PyYAML, or use the JSON form of the deployed configuration") from None
        try:
            value = yaml.safe_load(source)
        except yaml.YAMLError:
            raise ValueError("Invalid gateway YAML") from None
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def codex_profile(path, gateway, billing):
    try:
        import tomllib
    except ImportError:  # Python 3.10
        try:
            import tomli as tomllib
        except ImportError:
            raise ValueError("Reading Codex TOML requires Python 3.11+ or tomli on Python 3.10") from None
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise ValueError("Invalid Codex configuration TOML") from None
    provider_name = config.get("model_provider")
    if "profile" in config:
        profile = config.get("profiles", {}).get(config["profile"])
        require(isinstance(profile, dict), "Selected Codex profile is missing")
        provider_name = profile.get("model_provider", provider_name)
    provider = config.get("model_providers", {}).get(provider_name)
    require(isinstance(provider, dict) and provider.get("base_url", "").rstrip("/") == gateway + "/v1"
            and provider.get("wire_api") == "responses" and provider.get("supports_websockets") is False,
            "Active Codex provider must use this gateway's /v1 Responses endpoint over HTTP")
    require(not any(provider.get(key) for key in ("experimental_bearer_token", "http_headers", "auth")),
            "Active Codex provider has conflicting credential overrides")
    if billing == "subscription":
        headers = provider.get("env_http_headers", {})
        require(provider.get("requires_openai_auth") is True and not provider.get("env_key")
                and isinstance(headers, dict) and set(headers) == {"x-litellm-api-key"},
                "Codex must preserve the ChatGPT login and use a separate LiteLLM header")
        key = headers["x-litellm-api-key"]
    else:
        require(not provider.get("requires_openai_auth") and not provider.get("env_http_headers"),
                "The API provider must use the gateway virtual key for authentication")
        key = provider.get("env_key")
    require(isinstance(key, str) and re.fullmatch(r"[A-Z_][A-Z0-9_]*", key), "Expected gateway key variable")
    if not os.environ.get(key):
        dotenv = path.parent / ".env"
        require(dotenv.is_file() and any(re.fullmatch(r"(?:export\s+)?" + key + r"\s*=\s*\S+\s*", line)
                and line.split("=", 1)[1].strip().strip("\"'") for line in dotenv.read_text(
                    encoding="utf-8-sig").splitlines()), "Gateway key missing from the Codex profile environment")


def claude_profile(path, gateway, alias, billing):
    settings = read_object(path)
    env = settings.get("env", {})
    require(isinstance(env, dict), "Invalid Claude settings environment")
    # Check process-level conflicts too. Only the operator can verify that a managed
    # worker actually inherits these settings; the coordinator cannot inject them.
    for key, value in env.items():
        if key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")) and os.environ.get(key):
            require(os.environ[key] == value, "Claude settings conflict with the execution environment")
    env = {**os.environ, **env}
    require(env.get("ANTHROPIC_BASE_URL", "").rstrip("/") == gateway,
            "Active Claude profile must use this LiteLLM gateway root")
    require(not settings.get("apiKeyHelper") and not env.get("ANTHROPIC_API_KEY")
            and not any(env.get(k, "").lower() in ("1", "true") for k in
                        ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")),
            "Active Claude profile contains a competing provider or credential")
    allowed = settings.get("availableModels")
    require(allowed is None or isinstance(allowed, list) and alias in allowed,
            "Claude managed availableModels must allow the router alias")
    headers = env.get("ANTHROPIC_CUSTOM_HEADERS", "")
    if billing == "subscription":
        require(not env.get("ANTHROPIC_AUTH_TOKEN")
                and re.fullmatch(r"x-litellm-api-key:\s*Bearer\s+\S+", headers.strip(), re.I),
                "Claude must preserve subscription OAuth and provide a separate LiteLLM header")
    else:
        require(env.get("ANTHROPIC_AUTH_TOKEN") and not headers,
                "Claude API routing requires its scoped gateway token")


def route(args, agent):
    location = args.routing_file or os.environ.get("ORCA_WORKFLOW_ROUTING")
    if not location:
        raise ValueError(f"No routing policy for {agent}. Set ORCA_WORKFLOW_ROUTING to your "
                         "verified worker policy. See references/routing.md.")
    policy = Path(location)
    binding = read_object(policy).get(agent)
    if not isinstance(binding, dict) or binding.get("worker_host_verified") is not True:
        raise ValueError(f"Verify the active {agent} worker execution profile in references/routing.md")
    alias = binding.get("alias")
    billing = binding.get("billing")
    require(name(alias) and billing in ("subscription", "api"), "Expected a router alias and billing mode")
    require(not getattr(args, "model", None) or args.model == alias, "Model override differs from the verified alias")
    config_path = binding.get("gateway_config")
    require(isinstance(config_path, str) and config_path, "Specify the deployed gateway_config file")
    models = gateway_models(read_object(policy.parent / config_path, gateway=True), alias, agent, billing)
    enabled = binding.get("enabled_models")
    require(isinstance(enabled, list) and all(isinstance(m, str) for m in enabled) and set(enabled) == models,
            "Deployed tiers/default differ from the developer's enabled_models")
    if billing == "api":
        require(set(args.allow_api_model) == models,
                "Separate API billing requires explicit --allow-api-model for each enabled provider/model")
    gateway = binding.get("gateway_url")
    require(isinstance(gateway, str), "Specify the verified gateway_url")
    gateway = gateway.rstrip("/")
    url = urlsplit(gateway)
    require(url.hostname and not (url.username or url.password or url.query or url.fragment)
            and (url.scheme == "https" or url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")),
            "Use a gateway URL without embedded credentials (HTTPS or local loopback)")
    profile = binding.get("cli_config")
    require(isinstance(profile, str) and profile, "Specify the active worker cli_config file")
    if agent == "codex":
        codex_profile(policy.parent / profile, gateway, billing)
    else:
        claude_profile(policy.parent / profile, gateway, alias, billing)
    return {"agent": agent, "alias": alias, "billing": billing, "enabled_models": sorted(models)}
