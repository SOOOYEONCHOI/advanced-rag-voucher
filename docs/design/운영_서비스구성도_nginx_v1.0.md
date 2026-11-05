# 운영 서비스 구성도 · nginx 설정 비교 v1.0

> 작성 2026-11-02 · 기준: 저장소 `deploy/webwas/etc/nginx/conf.d/`(00-default·maip·chatbot·ai-api.conf), 배포 문서 2종
> 서버에 실제로 깔린 파일과 같은지는 확인하지 않았다(운영 서버 미접속, CLAUDE.md 절대 규칙 2). 주소·키 값은 쓰지 않는다.
> 설치·배포 절차는 `운영배포_가이드_서버별_v1.1.md`, `운영배포_수정배포_가이드_v1.1.md`를 따른다. HTTPS·서브도메인의 MAIP 쪽 절차는 MAIP `docs/DEPLOYMENT.md` §5.

---

## 1. 전체 구조

```
                         사용자 브라우저 / MAIP 현장 Client
                                      │  https (인증서는 ALB)   ※ 80→443 넘기기는 나중에
                                      ▼
┌──────────────────────── NCP 수도권 ──────────────────────────────────────────────┐
│  NCP ALB  :443 HTTPS / :80 HTTP  (MAIP와 함께 씀, 대상 그룹 = yest-web 80)        │
│     │  http + X-Forwarded-For / X-Forwarded-Proto                                │
│     ▼                                                                            │
│  yest-web  (Rocky 9.6, WEB/WAS)                                                  │
│  ┌─ nginx :80 (MAIP 운영) ─────────────────────────────────────────────────┐     │
│  │  00-default.conf  이름 없는 요청 → /lb-health "ok"(ALB 헬스체크), 나머지 끊음 │     │
│  │  maip.conf     maip-web.yest.co.kr ──────────▶ 127.0.0.1:8080 MAIP (Django)│     │
│  │  chatbot.conf  chatbot.yest.co.kr                                        │     │
│  │                 ├ /, /admin, /assets/ ─▶ /opt/yest/chatbot/frontend (Vue)  │     │
│  │                 └ /api/ ───────────────▶ 127.0.0.1:8081                    │     │
│  │  ai-api.conf   ai-api.yest.co.kr (사무실 IP만) ─▶ GPU Wezard :8000 ───────┼──┐  │
│  └─────────────────────────────────────────────────────────────────────────┘  │  │
│                                                       │                         │  │
│  chatbot_backend 컨테이너 (FastAPI, systemd chatbot)  ◀┘                         │  │
│    /app  ← /opt/yest/chatbot/backend (읽기 전용 소스, deploy.sh가 교체)           │  │
│    /data ← /mnt/a/chatbot/data  (원본 문서·사진·청크·SQLite 메타)                 │  │
│    /logs ← /mnt/a/chatbot/logs      .env ← /opt/yest/chatbot/.env              │  │
│       │                │                                    │                   │  │
│       │ 15020          │ 6333                               │ vLLM·docling 포트 │  │
│       ▼                ▼                                    │                   │  │
│  NCP Cloud DB      yest-vector-db                           │                   │  │
│  PostgreSQL        (Ubuntu 24.04)                           │                   │  │
│  (관리형)           Qdrant                                   │                   │  │
└─────────────────────────────────────────────────────────────┼───────────────────┼──┘
                                                 리전 간 연결  │                   │
┌──────────────────────── NCP 남부권 ─────────────────────────▼───────────────────▼──┐
│  yest-gpu (Ubuntu 24.04)                                                          │
│    vLLM 4개: 답변 LLM · 임베딩 · 재순위 · 이미지 설명    ← 챗봇 백엔드가 직접 부름     │
│    docling-parser (PDF·이미지 파싱)                      ← 챗봇 백엔드가 직접 부름     │
│    Wezard :8000 ── MAIP와 서버끼리 직접 통신(ALB 안 거침) ──▶ yest-web :80           │
└───────────────────────────────────────────────────────────────────────────────────┘

관리 접속: 개발 PC ─SSL VPN(수도권·남부권 각각)─▶ 각 서버 :22 (WinSCP·ssh, 계정 sychoi)
배포:      개발 PC build_package.sh → /mnt/a/chatbot/offline/ → ./deploy.sh [--backend-only|--frontend-only]
```

- GPU 모델 구성(vLLM 4개·docling)은 배포 문서 기준이다. 모델별 포트는 수정배포 가이드 §5.1.
- 음성(ASR/TTS) 서버는 운영 사용 여부를 확인하지 못해 그림에 넣지 않았다.

### 1.1 챗봇 요청 한 건의 흐름 (`https://chatbot.yest.co.kr`)

1. 브라우저가 ALB 443에 접속하고, ALB가 인증서로 HTTPS를 푼다.
2. ALB가 yest-web nginx 80으로 평문으로 넘긴다. 원래 HTTPS였다는 표시(`X-Forwarded-Proto: https`)를 함께 보낸다.
3. nginx가 Host `chatbot.yest.co.kr`을 보고 `chatbot.conf`로 보낸다. 화면 파일은 nginx가 바로 주고, `/api/…`는 컨테이너 8081로 넘긴다.
4. 백엔드가 권한을 확인하고 PostgreSQL(메타데이터·권한), Qdrant(벡터 검색), GPU 서버(임베딩·재순위·답변 생성)를 차례로 부른 뒤 답변을 스트리밍으로 돌려준다.

### 1.2 밖에 열린 것

