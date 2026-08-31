#!/usr/bin/env python3
"""
Create or replace data contracts in a CPD/watsonx project.

Usage:
    python create_contract.py <file1> [<file2> ...]

Environment variables (required):
    URL        - Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    API_KEY    - IBM Cloud IAM API key; a fresh bearer token is obtained at runtime
    PROJECT_ID - Project ID that owns the contract

Exit codes:
    0 - all contracts created/updated successfully
    1 - one or more contracts failed or an error occurred

Writes GITHUB_OUTPUT:
    body        - Markdown summary for PR comment
    contract_ids - Space-separated list of created/updated contract IDs
"""

import os
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from wxdi.data_contracts import DataContractsProvider
from wxdi.data_contracts.models import DataContractPrototypeYaml
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
    files = sys.argv[1:]
    if not files:
        print("No contract files provided — nothing to create.")
        return 0

    cpd_url    = os.environ.get("URL", "").rstrip("/")
    api_key    = os.environ.get("API_KEY", "")
    project_id = os.environ.get("PROJECT_ID", "")

    bearer     = get_bearer_token(api_key)
    config     = ProviderConfig(url=cpd_url, auth_token=bearer)
    provider   = DataContractsProvider(config)

    result_lines = []
    contract_ids = []

    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, "r", encoding="utf-8") as fh:
            content = fh.read()

        collection = provider.list_project_data_contracts(project_id, limit=200)
        existing   = next((dc for dc in collection.data_contracts if dc.name == name), None)

        body = DataContractPrototypeYaml(name=name, contract_yaml=content)
        if existing:
            contract = provider.replace_project_data_contract(
                project_id, existing.id, body, validate=True
            )
            result_lines.append(f"### 🔄 `{f}` — updated (id: `{contract.id}`)")
            print(f"Updated  {f}  →  id={contract.id}")
        else:
            contract = provider.create_project_data_contract(
                project_id, body, validate=True
            )
            result_lines.append(f"### ✅ `{f}` — created (id: `{contract.id}`)")
            print(f"Created  {f}  →  id={contract.id}")

        contract_ids.append(contract.id)

    md = "## 📦 Data Contract Create\n\n" + "\n\n".join(result_lines) + "\n"
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as out:
            out.write("body<<EOF\n")
            out.write(md + "\n")
            out.write("EOF\n")
            out.write("contract_ids=" + " ".join(filter(None, contract_ids)) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
