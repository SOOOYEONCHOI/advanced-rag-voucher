#!/bin/sh
# 컨테이너 안에서 실행: 샘플 3건을 /parse 로 보내고 완료될 때까지 기다린다.
# 사용: parse_samples.sh <API_KEY> <샘플폴더>
KEY="$1"; DIR="$2"; BASE=http://127.0.0.1:8008
for i in $(seq 1 120); do curl -sf $BASE/health >/dev/null && break; sleep 2; done
curl -sf $BASE/health || { echo "health 실패"; exit 1; }
echo
RC=0
for f in sample_text.pdf sample_scan.pdf sample.png; do
  R=$(curl -s -H "X-API-KEY: $KEY" -F "file=@$DIR/$f" $BASE/api/parse)
  J=$(echo "$R" | python -c 'import sys,json;print(json.load(sys.stdin).get("job_id",""))' 2>/dev/null)
  [ -z "$J" ] && { echo "$f 요청 실패: $R"; RC=1; continue; }
  S=""
  for i in $(seq 1 300); do
    S=$(curl -s -H "X-API-KEY: $KEY" $BASE/api/job/$J | python -c 'import sys,json;print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
    case "$S" in completed|success|done|failed|error) break;; esac
    sleep 2
  done
  echo "$f -> job $J status=$S"
  case "$S" in completed|success|done) ;; *) RC=1; curl -s -H "X-API-KEY: $KEY" $BASE/api/job/$J; echo;; esac
done
exit $RC
