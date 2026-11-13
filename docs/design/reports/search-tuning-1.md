# 검색 개선 1차 — SOP 질의 토큰·리랭커 입력 (2026-11-10)

관련 ID: R4-1(품번·규격 정확 검색), R4-2, MOD-08(검색 엔진), F-4-01, F-4-02, API-05
브랜치: `refactor-1`(작업 폴더, 커밋 안 함)

## 1. 요약

검토(질의 → 형태소 분석 → 검색 → 리랭킹)에서 찾은 문제 중 1~3번을 고쳤다.

| # | 문제 | 수정 |
|---|---|---|
| ① | 질의의 법령 표기 변환이 SOP 표현을 망가뜨림: "3호기"→"제3호기", "2조립"→"제2조립"(법령 질의로 분류), "제12조"→"제1제2조"(숫자 중간 매칭) | 뒤가 끝·기호·조사일 때만 변환. 설정 `QUERY_LAW_NOTATION_NORMALIZE`(코드 기본 true)로 변환·법령 조문 추출을 끌 수 있음 |
| ② | 모델 코드·규격이 BM25에서 사라짐: "XG-500A"→`XG`만, "M6"·"12N·m" 숫자 소실. Qdrant BM25(FastEmbed)도 다시 소문자화·비단어 문자 분리 | 토큰 정책 v2: 코드(영문+숫자)·규격(수치+단위)·N호기를 한 토큰으로 두고 Qdrant에서도 깨지지 않는 표준형(`xg500a`+조각 `xg`·`500a`, `12nm`, `1_5mm`)으로 적재·질의 양쪽 적용. `KIWI_BM25_ENCODER_VERSION=kiwi-bm25-v2`로 켬(코드 기본 v1 = 기존 동작) |
| ③ | 리랭커 입력 `[문서명]`이 늘 빠짐(payload에 `filename` 없음, `original_filename`만 있음). 엑셀은 위치 정보도 없음 | `original_filename` 우선, 엑셀은 `[시트] 시트명` 추가 |

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `adrag_backend/app/core/config.py` | `query_law_notation_normalize` 추가, 인코더 버전 설명 |
| `adrag_backend/app/core/container.py` | 전처리기에 설정 전달 |
| `adrag_backend/app/graphs/preprocessing/query_preprocessor.py` | 법령 표기 패턴 경계 수정, 설정으로 끄기 |
| `adrag_backend/app/utils/kiwi_tokenizer.py` | 토큰 정책 v1/v2, 정책별 Kiwi 인스턴스, 코드·규격 표준형, `tokenize_*`에 `policy` 인자 |
| `adrag_backend/app/clients/kiwi_bm25_encoder.py` | 인코더 버전 → 토큰 정책 선택(적재·질의 동일) |
| `adrag_backend/app/graphs/nodes/rerank.py` | 리랭커 입력 문서명·시트명 |
| `adrag_backend/scripts/rebuild_kiwi_bm25.py` | 신규: 기존 포인트 BM25 벡터 재계산 + 버전 프로필 갱신(기본 dry-run) |
| `adrag_backend/tests/test_search_tuning_sop_tokens.py` | 신규 테스트 29개 |
| `.env.example` | `QUERY_LAW_NOTATION_NORMALIZE`(주석, 기본 true), `KIWI_BM25_ENCODER_VERSION` 안내 |

구현 중 확인한 사실(코드 주석에도 남김)
- Kiwi `add_re_word`는 같은 위치에서 겹치면 **나중에 등록한 패턴**이 이긴다(실측). 기존 주석 "법령 조문 패턴을 먼저 등록"과 반대. v2 패턴은 맨 뒤에 코드 < N호기 < 규격 순서로 등록.
- 규격을 NNP로 등록하면 뒤 낱말 분석이 바뀐다("220V 전원" → `전/MM 원/NNB`). SL로 등록.
- 계획에서 `extract_search_terms`에도 v2를 적용한다고 했으나, BM25 질의는 인코더에서 다시 토큰화되므로 필요 없어 바꾸지 않았다(메타데이터 soft boost 키워드는 기존 그대로).

## 3. 완료 기준 근거

| 항목 | 결과 |
|---|---|
| 신규 테스트 | `tests/test_search_tuning_sop_tokens.py` **29 passed** |
| 관련 기존 테스트(kiwi·사전·토큰 정책·검색 채널·평가 Kiwi) | **82 passed** (단독 묶음 실행) |
| 전체(`-m "not e2e and not voice" --continue-on-collection-errors`) | **488 passed / 13 failed / 26 skipped / 수집 오류 9** (12분) |
| 수집 오류 6건 추가분 단독 실행 | `test_document_model_name`·`test_document_version_restore`·`test_document_versions`·`test_excel_ingest_routing`·`test_multi_document_upload`·`test_original_file_path` → **66 passed / 1 failed**(기존 실패 `test_multi_document_upload`) |
| 재계산 스크립트 dry-run(dev 컨테이너) | 정상. 현재 v1이라 재계산 대상 0, 프로필 갱신 0 |
| 재계산 `--apply`(임시 컬렉션 생성 → 검증 → 삭제) | 3포인트 갱신, payload 버전 v2, 재실행 시 0건(멱등). 재계산 전 v2 질의 "XG500A 체결"은 다른 모델 청크가 1위 → 재계산 후 정답 1위. "12N·m"·"3호기"도 정답 1위 |

