#!/usr/bin/env python3
"""
remove_text_v9.py — Nano Banana Pro (gemini-3-pro-image-preview) 텍스트 제거
슬라이드 PNG에서 텍스트를 지우고 클린 배경 이미지를 반환한다.

Usage:
  python3 remove_text_v9.py slides.pdf --slides 1,2 --output ./clean/
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-3.1-flash-image-preview"   # 최신 Flash 이미지 모델 (빠름 + 품질↑)
DPI = 300   # 고해상도 — 텍스트 경계 정밀도 향상


def pdf_to_png(pdf_path: Path, page_num: int, dpi: int = DPI) -> bytes:
    """PDF 페이지 → PNG bytes"""
    doc = fitz.open(str(pdf_path))
    page = doc[page_num - 1]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")


def remove_text_from_image(client: genai.Client, png_bytes: bytes, slide_num: int) -> bytes | None:
    """Nano Banana Pro로 슬라이드 이미지에서 텍스트 제거"""
    print(f"  S{slide_num}: Nano Banana Pro 텍스트 제거 요청...")

    prompt = (
        "CRITICAL TASK: Remove ALL text from this presentation slide image.\n\n"
        "REMOVE EVERY CHARACTER — including these often-missed items:\n"
        "- Metadata text at corners (e.g. '4%', '7%', 'Marketing Business Proposal')\n"
        "- Large hero titles and numbers (make sure NO trace remains)\n"
        "- Small subtitle/caption text\n"
        "- ALL text inside tables (cells should be completely empty, no ghost text)\n"
        "- ALL chart labels, axis labels, legend text\n"
        "- Korean (한글), English, numbers, punctuation, parentheses\n"
        "- Watermarks (NotebookLM logo/text)\n"
        "- ANY faint/shadow/ghost remnants from partial previous removal\n\n"
        "If you see ANY character anywhere, REMOVE it completely.\n\n"
        "PRESERVE:\n"
        "- Illustrations, icons, infographic shapes\n"
        "- Chart lines, bars, curves (structure without labels)\n"
        "- Table grid lines (empty cells without text)\n"
        "- Background colors and gradients\n\n"
        "Fill removed text areas with the EXACT surrounding background color. "
        "No visible seams, smudges, or artifacts.\n\n"
        "Return ONLY the fully cleaned image with zero text."
    )

    image_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[image_part, prompt],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                print(f"  S{slide_num}: 클린 이미지 수신 ({len(part.inline_data.data)} bytes)")
                return part.inline_data.data  # bytes

        print(f"  S{slide_num}: 이미지 응답 없음 — 텍스트 응답: {response.text[:200] if response.text else 'N/A'}")
        return None

    except Exception as e:
        print(f"  S{slide_num}: 오류 — {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Nano Banana Pro 텍스트 제거")
    parser.add_argument("pdf", help="NLM 슬라이드 PDF")
    parser.add_argument("--slides", default="1,2", help="처리할 슬라이드 번호 (예: 1,2,3)")
    parser.add_argument("--output", "-o", default="./clean", help="출력 폴더")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    slide_nums = [int(x.strip()) for x in args.slides.split(",")]

    client = genai.Client(api_key=API_KEY)

    print("=" * 50)
    print("  Nano Banana Pro — 텍스트 제거")
    print("=" * 50)
    print(f"  PDF   : {pdf_path}")
    print(f"  슬라이드: {slide_nums}")
    print(f"  출력  : {out_dir}")
    print(f"  모델  : {MODEL}")
    print()

    results = {}

    for sn in slide_nums:
        # 1) PDF → PNG
        png_bytes = pdf_to_png(pdf_path, sn)
        orig_path = out_dir / f"slide_{sn:02d}_original.png"
        orig_path.write_bytes(png_bytes)
        print(f"  S{sn}: 원본 PNG 저장 ({len(png_bytes)//1024}KB) → {orig_path.name}")

        # 2) 텍스트 제거 — 1차 패스
        clean_bytes = remove_text_from_image(client, png_bytes, sn)

        # 3) 반복 패스 — 잔상이 없을 때까지 (최대 5패스)
        MAX_PASSES = 5
        if clean_bytes:
            for p in range(2, MAX_PASSES + 1):
                print(f"  S{sn}: {p}차 패스 — 잔상 제거...")
                result = remove_text_from_image(client, clean_bytes, sn)
                if result:
                    clean_bytes = result
                    print(f"  S{sn}: {p}차 패스 완료")
                else:
                    print(f"  S{sn}: {p}차 패스 실패 — 이전 결과 사용")
                    break

        if clean_bytes:
            clean_path = out_dir / f"slide_{sn:02d}_clean.png"
            clean_path.write_bytes(clean_bytes)
            b64 = base64.b64encode(clean_bytes).decode()
            results[sn] = {"clean_path": str(clean_path), "b64_len": len(b64)}
            print(f"  S{sn}: 클린 이미지 저장 → {clean_path.name}")
        else:
            results[sn] = None
            print(f"  S{sn}: 실패")

        print()

    # 결과 요약
    print("=" * 50)
    success = sum(1 for v in results.values() if v)
    print(f"  완료: {success}/{len(slide_nums)} 성공")
    print("=" * 50)

    # JSON 결과 저장
    summary_path = out_dir / "results.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"  결과 JSON: {summary_path}")


if __name__ == "__main__":
    main()
