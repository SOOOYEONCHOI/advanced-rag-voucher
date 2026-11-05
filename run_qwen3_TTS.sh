#!/bin/bash
set -e

# vLLM-Omni(vllm>=0.20) 전용 venv. 기존 .venv_flash(ASR)와 vLLM 버전이 달라 분리한다.
source /opt/vllm/.venv_omni/bin/activate
source /opt/vllm/app/env.sh

export CUDA_VISIBLE_DEVICES=0

export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0
export VLLM_DISABLE_FLASHINFER=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

MODEL_PATH="/opt/vllm/models/gen/Qwen3-TTS-1.7B"
MODEL_NAME="Qwen3-TTS-1.7B"
PORT=8008
# GPU 메모리 비율·동시 처리 수는 deploy config의 stage별 값으로 지정한다(ASR과 GPU 0 공유).
DEPLOY_CONFIG="/opt/vllm/app/qwen3_tts_deploy.yaml"
LOG_PATH="/opt/vllm/logs/vllm_qwen3_tts_1.7b.log"

mkdir -p /opt/vllm/logs

echo "Starting Qwen3-TTS-1.7B server (${PORT})..."

exec vllm serve "${MODEL_PATH}" \
  --omni \
  --deploy-config "${DEPLOY_CONFIG}" \
  --served-model-name "${MODEL_NAME}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --trust-remote-code \
  --enforce-eager \
  --api-key "${VLLM_API_KEY}" \
  > "${LOG_PATH}" 2>&1 &
