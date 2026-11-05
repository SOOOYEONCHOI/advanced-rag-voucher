#!/usr/bin/env bash
# 개발 PC(WSL): VLM 테스트 모델 Gemma4-12B-it 를 받아 폐쇄망 반입용으로 모은다.
# 저장소 루트에서:
#   hf auth login                                   # Gemma 는 사용 동의가 필요한 모델 — 동의한 계정 토큰으로 한 번
#   bash deploy/gpu/tools/download_gemma4_model.sh  # 또는 REPO=<저장소 ID> bash ...
#   → deploy/gpu/mnt/a/chatbot/offline/vllm/models/gen/gemma-4-12B-it/ (+ 폴더 안 SHA256SUMS)
#     서버 /mnt/a/chatbot/offline/vllm/models/gen/gemma-4-12B-it/ 로 WinSCP(바이너리 모드)
# 개발 서버에 이미 있는 모델(/opt/vllm/models/gen/gemma-4-12B-it)을 복사해 와도 된다 — 그때는 SRC=<복사해 온 폴더>.
# 설명: docs/design/운영배포_VLM테스트_Gemma4_20261105.md
# 2026.11.05 추가
set -e

# TODO(결정필요: Hugging Face 저장소 ID 확인 — 개발 서버 모델을 받은 곳과 같은지)
REPO=${REPO:-google/gemma-4-12B-it}
NAME=gemma-4-12B-it
OUT=deploy/gpu/mnt/a/chatbot/offline/vllm/models/gen/$NAME

mkdir -p "$OUT"
if [ -n "$SRC" ]; then
  cp -a "$SRC"/. "$OUT"/
else
  hf download "$REPO" --local-dir "$OUT"
fi
rm -rf "$OUT/.cache"   # hf 가 남기는 내려받기 기록 — 서버에 필요 없음

# 필수 파일 확인 (없으면 vLLM 기동 실패)
for f in config.json tokenizer_config.json; do
  [ -f "$OUT/$f" ] || { echo "== $f 없음 — 모델 폴더를 확인"; exit 1; }
done
ls "$OUT"/*.safetensors >/dev/null 2>&1 || { echo "== safetensors 없음"; exit 1; }
[ -f "$OUT/preprocessor_config.json" ] || [ -f "$OUT/processor_config.json" ] || echo "== 경고: 이미지 전처리 설정 파일이 없음(VLM 이면 보통 있음)"

(cd "$OUT" && find . -type f ! -name SHA256SUMS -exec sha256sum {} \; > SHA256SUMS)
echo "== 완료: $OUT ($(du -sh "$OUT" | cut -f1), 파일 $(wc -l < "$OUT/SHA256SUMS")개)"
