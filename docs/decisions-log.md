# Gateway decisions

## Confirmed integration details

| Item | Decision |
|---|---|
| Base URL | `https://brane.ai-z.io/api/v1` |
| Authentication | `Authorization: Bearer <BRANE_API_KEY>`; load only from environment or local `.env` |
| Model listing and health check | `GET /models` relative to the base URL |
| Cloud completion | `POST /chat/completions` relative to the base URL; model from `BRANE_MODEL` |
| Local model | Model from `BRANE_LOCAL_MODEL`; local path currently defaults to `/local/chat/completions` pending AI-Z confirmation |
| Policy setup | README does not describe the policy configuration interface, schema, or `brane_policy_ref` mapping; ask AI-Z |
| Decision capture | Retain response status, decision-related headers, policy/verdict fields and full raw response in `Decision.brane_verdict` |

The gateway does not retry against another host. A BRANE block raises `BraneBlocked`; connection failures, timeouts and 5xx responses raise `BraneUnavailable`.

## Perimeter assumption

20 Nov 2026 — AI-Z mentor: “BRANE is treated as inside the bank's trusted perimeter; the external model behind it is the outside recipient.”

## Remaining unknowns

| Question | Status |
|---|---|
| Exact BRANE local completion path | Assumed `/local/chat/completions`; ask AI-Z to confirm |
| Policy configuration interface/schema and mapping for P1–P15 | Not covered by README; ask AI-Z |
| Exact verdict/policy response fields and protected-text format | Not covered by README; adapter retains full raw response and decision headers |
| Live evidence and enforcement-test protocol | Not covered by README; requires credentials and service access |

The earlier gateway README documented assumed `/v1/chat/completions`, `/v1/local/chat/completions` and `/health` routes. Those differ from the now-confirmed base-relative cloud route and `GET /models` health check; the local route remains unconfirmed. No actual starter-folder README path was supplied or found; the gateway README was the available BRANE-specific README and is now updated.
