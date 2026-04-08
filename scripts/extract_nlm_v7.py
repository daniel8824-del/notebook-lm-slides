#!/usr/bin/env python3
"""NLM 슬라이드 해체 v7 — 멀티패스 Gemini Vision + 오버플로우 자동 보정.

PDF → 300dpi 이미지 → Gemini Vision 멀티패스 → PptxGenJS 호환 JSON

v6 대비 개선:
  - 멀티패스 Vision (구조 추출 → 검증 → 차트 정밀)
  - 오버플로우 방지 (텍스트 면적 계산 + 자동 fontSize 축소)
  - role 분류 (title/subtitle/stat/body/label/caption)
  - 스타일 가이드 통합 생성
  - 한국어 텍스트 너비 계산 개선

Usage:
    python3 extract_nlm_v7.py input.pdf -o output.json
    python3 extract_nlm_v7.py input.pdf --model gemini-2.5-flash --pages 1-3
    python3 extract_nlm_v7.py input.pdf --fast  # Pass 2,3 건너뛰기
"""

import argparse
import base64
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ─── 상수 ──────────────────────────────────────────────────────────────
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
DPI = 300
SLIDE_W = 10.0       # inches (16:9)
SLIDE_H = 5.625      # inches (16:9)
MIN_FONT = 12        # pt — 이보다 더 줄이지 않음
LINE_H_RATIO = 1.35  # line-height / font-size

# ─── 프롬프트 ──────────────────────────────────────────────────────────

PASS1_PROMPT = """\
이 프레젠테이션 슬라이드 이미지를 정밀 분석하여 PptxGenJS로 재현할 수 있도록 JSON을 추출하세요.

## 출력 스키마

```json
{
  "background": { "type": "solid", "color": "#HEX" },
  "elements": [ ... ]
}
```

background.type은 "solid" | "gradient" | "image" 중 하나.
gradient이면 "colors": ["#HEX1", "#HEX2"], "angle": 숫자 추가.

## 요소 타입별 필드

### text
{ "type": "text", "role": "title|subtitle|stat|body|label|caption",
  "content": "전체 텍스트 (줄바꿈은 \\n)",
  "x_pct": 숫자, "y_pct": 숫자, "w_pct": 숫자, "h_pct": 숫자,
  "fontSize": 숫자(pt), "fontWeight": "normal|bold",
  "color": "#HEX", "align": "left|center|right",
  "lineCount": 실제로보이는줄수 }

### chart
{ "type": "chart", "chartType": "bar|line|pie|doughnut|area",
  "title": "차트 제목",
  "labels": ["라벨"],
  "datasets": [{ "name": "시리즈", "values": [수치], "color": "#HEX" }],
  "x_pct": 숫자, "y_pct": 숫자, "w_pct": 숫자, "h_pct": 숫자 }

### table
{ "type": "table", "headers": ["헤더"],
  "rows": [["셀"]],
  "headerColor": "#HEX",
  "x_pct": 숫자, "y_pct": 숫자, "w_pct": 숫자, "h_pct": 숫자 }

### shape
{ "type": "shape", "shapeType": "rectangle|roundedRect|circle|line|arrow",
  "fill": "#HEX",
  "x_pct": 숫자, "y_pct": 숫자, "w_pct": 숫자, "h_pct": 숫자 }

### image
{ "type": "image", "description": "이미지 설명",
  "x_pct": 숫자, "y_pct": 숫자, "w_pct": 숫자, "h_pct": 숫자 }

## fontSize 추정 기준 (슬라이드 높이 대비)
- 5-7% → 36-44pt (title/stat)
- 3-4% → 20-28pt (subtitle)
- 2-2.5% → 14-18pt (body)
- ~1.5% → 10-12pt (label/caption)

## 핵심 규칙
- 좌표는 슬라이드 전체 크기 대비 퍼센트(%)
- 색상은 정확한 HEX
- 차트 데이터는 이미지에서 읽을 수 있는 만큼 정확하게
- 테이블 모든 셀 빠짐없이
- 누락 요소 없이 빠짐없이 추출
- JSON만 반환하세요. 설명이나 마크다운 코드 블록 없이."""

