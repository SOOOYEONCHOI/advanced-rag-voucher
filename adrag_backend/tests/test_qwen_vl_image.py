"""Qwen3-VL 도면 해석 단독 실행 도구.

프로젝트 루트에서 실행:
    python adrag_backend/tests/test_qwen_vl_image.py --list-models
    python adrag_backend/tests/test_qwen_vl_image.py --image path/to/drawing.png
    python adrag_backend/tests/test_qwen_vl_image.py --image drawing.jpg --model Qwen3-VL-8B-Instruct

환경 변수 VLM_API_URL, VLM_API_KEY, VLM_MODEL_NAME를 기본값으로 사용한다.
API 키는 --api-key로도 전달할 수 있다. 이 파일은 pytest 테스트가 아니라 수동 실행용이다.
"""

import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
import sys
import time

import httpx


DEFAULT_BASE_URL = "http://10.10.10.110:8005"
SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
PROCESS_FLOW_PROMPT = """당신은 제조 공정 흐름도(Process Flowchart)를 구조화하는 전문 분석기다.

목표는 이미지에 표시된 도형, 텍스트, 화살표, 분기 조건을 시각적으로 확인하여 검색 및
RAG 처리에 사용할 수 있는 정확한 JSON 그래프를 생성하는 것이다.

다음 원칙을 반드시 준수한다.
1. 이미지에 실제로 보이는 정보만 추출한다.
2. 일반적인 제조 지식으로 누락된 관계를 추측하거나 보완하지 않는다.
3. 화살표 방향은 도형의 위치가 아니라 화살촉이 향하는 방향으로 판단한다.
4. 두 선이 교차해도 연결점 또는 화살촉이 없다면 연결된 것으로 판단하지 않는다.
5. 도형이 서로 가까이 있어도 연결선이 확인되지 않으면 edge를 생성하지 않는다.
6. OK, NG 등의 문구는 가장 가까운 선이 아니라 실제로 연결된 화살표의 조건으로 기록한다.
7. 여러 공정이 동일한 선에 연결되어 있어도 병렬인지 순차인지 명확하지 않으면 execution_type을 "unknown"으로 기록한다.
8. 검사 항목, 참고 문서, 산출물은 반드시 공정 단계와 구분한다.
9. 판독할 수 없는 텍스트는 추측하지 말고 unreadable_text에 기록한다.
10. 연결이 불명확한 edge는 확정하지 말고 ambiguous_edges에 기록한다.
11. summary는 nodes와 edges에서 확인된 관계만 사용해 작성한다.
12. main_flow는 명확하게 연결된 경로만 포함한다. 끊어진 구간을 임의로 연결하지 않는다.

아래 스키마를 만족하는 유효한 JSON 객체만 출력한다. Markdown 코드 블록이나 설명은
출력하지 않는다.
{
  "diagram_type": "process_flow",
  "nodes": [
    {
      "id": "n1",
      "label": "도형 안의 원문 텍스트",
      "shape": "rectangle|rounded_rectangle|diamond|circle|parallelogram|unknown",
      "node_type": "start|process|decision|end|inspection|reference_document|output|input|unknown",
      "position": "top_left|top_center|top_right|middle_left|middle_center|middle_right|bottom_left|bottom_center|bottom_right",
      "confidence": "high|medium|low"
    }
  ],
  "edges": [
    {
      "source": "n1",
      "destination": "n2",
      "condition": "OK, NG 등의 화살표 조건 또는 빈 문자열",
      "direction": "down|up|left|right|mixed|unknown",
      "execution_type": "sequential|parallel|unknown",
      "confidence": "high|medium|low"
    }
  ],
  "main_flow": ["n1", "n2"],
  "unreadable_text": ["판독할 수 없는 텍스트의 위치와 이유"],
  "ambiguous_edges": [
    {
      "source": "n1 또는 빈 문자열",
      "destination": "n2 또는 빈 문자열",
      "reason": "확정할 수 없는 연결의 시각적 근거"
    }
  ],
  "summary": "확인된 흐름을 1~2문장으로 요약"
}

모든 node id는 화면을 위에서 아래, 왼쪽에서 오른쪽 순서로 n1, n2, n3처럼 생성하고,
모든 edge는 해당 id를 참조한다. 해당 항목이 없으면 빈 배열을 사용한다."""


