#!/usr/bin/env python3
"""LibreOffice UNO를 사용해 단일 Excel 시트를 근거 강조 PDF로 변환한다."""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import uno
from com.sun.star.beans import PropertyValue


CELL_RANGE_PATTERN = re.compile(
    r"^(?:(?P<start>[A-Z]{1,3}[1-9][0-9]*)(?::(?P<end>[A-Z]{1,3}[1-9][0-9]*))?|(?P<row_start>[1-9][0-9]*):(?P<row_end>[1-9][0-9]*))$",
    re.IGNORECASE,
)


def _property(name: str, value: object) -> PropertyValue:
    prop = PropertyValue()
    prop.Name = name
    prop.Value = value
    return prop


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _column_name(index: int) -> str:
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _normalize_range(sheet: object, source_range: str) -> str:
    raw = source_range.strip().replace("$", "").upper()
    match = CELL_RANGE_PATTERN.fullmatch(raw)
    if not match:
        raise ValueError("셀 범위는 A1, A1:B10 또는 12:18 형식이어야 합니다.")
    if match.group("start"):
        return raw if match.group("end") else f"{raw}:{raw}"

    cursor = sheet.createCursor()
    cursor.gotoEndOfUsedArea(True)
    end_column = _column_name(cursor.getRangeAddress().EndColumn)
    return f"A{match.group('row_start')}:{end_column}{match.group('row_end')}"


def _start_libreoffice(soffice: str, profile_dir: Path, port: int) -> subprocess.Popen:
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_url = uno.systemPathToFileUrl(str(profile_dir.resolve()))
    command = [
        soffice,
        "--headless",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nofirststartwizard",
        f"-env:UserInstallation={profile_url}",
        f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext",
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _connect_uno(port: int, process: subprocess.Popen, timeout: float = 20.0) -> object:
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_context
    )
    endpoint = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            raise RuntimeError(f"LibreOffice가 시작 중 종료되었습니다. {stderr.strip()}")
        try:
            return resolver.resolve(endpoint)
        except Exception as exc:  # UNO 연결 준비 전 재시도
            last_error = exc
            time.sleep(0.25)
    raise TimeoutError("LibreOffice UNO 연결 시간이 초과되었습니다.") from last_error


def _add_highlight(document: object, sheet: object, source_range: str) -> object:
    normalized = _normalize_range(sheet, source_range)
    target = sheet.getCellRangeByName(normalized)
    rectangle = document.createInstance("com.sun.star.drawing.RectangleShape")
    rectangle.Position = target.Position
    rectangle.Size = target.Size
    rectangle.setPropertyValue("FillStyle", uno.Enum("com.sun.star.drawing.FillStyle", "SOLID"))
    rectangle.setPropertyValue("FillColor", 0xFFF3B0)
    rectangle.setPropertyValue("FillTransparence", 82)
    rectangle.setPropertyValue("LineColor", 0x16A34A)
    rectangle.setPropertyValue("LineWidth", 100)
    rectangle.setPropertyValue("Printable", True)
    sheet.getDrawPage().add(rectangle)
    return target


# 2026.10.28(woojin.jung) 추가 - 답변 근거 범위만 첫 화면에 온전히 보이도록 단일 페이지 인쇄영역 구성
def _configure_print_area(document: object, sheet: object, target: object) -> None:
    target_address = target.getRangeAddress()
    sheet.setPrintAreas((target_address,))

    # SinglePageSheets가 인쇄영역 밖의 사용 셀까지 포함하므로 미리보기 메모리 문서에서만 숨긴다.
    cursor = sheet.createCursor()
    cursor.gotoEndOfUsedArea(True)
    used_address = cursor.getRangeAddress()
    rows = sheet.getRows()
    columns = sheet.getColumns()
    for row_index in range(used_address.StartRow, target_address.StartRow):
        rows.getByIndex(row_index).IsVisible = False
    for row_index in range(target_address.EndRow + 1, used_address.EndRow + 1):
        rows.getByIndex(row_index).IsVisible = False
    for column_index in range(used_address.StartColumn, target_address.StartColumn):
        columns.getByIndex(column_index).IsVisible = False
    for column_index in range(target_address.EndColumn + 1, used_address.EndColumn + 1):
        columns.getByIndex(column_index).IsVisible = False

    page_style_name = sheet.getPropertyValue("PageStyle")
    page_styles = document.getStyleFamilies().getByName("PageStyles")
    page_style = page_styles.getByName(page_style_name)

    # 기존 시트의 방향·여백은 유지하면서 근거 범위를 가로·세로 한 페이지에 맞춘다.
    for property_name, value in (
        ("ScaleToPages", 0),
        ("ScaleToPagesX", 1),
        ("ScaleToPagesY", 1),
    ):
        try:
            page_style.setPropertyValue(property_name, value)
        except Exception:
            pass


