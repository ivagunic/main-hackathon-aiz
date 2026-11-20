# BRANE adapter

Live requests use `BRANE_BASE_URL` (default `https://brane.ai-z.io/api/v1`) and relative `POST /chat/completions` or `GET /models` paths. Both cloud and local lanes use the same chat-completions endpoint. The cloud model is `BRANE_MODEL` (default `auto`); the local model is `BRANE_LOCAL_MODEL` (default `vllm:deepseek-v4.1-flash`). Authentication is read from `BRANE_API_KEY` only.

Every response header beginning `X-Brane-` is retained in the decision snapshot, alongside status, response decision fields and raw response content. HTTP 422 policy refusals raise `BraneBlocked`; connection errors, timeouts and 5xx responses raise `BraneUnavailable`. There is no other-host retry or fallback.

Normal cloud completion validates the exact four integer cent fields before dispatch. The separately named `complete_synthetic_policy_evidence` method is only for the opt-in evidence runner and its synthetic test prompts; it still sends through BRANE so BRANE's policy router can decide cloud, local, placeholder or refusal.
