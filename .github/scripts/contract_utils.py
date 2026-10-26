#!/usr/bin/env python3
"""
Shared utilities for data contract scripts.
"""

import json
import os

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# IAM endpoint used for ibm_cloud when IAM_TOKEN_URL is not set (IBM Cloud test).
DEFAULT_IBM_CLOUD_IAM_URL = "https://iam.test.cloud.ibm.com/identity/token"


def get_bearer_token() -> str:
    """Return a "Bearer <token>" string for the configured platform environment.

    Authentication is delegated to wxdi.common.auth (AuthConfig / AuthProvider),
    selected by environment variables:

        PLATFORM_ENV         ibm_cloud (default) | aws_cloud | gov_cloud | on_prem
        PLATFORM_URL         Platform base URL; for on_prem it is also the auth host
        PLATFORM_API_KEY     API key (cloud environments; optional for on_prem)
        PLATFORM_USERNAME    Required for on_prem
        PLATFORM_PASSWORD    on_prem, when no API key is given
        PLATFORM_ACCOUNT_ID  Required for aws_cloud
        IAM_TOKEN_URL        Optional token endpoint override for cloud environments.
                             Defaults to the IBM Cloud test endpoint for ibm_cloud
                             and to the SDK default for the other cloud types.

    Raises:
        RuntimeError: when the configuration is invalid or the token request fails.
    """
    from wxdi.common.auth import AuthConfig, AuthProvider, EnvironmentType

    env_name = (os.environ.get("PLATFORM_ENV") or "ibm_cloud").strip().lower()
    try:
        env_type = EnvironmentType(env_name)
    except ValueError:
        valid = ", ".join(e.value for e in EnvironmentType)
        raise RuntimeError(f"Invalid PLATFORM_ENV '{env_name}'. Expected one of: {valid}")

    params = {
        "environment_type": env_type,
        "api_key": os.environ.get("PLATFORM_API_KEY") or None,
    }
    if env_type == EnvironmentType.ON_PREM:
        params["url"] = os.environ.get("PLATFORM_URL", "").rstrip("/") or None
        params["username"] = os.environ.get("PLATFORM_USERNAME") or None
        params["password"] = os.environ.get("PLATFORM_PASSWORD") or None
    else:
        iam_url = os.environ.get("IAM_TOKEN_URL") or None
        if iam_url is None and env_type == EnvironmentType.IBM_CLOUD:
            iam_url = DEFAULT_IBM_CLOUD_IAM_URL
        params["url"] = iam_url
        if env_type == EnvironmentType.AWS_CLOUD:
            params["account_id"] = os.environ.get("PLATFORM_ACCOUNT_ID") or None

    try:
        token = AuthProvider(AuthConfig(**params)).get_token()
    except Exception as exc:
        raise RuntimeError(f"Failed to obtain {env_type.value} token: {exc}") from exc
    return f"Bearer {token}"


def extract_project_id(contract_file: str, fallback: str) -> str:
    """Return the projectId from a contract file's top-level customProperties.

    Looks for:
        customProperties:
          - property: projectId
            value: <uuid>

    Works for both JSON (.json) and YAML (.yaml / .yml) contract files.
    Falls back to `fallback` when:
      - the file cannot be parsed
      - customProperties is absent
      - no entry with property == "projectId" exists

    Args:
        contract_file: Path to the contract file.
        fallback: Value to return when projectId is not found in the file.

    Returns:
        The projectId string from the file, or `fallback`.
    """
    try:
        with open(contract_file, "r", encoding="utf-8") as fh:
            content = fh.read()

        ext = os.path.splitext(contract_file)[1].lower()
        if ext == ".json":
            doc = json.loads(content)
        elif ext in (".yaml", ".yml"):
            if not _YAML_AVAILABLE:
                return fallback
            doc = yaml.safe_load(content)
        else:
            # Try JSON first, then YAML
            try:
                doc = json.loads(content)
            except json.JSONDecodeError:
                if _YAML_AVAILABLE:
                    doc = yaml.safe_load(content)
                else:
                    return fallback

        custom_props = doc.get("customProperties") if isinstance(doc, dict) else None
        if not custom_props:
            return fallback

        for prop in custom_props:
            if isinstance(prop, dict) and prop.get("property") == "projectId":
                value = prop.get("value")
                if value and isinstance(value, str):
                    return value.strip()

    except Exception:
        pass

    return fallback
