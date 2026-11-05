"""파일 제공. 데이터 관리의 보호된 미디어는 `media.py` 가 권한을 확인하고 내준다.

`sendfile()` 은 권한 확인이 끝난 파일을 응답으로 만든다. 운영(`FILE_ACCEL_REDIRECT=True`)에서는
nginx 의 internal location 으로 전송을 넘긴다(X-Accel-Redirect, Range 도 nginx 가 처리한다).
Django(gunicorn sync 워커)가 큰 파일을 흘려보내면 `--timeout` 을 넘겨 워커가 죽고 전송이 끊기고,
받는 동안 워커 하나를 붙잡는다.
"""
import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseNotModified
from django.utils.http import content_disposition_header, http_date
from django.views.static import was_modified_since

# nginx internal location 과 짝이다. 이 폴더 밖의 파일은 넘기지 않는다.
ACCEL_LOCATIONS = (('/_protected/media/', 'MEDIA_ROOT'),
                   ('/_protected/distribution/', 'DISTRIBUTION_ROOT'))


def sendfile(path, *, request=None, content_type=None, as_attachment=False, filename=None):
    """파일 응답. 파일이 없거나 허용 폴더 밖이면 FileNotFoundError.

    `request` 를 주면 조건부 응답을 한다 — 파일이 바뀌지 않았으면 304.
    이미지는 편집(회전·자르기)하면 같은 주소가 다른 파일이 되므로 매번 확인하게 한다(`no-cache`).
    """
    path = Path(path)
    if request is not None:
        mtime = path.stat().st_mtime   # 없으면 FileNotFoundError
        if not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'), int(mtime)):
            return HttpResponseNotModified()
        response = _send(path, content_type, as_attachment, filename)
        response['Last-Modified'] = http_date(mtime)
        response['Cache-Control'] = 'private, no-cache'
        return response
    return _send(path, content_type, as_attachment, filename)


def _send(path, content_type, as_attachment, filename):
    if not settings.FILE_ACCEL_REDIRECT:
        kwargs = {'filename': filename} if filename else {}
        return FileResponse(path.open('rb'), content_type=content_type, as_attachment=as_attachment, **kwargs)
    resolved = path.resolve()
    for prefix, setting_name in ACCEL_LOCATIONS:
        root = Path(getattr(settings, setting_name)).resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            response = HttpResponse(content_type=content_type or mimetypes.guess_type(path.name)[0]
                                    or 'application/octet-stream')
            response['X-Accel-Redirect'] = prefix + quote(resolved.relative_to(root).as_posix())
            response['Content-Disposition'] = content_disposition_header(as_attachment, filename or path.name)
            return response
    raise FileNotFoundError(path)