- ALB의 443·80뿐이다.
- 8080(MAIP)·8081(챗봇)은 `127.0.0.1`에만 열려 있어 서버 밖에서 직접 들어올 수 없다.
- DB·Qdrant·GPU는 서버끼리만 통신하고 ACG로 막혀 있다(서버별 가이드 §0.2 연결도와 포트).

---

## 2. nginx 설정 비교 — `chatbot.conf` / `maip.conf`

**같은 점**

- 둘 다 평문 80으로 받고 Host(도메인 이름)로 서비스를 가른다.
- ALB 대역에서 온 접속 주소만 믿는다(`set_real_ip_from`, 같은 대역).
- `X-Forwarded-Proto`는 둘 다 `00-default.conf`의 `$forwarded_proto` 값을 넘긴다.
- 이 세 가지 덕분에 HTTPS 전환 때 nginx를 바꿀 필요가 없다.

| 항목 | `maip.conf` | `chatbot.conf` | 이유 |
|---|---|---|---|
| 받는 이름 | `maip-web.yest.co.kr` + ALB 주소 | `chatbot.yest.co.kr`만 | MAIP는 ALB 주소로 붙는 옛 Client가 남아 있다. 모두 바꾼 뒤 ALB 주소를 뺀다 |
| 화면 내보내기 | 전부 앱(Django, 8080)으로 넘긴다 | 화면 파일은 nginx가 직접 주고 `/api/`만 8081로 넘긴다 | 챗봇 화면은 Vue 빌드 결과(정적 파일)다 |
| 화면 캐시 | 없음 | `/assets/` 30일 캐시, `index.html`은 매번 새로 확인 | 배포 뒤 옛 화면이 남지 않게 한다 |
| 화면 주소 처리 | 앱이 처리 | 없는 주소는 `index.html`로 보냄 | `/admin` 같은 화면 주소(Vue Router history 모드)가 열리는 이유 |
| 응답 대기 시간 | 120초 | 300초 | 챗봇은 답변 생성·엑셀 등록이 오래 걸린다. ALB 유휴 시간 제한도 300초 이상 |
| 응답 모아 두기 | 기본(켜짐) | 끔(`proxy_buffering off`) | 답변이 글자 단위로 흘러나오게(스트리밍) 한다 |
| 업로드 한도 | 40MB | 60MB | 챗봇 앱 업로드 상한(50MB)보다 크게. 상한 판정은 앱이 한다 |
| 특정 IP만 여는 경로 | `/api/v1/datasets/`는 Wezard(GPU)만 | 없음 | MAIP는 Wezard가 ALB를 거치지 않고 서버로 바로 붙는 경로가 있다 |
| 내부 전용 경로 | `/_protected/…`: 앱이 권한을 확인한 뒤 nginx가 파일을 직접 준다 | `/internal/`: 무조건 404 | 챗봇은 원본 파일·이미지를 앱이 권한을 확인하고 직접 준다. nginx는 데이터 폴더를 읽지 않는다(ACL로 프런트 폴더만) |
| 프록시 연결 방식 | 기본(HTTP/1.0) | HTTP/1.1 | 스트리밍 응답에 필요하다 |

요약: MAIP는 nginx가 앱 앞에서 거의 그대로 넘겨주는 역할이고, 챗봇은 nginx가 화면 서버 역할까지 하며 API에는 오래 걸리는 요청·스트리밍용 설정이 더 들어가 있다. 서로 충돌하는 부분은 없다.

### 2.1 나머지 두 파일

| 파일 | 역할 |
|---|---|
| `00-default.conf` | 공통 설정. 이름이 맞지 않는 요청을 받는 기본 server(ALB 헬스체크 `/lb-health`·`/`는 "ok", 나머지는 응답 없이 끊음), `$forwarded_proto` 정의, 긴 서버 이름용 해시 크기. 서비스 파일보다 먼저 읽히게 `00-`으로 둔다 |
| `ai-api.conf` | `ai-api.yest.co.kr` → GPU 서버 Wezard 관리자 화면. 사무실 공인 IP만 열고 `/api/v1`은 막는다 |

nginx는 MAIP 담당이 운영한다. `chatbot.conf`를 바꿀 때는 먼저 알린다(서버별 가이드 §4.3 ⑪, 수정배포 가이드 §4.5).

---

## 3. HTTPS 적용 (2026-11-02 인증서 발급)

- 인증서는 **ALB에 등록**한다. 서버 nginx와 챗봇 설정은 바꾸지 않는다(`CORS_ORIGINS`에 http·https 둘 다 있음, 프런트는 `/api` 상대 경로).
- 순서:
  1. 받은 파일에서 PEM 세 가지(개인 키·도메인 인증서·체인)를 준비한다.
  2. NCP Certificate Manager에 외부 인증서로 등록한다.
  3. ALB에 HTTPS 443 리스너를 추가한다. 대상 그룹은 기존 80 리스너와 같은 것으로 한다.
  4. `https://chatbot.yest.co.kr/admin`, `/api/health`로 확인한다.
  5. 마지막에 80을 443으로 넘긴다(MAIP 담당과 시점을 맞춘다).
- ALB를 MAIP와 함께 쓰므로, 인증서가 `*.yest.co.kr`이 아니면 MAIP 주소를 어떻게 덮을지 MAIP 담당과 먼저 정한다.
- 개인 키와 `.pfx` 비밀번호는 저장소(`deploy/` 포함)·문서에 넣지 않는다. 만료일을 기록해 두고, 갱신 때는 Certificate Manager에 새로 등록한 뒤 리스너 인증서만 바꾼다.
