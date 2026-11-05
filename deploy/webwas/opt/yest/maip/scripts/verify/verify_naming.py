#!/usr/bin/env python
"""폐기한 원본 프로젝트 이름이 소스와 살아 있는 문서에 남지 않았는지 본다.

제품 이름은 **제조AI플랫폼** 하나다. `AIDataHub` 와 `vision-inspection` 은 이
프로젝트를 만들 때 기능을 가져온 원본 저장소의 이름이고, 더는 쓰지 않기로
했다(사용자 결정, 2026-10-04 · 2026-10-06).

**혼동하기 쉬운 셋은 잡지 않는다.** `vision_inspection` 은 테이블 이름이고
`vision/inspection` 은 우리 모듈 경로다 — 그래서 `vision-inspection` 은
**하이픈이 있는 것만** 금지한다. `VisionInspectionClient` 는 클라이언트
배포물 이름이자 계약 값이라(zip 파일명 · `/api/v1/client-packages` 응답)
금지 대상이 아니다.

    python scripts/verify/verify_naming.py

**기록 문서(`docs/archive/`)는 보지 않는다.** 통합 당시의 분석·계획·결정
원문은 세 원본을 비교하는 것이 주제 자체라, 이름을 빼면 표와 결정 기록이
뜻을 잃는다. 외부 계약(`docs/client/`)도 보지 않는다. 지운 주석이 무엇이었는지는 git 이력에 남는다.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

BANNED = [
    (re.compile(r'aidatahub', re.IGNORECASE), '데이터 관리 원본 저장소'),
    # 하이픈만 잡는다. `vision_inspection`(테이블) · `vision/inspection`(모듈)은
    # 우리 것이고, `VisionInspectionClient` 는 계약 값이다.
    (re.compile(r'vision-inspection', re.IGNORECASE), '비전 검사 원본 저장소'),
]

SOURCE_DIRS = ['app', 'domain', 'configurations', 'scripts', 'tests']
SOURCE_SUFFIX = {'.py', '.html', '.js', '.css'}

# 계속 읽히고 갱신되는 문서 — 루트 세 개와 docs/ 바로 아래 전부. 목록으로 적으면
# 문서 이름이 바뀔 때 조용히 빠진다. docs/archive·docs/client 는 하위 폴더라 빠진다.
LIVING_DOCS = ['AGENTS.md', 'README.md', 'DESIGN.md', 'distribution/README.md']
LIVING_DOC_GLOB = 'docs/*.md'

# 이름을 적을 수밖에 없는 곳.
#
# - 공유 PostgreSQL 설명의 `aidatahub` 는 **다른 프로젝트의 데이터베이스
#   이름**이다(우리 것은 `yest`). 지우면 문장이 거짓이 되고, pg_stat_activity
#   결과에서 남의 DB 를 알아볼 수 없다.
# - 규칙 자체를 적은 문단과 이 검사를 소개하는 줄은 금지어를 담아야 뜻이 선다.
ALLOWED = {
    ('AGENTS.md', '`aidatahub` 등)'),
    ('AGENTS.md', '(`AIDataHub` · `vision-inspection`)은'),
    ('AGENTS.md', '공유 PostgreSQL 설명에 나오는'),
    ('AGENTS.md', 'verify_naming.py'),
    ('docs/DEVELOPMENT.md', '`aidatahub` 등. 우리 DB 는'),
}


SELF = pathlib.Path(__file__).resolve()


def targets():
    for name in SOURCE_DIRS:
        for path in sorted((ROOT / name).rglob('*')):
            # 이 스크립트는 금지어를 담을 수밖에 없다.
            if path.resolve() == SELF:
                continue
            if path.is_file() and path.suffix in SOURCE_SUFFIX:
                yield path
    for name in LIVING_DOCS:
        yield ROOT / name   # 없으면 읽다가 실패한다 — 조용히 건너뛰지 않는다
    yield from sorted(ROOT.glob(LIVING_DOC_GLOB))


def main():
    hits = []
    for path in targets():
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for pattern, why in BANNED:
                if not pattern.search(line):
                    continue
                if any(rel == f and snippet in line for f, snippet in ALLOWED):
                    continue
                hits.append((rel, lineno, why, line.strip()[:60]))

    for rel, lineno, why, text in hits:
        print('잔재  {}:{}  [{}]  {}'.format(rel, lineno, why, text))

    print('\n폐기한 원본 이름 {}건'.format(len(hits)))
    print('PASS' if not hits else 'FAIL')
    return 0 if not hits else 1


if __name__ == '__main__':
    sys.exit(main())
