#!/bin/bash
# 평가 데이터셋 생성용 Gemma-4-31B-it (FP8) — GPU 2, 포트 8112
# 2026.11.17(sooyeon.choi) 추가 - RAG 평가 데이터셋(질문·정답) 생성용. systemd vllm@gen-gemma31b.service 가 실행한다.
#   상시 서비스가 아니다. 데이터셋 만드는 기간에만 start 하고 끝나면 stop 한다(enable 하지 않는다).
#   GPU 2: Qwen3 리랭커(0.10, 8104)와 함께 쓴다. 2026-11-17 nvidia-smi 기준 GPU 2 사용 8.6GB.
#   bf16 가중치 약 62GB 라 0.9 상한 안에 KV 캐시 자리가 없다 → 미리 양자화된 FP8 모델(gemma-4-31B-it-FP8, 가중치 약 31~33GB)을 쓴다
#   키는 기존 VLLM_API_KEY 를 같이 쓴다(env.sh 변경 없음).
#   포트: 8101~8119 가 챗봇 범위(MAIP 공유 11-17). 8111 다음 빈 번호 8112.
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh

# 키가 비어 있으면 인증 없이 열리므로 기동하지 않는다
: "${VLLM_API_KEY:?env.sh에 VLLM_API_KEY가 비어 있음}"

export CUDA_VISIBLE_DEVICES=2

MODEL_ROOT=/mnt/a/chatbot/models
MODEL_DIR="${MODEL_ROOT}/gen/gemma-4-31B-it-FP8"

echo "Starting gemma-4-31B-it-FP8 dataset generator (8112)..."

# --gpu-memory-utilization 0.75 ≈ 60GB: FP8 가중치 약 31GB + KV 캐시 약 25GB.
#   GPU 2 합계 = Qwen3 리랭커 0.10 + 0.75 = 0.85 로 0.9 이하
# --quantization 은 주지 않는다: FP8 모델의 config.json(quantization_config)을 vLLM이 자동으로 읽는다.
#   형식이 다른데 fp8 을 직접 지정하면 기동 오류가 나므로 비워 둔다
# --limit-mm-per-prompt image 0: 텍스트만 생성한다. 이미지 처리용 메모리를 잡지 않는다
# --max-model-len 16384: 문서 청크 여러 개 + 질문·정답 JSON 출력이면 충분. KV 캐시 부족 오류가 나면 8192로 낮춘다
exec vllm serve "${MODEL_DIR}" \
  --served-model-name gemma-4-31B-it-FP8 \
  --host 0.0.0.0 \
  --port 8112 \
  --dtype bfloat16 \
  --max-model-len 16384 \
  --max-num-seqs 16 \
  --max-num-batched-tokens 8192 \
  --limit-mm-per-prompt '{"image": 0}' \
  --gpu-memory-utilization 0.75 \
  --tensor-parallel-size 1 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --trust-remote-code \
  --api-key "${VLLM_API_KEY}"
