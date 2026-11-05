#!/bin/bash
# LLM Qwen3.5-9B — GPU 0, 포트 8101 (개발 run_adrag_model_v2.sh 기준)
# systemd vllm@llm.service 가 실행한다. 로그는 systemd가 /mnt/a/chatbot/vllm/logs/llm.log 에 쓴다.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${VLLM_API_KEY:?env.sh에 VLLM_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=0

MODEL_ROOT=/mnt/a/chatbot/models   # 2026.10.30 수정 - 서버 실제 위치(gen/embedding/reranker 구조)

echo "Starting Qwen3.5-9B LLM server (8101)..."

# --max-model-len 은 backend VLLM_MAX_MODEL_LEN(24576)과 같게
# --gpu-memory-utilization: 개발 0.49(한 GPU에 4개 공존) → 운영 0.70(GPU 0은 LLM + docling)
exec vllm serve "${MODEL_ROOT}/gen/Qwen3.5-9B" \
  --served-model-name Qwen3.5-9B \
  --host 0.0.0.0 \
  --port 8101 \
  --dtype bfloat16 \
  --max-model-len 24576 \
  --max-num-seqs 16 \
  --gpu-memory-utilization 0.70 \
  --tensor-parallel-size 1 \
  --attention-backend FLASH_ATTN \
  --trust-remote-code \
  --api-key "${VLLM_API_KEY}"
