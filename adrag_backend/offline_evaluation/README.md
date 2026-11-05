# 골든 데이터셋은 자동 생성 → 사람이 검수 → 검색 취약 케이스 수동 추가 방식이 좋습니다. 이 프로젝트에는 이미 반자동 생성기가 있습니다.

  1. 먼저 후보셋 생성
  Qdrant 컬렉션에서 chunk를 샘플링하고, Ollama로 질문/답변 후보를 만듭니다.

  cd adrag_backend

  python -m offline_evaluation generate `
    --collection <qdrant_collection_name> `
    --sample 30 `
    --per-chunk 2 `
    --out offline_evaluation/data/candidates `
    --ollama-url http://localhost:11434 `
    --model qwen3:14b

  그러면 대략 offline_evaluation/data/candidates/candidates_<collection>_<timestamp>.json 파일이 생깁니다.

  2. 후보셋은 그대로 쓰지 말고 검수
  자동 생성 결과는 “후보”입니다. 반드시 사람이 확인해야 합니다.

  검수 기준:

  - 질문이 실제 사용자가 물어볼 만한가
  - expected_answer가 해당 chunk 근거만으로 답 가능한가
  - expected_evidence[0].chunk_id가 진짜 정답 chunk인가
  - 질문이 너무 chunk 문장 그대로 복붙되어 있지 않은가
  - 검색 개선 대상인 조문/약어/복합명사/띄어쓰기 변형이 충분히 들어갔는가
  - split을 test 또는 tune으로 바꿨는가

  3. 검색기 개선용 수동 케이스를 꼭 추가
  이번 작업은 일반 QA보다 한국어 검색 취약점 검증이 핵심이라 자동 생성만으로는 부족합니다. 아래 유형을 직접 넣는 게 좋습니다.

  - 조문: 제7조의3, 제10조제2항
  - 별표/부칙: 별표 3, 부칙 제3조
  - 약어: PSM, MSDS, LOTO, TBM
  - 복합명사: 공정안전관리, 위험성평가, 안전보건관리책임자
  - 띄어쓰기 변형: 위험성 평가 기준은?
  - 기능어 포함: 공정안전관리 기준 알려줘
  - near-miss: 비슷한 문서가 많은데 특정 조문을 찾아야 하는 질문
  - unanswerable: 문서에 없는 질문

  골든 레코드 예시
  실제 chunk_id, document_id, collection_name은 Qdrant payload 기준으로 채워야 합니다.

  [
    {
      "id": "ko_search_0001",
      "collection_name": "documents",
      "user_id": "eval_user",
      "question": "제7조의3에 따른 안전관리자 선임 기준은?",
      "expected_answer": "해당 조문에서 정한 안전관리자 선임 기준을 답변한다.",
      "expected_evidence": [
        {
          "document_id": "actual-document-id",
          "chunk_id": "actual-chunk-id",
          "filename": "산업안전보건법.pdf",
          "page_number": 12,
          "evidence_text": "정답 근거가 되는 chunk 원문 일부"
        }
      ],
      "expected_behavior": "answer",
      "question_type": "factual",
      "difficulty": "normal",
      "split": "test",
      "tags": ["legal_reference", "korean_search", "article_pattern"],
      "notes": "제7조의3 패턴 보존 검증"
    }
  ]

  4. tune/test를 분리
  추천은 다음처럼 나누는 겁니다.

  - tune: 가중치, BM25 파라미터, stopword 조정용
  - test: 최종 before/after 비교용, 수정 중에는 건드리지 않음

  처음에는 이렇게 시작하면 충분합니다.

  - tune: 20~30개
  - test: 20~30개
  - 그중 검색 취약 케이스를 최소 절반 이상 포함

  5. 저장 위치
  검수 완료본은 예를 들어 이렇게 두면 됩니다.

  adrag_backend/offline_evaluation/data/test/korean_search_golden.json
  adrag_backend/offline_evaluation/data/tune/korean_search_tune.json

  6. baseline 실행
  검수 완료 후 변경 전 결과를 먼저 저장합니다.

  cd adrag_backend

  python -m offline_evaluation run `
    --golden offline_evaluation/data/test/korean_search_golden.json `
    --split test `
    --top-k 10 `
    --no-llm-judge `
    --out offline_evaluation/results/before_korean_search

  핵심은 expected_evidence.chunk_id입니다. 평가 코드는 답변 문자열보다 이 chunk_id가 retrieve/rerank 결과에 들어왔는지를 기준으로 Recall@10,
  Hit@5, nDCG@5를 계산합니다.
