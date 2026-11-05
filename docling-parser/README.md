# GPU Docling Parsing Server

Docling 기반 문서 파싱 전용 GPU 서버 (FastAPI)

## 개요

- GPU를 사용하여 PDF, Office, 이미지 등 다양한 문서를 파싱
- 스캔 PDF 자동 감지 및 EasyOCR(GPU) 적용
- 비동기 Job 기반 처리 (요청 → Job ID 반환 → 폴링 → 결과 수신)
- API Key 인증 지원

## 지원 파일 형식

| 형식 | 확장자 | OCR |
|---|---|---|
| PDF (텍스트 레이어) | `.pdf` | 미적용 |
| PDF (스캔본) | `.pdf` | EasyOCR + GPU 자동 적용 |
| Word | `.docx` `.dotx` `.docm` `.dotm` | — |
| PowerPoint | `.pptx` `.pptm` `.potx` `.potm` | — |
| Excel | `.xlsx` `.xlsm` `.xltx` `.xltm` | — |
| 이미지 | `.png` `.jpg` `.jpeg` `.tiff` `.tif` `.bmp` `.webp` | EasyOCR + GPU |

## 시스템 요구사항

- Docker & Docker Compose
- NVIDIA GPU (CUDA 12.1 이상)
- NVIDIA Container Toolkit

## 디렉토리 구조

```
docling-parser/
├── main.py                  # FastAPI 애플리케이션 진입점
├── start.sh                 # 컨테이너 시작 스크립트 (FastAPI)
├── app/
│   ├── __init__.py
│   ├── auth.py              # API Key 인증
│   ├── job_manager.py       # Job 상태 관리
│   ├── docling_wrapper.py   # Docling 파싱 래퍼 (스캔 감지 포함)
│   ├── core/
│   │   └── config.py        # 환경 설정
│   └── utils/
│       └── log/             # 로깅 유틸리티
├── data/
│   ├── uploads/             # 업로드 파일 (볼륨 마운트)
│   ├── outputs/             # 출력 파일 (볼륨 마운트)
│   └── results/             # 파싱 결과 JSON (볼륨 마운트)
├── generate_api_key.py      # API Key 생성 유틸리티
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 설치 및 실행

### 1. 사전 준비 확인

```bash
docker --version
docker-compose --version
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

### 2. .env 파일 생성

```bash
python3 generate_api_key.py
```

API Key를 자동으로 생성하고 `.env` 파일을 작성합니다.  
`.env`가 이미 존재하면 덮어쓸지 확인합니다.

생성되는 `.env` 형식:
```
API_KEY=<자동_생성된_키>
PORT=8007
CUDA_VISIBLE_DEVICES=0
EXCEL_PARSER=openpyxl
```

<!-- 2026.08.13(sooyeon.choi) 수정 - Excel 파서 선택 방법 문서화 -->
`EXCEL_PARSER`의 기본값은 `openpyxl`입니다. Docling의 `ExcelFormatOption` 결과와
비교하려면 `docling`으로 변경한 후 컨테이너를 재시작합니다. 자동 fallback은
수행하지 않으며, 실제 사용된 파서는 결과의 `metadata.parser`와 서버 로그에서
확인할 수 있습니다.

### 4. 데이터 디렉토리 생성

```bash
mkdir -p data/uploads data/outputs data/results
```

### 5. Docker 실행

```bash
docker-compose up -d --build
```

> 첫 실행 시 이미지 빌드에 5~10분 소요됩니다.  
> 이후 코드 수정 시에는 `docker-compose up -d`만 실행하면 됩니다.

### 6. 상태 확인

```bash
docker-compose ps
curl http://localhost:8007/health
```

정상 응답:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-01T00:00:00",
  "active_jobs": 0
}
```

## API 사용법

### 문서 파싱 요청

```bash
curl -X POST "http://<SERVER_IP>:8007/api/parse?output_format=md" \
  -H "X-API-KEY: <your-api-key>" \
  -F "file=@document.pdf"
