# Advanced RAG Framework

프로덕션 환경을 위한 Retrieval-Augmented Generation 시스템으로, 다양한 형식의 문서 수집, 하이브리드 검색, 멀티 프로바이더 LLM 통합을 지원합니다.

## 주요 기능

- 다양한 형식의 문서 수집 (PDF, DOCX, PPTX, XLSX, PNG OCR) — Docling 파서 연동
- 문서 유형 판정(law·manual·general)과 유형별 청킹 전략
- 하이브리드 검색 (벡터 유사도 + BM25/희소 벡터 키워드 검색, 한국어 형태소 분석)
- Cross-Encoder 재순위화 (bge-reranker-v2-m3, vLLM HTTP 서빙)
- vLLM 기반 LLM 서빙 (Qwen3-8B, OpenAI 호환 API)
- vLLM 기반 Embedding 서빙 (Qwen3-Embedding-4B, 2560차원)
- LangGraph 기반 RAG 워크플로 (입력 검증 → 질의 재작성 → 검색 → 재정렬 → 답변 생성 → 인용)
- 출처 추적이 포함된 인용 생성 및 매뉴얼 원문 표시
- 사용자·부서 기반 접근 제어와 관리자/사용자 통계 대시보드
- RAG 평가 플랫폼 (QA 데이터셋 자동 생성·검증, 검색/인용/답변 정확도 지표, LLM Judge, E2E 실행)
- 인터페이스(Protocol) 기반 컴포넌트 교체 아키텍처 (청커·임베딩·리랭커·LLM·벡터스토어)
- Docker 기반 배포 (단일 GPU 서버)

## 시스템 아키텍처

```
┌─────────────┐     ┌──────────────────────────────┐     ┌─────────────────────┐
│  Frontend   │────▶│  Backend (FastAPI)            │────▶│  vllm-llm           │
│  Nginx:80   │     │  Port 8081  │  CPU only      │     │  Qwen3-8B           │
└─────────────┘     │             │                │     │  Port 8002  ~18GB   │
                    │             ├────────────────┤     └─────────────────────┘
                    │             │                │────▶┌─────────────────────┐
                    │             │                │     │  vllm-embedding     │
                    └──────┬──────┘                │     │  Qwen3-Embedding-4B │
                           │                       │     │  Port 8001  ~11GB   │
                    ┌──────▼──────┐                │     └─────────────────────┘
                    │   Qdrant    │                │
                    │  Port 6333  │                │────▶ Reranker vLLM (외부 HTTP)
                    └─────────────┘                │────▶ Docling API (외부)
```

GPU VRAM 배분 (RTX 6000 Ada 46GB):
- vllm-llm: ~18GB (gpu-memory-utilization: 0.40)
- vllm-embedding: ~11GB (gpu-memory-utilization: 0.25)
- 합계: ~29GB / 46GB (여유 ~17GB)

## 사전 요구사항

- Ubuntu 20.04+
- Docker 및 Docker Compose
- NVIDIA GPU (46GB+ VRAM 권장, 최소 32GB)
- NVIDIA Container Toolkit
- 디스크: 루트 20GB+ 여유, 모델 캐시용 별도 파티션 30GB+ 권장

## 빠른 시작

### 1. 사전 준비

```bash
# Ollama 등 GPU 사용 프로세스 중지
sudo systemctl stop ollama

# 모델 캐시 디렉토리 생성 (최초 1회)
sudo mkdir -p /mnt/huggingface-cache
sudo chmod 777 /mnt/huggingface-cache
```

### 2. 환경 변수 설정

```bash
# 견본을 복사한 뒤 서비스 주소, 모델명, 인증 정보 등 필요한 값을 채운다
# (.env는 모든 서비스가 공유하는 Single Source of Truth, 저장소에 올리지 않는다)
cp .env.example .env
# ADMIN_PASSWORD(10자 이상)를 채우면 dev 컨테이너가 최초 기동 때 관리자 계정을 만든다(D-19)
```

### 3. 개발 환경 실행

