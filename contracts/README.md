# Contract Format

Data contracts may be written in **YAML** (`.yaml` / `.yml`) or **JSON** (`.json`). Both formats are fully supported by all pipeline scripts.

The filename (without extension) becomes the contract's canonical name on the platform.

---

## Required: `customProperties.projectId`

Every contract **must** include a top-level `customProperties` array containing a `projectId` entry. The pipeline uses this value to determine which CPD/watsonx project to target — it is not read from any environment variable or workflow input.

```yaml
customProperties:
  - property: projectId
    value: "your-cpd-project-uuid-here"
```

Missing `projectId` causes all pipeline scripts to exit with an error immediately.

---

## Minimal Example (YAML)

```yaml
version: 1.0.0
apiVersion: v3.1.0
kind: DataContract
id: my_contract_001
name: my_contract
status: active
domain: "Finance: Reporting"
tenant: finance_team

servers:
  - server: my-db
    type: db2
    host: db.example.com
    port: 50000
    database: MYDB
    schema: MYSCHEMA

schema:
  - name: MY_TABLE
    physicalName: MYSCHEMA/MY_TABLE
    physicalType: table
    logicalType: object
    quality:
      - name: row_count_check
        type: sql
        query: "SELECT * FROM MYSCHEMA.MY_TABLE;"
        mustBe: 1000
        dimension: completeness
    properties:
      - name: ID
        physicalName: ID
        logicalType: string
        required: true
        unique: true

customProperties:
  - property: projectId
    value: "your-cpd-project-uuid-here"
  - property: connectionIds
    value:
      - "your-connection-uuid-here"
```

---

## Top-Level Fields

| Field | Type | Description |
|---|---|---|
| `version` | string | Contract schema version (e.g. `1.0.0`) |
| `apiVersion` | string | API version (e.g. `v3.1.0`) |
| `kind` | string | Always `DataContract` |
| `id` | string | Unique identifier for the contract |
| `name` | string | Human-readable name |
| `status` | string | `active` or `draft` |
| `domain` | string | Business domain |
| `tenant` | string | Owning team or department |
| `servers` | array | One or more database server definitions |
| `dataProduct` | string | (Optional) Associated data product name |
| `schema` | array | Table/view definitions with quality rules |
| `customProperties` | array | Must include `projectId`; optionally `connectionIds` |

---

## Quality Rules

Quality rules are defined under `quality` at both the **schema** (table) level and the **property** (column) level.

### Rule types

| `type` | Description |
|---|---|
| `sql` | A custom SQL query. The result row count is evaluated against the assertion. |
| `library` | A built-in metric — see [Library Metrics](#library-metrics) below. |

### Assertion fields

| Field | Meaning |
|---|---|
| `mustBe` | Result must equal this value exactly |
| `mustBeLessThan` | Result must be strictly less than this value |
| `mustBeGreaterThan` | Result must be strictly greater than this value |
| `mustBeBetween` | Result must fall within `[min, max]` (inclusive), specified as a two-element array |

The `unit` field (optional) controls what the assertion is evaluated against:

| `unit` | Meaning |
|---|---|
| `rows` | (default) compare the assertion against an absolute row count |
| `percent` | compare the assertion against a percentage of total rows |

### SQL rule example

```yaml
quality:
  - name: Invalid ZIP format
    type: sql
    query: >-
      SELECT ZIP FROM MY_TABLE
      WHERE ZIP IS NOT NULL AND NOT REGEXP_LIKE(TRIM(ZIP), '^[0-9]{5}$');
    mustBeLessThan: 10
    dimension: conformity
```

---

## Library Metrics

Library metrics are reusable, pre-built checks referenced with `type: library` and a `metric` name. They accept optional `arguments` for customisation.

### Metric reference

| Metric | Level | Description | Arguments |
|---|---|---|---|
| `nullValues` | Property | Counts null values in a column | None |
| `missingValues` | Property | Counts values considered missing (empty strings, N/A, etc.) | `missingValues`: array of values to treat as missing |
| `invalidValues` | Property | Counts values that don't match valid criteria | `validValues`: array of allowed values **or** `pattern`: regex string |
| `duplicateValues` | Property | Counts duplicate values in a column | None |
| `duplicateValues` | Schema | Counts duplicate rows across multiple columns (compound key check) | `properties`: array of property names |
| `rowCount` | Schema | Counts total number of rows in a table | None |

---

### `nullValues`

Counts null values in a column.

```yaml
# Exact count — must be zero
properties:
  - name: customer_id
    quality:
      - id: customer_id_no_nulls
        type: library
        metric: nullValues
        mustBe: 0
        description: "There must be no null values in the column."
```

```yaml
# Percent threshold
properties:
  - name: order_status
    quality:
      - id: order_status_null_percent
        type: library
        metric: nullValues
        mustBeLessThan: 1
        unit: percent
        description: "There must be less than 1% null values in the column."
```

---

### `missingValues`

Counts values that match a user-defined list of "missing" representations (empty strings, sentinel values, etc.).

```yaml
properties:
  - name: email_address
    quality:
      - id: email_missing_values
        type: library
        metric: missingValues
        arguments:
          missingValues: [null, '', 'N/A', 'n/a']
        mustBeLessThan: 100
        unit: rows
```

---

### `invalidValues`

Counts values that fall outside a defined set of valid values or don't match a regex pattern.

```yaml
# Valid values list
properties:
  - name: line_item_unit
    quality:
      - id: line_item_unit_valid_values
        type: library
        metric: invalidValues
        arguments:
          validValues: ['pounds', 'kg']
        mustBeLessThan: 5
        unit: rows
```

```yaml
# Regex pattern
properties:
  - name: iban
    quality:
      - id: iban_pattern_check
        type: library
        metric: invalidValues
        mustBe: 0
        description: "The value must be a valid IBAN."
        arguments:
          pattern: '^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}([A-Z0-9]?){0,16}$'
```

---

### `duplicateValues` (property level)

Counts duplicate values in a single column.

```yaml
# Absolute row count
properties:
  - name: email_address
    quality:
      - id: email_duplicate_values
        type: library
        metric: duplicateValues
        mustBeLessThan: 10
        unit: rows
        description: "There must be fewer than 10 duplicate values in the column."
```

```yaml
# Percent threshold
properties:
  - name: phone_number
    quality:
      - id: phone_duplicate_percent
        type: library
        metric: duplicateValues
        mustBeLessThan: 1
        unit: percent
```

---

### `rowCount` (schema level)

Counts the total number of rows in a table and compares it against an assertion.

```yaml
schema:
  - name: orders
    quality:
      - id: orders_row_count
        type: library
        metric: rowCount
        mustBeBetween: [100, 120]
```

---

### `duplicateValues` (schema level)

Checks for duplicate rows based on a combination of columns — useful for validating compound keys.

```yaml
schema:
  - name: orders
    quality:
      - id: orders_unique_tenant_order
        type: library
        metric: duplicateValues
        mustBe: 0
        description: "The combination of tenant_id and order_id must be unique."
        arguments:
          properties:
            - tenant_id
            - order_id
```
