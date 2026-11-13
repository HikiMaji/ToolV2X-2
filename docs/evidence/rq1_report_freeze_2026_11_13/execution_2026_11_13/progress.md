# SDD ledger — plan: docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/implementation_plan.md

Task status: Task 1 implemented at 2b71ea9, independent code review running; Task 2 not started.
Base commit: e1e52d4. Worktree already isolated on experiment/rq1-score-revision-2026-11-13.

| Checked tasks | Interface or internal agreement | Finding |
| --- | --- | --- |
| Task 1 | prepare/fit/evaluate consume frozen config; fixtures cover new semantics | Compatible with SDS; no changes to legacy production |
| Task 2 | consumes complete marks, predictions and metrics from Task 1 | Must await independent code approval before real run |
| Task 1 / Task 2 | CLI stages and output filenames | Compatible; scientific failure still completes experiment |

Ruling: Existing isolated worktree reused; do not create another or touch dirty root historical files.
Ruling: Preserve scratch/evidence at finish under project preservation requirements; no cleanup deletion.
Ruling: Native prepare uses verified Python3.10.19 numpy1.25.2 scipy1.11.4. Numeric fit/evaluate use main Python3.8.10 numpy1.24.2 scipy1.10.1 to match old score artifacts. all must dispatch native prepare subprocess then main numeric stages.
Ruling: re6 external original has trailing blank line; preserve byte-for-byte and exclude that original from whitespace check. Authored docs passed.

SDS reviewer: /root/report_freeze_sds_review, PASS spec and readiness. Implementer: /root/report_freeze_implement. Independent result checker: /root/report_freeze_recount (preparing only; formal recount waits completion).

Task 1 implementation: 2b71ea9; 9 new tests PASS, full temporary flow and native/numeric scheduling covered. Reviewer /root/report_freeze_code_review is reviewing complete implementation delta e1e52d4..2b71ea9. No true run launched.

Task 1 fix round 1/5: 1 addressed, 0 open; commit 2b71ea9..4b90295. Candidate and required-comparator missing primary scores now block retention. Reviewer PASS spec and Ship after scoped re-review.
Task status: Task 1 complete; Task 2 launching the frozen all pipeline at 4b90295.

Live execution checkpoint: launcher tool session 15431, main PID recorded in execution.attempt1.json (recheck live state before any process action). 15/30 jobs COMPLETE, no error markers, prepare still running. Numerical code 4b90295 unchanged. After run.complete and exit0: trigger /root/report_freeze_recount for actual independent audit; plot_results.py is prepared but must run only after audit passes; then archive results and update PPT/master/STATUS. Do not restart a running all process.

Ruling: Added two helper native processes to service unstarted jobs from the same frozen manifest, within max six workers. Existing per-job locks make parent pool adopt completion without duplicate replay. No source/config/model edits; helper IDs and PIDs in worker_assist.json.

Execution: 30 tasks terminal (25 COMPLETE, 5 UNREALIZABLE); fit.complete for all three regimes saved, feature generation/evaluation running. Old cal inspection before new eval review revealed expected MATE scoreless Unknown domain. report_integrity_revision.md fixes only report completeness semantics after original run finishes, preserving all raw scores/policies/decisions/effect metrics and original reports; report_integrity.py being implemented separately, core running files remain 4b90295. Independent reviewer confirmed MATE deletion semantics from actual updater.

Task 2 complete: original all exit0, 3683.684s, 25 COMPLETE+5 UNREALIZABLE, 19 nonempty false entities. Report-only 7c380ea revision completed20.747s; original scores/decisions/metrics preserved. Independent recount PASS237610 rows0 production differences;70 floating boundary checks resolved using saved scores and original inequalities, no epsilon or recomputation of full statistics. D_zero/J_zero all three regimes not_retained. PPT/REALLY/master updated, final archive in progress.

Task status: COMPLETE. All planned work, independent review, audited results, PPT figures/CSV and current research decision are delivered. No active research process remains. Current branch/worktree and all old/new evidence are preserved; no merge, cleanup deletion or GitHub push requested for this execution turn.
