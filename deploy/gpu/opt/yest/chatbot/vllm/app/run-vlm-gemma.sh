#!/bin/bash
# VLM 테스트 Gemma-4-12B-it — GPU 3, 포트 8111
# 2026.11.10(sooyeon.choi) 추가 - 흐름도·도면 이미지 인식용. A.X-4.0-VL-Light(8110)와 비교. systemd vllm@vlm-gemma.service 가 실행한다.
#   GPU 3: 2026-11-10 사용자 확인으로 사용 가능(2·3번). 비어 있던 3번에 혼자 올린다.
#   개발 run_gemma4_12b_tp2.sh 는 GPU 2장(TP 2)이었지만 H100 80GB 는 1장으로 충분하다(가중치 bf16 약 24GB).
#   키는 기존 VLM_API_KEY 를 같이 쓴다(env.sh 변경 없음).
#   포트: 8110 은 A.X VLM, 8104 는 Qwen3 리랭커라 VLM 옆 8111 을 쓴다.
#   절차 docs/design/운영배포_VLM테스트_20261105.md §6
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${VLM_API_KEY:?env.sh에 VLM_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=3

MODEL_ROOT=/mnt/a/chatbot/models

echo "Starting Gemma-4-12B-it VLM server (8111)..."

# --gpu-memory-utilization 0.60 ≈ 48GB: 가중치 약 24GB + 이미지 처리·KV 캐시.
#   TTS(0.24, 8109)도 GPU 3에 올린다(2026-11-10 사용자 결정) → 합계 0.84 로 0.9 이하
# --max-model-len 32768: 개발 스크립트와 같다. 도면 여러 장 + 긴 JSON 출력 여유. KV 캐시 부족 오류가 나면 16384로 낮춘다
# 개발 스크립트의 --kv-cache-dtype fp8 은 빼었다(TTS와 함께 써도 GPU 3 메모리 여유가 있고, 품질 영향을 없앤다)
exec vllm serve "${MODEL_ROOT}/gen/Gemma-4-12B-it" \
  --served-model-name Gemma-4-12B-it \
  --host 0.0.0.0 \
  --port 8111 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 4096 \
  --limit-mm-per-prompt '{"image": 4}' \
  --gpu-memory-utilization 0.60 \
  --tensor-parallel-size 1 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --trust-remote-code \
  --api-key "${VLM_API_KEY}"