def load_project_env() -> None:
    """독립 실행 시에도 프로젝트 루트 .env의 VLM 설정을 기본값으로 사용한다."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_url(base_url: str, path: str) -> str:
    """루트 URL 또는 /v1 URL 모두에 OpenAI 호환 경로를 붙인다."""
    base_url = base_url.rstrip("/")
    return f"{base_url}{path}" if base_url.endswith("/v1") else f"{base_url}/v1{path}"


def image_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0]
    if mime_type not in SUPPORTED_IMAGE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_TYPES))
        raise ValueError(f"지원하지 않는 이미지 형식입니다: {image_path.name} (지원: {supported})")

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def response_json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON이 아닌 응답입니다: {response.text}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"예상하지 못한 JSON 응답입니다: {payload}")
    return payload


def list_models(client: httpx.Client, base_url: str) -> list[str]:
    response = client.get(api_url(base_url, "/models"))
    response.raise_for_status()
    payload = response_json(response)
    models = payload.get("data", [])
    if not isinstance(models, list):
        raise RuntimeError(f"예상하지 못한 /v1/models 응답입니다: {payload}")
    return [model["id"] for model in models if isinstance(model, dict) and isinstance(model.get("id"), str)]


def select_qwen3_vl(models: list[str]) -> str:
    matches = [model for model in models if "qwen3-vl" in model.lower()]
    if not matches:
        available = ", ".join(models) or "없음"
        raise RuntimeError(f"Qwen3-VL 계열 모델을 찾지 못했습니다. 등록 모델: {available}")
    return matches[0]


def print_models(models: list[str]) -> None:
    print("[vLLM 등록 모델]")
    if not models:
        print("  없음")
        return
    for model in models:
        print(f"  - {model}")


def analyze_drawing(
    client: httpx.Client,
    base_url: str,
    model: str,
    image_path: Path,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict, float]:
    # Qwen3-VL cookbook의 image + text 메시지 순서를 따르되, vLLM OpenAI API에는
    # image_url 데이터 URI 형식으로 전달한다.
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
                {"type": "text", "text": prompt},
            ],
        }],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    started = time.perf_counter()
    response = client.post(api_url(base_url, "/chat/completions"), json=payload)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response_json(response), elapsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen3-VL vLLM 도면 이미지 해석 도구")
    parser.add_argument("--image", type=Path, help="분석할 로컬 도면 이미지(PNG, JPG, WebP, GIF)")
    parser.add_argument("--list-models", action="store_true", help="/v1/models의 등록 모델을 출력하고 종료")
    parser.add_argument("--base-url", default=os.getenv("VLM_API_URL", DEFAULT_BASE_URL), help="vLLM 서버 URL")
    parser.add_argument("--model", default=os.getenv("VLM_MODEL_NAME"), help="사용할 모델 ID (생략 시 Qwen3-VL 자동 탐색)")
    parser.add_argument(
        "--api-key",
        default=(
            os.getenv("VLM_API_KEY")
            or os.getenv("VLLM_VL_API_KEY")
            or os.getenv("VLLM_API_KEY", "EMPTY")
        ),
        help="vLLM Bearer API 키",
    )
    parser.add_argument("--prompt", default=PROCESS_FLOW_PROMPT, help="이미지 분석 프롬프트")
    parser.add_argument("--max-tokens", type=int, default=4096, help="최대 출력 토큰 수")
    parser.add_argument("--temperature", type=float, default=0.0, help="생성 온도")
    parser.add_argument("--timeout", type=float, default=180.0, help="연결·읽기 timeout(초)")
    return parser


def main() -> int:
    load_project_env()
    parser = build_parser()
    args = parser.parse_args()
    if not args.list_models and args.image is None:
        parser.error("--image 또는 --list-models 중 하나를 지정해야 합니다.")
    if args.image is not None and not args.image.is_file():
        parser.error(f"이미지 파일이 없습니다: {args.image}")
    if args.max_tokens <= 0 or args.timeout <= 0 or not 0.0 <= args.temperature <= 2.0:
        parser.error("--max-tokens와 --timeout은 양수이고, --temperature는 0.0~2.0이어야 합니다.")

    headers = {"Authorization": f"Bearer {args.api_key}"}
    timeout = httpx.Timeout(args.timeout)
    try:
        with httpx.Client(headers=headers, timeout=timeout) as client:
            if args.list_models:
                print_models(list_models(client, args.base_url))
                return 0

            model = args.model
            if not model:
                model = select_qwen3_vl(list_models(client, args.base_url))
                print(f"자동 선택 모델: {model}")

            result, elapsed = analyze_drawing(
                client, args.base_url, model, args.image, args.prompt, args.max_tokens, args.temperature
            )
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code} ({exc.request.url})", file=sys.stderr)
        print(exc.response.text, file=sys.stderr)
        return 1
    except (httpx.RequestError, OSError, RuntimeError, ValueError) as exc:
        print(f"vLLM 호출 실패: {exc}", file=sys.stderr)
        return 1

    choices = result.get("choices") or []
    content = choices[0].get("message", {}).get("content") if choices else None
    if not content:
        print(f"분석 결과가 비어 있습니다: {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)
        return 1

    print(f"\n[도면 분석 결과: {model}]")
    print(content)
    print(f"\n처리 시간: {elapsed:.2f}초")
    print(f"종료 사유: {choices[0].get('finish_reason')}")
    print(f"Token usage: {json.dumps(result.get('usage', {}), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
