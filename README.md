# DQProject — Data Contract CI/CD

GitHub Actions pipeline that validates, tests and publishes data contracts to an IBM watsonx / CPD project using the [`data-intelligence-sdk`](https://pypi.org/project/data-intelligence-sdk/).

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
│   │   ├── data-contract.yml     # The pipeline (PR flow + merge flow)
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
2. **Check the trigger branch.** The merge flow in [`data-contract.yml`](.github/workflows/data-contract.yml) runs on pushes to `main`. Change `branches: [main]` if your default branch differs.
3. **Add the secrets** listed below under **Settings → Secrets and variables → Actions → New repository secret**.
4. **Allow workflow permissions.** Under **Settings → Actions → General → Workflow permissions**, make sure workflows can run. The workflow itself requests the permissions it needs (see below).
5. **Open a pull request** that adds or changes a file under `contracts/`. The pipeline runs and posts a comment after each stage.

---

## Secrets

| Secret | Required | Where to set it | Description |
|---|---|---|---|
| `PLATFORM_URL` | Yes | Repository secret | Base URL of the CPD / watsonx instance, without a trailing slash (e.g. `https://api.dai.dev.cloud.ibm.com`). |
| `PLATFORM_ENV` | No | Repository secret | Deployment type: `ibm_cloud` (default), `aws_cloud`, `gov_cloud` or `on_prem`. |
| `PLATFORM_API_KEY` | Yes for cloud; `on_prem` needs it or username/password | Repository secret | API key. The scripts exchange it for a bearer token through the SDK's `wxdi.common.auth` module. The identity behind the credentials needs access to the target project, with permission to create, replace, test and delete data contracts. |
| `PLATFORM_USERNAME` | `on_prem` only | Repository secret | Username for Cloud Pak for Data. |
| `PLATFORM_PASSWORD` | `on_prem`, if no API key | Repository secret | Password for Cloud Pak for Data. |
| `PLATFORM_ACCOUNT_ID` | `aws_cloud` only | Repository secret | Account ID. |
| `IAM_TOKEN_URL` | No (cloud only) | Repository secret | IAM token endpoint that matches the environment of `PLATFORM_API_KEY`, e.g. `https://iam.cloud.ibm.com/identity/token` (production IBM Cloud) or `https://iam.test.cloud.ibm.com/identity/token` (IBM Cloud test). If the secret is not defined, the test endpoint is used. |
| `GITHUB_TOKEN` | Automatic | Provided by GitHub | Used to post PR comments, upload/download test-result artifacts and look up the merged PR. Do **not** create it manually. |

How they are used:

| Secret | Consumed by | Passed as |
|---|---|---|
| `PLATFORM_URL` | All five actions | `url` input → `PLATFORM_URL` env var |
| `PLATFORM_ENV` | All five actions | `environment` input → `PLATFORM_ENV` env var |
| `PLATFORM_API_KEY` | All five actions | `api-key` input → `PLATFORM_API_KEY` env var |
| `PLATFORM_USERNAME` | All five actions | `username` input → `PLATFORM_USERNAME` env var |
| `PLATFORM_PASSWORD` | All five actions | `password` input → `PLATFORM_PASSWORD` env var |
| `PLATFORM_ACCOUNT_ID` | All five actions | `account-id` input → `PLATFORM_ACCOUNT_ID` env var |
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
- **TLS certificates are not verified for platform calls.** The SDK's `DataContractsProvider` makes its API calls with `verify=False`. For `on_prem` and `gov_cloud`, token requests are also unverified because `AuthConfig` defaults `disable_ssl_verification` to `True` (the `ibm_cloud` and `aws_cloud` token requests are verified). Do not run this pipeline across an untrusted network; use a private network path (see [On-prem network access](#on-prem-network-access)).
- Store `PLATFORM_PASSWORD` and `PLATFORM_API_KEY` as Actions secrets, and prefer a dedicated service account over a personal on-prem user.

---

## On-prem network access

The bundled workflow uses `runs-on: ubuntu-latest`, a GitHub-hosted runner on the public internet. An on-prem Cloud Pak for Data instance is usually on a private network, so those runners cannot reach `PLATFORM_URL` and every job fails at the token step. Choose one of the following before setting `PLATFORM_ENV=on_prem`:

| Option | How | Notes |
|---|---|---|
| **Self-hosted runner** (recommended) | Install a [self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) on a machine that can reach the instance, then change each job to `runs-on: [self-hosted, linux]` (or your runner labels). | No inbound firewall rules needed; the runner connects out to GitHub. The runner needs `python3`, `pip` and outbound access to PyPI (or an internal mirror) and to GitHub. |
| **VPN / tunnel from a hosted runner** | Add a step before the first action in each job that connects to your VPN (for example WireGuard or OpenVPN), and disconnect afterwards. | Every job needs the step, because jobs run on separate machines. Keep the VPN credentials in Actions secrets and use a key restricted to the instance's subnet. |
| **Expose the instance and allow-list GitHub IPs** | Publish the endpoint and allow GitHub's runner IP ranges. | Not recommended: the ranges are large and change, and it puts the platform on the public internet. |

Security considerations:

- A self-hosted runner executes workflow code on your network. Do not attach one to a public repository or to a repository that accepts fork PRs, because a PR can run arbitrary code on it. Use a private repository, restrict who can trigger the workflow, and run the runner as an unprivileged user (ideally ephemeral or in a container).
- Give the runner or VPN identity network access only to the instance's API host and port.
- The PR flow still creates and deletes temporary contracts, so point it at a non-production project.
- Certificate verification is not currently configurable from the workflow inputs (see the TLS note under Security notes), so rely on the private network path rather than on TLS verification.

---

## Local debugging

The scripts can be run outside GitHub Actions:

```bash
pip install "data-intelligence-sdk==2.3.0"

export PLATFORM_URL="https://api.dai.dev.cloud.ibm.com"
export PLATFORM_API_KEY="your-iam-api-key"
export IAM_TOKEN_URL="https://iam.cloud.ibm.com/identity/token"   # optional

# For on-prem instead of the API key above:
#   export PLATFORM_ENV="on_prem" PLATFORM_USERNAME="admin" PLATFORM_PASSWORD="..."

python .github/scripts/validate_contract.py contracts/dc.yaml
```

See [`.github/scripts/README.md`](.github/scripts/README.md) for the arguments of each script.

---

## Known configuration to review when reusing

- **SDK source and version.** Every `action.yml` installs `data-intelligence-sdk==2.3.0` from PyPI. See [`.github/actions/README.md`](.github/actions/README.md) for how to change it.
- **IAM endpoint.** For cloud environments, set the optional `IAM_TOKEN_URL` secret to the token endpoint of the environment your API key belongs to. No code change is needed. If it is not set, `ibm_cloud` uses `https://iam.test.cloud.ibm.com/identity/token`. It is ignored for `on_prem`.

---

## Documentation index

| Topic | Location |
|---|---|
| Pipeline jobs, conditions, permissions | [`.github/workflows/README.md`](.github/workflows/README.md) |
| Composite actions and their inputs/outputs | [`.github/actions/README.md`](.github/actions/README.md) |
| Python scripts and local usage | [`.github/scripts/README.md`](.github/scripts/README.md) |
