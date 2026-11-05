#!/usr/bin/env python
"""템플릿이 거는 내부 링크와 정적 파일, 현행 문서의 참조가 실제로 있는지 본다.

이식 과정에서 원본 프로젝트의 URL 이 그대로 남은 곳이 있다 — 데이터 화면의
`/projects/` · `/dataset/manage/` · `/workspace/versions/` 가 그랬다. 이
프로젝트의 화면은 전부 `/gui/<gui_code>/` 로 뜨므로 그 링크는 404 다.
누르기 전에는 드러나지 않고, 화면을 열기만 하는 capture_ui.py 도 못 잡는다.

    python scripts/verify/verify_links.py

`href`·폼 `action`·따옴표 안의 `/api/...` 문자열을 모아 **경로 전체를 라우터로
해석한다.** 처음에는 첫 조각만 봤는데, 그래서 검사항목 목록 폼의
`/api/data/admin/items/commands/`(라우트가 없어 404)를 놓쳤다. 문자열을 `+` 로
이어 붙이는 경로(`'/api/data/items/' + id + '/members/'`)는 뒤를 알 수 없어
첫 조각만 본다. `/api/<task>/<view>` · `/page/<folder>/<name>`
는 라우터가 무엇이든 받으므로 뒤에 실제 모듈·템플릿이 있는지까지 본다.

`{% static '...' %}` 은 파일이 없어도 템플릿이 조용히 경로를 뱉고 브라우저만
404 를 받는다 — 스타일시트면 화면이 통째로 민짜가 된다. 그래서 실제 파일이
있는지 함께 본다.
"""
import os
import pathlib
import re
import sys

import django

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'configurations.settings')
django.setup()

from django.conf import settings  # noqa: E402
from django.urls import Resolver404, get_resolver, resolve  # noqa: E402

TEMPLATES = ROOT / 'app' / 'templates'
VIEWS = ROOT / 'app' / 'views'
# 데이터 화면의 공통 스크립트도 경로를 건다.
SCRIPTS = sorted((ROOT / 'app' / 'static' / 'data').glob('*.js'))

# href="/..." · href: '/...' · location.href = '/...' · .attr('href', '/...') · action="/..."
# 그리고 따옴표 안의 '/api/...'. 닫는 따옴표 뒤에 `+` 가 오면 이어 붙이는 경로다.
ATTR = r"""(?:href\s*[:=]\s*|location\.href\s*=\s*|attr\(\s*['"]href['"]\s*,\s*|action\s*[:=]\s*)"""
LINK = re.compile(ATTR + r"""['"](/[^'"#?\s]*)[^'"]*['"](\s*\+)?"""
                  + r"""|['"](/api/[^'"#?\s]*)[^'"]*['"](\s*\+)?""")

# /* ... */ · <!-- ... -->. `accept="image/*"` 같은 값은 주석이 아니다(앞이 단어·따옴표).
BLOCK_COMMENT = re.compile(r"""(?<![\w"'])/\*.*?\*/|<!--.*?-->""", re.S)

# 라우팅을 거치지 않는 것들.
SKIP_ROOTS = {'static', 'media'}


def url_roots():
    """URLconf 최상위 경로의 첫 조각을 모은다."""
    roots = set()
    for pattern in get_resolver().url_patterns:
        text = str(getattr(pattern, 'pattern', ''))
        first = text.lstrip('^').split('/')[0]
        if first and '<' not in first and not first.startswith('('):
            roots.add(first)
    return roots


def target_exists(match):
    """무엇이든 받는 동적 라우트 뒤에 실제 모듈·템플릿이 있는가."""
    kwargs = match.kwargs
    if match.url_name == 'api':
        return (VIEWS / kwargs['task_name'] / (kwargs['view_name'] + '.py')).exists()
    if match.url_name == 'page':
        return (TEMPLATES / 'page' / kwargs['folder'] / (kwargs['template_name'] + '.html')).exists()
    return True


def broken(url, concatenated, roots):
    """이 링크가 없는 곳을 가리키면 True."""
    first = url.strip('/').split('/')[0]
    if not first or first in SKIP_ROOTS:   # 루트 '/' 는 언제나 있다
        return False
    if concatenated or '{' in url:         # 뒤가 런타임에 붙거나 템플릿 변수다
        return first not in roots
    try:
        return not target_exists(resolve(url))
    except Resolver404:
        pass
    # CommonMiddleware 의 APPEND_SLASH 가 '/login' 을 '/login/' 로 돌려보낸다.
    if settings.APPEND_SLASH and not url.endswith('/'):
        try:
            return not target_exists(resolve(url + '/'))
        except Resolver404:
            pass
    return True