전체 테스트 판정
- 실패 13건 = refactor-1 보고서의 기존 목록(기존 11 + `test_database_migrations` HEAD 3건)과 같음. 단 `test_multi_document_upload`는 이번에 수집 오류 쪽으로 빠졌다.
- 수집 오류 +6건은 이번 변경과 무관: 작업 폴더에 이미 수정되어 있던 `app/routes/ingest.py:90`이 import 시점에 `get_settings().sheet_preview_max_concurrency`를 읽는데, 앞선 테스트의 `SimpleNamespace` 설정 stub에 그 값이 없어 순서 의존으로 실패. 단독 실행 시 통과(위 표).

### 3.1 개발 데이터 전후 비교 (읽기 전용, 집계만)

개발 Qdrant의 SOP 엑셀 포인트(AIE_C2 486, AIE_NEOCON C2 243) 본문으로 로컬 BM25(k1=1.2, b=0.5, FastEmbed 토크나이저 흉내)를 v1·v2로 만들어 비교. 컬렉션 데이터는 바꾸지 않음.

코드·규격 질의(본문의 코드/규격 1개 + 같은 청크 명사 1개, 150건, 정답 = 두 단어를 모두 포함한 청크)

| 컬렉션 | 정책 | Hit@1 | Hit@10 | MRR@10 |
|---|---|---:|---:|---:|
| AIE_C2 | v1 | 0.687 | 0.773 | 0.706 |
| AIE_C2 | v2 | **0.973** | **0.980** | **0.974** |
| AIE_NEOCON C2 | v1 | 0.727 | 0.793 | 0.748 |
| AIE_NEOCON C2 | v2 | **0.973** | **0.980** | **0.976** |

일반 한국어 질의(명사 2개, 150건): 두 컬렉션 모두 v1 = v2(Hit@10 1.000 / 0.987) → 회귀 없음.

한계: 질의를 v2와 같은 정규식으로 뽑은 합성 질의라 v2에 유리하다. Dense 채널·RRF·리랭커를 거친 최종 순위가 아니다. SOP 골든셋으로 다시 확인해야 한다.

### 3.2 ③ 리랭커 점수 변화 (사내 리랭커 bge-reranker-v2-m3)

질의 40건 × 후보 20개, 수정 전(문서명·시트 없음)/후 비교.

| 컬렉션 | 최고점 평균 전→후 | 최고점 중앙값 전→후 | 임계값(0.25) 통과 수 평균 전→후 |
|---|---|---|---|
| AIE_C2 | 0.757 → 0.717 | 0.861 → 0.806 | 14.03 → 13.82 |
| AIE_NEOCON C2 | 0.692 → 0.640 | 0.757 → 0.691 | 9.00 → 9.68 |

점수가 0.04~0.05 낮아지지만 임계값 통과 수는 거의 같아 `RELEVANCE_THRESHOLD` 조정은 지금 필요 없다고 판단. 정확도 영향은 합성 질의가 너무 일반적이라(원 청크 1위 비율 전후 모두 ≈0) 판단 불가 → 골든셋 필요.

### 3.3 dev 적용 (2026-11-11, 사용자 요청)

- dev `.env`에 `KIWI_BM25_ENCODER_VERSION=kiwi-bm25-v2` 추가(`QUERY_LAW_NOTATION_NORMALIZE`는 결정 대기라 그대로 = true).
- 컨테이너 kiwipiepy 0.24.1(로컬 0.23.2)에서도 신규 테스트 29 passed 확인 후 진행.
- 재계산(컨테이너 안, 실행 중 컨테이너에 v2 값을 넘겨 실행): `AIE_NEOCON C2` 243, `AIE_산업안전보건법` 308포인트 갱신, 실패 0, 버전 프로필 4건 갱신 → backend 재생성(healthy, 로그 "정책 v2"). 재실행 dry-run 0건, 모든 버전 프로필 = v2.
- `AIE_C2`(Qdrant에만 있고 `tb_collections`에 없음)는 대상 아님 → 원래 검색 대상이 아니다.

실제 dev Qdrant 검색(`AIE_NEOCON C2`, 같은 질의 세트, 운영 코드의 `search_kiwi_bm25`·`search_hybrid` 직접 호출, 리랭커 제외)

| 질의 | 지표 | 적용 전(v1) | 적용 후(v2) |
|---|---|---:|---:|
| 코드·규격 80건 | BM25 Hit@1 / Hit@10 | 0.650 / 0.787 | **0.863 / 0.925** |
| 코드·규격 80건 | Hybrid Hit@1 / Hit@10 | 0.625 / 0.762 | 0.637 / **0.850** |
| 일반 명사 80건 | BM25 Hit@1 / Hit@10 | 0.912 / 0.938 | 0.912 / 0.938 |
| 일반 명사 80건 | Hybrid Hit@1 / Hit@10 | 0.950 / 0.975 | 0.950 / 0.975 |

