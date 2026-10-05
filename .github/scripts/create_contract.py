#!/usr/bin/env python3
"""
Create data contracts in a CPD/watsonx project.

Two modes:

  --mode pr   (PR validation)
      Creates an ephemeral contract named "<contract_name>_PR_<pr_number>".
      The contract is used for CI testing only and deleted afterwards.
      Emits contract_ids as "<project_id>:<contract_id>" pairs.

  --mode merge  (post-merge upsert)
      Creates or replaces the real contract using the canonical name from
      the contract file. This is the production upsert path.

Usage:
    python create_contract.py --mode pr   --pr-number <N> <file1> [<file2> ...]
    python create_contract.py --mode merge               <file1> [<file2> ...]

Environment variables (required):
    PLATFORM_URL     - Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    PLATFORM_API_KEY - IBM Cloud IAM API key; a fresh bearer token is obtained at runtime

Project ID is read exclusively from customProperties.projectId in each contract file.

Exit codes:
    0 - all contracts created/updated successfully
    1 - one or more contracts failed or an error occurred

Writes GITHUB_OUTPUT:
    body         - Markdown summary for PR comment
    contract_ids - Space-separated list of <project_id>:<contract_id> pairs
"""

import os
import sys
import argparse
import importlib.util
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from wxdi.data_contracts import DataContractsProvider
from wxdi.data_contracts.models import DataContractPrototypeYaml
from wxdi.dq_validator.provider.config import ProviderConfig

# Load contract_utils from the same directory as this script
_utils_path = os.path.join(os.path.dirname(__file__), "contract_utils.py")
_spec = importlib.util.spec_from_file_location("contract_utils", _utils_path)
_mod  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
extract_target_info = _mod.extract_target_info

IAM_TOKEN_URL = "https://iam.test.cloud.ibm.com/identity/token"


def get_dph_client(cpd_url: str, bearer_token: str):
    """Create and return a configured DphV1 client."""
    from wxdi.dph_services import DphV1
    from ibm_cloud_sdk_core.authenticators import BearerTokenAuthenticator

    raw_token = bearer_token.replace("Bearer ", "").strip()
    authenticator = BearerTokenAuthenticator(raw_token)
    dph = DphV1(authenticator=authenticator)
    dph.set_service_url(cpd_url)
    return dph


def get_dph_catalog_id(dph) -> str:
    """Fetch default Data Product Hub catalog ID via DphV1.get_initialize_status().

    Validates that DPH initialization has succeeded, then extracts the catalog ID
    from the container.id query parameter in the response href.
    """
    from urllib.parse import urlparse, parse_qs

    resp = dph.get_initialize_status()
    res = resp.get_result() if hasattr(resp, "get_result") else resp.result

    status = res.get("status", "")
    if status != "succeeded":
        raise RuntimeError(
            f"DPH initialization has not succeeded (status={status}). "
            "Ensure the DPH instance is fully initialized before running contracts."
        )

    # Extract catalog ID from container.id query param in href
    href = res.get("href", "")
    catalog_id = parse_qs(urlparse(href).query).get("container.id", [None])[0]
    if not catalog_id:
        raise RuntimeError(f"DPH catalog container ID not found in href: {href!r}")

    return catalog_id


def get_draft_contract_info(dph, draft_id: str, data_product_id: str = "-") -> tuple:
    """Fetch draft details and return (existing_contract_id, resolved_contract_terms_id)."""
    print(f"  Fetching draft {draft_id} ...")
    resp = dph.get_data_product_draft(
        data_product_id=data_product_id,
        draft_id=draft_id,
    )
    res = resp.get_result() if hasattr(resp, "get_result") else resp.result
    contract_terms_list = res.get("contract_terms") or []
    if not contract_terms_list:
        raise RuntimeError(f"No contract_terms found in draft {draft_id}")

    target_terms = contract_terms_list[0]
    resolved_terms_id = target_terms.get("id")
    if not resolved_terms_id:
        raise RuntimeError(f"Missing id in contract_terms for draft {draft_id}")

    existing_contract_id = target_terms.get("data_contract_id") or ""

    return existing_contract_id, resolved_terms_id


