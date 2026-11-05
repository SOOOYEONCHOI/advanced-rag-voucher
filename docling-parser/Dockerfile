# GPU 지원을 위한 CUDA 베이스 이미지 사용
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# 작업 디렉토리 설정
WORKDIR /app

# 2026.10.27(sooyeon.choi) 수정 - Python 3.10 → 3.12
#   ubuntu22.04 기본 저장소에 3.12가 없어 deadsnakes PPA로 설치, CUDA 베이스 이미지는 유지
#   시스템 python3(3.10)와 섞이지 않도록 /opt/venv 가상환경 사용
ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# 시스템 패키지 업데이트 및 Python 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    gpg-agent \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 가상환경 생성 (python / pip 는 /opt/venv/bin 의 3.12를 가리킨다)
RUN python3.12 -m venv $VIRTUAL_ENV \
    && pip install --no-cache-dir --upgrade pip setuptools wheel

# Python 의존성 설치 (Docling 포함)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY main.py .
COPY app/ ./app/
COPY start.sh .

# start.sh 실행 권한 부여
RUN chmod +x /app/start.sh

# 업로드, 출력, 결과 디렉토리 생성
RUN mkdir -p uploads outputs results

# 포트 노출
EXPOSE 8008

# 환경 변수 설정
ENV PORT=8008
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 애플리케이션 실행 (FastAPI + Jupyter Lab)
# bash로 직접 실행하여 권한 문제 해결
CMD ["bash", "/app/start.sh"]
