"""RAG 평가 자동화 서비스 패키지.

reference 평가 플랫폼(DB·API·백그라운드)을 이식하되, 기존 CLI 평가 패키지
(adrag_backend/offline_evaluation)의 평가 축(가드레일·threshold-fallback·거절·한국어
세그먼트)을 evaluator 재사용으로 병합한다. (설계서: docs/eval_platform_design.md)

격리 원칙: metrics/dataset/runner는 ports.py의 Protocol에만 의존하고,
기존 app.graphs/app.clients 직접 import는 adapters/ 에서만 허용한다.
"""
