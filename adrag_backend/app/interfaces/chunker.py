"""
청커(청킹 전략) 인터페이스.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/parsers/chunkers/ (law/manual/general 분기 함수들)
Semantic/Recursive 등 신규 청킹 전략(SFR-019)은 이 계약(docs, config를 받아
청크 리스트 반환)에 맞는 callable을 작성해 processor의 청커 레지스트리
(register_chunker)에 등록하면 문서 유형 라우팅에 편입된다.
"""

from typing import Any, Callable, List

# 청커 계약: (LCDocument 리스트, ChunkingConfig) → 청크(LCDocument) 리스트
# 함수형 구현이 대부분이므로 Protocol 클래스 대신 Callable 별칭으로 정의한다.
Chunker = Callable[[List[Any], Any], List[Any]]
