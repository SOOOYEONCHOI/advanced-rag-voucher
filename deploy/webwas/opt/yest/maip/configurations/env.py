"""환경변수 로더.

프로젝트 루트의 `.env`를 읽어 `os.environ`에 채운다. 이미 설정된 실제
환경변수가 우선하므로, 운영에서는 `.env` 없이 환경변수만으로 동작한다.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

_UNSET = object()


def load_dotenv(path):
    """`.env` 파일을 읽어 os.environ의 빈 항목만 채운다."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (FileNotFoundError, NotADirectoryError):
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(key, default=_UNSET):
    """환경변수를 읽는다. default가 없으면 미설정 시 부팅을 거부한다."""
    value = os.environ.get(key)
    if value is None or value == '':
        if default is _UNSET:
            raise ImproperlyConfigured(f'필수 환경변수가 설정되지 않았다: {key}')
        return default
    return value


def env_bool(key, default=False):
    return str(env(key, str(default))).strip().lower() in ('1', 'true', 'yes', 'on')


def env_int(key, default):
    return int(env(key, str(default)))


def env_list(key, default=''):
    """쉼표로 구분된 목록을 읽는다."""
    raw = env(key, default)
    return [item.strip() for item in raw.split(',') if item.strip()]
