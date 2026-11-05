"""
공유 httpx.AsyncClient 모듈.

2026.07.16(sooyeon.choi) 추가 - HTTP 커넥션 풀링 (리팩토링 B6)
  기존: 각 클라이언트가 요청마다 httpx.AsyncClient를 생성 → keep-alive 없이
        매 호출 TCP/TLS 핸드셰이크 발생 (질의 1건당 임베딩+리랭커+LLM 3~5회)
  변경: 프로세스 전역 공유 AsyncClient를 재사용하고,
        타임아웃은 호출부에서 요청 단위로 지정한다.
  종료: main.py lifespan 종료 시 close_shared_async_client() 호출.
"""

import httpx

_shared_client: httpx.AsyncClient | None = None


def get_shared_async_client() -> httpx.AsyncClient:
    """프로세스 전역 공유 AsyncClient를 반환한다 (지연 생성).

    타임아웃 기본값은 안전망(120s)이며, 각 호출부에서 요청 단위
    timeout 인자로 재정의하는 것을 전제로 한다.
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )
    return _shared_client


async def close_shared_async_client() -> None:
    """공유 AsyncClient를 종료한다 (앱 shutdown 시 1회 호출)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None
