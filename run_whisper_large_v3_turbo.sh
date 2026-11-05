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
# Whisper 디코더 최대 길이는 448 토큰(max_target_positions)이라 max-model-len을 그 이하로 둔다.
export VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=50

MODEL_NAME="openai/whisper-large-v3-turbo"
PORT=8009
LOG_PATH="/opt/vllm/logs/vllm_whisper_large_v3_turbo.log"

mkdir -p /opt/vllm/logs

echo "Starting Whisper large-v3-turbo server (${PORT})..."

exec vllm serve "${MODEL_NAME}" \
  --served-model-name "${MODEL_NAME}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --dtype bfloat16 \
  --max-model-len 448 \
  --max-num-seqs 8 \  
  --gpu-memory-utilization 0.10 \
  --tensor-parallel-size 1 \
  --api-key "${VLLM_API_KEY}" \
  > "${LOG_PATH}" 2>&1 &
