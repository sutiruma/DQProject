#!/usr/bin/env python3
"""
Validate a single data contract file using the data-intelligence-sdk.

Usage:
    python validate_contract.py <contract_file>

Environment variables:
    PLATFORM_URL        - (required) Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    PLATFORM_ENV        - ibm_cloud (default) | aws_cloud | gov_cloud | on_prem
    PLATFORM_API_KEY    - API key (cloud); optional for on_prem when username/password is used
    PLATFORM_USERNAME   - on_prem only
    PLATFORM_PASSWORD   - on_prem only, when no API key is given
    PLATFORM_ACCOUNT_ID - aws_cloud only
    IAM_TOKEN_URL       - optional token endpoint override (cloud environments)
A fresh bearer token is obtained at runtime via wxdi.common.auth.

Project ID is read exclusively from customProperties.projectId in the contract file.

Exit codes:
    0 - contract is valid
    1 - contract is invalid or an error occurred
"""

import os
import sys
import importlib.util

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
extract_project_id = _mod.extract_project_id
get_bearer_token = _mod.get_bearer_token


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_contract.py <contract_file>", file=sys.stderr)
        return 1

    contract_file = sys.argv[1]

    cpd_url  = os.environ.get("PLATFORM_URL", "").rstrip("/")

    # Project ID comes exclusively from customProperties.projectId in the file
    project_id = extract_project_id(contract_file, "")

    if not cpd_url or not project_id:
        missing = [n for n, v in [("PLATFORM_URL", cpd_url)] if not v]
        if not project_id:
            print(
                f"ERROR: customProperties.projectId not found in {contract_file}.",
                file=sys.stderr,
            )
        if missing:
            print(f"ERROR: missing required env vars: {', '.join(missing)}", file=sys.stderr)
        return 1

    print(f"Using project_id={project_id} for {contract_file}")

    try:
        bearer_token = get_bearer_token()
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
