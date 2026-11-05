"""추론 경계 — Wezard(학습·추론 서버) 호출.

`WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 있으면 `WezardGateway` 가 매핑된 모델 이름(`model_code` = Wezard
`model_name`)으로 배포된 최신 모델을 찾아 `POST /api/v1/inference/{model_id}` 를 부른다.
설정이 없으면 Stub 이 `GpuNotConfiguredError` 를 던진다 — 검사는 `RECEIVED` 다(O-12).

> `torch`·`torchvision` 을 여기로 들이지 않는다 — WEB 서버에 설치하지 않는다(O-1). 추론은 Wezard 가 한다.
> HTTP 는 표준 라이브러리(`urllib`)로 한다 — 운영 의존성을 늘리지 않는다.
"""
import base64
import binascii
import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


class GpuNotConfiguredError(Exception):
    """GPU Server 가 구성되지 않았다.

    검사는 정상 접수되고 이미지도 저장된다. 판정만 보류된다.
    Client 에는 `status: "RECEIVED"` 로 응답한다 — 이 예외를 오류 봉투로
    내보내면 Client 가 매 촬영마다 오류 타일을 띄워 현장 검사가 막힌다.
    """

    code = 'GPU_INFERENCE_NOT_CONFIGURED'


class ModelNotDeployedError(GpuNotConfiguredError):
    """매핑된 이름의 배포 모델이 Wezard 에 없다. 미설정과 같이 `RECEIVED` 로 접수만 한다(사용자 결정 2026-10-12)."""

    code = 'WEZARD_MODEL_NOT_DEPLOYED'


class WezardError(Exception):
    """Wezard 호출 실패. 검사는 `FAILED` 다. `code` 는 Wezard `error.code` 또는 `TIMEOUT`·`UNREACHABLE`."""

    def __init__(self, code, status=None):
        super().__init__(f'{code} (HTTP {status})' if status else code)
        self.code = code
        self.status = status


BBOX_KEYS = ('x1', 'y1', 'x2', 'y2')


@dataclass
class Defect:
    """탐지 1건. Client `_parse_defect` 계약과 필드명이 같아야 한다.

    `bbox` 는 `{x1, y1, x2, y2}` — **원본 이미지 Pixel 좌표** 정수이고
    `0 <= x1 < x2`, `0 <= y1 < y2` 다.
    """

    class_name: str
    confidence: float
    bbox: dict

    def __post_init__(self):
        # GPU Server 응답이 그대로 Client 로 나가는 경계다. 모양이 틀리면 여기서 멈춘다.
        if not isinstance(self.bbox, dict) or any(key not in self.bbox for key in BBOX_KEYS):
            raise ValueError(f'bbox 는 {", ".join(BBOX_KEYS)} 를 가진 객체여야 합니다.')


@dataclass
class InferenceResult:
    abnormal: bool
    model_name: str
    model_version: str
    defects: list = field(default_factory=list)
    anomaly_score: float = None
    threshold: float = None
    inference_ms: float = None
    # 분류의 1순위 {label, score}. 정상·불량은 라벨 클래스를 아는 검사 서비스가 정한다.
    classification: dict = None
    # 이상 탐지의 색 지도 PNG(원본 크기). 원본과 겹치는 일은 검사 서비스가 한다.
    heatmap_png: bytes = None


class InferenceGateway:
    """추론 요청의 단일 진입점."""

    def is_configured(self) -> bool:
        return False

    def infer(self, *, inspection_type, model_code, model_version, threshold,
              image_bytes, request_id) -> InferenceResult:
        raise GpuNotConfiguredError()


# 검사 POST 는 20초 안에 끝낸다(DEC-C11) — 모델 조회 5초 + 추론 15초. 재시도는 하지 않는다.
LOOKUP_TIMEOUT = 5
INFER_TIMEOUT = 15
# 추론 도중 배포가 풀리거나 모델이 사라진 경우. 접수만 하고 FAILED 로 두지 않는다.
NOT_DEPLOYED_CODES = {'MODEL_NOT_DEPLOYED', 'MODEL_NOT_FOUND', 'MODEL_NOT_READY'}
THRESHOLD_FIELD = {'ANOMALY': 'anomaly_threshold', 'DETECTION': 'score_threshold'}


