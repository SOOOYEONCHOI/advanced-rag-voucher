"""비전검사항목 AI 모델 매핑(`domain.services.vision.model_mapping`) — Wezard 배포 모델에서 이름을 골라 매핑한다.

화면은 비전검사항목 관리 상세다(`item/item_admin`, tests.test_item_api). 비전검사항목 모델 매핑 화면은 2026-10-21 지웠다.

이름을 저장하고 추론 때마다 그 이름의 최신 배포 모델을 찾는다. 로컬 `VisionModel` 은 이름표(version `latest`)다.
해제는 모델 "(매핑 없음)"을 골라 저장하고, 지우지 않고 비활성으로 남긴다(어떤 모델로 판정했는지 이력이 필요하다).
"""
from unittest.mock import patch

from django.test import TestCase

from domain.models.data import InspectionItem
from domain.models.vision import VisionItemModelMapping, VisionModel
from domain.services.vision import model_mapping
from domain.services.vision.gateway import InferenceGateway, WezardError
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic

T = InspectionItem.TaskType


def models(item):
    with tenant_atomic():
        found, message = model_mapping.deployed_models(item)
    return {'models': found, 'message': message}


def save(**posparam):
    with tenant_atomic():
        return model_mapping.save_mapping(posparam)


class FakeWezard(InferenceGateway):
    """task_type 별 배포 모델(최신순). error 를 주면 목록 조회가 실패한다."""

    def __init__(self, error=None):
        self.error = error

    def is_configured(self):
        return True

    def list_models(self, task_type):
        if self.error:
            raise self.error
        return {'detection': [{'model_name': 'other-det', 'version': 3, 'dataset_external_ref': None},
                              {'model_name': 'wz-det', 'version': 2, 'dataset_external_ref': 'maip:WZ-DET:v2.0#9'},
                              {'model_name': 'wz-det', 'version': 1, 'dataset_external_ref': 'maip:WZ-DET:v1.0#5'}],
                'anomaly': [{'model_name': 'wz-ano', 'version': 1, 'dataset_external_ref': None}],
                'classification': [{'model_name': 'wz-cls', 'version': 1, 'dataset_external_ref': None}]}[task_type]


class ModelMappingTestCase(TestCase):
    gateway = FakeWezard()

    def setUp(self):
        reset_tenant_cache()
        with tenant_atomic():
            self.item = InspectionItem.objects.create(tenant=current_tenant(), code='WZ-DET', name='검출',
                                                      task_type=T.OBJECT_DETECTION)
        patcher = patch('domain.services.vision.model_mapping.get_inference_gateway', side_effect=lambda: self.gateway)
        patcher.start()
        self.addCleanup(patcher.stop)

    def active(self):
        with tenant_atomic():
            return list(VisionItemModelMapping.objects.filter(item=self.item, active=True))


class ModelListTest(ModelMappingTestCase):
    def test_유형이_맞는_배포_모델을_이름별로_주고_코드_소문자_이름이_먼저다(self):
        body = models(self.item)
        self.assertEqual([(m['name'], m['version'], m['recommended']) for m in body['models']],
                         [('wz-det', 2, True), ('other-det', 3, False)])
        self.assertEqual(body['message'], '')

    def test_분류_검사항목은_분류_모델을_고르고_이름표_유형은_CLASSIFICATION_이다(self):
        with tenant_atomic():
            item = InspectionItem.objects.create(tenant=current_tenant(), code='WZ-CLS', name='분류',
                                                 task_type=T.CLASSIFICATION)
        body = models(item)
        self.assertEqual([(m['name'], m['recommended']) for m in body['models']], [('wz-cls', True)])
        self.assertTrue(save(item_id=item.id, model_name='wz-cls')['success'])
        with tenant_atomic():
            self.assertEqual(VisionModel.objects.get(name='wz-cls').inspection_type, 'CLASSIFICATION')

    def test_Wezard_설정이_없으면_안내한다(self):
        self.gateway = InferenceGateway()
        body = models(self.item)
        self.assertEqual(body['models'], [])
        self.assertIn('Wezard 연결 설정', body['message'])

    def test_Wezard_오류는_안내하고_키는_보이지_않는다(self):
        self.gateway = FakeWezard(WezardError('UNAUTHORIZED', 401))
        body = models(self.item)
        self.assertEqual(body['models'], [])
        self.assertIn('UNAUTHORIZED', body['message'])

    def test_시간_초과와_연결_실패는_한국어로_알린다(self):
        for code, text in (('TIMEOUT', '응답 시간 초과'), ('UNREACHABLE', '연결 실패')):
            self.gateway = FakeWezard(WezardError(code))
            message = models(self.item)['message']
            self.assertEqual(message, f'Wezard 에서 모델 목록을 받지 못했습니다({text}).')



