---
task_ref: TASK-148
plan_ref: PLAN-012
review_type: quality
verdict: PASS
reviewed_at: 2026-05-11T14:28:00Z
reviewed_by: SMA
---

# TASK-148 Quality Review: ember-api

## Verdict

PASS

## Findings

### Resolved: API pass-through now includes canonical data-layer field names

`ember-data` exposes canonical TASK-148 fields including:

- `earliest_patent_expiry_derivation_method`
- `earliest_patent_expiry_verified_date`
- `data_exclusivity_expiry`
- `data_exclusivity_regime`
- `framework_regulatory_context`

The API pass-through list includes shorter aliases such as `patent_expiry_derivation_method` and `data_exclusivity`, but omits several canonical data-layer field names. This risks dropping fields produced by `ember-data` before they reach the phase 5 dashboard/API consumers.

Revision completed:

- Canonical data-layer field names were added to `_PATENT_REGULATORY_FIELDS`.
- Tests now prove `/results` and `/runs` preserve the canonical fields listed above.
- Existing alias fields remain additive compatibility fields.

## Verification Evidence

- `.venv/bin/pytest -q tests/test_results_endpoint.py` passed: 17 tests, 1 unrelated dependency warning.
- `.venv/bin/ruff check src/ember_api/routes/results.py tests/test_results_endpoint.py` passed.
- Revision dispatch `0001N03SNWZQHW8T` completed successfully.
- SMA local validation after revision: `.venv/bin/pytest -q tests/test_results_endpoint.py` passed: 19 tests, 1 unrelated dependency warning.
- SMA local validation after revision: `.venv/bin/ruff check src/ember_api/routes/results.py tests/test_results_endpoint.py` passed.
