"""ManufacturingAIPlatform Django 설정.

비밀값과 환경 의존 값은 모두 환경변수로 주입한다. 개발 편의를 위해
프로젝트 루트의 `.env`를 읽지만, `.env`는 저장소에 커밋하지 않는다.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from configurations.env import env, env_bool, env_int, env_list, load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# --------------------------------------------------------------------------
# 기본
# --------------------------------------------------------------------------
SECRET_KEY = env('SECRET_KEY', 'dev-insecure-do-not-use-in-production')
# `/api/v1/health` 의 version. 환경이 아니라 배포물의 성질이므로 .env 로 빼지 않는다.
APP_VERSION = '1.1.0'
# 개발 PC 는 .env 에 DEBUG=True. 빠뜨린 운영이 DEBUG 로 뜨지 않게 기본은 False
DEBUG = env_bool('DEBUG', False)
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', '*' if DEBUG else '')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

if not DEBUG:
    if '*' in ALLOWED_HOSTS or not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            'DEBUG=False에서는 ALLOWED_HOSTS를 실제 호스트명으로 지정해야 한다.'
        )
    if SECRET_KEY.startswith('dev-insecure'):
        raise ImproperlyConfigured('DEBUG=False에서는 SECRET_KEY 환경변수가 필요하다.')

SITE_NAME = 'Manufacturing AI Platform'

INSTALLED_APPS = [
    'app',
    'domain',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'configurations.middleware.request_id.RequestIdMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'configurations.middleware.response.RemoveCriticalResponseHeader',
]

ROOT_URLCONF = 'configurations.urls'
WSGI_APPLICATION = 'configurations.wsgi.application'

# TEMPLATES는 DEBUG 여부와 무관하게 항상 정의한다.
# (원본 MES는 `if DEBUG:` 블록 안에 두어 DEBUG=False에서 부팅이 불가능했다 — 부채 D3)
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
        },
    },
]

# --------------------------------------------------------------------------
# 데이터베이스
# --------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': env('DB_HOST', '127.0.0.1'),
        'PORT': env_int('DB_PORT', 5432),
        'NAME': env('DB_NAME', 'yest'),
        'USER': env('DB_USER', 'yest'),
        'PASSWORD': env('DB_PASSWORD', ''),
        'CONN_MAX_AGE': env_int('DB_CONN_MAX_AGE', 60),
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'application_name': env('DB_APPLICATION_NAME', 'manufacturing_ai_platform'),
            'options': '-c search_path=' + env('DB_SEARCH_PATH', 'public'),
        },
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 원본 MES 의 raw SQL 서비스가 분기용으로 참조한다. PostgreSQL 전용이며,
# 일부 서비스에 남은 MSSQL 분기는 타지 않는다.
DBMS = 'POSTGRESQL'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --------------------------------------------------------------------------
# 지역화 — USE_TZ=False 유지(원본 MES의 raw SQL 101개 모듈이 naive datetime 전제)
# --------------------------------------------------------------------------
LANGUAGE_CODE = 'ko-KR'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = False

# --------------------------------------------------------------------------
# 정적 파일 / 저장소
# --------------------------------------------------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = str(BASE_DIR / 'static')
# 템플릿은 {% static %} 으로 싣는다. 운영(DEBUG=False)의 collectstatic 이 해시 이름·gzip 을 만들고
# whitenoise 가 해시 이름 파일을 10년 immutable 로 낸다 — 손으로 ?v= 를 올릴 필요가 없다.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'configurations.storage.StaticStorage'},
}
# 해시가 없는 파일(JS 가 문자열로 만든 경로 — 테마 CSS)만 이 값을 받는다.
WHITENOISE_MAX_AGE = 3600

# 업로드 원본·파생 파일의 단일 루트. nginx에 노출하지 않고 권한 확인 View로만 제공한다.
STORAGE_ROOT = Path(env('STORAGE_ROOT', str(BASE_DIR / 'storage')))

# 시스템 로그. 비우면 저장소 아래 logs/. 날마다 app-YYYY-MM-DD.log 로 나뉘고
# 보존 기간이 지난 파일은 지운다(0 이면 지우지 않는다). configurations/log.py
LOG_DIR = Path(env('LOG_DIR', str(STORAGE_ROOT / 'logs')))
LOG_RETENTION_DAYS = env_int('LOG_RETENTION_DAYS', 30)

# 큰 파일(배포물·스냅샷 zip·이미지 원본) 전송을 nginx 에 넘긴다(X-Accel-Redirect). 운영 True.
# nginx 에 internal location 이 있어야 한다 — 없이 켜면 파일이 빈 응답이 된다.
FILE_ACCEL_REDIRECT = env_bool('FILE_ACCEL_REDIRECT', False)

# 로그인 실패 횟수(domain/services/login_throttle.py)를 gunicorn 워커끼리 함께 센다.
# ponytail: 파일 캐시라 incr 가 프로세스 간 원자적이지 않다(동시 실패 몇 번이 한 번으로 셀 수 있다).
# 웹 서버를 여러 대로 늘리면 Redis 등 공유 캐시로 바꾼다.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': str(STORAGE_ROOT / 'cache'),
    }
}

# RUNNING 으로 이만큼(초) 지난 작업은 워커가 죽은 것으로 보고 다시 대기열에 넣는다.
# 가장 오래 걸리는 Export 보다 길어야 한다 — 짧으면 정상 작업이 두 번 돈다. domain/services/data/job.py
WORKER_STALE_SECONDS = env_int('WORKER_STALE_SECONDS', 3600)

# Wezard(학습·추론 서버) — 검사 추론·모델 목록을 부른다(docs/Wezard/integration-protocol.md). 둘 중 하나라도
# 비면 추론은 Stub 이다(검사는 RECEIVED + GPU_INFERENCE_NOT_CONFIGURED). 키는 로그·오류에 넣지 않는다.
WEZARD_BASE_URL = env('WEZARD_BASE_URL', '')
WEZARD_API_KEY = env('WEZARD_API_KEY', '')

# 상단 바 We.RAG 로고가 새 탭으로 여는 주소. 비면 로고를 보이지 않는다. http(s) 만 받는다(app/views/__init__.py home)
WERAG_URL = env('WERAG_URL', '')

# `/api/v1` 로 내려주는 배포물. licenses/(LGPL 대응 소스)·client/(Client 배포 zip).
# `app/static/` 아래 두지 않는다 — collectstatic 이 1GB 를 STATIC_ROOT 로 복사하고
# whitenoise 가 `/static/distribution/...` 으로 같은 파일을 두 번째 경로로 내보낸다.
DISTRIBUTION_ROOT = Path(env('DISTRIBUTION_ROOT', str(BASE_DIR / 'distribution')))

FILE_UPLOAD_PATH = str(STORAGE_ROOT / 'upload') + os.sep
FILE_TEMP_UPLOAD_PATH = str(STORAGE_ROOT / 'upload_temp') + os.sep
MES_FORM_PATH = str(STORAGE_ROOT / 'form') + os.sep

# 데이터 관리 도메인의 FileField/ImageField 가 저장되는 곳.
# MEDIA_URL 은 두지 않는다 — 파일은 권한을 확인하는 View 로만 제공하고
# nginx 에 노출하지 않는다(DEC-019).
MEDIA_ROOT = str(STORAGE_ROOT / 'media')
os.makedirs(MEDIA_ROOT, exist_ok=True)

FILE_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 35 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640

for _folder in (FILE_UPLOAD_PATH, FILE_TEMP_UPLOAD_PATH, MES_FORM_PATH):
    os.makedirs(_folder, exist_ok=True)

# --------------------------------------------------------------------------
# 세션 / 보안
# --------------------------------------------------------------------------
SESSION_COOKIE_NAME = 'map'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
# 유휴 8시간이면 끝난다(한 근무조). 브라우저를 닫아도 끝난다(account.py set_expiry(0)).
# ponytail: 요청마다 세션 행을 다시 쓴다. 쓰기가 부담되면 N 분마다만 저장하는 미들웨어로 바꾼다.
SESSION_COOKIE_AGE = 8 * 3600
SESSION_SAVE_EVERY_REQUEST = True

X_FRAME_OPTIONS = 'SAMEORIGIN'  # iframe 탭 셸이 전제다. DENY로 바꾸면 화면이 뜨지 않는다.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

HTTPS_ENABLED = env_bool('HTTPS_ENABLED', False)
SECURE_SSL_REDIRECT = HTTPS_ENABLED
SESSION_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
SECURE_HSTS_SECONDS = 31536000 if HTTPS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS_ENABLED
SECURE_HSTS_PRELOAD = HTTPS_ENABLED

# --------------------------------------------------------------------------
# 애플리케이션 설정
# --------------------------------------------------------------------------
# API 인가 훅 동작 모드 — off | warn | enforce
#
# enforce: 매핑에 없는 `<task>/<view>` 는 403이 된다.
# verify_permission_map.py 가 PASS(뷰 ↔ 매핑 1:1)한 것을 확인하고 전환했다.
# 화면을 추가할 때 매핑 등록을 빠뜨리면 즉시 403으로 드러난다 — 의도한 동작이다.
# 문제가 생기면 환경변수로 즉시 warn 으로 되돌릴 수 있다.
API_AUTHZ_MODE = env('API_AUTHZ_MODE', 'enforce')

# 테넌트 RLS
TENANT_RLS_ENABLED = env_bool('TENANT_RLS_ENABLED', True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            # 웹 워커 여러 개와 run_worker 가 한 파일에 쓴다. process 로 가른다.
            'format': '[{asctime}] {levelname} {process} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
        'file': {'()': 'configurations.log.DailyFileHandler', 'formatter': 'standard',
                 'directory': str(LOG_DIR), 'retention_days': LOG_RETENTION_DAYS},
    },
    'root': {'handlers': ['console', 'file'], 'level': env('LOG_LEVEL', 'INFO')},
}
