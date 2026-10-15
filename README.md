# DQProject — Data Contract CI/CD

GitHub Actions pipeline that validates, tests and publishes data contracts to an IBM watsonx / CPD project using the [`data-intelligence-sdk`](https://test.pypi.org/project/data-intelligence-sdk/).

Data contracts are stored as YAML/JSON files under `contracts/`. Every pull request that touches them is validated and tested against the platform. When the PR is merged, the real contracts are upserted and the PR's test results are attached to them.

```
PR opened / updated            PR merged to main
        │                              │
  validate ──► create temp ──► test ──► delete temp        upsert real contracts ──► save PR test results
  (PR comment after each step)                             (visible in Actions run log)
```

For the full job-by-job description see [`.github/workflows/README.md`](.github/workflows/README.md).

---

## Repository structure

This is the layout another repository needs in order to reuse the pipeline. Copy the `.github/` folder as-is and add your own `contracts/` folder.

```
your-repo/
├── .github/
│   ├── workflows/
│   │   ├── validate-data-contract.yml     # The pipeline (PR flow + merge flow)
│   │   └── README.md
│   ├── actions/                           # Reusable composite actions
│   │   ├── README.md
│   │   ├── data-contract-validate/        # action.yml + README.md
│   │   ├── data-contract-create/          # action.yml + README.md
│   │   ├── data-contract-test/            # action.yml + README.md
│   │   ├── data-contract-delete/          # action.yml + README.md
│   │   └── data-contract-save-results/    # action.yml + README.md
│   └── scripts/                           # Python logic called by the actions
│       ├── README.md
│       ├── contract_utils.py
│       ├── validate_contract.py
│       ├── create_contract.py
│       ├── test_contract.py
│       ├── delete_contract.py
│       └── save_test_results.py
├── contracts/                             # YOUR data contracts (ODCS .yaml / .yml / .json)
│   ├── my_contract.yaml
│   └── another_contract.json
└── README.md
```

Notes:

- The workflow uses local actions (`uses: ./.github/actions/...`), so `.github/actions/` and `.github/scripts/` **must be present in the same repository** as the workflow.
- Only files under `contracts/` trigger the pipeline. Contract file names (without extension) become the contract names on the platform.
- Each contract file must declare its target project in `customProperties`:

  ```yaml
  customProperties:
    - property: projectId
      value: <your-project-id>
  ```

  (JSON equivalent: `{"property": "projectId", "value": "<your-project-id>"}`). The scripts read the project ID only from this property. See [`contracts/dc_rule_name_test.yaml`](contracts/dc_rule_name_test.yaml) for an example.

---

## Setup in your own repository

1. **Copy** `.github/` (workflows, actions, scripts) into your repository and create a `contracts/` folder with your contract files.
2. **Check the trigger branch.** The merge flow in [`validate-data-contract.yml`](.github/workflows/validate-data-contract.yml) runs on pushes to `main`. Change `branches: [main]` if your default branch differs.
3. **Add the secrets** listed below under **Settings → Secrets and variables → Actions → New repository secret**.
4. **Allow workflow permissions.** Under **Settings → Actions → General → Workflow permissions**, make sure workflows can run. The workflow itself requests the permissions it needs (see below).
5. **Open a pull request** that adds or changes a file under `contracts/`. The pipeline runs and posts a comment after each stage.

---

## Secrets

| Secret | Required | Where to set it | Description |
|---|---|---|---|
| `PLATFORM_URL` | Yes | Repository secret | Base URL of the CPD / watsonx instance, without a trailing slash (e.g. `https://api.dai.dev.cloud.ibm.com`). |
| `PLATFORM_API_KEY` | Yes | Repository secret | IBM Cloud IAM API key. The scripts exchange it for a bearer token. The identity behind the key needs access to the target project, with permission to create, replace, test and delete data contracts. |
| `IAM_TOKEN_URL` | No | Repository secret | IAM token endpoint that matches the environment of `PLATFORM_API_KEY`, e.g. `https://iam.cloud.ibm.com/identity/token` (production IBM Cloud) or `https://iam.test.cloud.ibm.com/identity/token` (IBM Cloud test). If the secret is not defined, the test endpoint is used. |
| `GITHUB_TOKEN` | Automatic | Provided by GitHub | Used to post PR comments, upload/download test-result artifacts and look up the merged PR. Do **not** create it manually. |

How they are used:

| Secret | Consumed by | Passed as |
|---|---|---|
| `PLATFORM_URL` | All five actions | `url` input → `PLATFORM_URL` env var |
| `PLATFORM_API_KEY` | All five actions | `api-key` input → `PLATFORM_API_KEY` env var |
| `IAM_TOKEN_URL` | All five actions | `iam-url` input → `IAM_TOKEN_URL` env var |
| `GITHUB_TOKEN` | All five actions | `github-token` input → `GH_TOKEN` env var for the `gh` CLI |

### Workflow permissions (`GITHUB_TOKEN` scopes)

```yaml
permissions:
  pull-requests: write   # post PR comments
  contents: read         # checkout the repository
  actions: read          # download the PR's test-result artifact on merge
```

### Security notes

- Never commit the API key or URL; keep them as Actions secrets only.
- **Pull requests from forks do not receive repository secrets**, so the pipeline cannot reach the platform for fork PRs. For a public repository, have contributors open PRs from branches in the same repository, or review fork PRs and re-run them from a branch you control.
- Use a dedicated service-ID API key with the minimum project access required.
- The PR flow creates and deletes temporary contracts (`<name>_PR_<number>`) in the target project, so point it at a non-production project if possible.

---

## Local debugging

The scripts can be run outside GitHub Actions:

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "data-intelligence-sdk==2.3.0"

export PLATFORM_URL="https://api.dai.dev.cloud.ibm.com"
export PLATFORM_API_KEY="your-iam-api-key"
export IAM_TOKEN_URL="https://iam.cloud.ibm.com/identity/token"   # optional

python .github/scripts/validate_contract.py contracts/dc.yaml
```

See [`.github/scripts/README.md`](.github/scripts/README.md) for the arguments of each script.

---

## Known configuration to review when reusing

- **SDK source and version.** Every `action.yml` installs `data-intelligence-sdk==2.3.0` from TestPyPI. See [`.github/actions/README.md`](.github/actions/README.md) for how to change it.
- **IAM endpoint.** Set the optional `IAM_TOKEN_URL` secret to the token endpoint of the environment your API key belongs to. No code change is needed. If it is not set, `https://iam.test.cloud.ibm.com/identity/token` is used.

---

## Documentation index

| Topic | Location |
|---|---|
| Pipeline jobs, conditions, permissions | [`.github/workflows/README.md`](.github/workflows/README.md) |
| Composite actions and their inputs/outputs | [`.github/actions/README.md`](.github/actions/README.md) |
| Python scripts and local usage | [`.github/scripts/README.md`](.github/scripts/README.md) |
