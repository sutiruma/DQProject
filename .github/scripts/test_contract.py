#!/usr/bin/env python3
"""
Trigger and poll data contract test runs in a CPD/watsonx project.

Usage:
    python test_contract.py <contract_id1> [<contract_id2> ...]

Environment variables (required):
    URL        - Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    API_KEY    - IBM Cloud IAM API key; a fresh bearer token is obtained at runtime
    PROJECT_ID - Project ID that owns the contract

Exit codes:
    0 - all contract tests completed successfully
    1 - one or more tests failed or an error occurred

Writes GITHUB_OUTPUT:
    body    - Markdown summary for PR comment
    overall - 0 (all passed) or 1 (one or more failed)
"""

import os
import sys
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from wxdi.data_contracts import DataContractsProvider
from wxdi.data_contracts.models import DataContractTestRequest
from wxdi.dq_validator.provider.config import ProviderConfig

IAM_TOKEN_URL = "https://iam.test.cloud.ibm.com/identity/token"

MAX_POLLS     = 30
POLL_INTERVAL = 10


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
    contract_ids = sys.argv[1:]
    if not contract_ids:
        print("No contract IDs provided — nothing to test.")
        return 0

    cpd_url    = os.environ.get("URL", "").rstrip("/")
    api_key    = os.environ.get("API_KEY", "")
    project_id = os.environ.get("PROJECT_ID", "")

    bearer   = get_bearer_token(api_key)
    config   = ProviderConfig(url=cpd_url, auth_token=bearer)
    provider = DataContractsProvider(config)

    result_lines = []
    overall      = 0

    for cid in contract_ids:
        print(f"Triggering test for contract id={cid} ...")
        try:
            test_resp = provider.test_project_data_contract(
                project_id, cid,
                DataContractTestRequest(retain_dq_objects=False),
            )
        except ValueError as exc:
            print(f"ERROR: test trigger failed for {cid}: {exc}", file=sys.stderr)
            overall = 1
            result_lines.append(f"### ❌ `{cid}` — test trigger failed")
            result_lines.append(f"> Error: `{exc}`")
            result_lines.append("")
            continue

        # The API returns `job_run_id`; the SDK model maps it to `id` only
        # when that field name is present — fall back to `job_run_id` from
        # the pydantic extra-fields dict when `id` is None.
        run_id = test_resp.id or (
            test_resp.model_extra or {}
        ).get("job_run_id")
        if not run_id:
            raw = test_resp.model_dump()
            print(f"WARNING: could not resolve run_id for contract {cid}. "
                  f"Raw response: {raw}", file=sys.stderr)
            overall = 1
            result_lines.append(f"### ❌ `{cid}` — test trigger returned no run ID")
            result_lines.append(f"> Raw response (all fields): `{raw}`")
            result_lines.append("")
            continue

        print(f"  run_id={run_id} — polling ...")
        result = None
        for _ in range(MAX_POLLS):
            result = provider.get_project_data_contract_test_result(
                project_id, cid, run_id, include_all_details=True
            )
            if result.status in ("completed", "failed"):
                break
            time.sleep(POLL_INTERVAL)

        status = result.status if result else "unknown"
        start  = result.start  if result else "-"
        end    = result.end    if result else "-"
        run_by = result.run_by if result else "-"

        if status == "completed":
            result_lines.append(f"### ✅ `{cid}` — test completed")
        else:
            overall = 1
            result_lines.append(f"### ❌ `{cid}` — test **{status}**")

        result_lines.append(
            f"> Run ID: `{run_id}` | Started: {start} | Ended: {end} | Run by: {run_by}"
        )

        if result and result.check_results:
            # Determine whether any check failed — if so, add a Message column
            any_failed = any(
                (cr.status or "").lower() in ("failed", "error")
                for cr in result.check_results
            )
            if any_failed:
                rows = ["| Rule | Status | Passed | Message |", "|---|---|---|---|"]
            else:
                rows = ["| Rule | Status | Passed |", "|---|---|---|"]

            for cr in result.check_results:
                # check_name may be None if the API uses a different field name;
                # fall back to model_extra keys like "rule_name" or "name"
                extra = cr.model_extra or {}
                rule = (
                    cr.check_name
                    or extra.get("rule_name")
                    or extra.get("name")
                    or "-"
                )
                st  = cr.status or "-"
                chk = "✅" if cr.passed else ("❌" if cr.passed is False else "-")
                if any_failed:
                    msg = cr.message or extra.get("message") or ""
                    rows.append(f"| {rule} | `{st}` | {chk} | {msg} |")
                else:
                    rows.append(f"| {rule} | `{st}` | {chk} |")

            result_lines.append("\n**Check Results**\n\n" + "\n".join(rows))

        # Show error-level log messages beneath the table
        error_logs = [
            lg for lg in (result.logs if result else [])
            if (lg.level or "").lower() in ("error", "warn")
        ]
        if error_logs:
            log_lines = ["**Logs**", "```"]
            for lg in error_logs:
                ts  = f"[{lg.timestamp}] " if lg.timestamp else ""
                lvl = (lg.level or "").upper()
                log_lines.append(f"{ts}{lvl}: {lg.message or ''}")
            log_lines.append("```")
            result_lines.append("\n" + "\n".join(log_lines))

        result_lines.append("")

    md = "## 🧪 Data Contract Test Run\n\n" + "\n".join(result_lines) + "\n"
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as out:
            out.write("body<<EOF\n")
            out.write(md + "\n")
            out.write("EOF\n")
            out.write(f"overall={overall}\n")

    # Always exit 0 here — the composite action's "Fail if test failed" step
    # reads `overall` from GITHUB_OUTPUT and calls `exit 1` if needed.
    # Returning non-zero here would skip the "Post PR comment (success)" step.
    return 0


if __name__ == "__main__":
    sys.exit(main())