PASS2_PROMPT = """\
아래는 이 슬라이드에서 1차 추출한 JSON입니다.
원본 이미지와 비교하여 오류를 수정하고, 누락된 요소를 추가하세요.

```json
{extracted}
```

## 검증 항목
1. 텍스트 내용: 빠진 글자, 오타, 잘린 내용
2. fontSize: 제목이 본문보다 작으면 안 됨. 슬라이드 높이 대비 재검증
3. 좌표: 요소가 실제 위치와 크게 다르면 보정
4. 누락 요소: 이미지에 있지만 JSON에 없는 요소 추가
5. role: title > subtitle > stat > body > label > caption 계층 확인
6. 차트 수치: 데이터 라벨이 보이면 그 값 우선 사용

수정된 전체 JSON을 반환하세요. 변경 없으면 그대로 반환.
JSON만 반환."""

PASS3_PROMPT = """\
이 슬라이드의 차트/그래프만 집중 분석하세요.

각 차트마다:
1. chartType: bar | line | pie | doughnut | area | stacked-bar | grouped-bar
2. title: 차트 제목
3. labels: X축 라벨 목록
4. datasets: [{ "name": "시리즈명", "values": [수치], "color": "#HEX" }]
5. unit: Y축 단위 (%, 원, 건 등)

## 수치 읽기
- 데이터 라벨(숫자가 막대/조각 위에 표시)이 있으면 그 값을 정확히 사용
- 없으면 Y축 눈금 기준으로 추정
- 원형: 각 조각 % (합계 100)
- 선그래프: 각 데이터포인트 값

차트 배열을 JSON으로 반환. 차트가 1개면 배열에 1개만."""


# ─── 유틸리티 ──────────────────────────────────────────────────────────

def repair_json(text: str) -> str:
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    cfg = Path.home() / ".openclaw" / "openclaw.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
            for tc in data.get("tools", {}).values():
                if isinstance(tc, dict):
                    for k, v in tc.items():
                        if "gemini" in k.lower() and "key" in k.lower():
                            return v
        except Exception:
            pass
    return ""


def pdf_to_images(pdf_path: str, dpi: int = DPI) -> list[tuple[int, bytes]]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("ERROR: pip install pymupdf")
        sys.exit(1)
    doc = fitz.open(pdf_path)
    imgs = []
    for i in range(len(doc)):
        pix = doc[i].get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
        imgs.append((i + 1, png))
        print(f"  페이지 {i + 1}/{len(doc)} → {len(png):,} bytes")
    doc.close()
    return imgs


# ─── Gemini API ────────────────────────────────────────────────────────

def call_gemini(img_bytes: bytes, prompt: str, api_key: str, model: str) -> str | None:
    b64 = base64.b64encode(img_bytes).decode()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 16384},
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, json=payload, timeout=120)
            if r.status_code == 429:
                w = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"    rate-limited, {w}s 대기…")
                time.sleep(w)
                continue
            if r.status_code != 200:
                print(f"    HTTP {r.status_code}: {r.text[:200]}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY * attempt)
                    continue
                return None
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except requests.exceptions.Timeout:
            print(f"    timeout (attempt {attempt})")
        except requests.exceptions.RequestException as e:
            print(f"    request error: {e}")
        except (KeyError, IndexError) as e:
            print(f"    response error: {e}")
            return None
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BASE_DELAY * attempt)
    return None


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(repair_json(text))
        except json.JSONDecodeError as e:
            print(f"    JSON 파싱 실패: {e}")
            return None


# ─── 오버플로우 보정 ───────────────────────────────────────────────────

def _is_wide(ch: str) -> bool:
    """CJK 전각 문자 여부."""
    try:
        return unicodedata.east_asian_width(ch) in ("W", "F")
    except Exception:
        return False


