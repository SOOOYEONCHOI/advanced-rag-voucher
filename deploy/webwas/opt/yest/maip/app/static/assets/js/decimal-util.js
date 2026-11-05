/**
 * MES·WeZonGrid의 공통 소수 처리 규칙. decimal.js 원본이 아닌 프로젝트용 래퍼다.
 * 실제 사칙연산·비교·반올림은 decimal.js 10.6.0이 수행한다.
 *
 * 의존성과 로딩 순서:
 *   decimal.js → decimal-util.js → wezongrid.js 및 DecimalUtil을 사용하는 화면 코드.
 * 이 파일을 평가하는 즉시 전역 Decimal.clone()을 호출하므로 decimal.js가 먼저 필요하다.
 * 두 파일은 브라우저 정적 자산이며 Python requirements.txt의 설치 대상이 아니다.
 * Python 서버의 decimal은 표준 라이브러리로 별도 pip 설치가 필요 없다.
 *
 * 정밀도와 반환값:
 * - 원본 전역 Decimal 설정을 바꾸지 않고, 유효숫자 50자리인 별도 생성자 D를 사용한다.
 *   50은 소수점 아래 자리수가 아니다. 연산은 이 유효숫자 범위에서 반올림될 수 있다.
 * - 큰 소수는 처음부터 문자열로 전달한다. 이미 Number로 손실된 끝자리는 복원할 수 없다.
 * - 사칙연산 결과는 문자열, toDecimal/parse는 Decimal 객체, 비교는 숫자/boolean을 반환한다.
 *   결과를 Number/parseFloat로 되돌리면 소수 정밀도가 다시 손실될 수 있다.
 *
 * 반올림과 표시:
 * - input(value)은 유효한 입력을 소수 3자리 ROUND_HALF_UP 문자열로 확정한다.
 *   예: '1.2345' → '1.235', '-1.2345' → '-1.235'. 항상 올림하는 규칙은 아니다.
 * - add/sub/mul/div는 매번 소수 3자리로 자르지 않는다. round/format은 자리수 지정 가능.
 * - formatPattern은 쉼표·0/# 소수 자리·퍼센트를 표시하는 현재 Decimal 전용 경로다.
 *   표시 결과를 DB 저장용 원값으로 사용하지 않는다. 그리드의 기존 Number 포맷과는 별도다.
 *
 * 오류 처리:
 * - toDecimal/input은 빈값·NaN·Infinity를 거부한다. parse는 실패 시 지정한 기본값을 반환한다.
 * - 계산·표시 래퍼는 잘못된 입력을 NaN으로 전달하므로 'NaN' 문자열이 반환될 수 있다.
 *   계산 결과(예: 0으로 나눈 Infinity)의 최종 유효성 검사는 입력/저장 경계에서 수행한다.
 */
(function (root) {
    'use strict';
    // clone으로 이 프로젝트의 계산 설정을 격리한다. 다른 화면의 전역 Decimal 설정은 유지한다.
    const D = root.Decimal.clone({ precision: 50, rounding: root.Decimal.ROUND_HALF_UP,
        toExpNeg: -100, toExpPos: 100 });
    // 엄격한 변환: 문자열을 통해 읽고 유한한 값만 허용한다. boolean은 기존 0/1 규칙을 따른다.
    function toDecimal(value) {
        if (value === null || value === undefined || String(value).trim() === '') {
            throw new TypeError('A decimal value is required');
        }
        const result = new D(typeof value === 'boolean' ? (value ? 1 : 0) : String(value).trim());
        if (!result.isFinite()) throw new RangeError('A finite decimal value is required');
        return result;
    }
    // 화면의 빈값/잘못된 입력을 예외 대신 기본값으로 처리할 때 사용한다.
    function parse(value, defaultValue = null) {
        try { return toDecimal(value); } catch (_) { return defaultValue; }
    }
    // 편집 중 잘못된 값은 기존 NaN 흐름으로 유지한다. 확정 입력에는 input()을 사용한다.
    const operand = value => parse(value) || new D(NaN);
    const compare = (a, b) => operand(a).comparedTo(operand(b));
    // input()이 사용하는 엄격한 반올림. 아래 공개 round()는 NaN을 허용하므로 계약이 다르다.
    function round(value, places = 3) {
        return toDecimal(value).toFixed(places, D.ROUND_HALF_UP);
    }
    // 화면 표시 전용: #는 선택 소수 자리, 0은 필수 소수 자리, %는 100배 표시를 뜻한다.
    // 전체 Intl/DecimalFormat 문법을 구현한 함수가 아니며 숫자 패턴 부분만 해석한다.
    function formatPattern(value, pattern) {
        let number = parse(value);
        if (!number) return value == null ? '' : String(value);
        if (!pattern) return number.toFixed();
        const percent = pattern.includes('%');
        if (percent) number = number.times(100);
        const match = pattern.match(/[#,0]+(?:\.([0#]+))?/);
        if (!match) return number.toFixed();
        const decimals = match[1] || '';
        const minPlaces = decimals.lastIndexOf('0') + 1;
        let parts = number.toFixed(decimals.length, D.ROUND_HALF_UP).split('.');
        if (match[0].includes(',')) parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        if (parts[1]) {
            while (parts[1].length > minPlaces && parts[1].endsWith('0')) parts[1] = parts[1].slice(0, -1);
        }
        return parts[0] + (parts[1] ? '.' + parts[1] : '') + (percent ? '%' : '');
    }
    // 공개 API: 문자열 반환으로 그리드·JSON 전송 중 Number 재변환을 피한다.
    // 호출 예: add('0.1', '0.2') → '0.3', input('1.2345') → '1.235'.
    root.DecimalUtil = Object.freeze({
        toDecimal, parse, input: value => round(value),
        round: (value, places = 3) => operand(value).toFixed(places, D.ROUND_HALF_UP),
        add: (a, b) => operand(a).plus(operand(b)).toString(),
        sub: (a, b) => operand(a).minus(operand(b)).toString(),
        mul: (a, b) => operand(a).times(operand(b)).toString(),
        div: (a, b) => operand(a).div(operand(b)).toString(),
        compare, eq: (a, b) => compare(a, b) === 0,
        lt: (a, b) => compare(a, b) < 0, lte: (a, b) => compare(a, b) <= 0,
        gt: (a, b) => compare(a, b) > 0, gte: (a, b) => compare(a, b) >= 0,
        ceil: value => operand(value).ceil().toString(),
        format: (value, places = 3) => operand(value).toFixed(places, D.ROUND_HALF_UP), formatPattern
    });
})(typeof window !== 'undefined' ? window : globalThis);
