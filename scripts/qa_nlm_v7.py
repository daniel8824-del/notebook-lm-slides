#!/usr/bin/env python3
"""QA 루프: 원본 NLM 슬라이드 vs 렌더링 PPTX 비교 → 점수 + 개선안 → 반복.

파이프라인:
  1. render_nlm_v7b.js로 PPTX 렌더링
  2. PowerPoint COM으로 PDF 변환
  3. PDF → 이미지
  4. 원본 NLM PDF → 이미지
  5. Gemini Vision으로 슬라이드별 비교 → 점수 + 개선안
  6. 점수 < 목표면 개선안 출력 후 반복 대기

Usage:
    python3 qa_nlm_v7.py original.pdf v7-output.json -o output.pptx --target 95
    python3 qa_nlm_v7.py original.pdf v7-output.json --auto  # 자동 반복 모드
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_RETRIES = 3
RETRY_DELAY = 2.0
NODE_PATH = subprocess.run(
    ["npm", "root", "-g"], capture_output=True, text=True
).stdout.strip()

QA_PROMPT = """\
두 슬라이드 이미지를 비교하세요.

**왼쪽 = 원본 (NLM 생성)**, **오른쪽 = 재생성 (PptxGenJS)**

## 평가 기준 (각 20점, 총 100점)

1. **텍스트 정확도** (20점): 내용이 동일한가? 빠진 텍스트, 오타, 잘린 내용?
2. **레이아웃 유사도** (20점): 요소 배치가 원본과 비슷한가? 겹침, 어긋남?
3. **색상/디자인** (20점): 배경색, 텍스트색, 차트색이 원본과 일치하는가?
4. **가독성** (20점): 텍스트 크기, 줄바꿈, 여백이 적절한가? 읽기 편한가?
5. **차트/데이터** (20점): 차트 타입, 데이터 값, 비율이 정확한가?

## 출력 형식 (JSON)

```json
{
  "slide": 슬라이드번호,
  "scores": {
    "text_accuracy": 숫자,
    "layout_similarity": 숫자,
    "color_design": 숫자,
    "readability": 숫자,
    "chart_data": 숫자
  },
  "total": 합계,
  "issues": [
    {"severity": "high|medium|low", "category": "카테고리", "description": "구체적 문제", "fix": "수정 방법"}
  ]
}
```

차트/데이터가 없는 슬라이드는 chart_data를 텍스트 완성도로 대체 평가.
JSON만 반환."""


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


def pdf_to_images(pdf_path: str, dpi: int = 150) -> list[tuple[int, bytes]]:
    """PDF → PNG 이미지 리스트."""
    try:
        import fitz
    except ImportError:
        print("ERROR: pip install pymupdf")
        sys.exit(1)
    doc = fitz.open(pdf_path)
    imgs = []
    for i in range(len(doc)):
        pix = doc[i].get_pixmap(dpi=dpi)
        imgs.append((i + 1, pix.tobytes("png")))
    doc.close()
    return imgs


def render_pptx(json_path: str, output_pptx: str) -> bool:
    """render_nlm_v7b.js 실행."""
    script = Path(__file__).parent / "render_nlm_v7b.js"
    env = os.environ.copy()
    env["NODE_PATH"] = NODE_PATH
    r = subprocess.run(
        ["node", str(script), json_path, "-o", output_pptx],
        capture_output=True, text=True, env=env,
    )
    if r.returncode != 0:
        print(f"  렌더링 실패: {r.stderr[:300]}")
        return False
    return True


def pptx_to_pdf(pptx_win_path: str, pdf_win_path: str) -> bool:
    """PowerPoint COM으로 PDF 변환."""
    ps_cmd = f"""
