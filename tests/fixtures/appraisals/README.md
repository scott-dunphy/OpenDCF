# Public appraisal fixtures

This directory holds appraisal evidence used to test OpenDCF document classification, extraction,
reconstruction, and valuation parity. The current source set is made entirely from public SEC exhibits
that explicitly identify the published DCF software as the cash-flow software.

## Layout

- `source/` — immutable source documents downloaded from the SEC.
- `manifests/` — provenance, checksums, software versions, test routing, and expected coverage.
- `expected/` — reviewed extraction JSON and portable OpenDCF packages. These are added only after
  analyst review; model-generated output must never become its own expected result automatically.
- `synthetic/` — generated, redistribution-safe edge cases for leases, amendments, missing documents,
  stale data, and conflicting facts.

## Rules

1. Never edit a file in `source/`. Download a new copy and update its SHA-256 if the SEC changes it.
2. Every source must have a catalog entry with a primary-source URL and explicit evidence of the cash-flow software used.
3. Confidential client appraisals must not be committed. Put them in a separately configured ignored
   directory and use the same manifest schema without names or sensitive facts.
4. Expected extraction data requires human review and page-level provenance.
5. Large future fixtures should use Git LFS. The current public set is about 16 MB.

Run fixture integrity checks with:

```shell
.venv/bin/python -m pytest -q tests/integration/test_appraisal_fixture_catalog.py
```

The existing valuation-parity tests remain in `tests/integration/test_published_appraisal_*.py`.

