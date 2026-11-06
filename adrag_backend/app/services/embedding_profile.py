"""현재 검색 경로의 임베딩 프로필 (2026.11.06(sooyeon.choi) 수정 - 신규, UI-12 이전 버전 복원, 설계 v1.1 5.5·9.2).

- 모델명·차원·질의 인코딩 설정·sparse/kiwi 구성 등 벡터 의미 공간을 결정하는 설정값을 정규화해 해시한다.
  같은 차원·같은 모델명만으로 호환을 판단하지 않는다(설정이 하나라도 다르면 다른 프로필).
- 적재 성공 시 버전에 현재 프로필 ID를 기록하고, 복원은 버전 프로필 = 현재 프로필일 때만 허용한다.
- 프로필 행은 해시 기준으로 한 번만 만든다(현재 프로필은 is_supported=true).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from app.core.config import get_settings
from app.repositories.database import get_database_manager

# 벡터 정의에 영향을 주는 설정 이름(값이 바뀌면 새 프로필)
_PROFILE_SETTINGS = (
    "embedding_provider",
    "embedding_model_name",
    "embedding_dim",
    "embedding_instruct_template",
    "embedding_truncate_prompt_tokens",
    "sparse_encoder_type",
    "kiwi_bm25_vector_name",
    "kiwi_bm25_encoder_version",
)


def current_profile_definition(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {name: getattr(settings, name, None) for name in _PROFILE_SETTINGS}


def profile_hash(definition: dict[str, Any]) -> str:
    canonical = json.dumps(definition, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_current_profile_id(db=None, settings=None) -> int:
    """현재 프로필 행 ID(없으면 만든다). 호출자 트랜잭션 안에서도 쓸 수 있다."""
    db = db or get_database_manager()
    definition = current_profile_definition(settings)
    digest = profile_hash(definition)
    rows = db.execute_query(
        """INSERT INTO tb_embedding_profiles (profile_hash, definition_json, is_supported)
           VALUES (?, ?, true)
           ON CONFLICT (profile_hash) DO UPDATE SET is_supported = true
           RETURNING embedding_profile_id""",
        (digest, json.dumps(definition, ensure_ascii=False, default=str)),
    )
    return int(rows[0][0])


def current_profile_id(db=None, settings=None) -> Optional[int]:
    """조회 전용: 현재 프로필 행이 아직 없으면 None(아직 이 설정으로 적재한 버전이 없다는 뜻)."""
    db = db or get_database_manager()
    rows = db.execute_query(
        "SELECT embedding_profile_id FROM tb_embedding_profiles WHERE profile_hash = ? AND is_supported",
        (profile_hash(current_profile_definition(settings)),),
    )
    return int(rows[0][0]) if rows else None
