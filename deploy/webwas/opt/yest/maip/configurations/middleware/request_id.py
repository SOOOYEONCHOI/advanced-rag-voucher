"""애플리케이션·감사 로그용 요청 상관관계 미들웨어.

받은 `X-Request-ID` 가 1~64자 `[A-Za-z0-9._-]` 일 때만 그대로 쓰고, 아니면 새로 만든다.
검사 없이 쓰면 긴 값·제어 문자가 로그와 감사 기록에 그대로 들어간다. 형식이 틀렸다고 요청을 거절하지는 않는다.
"""
import re
import uuid

VALID_REQUEST_ID = re.compile(r'[A-Za-z0-9._-]{1,64}')


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        received = request.headers.get('X-Request-ID', '')
        request.request_id = received if VALID_REQUEST_ID.fullmatch(received) else uuid.uuid4().hex
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        return response
