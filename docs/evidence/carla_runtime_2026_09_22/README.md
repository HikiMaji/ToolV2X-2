# CARLA runtime / static-map integration evidence

Date: 2026-09-22. CARLA 0.9.10.1 archive passed a full gzip/tar read, installed at `/root/autodl-tmp/CARLA_0.9.10.1` (7.6GiB). Client and server report the same version. Town03 OpenDrive parses and Town03 loads on the live server.

`capture.json`: new controlled two-vehicle capture at Town03 road19/lane-1, not reproduction of the earlier V2Xverse record. Both LiDAR frame IDs and timestamps match the world snapshot at 50ms fixed simulation steps. 32 channels, 50m range, 100000 points/s, 20Hz, vehicle-relative sensor z=2m; vehicles were braked and allowed 20 settling ticks. Raw pointclouds remain under `outputs/carla_runtime_2026_09_22/`. Actors spawned by this check were destroyed and world settings restored.

`pdm_map_smoke.json`: original PDM called using actual static-map geometry and own-state calibration, with deliberately empty obstacle fixture. This is NOT detection, F/MTR, sensor-based driving, closed-loop control, or method-effect evidence. `synthetic_contract` is retained because the obstacle/signal inputs are placeholders. Test cap=3m/s and zero steering are explicitly assumptions for the stationary smoke, not a production signal/steering reader.

Wheel positions from the runtime are world-frame centimetres, converted to vehicle-local metres. Rear axle origin is mean rear-wheel x projected onto vehicle ground plane. Raw wheel coordinates, body box and center of mass are retained for review. This calibration is for the spawned Lincoln and does not establish the old recording's vehicle calibration.

Server startup (existing autodl user, writable Saved/runtime HOME):

```bash
cd /root/autodl-tmp/CARLA_0.9.10.1
runuser -u autodl -- env HOME=/root/autodl-tmp/carla-runtime-home DISPLAY= SDL_VIDEODRIVER=offscreen ./CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping CarlaUE4 -opengl -quality-level=Low -carla-rpc-port=2200 -nosound
```

Original launcher emitted a harmless chmod warning for root-owned executable; binary ran successfully. Direct binary startup above avoids that warning. Server was used for this bounded readiness check only.

Reproduce map/PDM conversion from saved capture:

```bash
/root/autodl-tmp/conda-envs/pdm39/bin/python scripts/check_carla_capture.py outputs/carla_runtime_2026_09_22/capture.json /tmp/new_pdm_map_check.json
```

Open items: actual recorded route and timing/calibration binding; legal detector/tracker and reliable prediction; production method_episode integration; actual controller/closed-loop and P/F effect evaluation.
