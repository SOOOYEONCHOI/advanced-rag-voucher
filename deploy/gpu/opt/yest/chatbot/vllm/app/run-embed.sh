#!/bin/bash
# 임베딩 Qwen3-Embedding-4B — GPU 1, 포트 8102 (개발 run_adrag_model_v2.sh 기준)
# systemd vllm@embed.service 가 실행한다.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${EMBEDDING_API_KEY:?env.sh에 EMBEDDING_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=1

MODEL_ROOT=/mnt/a/chatbot/models   # 2026.10.30 수정 - 서버 실제 위치(gen/embedding/reranker 구조)

echo "Starting Embedding server (8102)..."

# --max-model-len: 개발 2048 → 8192 (backend EMBEDDING_MAX_MODEL_LEN=8192와 같게. 작으면 긴 청크에서 400 오류)
exec vllm serve "${MODEL_ROOT}/embedding/Qwen3-Embedding-4B" \
  --served-model-name Qwen3-Embedding-4B \
  --runner pooling \
  --host 0.0.0.0 \
  --port 8102 \
  --dtype auto \
  --gpu-memory-utilization 0.18 \
  --max-model-len 8192 \
  --attention-backend FLASH_ATTN \
  --trust-remote-code \
  --api-key "${EMBEDDING_API_KEY}"
