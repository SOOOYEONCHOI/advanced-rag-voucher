#!/bin/bash
# 리랭커 bge-reranker-v2-m3 — GPU 1, 포트 8103, /v1/score (개발 run_adrag_model_v2.sh 기준)
# systemd vllm@rerank.service 가 실행한다.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${RERANKER_API_KEY:?env.sh에 RERANKER_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=1

MODEL_ROOT=/mnt/a/chatbot/models   # 2026.10.30 수정 - 서버 실제 위치(gen/embedding/reranker 구조)

echo "Starting Reranker server (8103)..."

exec vllm serve "${MODEL_ROOT}/reranker/bge-reranker-v2-m3" \
  --served-model-name bge-reranker-v2-m3 \
  --runner pooling \
  --host 0.0.0.0 \
  --port 8103 \
  --dtype float16 \
  --gpu-memory-utilization 0.05 \
  --attention-backend FLASH_ATTN \
  --api-key "${RERANKER_API_KEY}"
