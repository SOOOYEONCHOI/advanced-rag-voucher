"""데이터 관리 도메인의 보호된 미디어 제공.

`MEDIA_URL` 을 두지 않고(DEC-019) 모든 파일을 여기서 권한 확인 후 내보낸다.

URL 이름(`private-image` 등)은 바꾸지 않는다 — 데이터 관리 서비스가
`reverse()` 로 그대로 부른다.
"""
from django.http import Http404
from django.views import View

from app.views.files import sendfile
from domain.models.data import ExportJob, ImageAsset, InspectionItem
from domain.services.data.authorization import AuthorizationService
from domain.tenancy import current_tenant, tenant_atomic


def _file_response(file_field, request, **kwargs):
    """저장소에서 파일이 사라진 행을 500이 아니라 404로 답한다.

    DB 행은 남았는데 실제 파일이 없는 상태(백업 복원 누락, 수동 삭제)에서
    FileNotFoundError 가 그대로 올라가면 500이 되고, DEBUG 에서는 저장 경로까지
    응답에 실린다.
    """
    if not file_field:
        raise Http404('파일이 없습니다.')
    try:
        return sendfile(file_field.path, request=request, **kwargs)
    except FileNotFoundError as exc:
        raise Http404('파일을 찾을 수 없습니다.') from exc


class _PrivateMediaView(View):
    """로그인 + 검사항목 조회 권한을 확인하고 파일을 스트리밍한다."""

    http_method_names = ['get']

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_anonymous:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def _guard(self, request, item):
        # 다른 조직의 id는 없는 것처럼 404다 — 존재 여부를 흘리지 않는다.
        AuthorizationService.require(request, 'item.read', item=item)


class PrivateImageView(_PrivateMediaView):
    def get(self, request, image_id):
        with tenant_atomic():
            image = self._image(request, image_id)
            return _file_response(image.file, request, content_type=image.mime_type or None)

    def _image(self, request, image_id):
        try:
            image = (ImageAsset.objects.for_tenant(current_tenant())
                     .select_related('dataset__item').get(pk=image_id))
        except ImageAsset.DoesNotExist as exc:
            raise Http404 from exc
        self._guard(request, image.dataset.item)
        return image


class PrivateImageThumbnailView(PrivateImageView):
    def get(self, request, image_id):
        with tenant_atomic():
            image = self._image(request, image_id)
            return _file_response(image.thumbnail or image.file, request, content_type='image/webp')


class PrivateItemCoverView(_PrivateMediaView):
    def get(self, request, item_id):
        with tenant_atomic():
            try:
                item = InspectionItem.objects.for_tenant(current_tenant()).get(pk=item_id)
            except InspectionItem.DoesNotExist as exc:
                raise Http404 from exc
            self._guard(request, item)
            return _file_response(item.cover_image, request)


class PrivateOverlayView(_PrivateMediaView):
    """비전검사 Overlay 관리 화면의 미리보기. 클라이언트는 `/api/v1/overlays/<id>/image` 로 받는다."""

    def get(self, request, item_id):
        from domain.models.vision import VisionOverlay

        with tenant_atomic():
            try:
                item = InspectionItem.objects.for_tenant(current_tenant()).get(pk=item_id)
                overlay = VisionOverlay.objects.get(item=item)
            except (InspectionItem.DoesNotExist, VisionOverlay.DoesNotExist) as exc:
                raise Http404 from exc
            self._guard(request, item)
            return _file_response(overlay.image, request)


class PrivateExportView(_PrivateMediaView):
    def get(self, request, export_job_id):
        with tenant_atomic():
            try:
                job = (ExportJob.objects.for_tenant(current_tenant())
                       .select_related('dataset_version__dataset__item').get(pk=export_job_id))
            except ExportJob.DoesNotExist as exc:
                raise Http404 from exc
            AuthorizationService.require(
                request, 'dataset.export', item=job.dataset_version.dataset.item)
            return _file_response(job.file, request, as_attachment=True)


class DigFormImageView(_PrivateMediaView):
    """디지털 양식 이미지 — 참고사진과 작성 결과의 이미지 칸. 디지털 양식 메뉴 중 하나라도 읽기 권한이 있어야 한다.

    권한이 없거나 없는 id 면 구분 없이 404 다 — 존재 여부를 흘리지 않는다.
    """

    def get(self, request, file_id):
        from app.views import authorize_menu_codes
        from domain.gui import DIG_FORM_MENU_CODES
        from domain.models.system import AttachFile
        from domain.services.dig_form_image import CONTENT_TYPES, FOLDERS, image_path

        if authorize_menu_codes(request, list(DIG_FORM_MENU_CODES), 'media/dig-form-image'):
            raise Http404
        attach = AttachFile.objects.filter(pk=file_id).first()
        if attach is None or (attach.TableName, attach.AttachName) not in FOLDERS:
            raise Http404
        try:
            return sendfile(str(image_path(attach)), request=request, content_type=CONTENT_TYPES.get(attach.ExtName))
        except FileNotFoundError as exc:
            raise Http404('파일을 찾을 수 없습니다.') from exc


class DigFormOverlayView(_PrivateMediaView):
    """사진 넣기 팝업의 Overlay — 칸(dig_form_item)에 연결된 비전검사항목의 Overlay, 표시(visible)일 때만.

    비전검사 Overlay 관리 화면 미리보기(`/media/overlay/`)는 그 조직의 비전검사항목인지를 보고, 검사작성은 디지털 양식 메뉴 권한으로 본다.
    """

    def get(self, request, item_id):
        from app.views import authorize_menu_codes
        from domain.gui import DIG_FORM_MENU_CODES
        from domain.models.dig_form import DigFormItem
        from domain.models.vision import VisionOverlay

        if authorize_menu_codes(request, list(DIG_FORM_MENU_CODES), 'media/dig-form-overlay'):
            raise Http404
        cell = DigFormItem.objects.filter(pk=item_id).exclude(VisionItem=None).first()
        if cell is None:
            raise Http404
        with tenant_atomic():
            overlay = VisionOverlay.objects.filter(item_id=cell.VisionItem_id, visible=True).first()
            if overlay is None:
                raise Http404
            return _file_response(overlay.image, request)


class DigFormAssetView(_PrivateMediaView):
    """디지털 양식의 비전 연결 이미지 칸 사진(비전 데이터 이미지). 저장된 연결 칸 결과가 가리키거나,
    이 사용자가 이번 세션에 사진 넣기로 올린 것만 내준다. 디지털 양식 메뉴 중 하나의 읽기 권한이 있어야 한다."""

    def get(self, request, asset_id):
        from app.views import authorize_menu_codes
        from domain.gui import DIG_FORM_MENU_CODES
        from domain.models.dig_form import DigFormItemResult
        from domain.services.dig_form_image import CAPTURE_SESSION_KEY

        if authorize_menu_codes(request, list(DIG_FORM_MENU_CODES), 'media/dig-form-asset'):
            raise Http404
        if asset_id not in request.session.get(CAPTURE_SESSION_KEY, []) and not DigFormItemResult.objects.filter(
                TextResult=str(asset_id), DigFormItem__ResultType='I', DigFormItem__VisionItem__isnull=False).exists():
            raise Http404
        with tenant_atomic():
            image = ImageAsset.objects.for_tenant(current_tenant()).filter(pk=asset_id).first()
            if image is None:
                raise Http404
            return _file_response(image.file, request, content_type=image.mime_type or None)
