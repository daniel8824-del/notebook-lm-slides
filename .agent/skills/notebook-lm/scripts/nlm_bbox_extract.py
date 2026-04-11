#!/usr/bin/env python3
"""
extract_nlm_v10.py — Pixel-precise bbox extraction via Gemini Vision

파이프라인 (슬라이드당):
  1. PDF 페이지 → 300 DPI PNG (원본 ~5734x3200)
  2. 1600px 너비로 리사이즈 (비율 유지)
  3. 리사이즈 이미지 → Gemini 2.5 Flash (structured JSON)
  4. 픽셀 bbox 파싱 (리사이즈 공간 기준)
  5. original_size + resize_size 저장

Usage:
  python3 extract_nlm_v10.py <pdf_path> --slides 1,2,...,13 --output extracted_v10.json
"""

import os, sys, json, argparse, time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import fitz
from PIL import Image
import io

load_dotenv(Path.home() / "slide-generator-app/.env")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

W_TARGET = 1600


def pdf_page_to_png(pdf_path: Path, page_idx: int) -> bytes:
    """PDF 페이지 → 300 DPI PNG bytes"""
    doc = fitz.open(str(pdf_path))
    page = doc[page_idx]
    mat = fitz.Matrix(300 / 72, 300 / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def resize_to_target(png_bytes: bytes, w_target: int = W_TARGET):
    """1600px 너비로 리사이즈, (resized_bytes, W_ORIG, H_ORIG, W_R, H_R) 반환"""
    img = Image.open(io.BytesIO(png_bytes))
    W_ORIG, H_ORIG = img.size
    H_TARGET = int(H_ORIG * w_target / W_ORIG)
    img_small = img.resize((w_target, H_TARGET), Image.LANCZOS)
    buf = io.BytesIO()
    img_small.save(buf, format="PNG")
    return buf.getvalue(), W_ORIG, H_ORIG, w_target, H_TARGET


def extract_bboxes(small_bytes: bytes, W_R: int, H_R: int, slide_num: int) -> list:
    """Gemini Vision으로 픽셀 bbox 추출"""
    prompt = f"""Analyze this image ({W_R}x{H_R} pixels).

Return a JSON array of EVERY text element visible in the image.

For each text element:
- "text": full text content (preserve Korean exactly, join multi-line text into single string)
- "bbox": [x1, y1, x2, y2] in PIXELS from top-left corner (integers)
  IMPORTANT: bbox must be a HORIZONTAL reading rectangle.
  Even if text appears rotated or vertical in the image, provide the bbox as if the text were laid out horizontally.
  x1 < x2, y1 < y2, width must be >= height for most text elements.
  Use the text block's CENTER position and estimate a horizontal reading box around it.
- "role": title|subtitle|body|caption|label|table_cell

Rules:
- Be EXHAUSTIVE — include every visible text
- For rotated/vertical text: use center of the text block, estimate horizontal bbox
- Merge text that belongs to same logical element (e.g. multi-line title)
- Return ONLY valid JSON array, no markdown."""

    image_part = types.Part.from_bytes(data=small_bytes, mime_type="image/png")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    text = response.text.strip()
    # JSON 배열 추출 (```json ... ``` 래퍼 제거)
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(text)
    return data if isinstance(data, list) else []


def load_old_charts_tables(old_json_path: Path, slide_num: int) -> list:
    """기존 extracted.json에서 chart/table 요소만 추출"""
    if not old_json_path.exists():
        return []
    d = json.loads(old_json_path.read_text(encoding="utf-8"))
    for s in d.get("slides", []):
        if s.get("slide") == slide_num:
            return [
                e for e in s.get("elements", [])
                if e.get("type") in ("chart", "table")
            ]
    return []


def main():
    parser = argparse.ArgumentParser(description="NLM v10 픽셀 bbox 추출기")
    parser.add_argument("pdf_path", help="PDF 파일 경로")
    parser.add_argument("--slides", default=None, help="슬라이드 번호 (예: 1,2,3 또는 전체)")
    parser.add_argument("--output", default="extracted_v10.json", help="출력 JSON 파일")
    parser.add_argument("--old-json", default=None, help="기존 extracted.json 경로 (차트/표 보존용)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)

    # 슬라이드 범위 결정
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    doc.close()

    if args.slides:
        slide_nums = [int(s.strip()) for s in args.slides.split(",")]
    else:
        slide_nums = list(range(1, total_pages + 1))

    # old extracted.json 경로 자동 감지
    old_json_path = Path(args.old_json) if args.old_json else pdf_path.parent / "extracted.json"

    output_path = Path(args.output)
    # 기존 결과 로드 (재시작 지원)
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        done_slides = {s["slide"] for s in existing.get("slides", [])}
        result_slides = existing.get("slides", [])
        print(f"기존 결과 로드: {len(done_slides)}개 슬라이드 완료")
    else:
        done_slides = set()
        result_slides = []

    print("=" * 60)
    print("  NLM v10 — 픽셀 bbox 추출기")
    print("=" * 60)
    print(f"  PDF     : {pdf_path.name}")
    print(f"  슬라이드 : {slide_nums}")
    print(f"  출력    : {output_path}")
    print()

    for slide_num in slide_nums:
        if slide_num in done_slides:
            print(f"  S{slide_num}: 이미 완료 (스킵)")
            continue

        print(f"  S{slide_num}: 처리 중...", end="", flush=True)
        try:
            page_idx = slide_num - 1
            png_bytes = pdf_page_to_png(pdf_path, page_idx)
            small_bytes, W_ORIG, H_ORIG, W_R, H_R = resize_to_target(png_bytes)

            elements = extract_bboxes(small_bytes, W_R, H_R, slide_num)

            # 차트/표 보존 (old extracted.json)
            old_elements = load_old_charts_tables(old_json_path, slide_num)
            if old_elements:
                print(f" +{len(old_elements)}개 차트/표", end="", flush=True)

            result_slides.append({
                "slide": slide_num,
                "original_size": [W_ORIG, H_ORIG],
                "resize_size": [W_R, H_R],
                "elements": elements,
                "legacy_elements": old_elements,  # 차트/표 (% 좌표)
            })

            print(f" -> {len(elements)}개 텍스트 감지 ({W_ORIG}x{H_ORIG} -> {W_R}x{H_R})")

            # 중간 저장
            output_path.write_text(
                json.dumps(
                    {"source": pdf_path.name, "slides": sorted(result_slides, key=lambda s: s["slide"])},
                    ensure_ascii=False, indent=2
                ),
                encoding="utf-8"
            )
            done_slides.add(slide_num)

            # API rate limit 방지
            if slide_num != slide_nums[-1]:
                time.sleep(1)

        except Exception as e:
            print(f" ERROR: {e}")
            result_slides.append({
                "slide": slide_num,
                "error": str(e),
                "elements": [],
                "legacy_elements": [],
            })

    # 최종 저장
    final = {
        "source": pdf_path.name,
        "slides": sorted(result_slides, key=lambda s: s["slide"]),
    }
    output_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    success = [s for s in result_slides if not s.get("error")]
    errors = [s for s in result_slides if s.get("error")]
    total_texts = sum(len(s.get("elements", [])) for s in success)
    print(f"  완료: {len(success)}/{len(slide_nums)} 슬라이드")
    print(f"  총 텍스트: {total_texts}개")
    if errors:
        print(f"  오류: {[s['slide'] for s in errors]}")
    print(f"  저장: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
