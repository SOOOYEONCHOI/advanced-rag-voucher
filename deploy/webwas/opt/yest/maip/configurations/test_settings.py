"""테스트 전용 설정.

`manage.py test --settings=configurations.test_settings` 로만 실행한다.
이 설정을 빼면 원격 PostgreSQL에 테스트 DB가 생성된다.
"""
import tempfile
from pathlib import Path

from configurations.settings import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost']
SECRET_KEY = 'test-only-secret-key'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

STORAGE_ROOT = Path(tempfile.mkdtemp(prefix='map-test-'))
FILE_UPLOAD_PATH = str(STORAGE_ROOT / 'upload')
FILE_TEMP_UPLOAD_PATH = str(STORAGE_ROOT / 'upload_temp')
MES_FORM_PATH = str(STORAGE_ROOT / 'form')
# settings.py 가 STORAGE_ROOT 로부터 계산해 둔 값이다. 위에서 STORAGE_ROOT 를
# 바꿨어도 이미 계산된 뒤라 다시 지정해야 한다 — 빼면 테스트가 실제
# storage/media/ 에 이미지와 썸네일을 쌓는다.
MEDIA_ROOT = str(STORAGE_ROOT / 'media')
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
# 테스트는 collectstatic 없이 템플릿을 그린다 — 해시 manifest 를 쓰지 않는다.
STORAGES = {**STORAGES, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}

TENANT_RLS_ENABLED = False
API_AUTHZ_MODE = 'enforce'
# .env 의 Wezard 주소로 테스트가 실제 요청을 보내지 않게 비운다(추론은 Stub).
WEZARD_BASE_URL = ''
WEZARD_API_KEY = ''
# .env 의 We.RAG 주소가 화면 테스트에 섞이지 않게 비운다.
WERAG_URL = ''

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'null': {'class': 'logging.NullHandler'}},
           'root': {'handlers': ['null'], 'level': 'CRITICAL'}}