def link_contract_to_data_product_draft(dph, draft_id: str, contract_terms_id: str, contract_id: str, data_product_id: str = "-"):
    """Link data contract to draft contract terms using an 'add' JSON patch."""
    from wxdi.dph_services.dph_v1 import JsonPatchOperation

    print(f"  Linking contract {contract_id} to draft {draft_id} (contract_terms_id: {contract_terms_id}) ...")
    patch_op = JsonPatchOperation(op="add", path="/data_contract_id", value=contract_id)
    dph.update_data_product_draft_contract_terms(
        data_product_id=data_product_id,
        draft_id=draft_id,
        contract_terms_id=contract_terms_id,
        json_patch_instructions=[patch_op],
    )
    print(f"  Successfully linked data_contract_id={contract_id} to draft {draft_id}")


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pr", "merge"], required=True,
                        help="'pr' creates an ephemeral contract; 'merge' upserts the real one")
    parser.add_argument("--pr-number", default="",
                        help="PR number — required when --mode pr")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    if not args.files:
        print("No contract files provided — nothing to create.")
        return 0

    if args.mode == "pr" and not args.pr_number:
        print("ERROR: --pr-number is required when --mode pr", file=sys.stderr)
        return 1

    cpd_url = os.environ.get("PLATFORM_URL", "").rstrip("/")
    api_key = os.environ.get("PLATFORM_API_KEY", "")

    bearer   = get_bearer_token(api_key)
    config   = ProviderConfig(url=cpd_url, auth_token=bearer)
    provider = DataContractsProvider(config)

    result_lines   = []
    contract_pairs = []

    # Cache DPH client and catalog id if needed
    dph_client = None
    dph_catalog_id = None

    for f in args.files:
        canonical_name = os.path.splitext(os.path.basename(f))[0]

        # In PR mode use an ephemeral name so the real contract is untouched
        if args.mode == "pr":
            name = f"{canonical_name}_PR_{args.pr_number}"
        else:
            name = canonical_name

        target = extract_target_info(f)
        is_dph = target.get("is_dph", False)
        contract_type = target.get("type", "").lower()
        draft_id = target.get("draft_id", "")
        data_product_id = "-"
        project_id = target.get("project_id", "")

        if is_dph:
            if not dph_client:
                dph_client = get_dph_client(cpd_url, bearer)
            if not dph_catalog_id:
                try:
                    dph_catalog_id = get_dph_catalog_id(dph_client)
                except Exception as exc:
                    print(f"ERROR: Failed to resolve DPH catalog for {f}: {exc}", file=sys.stderr)
                    sys.exit(1)

            # When type is "contract", draftId is mandatory
            is_contract_type = contract_type == "contract"
            if is_contract_type and not draft_id:
                print(f"ERROR: customProperties.draftId is required when isDPH is true and type is 'contract' in {f}.",
                      file=sys.stderr)
                sys.exit(1)

            container_id = dph_catalog_id
            container_type = "catalog"
            print(f"[{args.mode}] Using DPH catalog_id={container_id}, contract name='{name}' for {f}")
        else:
            if not project_id:
                print(f"ERROR: customProperties.projectId not found (and isDPH is not true) in {f}.",
                      file=sys.stderr)
                sys.exit(1)

            container_id = project_id
            container_type = "project"
            print(f"[{args.mode}] Using project_id={container_id}, contract name='{name}' for {f}")

        with open(f, "r", encoding="utf-8") as fh:
            content = fh.read()

        if container_type == "catalog":
            collection = provider.list_catalog_data_contracts(container_id, limit=200)
            
            # Match existing contract by name and type (if type property is present on the asset)
            def _matches_catalog_dc(dc) -> bool:
                if dc.name != name:
                    return False
                if contract_type:
                    dc_type = getattr(dc, "type", None) or (getattr(dc, "model_extra", {}) or {}).get("type") or ((getattr(dc, "model_extra", {}) or {}).get("entity", {}).get("ibm_data_contract", {}) or {}).get("type")
                    if dc_type and str(dc_type).lower() != contract_type:
                        return False
                return True

            existing = next((dc for dc in collection.data_contracts if _matches_catalog_dc(dc)), None)

            # In DPH contract mode, check draft for an existing attached contract
            existing_draft_contract_id = ""
            resolved_terms_id = ""
            if is_contract_type:
                try:
                    existing_draft_contract_id, resolved_terms_id = get_draft_contract_info(
                        dph=dph_client,
                        draft_id=draft_id,
                        data_product_id=data_product_id,
                    )
                except Exception as exc:
                    print(f"ERROR: Failed to inspect draft {draft_id}: {exc}", file=sys.stderr)
                    sys.exit(1)

            # Determine target contract ID to replace (draft's attached contract takes priority)
            target_replace_id = existing_draft_contract_id or (existing.id if existing else None)

            body = DataContractPrototypeYaml(name=name, contract_yaml=content)
            if target_replace_id:
                # PUT / replace operation on existing contract in catalog
                print(f"  Existing contract found (id={target_replace_id}). Performing PUT/replace operation in catalog ...")
                contract = provider.replace_catalog_data_contract(
                    container_id, target_replace_id, body, validate=True
                )
                if args.mode == "pr":
                    result_lines.append(f"### 🔄 `{f}` — ephemeral DPH contract updated (name: `{name}`, id: `{contract.id}`)")
                else:
                    result_lines.append(f"### 🔄 `{f}` — updated in DPH catalog (id: `{contract.id}`)")
                print(f"Updated DPH contract {f}  →  name={name}  id={contract.id}")
            else:
                # POST / create new contract in catalog
                contract = provider.create_catalog_data_contract(
                    container_id, body, validate=True
                )
                # Link newly created contract to data product draft
                if is_contract_type:
                    try:
                        link_contract_to_data_product_draft(
                            dph=dph_client,
                            draft_id=draft_id,
                            contract_terms_id=resolved_terms_id,
                            data_product_id=data_product_id,
                            contract_id=contract.id,
                        )
                    except Exception as exc:
                        print(f"ERROR: Failed to link contract {contract.id} to draft {draft_id}: {exc}", file=sys.stderr)
                        sys.exit(1)

                if args.mode == "pr":
                    result_lines.append(f"### ✅ `{f}` — ephemeral DPH contract created (name: `{name}`, id: `{contract.id}`)")
                else:
                    result_lines.append(f"### ✅ `{f}` — created in DPH catalog (id: `{contract.id}`)")
                print(f"Created DPH contract {f}  →  name={name}  id={contract.id}")
        else:
            collection = provider.list_project_data_contracts(container_id, limit=200)
            existing   = next((dc for dc in collection.data_contracts if dc.name == name), None)
            body       = DataContractPrototypeYaml(name=name, contract_yaml=content)
            if existing:
                contract = provider.replace_project_data_contract(
                    container_id, existing.id, body, validate=True
                )
                if args.mode == "pr":
                    result_lines.append(f"### 🔄 `{f}` — ephemeral contract updated (name: `{name}`, id: `{contract.id}`)")
                else:
                    result_lines.append(f"### 🔄 `{f}` — updated (id: `{contract.id}`)")
                print(f"Updated  {f}  →  name={name}  id={contract.id}")
            else:
                contract = provider.create_project_data_contract(
                    container_id, body, validate=True
                )
                if args.mode == "pr":
                    result_lines.append(f"### ✅ `{f}` — ephemeral contract created (name: `{name}`, id: `{contract.id}`)")
                else:
                    result_lines.append(f"### ✅ `{f}` — created (id: `{contract.id}`)")
                print(f"Created  {f}  →  name={name}  id={contract.id}")

        contract_pairs.append(f"{container_id}:{contract.id}")

    if args.mode == "pr":
        md_title = "## 📦 Data Contract Create (Ephemeral — PR validation)"
    else:
        md_title = "## 📦 Data Contract Create"

    md = md_title + "\n\n" + "\n\n".join(result_lines) + "\n"
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as out:
            out.write("body<<EOF\n")
            out.write(md + "\n")
            out.write("EOF\n")
            out.write("contract_ids=" + " ".join(contract_pairs) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
