#!/bin/bash
set -e

source /opt/vllm/.venv_flash/bin/activate
source /opt/vllm/app/env.sh

export CUDA_VISIBLE_DEVICES=0

export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0
export VLLM_DISABLE_FLASHINFER=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# 오디오 파일 최대 크기(MB)
export VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=50

MODEL_PATH="/opt/vllm/models/gen/Qwen3-ASR-1.7B"
MODEL_NAME="Qwen3-ASR-1.7B"
PORT=8007
LOG_PATH="/opt/vllm/logs/vllm_qwen3_asr_1.7b.log"

mkdir -p /opt/vllm/logs

echo "Starting Qwen3-ASR-1.7B server (${PORT})..."

exec vllm serve "${MODEL_PATH}" \
  --served-model-name "${MODEL_NAME}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.10 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --api-key "${VLLM_API_KEY}" \
  > "${LOG_PATH}" 2>&1 &