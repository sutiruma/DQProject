#!/usr/bin/env python3
"""
Delete ephemeral data contracts from a CPD/watsonx project.

Used after PR validation to clean up ephemeral contracts created with
the _PR_<pr_number> naming pattern.

Usage:
    python delete_contract.py <project_id:contract_id> [<project_id:contract_id> ...]

Environment variables (required):
    PLATFORM_URL     - Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    PLATFORM_API_KEY - IBM Cloud IAM API key; a fresh bearer token is obtained at runtime

Exit codes:
    0 - all contracts deleted (or already absent)
    1 - one or more deletions failed
"""

import os
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from wxdi.data_contracts import DataContractsProvider
from wxdi.dq_validator.provider.config import ProviderConfig

IAM_TOKEN_URL = "https://iam.test.cloud.ibm.com/identity/token"


def get_bearer_token(api_key: str) -> str:
    resp = requests.post(
        IAM_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("IAM response did not contain access_token")
    return f"Bearer {token}"


def main() -> int:
    entries = sys.argv[1:]
    if not entries:
        print("No contract IDs provided — nothing to delete.")
        return 0

    cpd_url = os.environ.get("PLATFORM_URL", "").rstrip("/")
    api_key = os.environ.get("PLATFORM_API_KEY", "")

    bearer   = get_bearer_token(api_key)
    config   = ProviderConfig(url=cpd_url, auth_token=bearer)
    provider = DataContractsProvider(config)

    # Group contract IDs by project so we can batch-delete per project
    by_project: dict[str, list[str]] = {}
    for entry in entries:
        if ":" not in entry:
            print(f"ERROR: entry '{entry}' is not in project_id:contract_id format.",
                  file=sys.stderr)
            return 1
        project_id, cid = entry.split(":", 1)
        by_project.setdefault(project_id, []).append(cid)

    overall = 0
    for project_id, cids in by_project.items():
        ids_csv = ",".join(cids)
        print(f"Deleting {len(cids)} ephemeral contract(s) from project {project_id}: {ids_csv}")
        try:
            provider.delete_project_data_contracts(
                project_id,
                data_contract_ids=ids_csv,
            )
            print(f"  ✅ Deleted: {ids_csv}")
        except ValueError as exc:
            print(f"  ERROR: delete failed for project {project_id}: {exc}",
                  file=sys.stderr)
            overall = 1

    return overall


if __name__ == "__main__":
    sys.exit(main())
