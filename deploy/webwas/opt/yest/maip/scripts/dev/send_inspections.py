#!/usr/bin/env python
"""비전검사 클라이언트처럼 검사 이미지를 `/api/v1/inspections` 로 보낸다(개발·점검용).

라벨링 워크플로우를 사람이 따라가 볼 때 쓴다.
e2e `tests/e2e/test_client_workflow.py` 도 여기의 `defect_jpeg` 로 이미지를 만든다.

    VISION_API_KEY=<발급받은 키> python scripts/dev/send_inspections.py \\
        --client-id E2E-MANUAL --item-id <id> --kind mixed --count 5
    python scripts/dev/send_inspections.py --images ~/사진 --client-id ... --item-id ...
    python scripts/dev/send_inspections.py --self-check      # 서버 없이 그림·metadata 만 확인

API Key 는 환경변수 `VISION_API_KEY` 로만 받고 출력하지 않는다.
"""
import argparse
import datetime
import io
import json
import os
import pathlib
import random
import sys
import uuid

from PIL import Image, ImageDraw

KINDS = ('scratch', 'dent', 'normal')
SIZE = (640, 480)


def defect_jpeg(kind, seed=0):
    """회색 판 무늬 위에 결함을 그린 JPEG 바이트. seed 가 다르면 내용(sha256)도 다르다.

    scratch: 가로 30~60%·세로 30~60% 를 잇는 대각선, dent: 가운데(50%, 50%) 반지름 10% 원, normal: 무늬만.
    """
    if kind not in KINDS:
        raise ValueError(f'kind 는 {KINDS} 중 하나다: {kind}')
    rng = random.Random(f'{kind}-{seed}')
    width, height = SIZE
    image = Image.new('RGB', SIZE, (150, 150, 150))
    draw = ImageDraw.Draw(image)
    for _ in range(60):  # 판 무늬
        y = rng.randrange(height)
        shade = rng.randrange(135, 165)
        draw.line([(0, y), (width, y + rng.randrange(-8, 8))], fill=(shade, shade, shade), width=2)
    if kind == 'scratch':
        draw.line([(width * 0.3, height * 0.3), (width * 0.6, height * 0.6)], fill=(40, 40, 40), width=6)
    elif kind == 'dent':
        radius = width * 0.1
        draw.ellipse([width * 0.5 - radius, height * 0.5 - radius, width * 0.5 + radius, height * 0.5 + radius],
                     fill=(70, 70, 70), outline=(30, 30, 30), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=90)
    return buffer.getvalue()


def metadata(client_id, item_id, request_id=None):
    """클라이언트 계약의 metadata. process_id·product_id 는 서버가 보지 않는다."""
    return {
        'request_id': request_id or str(uuid.uuid4()),
        'client_id': client_id,
        'process_id': 1, 'product_id': 1,
        'inspection_item_id': item_id,
        'capture_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'client_version': 'send_inspections',
        'camera': {'vendor': 'sample', 'serial_number': 'SAMPLE-1'},
    }


def images_to_send(args):
    """(파일 이름, 바이트, content-type) 목록."""
    if args.images:
        folder = pathlib.Path(args.images).expanduser()
        types = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in types)
        if not files:
            raise SystemExit(f'{folder} 에 jpg·png 가 없습니다.')
        return [(p.name, p.read_bytes(), types[p.suffix.lower()]) for p in files]
    kinds = KINDS if args.kind == 'mixed' else (args.kind,)
    stamp = datetime.datetime.now().strftime('%H%M%S')
    return [(f'{kinds[i % len(kinds)]}-{i}.jpg', defect_jpeg(kinds[i % len(kinds)], seed=f'{stamp}-{i}'), 'image/jpeg')
            for i in range(args.count)]


def send(args):
    import requests

    api_key = os.environ.get('VISION_API_KEY')
    if not api_key:
        raise SystemExit('환경변수 VISION_API_KEY 가 없습니다(비전검사 클라이언트 관리 화면에서 발급한 키).')
    headers = {'X-Client-ID': args.client_id, 'X-API-Key': api_key}
    failed = 0
    for name, content, content_type in images_to_send(args):
        meta = metadata(args.client_id, args.item_id)
        try:
            response = requests.post(f'{args.base_url.rstrip("/")}/api/v1/inspections', headers=headers, timeout=30,
                                     files={'image': (name, content, content_type)}, data={'metadata': json.dumps(meta)})
        except requests.RequestException as exc:
            raise SystemExit(f'서버에 연결하지 못했습니다: {exc.__class__.__name__}')
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code in (200, 201):
            print(f'{meta["request_id"]}  {response.status_code}  {name}  검사 {body["data"]["id"]}')
        else:
            failed += 1
            problem = body.get('error') or {}
            print(f'{meta["request_id"]}  {response.status_code}  {name}  {problem.get("code", "-")}: {problem.get("message", response.text[:200])}')
    return 1 if failed else 0


def self_check():
    for kind in KINDS:
        content = defect_jpeg(kind)
        assert content[:2] == b'\xff\xd8', kind
        assert Image.open(io.BytesIO(content)).size == SIZE
        assert defect_jpeg(kind, seed=1) != content, kind
    assert defect_jpeg('scratch') == defect_jpeg('scratch')
    meta = json.loads(json.dumps(metadata('CLIENT-X', 7)))
    assert meta['inspection_item_id'] == 7 and meta['capture_timestamp'].endswith('Z')
    print('self-check 통과')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--client-id')
    parser.add_argument('--item-id', type=int)
    parser.add_argument('--kind', choices=KINDS + ('mixed',), default='mixed')
    parser.add_argument('--count', type=int, default=3)
    parser.add_argument('--images', help='보낼 사진 폴더(jpg·png). 주면 --kind·--count 를 무시한다')
    parser.add_argument('--base-url', default='http://127.0.0.1:8123')
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if not args.client_id or args.item_id is None:
        parser.error('--client-id 와 --item-id 가 필요합니다.')
    return send(args)


if __name__ == '__main__':
    sys.exit(main())
