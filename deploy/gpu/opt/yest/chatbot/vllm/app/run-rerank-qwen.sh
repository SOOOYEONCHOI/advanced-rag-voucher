#!/bin/bash
# 리랭커 비교 Qwen3-Reranker-0.6B — GPU 2, 포트 8104, /v1/score
# 2026.11.10(sooyeon.choi) 추가 - bge-reranker-v2-m3(8103)와 비교용. systemd vllm@rerank-qwen.service 가 실행한다.
#   GPU 2: 2026-11-10 사용자 확인으로 사용 가능(2·3번). 이 서비스 하나만 올린다.
#   키는 기존 RERANKER_API_KEY 를 같이 쓴다(env.sh 변경 없음).
#   절차 docs/design/운영배포_리랭커Qwen3_20261110.md
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${RERANKER_API_KEY:?env.sh에 RERANKER_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=2

MODEL_ROOT=/mnt/a/chatbot/models

echo "Starting Qwen3-Reranker-0.6B server (8104)..."

# --hf-overrides: 원본 Qwen3-Reranker 는 생성 모델 구조라 분류 모델로 바꿔 읽어야 /v1/score 점수가 맞다(vLLM 문서)
# --gpu-memory-utilization 0.10 ≈ 8GB: 가중치 약 1.2GB(bf16) + 배치 처리. GPU 2 전용이라 bge(0.05)보다 넉넉히 둔다
# --max-model-len 8192: backend 청크 길이 기준. 모델 기본값(40960)이면 메모리를 불필요하게 잡는다
exec vllm serve "${MODEL_ROOT}/reranker/Qwen3-Reranker-0.6B" \
  --served-model-name Qwen3-Reranker-0.6B \
  --runner pooling \
  --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}' \
  --host 0.0.0.0 \
  --port 8104 \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.10 \
  --attention-backend FLASH_ATTN \
  --api-key "${RERANKER_API_KEY}"
