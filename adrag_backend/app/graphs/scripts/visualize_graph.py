"""RAG 파이프라인 그래프 시각화 스크립트."""

import sys
import os
from datetime import datetime

# adrag_backend 루트를 Python 경로 및 CWD로 고정
_backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, _backend_root)
os.chdir(_backend_root)

from app.graphs.rag_graph import build_rag_graph

app = build_rag_graph()
graph_obj = app.get_graph()

# 1) Mermaid 텍스트 출력
mermaid_text = graph_obj.draw_mermaid()
print("=" * 60)
print("Mermaid 다이어그램:")
print("=" * 60)
print(mermaid_text)

# 2) PNG 저장 시도 (Mermaid.js API 호출)
timestamp = datetime.now().strftime("%Y%m%d_%H%M")
output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workflow-graphs"))
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, f"rag_pipeline_{timestamp}.png")
try:
    png_bytes = graph_obj.draw_mermaid_png()
    with open(output_path, "wb") as f:
        f.write(png_bytes)
    print(f"\nPNG 저장 완료: {output_path}")
except Exception as e:
    print(f"\nPNG 저장 실패 (인터넷 연결 또는 grandalf 필요): {e}")
    print("Mermaid 텍스트를 https://mermaid.live 에 붙여넣어 확인하세요.")