#!/bin/bash
# VLM 테스트 서버(vllm@vlm, 8110) 점검 — 모델 목록 · 키 없는 호출 401 · 텍스트 답변 · 이미지 답변
# 2026.11.05 추가. 키를 읽어야 하므로 vllm-admin 으로 실행한다:
#   sudo -u vllm-admin bash /opt/yest/chatbot/vllm/app/check-vlm.sh
# 시험 이미지는 이 스크립트가 직접 그린다(원본 문서·추출 이미지를 쓰지 않는다).
set -e

source /opt/venvs/chatbot/vllm/bin/activate
source /opt/yest/chatbot/vllm/app/env.sh
: "${VLM_API_KEY:?env.sh에 VLM_API_KEY가 비어 있음}"

URL=http://127.0.0.1:8110/v1
MODEL=gemma-4-12B-it

echo "== 1. 모델 목록"
curl -sf -H "Authorization: Bearer ${VLM_API_KEY}" "$URL/models" | head -c 300; echo

echo "== 2. 키 없이 호출 (401 이어야 정상)"
curl -s -o /dev/null -w "%{http_code}\n" "$URL/models"

echo "== 3. 텍스트 답변"
curl -sf "$URL/chat/completions" -H "Content-Type: application/json" -H "Authorization: Bearer ${VLM_API_KEY}" \
  -d "{\"model\":\"$MODEL\",\"max_tokens\":64,\"messages\":[{\"role\":\"user\",\"content\":\"한 문장으로 자기소개 해 주세요.\"}]}" \
  | python -c "import json,sys;print(json.load(sys.stdin)['choices'][0]['message']['content'])"

echo "== 4. 이미지 답변 (상자 2개와 화살표를 그린 흐름도)"
python - "$URL" "$MODEL" <<'PY'
import base64, io, json, os, sys, time, urllib.request
from PIL import Image, ImageDraw

url, model = sys.argv[1], sys.argv[2]
img = Image.new("RGB", (640, 240), "white")
d = ImageDraw.Draw(img)
d.rectangle([40, 80, 220, 160], outline="black", width=3)
d.text((90, 112), "START", fill="black")
d.rectangle([420, 80, 600, 160], outline="black", width=3)
d.text((480, 112), "END", fill="black")
d.line([220, 120, 420, 120], fill="black", width=3)
d.polygon([(420, 120), (400, 110), (400, 130)], fill="black")
buf = io.BytesIO(); img.save(buf, "PNG")
data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

body = {
    "model": model, "max_tokens": 128, "temperature": 0,
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": "이 흐름도의 상자 글자와 화살표 방향을 한 줄로 설명해 주세요."},
    ]}],
}
req = urllib.request.Request(url + "/chat/completions", json.dumps(body).encode(), {
    "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["VLM_API_KEY"]})
t = time.perf_counter()
res = json.load(urllib.request.urlopen(req, timeout=180))
print(res["choices"][0]["message"]["content"])
print(f"== 응답 {time.perf_counter() - t:.1f}초, 토큰 {res['usage']}")
PY
