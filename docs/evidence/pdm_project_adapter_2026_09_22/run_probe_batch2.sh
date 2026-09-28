#!/usr/bin/env bash
set -eu
cd /root/autodl-tmp/ToolV2X
LD_LIBRARY_PATH=/root/miniconda3/envs/tcp_codriving/lib/python3.7/site-packages/spconv:/root/miniconda3/envs/tcp_codriving/lib OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/miniconda3/envs/tcp_codriving/bin/python scripts/probe_pdm_closedloop.py \
 --output outputs/pdm_project_adapter_2026_09_22_v2 \
 --carla-root /root/autodl-tmp/CARLA_0.9.10.1 \
 --source-root /root/autodl-tmp/toolv2x_backbone_research_2026_09_19/detector/V2Xverse \
 --model-dir /root/autodl-tmp/toolv2x_backbone_research_2026_09_19/detector \
 --overlap-extension-dir /root/autodl-tmp/CMP/opencood/utils \
 --v2vgot-root /root/autodl-tmp/V2V-GoT \
 --tracker-python /root/autodl-tmp/conda-envs/dmstrack/bin/python \
 --pdm-python /root/autodl-tmp/conda-envs/pdm39/bin/python \
 --port 2200 --batch-number 2 --change-reason "Remove fixed lateral offsets that cannot fit the declared single-route lane-keeping corridor"
