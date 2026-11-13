# SDD ledger — plan: docs/REALLY_MAYBE/rq1_score_revision_2026_11_13/implementation_plan.md

User authorization: 2026-11-13 试试吧. Base eb0617f. Worktree experiment/rq1-score-revision-2026-11-13.

## State
- Completed. Numerical implementation 563b1d057d713f9219b2c6ac762bf1a030307a58; all four numerical stages exit0, total897.10s.
- Task1 prepare reviewed and complete:18COMPLETE/8UNREALIZABLE,17 qualifying entities. Task2 heads/pipeline and final engineering fix independently reviewed PASS.
- Task3 independent result recount PASS,0 production discrepancies across196433 prediction rows. Scaler/fold metadata audit passed. Checker schema and floating-list tolerance corrections recorded without production changes or repeated full scan.
- Method outcome: mixed joint and both transfer claims NOT RETAINED. Preserve supervised scoring infrastructure and D development baseline; no new parameter search or experiment started.
- Current reports task-1-report.md and task-2-score-revision-report.md. Historical task-2-report.md is unrelated and preserved.

## Preflight
| Area | Comparison | Ruling |
| --- | --- | --- |
| Task1/Task2 | prepare.iter_rows + support.json consumed by model pipeline | Shared original row schema, old rows referenced read-only. Task2 may not edit live Task1 source. |
| Task1 | frozen 26 tasks vs native wrapper only NEW_PARENTS | Use direct native functions and explicit per-parent cache adapter, not legacy native.prepare loop. |
| Task2 | fixed source-only fit/cal vs common normal models | Family filter before head scaler/fitting/calibration; normal models only clean. |
| Task3 | uncertainty requirement vs single-parent k3 | Analytical support check first; unavailable interval is not pass. |

Ruling: preserve new worktree and ledger as research provenance — do not apply generic SDD cleanup.
Ruling: prior frozen code/tests unchanged, verified source hashes and runtime imports instead of repeating historical full suite — new tests cover only changed contracts.
Ruling: five legacy fit parents use H1 detections/{parent}, sender FOV and offlineGT; fourth-parent native scan cache is reused — no PCD/detector recomputation is required.
Ruling: after Task1 approval, compare the pre-injection prefix of the first completed job for each cache type against its frozen clean counterpart, before fitting — this checks the newly adapted coordinate/frame input contract once, not repeatedly per job.

Task1 interface ruling: manifest.jobs uses origin=reference for old jobs with source_origin and source_rows/status paths, origin=score_revision for new26. iter_rows returns original schema without head-regime filtering. support_summary owns raw entity support only.

Task1 code complete (3638f32..bae0a67, spec and quality approved).
Task1 minor (deferred): recovered rows+coverage without complete lose diagnostic target_query_rows; authoritative support is recomputed from persisted rows and is unaffected. Do not read missing diagnostic as zero.
Ruling: proceed with approved prepare; avoid live source changes. The minor will be handled after the native batch, without replaying research data.

Task1 fix round1: bae0a67..4a64954 reviewed PASS. Native initial attempt16COMPLETE/8UNREALIZABLE/2errors, all workers exited. Missing FOV public None->[] preserves old unknown/no-coverage; original scan and attack frozen. Manifest snapshot and per-stage code versions retained; only2 online/label stages resumed. Historical error/partial artifacts retained.
Task2 resumed score_revision_heads_implement at review BASE4a64954; drafts heads.py/test_heads.py/test_run.py, run.py pending; no real fitting.

Native prepare COMPLETE: 26 attempts,18COMPLETE/8UNREALIZABLE, historical2FOV errors resolved. Support F1=11entities/6parents, F2=6/5; all3 regimes supported. Initial normal3-car/4-car prefix checks512/578rows no differences; repaired missing-FOV prefix check recorded separately. Task2 implementation still running, no real features/fit/score started.

Prefix audit completed: normal legacy3-car512 rows, native4-car578 rows, repaired missing-FOV3-car194 rows. All compared pre-injection observable/label/native-trust multisets match frozen clean at6 decimals; central numeric IDs excluded and partition ordering normalized. Evidence prefix_check_initial.json and prefix_check_fov_fix.json.

Ruling: inherited tracked task-2-report.md belongs to historical temporal plan (old0.5CPU report), do not read/overwrite as this task. Current Task2 report path is task-2-score-revision-report.md; original task-2 brief and this ledger identify the current score-revision plan. This avoids basename collision without changing the frozen method.

Task2 implementation DONE d6abf17 (BASE4a64954), report task-2-score-revision-report.md, 16 new fixture tests passed. Independent Task2+whole-branch interface review running score_revision_heads_review; no real features/fit/score/report started. Missing historical scripts/check_review.py recorded, no broad reinstall.

Task2 d6abf17 spec and quality approved; review heads_code_review.md. Ruling: before actual features, implement independent cal/eval job parallelism and phase-level imported-code binding; same mathematical inputs/outputs, prevents avoidable serial runtime and unrecorded recovery drift. One targeted fix wave at BASEd6abf17; no real features yet.

Task2 complete (4a64954..d6abf17, spec+quality PASS), engineering fix d6abf17..563b1d0 re-reviewed PASS. Numerical code frozen563b1d0. Starting real features/fit/score/report, workers8, no parameter changes. Independent result checker score_revision_result_recount prepared execution_2026_11_13/recount.py and awaits report.complete.

Final execution complete. Result: docs/REALLY/判别评分修订_开发结果与方法决定_2026-11-13.md. Main docs updated to actual new score. Source-only transfer failed numeric gates; CI unavailable is an additional limitation, not sole failure. Original error/partial and all prior experiments preserved. Local archive only; no GitHub push in this turn.