```

응답:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Parsing job created successfully"
}
```

### Job 상태 조회

```bash
curl -X GET "http://<SERVER_IP>:8007/api/job/{job_id}" \
  -H "X-API-KEY: <your-api-key>"
```

응답:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "created_at": "2026-01-01T00:00:00",
  "completed_at": "2026-01-01T00:01:00",
  "result": null
}
```

> `status`가 `"completed"`일 때 아래 결과 조회 엔드포인트로 본문을 수신합니다.

### 결과 수신

```bash
curl -X GET "http://<SERVER_IP>:8007/api/job/{job_id}/result" \
  -H "X-API-KEY: <your-api-key>"
```

응답 (`output_format=md`):
```json
{
  "format": "md",
  "pages": [
    { "page_no": 1, "markdown": "..." },
    { "page_no": 2, "markdown": "..." }
  ],
  "num_pages": 2,
  "metadata": {
    "file_path": "/app/uploads/...",
    "num_pages": 2
  }
}
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/` | 서버 정보 |
| `GET` | `/health` | 헬스 체크 (활성 Job 수 포함) |
| `POST` | `/api/parse` | 문서 파싱 요청 |
| `GET` | `/api/job/{job_id}` | Job 상태 조회 |
| `GET` | `/api/job/{job_id}/result` | 파싱 결과 수신 (수신 후 메모리에서 제거) |
<!-- 2026.08.10(sooyeon.choi) 추가 - MSDS Markdown 파일 반환 API -->
| `POST` | `/api/msds/parse` | MSDS Markdown 파싱 Job 생성 |
| `GET` | `/api/msds/parse/job/{job_id}` | MSDS Job 상태 조회 |
| `GET` | `/api/msds/parse/job/{job_id}/result` | MSDS Markdown 파일 다운로드 |

### MSDS Markdown 파싱

<!-- 2026.08.10(sooyeon.choi) 추가 - MSDS API 업로드 확장자 제한 -->
MSDS API는 파일명의 마지막 확장자를 기준으로 다음 형식만 허용합니다. 확장자 대소문자는 구분하지 않습니다.

```text
.pdf .jpg .jpeg .png .gif .bmp .tiff .webp
```

`.tif`, Word, PowerPoint, Excel 및 그 밖의 확장자는 `400 Bad Request`를 반환합니다. 이 제한은 MSDS API에만 적용되며 기존 `/api/parse`의 지원 형식에는 영향을 주지 않습니다.

```bash
curl -X POST "http://<SERVER_IP>:8007/api/msds/parse" \
  -H "X-API-KEY: <your-api-key>" \
  -F "file=@msds.pdf"

curl -X GET "http://<SERVER_IP>:8007/api/msds/parse/job/{job_id}" \
  -H "X-API-KEY: <your-api-key>"

curl -X GET "http://<SERVER_IP>:8007/api/msds/parse/job/{job_id}/result" \
  -H "X-API-KEY: <your-api-key>" \
  --output result.md
```

## 운영

### 로그 확인

```bash
# 실시간 로그
docker-compose logs -f docling-gpu-server

# 최근 100줄
docker-compose logs --tail=100 docling-gpu-server
```

### 중지 / 재시작

```bash
docker-compose down
docker-compose restart
```

### 완전 재빌드

```bash
docker-compose down
docker-compose up -d --build
```

## 문제 해결

**GPU가 인식되지 않는 경우**
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
# docker-compose.yml의 deploy.resources.reservations.devices 섹션 확인
```

**포트 충돌**
```bash
sudo netstat -tlnp | grep 8007
# .env 파일에서 PORT 값 변경 후 재실행
```

**컨테이너가 시작되지 않는 경우**
```bash
docker-compose logs docling-gpu-server
```

## 보안

- 모든 API 요청에 `X-API-KEY` 헤더 필수
- 방화벽/보안그룹에서 호출 서버 IP만 허용 권장
- `API_KEY` 미설정 시 개발 환경에서만 인증 없이 허용됨
