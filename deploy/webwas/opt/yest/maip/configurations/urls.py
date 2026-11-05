"""ManufacturingAIPlatform URL 구성."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import path
from django.views.generic.base import RedirectView

from app.views import (
    ApiModuleView,
    GUITemplatesView,
    SystemDefaultRenderer,
    TemplatePathView,
)
from app.views.account import AccountLoginView, AccountLogoutView
from app.views.api_v1 import (
    CatalogVersionView,
    CatalogView,
    ClientPackageDownloadView,
    ClientPackageListView,
    HealthView,
    InspectionByRequestView,
    InspectionCreateView,
    InspectionHeatmapView,
    LicenseSourceDownloadView,
    LicenseSourceListView,
    OverlayImageView,
    OverlayView,
    V1NotFoundView,
)
from app.views.api_v1_datasets import SnapshotDetailView, SnapshotDownloadView, SnapshotListView
from app.views.files.media import (
    DigFormAssetView,
    DigFormImageView,
    DigFormOverlayView,
    PrivateExportView,
    PrivateImageThumbnailView,
    PrivateImageView,
    PrivateItemCoverView,
    PrivateOverlayView,
)

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('img/favicon.ico'))),

    path('', SystemDefaultRenderer.home, name='home'),
    path('error/', SystemDefaultRenderer.error500, name='error'),

    path('api/alive', SystemDefaultRenderer.alive, name='alive'),

    # VisionInspectionClient 호환 계층. 현장 Client 는 base_url 만 바꾸면 된다.
    # 경로·응답 형태를 바꾸면 배포된 Client 가 깨진다.
    path('api/v1/health', HealthView.as_view(), name='v1-health'),
    path('api/v1/catalog', CatalogView.as_view(), name='v1-catalog'),
    path('api/v1/catalog/version', CatalogVersionView.as_view(), name='v1-catalog-version'),
    path('api/v1/inspections', InspectionCreateView.as_view(), name='v1-inspections'),
    path('api/v1/inspections/by-request/<str:request_id>', InspectionByRequestView.as_view(),
         name='v1-inspection-by-request'),
    path('api/v1/inspections/<str:inspection_id>/heatmap', InspectionHeatmapView.as_view(),
         name='v1-inspection-heatmap'),
    path('api/v1/overlays/<int:inspection_item_id>', OverlayView.as_view(), name='v1-overlay'),
    path('api/v1/overlays/<int:inspection_item_id>/image', OverlayImageView.as_view(),
         name='v1-overlay-image'),

    # 학습 플랫폼(Wezard)용 스냅샷 API. 정본은 docs/Wezard/maip-api.md(DECISIONS DEC-029).
    path('api/v1/datasets/snapshots', SnapshotListView.as_view(), name='v1-dataset-snapshots'),
    path('api/v1/datasets/snapshots/<int:snapshot_id>', SnapshotDetailView.as_view(),
         name='v1-dataset-snapshot'),
    path('api/v1/datasets/snapshots/<int:snapshot_id>/download', SnapshotDownloadView.as_view(),
         name='v1-dataset-snapshot-download'),

    # 배포·라이선스. 인증 없이 제공한다.
    # LGPL 고지문에 이 주소가 박혀 있어 바꾸지 않는다.
    path('api/v1/licenses/sources', LicenseSourceListView.as_view(),
         name='v1-license-sources'),
    path('api/v1/client-packages', ClientPackageListView.as_view(),
         name='v1-client-packages'),
    path('api/v1/licenses/sources/<str:filename>', LicenseSourceDownloadView.as_view(),
         name='v1-license-source-download'),
    path('api/v1/client-packages/<str:filename>', ClientPackageDownloadView.as_view(),
         name='v1-client-package-download'),

    # 미지 `/api/v1` 경로도 봉투로 답한다. 위치가 동작을 바꾼다 — 구체 v1 라우트
    # **뒤**, 범용 `api/<task>/<view>` **앞**이어야 한다. 앞에 두면 정상 Endpoint 가
    # 전부 404 가 되고, 뒤에 두면 2-segment 경로가 범용 라우트에 먹혀 401 HTML 이 된다.
    # 루트도 봉투로 답한다. 없으면 Django 404 HTML(DEBUG 면 URL 패턴 목록)이 나간다.
    path('api/v1', V1NotFoundView.as_view()),
    path('api/v1/', V1NotFoundView.as_view()),
    path('api/v1/<path:rest>', V1NotFoundView.as_view(), name='v1-not-found'),

    # 보호된 미디어. MEDIA_URL 을 두지 않고 권한 확인 View 로만 제공한다(DEC-019).
    path('media/image/<int:image_id>/', PrivateImageView.as_view(), name='private-image'),
    path('media/image/<int:image_id>/thumbnail/', PrivateImageThumbnailView.as_view(),
         name='private-image-thumbnail'),
    path('media/item-cover/<int:item_id>/', PrivateItemCoverView.as_view(),
         name='private-item-cover'),
    path('media/export/<int:export_job_id>/', PrivateExportView.as_view(), name='private-export'),
    path('media/overlay/<int:item_id>/', PrivateOverlayView.as_view(), name='private-overlay'),
    path('media/dig-form-image/<int:file_id>/', DigFormImageView.as_view(), name='private-dig-form-image'),
    path('media/dig-form-overlay/<int:item_id>/', DigFormOverlayView.as_view(), name='private-dig-form-overlay'),
    path('media/dig-form-asset/<int:asset_id>/', DigFormAssetView.as_view(), name='private-dig-form-asset'),
    path('api/<str:task_name>/<str:view_name>', ApiModuleView.as_view(), name='api'),

    # GUIConfiguration 기반
    path('gui/<str:gui_code>/', GUITemplatesView.as_view(), name='gui1'),
    path('gui/<str:gui_code>/<str:template_key>', GUITemplatesView.as_view(), name='gui2'),

    # templates path 기반
    path('page/<str:folder>/<str:template_name>', TemplatePathView.as_view(), name='page'),

    path('login/', AccountLoginView.as_view(next='/'), name='login'),
    path('logout/', AccountLogoutView.as_view(next='/login'), name='logout'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
