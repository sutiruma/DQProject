# Data Contract CI/CD Pipeline

A GitHub Actions pipeline for managing data contracts in IBM watsonx Data Intelligence (CPD) projects. Contracts stored in this repository are automatically validated, tested against live data, and upserted to the platform as part of every pull request and merge to `main`.

---

## Documentation

| Page | Location | Description |
|---|---|---|
| [Contract Format](.github/../contracts/README.md) | `contracts/` | File structure, required fields, quality rule types, and assertion syntax |
| [CI/CD Workflow](.github/workflows/README.md) | `.github/workflows/` | How the PR flow and merge flow work, job conditions, and required secrets |
| [Composite Actions](.github/actions/README.md) | `.github/actions/` | Inputs, outputs, and behaviour for all four GitHub Actions |
| [Python Scripts](.github/scripts/README.md) | `.github/scripts/` | Script reference with CLI usage, local debugging, and exit codes |

---

## Quick Start

1. **Add a contract** — create a `.yaml` or `.json` file in `contracts/`. See [Contract Format](contracts/README.md) for the required structure, including the mandatory `customProperties.projectId` field.

2. **Set repository secrets** — add `PLATFORM_URL` and `PLATFORM_API_KEY` in **Settings → Secrets and variables → Actions**.

3. **Open a pull request** — the pipeline automatically validates, creates an ephemeral test copy, runs data quality checks, and cleans up.

4. **Merge** — the contract is upserted to the production project under its canonical name (the filename without extension).

---

## Repository Structure

```
.
├── contracts/
│   ├── README.md                            ← Contract format guide
│   ├── dc.yaml                              ← Example YAML contract
│   ├── dc_5.json                            ← Example JSON contract
│   └── ...
└── .github/
    ├── workflows/
    │   ├── README.md                        ← Workflow documentation
    │   └── validate-data-contract.yml       ← Main CI/CD workflow
    ├── actions/
    │   ├── README.md                        ← Composite actions documentation
    │   ├── data-contract-validate/
    │   ├── data-contract-create/
    │   ├── data-contract-test/
    │   └── data-contract-delete/
    └── scripts/
        ├── README.md                        ← Python scripts documentation
        ├── contract_utils.py
        ├── validate_contract.py
        ├── create_contract.py
        ├── test_contract.py
        └── delete_contract.py
```