해석: 일반 질의는 변화 없음(회귀 없음). 코드 질의는 BM25가 크게 좋아졌고 hybrid Hit@10도 +0.09. hybrid Hit@1은 거의 그대로 → Dense 쪽 순위가 RRF에서 1위를 정하는 경우가 많다. RRF 가중치(검토 4장, 질의 유형이 SOP에 안 맞음)와 리랭커가 다음 개선 대상.

되돌리기(dev): `.env`에서 해당 줄 삭제(백업은 작업 세션 임시 폴더) → `docker exec -e KIWI_BM25_ENCODER_VERSION=kiwi-bm25-v1 rag-backend-dev python scripts/rebuild_kiwi_bm25.py --apply` → backend 재생성.

## 4. 마이그레이션 여부

- DB 스키마 변경 없음(Alembic revision 없음).
- **데이터 재계산 필요(v2를 켤 때만)**: `KIWI_BM25_ENCODER_VERSION`은 임베딩 프로필 해시에 들어가므로 바꾸면 문서·질의 토큰이 어긋나고 이전 버전 복원(UI-12)이 막힌다. 순서:
  1. `.env`에 `KIWI_BM25_ENCODER_VERSION=kiwi-bm25-v2`
  2. `python scripts/rebuild_kiwi_bm25.py`(dry-run으로 대상 확인) → `--apply`
  3. 백엔드 재기동
  - 스크립트는 Dense를 건드리지 않고, 실패가 1건이라도 있으면 버전 프로필을 바꾸지 않는다. 프로필은 옛 프로필과 인코더 버전 외 설정이 같을 때만 갱신(다른 설정이 바뀐 버전은 복원 차단 유지).
  - 재계산과 재기동 사이 짧은 시간 동안 BM25 점수가 어긋난다(Dense는 정상). 운영은 사용 적은 시간에.
- dev는 11-11 v2 적용 완료(3.3절). 운영 `.env`는 바꾸지 않았다(v1). 법령 정규화는 dev·운영 모두 기본 true 그대로.

## 5. 되돌리는 방법

- 설정: `KIWI_BM25_ENCODER_VERSION=kiwi-bm25-v1`로 되돌린 뒤 `rebuild_kiwi_bm25.py --apply`(v1로 재계산) → 재기동. `QUERY_LAW_NOTATION_NORMALIZE=true`.
- 코드: 위 2절 파일의 `2026.11.10(sooyeon.choi)` 주석 지점 되돌림, 신규 파일 2개 삭제. ①의 경계 수정과 ③은 설정 없이 바뀐 동작(버그 수정)이다.

## 6. 남은 이슈·결정 필요

1. **(11-11 결정: 법령 문서도 사용 → `QUERY_LAW_NOTATION_NORMALIZE` 기본 true 유지)** 개발 환경에 법령 컬렉션 `AIE_산업안전보건법`(308포인트)이 있다. `QUERY_LAW_NOTATION_NORMALIZE=false`로 하면 이 컬렉션에서 "1조" 같은 질의가 법령 질의로 분류되지 않는다. 법령 컬렉션을 계속 쓸지에 따라 dev `.env` 값을 정해야 한다(운영은 SOP 전용이면 false 권장).
2. v2 적용(dev·운영)은 사용자가 위 4절 순서로 실행. dev에서 먼저 적용 후 실제 질의로 확인 권장.
3. `AIE_C2` 컬렉션은 Qdrant에만 있고 `tb_collections`에 없어 스크립트 대상에서 빠진다(고아 컬렉션 여부 확인 필요).
4. 이번 범위 밖(검토 보고 4장): 사전 YAML에 SOP 용어(R2-4·UI-19와 연계), 질의 유형 분류·RRF 가중치 SOP화, 재작성 프롬프트에 "모델명·품번·수치 유지", 임베딩 질의 지시문, 모델명 payload 필드(N-3), 문서당 청크 2개 제한·인접 단계 확장, SOP 골든셋, Qwen3-Reranker-0.6B 비교.
5. 테스트 기반 정리(이번 변경과 무관): `app/routes/ingest.py:90` import 시점 설정 읽기 때문에 수집 오류 6건 추가. 지연 생성으로 바꾸거나 stub에 값 추가 필요.

## 7. 요구사항 정의서·기능 목록에 반영할 것

- R4-1 완료 기준에 "하이픈·가운뎃점 표기 차이(XG-500A/XG500A, 12N·m/12Nm)에도 같은 품번·규격 청크를 찾는다" 추가 제안.
- 설정 목록에 `QUERY_LAW_NOTATION_NORMALIZE`, `KIWI_BM25_ENCODER_VERSION` 값 `kiwi-bm25-v2` 의미 추가.