class MeasurementItemMappingTest(ModelMappingTestCase):
    def test_치수_측정_항목은_매핑하지_않는다(self):
        with tenant_atomic():
            dim = InspectionItem.objects.create(tenant=current_tenant(), code='WZ-DIM', name='치수', task_type=T.MEASUREMENT)
        self.assertFalse(save(item_id=dim.id, model_name='wz-det')['success'])


class ModelMappingSaveTest(ModelMappingTestCase):
    def test_이름을_고르면_이름표_모델을_맞추고_매핑한다(self):
        self.assertTrue(save(item_id=self.item.id, model_name='wz-det')['success'])
        [mapping] = self.active()
        self.assertEqual((mapping.model_code, mapping.model_version), ('wz-det', 'latest'))
        with tenant_atomic():
            model = VisionModel.objects.get(name='wz-det')
        self.assertEqual((model.version, model.inspection_type, model.runtime), ('latest', 'DETECTION', 'wezard'))
        # 같은 이름을 다시 골라도 이름표는 하나다
        save(item_id=self.item.id, model_name='wz-det')
        self.assertEqual(VisionModel.objects.filter(name='wz-det').count(), 1)

    def test_배포_목록에_없거나_유형이_다른_이름은_거절한다(self):
        for name in ('no-such', 'wz-ano'):
            result = save(item_id=self.item.id, model_name=name)
            self.assertFalse(result['success'], name)
        self.assertEqual(result['message'], "'wz-ano' 모델이 Wezard 에 배포된 객체 탐지 모델에 없습니다.")
        self.assertEqual(self.active(), [])

    def test_매핑_없음을_저장하면_해제하고_이력은_남긴다(self):
        save(item_id=self.item.id, model_name='wz-det')
        result = save(item_id=self.item.id, model_name='')
        self.assertTrue(result['success'], result)
        self.assertEqual(self.active(), [])
        with tenant_atomic():
            self.assertEqual(VisionItemModelMapping.objects.filter(item=self.item).count(), 1)

    def test_매핑이_없는데_매핑_없음을_저장해도_된다(self):
        self.assertTrue(save(item_id=self.item.id, model_name='')['success'])

    def test_임계값을_보내지_않으면_직전_재지정_값을_이어_받는다(self):
        """상세 화면에 임계값 칸이 없다. 모델만 바꿔 저장해도 재지정 값이 지워지지 않는다."""
        save(item_id=self.item.id, model_name='wz-det', threshold_override='0.42')
        save(item_id=self.item.id, model_name='other-det')
        self.assertEqual([m.threshold_override for m in self.active()], [0.42])

    def test_임계값을_비워_보내면_재지정을_없앤다(self):
        save(item_id=self.item.id, model_name='wz-det', threshold_override='0.42')
        save(item_id=self.item.id, model_name='wz-det', threshold_override='')
        self.assertEqual([m.threshold_override for m in self.active()], [None])

    def test_지금_모델_이름은_활성_매핑의_이름이다(self):
        with tenant_atomic():
            self.assertEqual(model_mapping.active_model_name(self.item), '')
        save(item_id=self.item.id, model_name='wz-det')
        with tenant_atomic():
            self.assertEqual(model_mapping.active_model_name(self.item), 'wz-det')


class RetiredAiModelScreenTest(TestCase):
    """AI 모델 등록 화면(wm_vis_model)과 모델 매핑 화면(wm_vis_model_mapping)·그 API 는 지웠다 — 모델은 Wezard 가 갖고
    비전검사항목 관리 상세가 이름표를 만든다."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user('root', password='x', is_superuser=True))

    def test_화면과_API_가_없다(self):
        from domain.gui import GUIConfiguration
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_vis_model'))
        self.assertNotEqual(self.client.get('/api/vision/model', {'action': 'list'}).status_code, 200)
        self.assertNotEqual(self.client.post('/api/vision/model?action=save', {'name': 'x', 'version': '1'}).status_code, 200)
        self.assertFalse(VisionModel.objects.exists())
        self.assertIsNone(GUIConfiguration.get_gui_info('wm_vis_model_mapping'))
        self.assertNotEqual(self.client.get('/api/vision/model_mapping', {'action': 'list'}).status_code, 200)
