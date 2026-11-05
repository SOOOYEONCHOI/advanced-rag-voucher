"""Wezard 추론 게이트웨이 — 배포 모델 조회 → 추론 → InferenceResult 변환(Wezard 통신 규약 v1, docs/Wezard/wezard-api.md).

HTTP 는 `_request` 를 바꿔 끼워 흉내 낸다. 실제 Wezard 호출은 계획 Task 4 실측으로 본다.
"""
from django.test import SimpleTestCase, override_settings

from domain.services.vision import gateway
from domain.services.vision.gateway import (
    InferenceGateway, ModelNotDeployedError, WezardError, WezardGateway, get_inference_gateway)

MODEL = {'model_id': 'a' * 32, 'model_name': 'fan-panel', 'version': 2, 'task_type': 'anomaly'}


class FakeWezard(WezardGateway):
    """경로별 응답(dict) 또는 예외를 돌려주고 받은 요청을 기록한다."""

    def __init__(self, responses):
        super().__init__('http://wezard.test', 'wz_test-key')
        self.responses = responses
        self.calls = []

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        response = self.responses[path]
        if isinstance(response, Exception):
            raise response
        return response


def infer(fake, inspection_type='ANOMALY', threshold=None):
    return fake.infer(inspection_type=inspection_type, model_code='fan-panel', model_version='latest',
                      threshold=threshold, image_bytes=b'png-bytes', request_id='0f8e5a52-6a1c-4c58-9d1f-2b7d3f1e9c10')


class WezardGatewayTest(SimpleTestCase):
    def test_이상_탐지_결과를_판정으로_바꾼다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'fan-panel', 'version': 2, 'elapsed_ms': 153,
            'results': [{'width': 1448, 'height': 1086, 'anomaly_score': 48.4, 'threshold': 41.1, 'is_anomaly': True}]}})
        result = infer(fake)
        self.assertEqual((result.abnormal, result.anomaly_score, result.threshold, result.defects),
                         (True, 48.4, 41.1, []))
        self.assertEqual((result.model_name, result.model_version, result.inference_ms), ('fan-panel', '2', 153))
        _, _, lookup = fake.calls[0]
        self.assertEqual(lookup['query'], {'model_name': 'fan-panel', 'deployed': 'true', 'status': 'READY',
                                           'category': 'vision', 'limit': 1})
        _, _, call = fake.calls[1]
        self.assertEqual(call['request_id'], '0f8e5a52-6a1c-4c58-9d1f-2b7d3f1e9c10')
        # 이상 탐지는 Heatmap 을 함께 받는다(계약 §8)
        self.assertEqual(call['fields'], {'return_heatmap': 'true'})
        self.assertIsNone(result.heatmap_png)

    def test_임계값_재지정은_유형별_필드로_보낸다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'fan-panel', 'version': 2, 'elapsed_ms': 1,
            'results': [{'width': 10, 'height': 10, 'anomaly_score': 1.0, 'threshold': 50.0, 'is_anomaly': False}]}})
        infer(fake, threshold=50.0)
        self.assertEqual(fake.calls[1][2]['fields'], {'anomaly_threshold': '50.0', 'return_heatmap': 'true'})
        fake.calls.clear()
        fake.responses[f'/api/v1/inference/{"a" * 32}']['results'] = [{'width': 10, 'height': 10, 'detections': []}]
        infer(fake, inspection_type='DETECTION', threshold=0.4)
        self.assertEqual(fake.calls[1][2]['fields'], {'score_threshold': '0.4'})

    def test_탐지_박스는_정수로_이미지_안에_자르고_넓이_0_은_버린다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'fan-panel-det', 'version': 1, 'elapsed_ms': 9,
            'results': [{'width': 100, 'height': 80, 'detections': [
                {'label': 'scratch', 'score': 0.93, 'bbox': [10.6, 20.2, 30.1, 40.9]},
                {'label': 'scratch', 'score': 0.5, 'bbox': [-3.0, 70.0, 120.0, 95.0]},
                {'label': 'dent', 'score': 0.4, 'bbox': [50.2, 10.0, 50.7, 20.0]},
                {'label': 'dent', 'score': 0.3, 'bbox': [60.0, 10.0, 60.0, 20.0]},
                {'label': 'dent', 'score': 0.3, 'bbox': [100.0, 10.0, 130.0, 20.0]}]}]}})
        result = infer(fake, inspection_type='DETECTION')
        self.assertTrue(result.abnormal)
        self.assertEqual([(d.class_name, d.confidence, d.bbox) for d in result.defects], [
            ('scratch', 0.93, {'x1': 10, 'y1': 20, 'x2': 31, 'y2': 41}),
            ('scratch', 0.5, {'x1': 0, 'y1': 70, 'x2': 100, 'y2': 80}),
            ('dent', 0.4, {'x1': 50, 'y1': 10, 'x2': 51, 'y2': 20})])

    def test_분류는_1순위_라벨과_점수를_넘기고_임계값은_보내지_않는다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'fan-panel-cls', 'version': 4, 'elapsed_ms': 12,
            'results': [{'width': 10, 'height': 10, 'label': 'defect', 'score': 0.91,
                         'topk': [{'label': 'defect', 'score': 0.91}, {'label': 'normal', 'score': 0.09}]}]}})
        result = infer(fake, inspection_type='CLASSIFICATION', threshold=0.5)
        self.assertEqual(result.classification, {'label': 'defect', 'score': 0.91})
        self.assertEqual((result.defects, result.anomaly_score, result.threshold), ([], None, None))
        self.assertEqual(fake.calls[1][2]['fields'], {})

    def test_이상_탐지_Heatmap_은_base64_를_풀어_넘긴다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'fan-panel', 'version': 2, 'elapsed_ms': 1,
            'results': [{'width': 10, 'height': 10, 'anomaly_score': 50.0, 'threshold': 41.0, 'is_anomaly': True,
                         'heatmap_png_base64': 'aGVhdG1hcA=='}]}})
        self.assertEqual(infer(fake).heatmap_png, b'heatmap')

    def test_Heatmap_이_깨져_있어도_판정은_그대로다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'fan-panel', 'version': 2, 'elapsed_ms': 1,
            'results': [{'width': 10, 'height': 10, 'anomaly_score': 50.0, 'threshold': 41.0, 'is_anomaly': True,
                         'heatmap_png_base64': '@@@'}]}})
        result = infer(fake)
        self.assertEqual((result.abnormal, result.heatmap_png), (True, None))

    def test_탐지가_없으면_정상이다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': {
            'model_name': 'm', 'version': 1, 'elapsed_ms': 1, 'results': [{'width': 10, 'height': 10, 'detections': []}]}})
        result = infer(fake, inspection_type='DETECTION')
        self.assertEqual((result.abnormal, result.defects), (False, []))

    def test_배포된_모델이_없으면_ModelNotDeployedError(self):
        with self.assertRaises(ModelNotDeployedError) as raised:
            infer(FakeWezard({'/api/v1/models': {'items': []}}))
        self.assertEqual(raised.exception.code, 'WEZARD_MODEL_NOT_DEPLOYED')

    def test_추론_사이에_배포가_풀리면_ModelNotDeployedError(self):
        for code, status in (('MODEL_NOT_DEPLOYED', 409), ('MODEL_NOT_FOUND', 404), ('MODEL_NOT_READY', 409)):
            fake = FakeWezard({'/api/v1/models': {'items': [MODEL]},
                               f'/api/v1/inference/{"a" * 32}': WezardError(code, status)})
            with self.assertRaises(ModelNotDeployedError):
                infer(fake)

    def test_서버_오류는_WezardError_그대로다(self):
        for error in (WezardError('UPSTREAM_TIMEOUT', 504), WezardError('TIMEOUT', None), WezardError('UNAUTHORIZED', 401)):
            fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}, f'/api/v1/inference/{"a" * 32}': error})
            with self.assertRaises(WezardError) as raised:
                infer(fake)
            self.assertNotIsInstance(raised.exception, ModelNotDeployedError)

    def test_모델_목록은_배포된_vision_모델을_유형별로_받는다(self):
        fake = FakeWezard({'/api/v1/models': {'items': [MODEL]}})
        self.assertEqual(fake.list_models('anomaly'), [MODEL])
        self.assertEqual(fake.calls[0][2]['query'], {'deployed': 'true', 'status': 'READY', 'category': 'vision',
                                                     'task_type': 'anomaly', 'limit': 200})


