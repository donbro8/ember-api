# ember-api

## What this package does

Thin FastAPI HTTP layer for the Ember Bio platform. Handles request validation,
auth middleware, CORS, and SSE streaming of agent responses. All domain logic
comes from imported packages (ember-agents, ember-data, ember-shared).

## Key modules

- `main.py` — FastAPI app entry point
- `routes/` — HTTP route handlers (chat, search, reports, health)
- `middleware/` — Auth middleware (Phase 2)
- `deps.py` — FastAPI dependency injection

## How to run tests

```bash
uv sync --extra dev
uv run pytest --cov
```

## How to run the server

```bash
uv run uvicorn ember_api.main:app --reload
```

## Conventions

- Stateless — session state lives in a database, not API memory
- SSE streaming for agent responses
- Depends on ember-shared, ember-data, and ember-agents
- Dockerfile is a placeholder until EB4
- Lint with ruff: `uv run ruff check src/ tests/`

## Agent Routing (3 agents)

| Role | Agent File | Tier Class | When to Use |
|---|---|---|---|
| module-architect | `.claude/agents/module-architect.md` | architect | API design, route architecture, middleware patterns |
| implementer | `.claude/agents/implementer.md` | implementer | Route implementation, middleware coding, tests |
| reviewer | `.claude/agents/reviewer.md` | reviewer | API review, REST contract compliance, security checks |

Selection rule: SMA dispatches the appropriate agent based on task type. Module-architect for design tasks, implementer for coding tasks, reviewer for review tasks.
