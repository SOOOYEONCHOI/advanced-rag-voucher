"""정적 파일 저장소 — 해시 이름(긴 캐시) + gzip. 운영의 collectstatic 이 만든다.

벤더 CSS 가 가리키는 파일 중 배포본에 없는 것(쓰지 않는 글꼴·이미지)이 있어 엄격 모드면 collectstatic 이 멈춘다.
없는 파일은 해시하지 않고 원래 이름으로 둔다 — 그 참조는 지금도 404 다.
"""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name