def _text_width_inches(text: str, fs: float) -> float:
    """한 줄 텍스트의 예상 렌더링 너비(인치)."""
    w = 0.0
    cw_latin = fs / 72 * 0.55
    cw_cjk = fs / 72 * 1.0
    for ch in text:
        if ch in ("\n", "\r"):
            continue
        w += cw_cjk if _is_wide(ch) else cw_latin
    return w


def fix_overflow(el: dict) -> dict:
    """텍스트 요소의 오버플로우를 감지하고 fontSize를 축소한다."""
    if el.get("type") != "text":
        return el
    content = el.get("content", "")
    if not content:
        return el

    fs = el.get("fontSize", 16)
    box_w = el.get("w_pct", 80) / 100 * SLIDE_W
    box_h = el.get("h_pct", 10) / 100 * SLIDE_H

    lines = content.split("\\n") if "\\n" in content else content.split("\n")
    original_fs = fs

    while fs >= MIN_FONT:
        lh = fs / 72 * LINE_H_RATIO
        total = 0
        for ln in lines:
            if not ln.strip():
                total += 1
                continue
            tw = _text_width_inches(ln, fs)
            total += max(1, math.ceil(tw / box_w)) if box_w > 0 else 1
        if total * lh <= box_h * 1.05:  # 5 % 여유
            break
        fs -= 1

    # 최대 30% 축소 제한 — Gemini 좌표 추정 오차 감안
    min_allowed = max(MIN_FONT, int(original_fs * 0.7))
    fs = max(fs, min_allowed)

    if fs < original_fs:
        el["fontSize"] = fs
        el["_overflow"] = {"original": original_fs, "adjusted": fs}
    return el


# ─── 슬라이드 추출 ────────────────────────────────────────────────────

def extract_slide(
    img: bytes,
    num: int,
    api_key: str,
    model: str,
    *,
    verify: bool = True,
    chart_detail: bool = True,
) -> dict:
    """단일 슬라이드 멀티패스 추출."""

    # ── Pass 1 ─────────────────────────────────────────────
    print(f"  S{num} [Pass 1] 구조 추출…")
    raw = call_gemini(img, PASS1_PROMPT, api_key, model)
    if not raw:
        return {"slide": num, "error": "pass1_failed", "elements": []}

    data = parse_json(raw)
    if not data:
        return {"slide": num, "error": "pass1_json", "elements": []}
    if isinstance(data, list):
        data = data[0] if data else {}

    result = {
        "slide": num,
        "background": data.get("background", {}),
        "elements": data.get("elements", []),
    }
    p1 = len(result["elements"])
    _types = _type_summary(result["elements"])
    print(f"         → {p1}개 요소 [{_types}]")

    # ── Pass 2 (검증) ──────────────────────────────────────
    if verify:
        print(f"  S{num} [Pass 2] 검증…")
        prompt2 = PASS2_PROMPT.format(
            extracted=json.dumps(result, ensure_ascii=False, indent=2)
        )
        raw2 = call_gemini(img, prompt2, api_key, model)
        if raw2:
            v = parse_json(raw2)
            if v:
                if isinstance(v, list):
                    v = v[0] if v else {}
                result["background"] = v.get("background", result["background"])
                result["elements"] = v.get("elements", result["elements"])
                p2 = len(result["elements"])
                delta = f" ({p1}→{p2})" if p2 != p1 else ""
                print(f"         → 검증 완료{delta}")
        else:
            print(f"         → 검증 건너뜀 (API 오류)")

    # ── Pass 3 (차트 정밀) ─────────────────────────────────
    charts = [i for i, e in enumerate(result["elements"]) if e.get("type") == "chart"]
    if charts and chart_detail:
        print(f"  S{num} [Pass 3] 차트 {len(charts)}개 정밀 분석…")
        raw3 = call_gemini(img, PASS3_PROMPT, api_key, model)
        if raw3:
            cd = parse_json(raw3)
            if cd:
                if isinstance(cd, dict):
                    cd = [cd]
                for ci, idx in enumerate(charts):
                    if ci >= len(cd):
                        break
                    el = result["elements"][idx]
                    src = cd[ci]
                    el["chartType"] = src.get("chartType", el.get("chartType", "bar"))
                    el["title"] = src.get("title", el.get("title", ""))
                    # labels는 비어있지 않을 때만 교체
                    src_labels = src.get("labels", [])
                    if src_labels:
                        el["labels"] = src_labels
                    if "datasets" in src:
                        el["datasets"] = src["datasets"]
                    elif "values" in src:
                        el["datasets"] = [
                            {"name": "", "values": src["values"],
                             "color": (src.get("colors") or ["#4A90D9"])[0]}
                        ]
                    if "unit" in src:
                        el["unit"] = src["unit"]
                print(f"         → {min(len(cd), len(charts))}개 차트 보강")

    # ── Post: 좌표 정규화 (0-1 → 0-100) ─────────────────────
    for el in result["elements"]:
        for key in ("x_pct", "y_pct", "w_pct", "h_pct"):
            v = el.get(key)
            if v is not None and v < 1.5:  # 0-1 범위면 %로 변환
                el[key] = round(v * 100, 1)

    # ── Post: 오버플로우 보정 ──────────────────────────────
    ov = 0
    for i in range(len(result["elements"])):
        result["elements"][i] = fix_overflow(result["elements"][i])
        if "_overflow" in result["elements"][i]:
            ov += 1
    if ov:
        print(f"  S{num} [Post] 오버플로우 보정 {ov}개")

    return result


