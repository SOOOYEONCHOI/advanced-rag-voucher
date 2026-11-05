#!/bin/bash
set -euo pipefail

source /opt/vllm/.venv_flash/bin/activate
source /opt/vllm/app/env.sh

# GPU 0, GPU 1을 하나의 모델에 사용
export CUDA_VISIBLE_DEVICES=0,1

export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

LOG_DIR="/opt/vllm/logs"
mkdir -p "${LOG_DIR}"

# =========================
# Gemma 4 12B IT
# GPU 0 + GPU 1 Tensor Parallel
# =========================

GEMMA4_MODEL_PATH="/opt/vllm/models/gen/gemma-4-12B-it"
GEMMA4_PORT=8101
GEMMA4_MODEL_NAME="gemma-4-12B-it"

LOG_FILE="${LOG_DIR}/gemma_4_12b_it_tp2.log"

echo "Starting Gemma 4 12B IT..."
echo "GPU: ${CUDA_VISIBLE_DEVICES}"
echo "Tensor Parallel Size: 2"
echo "Port: ${GEMMA4_PORT}"
echo "Log: ${LOG_FILE}"

vllm serve "${GEMMA4_MODEL_PATH}" \
  --host 0.0.0.0 \
  --port "${GEMMA4_PORT}" \
  --dtype bfloat16 \
  --trust-remote-code \
  --api-key "${VLLM_API_KEY}" \
  --served-model-name "${GEMMA4_MODEL_NAME}" \
  --tensor-parallel-size 2 \
  --distributed-executor-backend mp \
  --disable-custom-all-reduce \
  --max-model-len 32768 \
  --max-num-batched-tokens 4096 \
  --enable-prefix-caching \
  --no-scheduler-reserve-full-isl \
  --enable-chunked-prefill \
  --gpu-memory-utilization 0.90 \
  --kv-cache-dtype fp8 \
  >> "${LOG_FILE}" 2>&1 &

echo "Gemma 4 is starting."
echo "GPU: ${CUDA_VISIBLE_DEVICES}"
echo "API: http://localhost:${GEMMA4_PORT}/v1"
echo "Log: ${LOG_FILE}"