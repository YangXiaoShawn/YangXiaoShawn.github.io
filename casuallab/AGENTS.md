# Repository Working Agreement

This repository evaluates marketplace pricing and incentive experiments under interference. Treat this file as persistent implementation guidance.

## Non-negotiable research rules

- Define the estimand and assignment mechanism before choosing an estimator.
- Never call an observational association causal without a defensible identification argument.
- Label every result as empirical/descriptive, semi-synthetic, or theoretical.
- Never hard-code simulated findings, treatment effects, uncertainty, power, or coverage.
- Preserve privacy suppression and measurement-rounding indicators; do not silently treat them as exact values.
- Use deterministic seeds in configs and record them in output metadata.
- Evaluate learned policies on data or simulation draws not used for training.

## Engineering rules

- Support a laptop-safe sample mode before full-data mode.
- Keep notebooks thin; reusable logic belongs in `src/casuallab`.
- Put small immutable fixtures in `data/fixtures`; generated data belongs in ignored directories.
- Every generated artifact must include enough metadata to reproduce its inputs and configuration.
- Add or update tests with each behavioral change. Run focused tests during development and the full suite before handoff.
- Update `docs/DECISION_LOG.md` for consequential modeling or identification choices and `STATUS.md` for milestone changes.

## Completion checks

Run `make lint`, `make test`, and `make reproduce-sample`. Confirm the dashboard identifies the estimand and distinguishes descriptive real-data moments from simulated causal effects.