def _type_summary(elements: list) -> str:
    c: dict[str, int] = {}
    for e in elements:
        t = e.get("type", "?")
        c[t] = c.get(t, 0) + 1
    return ", ".join(f"{t}:{n}" for t, n in sorted(c.items()))


# ─── 스타일 가이드 ────────────────────────────────────────────────────

def build_style_guide(slides: list) -> dict:
    bg_ctr: Counter = Counter()
    txt_ctr: Counter = Counter()
    sizes: dict[str, list] = {
        "title": [], "subtitle": [], "stat": [],
        "body": [], "label": [], "caption": [],
    }
    counts = []

    shape_ctr: Counter = Counter()

    for s in slides:
        bg = s.get("background", {})
        if isinstance(bg, dict) and "color" in bg:
            bg_ctr[bg["color"]] += 1
        counts.append(len(s.get("elements", [])))
        for el in s.get("elements", []):
            # shape fill 색상 수집
            if el.get("type") == "shape" and el.get("fill"):
                shape_ctr[el["fill"]] += 1
            # chart dataset 색상 수집
            if el.get("type") == "chart":
                for ds in el.get("datasets", []):
                    c = ds.get("color")
                    if c and isinstance(c, str):
                        shape_ctr[c] += 1
                    elif c and isinstance(c, list):
                        for cc in c:
                            if isinstance(cc, str):
                                shape_ctr[cc] += 1
            if el.get("type") != "text":
                continue
            c = el.get("color", "")
            if c:
                txt_ctr[c] += 1
            role = el.get("role", "body")
            fs = el.get("fontSize")
            if fs and role in sizes:
                sizes[role].append(fs)

    def _med(vals):
        if not vals:
            return None
        v = sorted(vals)
        return v[len(v) // 2]

    NEUTRAL = {"#FFFFFF", "#FFF", "#000000", "#000"}
    # shape/chart 색상을 우선, 텍스트 색상은 보조
    all_accents = shape_ctr + txt_ctr
    accents = [c for c, _ in all_accents.most_common(10)
               if c.upper() not in {n.upper() for n in NEUTRAL}]

    return {
        "palette": {
            "backgrounds": [c for c, _ in bg_ctr.most_common(4)],
            "text_primary": (txt_ctr.most_common(1)[0][0] if txt_ctr else "#FFFFFF"),
            "accent_colors": accents[:3],
        },
        "typography": {
            role: int(_med(v)) for role, v in sizes.items() if v
        },
        "density": {
            "avg_elements": round(sum(counts) / max(len(counts), 1), 1),
            "max_elements": max(counts, default=0),
        },
    }


# ─── 메인 ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="NLM 슬라이드 해체 v7 — 멀티패스 Gemini Vision"
    )
    ap.add_argument("input", help="PDF 파일 경로")
    ap.add_argument("--output", "-o", default="v7-output.json")
    ap.add_argument("--model", "-m", default=DEFAULT_MODEL)
    ap.add_argument("--dpi", type=int, default=DPI)
    ap.add_argument("--pages", "-p", help="예: 1,3,5 또는 1-5")
    ap.add_argument("--fast", action="store_true",
                    help="Pass 1만 실행 (검증·차트 정밀 건너뜀)")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"ERROR: 파일 없음 — {inp}")
        sys.exit(1)
    if inp.suffix.lower() != ".pdf":
        print(f"ERROR: PDF만 지원 — {inp.suffix}")
        sys.exit(1)

    api_key = get_api_key()
    if not api_key:
        print("ERROR: GEMINI_API_KEY 설정 필요 (.env 또는 환경변수)")
        sys.exit(1)

    # 페이지 범위
    pages = None
    if args.pages:
        pages = set()
        for p in args.pages.split(","):
            p = p.strip()
            if "-" in p:
                a, b = p.split("-", 1)
                pages.update(range(int(a), int(b) + 1))
            else:
                pages.add(int(p))

    mode = "fast (Pass 1만)" if args.fast else "full (Pass 1→2→3 + 보정)"
    print(f"{'=' * 50}")
    print(f"  NLM 슬라이드 해체 v7")
    print(f"  입력  : {inp}")
    print(f"  모델  : {args.model}")
    print(f"  DPI   : {args.dpi}")
    print(f"  모드  : {mode}")
    print(f"{'=' * 50}")
    print()

    # Step 1 — PDF → 이미지
    print("[1/3] PDF → 이미지")
    images = pdf_to_images(str(inp), dpi=args.dpi)
    if pages:
        images = [(n, im) for n, im in images if n in pages]
        print(f"  → {len(images)}페이지 선택")
    print()

    # Step 2 — 멀티패스 추출
    print(f"[2/3] 멀티패스 추출 ({len(images)}페이지)")
    slides = []
    for num, img in images:
        s = extract_slide(
            img, num, api_key, args.model,
            verify=not args.fast,
            chart_detail=not args.fast,
        )
        slides.append(s)
        print()

    # Step 3 — 스타일 가이드 + 출력
    print("[3/3] 스타일 가이드 생성 + 저장")
    guide = build_style_guide(slides)

    output = {
        "metadata": {
            "source": "nlm",
            "version": "v7",
            "model": args.model,
            "dpi": args.dpi,
            "slides_count": len(slides),
            "mode": "fast" if args.fast else "full",
        },
        "style_guide": guide,
        "slides": slides,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 요약 ──
    total = sum(len(s.get("elements", [])) for s in slides)
    errs = [s for s in slides if "error" in s]
    ovf = sum(1 for s in slides for e in s.get("elements", []) if "_overflow" in e)

    print()
    print(f"{'=' * 50}")
    print(f"  완료!")
    print(f"  출력      : {out}")
    print(f"  슬라이드  : {len(slides)}장")
    print(f"  총 요소   : {total}개")
    print(f"  오버플로우: {ovf}개 보정")
    if errs:
        print(f"  오류      : {len(errs)}장 ({', '.join(str(s['slide']) for s in errs)})")
    ts = _type_summary([e for s in slides for e in s.get("elements", [])])
    if ts:
        print(f"  요소 분포 : {ts}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
