# 프로덕션 최적화 Dockerfile
# 2026.04.21(sooyeon.choi) 수정 - CPU 서버 전환: nvidia/cuda 베이스 이미지 → python:3.11-slim
#   reranker vLLM 분리로 backend GPU 의존성 완전 제거
# 2026.10.27(sooyeon.choi) 수정 - Python 3.11 → 3.12 (python:3.12-slim)
# Multi-stage build로 이미지 크기 최소화

# ============================================
# Stage 1: Builder (빌드 및 의존성 설치)
# ============================================
FROM python:3.12-slim AS builder

# 환경 변수 설정
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 빌드 도구 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 가상환경 생성
RUN python -m venv $VIRTUAL_ENV

# pip 업그레이드
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# PyTorch CPU 버전 설치
RUN pip install --no-cache-dir \
    torch==2.4.0 \
    torchvision==0.19.0 \
    --index-url https://download.pytorch.org/whl/cpu

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 2: Runtime (실행 환경)
# ============================================
FROM python:3.12-slim

# 환경 변수 설정
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 런타임 의존성만 설치 (빌드 도구 제외)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Builder stage에서 가상환경 복사
COPY --from=builder /opt/venv /opt/venv

# 애플리케이션 코드 복사
COPY . .

# 필요한 디렉토리 생성
RUN mkdir -p /app/data /app/uploads /app/logs /app/plugins

# 권한 설정
RUN chmod -R 755 /app

# 포트 개방
EXPOSE 8081

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8081/health || exit 1

# Non-root 사용자로 실행 (보안 강화)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# 2026.04.21(sooyeon.choi) 수정 - GPU OOM 제한 해제, 멀티워커 가능 (reranker 분리로 GPU 공유 이슈 없음)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