def _render(input_path: Path, output_path: Path, sheet_name: str, source_range: str, soffice: str, profile_dir: Path) -> None:
    port = _free_port()
    process = _start_libreoffice(soffice, profile_dir, port)
    document = None
    desktop = None
    try:
        context = _connect_uno(port, process)
        service_manager = context.ServiceManager
        desktop = service_manager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
        load_options = (
            _property("Hidden", True),
            _property("Silent", True),
            _property("ReadOnly", False),
            _property("MacroExecutionMode", uno.getConstantByName("com.sun.star.document.MacroExecMode.NEVER_EXECUTE")),
            _property("UpdateDocMode", uno.getConstantByName("com.sun.star.document.UpdateDocMode.NO_UPDATE")),
        )
        document = desktop.loadComponentFromURL(
            uno.systemPathToFileUrl(str(input_path.resolve())), "_blank", 0, load_options
        )
        if document is None:
            raise RuntimeError("Excel 문서를 열 수 없습니다.")

        sheets = document.getSheets()
        if not sheets.hasByName(sheet_name):
            raise LookupError(f"시트를 찾을 수 없습니다: {sheet_name}")
        target_sheet = sheets.getByName(sheet_name)
        target_sheet.IsVisible = True
        for name in tuple(sheets.getElementNames()):
            if name != sheet_name:
                # 2026.10.28(woojin.jung) 수정 - SinglePageSheets가 숨김 시트도 출력하므로
                # 미리보기용 메모리 문서에서는 대상 시트만 남겨 PDF 첫 페이지를 보장
                sheets.removeByName(name)
        controller = document.getCurrentController()
        if controller is not None:
            controller.setActiveSheet(target_sheet)

        # 2026.10.28(woojin.jung) 추가 - 원본 셀 서식을 덮지 않는 반투명 도형으로 답변 근거 범위 강조
        normalized_range = _normalize_range(target_sheet, source_range)
        target = target_sheet.getCellRangeByName(normalized_range)
        # 2026.10.28(woojin.jung) 수정 - 전체 시트 대신 근거 셀 범위만 PDF 첫 페이지에 출력
        _configure_print_area(document, target_sheet, target)
        # 2026.10.28(woojin.jung) 수정 - 범위 밖 행·열 정리 후 변경된 셀 좌표에 강조 도형 배치
        _add_highlight(document, target_sheet, normalized_range)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.storeToURL(
            uno.systemPathToFileUrl(str(output_path.resolve())),
            (
                _property("FilterName", "calc_pdf_Export"),
                _property("Overwrite", True),
                # 2026.10.28(woojin.jung) 추가 - 기존 Excel 페이지 나눔과 무관하게 근거 인쇄영역을 한 페이지로 출력
                _property(
                    "FilterData",
                    uno.Any(
                        "[]com.sun.star.beans.PropertyValue",
                        (_property("SinglePageSheets", True),),
                    ),
                ),
            ),
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("PDF 변환 결과가 생성되지 않았습니다.")
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                pass
        if desktop is not None:
            try:
                desktop.terminate()
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--range", dest="source_range", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--soffice", required=True)
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    profile_dir = Path(args.profile).resolve()
    if not input_path.is_file():
        print("입력 Excel 파일을 찾을 수 없습니다.", file=sys.stderr)
        return 2
    try:
        _render(input_path, output_path, args.sheet, args.source_range, args.soffice, profile_dir)
        return 0
    except (ValueError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"시트 미리보기 변환 실패: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