class WezardGateway(InferenceGateway):
    """Wezard API 클라이언트. 키는 헤더로만 보내고 로그·예외 문구에 넣지 않는다."""

    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key

    def is_configured(self) -> bool:
        return True

    def list_models(self, task_type):
        """배포된 READY vision 모델(최신순). task_type 은 Wezard 값(`classification`·`detection`·`anomaly`)."""
        return self._request('GET', '/api/v1/models', timeout=LOOKUP_TIMEOUT, query={
            'deployed': 'true', 'status': 'READY', 'category': 'vision', 'task_type': task_type, 'limit': 200})['items']

    def infer(self, *, inspection_type, model_code, model_version, threshold,
              image_bytes, request_id) -> InferenceResult:
        # 재학습하면 model_id 가 바뀐다 — 이름으로 그때의 최신 배포 모델을 찾는다.
        items = self._request('GET', '/api/v1/models', timeout=LOOKUP_TIMEOUT, query={
            'model_name': model_code, 'deployed': 'true', 'status': 'READY', 'category': 'vision', 'limit': 1})['items']
        if not items:
            raise ModelNotDeployedError()
        # 분류에는 임계값이 없다 — 1순위 클래스로 판정한다.
        fields = ({THRESHOLD_FIELD[inspection_type]: str(threshold)}
                  if threshold is not None and inspection_type in THRESHOLD_FIELD else {})
        if inspection_type == 'ANOMALY':
            fields['return_heatmap'] = 'true'
        try:
            body = self._request('POST', f'/api/v1/inference/{items[0]["model_id"]}', timeout=INFER_TIMEOUT,
                                 fields=fields, image=image_bytes, request_id=request_id)
        except WezardError as exc:
            if exc.code in NOT_DEPLOYED_CODES:
                raise ModelNotDeployedError() from exc
            raise
        row = body['results'][0]
        result = InferenceResult(abnormal=False, model_name=body['model_name'], model_version=str(body['version']),
                                 inference_ms=body.get('elapsed_ms'))
        if 'detections' in row:
            result.defects = [defect for defect in (_defect(d, row['width'], row['height']) for d in row['detections'])
                              if defect]
            result.abnormal = bool(result.defects)
        elif 'label' in row:
            result.classification = {'label': row['label'], 'score': row['score']}
        else:
            result.abnormal = bool(row['is_anomaly'])
            result.anomaly_score = row['anomaly_score']
            result.threshold = row['threshold']
            result.heatmap_png = _heatmap_png(row.get('heatmap_png_base64'))
        return result

    def _request(self, method, path, *, timeout, query=None, fields=None, image=None, request_id=None):
        """JSON 응답(dict). 4xx·5xx 는 Wezard `error.code` 로, 연결·시간 초과는 `UNREACHABLE`·`TIMEOUT` 으로 WezardError."""
        url = self.base_url + path + ('?' + urlencode(query) if query else '')
        headers = {'X-API-Key': self.api_key, 'X-Request-ID': request_id or uuid.uuid4().hex, 'Accept': 'application/json'}
        data = None
        if image is not None:
            boundary = uuid.uuid4().hex
            parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                     for name, value in (fields or {}).items()]
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{request_id}"\r\n'
                         'Content-Type: application/octet-stream\r\n\r\n'.encode() + image + b'\r\n')
            parts.append(f'--{boundary}--\r\n'.encode())
            data = b''.join(parts)
            headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
        try:
            with urlopen(Request(url, data=data, headers=headers, method=method), timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            try:
                code = json.loads(exc.read())['error']['code']
            except (ValueError, KeyError, TypeError):
                code = 'HTTP_ERROR'
            raise WezardError(code, exc.code) from None
        except TimeoutError as exc:
            raise WezardError('TIMEOUT') from exc
        except URLError as exc:
            raise WezardError('TIMEOUT' if isinstance(exc.reason, TimeoutError) else 'UNREACHABLE') from exc


def _heatmap_png(encoded):
    """Wezard `heatmap_png_base64` → 바이트. 없거나 깨졌으면 None — Heatmap 때문에 판정을 버리지 않는다."""
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        logger.warning('Wezard Heatmap 을 풀지 못했다 — 판정만 남긴다')
        return None


def _defect(detection, width, height):
    """Wezard 박스(실수 xyxy) → Defect. 정수로 넓혀 이미지 안으로 자르고, 넓이가 0 이면 None(DEC-C13)."""
    x1, y1, x2, y2 = detection['bbox']
    box = {'x1': max(0, math.floor(x1)), 'y1': max(0, math.floor(y1)),
           'x2': min(width, math.ceil(x2)), 'y2': min(height, math.ceil(y2))}
    if box['x1'] >= box['x2'] or box['y1'] >= box['y2']:
        return None
    return Defect(class_name=detection['label'], confidence=detection['score'], bbox=box)


def get_inference_gateway() -> InferenceGateway:
    """`WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 둘 다 있으면 Wezard, 아니면 Stub."""
    if settings.WEZARD_BASE_URL and settings.WEZARD_API_KEY:
        return WezardGateway(settings.WEZARD_BASE_URL, settings.WEZARD_API_KEY)
    return InferenceGateway()
