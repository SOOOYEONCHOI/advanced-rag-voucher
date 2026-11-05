#!/usr/bin/env python
"""디자인 토큰을 거치지 않은 색·서체가 남아 있는지 찾는다.

세 네임스페이스는 tokens.css 한 곳에 모은다. CSS 에
색 리터럴을 직접 쓰면 다시 흩어지므로 여기서 막는다.

    python scripts/verify/verify_tokens.py

허용 예외는 ALLOW 에 이유와 함께 적는다. 이유 없이 늘리지 않는다.
"""
import colorsys
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

# 단일 원천. 여기서만 색 리터럴을 선언한다.
TOKENS = ROOT / 'app' / 'static' / 'assets' / 'css' / 'tokens.css'

# 유채색 리터럴을 한 점도 허용하지 않는 파일. 전수 치환한 곳이다.
STRICT = [
    ROOT / 'app' / 'static' / 'data' / 'main.css',
    ROOT / 'app' / 'static' / 'data' / 'governance.css',
    ROOT / 'app' / 'static' / 'data' / 'preview.css',
]

# MES 계열은 브랜드 빨강과 데이터 청록만 토큰으로 바꿨고 나머지 유채색(링크
# 파랑 등)이 남아 있다. 그래서 전수 금지가 아니라 지목한 리터럴만 막는다.
BANNED = {
    '#ea1b1b': '브랜드 빨강은 var(--brand-primary)',
    '#16a5a3': '데이터 청록은 var(--brand-primary)',
    '#003597': '그리드 남색은 var(--brand-primary)',
}
BANNED_IN = [
    ROOT / 'app' / 'static' / 'assets' / 'css' / 'SF-Custom.css',
    ROOT / 'app' / 'static' / 'assets' / 'css' / 'SF-login.css',
]

HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')

# 흑·백은 토큰을 거칠 필요가 없다. 그 외의 유채색만 본다.
ALLOW = {'#ffffff', '#000000'}


def _norm(h):
    x = h.lstrip('#').lower()
    if len(x) == 3:
        x = ''.join(c * 2 for c in x)
    return '#' + x[:6]


def _chromatic(h):
    """회색 계열이면 False. 유채색만 토큰을 요구한다."""
    x = _norm(h).lstrip('#')
    r, g, b = (int(x[i:i + 2], 16) / 255 for i in (0, 2, 4))
    _, _, s = colorsys.rgb_to_hls(r, g, b)
    return s >= 0.08


def main():
    violations = []

    for path in STRICT:
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for raw in HEX.findall(line):
                if _norm(raw) in ALLOW or not _chromatic(raw):
                    continue
                violations.append(('색', rel, lineno, raw, line.strip()[:66]))
            # 서체는 tokens.css 의 --font-sans 한 곳으로 모은다.
            if ('font-family' in line
                    and 'var(--font-sans)' not in line
                    and 'monospace' not in line):
                violations.append(('서체', rel, lineno, 'font-family 직접 선언', ''))

    for path in BANNED_IN:
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for raw in HEX.findall(line):
                why = BANNED.get(_norm(raw))
                if why:
                    violations.append(('금지', rel, lineno, raw, why))

    if not TOKENS.exists():
        violations.append(('없음', TOKENS.relative_to(ROOT), 0, 'tokens.css 가 없다', ''))

    for kind, rel, lineno, what, ctx in violations:
        print('{:4} {}:{}  {}  {}'.format(kind, rel, lineno, what, ctx))

    print('\n토큰을 거치지 않은 선언 {}건'.format(len(violations)))
    print('PASS' if not violations else 'FAIL')
    return 0 if not violations else 1


if __name__ == '__main__':
    sys.exit(main())
