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

# 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - DWG→DXF 변환기 LibreDWG(GPLv3). 런타임 단계에 /opt/libredwg를 복사, 별도 프로세스로만 호출
# 2026.11.13(sooyeon.choi) 수정 - 운영 도면 등록을 켜므로 기본값 true. 빼려면 --build-arg WITH_LIBREDWG=false
ARG WITH_LIBREDWG=true
ARG LIBREDWG_VERSION=0.13.3
RUN mkdir -p /opt/libredwg && if [ "$WITH_LIBREDWG" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends make xz-utils \
      && curl -fsSL "https://ftp.gnu.org/gnu/libredwg/libredwg-${LIBREDWG_VERSION}.tar.xz" -o /tmp/libredwg.tar.xz \
      && tar -xJf /tmp/libredwg.tar.xz -C /tmp \
      && cd /tmp/libredwg-${LIBREDWG_VERSION} \
      && ./configure --disable-bindings --disable-docs --prefix=/opt/libredwg \
      && make -j"$(nproc)" && make install \
      && cd / && rm -rf /tmp/libredwg* && rm -rf /var/lib/apt/lists/*; \
    fi

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
# 2026.10.28(woojin.jung) 추가 - Excel 시트 PDF 렌더링용 LibreOffice UNO와 한글 글꼴
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice-calc \
    python3-uno \
    fonts-noto-cjk \
    fonts-nanum \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Builder stage에서 가상환경 복사
COPY --from=builder /opt/venv /opt/venv
# 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - LibreDWG(빌드한 경우에만 내용이 있음). LIBREDWG_BIN 기본값 dwg2dxf로 찾도록 PATH에 둔다
# 2026.11.13(sooyeon.choi) 수정 - 변환기는 PATH·LANG 만 넘겨 실행해 LD_LIBRARY_PATH 가 전달되지 않는다 → ldconfig 에 등록
COPY --from=builder /opt/libredwg /opt/libredwg
RUN echo /opt/libredwg/lib > /etc/ld.so.conf.d/libredwg.conf && ldconfig
ENV PATH="/opt/libredwg/bin:$PATH"

# 애플리케이션 코드 복사
COPY . .

# 필요한 디렉토리 생성
# 2026.10.28(woojin.jung) 수정 - UNO 시트 미리보기 작업 디렉터리까지 런타임에 생성
RUN mkdir -p /app/data /app/uploads /app/logs /app/plugins /app/instance/sheet_preview

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
