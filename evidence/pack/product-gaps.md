# Product gaps

- BRANE misses repeated and upper-case name variants. PRESCRUB replaces every known variant before live pipeline calls; `T3-brane-only` records this BRANE-only gap.
- BRANE does not detect employer ORG reliably. PRESCRUB replaces the known employer before live pipeline calls; `T3-brane-only` records the gap.
- BRANE did not treat BSN as a national ID before the new category. The live policy now has `NATIONAL_ID_BSN` with refusal; `P3-BSN` checks the denial.
- Before the live medical-transfer policy update, the E5 transfer note routed to cloud. The before-fix result is retained; the after-fix run checks local routing.