2026.10.20 수정 - dev는 Backend + Qdrant + PostgreSQL만 컨테이너로 띄우고 LLM·임베딩·리랭커는 외부 GPU 서버(.env 주소)를 쓴다.
WSL에는 compose 플러그인이 없어 `docker-compose`(v1)를 쓴다.

```bash
# 최초 실행: 이미지 빌드 + 기동 (PostgreSQL이 healthy가 된 뒤 backend 시작)
docker-compose -f docker-compose.dev.yml up -d --build

# 백엔드 로그 확인
docker-compose -f docker-compose.dev.yml logs -f backend
#   "✓ Database ready: … @ <revision>"   → alembic upgrade head 완료
#   "[dev 관리자] 관리자 계정을 만들었습니다: admin"   → 이 계정으로 로그인
#   "[dev 관리자] ADMIN_PASSWORD가 .env에 없어 …"     → .env에 추가 후 아래 재시작
docker-compose -f docker-compose.dev.yml restart backend

curl http://localhost:8081/health      # Backend

# 프런트엔드 (http://localhost:3000, /api는 localhost:8081으로 프록시)
cd adrag_frontend && npm install && npm run dev
```

관리자 비밀번호 변경: `docker exec -it rag-backend-dev python scripts/create_admin.py --user-id admin --reset-password`
DB 볼륨(`postgres-dev-data`)을 지우고 다시 띄우면 관리자도 다시 만들어진다.

### 4. 프로덕션 배포

```bash
docker-compose build
docker-compose up -d
```

운영은 관리자를 자동 생성하지 않는다. 최초 1회 `python scripts/create_admin.py --user-id <아이디> --name <이름>`을 실행한다
(SQLite에서 이관한 경우 `admin` 비밀번호를 `--reset-password`로 즉시 변경, docs/design/phase-1_5_PostgreSQL_전환_설계.md 6.2).

### 접속 정보

| 서비스 | 개발 환경 | 프로덕션 |
|--------|----------|---------|
| 프론트엔드 | http://localhost:3000 | http://서버IP |
| 백엔드 API | http://localhost:8081/docs | http://서버IP:8081/docs |
| vLLM LLM·Embedding | .env의 `VLLM_API_URL`·`EMBEDDING_API_URL` (외부 GPU 서버) | 같음 |
| Qdrant | http://localhost:6333/dashboard | http://서버IP:6333/dashboard |

## 프로젝트 구조

```
advanced-rag-framework/
├── adrag_backend/                # FastAPI RAG 백엔드
│   ├── app/
│   │   ├── routes/               # API 라우터 (chat, query, ingest, parse, collections, auth, admin_*, user_*, evaluation)
│   │   ├── clients/              # 외부 서비스 클라이언트
│   │   │   ├── llm_client.py         # vLLM LLM 호출 (httpx 비동기)
│   │   │   ├── embedding_client.py   # vLLM Embedding 호출 (httpx 비동기)
│   │   │   ├── reranker_client.py    # Reranker vLLM HTTP 호출
│   │   │   ├── openai_client.py      # OpenAI 호환 API 호출
│   │   │   ├── sparse_encoder.py     # SPLADE 희소 벡터 인코더
│   │   │   └── kiwi_bm25_encoder.py  # Kiwi 형태소 기반 BM25 인코더
│   │   ├── core/                 # 설정 (pydantic-settings), 공유 HTTP 클라이언트
│   │   ├── interfaces/           # 컴포넌트 교체용 Protocol (chunker, embedding, llm, parser, reranker, vectorstore …)
│   │   ├── graphs/               # LangGraph RAG 파이프라인 (rag_graph, nodes/, retrieval_engine, state, edges)
│   │   ├── models/               # 데이터 모델
│   │   ├── parsers/              # 문서 파싱/유형 판정/청킹 (loaders, detectors, chunkers, utils)
│   │   ├── evaluation/           # RAG 평가 플랫폼 (dataset, metrics, runner, adapters, ports)
│   │   ├── prompts/              # 프롬프트 템플릿
│   │   ├── repositories/         # PostgreSQL/Qdrant 저장소 (로컬 실행: docs/design/local_postgres.md)
│   │   ├── services/             # 비즈니스 로직 (수집, 검색, 통계, 질의 기록)
│   │   └── utils/                # 유틸리티 (보안, 로깅, Kiwi 형태소 분석)
│   ├── main.py                   # FastAPI 애플리케이션 진입점
│   ├── init_database.py          # DB 초기화 스크립트
│   ├── offline_evaluation/       # 오프라인 검색 성능 평가 도구
│   ├── docs/                     # 백엔드 설계 문서 (모듈 교체 가이드 등)
│   ├── tests/                    # 단위·통합·E2E 테스트
│   ├── instance/                 # 런타임 생성 데이터 (원본, 파싱 결과, 청크, db, log)
│   ├── Dockerfile                # 프로덕션 (python:3.12-slim, CPU)
│   ├── Dockerfile.dev            # 개발 (nvidia/cuda 기반)
│   └── requirements.txt
├── adrag_frontend/               # Vue 3 + Vite 프론트엔드 (채팅, 관리, 통계, 평가 화면)
├── docling-parser/               # 문서 → Markdown 변환 파서 서비스 (별도 컨테이너)
├── docs/                         # API 명세, 테이블 정의, 평가 설계 문서
├── docker-compose.yml            # 프로덕션 구성
├── docker-compose.dev.yml        # 개발 구성 (소스코드 마운트)
└── .env                          # 환경 변수 (Single Source of Truth)
```

