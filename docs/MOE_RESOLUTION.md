# MoE resolution and version mapping

The user-designated 2026-10-16 PDF resolves the old Table 5 mismatch:
Mixtral reports 1.16/0.35/0.46 and 2.52x; Llama reports 1.02/0.28/0.38
and 2.68x. These match the 50,000-slot evidence in `evidence/moe/`.

The current figure uses the 100,000-slot experiment in
`evidence/moe_censored/`, not the old completed-only or fixed-penalty figure.
Every run, unfinished-request arrival record, aggregate, original figure PDF,
and original measurement/plotting source is included.

Run `python scripts/verify_moe_censored.py` to audit the data and
`python scripts/reproduce_moe_censored.py` for a portable numeric redraw.
The manuscript's metric/horizon wording questions were deferred by the user.
They remain explicit scope notes, not missing-data claims.

The old audit under `evidence/moe/history/` preserves provenance and no
longer controls the current MoE publication gate.
