# Contract: In-process services between the answer API (003) and work orders (005)

Owner: orchestrator. Types: `src/copilot_contracts/services.py`.

The API (003) owns everything HTTP: sessions, routing, request parsing, mapping errors to status
codes, static files. Work orders (005) own the rules and storage for drafts **and** the audit log.
The API never writes the `app` schema directly; it calls these interfaces.

| Interface | Implemented by | Used by |
|---|---|---|
| `WorkOrders` | 005, package `copilot_workorders` | 003 for every `/api/work-orders` endpoint |
| `AuditLog` | 005, package `copilot_workorders` | 003 for answer, source view and access-denied events; 005 itself for draft events |
| `AnswerEngine` (answer.md) | 002, `copilot_answer.build_engine()` | 003 for `/api/ask` |

## Errors

Methods raise subclasses of `ServiceError`; each carries the `code` and `http_status` from
http-api.md, section "Errors". The API turns them into `{"error": code, "detail": str(e)}`.
`copilot_answer.ProviderUnavailable` maps to `503 model_unavailable`;
`copilot_answer.ConfigurationError` stops the server at start.

## Storage

Postgres database `copilot`, schema `app`, created by 005's migration
(`src/copilot_workorders/db/app_schema.sql`, applied idempotently by
`copilot_workorders.migrate(conn)`). The API calls `migrate` at start. Tables are 005's choice; the
audit table is append-only (no UPDATE or DELETE grants are needed, and code never issues them).

## Construction

```python
from copilot_workorders import build_services     # 005
work_orders, audit = build_services(database_url)  # -> (WorkOrders, AuditLog)
from copilot_answer import build_engine            # 002
engine = build_engine()
```

Until 005 exists, the API uses in-memory fakes of both interfaces in its tests; until 003 exists,
005 tests its services directly.