class WezardRequestTest(SimpleTestCase):
    """`_request` 가 만드는 HTTP 요청 — urlopen 을 바꿔 끼워 본다."""

    def test_multipart_에_이미지와_필드를_싣고_키와_요청_ID_를_헤더로_보낸다(self):
        sent = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": 1}'

        def urlopen(request, timeout):
            sent.update(url=request.full_url, headers=dict(request.header_items()), body=request.data, timeout=timeout)
            return Response()

        original = gateway.urlopen
        gateway.urlopen = urlopen
        try:
            body = WezardGateway('http://wezard.test/', 'wz_k').\
                _request('POST', '/api/v1/inference/x', fields={'score_threshold': '0.4'}, image=b'IMG',
                         request_id='rid-1', timeout=15)
        finally:
            gateway.urlopen = original
        self.assertEqual(body, {'ok': 1})
        self.assertEqual((sent['url'], sent['timeout']), ('http://wezard.test/api/v1/inference/x', 15))
        self.assertEqual((sent['headers']['X-api-key'], sent['headers']['X-request-id']), ('wz_k', 'rid-1'))
        self.assertIn(b'name="score_threshold"\r\n\r\n0.4\r\n', sent['body'])
        self.assertIn(b'name="files"; filename="rid-1"', sent['body'])
        self.assertIn(b'\r\n\r\nIMG\r\n', sent['body'])


class GatewayChoiceTest(SimpleTestCase):
    @override_settings(WEZARD_BASE_URL='http://wezard.test', WEZARD_API_KEY='wz_k')
    def test_설정이_있으면_Wezard(self):
        self.assertIsInstance(get_inference_gateway(), WezardGateway)

    @override_settings(WEZARD_BASE_URL='', WEZARD_API_KEY='wz_k')
    def test_설정이_없으면_Stub(self):
        chosen = get_inference_gateway()
        self.assertIs(type(chosen), InferenceGateway)
        self.assertFalse(chosen.is_configured())
