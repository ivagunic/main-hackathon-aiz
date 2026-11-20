# Repository rules

1. Use synthetic data only.
2. Only `app/gateway/` may make network calls. Do not import network clients elsewhere.
3. Cloud calls go through BRANE. If BRANE is unavailable, fail closed.
4. Financial calculations are deterministic code, never model output.
5. Routing decisions are deterministic; sort before iteration.
6. Treat `contracts/` and `app/models.py` as shared interfaces.
7. Python 3.12, type hints, and dependencies listed in `requirements.txt`.
