# Gateway decisions

The repository arrived without AI-Z connection details or credentials. The gateway therefore implements the assumed OpenAI-compatible BRANE chat-completions shape behind `BraneClient`; requests are disabled until `BRANE_BASE_URL` and `BRANE_MODEL` are configured. Authentication uses `BRANE_API_KEY` when supplied.

`BRANE_MODE=fake` is the default for local development. The live API is not verified against AI-Z's service. BRANE policy configuration and its decision-log schema remain external setup items; the adapter captures a response body `brane_verdict` field or `x-brane-verdict` header and records `unreported` otherwise.

The local processing adapter remains a deterministic fake. AI-Z's approved local route and model name were not supplied. The runtime uses aggregate-only cloud prompts, which contain no case document text.

## AI-Z questions still awaiting answers

| Question from the integration plan | Status |
|---|---|
| Exact BRANE base URL, auth method, and chat API compatibility | Not supplied |
| Where and how BRANE policy rules are configured | Not supplied; local policy references are proposed IDs only |
| BRANE local model route and model name | Not supplied; adapter assumes `/v1/local/chat/completions` |
| BRANE decision log and protected-input response fields | Not supplied; adapter captures known response fields and safe metadata |
| Jury execution method and live evidence format | Not supplied; local protocol remains pending live results |

No live BRANE call or BRANE policy setup was possible from the provided workspace.
