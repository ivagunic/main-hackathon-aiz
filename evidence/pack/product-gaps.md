# Product gaps

- BRANE misses repeated and upper-case name variants. PRESCRUB replaces every known variant before live pipeline calls; `T3-brane-only` records this BRANE-only gap.
- BRANE does not detect employer ORG reliably. PRESCRUB replaces the known employer before live pipeline calls; `T3-brane-only` records the gap.
- BRANE did not treat BSN as a national ID before the new category. The live policy now has `NATIONAL_ID_BSN` with refusal; `P3-BSN` checks the denial.
- BRANE's broad `SENSITIVE_MERCHANT` local category cannot separate protected health context from lookalike merchants or mandatory insurance premiums; E1 and E4 document usefulness/legal-review tradeoffs.
- T4 was refused under `NATIONAL_ID_BSN`, not a dedicated `PROMPT_INJECTION` decision. The agent's document-text controls remain necessary; the live trace does not prove a BRANE-specific injection rule.
- BRANE's built-in injection guard can route a flagged prompt to local instead of refusing (live T1 workbench observation); the custom `OVERRIDE_ATTEMPT` refusal rule addresses this routing gap.
- Before the live medical-transfer policy update, the E5 transfer note routed to cloud. The before-fix result is retained; the after-fix run checks local routing.
