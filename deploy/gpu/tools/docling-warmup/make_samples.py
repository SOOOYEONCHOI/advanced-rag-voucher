"""docling 모델 미리 받기용 임시 샘플 생성 (회사 문서 아님).

- sample_text.pdf : 텍스트 레이어 있는 PDF -> 일반 converter(레이아웃·표 구조 모델)
- sample_scan.pdf : 이미지만 있는 PDF       -> OCR converter(EasyOCR ko/en)
- sample.png      : 이미지                  -> 이미지 파이프라인(EasyOCR)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
out.mkdir(parents=True, exist_ok=True)

lines = [
    "Warmup sample document for offline model download only.",
    "Step 1 Prepare the tool and check the work area before you start.",
    "Step 2 Fasten the bracket with four bolts and check the torque value.",
    "Item  Qty  Note",
    "Bolt  4    M6",
    "Washer 4   Flat",
]

# 1) 텍스트 레이어 PDF (직접 작성한 최소 PDF)
content = "BT /F1 12 Tf 72 740 Td 16 TL\n" + "".join(
    "(" + l.replace("(", "[").replace(")", "]") + ") Tj T*\n" for l in lines
) + "ET\n"
objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    f"<< /Length {len(content)} >>\nstream\n{content}endstream",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
]
pdf = "%PDF-1.4\n"
offsets = []
for i, o in enumerate(objs, 1):
    offsets.append(len(pdf.encode("latin-1")))
    pdf += f"{i} 0 obj\n{o}\nendobj\n"
xref = len(pdf.encode("latin-1"))
pdf += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
pdf += "".join(f"{off:010d} 00000 n \n" for off in offsets)
pdf += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
(out / "sample_text.pdf").write_bytes(pdf.encode("latin-1"))

# 2) 이미지 (글자를 그림으로)
img = Image.new("RGB", (1200, 500), "white")
d = ImageDraw.Draw(img)
for i, l in enumerate(lines):
    d.text((40, 40 + i * 60), l, fill="black", font_size=32)
img.save(out / "sample.png")

# 3) 텍스트 레이어 없는 PDF (스캔본 흉내)
img.save(out / "sample_scan.pdf", "PDF", resolution=150)

print("samples:", sorted(p.name for p in out.iterdir()))
