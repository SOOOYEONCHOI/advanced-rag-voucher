import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional


class ManualDisplayService:
    # 2026.07.10(sooyeon.choi) 추가 - 매뉴얼 citation 표시용 원본 PDF 매핑 처리
    def __init__(self, base_dir: Optional[Path] = None):
        self.backend_root = Path(__file__).resolve().parents[2]
        self.base_dir = (base_dir or self.backend_root / "instance" / "manual_display").resolve()
        self.map_path = self.base_dir / "manual_citation_map.json"
        self.pdf_dir = self.base_dir / "pdf"
        # 2026.07.10(sooyeon.choi) 추가 - Docker 신규 instance 환경에서 표시용 PDF 디렉터리 자동 생성
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _to_page(value: Any, default: int = 1) -> int:
        try:
            page = int(value)
        except (TypeError, ValueError):
            return default
        return page if page > 0 else default

    @lru_cache(maxsize=1)
    def _load_map_cached(self, map_path: str) -> Dict[str, Any]:
        path = Path(map_path)
        if not path.is_file():
            return {}
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def load_map(self) -> Dict[str, Any]:
        return self._load_map_cached(str(self.map_path))

    def resolve(self, filename: str, page: Any) -> Dict[str, Any]:
        original_page = self._to_page(page)
        fallback = {
            "mapped": False,
            "display_filename": filename,
            "display_page": original_page,
        }
        if not filename:
            return fallback

        entry = self.load_map().get(filename)
        if not isinstance(entry, dict):
            return fallback

        display_source = entry.get("display_source")
        page_map = entry.get("page_map")
        if not display_source or not isinstance(page_map, dict):
            return fallback

        if str(original_page) not in page_map:
            return fallback

        mapped_page = self._to_page(page_map.get(str(original_page)), original_page)
        return {
            "mapped": True,
            "display_filename": str(display_source),
            "display_page": mapped_page,
        }

    def resolve_pdf_path(self, display_filename: str) -> Path:
        if not display_filename or Path(display_filename).name != display_filename:
            raise ValueError("Invalid manual display filename")

        pdf_root = self.pdf_dir.resolve()
        file_path = (pdf_root / display_filename).resolve()
        try:
            file_path.relative_to(pdf_root)
        except ValueError as exc:
            raise ValueError("Invalid manual display filename") from exc
        return file_path