$pp = New-Object -ComObject PowerPoint.Application
$pres = $pp.Presentations.Open('{pptx_win_path}', $true, $true, $false)
$pres.SaveAs('{pdf_win_path}', 32)
$pres.Close()
$pp.Quit()
Write-Output 'OK'
"""
    r = subprocess.run(
        ["powershell.exe", "-Command", ps_cmd],
        capture_output=True, text=True,
    )
    return "OK" in r.stdout


def wsl_to_win(wsl_path: str) -> str:
    """WSL 경로 → Windows 경로 변환."""
    r = subprocess.run(
        ["wslpath", "-w", wsl_path], capture_output=True, text=True
    )
    return r.stdout.strip()


def call_gemini_compare(
    img1_bytes: bytes,
    img2_bytes: bytes,
    slide_num: int,
    api_key: str,
    model: str,
) -> dict | None:
    """두 이미지를 Gemini Vision으로 비교."""
    b64_1 = base64.b64encode(img1_bytes).decode()
    b64_2 = base64.b64encode(img2_bytes).decode()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": QA_PROMPT},
                {"inline_data": {"mime_type": "image/png", "data": b64_1}},
                {"inline_data": {"mime_type": "image/png", "data": b64_2}},
            ]
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096},
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, json=payload, timeout=120)
            if r.status_code == 429:
                time.sleep(RETRY_DELAY * (2 ** (attempt - 1)))
                continue
            if r.status_code != 200:
                print(f"    API 오류 {r.status_code}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                return None
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = re.sub(r",\s*([}\]])", r"\1", text.strip())
            return json.loads(text)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"    파싱 오류: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            return None
        except requests.exceptions.RequestException as e:
            print(f"    요청 오류: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                continue
            return None
    return None


def run_qa_round(
    original_images: list[tuple[int, bytes]],
    rendered_images: list[tuple[int, bytes]],
    api_key: str,
    model: str,
    target_pages: set | None = None,
) -> list[dict]:
    """한 라운드 QA: 슬라이드별 비교."""
    results = []
    for (orig_num, orig_img), (rend_num, rend_img) in zip(original_images, rendered_images):
        if target_pages and orig_num not in target_pages:
            continue
        print(f"  S{orig_num} 비교 중...")
        qa = call_gemini_compare(orig_img, rend_img, orig_num, api_key, model)
        if qa:
            qa["slide"] = orig_num
            total = qa.get("total", sum(qa.get("scores", {}).values()))
            qa["total"] = total
            issues = qa.get("issues", [])
            high = sum(1 for i in issues if i.get("severity") == "high")
            med = sum(1 for i in issues if i.get("severity") == "medium")
            print(f"    → {total}/100점 (이슈: high={high}, medium={med})")
            results.append(qa)
        else:
            print(f"    → 비교 실패")
            results.append({"slide": orig_num, "total": 0, "error": "comparison_failed"})
    return results


def main():
    ap = argparse.ArgumentParser(description="NLM v7 QA 루프")
    ap.add_argument("original", help="원본 NLM PDF")
    ap.add_argument("json_input", help="v7 추출 JSON")
    ap.add_argument("--output", "-o", default="/tmp/v7-qa-output.pptx")
    ap.add_argument("--target", type=int, default=97, help="목표 점수 (기본: 97)")
    ap.add_argument("--model", "-m", default=DEFAULT_MODEL)
    ap.add_argument("--pages", "-p", help="특정 페이지만 (예: 1,2)")
    ap.add_argument("--max-rounds", type=int, default=5, help="최대 반복 횟수")
    ap.add_argument("--report", default="/tmp/v7-qa-report.json", help="QA 리포트 경로")
    args = ap.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("ERROR: GEMINI_API_KEY 필요")
        sys.exit(1)

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

    print("=" * 55)
    print("  NLM v7 QA 루프")
    print("=" * 55)
    print(f"  원본    : {args.original}")
    print(f"  JSON    : {args.json_input}")
    print(f"  목표    : {args.target}점")
    print(f"  최대반복: {args.max_rounds}회")
    print()

    # 원본 이미지 준비
    print("[준비] 원본 PDF → 이미지")
    orig_images = pdf_to_images(args.original, dpi=150)
    if pages:
        orig_images = [(n, img) for n, img in orig_images if n in pages]
    print(f"  → {len(orig_images)}페이지")
    print()

    all_rounds = []

    for round_num in range(1, args.max_rounds + 1):
        print(f"{'─' * 55}")
        print(f"  라운드 {round_num}/{args.max_rounds}")
        print(f"{'─' * 55}")

        # Step 1: 렌더링
        print("[1] PPTX 렌더링")
        if not render_pptx(args.json_input, args.output):
            print("  렌더링 실패, 중단")
            break
        print("  → OK")

        # Step 2: PDF 변환
        print("[2] PowerPoint → PDF")
        win_pptx = wsl_to_win(str(Path(args.output).resolve()))
        win_pdf = win_pptx.replace(".pptx", ".pdf")
        wsl_pdf = args.output.replace(".pptx", ".pdf")
        if not pptx_to_pdf(win_pptx, win_pdf):
            print("  PDF 변환 실패, 중단")
            break
        print("  → OK")

        # Step 3: 렌더링 이미지 추출
        print("[3] 렌더링 PDF → 이미지")
        rend_images = pdf_to_images(wsl_pdf, dpi=150)
        if pages:
            rend_images = [(n, img) for n, img in rend_images if n in pages]
        print(f"  → {len(rend_images)}페이지")

        # Step 4: Gemini Vision 비교
        print("[4] 원본 vs 렌더링 비교")
        results = run_qa_round(orig_images, rend_images, api_key, args.model, pages)

        avg_score = sum(r.get("total", 0) for r in results) / max(len(results), 1)
        all_rounds.append({
            "round": round_num,
            "avg_score": round(avg_score, 1),
            "slides": results,
        })

        print()
        print(f"  ★ 평균 점수: {avg_score:.1f}/100")

        if avg_score >= args.target:
            print(f"  ✓ 목표 {args.target}점 달성!")
            break

        # 개선안 출력
        print()
        print("  [개선안]")
        for r in results:
            if r.get("total", 0) >= args.target:
                continue
            for issue in r.get("issues", []):
                sev = issue.get("severity", "?")
                cat = issue.get("category", "?")
                desc = issue.get("description", "")
                fix = issue.get("fix", "")
                marker = "🔴" if sev == "high" else "🟡" if sev == "medium" else "⚪"
                print(f"    {marker} S{r['slide']} [{cat}] {desc}")
                if fix:
                    print(f"       → {fix}")

        if round_num < args.max_rounds:
            print()
            print(f"  다음 라운드를 위해 render_nlm_v7b.js를 수정한 뒤 다시 실행하세요.")
            print(f"  또는 Ctrl+C로 중단.")
            print()
            try:
                input("  [Enter] 다음 라운드 시작...")
            except (KeyboardInterrupt, EOFError):
                print("\n  중단됨.")
                break
        print()

    # 최종 리포트
    report = {
        "target": args.target,
        "rounds": all_rounds,
        "final_score": all_rounds[-1]["avg_score"] if all_rounds else 0,
        "achieved": all_rounds[-1]["avg_score"] >= args.target if all_rounds else False,
    }

    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 55)
    print(f"  QA 완료")
    print(f"  최종 점수 : {report['final_score']}/100")
    print(f"  목표 달성 : {'Yes' if report['achieved'] else 'No'}")
    print(f"  라운드    : {len(all_rounds)}회")
    print(f"  리포트    : {args.report}")
    print("=" * 55)


if __name__ == "__main__":
    main()
