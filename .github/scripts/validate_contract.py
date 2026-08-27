#!/usr/bin/env python3
"""
Validate a single data contract file using the data-intelligence-sdk.

Usage:
    python validate_contract.py <contract_file>

Environment variables (required):
    URL        - Base URL of the instance (e.g. https://cpd-host.example.com)
    TOKEN      - Bearer token (with or without the "Bearer " prefix)
    PROJECT_ID - Project ID that owns the contract

Exit codes:
    0 - contract is valid
    1 - contract is invalid or an error occurred
"""

import os
import sys

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from wxdi.data_contracts import DataContractsProvider
from wxdi.data_contracts.models import DataContractValidationRequest
from wxdi.dq_validator.provider.config import ProviderConfig


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_contract.py <contract_file>", file=sys.stderr)
        return 1

    contract_file = sys.argv[1]

    cpd_url = os.environ.get("URL", "").rstrip("/")
    cpd_token = os.environ.get("TOKEN", "")
    project_id = os.environ.get("PROJECT_ID", "")

    if not cpd_url or not cpd_token or not project_id:
        print(
            "ERROR: URL, TOKEN, and PROJECT_ID environment variables are required.",
            file=sys.stderr,
        )
        return 1

    # Accept token with or without the "Bearer " prefix
    bearer_token = cpd_token if cpd_token.startswith("Bearer ") else f"Bearer {cpd_token}"

    try:
        with open(contract_file, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        print(f"ERROR: Could not read {contract_file}: {exc}", file=sys.stderr)
        return 1

    config = ProviderConfig(url=cpd_url, auth_token=bearer_token)
    provider = DataContractsProvider(config)
    body = DataContractValidationRequest(data_contract_content=content)

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
