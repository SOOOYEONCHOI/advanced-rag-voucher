"""파싱 결과 확인용 md 출력 (요구사항 F-1).

출력 구조:
  {instance_dir}/parsed_results/{doc_key}/{run_id}/
    00_summary.md        문서 요약·시트별 집계·검수 필요 항목·경고
    sheets/NN_시트명.md   시트별 파싱 결과(Step, 섹션, 안내문, 라벨, 이미지, 흐름도, 인쇄영역 밖)
    chunks.md            벡터DB에 들어갈 청크 텍스트 미리보기
    ir.json              공통 IR 원본
    images/              추출 이미지(중복 제거, 해시 파일명)
  {instance_dir}/parsed_results/{doc_key}/LATEST   최신 run_id

동시 실행 안전: 임시 폴더(.tmp-{run_id})에 모두 쓴 뒤 os.replace로 한 번에 교체한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import datetime

from .parser import IR_SCHEMA_VERSION, ParseResult

ROLE_KO = {"step_photo": "Step 사진", "detail_view": "확대도", "step_related": "Step 관련", "part_photo": "부품 사진",
           "figure": "그림", "form_header": "양식 헤더", "decoration": "장식", "flowchart": "흐름도"}
TYPE_KO = {"sop": "SOP 작업절차", "flowchart": "흐름도", "register": "관리대장", "list": "목록",
           "inspection": "검사·체크시트", "reference": "기준표", "other": "기타"}


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")[:60]


def md_cell(s) -> str:
    return "" if s is None else str(s).replace("|", "\\|").replace("\n", "<br>")


def export_markdown(res: ParseResult, instance_dir: str, run_id: str | None = None,
                    source_name: str | None = None, convert_vector_images: bool = True, keep_last: int = 5) -> str:
    doc_key = safe_name(res.ir["doc"]["doc_key"])
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + res.ir["doc"]["file_sha256"][:8]
    base = os.path.join(instance_dir, "parsed_results", doc_key)
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f".tmp-{run_id}-", dir=base)
    try:
        os.makedirs(os.path.join(tmp, "sheets"))
        os.makedirs(os.path.join(tmp, "images"))
        img_files = _write_images(res, os.path.join(tmp, "images"), convert_vector_images)
        sheet_files = []
        for s in res.ir["sections"]:
            fn = f"{s['index']:02d}_{safe_name(s['name'])}.md"
            sheet_files.append(fn)
            with open(os.path.join(tmp, "sheets", fn), "w", encoding="utf-8") as f:
                f.write(_sheet_md(s, res, img_files))
        with open(os.path.join(tmp, "chunks.md"), "w", encoding="utf-8") as f:
            f.write(_chunks_md(res))
        with open(os.path.join(tmp, "00_summary.md"), "w", encoding="utf-8") as f:
            f.write(_summary_md(res, run_id, source_name, sheet_files, img_files))
        with open(os.path.join(tmp, "ir.json"), "w", encoding="utf-8") as f:
            json.dump({**res.ir, "chunks": res.chunks}, f, ensure_ascii=False, indent=1, default=str)
        final = os.path.join(base, run_id)
        if os.path.exists(final):
            shutil.rmtree(final)
        os.replace(tmp, final)
        with open(os.path.join(base, ".LATEST.tmp"), "w") as f:
            f.write(run_id)
        os.replace(os.path.join(base, ".LATEST.tmp"), os.path.join(base, "LATEST"))
        _cleanup(base, keep_last)
        return final
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _cleanup(base: str, keep_last: int):
    """문서별 최근 N개 실행 결과만 보관"""
    runs = sorted((d for d in os.listdir(base) if not d.startswith(".") and os.path.isdir(os.path.join(base, d))),
                  key=lambda d: os.path.getmtime(os.path.join(base, d)))
    for d in runs[:-keep_last] if keep_last > 0 else []:
        shutil.rmtree(os.path.join(base, d), ignore_errors=True)


# ----------------------------------------------------------------------
def _write_images(res: ParseResult, out_dir: str, convert: bool) -> dict[str, str]:
    files = {}
    for sha, a in res.assets.items():
        fn = f"{a['image_id']}.{a['ext']}"
        path = os.path.join(out_dir, fn)
        with open(path, "wb") as f:
            f.write(a["data"])
        if a["needs_conversion"] and convert and shutil.which("soffice"):
            try:
                subprocess.run(["soffice", "--headless", "--convert-to", "png", "--outdir", out_dir, path],
                               capture_output=True, timeout=60)
                png = os.path.join(out_dir, f"{a['image_id']}.png")
                if os.path.exists(png):
                    fn = os.path.basename(png)
                    res.ir["assets"][sha]["converted_png"] = True
            except Exception as e:  # 변환 실패는 경고로만 남김
                res.warnings.append(f"{fn} PNG 변환 실패: {e}")
        files[a["image_id"]] = fn
    return files


def _img(img_files, image_id, width=200):
    fn = img_files.get(image_id)
    return f'<img src="../images/{fn}" width="{width}" alt="{image_id}">' if fn else image_id


def _sheet_md(s: dict, res: ParseResult, img_files: dict) -> str:
    L = []
    c = s["counts"]
    rev = s.get("revision")
    rev_txt = (f"{rev.get('revision_no') or '-'} ({rev.get('revision_date') or '-'}), 제정 {rev.get('established') or '-'}"
               if rev else "-")
    L += [f"# {s['index']:02d}. {s['name']}", "",
          "| 항목 | 값 |", "|---|---|",
          f"| 시트 유형 | **{TYPE_KO[s['section_type']]}** (`{s['section_type']}`) — {md_cell(s['classify_reason'])} |",
          f"| 시트 상태 | {s['state']} |",
          f"| 인쇄 영역 | {', '.join(s['print_area']) if s['print_area'] else '미지정(전체)'} |",
          f"| 셀 / 병합 / 수식 | {c['cells']} / {c['merged']} / {c['formulas']} |",
          f"| 텍스트 도형 / 이미지 배치 / 연결선 | {c['shapes_with_text']} / {c['pictures']} / {c['connectors']} |",
          f"| 숨김 행 / 열 | {len(s['hidden_rows'])} / {len(s['hidden_cols'])} |",
          f"| 관리대장 개정 정보 | {rev_txt} |",
          ""]

    if s["header_kv"]:
        L += ["## 헤더 정보", ""]
        for h in s["header_kv"]:
            L.append("- " + " · ".join(f"`{a}` {md_cell(v)}" for a, v in h["cells"]))
        L.append("")

    if s["steps"]:
        label = "Step" if s["section_type"] == "sop" else "공정단계"
        L += [f"## {label} ({len(s['steps'])}개)", ""]
        for st in s["steps"]:
            L += [f"### {label} {st['no']}. {md_cell(st['title'])}", "",
                  f"행 {st['rows'][0]}–{st['rows'][1]}"
                  + (f" · 표시 {', '.join(st['markers'])}" if st.get("markers") else "")
                  + (f" · 번호 {''.join(st['callouts'])}" if st.get("callouts") else ""), "",
                  "| 항목 | 내용 |", "|---|---|"]
            for k, v in st["fields"].items():
                L.append(f"| {md_cell(k)} | {md_cell(v)} |")
            if st.get("sub_rows"):
                L += ["", "행 단위(여러 행에 걸친 항목 — 청크는 이 형태로 생성):", ""]
                L += [f"- **{x['row']}행** {md_cell(x['text'])}" for x in st["sub_rows"]]
            if st["image_ids"]:
                L += ["", " ".join(_img(img_files, i, 160) for i in st["image_ids"])]
            L.append("")

    if s["sections"]:
        L += ["## 표·본문 영역", ""]
        for sec in s["sections"]:
            L.append(f"### 행 {sec['rows'][0]}–{sec['rows'][1]}" + (f" · {md_cell(sec['title'])}" if sec["title"] else ""))
            if sec["header"]:
                L.append(f"\n헤더(행 {sec['header_row']}): `{md_cell(sec['header'])}`\n")
            for ln in sec["lines"]:
                L.append(f"- **{ln['row']}행** {md_cell(ln['text'])}")
            L.append("")

    if s["notes"]:
        L += ["## 도형 안내문 (guide_note)", ""]
        for n in s["notes"]:
            link = n["linked_section"]
            L += [f"**도형 #{n['shape_id']}** · 위치 `{n['range']}` · 인쇄 영역 {'안' if n['in_print_area'] else '**밖**'}"
                  + (f" · 연결 섹션 `{link['cell']}` {md_cell(link['text'])} ({link['method']})" if link else " · 연결 섹션 없음"),
                  ""] + ["> " + line for line in n["text"].split("\n")] + [""]

    if s["labels"]:
        L += ["## 도형 라벨 (이미지에 붙지 않은 것)", "", "| 도형 | 위치 | 텍스트 | 연결 |", "|---|---|---|---|"]
        for lb in s["labels"]:
            L.append(f"| #{lb['shape_id']} | `{lb['range']}` | {md_cell(lb['text'])} | {lb['attached_to'] or '-'} |")
        L.append("")

    if s["form_controls"]:
        L += ["## 폼 컨트롤", "", "| 이름 | 종류 | 라벨 | 상태 | 위치 |", "|---|---|---|---|---|"]
        for f in s["form_controls"]:
            L.append(f"| {f['name']} | {f['type']} | {md_cell(f['label'])} | {'☑ 체크' if f['checked'] else '☐ 미체크'} | {f['range'] or '-'} |")
        L += ["", "※ 양식 기본값일 수 있어 `is_form_default=true`로 태깅", ""]

    if s["placements"]:
        L += [f"## 이미지 배치 ({len(s['placements'])}건)", "",
              "| 이미지 | 위치 | 역할 | 연결 대상 | 번호·표시·오버레이 | 연결 방식(신뢰도) | 검수 | VLM |",
              "|---|---|---|---|---|---|---|---|"]
        for p in s["placements"]:
            a = res.ir["assets"][p["sha256"]]
            target = f"Step {p['step_no']} {p['step_title']}" if p["step_no"] else (p["row_item"] or p["context_text"][:40])
            marks = " ".join(p["callouts"] + p["markers"] + p["overlay_texts"])
            L.append(f"| {_img(img_files, p['image_id'], 120)}<br>`{p['image_id'][:8]}` | `{p['cell_range']}`"
                     f"{' 그룹' if p['in_group'] else ''} | {ROLE_KO.get(p['role'], p['role'])} | {md_cell(target)} | "
                     f"{md_cell(marks)} | {p['link_method']} ({p['confidence']}) | {p['review_status']} | "
                     f"{a['vlm_status']}<br>{a['vlm_reason']} |")
        L.append("")

    fg = s.get("flow_graph")
    if fg:
        names = {n["id"]: n for n in fg["nodes"]}
        L += ["## 흐름도 그래프 (XML 복원 · VLM 보강 전)", "",
              f"노드 {len(fg['nodes'])} · 확정 연결 {len(fg['edges'])} · 미연결 선 {len(fg['unresolved_connectors'])} · "
              f"고립 노드 {len(fg['isolated_nodes'])} · VLM `{fg['vlm_status']}` · 검수 `{fg['review_status']}`", "",
              "```mermaid", "flowchart TD"]
        for n in fg["nodes"]:
            t = n["text"].replace('"', "'")
            g = n["geom"] or ""
            shape = (f'{{"{t}"}}' if "Decision" in g else f'{{{{"{t}"}}}}' if "Preparation" in g
                     else f'("{t}")' if g == "roundRect" else f'["{t}"]')
            L.append(f"  n{n['id']}{shape}")
        for e in fg["edges"]:
            L.append(f"  n{e['from']} --> n{e['to']}")
        L += ["```", "", "### 공정단계별 노드", "", "| 공정단계 | 노드 | 도형 | 위치 |", "|---|---|---|---|"]
        for n in sorted(fg["nodes"], key=lambda x: (x["stage_no"] or 99, x["range"])):
            L.append(f"| {n['stage_no'] or '-'} {md_cell(n['stage'] or '')} | {md_cell(n['text'])} | {n['geom']} | `{n['range']}` |")
        L += ["", "### VLM 보강 필요: 끝점이 도형에 붙지 않은 연결선", "", "| 연결선 | 시작 | 끝 | 위치 |", "|---|---|---|---|"]
        for u in fg["unresolved_connectors"]:
            L.append(f"| #{u['connector']} | {md_cell(u['from'] or '∅')} | {md_cell(u['to'] or '∅')} | `{u['range']}` |")
        if fg["edge_label_shapes"]:
            L += ["", "OK/NG 라벨 도형(연결선에 미부착): " + ", ".join(f"{x['text']}@`{x['range']}`" for x in fg["edge_label_shapes"])]
        L.append("")

    if s["out_of_print_area"]:
        L += [f"## 인쇄 영역 밖 데이터 ({len(s['out_of_print_area'])}건, 모두 적재 대상)", "",
              "| 위치 | 종류 | 내용 |", "|---|---|---|"]
        for o in s["out_of_print_area"]:
            L.append(f"| `{o['cell']}` | {o['kind']} | {md_cell(o['text'][:80])} |")
        L.append("")
    n_chunks = sum(1 for ch in res.chunks if ch["sheet"] == s["name"])
    L += [f"---\n이 시트에서 생성된 청크: **{n_chunks}개** → `../chunks.md` 참고", ""]
    return "\n".join(L)


def _chunks_md(res: ParseResult) -> str:
    L = ["# 청크 미리보기", "", f"총 {len(res.chunks)}개 · 유형별 " +
         ", ".join(f"{k} {v}" for k, v in Counter(c['content_type'] for c in res.chunks).most_common()), ""]
    cur = None
    for ch in res.chunks:
        if ch["sheet"] != cur:
            cur = ch["sheet"]
            L += [f"## {cur}", ""]
        meta = {k: v for k, v in ch["meta"].items() if v not in (None, [], {})}
        L += [f"#### `{ch['chunk_id']}` · {ch['content_type']} · {len(ch['text'])}자", "",
              f"meta: `{json.dumps(meta, ensure_ascii=False, default=str)}`", "", "```text", ch["text"], "```", ""]
    return "\n".join(L)


def _summary_md(res: ParseResult, run_id, source_name, sheet_files, img_files) -> str:
    ir, secs = res.ir, res.ir["sections"]
    n_pl = sum(len(s["placements"]) for s in secs)
    vlm = Counter(a["vlm_status"] for a in ir["assets"].values())
    roles = Counter(p["role"] for s in secs for p in s["placements"])
    review = [(s["name"], p) for s in secs for p in s["placements"] if p["review_status"] == "needs_review"]
    L = [f"# 파싱 결과 요약 — {ir['doc']['doc_key']}", "",
         "| 항목 | 값 |", "|---|---|",
         f"| 원본 파일 | {md_cell(source_name or '-')} |",
         f"| 파일 sha256 | `{ir['doc']['file_sha256']}` |",
         f"| 적용 모델 | {ir['doc'].get('model') or '-'} |",
         f"| 실행 ID | `{run_id}` |",
         f"| 생성 시각 | {datetime.now().isoformat(timespec='seconds')} |",
         f"| IR 스키마 | {IR_SCHEMA_VERSION} |",
         f"| 시트 수 | {len(secs)} |",
         f"| 이미지 배치 / 고유 이미지 | {n_pl} / {len(ir['assets'])} |",
         f"| 청크 수 | {len(res.chunks)} |", "",
         "## 시트별 결과", "",
         "| # | 시트 | 유형 | Step/단계 | 섹션 | 안내문 | 라벨 | 폼 | 이미지 | 인쇄영역 밖 | 청크 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s, fn in zip(secs, sheet_files):
        nc = sum(1 for c in res.chunks if c["sheet"] == s["name"])
        L.append(f"| {s['index']} | [{md_cell(s['name'])}](sheets/{fn}) | {TYPE_KO[s['section_type']]} | {len(s['steps'])} | "
                 f"{len(s['sections'])} | {len(s['notes'])} | {len(s['labels'])} | {len(s['form_controls'])} | "
                 f"{len(s['placements'])} | {len(s['out_of_print_area'])} | {nc} |")
    L += ["", "## 이미지", "",
          "역할별: " + ", ".join(f"{ROLE_KO.get(k, k)} {v}" for k, v in roles.most_common()), "",
          f"VLM 판정(D-1): 대상(pending) {vlm.get('pending', 0)} · 제외(skipped) {vlm.get('skipped', 0)}", ""]
    reasons = Counter((a["vlm_status"], a["vlm_reason"]) for a in ir["assets"].values())
    L += ["| 판정 | 사유 | 이미지 수 |", "|---|---|---|"] + \
         [f"| {k[0]} | {k[1]} | {v} |" for k, v in reasons.most_common()] + [""]
    conv = [a for a in ir["assets"].values() if a["needs_conversion"]]
    if conv:
        L += ["벡터 이미지(emf/wmf): " + ", ".join(
            f"`{a['image_id']}.{a['ext']}` → {'PNG 변환됨' if a.get('converted_png') else '변환 안 됨'}" for a in conv), ""]
    L += [f"## 검수 필요 ({len(review)}건 이미지 연결 + 흐름도)", ""]
    for name, p in review[:50]:
        L.append(f"- {name} `{p['cell_range']}` {ROLE_KO.get(p['role'], p['role'])} — {p['link_method']} ({p['confidence']})")
    if len(review) > 50:
        L.append(f"- … 외 {len(review) - 50}건 (시트별 md 참고)")
    for s in secs:
        if s.get("flow_graph"):
            fg = s["flow_graph"]
            L.append(f"- {s['name']} 흐름도: 미연결 선 {len(fg['unresolved_connectors'])}건, 고립 노드 {len(fg['isolated_nodes'])}개 → VLM 보강 후 검수")
    L += ["", "## 경고", ""] + ([f"- {w}" for w in res.warnings] or ["- 없음"]) + [""]
    L += ["## 파일", "", "- `sheets/` 시트별 상세", "- `chunks.md` 벡터DB 적재 청크 미리보기",
          "- `ir.json` 공통 IR + 청크 원본", "- `images/` 추출 이미지(해시 파일명, 중복 제거)", ""]
    return "\n".join(L)
