# Changelog

Notable changes, in Keep a Changelog spirit. Tags are annotated and local until
the repository is pushed.

## [1.0.0] - 2026-10-28

The first complete release: measurement, cost model, decision semantics,
Terraform coverage, receipts, evidence.

### Added
- Committed ONNX model fixture with a manifest the runtime refuses to load
  without, and a throughput harness whose capacity estimator is best of 25
  short trials with the band and worst case range recorded.
- Dated, sourced rate card fixtures for AWS, Azure and GCP, and a strict
  loader.
- The cost model: four placements per provider, component breakdowns, and the
  consumed quantity tags E5 audits.
- Crossover sweep, sensitivity with a margin floor and co-winner handling, and
  the three way exit semantics (decided, cannot pick, refuse).
- Terraform generation, hcl2 parse back, and the coverage map.
- Serving arms: the FastAPI surface with a genuinely separate batch route, and
  the batch job runner.
- Experiments E1 to E5, the receipts tooling, the evidence tooling, and CI.

### Fixed, during the build
- The harness estimator, after long trials exposed a quarter of run to run
  variation the fixed item version had been dodging by luck.
- The exception handler ordering that turned every refusal into exit 3.
- The decision rule that printed a winner by a third of a percent (the margin
  floor exists because of that run), the tie handling that made single
  provider decisions impossible, the dead heat that crashed instead of
  reporting itself, and the inverted zone bisection that hid it.
- The receipts checker's textual slot, number pattern, date handling and prove
  step, each caught by running the checker against this repository's own
  documents.