## Docker 컨테이너 구성

| 컨테이너 | 이미지 | 포트 | GPU | 역할 |
|-----------|--------|------|-----|------|
| backend | python:3.12-slim | 8081 | ✗ | FastAPI (CPU only) |
| vllm-llm | vllm/vllm-openai:latest | 8002→8000 | ✓ (~18GB) | LLM 서빙 |
| vllm-embedding | vllm/vllm-openai:latest | 8001→8000 | ✓ (~11GB) | Embedding 서빙 |
| qdrant | qdrant/qdrant:latest | 6333 | ✗ | 벡터 DB |
| frontend | nginx:alpine | 80 | ✗ | 프론트엔드 |

## 모델 교체

환경 변수만 변경하면 모델을 교체할 수 있습니다:

```bash
# LLM 모델 변경 (backend/.env)
# 루트 .env
VLLM_MODEL_NAME=Qwen/Qwen2.5-14B-Instruct

# Embedding 모델 변경
EMBEDDING_MODEL_NAME=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIM=1024

# 변경 후 재시작
docker-compose -f docker-compose.dev.yml down
docker-compose -f docker-compose.dev.yml up -d
```

## 개발

### 백엔드 개발

```bash
# 개발 모드 실행 (소스코드 볼륨 마운트 + hot reload)
docker-compose -f docker-compose.dev.yml up -d

# 백엔드 로그 확인
docker-compose -f docker-compose.dev.yml logs -f backend

# 테스트 실행
docker exec -it rag-backend-dev pytest
```

### 로컬 개발 (Docker 없이)

```bash
cd adrag_backend

# 가상환경 생성 및 활성화
python -m venv venv
venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행 (vLLM 컨테이너는 별도 실행 필요)
uvicorn main:app --reload
```

## 디스크 관리

루트 디스크가 부족할 경우 Docker 데이터 경로를 /mnt로 변경:

```bash
# /etc/docker/daemon.json
{
  "data-root": "/mnt/docker-data"
}
sudo systemctl restart docker
```

주기적으로 Docker 캐시 정리:
```bash
docker system prune -a
```

## 문서

- [프로젝트 구조](PROJECT_STRUCTURE.md) - 디렉터리 구조와 작업 위치 안내
- [모듈화 아키텍처 분석서](Advanced_RAG_모듈화_아키텍처_분석서.md) - 인터페이스 기반 컴포넌트 교체 아키텍처
- [API 명세서](docs/API_명세서.md) - 백엔드 API 명세
- [모듈 교체 가이드](adrag_backend/docs/MODULE_REPLACEMENT_GUIDE.md) - 컴포넌트 교체 방법
- [API 문서](http://localhost:8081/docs) - FastAPI 자동 문서 (Swagger UI)

## 라이선스

MIT
