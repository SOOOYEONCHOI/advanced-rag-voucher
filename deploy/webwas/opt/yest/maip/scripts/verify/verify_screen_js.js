/**
 * 화면 템플릿 안 <script> 블록을 검사한다.
 *
 * 1) JS 문법 — 템플릿의 인라인 스크립트는 서버가 렌더할 때까지 아무도 파싱하지
 *    않는다. 문법이 깨져도 화면을 실제로 열어 보기 전에는 드러나지 않는다.
 * 2) AjaxUtil 콜백의 `this` — `function (result) {...}` 콜백 안에서 `this` 는
 *    화면 객체가 아니라 jQuery ajax 컨텍스트다. 화면들이 `let _this = this` 를
 *    잡아두고 콜백 안에서 `this.grid` 라고 쓰면 응답은 200 인데 그리드에 꽂히지
 *    않고 조용히 실패한다. 문법상 완전히 유효해서 1) 로는 잡히지 않는다.
 *    화살표 함수는 `this` 를 그대로 물려받으므로 검사 대상이 아니다.
 *
 *    한계: `let fn = function (r) {...}` 로 먼저 만들고 이름만 넘기는 형태는
 *    호출 지점에서 본문이 보이지 않아 잡지 못한다.
 *
 *   node scripts/verify/verify_screen_js.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..', '..', 'app');
const SCRIPT_BLOCK = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;

function walk(dir, out = []) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            walk(full, out);
        } else if (/\.(html|js)$/i.test(entry.name)) {
            out.push(full);
        }
    }
    return out;
}

/** Django 템플릿 태그를 같은 길이의 공백으로 바꿔 줄·열 번호를 보존한다. */
function stripDjango(source) {
    return source.replace(/\{%[\s\S]*?%\}|\{\{[\s\S]*?\}\}/g, (m) =>
        m.replace(/[^\n]/g, ' '));
}

/** 줄 주석을 같은 길이의 공백으로 지운다. 주석 속 this 는 검사 대상이 아니다. */
function stripLineComments(source) {
    return source.replace(/\/\/[^\n]*/g, (m) => ' '.repeat(m.length));
}

/**
 * AjaxUtil.*AsyncData 에 넘긴 function 콜백 본문에서 바인딩이 끊긴 `this.` 를 찾는다.
 * 반환: [{ line, text }]
 */
function findUnboundThis(code) {
    const source = stripLineComments(code);
    const call = /AjaxUtil\.(?:get|post)AsyncData\s*\(/g;
    const hits = [];
    let match;

    while ((match = call.exec(source)) !== null) {
        // 인자 안에 객체 리터럴이 먼저 올 수 있으므로 콜백 `function (…) {` 를
        // 첫 `{` 가 아니라 패턴으로 찾는다. 다음 AjaxUtil 호출 전까지만 본다.
        const nextCall = source.indexOf('AjaxUtil.', match.index + 1);
        const scope = source.slice(match.index, nextCall === -1 ? source.length : nextCall);
        const callback = /function\s*\([^)]*\)\s*\{/.exec(scope);
        if (!callback) continue;

        const open = match.index + callback.index + callback[0].length - 1;
        let depth = 0;
        let end = -1;
        for (let i = open; i < source.length; i += 1) {
            if (source[i] === '{') depth += 1;
            else if (source[i] === '}') {
                depth -= 1;
                if (depth === 0) { end = i; break; }
            }
        }
        if (end === -1) continue;

        const body = source.slice(open, end);
        const bodyStartLine = source.slice(0, open).split('\n').length;
        body.split('\n').forEach((text, idx) => {
            if (/(?<![\w.$])this\./.test(text)) {
                hits.push({ line: bodyStartLine + idx, text: text.trim() });
            }
        });
    }
    return hits;
}

let failures = 0;
let checked = 0;
let bindingFailures = 0;

for (const file of walk(ROOT)) {
    const relative = path.relative(ROOT, file);
    // 외부 라이브러리 번들은 검사 대상이 아니다.
    if (/vendor|\.min\.js$/i.test(relative)) continue;

    const source = fs.readFileSync(file, 'utf8');
    const blocks = [];

    if (file.endsWith('.js')) {
        blocks.push({ code: source, offset: 0 });
    } else {
        let match;
        SCRIPT_BLOCK.lastIndex = 0;
        while ((match = SCRIPT_BLOCK.exec(source)) !== null) {
            // 템플릿 엔진용 블록(text/x-tmpl)은 JS 가 아니다.
            if (/type\s*=\s*["']text\/x-tmpl["']/i.test(match[1])) continue;
            if (/\bsrc\s*=/i.test(match[1])) continue;
            const offset = source.slice(0, match.index).split('\n').length;
            blocks.push({ code: match[2], offset });
        }
    }

    for (const block of blocks) {
        checked += 1;
        try {
            new vm.Script(stripDjango(block.code), { filename: relative });
        } catch (error) {
            failures += 1;
            const line = (error.stack || '').match(/:(\d+)/);
            const at = line ? block.offset + Number(line[1]) : block.offset;
            console.log(`FAIL ${relative}:~${at}  ${error.message}`);
        }

        for (const hit of findUnboundThis(block.code)) {
            bindingFailures += 1;
            console.log(`BIND ${relative}:${block.offset + hit.line}  ${hit.text}`);
        }

    }
}

console.log(`\n스크립트 블록 ${checked}개 검사 / 문법 실패 ${failures}건 / this 바인딩 ${bindingFailures}건`);
const total = failures + bindingFailures;
console.log(total === 0 ? 'PASS' : 'FAIL');
process.exit(total === 0 ? 0 : 1);
