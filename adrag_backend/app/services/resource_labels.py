"""사진(스프레드시트 리소스) 표시 규칙 — 제목·역할 라벨·표시 가능 여부 (2026.10.19, R4-3 / UI-03·UI-05).

답변 사진(app/graphs/images.py)과 사진 목록 API(GET /api/documents/{id}/spreadsheet-resources)가 같은 규칙을 쓴다.
"""
from __future__ import annotations

from typing import Any

EXCLUDED_ROLES = {"decoration", "form_header"}
ROLE_LABELS = {
    "step_photo": "Step 사진", "same_image_as_step_photo": "Step 사진", "detail_view": "확대도",
    "drawing": "도면", "part_photo": "부품 사진", "flowchart": "흐름도", "step_related": "Step 관련 그림",
    "figure": "그림",
}
# 브라우저 <img>로 표시할 수 있는 형식만(svg는 스크립트를 담을 수 있어 제외, emf·wmf는 변환 전까지 제외 — Phase 5)
DISPLAYABLE_MIME_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"]


def resource_title(resource: dict[str, Any]) -> str:
    """예: "시트 Step 6 단계명 Step 사진", Step이 없으면 "시트 부품 사진 - 주변 텍스트 앞 60자"."""
    parts = [resource.get("sheet_name")]
    if resource.get("step_no") is not None:
        parts.append(f"Step {resource['step_no']}")
    if resource.get("step_title"):
        parts.append(str(resource["step_title"]))
    parts.append(ROLE_LABELS.get(resource.get("role_cd") or "", "이미지"))
    # Step이 없는 사진(부품 사진 등)은 주변 텍스트(부품명·품번)로 구별한다
    if resource.get("step_no") is None and resource.get("surrounding_text"):
        context = " ".join(str(resource["surrounding_text"]).split())
        parts.append(f"- {context[:60]}")
    return " ".join(str(p) for p in parts if p)


def is_displayable(resource: dict[str, Any]) -> bool:
    """화면에 보여줄 사진인지: 브라우저 표시 가능 형식, 장식·양식 머리글 아님, 검수에서 "연결 안 함" 아님, 삭제 안 됨."""
    return (
        resource.get("mime_type") in DISPLAYABLE_MIME_TYPES
        and resource.get("role_cd") not in EXCLUDED_ROLES
        and resource.get("review_status") != "unlinked"
        and resource.get("status") != "deleted"
    )
