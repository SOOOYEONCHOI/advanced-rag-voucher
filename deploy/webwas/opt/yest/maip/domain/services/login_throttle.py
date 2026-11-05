"""로그인 실패 제한.

제한이 없으면 비밀번호를 끝없이 대입할 수 있다. 실패 한 번마다 PBKDF2(약 0.1초)를
계산하므로 로그인 반복 호출만으로 워커 하나의 CPU를 태울 수도 있다.

잠금 단위는 **(아이디, 접속 주소)** 다. 아이디만으로 잠그면 누구나 틀린 비밀번호
5번으로 진짜 관리자의 로그인을 막을 수 있다.

실패 횟수는 Django 캐시에 쌓는다. 운영 `CACHES` 는 파일 캐시라 같은 서버의 gunicorn
워커들이 함께 센다(LocMemCache 는 워커마다 따로 세어 워커 수만큼 더 시도할 수 있다).

접속 주소는 같은 호스트의 nginx(gunicorn 은 127.0.0.1 에만 붙는다)가 넣는 `X-Real-IP` 만 믿는다.
`X-Forwarded-For` 첫 값은 클라이언트가 정하는 값이라 바꿔 가며 무한 대입할 수 있었다.
"""
import time

from django.core.cache import cache

MAX_FAILURES = 5
LOCK_SECONDS = 300
WINDOW_SECONDS = 300


def _keys(username, address):
    ident = '{}|{}'.format((username or '').strip().lower(), address or '')
    return 'login:fail:' + ident, 'login:lock:' + ident


# 이 주소에서 온 요청만 프록시로 보고 X-Real-IP 를 믿는다.
TRUSTED_PROXIES = frozenset({'127.0.0.1', '::1'})


def client_address(request):
    """접속 주소. 같은 호스트의 nginx 를 거쳤으면 nginx 가 넣은 X-Real-IP, 아니면 REMOTE_ADDR."""
    remote = request.META.get('REMOTE_ADDR')
    if remote in TRUSTED_PROXIES:
        real = request.META.get('HTTP_X_REAL_IP', '').strip()
        if real:
            return real
    return remote


def seconds_locked(username, address):
    """잠겨 있으면 남은 초(올림), 아니면 None."""
    _, lock_key = _keys(username, address)
    unlock_at = cache.get(lock_key)
    if not unlock_at:
        return None
    remaining = unlock_at - time.time()
    if remaining <= 0:
        cache.delete(lock_key)
        return None
    return int(remaining) + 1


def record_failure(username, address):
    """실패를 세고, 한도를 넘으면 잠근다. 잠갔으면 True."""
    fail_key, lock_key = _keys(username, address)
    # add + incr: 키가 없을 때만 만들고, 있으면 원자적으로 증가시킨다.
    cache.add(fail_key, 0, WINDOW_SECONDS)
    try:
        count = cache.incr(fail_key)
    except ValueError:  # 윈도가 만료돼 키가 사라진 경우
        cache.set(fail_key, 1, WINDOW_SECONDS)
        count = 1

    if count >= MAX_FAILURES:
        cache.set(lock_key, time.time() + LOCK_SECONDS, LOCK_SECONDS)
        cache.delete(fail_key)
        return True
    return False


def clear(username, address):
    """로그인에 성공하면 기록을 지운다."""
    cache.delete_many(list(_keys(username, address)))
