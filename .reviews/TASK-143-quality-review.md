---
task_ref: TASK-143
plan_ref: PLAN-012
review_type: quality
verdict: PASS
reviewed_at: 2026-05-11T14:06:07Z
reviewed_by: SMA
---

# TASK-143 Quality Review: ember-api

## Verdict

PASS

## Findings

### Resolved: API tests encode `concrete_labels` with the data-layer shape

The data-layer model defines `concrete_labels` as a mapping (`dict[str, str]`). The new API test uses a list value:

```python
"concrete_labels": ["PD-1"]
```

Impact: the API may pass tests while drifting from the provider model shape expected by `ember-data` and downstream UI consumers.

Revision completed:

- API tests now use the mapping shape `{"target": "PD-1"}`.
- Route logic remains a serializer pass-through for additive explanation metadata.

### Resolved With SMA Local Validation: child environment could not resolve dependencies

The child could not complete `pytest` or `ruff` because dependency resolution was blocked. SMA reran validation from the existing local `.venv`, avoiding package-index resolution.

Validation result:

- `.venv/bin/pytest -q tests/test_results_endpoint.py` passed: 14 tests, 1 unrelated dependency warning.
- `.venv/bin/ruff check src/ember_api/routes/results.py tests/test_results_endpoint.py` passed.

## Verification Evidence

- Child attempted:
  - `rtk uv run pytest -q tests/test_results_endpoint.py`
  - `rtk uv run ruff check src/ember_api/routes/results.py tests/test_results_endpoint.py`
- Child reported dependency resolution/runtime blockers prevented test completion.
- Escalated `rtk env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest -q tests/test_results_endpoint.py` failed with package-index `401 Unauthorized`.
- SMA local `.venv` validation passed as recorded above.
