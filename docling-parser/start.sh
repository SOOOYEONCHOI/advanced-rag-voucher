#!/bin/bash

# Python 캐시 삭제 (import 에러 방지)
find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find /app -name "*.pyc" -delete 2>/dev/null || true

# 2026.08.10(sooyeon.choi) 추가 - Jupyter Lab 제거 및 FastAPI 8007 포트 적용
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8007}"
