#!/usr/bin/env python3
"""시각 비교 자동 피드백 — 범용 워크스페이스 지원"""
import argparse, os, json, copy, glob
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
import fitz

load_dotenv(Path.home() / 'slide-generator-app/.env')
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

parser = argparse.ArgumentParser(description='NLM 시각 비교 피드백 루프')
parser.add_argument('workspace', nargs='?', default='.', help='워크스페이스 디렉토리 (기본: 현재 디렉토리)')
parser.add_argument('--pdf', default=None, help='원본 PDF 파일명 (기본: slides.pdf)')
parser.add_argument('--extracted', default='extracted.json', help='추출 JSON 파일명')
parser.add_argument('--rendered', default=None, help='렌더된 PPTX 또는 썸네일 디렉토리')
parser.add_argument('-o', '--output', default='extracted_refined.json', help='보정된 JSON 출력 파일명')
args = parser.parse_args()

ws = Path(args.workspace).resolve()

# PDF 자동 탐색
pdf_path = ws / (args.pdf or 'slides.pdf')
if not pdf_path.exists():
    # slides.pdf 없으면 *.pdf 중 첫 번째
    pdfs = sorted(ws.glob('*.pdf'))
    pdf_path = pdfs[0] if pdfs else pdf_path

# 렌더 썸네일 자동 탐색: thumbs/ 또는 original/ 폴더의 JPG/PNG
rend_dir = None
if args.rendered:
    rend_dir = Path(args.rendered)
else:
    for candidate in ['thumbs', 'rendered', 'qa']:
        p = ws / candidate
        if p.exists() and list(p.glob('*.JPG')) + list(p.glob('*.jpg')) + list(p.glob('*.png')):
            rend_dir = p
            break

prompt_template = """Compare these two presentation slides.
IMAGE 1: ORIGINAL (from NotebookLM PDF)
IMAGE 2: RENDERED (editable PPTX, exported as JPG)

For EACH text element that is MISALIGNED in the rendered version, provide correction.

Return JSON array:
- "text": content (first 30 chars)
- "delta": [Δx_percent, Δy_percent] shift needed (positive=right/down)
- "severity": "critical"|"minor"|"ok"

Include ALL text elements. If aligned correctly, use severity "ok" with delta [0,0].
Return ONLY valid JSON."""

extracted = json.loads((ws / args.extracted).read_text())
doc = fitz.open(str(pdf_path))
num_slides = len(doc)

corrections = {}
for slide_num in range(1, num_slides + 1):
    print(f'S{slide_num}: 비교 중...')

    # 원본 PNG (PDF에서 렌더)
    page = doc[slide_num - 1]
    mat = fitz.Matrix(150/72, 150/72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    orig_bytes = pix.tobytes('png')

    # 렌더된 이미지 탐색
    rend_bytes = None
    if rend_dir:
        for pattern in [f'*{slide_num}.JPG', f'*{slide_num}.jpg', f'*{slide_num:02d}*.jpg', f'*{slide_num:02d}*.png', f'슬라이드{slide_num}.JPG']:
            matches = list(rend_dir.glob(pattern))
            if matches:
                rend_bytes = matches[0].read_bytes()
                break

    if not rend_bytes:
        print(f'  ⚠️ 렌더 이미지 없음 — 스킵')
        continue
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(data=orig_bytes, mime_type='image/png'),
                types.Part.from_bytes(data=rend_bytes, mime_type='image/jpeg'),
                prompt_template,
            ],
            config=types.GenerateContentConfig(response_mime_type='application/json'),
        )
        data = json.loads(response.text)
        
        critical = sum(1 for d in data if d.get('severity') == 'critical')
        minor = sum(1 for d in data if d.get('severity') == 'minor')
        ok = sum(1 for d in data if d.get('severity') == 'ok')
        corrections[slide_num] = data
        print(f'  ✅ {len(data)}개 — ok:{ok} minor:{minor} critical:{critical}')
    except Exception as e:
        print(f'  ❌ 오류: {e}')

doc.close()

# 보정 적용 — extracted.json 복사본에 delta 반영
print('\n=== 좌표 보정 적용 ===')
refined = copy.deepcopy(extracted)

for slide_num, feedbacks in corrections.items():
    sd = refined['slides'][slide_num - 1]
    elements = sd.get('elements', [])
    
    for fb in feedbacks:
        if fb.get('severity') == 'ok':
            continue
        delta = fb.get('delta', [0, 0])
        if abs(delta[0]) < 0.1 and abs(delta[1]) < 0.1:
            continue
        
        fb_text = fb.get('text', '')[:20].strip().lower()
        
        for el in elements:
            if el.get('type') != 'text':
                continue
            el_text = (el.get('content', '') or '')[:20].strip().lower()
            if fb_text and el_text and fb_text[:10] in el_text[:15]:
                el['x_pct'] = round(el.get('x_pct', 0) + delta[0], 2)
                el['y_pct'] = round(el.get('y_pct', 0) + delta[1], 2)
                break

out_path = ws / args.output
out_path.write_text(json.dumps(refined, ensure_ascii=False, indent=2))
print(f'\n보정된 JSON: {out_path}')

# 요약
corr_path = ws / 'visual_corrections.json'
corr_path.write_text(json.dumps(corrections, ensure_ascii=False, indent=2))
print(f'전체 보정 데이터: {corr_path}')
