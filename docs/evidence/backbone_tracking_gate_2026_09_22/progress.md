# Tracking gate v1 implementation ledger

Authority: user said 继续吧 after reviewing docs/backbone_decision_and_tracking_spec_2026_09_22.md. This authorizes implementing and attempting its first independent tracking gate; no training, PID search, RP/F rollout or parameter/threshold changes.

Workspace: .worktrees/backbone-tracking-v1; existing main worktree changes preserved. Source additions will be reviewed and copied back without committing.

- Resource audit: CARLA 0.9.15 server absent. Official package 8,386,636,048 bytes; current local server is 0.9.10.1 and is not substituted. Large package remains user-supplied under AGENTS.md. No simulator started.
- Environment: preparing isolated Python 3.10.19 prefix on data disk; conda dry run official channel succeeds, 28,897,963 bytes to fetch, largest package 25,367,955 bytes. Base environment unchanged.
- Reference/geometry: delegated to commonroad_controller_choice; owns tracking_reference.py and its tests.
- Offline evaluator: delegated to freeze_f_source; owns evaluation/tracking_gate.py and its tests.
- Runner/control adapter: root. Frozen PID, fixed tick sequence and fixed preparation; no controller selection during execution.
- Pre-flight interface: reference rows use RH rear-axle local coordinates; runner transforms fixed world origin (50,0), logs actual actor/rear separately; evaluator derives rear velocity from pose offline.
- Ruling: prior document's no-implementation status is a historical status, superseded for the first tracking gate by the user's continue instruction. RP and F integration remain deferred by the approved gate order.
- Client environment complete: Python3.10.19, carla0.9.15, numpy1.24.2, shapely2.0.7. Conda base and old CARLA untouched. Official PID/misc sources vendored unmodified with license and readable provenance.
- Native client-only OpenDRIVE parse: 600x120m road, tested interior/exterior coordinates and flat z=0; no server connection/physics. Parser warns about omitted georeference; this local fixture does not use GNSS/global geography.
- Runtime contract tests: four first failed due absent implementation, then passed (versions, world-cm geometry, road specification, split preview times).
- Ruling: actual wheel geometry requires a vehicle instance; runtime preflight will use one stationary brake-held calibration actor for exactly 2 seconds before the eight trials, destroy it, then freeze geometry. This is measurement preparation, no PID/controller tuning; it adds 2s beyond the scored 216s and the 8x3s trial initialization.

- Final targeted checks: 24/24 PASS in Python3.10, 24.186s. Eight dense-corridor nominal references PASS; minimum bend clearance 0.337158m. Main worktree resource-independent suite 378/378 PASS (239.474s); isolated baseline 349/349 PASS retained separately.
- Prepared artifact: outputs/backbone_tracking_preparation_2026_09_22, status PREPARED_NOT_EXECUTED, physical_trials_started=0. Archived Python sources are byte-identical to current main copies; no hashes generated.
- Cross-UID ownership test exposed restricted /proc/fd access for root. The exact socket-inode/PGID check is now delegated to the server UID when necessary; the real bounded local dummy-listener test passed. This was not CARLA or driving.
- Final source review issues resolved: owned server, bounded cleanup, correct new-package map-write permissions, authoritative recorder coverage, independent disk audit, maximum preload excursion, complete physics/readback. No simulator server, model training or PID search executed.
- Blocker: user-supplied CARLA0.9.15 8,386,636,048-byte package absent. Asked only for an existing local archive/directory path; no large download initiated. Code and static preparation complete, runtime remains unverified.