STATIC = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]""")
STATIC_DIRS = [ROOT / 'app' / 'static']


def missing_static():
    """{% static %} 이 가리키는 파일이 없는 곳을 찾는다."""
    hits = []
    for path in sorted(TEMPLATES.rglob('*.html')):
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for rel in STATIC.findall(line):
                if any((d / rel).exists() for d in STATIC_DIRS):
                    continue
                hits.append((path.relative_to(TEMPLATES).as_posix(), lineno, rel))
    return hits


# ── 문서 참조 ───────────────────────────────────────────────────────────────
# 현행 문서는 다른 문서를 링크 대신 "FEATURES §8" 처럼 글자로 가리키고, 결정은 절 머리의
# "근거: DECISIONS …" 줄로 가리킨다. 글자 참조는 깨져도 아무도 모르므로 여기서 본다.
DOCS = {name: ROOT / (name + '.md') for name in ('AGENTS', 'README', 'DESIGN')}
DOCS.update({path.stem: path for path in sorted((ROOT / 'docs').glob('*.md')) if path.stem != 'README'})
DOCS['계약'] = ROOT / 'docs' / 'client' / 'SERVER_API_CONTRACT.md'
DOC_FILES = [DOCS['AGENTS'], DOCS['README'], DOCS['DESIGN']] + sorted((ROOT / 'docs').glob('*.md'))

HEADING = re.compile(r'#+\s*(?:\[(\d+)\]|(\d+(?:[.\-]\d+)*)\.?)\s')
SECTION_REF = re.compile(r'(?<![\w/])(' + '|'.join(sorted(map(re.escape, DOCS), key=len, reverse=True))
                         + r')(?:\.md)?\)?\s*(?:§\s*(\d+(?:[.\-]\d+)*)|\[(\d)\])')
MD_LINK = re.compile(r'\]\(([^)\s]+)\)')
DECISION_ID = re.compile(r'\b(DEC-C?\d+|O-\d+|Q\d+|F-\d+)\b')
DATE = re.compile(r'20\d\d-\d\d-\d\d')


def _sections(path):
    found = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        m = HEADING.match(line)
        if m:
            found.add(m.group(1) or m.group(2))
    return found


def broken_doc_refs():
    """현행 문서의 md 링크·"문서 §절" 글자 참조·근거 줄의 결정 ID 가 실제로 있는지 본다."""
    sections = {name: _sections(path) for name, path in DOCS.items()}
    decisions = DOCS['DECISIONS'].read_text(encoding='utf-8')
    hits = []
    for path in DOC_FILES:
        fenced = False
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if line.lstrip().startswith('```'):
                fenced = not fenced
            if fenced:
                continue
            where = '{}:{}'.format(path.relative_to(ROOT).as_posix(), lineno)
            for target in MD_LINK.findall(line):
                target = target.split('#')[0]
                if target and '://' not in target and not target.startswith('mailto:') \
                        and not (path.parent / target).exists():
                    hits.append((where, 'md 링크 ' + target))
            for name, sec, bracket in SECTION_REF.findall(line):
                if (sec or bracket) not in sections[name]:
                    hits.append((where, '{} §{} 절 없음'.format(name, sec or bracket)))
            if line.startswith('근거:'):
                for ref in DECISION_ID.findall(line):
                    if not re.search(r'^\|\s*' + re.escape(ref) + r'\b', decisions, re.M):
                        hits.append((where, '결정 {} 없음'.format(ref)))
                for date in DATE.findall(line):
                    if '사용자 결정({}'.format(date) not in decisions:
                        hits.append((where, '사용자 결정 {} 없음'.format(date)))
    return hits


def main():
    roots = url_roots() | SKIP_ROOTS
    hits = []
    for path in sorted(TEMPLATES.rglob('*.html')) + SCRIPTS:
        # 블록 주석으로 막아 둔 코드는 돌지 않는다. 줄 번호를 지키려고 줄바꿈은 남긴다.
        text = BLOCK_COMMENT.sub(lambda m: '\n' * m.group().count('\n'),
                                 path.read_text(encoding='utf-8'))
        for lineno, line in enumerate(text.splitlines(), 1):
            # 주석으로 막아 둔 줄은 돌지 않는다. '//' 가 URL 안의 '//' 가 아닐 때만.
            comment = re.search(r'(?<!:)//', line)
            if comment:
                line = line[:comment.start()]
            for attr_url, attr_plus, api_url, api_plus in LINK.findall(line):
                url = attr_url or api_url
                if broken(url, bool(attr_plus or api_plus), roots):
                    hits.append((path.relative_to(ROOT).as_posix(), lineno, url))

    for rel, lineno, url in hits:
        print('없는 경로  {}:{}  {}'.format(rel, lineno, url))

    static_hits = missing_static()
    for rel, lineno, name in static_hits:
        print('없는 파일  {}:{}  static {}'.format(rel, lineno, name))

    doc_hits = broken_doc_refs()
    for where, what in doc_hits:
        print('문서 참조  {}  {}'.format(where, what))

    total = len(hits) + len(static_hits) + len(doc_hits)
    print('\n없는 경로를 거는 링크 {}건 / 없는 정적 파일 {}건 / 깨진 문서 참조 {}건'.format(
        len(hits), len(static_hits), len(doc_hits)))
    print('PASS' if not total else 'FAIL')
    return 0 if not total else 1


if __name__ == '__main__':
    sys.exit(main())
