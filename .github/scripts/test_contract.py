#!/usr/bin/env python3
"""
Trigger and poll data contract test runs in a CPD/watsonx project.

Usage:
    python test_contract.py <entry1> [<entry2> ...]

Each entry must be a <project_id>:<contract_id> pair emitted by create_contract.py.
Project ID is embedded in each entry from customProperties.projectId in the contract file.

Environment variables (required):
    URL     - Base URL of the instance (e.g. https://api.dai.dev.cloud.ibm.com)
    API_KEY - IBM Cloud IAM API key; a fresh bearer token is obtained at runtime

Exit codes:
    0 - all contract tests completed (pass/fail reported via GITHUB_OUTPUT)
    1 - unexpected error

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

MAX_POLLS        = 30
POLL_INTERVAL    = 10
TRIGGER_RETRIES  = 3      # retry the POST trigger on transient 5xx errors
TRIGGER_BACKOFF  = 15     # seconds between retries (doubles each attempt)


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
        print("No contract IDs provided — nothing to test.")
        return 0

    cpd_url = os.environ.get("URL", "").rstrip("/")
    api_key = os.environ.get("API_KEY", "")

    bearer   = get_bearer_token(api_key)
    config   = ProviderConfig(url=cpd_url, auth_token=bearer)
    provider = DataContractsProvider(config)

    result_lines = []
    overall      = 0

    for entry in entries:
        # Entry must be "project_id:contract_id" as emitted by create_contract.py
        if ":" not in entry:
            print(f"ERROR: entry '{entry}' is not in project_id:contract_id format.",
                  file=sys.stderr)
            overall = 1
            result_lines.append(f"### ❌ `{entry}` — invalid format (expected project_id:contract_id)")
            result_lines.append("")
            continue

        project_id, cid = entry.split(":", 1)

        print(f"Triggering test for contract id={cid} (project={project_id}) ...")
        test_resp = None
        last_exc  = None
        for attempt in range(1, TRIGGER_RETRIES + 1):
            try:
                test_resp = provider.test_project_data_contract(
                    project_id, cid,
                    DataContractTestRequest(retain_dq_objects=False),
                )
                break  # success — stop retrying
            except ValueError as exc:
                last_exc = exc
                # Only retry on transient server errors (5xx in the message)
                is_transient = any(
                    code in str(exc) for code in ("500", "502", "503", "504")
                )
                if is_transient and attempt < TRIGGER_RETRIES:
                    wait = TRIGGER_BACKOFF * (2 ** (attempt - 1))
                    print(f"  attempt {attempt}/{TRIGGER_RETRIES} failed (transient): {exc}",
                          file=sys.stderr)
                    print(f"  retrying in {wait}s ...", file=sys.stderr)
                    time.sleep(wait)
                else:
                    break  # non-transient error or out of retries

        if test_resp is None:
            print(f"ERROR: test trigger failed for {cid}: {last_exc}", file=sys.stderr)
            overall = 1
            result_lines.append(f"### ❌ `{cid}` — test trigger failed")
            result_lines.append(f"> Error: `{last_exc}`")
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
            if (result.status or "").lower() in ("completed", "failed"):
                break
            time.sleep(POLL_INTERVAL)

        status = result.status if result else "unknown"
        start  = result.start  if result else "-"
        end    = result.end    if result else "-"
        run_by = result.run_by if result else "-"

        if status.lower() == "completed":
            result_lines.append(f"### ✅ `{cid}` — test completed")
        else:
            overall = 1
            result_lines.append(f"### ❌ `{cid}` — test **{status}**")

        result_lines.append(
            f"> Run ID: `{run_id}` | Started: {start} | Ended: {end} | Run by: {run_by}"
        )

        if result and result.check_results:
            # All meaningful fields live in model_extra — the API response uses
            # data_quality_rule.name/id, dataset.name/field, and per-check logs[].message
            any_error = any(
                (cr.status or "").lower() == "error"
                for cr in result.check_results
            )
            if any_error:
                rows = ["| Rule ID | Dataset | Field | Status | Tested | Passed | Failed | Message |",
                        "|---|---|---|---|---|---|---|---|"]
            else:
                rows = ["| Rule ID | Dataset | Field | Status | Tested | Passed | Failed |",
                        "|---|---|---|---|---|---|---|"]

            for cr in result.check_results:
                extra = cr.model_extra or {}

                # Rule: use data_quality_rule.id, fall back to .name
                dq_rule  = extra.get("data_quality_rule") or {}
                rule     = dq_rule.get("id") or dq_rule.get("name") or cr.check_name or "-"

                # Dataset / field
                dataset_obj = extra.get("dataset") or {}
                dataset     = dataset_obj.get("name") or "-"
                field       = dataset_obj.get("field") or "-"

                st      = cr.status or extra.get("status") or "-"
                tested  = extra.get("tested_record_count", "-")
                passed  = extra.get("passed_record_count", "-")
                failed  = extra.get("failed_record_count", "-")

                if any_error:
                    # Per-check logs list — grab the first message
                    check_logs = extra.get("logs") or []
                    msg = check_logs[0].get("message") if check_logs else (cr.message or "")
                    rows.append(f"| {rule} | {dataset} | {field} | `{st}` | {tested} | {passed} | {failed} | {msg} |")
                else:
                    rows.append(f"| {rule} | {dataset} | {field} | `{st}` | {tested} | {passed} | {failed} |")

            result_lines.append("\n**Check Results**\n\n" + "\n".join(rows))

        # Always show schema validation issues as informational — does not affect overall pass/fail
        schema_results = (result.model_extra or {}).get("schema_validation_results") if result else None
        if schema_results:
            sv_rows = ["| Table | Column | Issue | Expected | Actual |", "|---|---|---|---|---|"]
            for table_name, issues in schema_results.items():
                for issue in (issues or []):
                    col   = issue.get("column_name") or "-"
                    msg   = issue.get("message") or "-"
                    exp   = issue.get("expected_value") or "-"
                    act   = issue.get("actual_value") or "-"
                    sv_rows.append(f"| `{table_name}` | `{col}` | {msg} | `{exp}` | `{act}` |")
            result_lines.append("\n**Schema Validation Issues**\n\n" + "\n".join(sv_rows))

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
