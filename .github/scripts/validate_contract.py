#!/usr/bin/env python3
"""
Validate a single data contract file using the data-intelligence-sdk.

Usage:
    python validate_contract.py <contract_file>

Environment variables (required):
    PLATFORM_URL     - Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    PLATFORM_API_KEY - IBM Cloud IAM API key; a fresh bearer token is obtained at runtime

For non-DPH contracts: projectId is read from customProperties.projectId in the contract file.
For DPH contracts (isDPH=true): validation is performed against the DPH catalog.

Exit codes:
    0 - contract is valid
    1 - contract is invalid or an error occurred
"""

import os
import sys
import importlib.util

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from wxdi.data_contracts import DataContractsProvider
from wxdi.data_contracts.models import DataContractValidationRequest
from wxdi.dq_validator.provider.config import ProviderConfig

# Load contract_utils from the same directory as this script
_utils_path = os.path.join(os.path.dirname(__file__), "contract_utils.py")
_spec = importlib.util.spec_from_file_location("contract_utils", _utils_path)
_mod  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
extract_target_info = _mod.extract_target_info

IAM_TOKEN_URL = "https://iam.test.cloud.ibm.com/identity/token"


def get_bearer_token(api_key: str) -> str:
    """Exchange an IBM Cloud IAM API key for a fresh bearer token."""
    resp = requests.post(
        IAM_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Failed to obtain IAM token: {resp.status_code} {resp.text}"
        )
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("IAM response did not contain access_token")
    return f"Bearer {token}"


def get_dph_catalog_id(cpd_url: str, bearer_token: str) -> str:
    """Fetch the default DPH catalog ID via DphV1.get_initialize_status()."""
    try:
        from wxdi.dph.v1 import DphV1
    except ImportError:
        try:
            from wxdi.dph_v1 import DphV1
        except ImportError:
            from ibm_watsonx_data.dph_v1 import DphV1

    from ibm_cloud_sdk_core.authenticators import BearerTokenAuthenticator

    raw_token = bearer_token.replace("Bearer ", "").strip()
    authenticator = BearerTokenAuthenticator(raw_token)
    dph = DphV1(authenticator=authenticator)
    dph.set_service_url(cpd_url)

    resp = dph.get_initialize_status()
    res = resp.get_result() if hasattr(resp, "get_result") else resp.result
    catalog_id = (res.get("container") or {}).get("id")
    if not catalog_id:
        raise RuntimeError(f"DPH catalog container ID not found (status={res.get('status')})")
    return catalog_id


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_contract.py <contract_file>", file=sys.stderr)
        return 1

    contract_file = sys.argv[1]

    cpd_url = os.environ.get("PLATFORM_URL", "").rstrip("/")
    api_key = os.environ.get("PLATFORM_API_KEY", "")

    missing_env = [n for n, v in [("PLATFORM_URL", cpd_url), ("PLATFORM_API_KEY", api_key)] if not v]
    if missing_env:
        print(f"ERROR: missing required env vars: {', '.join(missing_env)}", file=sys.stderr)
        return 1

    target = extract_target_info(contract_file)
    is_dph     = target.get("is_dph", False)
    project_id = target.get("project_id", "")

    if is_dph:
        print(f"DPH contract detected — using catalog-based validation for {contract_file}")
    else:
        if not project_id:
            print(
                f"ERROR: customProperties.projectId not found (and isDPH is not true) in {contract_file}.",
                file=sys.stderr,
            )
            return 1
        print(f"Using project_id={project_id} for {contract_file}")

    try:
        bearer_token = get_bearer_token(api_key)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        with open(contract_file, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        print(f"ERROR: Could not read {contract_file}: {exc}", file=sys.stderr)
        return 1

    config   = ProviderConfig(url=cpd_url, auth_token=bearer_token)
    provider = DataContractsProvider(config)
    body     = DataContractValidationRequest(data_contract_content=content)

    try:
        if is_dph:
            catalog_id = get_dph_catalog_id(cpd_url, bearer_token)
            print(f"Using DPH catalog_id={catalog_id} for {contract_file}")
            result = provider.validate_catalog_data_contract(catalog_id, body)
        else:
            result = provider.validate_project_data_contract(project_id, body)
    except ValueError as exc:
        print(f"ERROR: Validation request failed: {exc}", file=sys.stderr)
        return 1

    if result.valid:
        print(f"VALID: {contract_file}")
        return 0

    # Print structured errors to stdout so the workflow can capture them
    print(f"INVALID: {contract_file} — {result.error_count} error(s)")
    for err in result.errors:
        prop = err.property or "(contract)"
        print(f"  [{err.type}] {prop}: {err.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
