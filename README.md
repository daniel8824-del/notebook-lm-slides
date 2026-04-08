# notebook-lm-slides

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![Node.js](https://img.shields.io/badge/Node.js-18%2B-green?logo=node.js)](https://nodejs.org)
[![notebooklm-py](https://img.shields.io/badge/notebooklm--py-PyPI-orange)](https://pypi.org/project/notebooklm-py/)
[![Gemini](https://img.shields.io/badge/Gemini-API-blue?logo=google)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Google NotebookLM 슬라이드를 **편집 가능한 PPTX**로 변환하는 v7 파이프라인 + Claude Code 스킬.

NLM이 생성한 슬라이드 PDF를 Gemini Vision으로 해체하고, Role 기반 템플릿 렌더러로 재조립해 PowerPoint에서 직접 편집 가능한 `.pptx`를 만든다.

---

## Features

- **A/B 바구니 시스템**: 내용 자료(A)와 디자인 레퍼런스(B)를 분리 관리
- **5단계 워크플로우**: 소스 준비 → 가이드 생성 → 프롬프트 설계 → NLM 슬라이드 생성 → PPTX 추출
- **Gemini Vision 멀티패스 추출** (`extract_nlm_v7.py`): 구조 추출 → 검증 → 차트 정밀의 3-pass 파이프라인
- **Role 기반 템플릿 렌더링** (`render_nlm_v7b.js`): title/subtitle/stat/body/label/caption 역할 기반 레이아웃
- **QA 루프** (`qa_nlm_v7.py`): 원본 NLM vs 렌더링 PPTX 비교, Gemini Vision 채점 (95점+ 목표)
- **49종 스타일 키워드**: 비주얼 디렉팅 언어로 디자인 방향 제어
- **JSON Slide Master**: B바구니 레퍼런스에서 색상/레이아웃 패턴 추출
- **Claude Code 스킬 연동**: `/notebook-lm` 또는 `노트북LM` 키워드로 자동 활성화

---

## 사용 방법

### 1. Claude Code 스킬로 사용

`SKILL.md`와 `cli-reference.md`를 Claude Code 스킬로 설치한다.

```bash
# 스킬 설치 (oh-my-claudecode 사용 시)
cp SKILL.md ~/.claude/skills/notebook-lm/SKILL.md
cp cli-reference.md ~/.claude/skills/notebook-lm/cli-reference.md
```

설치 후 Claude Code에서 `노트북LM`, `NLM`, `/notebook-lm` 키워드로 스킬이 자동 활성화된다.

### 2. Google Antigravity (notebooklm CLI) 직접 사용

`notebooklm` CLI를 직접 사용해 파이프라인을 실행한다.

```bash
# 노트북 생성 및 소스 추가
notebooklm create "Slides: [주제]"
notebooklm source add ./data.pdf
notebooklm source add "https://article-url.com"

# 슬라이드 생성 및 PDF 다운로드
notebooklm generate slide-deck "커스텀 프롬프트"
notebooklm download slide-deck ./slides.pdf

# v7 파이프라인으로 편집 가능한 PPTX 생성
python3 scripts/extract_nlm_v7.py ./slides.pdf -o ./extracted/v7.json
node scripts/render_nlm_v7b.js ./extracted/v7.json -o ./output.pptx
python3 scripts/qa_nlm_v7.py ./slides.pdf ./extracted/v7.json -o ./output.pptx --target 95
```

---

## ⚠️ 필수 사전 설정

### 1. notebooklm-py 설치

```bash
pip install notebooklm-py
```

### 2. Google OAuth 인증 (브라우저 로그인)

```bash
notebooklm login
```

명령 실행 시 브라우저가 열리며 Google 계정으로 로그인한다. **로컬 환경에서만 가능하며, 서버/CI 환경에서는 불가하다.**

### 3. 인증 상태 확인

```bash
notebooklm status
# → "Authenticated as: email@gmail.com" 출력되어야 정상
```

### 4. Gemini API Key 설정

v7 추출 파이프라인(`extract_nlm_v7.py`, `qa_nlm_v7.py`)은 Gemini Vision API를 사용한다.

```bash
export GEMINI_API_KEY="your-api-key-here"
# 또는 .env 파일에 저장
echo "GEMINI_API_KEY=your-api-key-here" >> .env
```

[Gemini API Key 발급](https://ai.google.dev/)

---

## 전체 파이프라인 ⓪~⑧

```
소스 준비 → 가이드 생성 → 프롬프트 설계 → NLM 슬라이드 생성
  → PDF 다운로드 → Gemini Vision 추출 → PPTX 렌더링 → QA → 편집 가능한 .pptx
```

| 단계 | 도구 | 아웃풋 |
|------|------|--------|
| ⓪ 노트북 생성 | `notebooklm create "Slides: [주제]"` | NLM 노트북 |
| ① 소스 준비 | `notebooklm source add` | NLM 노트북 with 소스 |
| ② 가이드 생성 | `notebooklm ask --save-as-note` | 슬라이드 가이드 (메모 → 소스) |
| ③ 프롬프트 설계 | 5요소 구조 + 스타일 키워드 | 커스텀 프롬프트 |
| ④ 슬라이드 생성 | `notebooklm generate slide-deck` | NLM 슬라이드 |
| ⑤ PDF 다운로드 | `notebooklm download slide-deck ./slides.pdf` | `slides.pdf` |
| ⑥ 추출 | `extract_nlm_v7.py` (Gemini Vision 멀티패스) | 레이아웃/텍스트/이미지 JSON |
| ⑦ 렌더링 | `render_nlm_v7b.js` (Role 기반 템플릿) | `output.pptx` |
| ⑧ QA | `qa_nlm_v7.py` (원본 비교, 95점+ 목표) | **`output.pptx` (최종)** |

**최종 아웃풋은 편집 가능한 `.pptx` 파일이다.** 이미지와 텍스트가 분리되어 PowerPoint에서 직접 편집 가능.

---

## v7 스크립트 역할

### `scripts/extract_nlm_v7.py` — Gemini Vision 멀티패스 추출기

NLM 슬라이드 PDF를 300dpi 이미지로 변환한 뒤, Gemini Vision으로 3단계 분석한다.

- **Pass 1**: 구조 추출 — 텍스트, 차트, 테이블, 도형, 이미지 요소 추출
- **Pass 2**: 검증 — 추출 결과의 정확성 교차검증
- **Pass 3**: 차트 정밀 분석 — 차트 타입, 데이터 값, 비율 정밀 추출

각 요소에 `role` (title/subtitle/stat/body/label/caption)을 부여하고, 오버플로우 방지를 위한 `fontSize` 자동 조정을 포함한 JSON을 출력한다.

```bash
python3 scripts/extract_nlm_v7.py input.pdf -o output.json
python3 scripts/extract_nlm_v7.py input.pdf --model gemini-2.5-flash --pages 1-3
python3 scripts/extract_nlm_v7.py input.pdf --fast  # Pass 2,3 건너뛰기
```

### `scripts/render_nlm_v7b.js` — Role 기반 템플릿 렌더러

v7 JSON의 `role` 정보를 활용해 검증된 레이아웃 템플릿으로 PPTX를 생성한다. 원본 좌표는 버리고 슬라이드 아키타입(cover/stats/chart/table/body 등)을 자동 감지하여 최적 레이아웃을 적용한다.

```bash
node scripts/render_nlm_v7b.js v7-output.json -o output.pptx
```

### `scripts/qa_nlm_v7.py` — 원본 비교 QA 루프

원본 NLM PDF와 렌더링된 PPTX를 Gemini Vision으로 슬라이드별 비교한다. 텍스트 정확도·레이아웃·색상·가독성·차트 데이터 5개 항목(각 20점, 총 100점)으로 채점하고, 목표 점수 미달 시 개선 방안을 출력한다.

```bash
python3 scripts/qa_nlm_v7.py original.pdf v7-output.json -o output.pptx --target 95
python3 scripts/qa_nlm_v7.py original.pdf v7-output.json --auto  # 자동 반복 모드
```

---

## A/B 바구니 시스템

소스를 두 바구니로 분류해 관리한다.

| 바구니 | 용도 | 예시 |
|--------|------|------|
| **A바구니** — 내용 자료 | NLM 소스로 활용, 슬라이드 콘텐츠 생성 | PDF, DOCX, URL, CSV, 음성, 이미지 |
| **B바구니** — 디자인 레퍼런스 | JSON Slide Master 추출, 스타일 적용 | PPT, PDF 템플릿, 브랜드 가이드 |

B바구니가 없으면 에이전트가 주제/목적 기반으로 스타일을 직접 작성한다.

---

## 49종 스타일 키워드

슬라이드 프롬프트에 스타일 키워드를 포함하면 시각적 방향을 정밀하게 제어할 수 있다.

키워드는 `SKILL.md` 내 "스타일 키워드" 섹션에서 전체 목록을 확인할 수 있다. 색상 계열, 레이아웃 스타일, 무드/톤, 산업별 테마 등 49종이 포함되어 있다.

---

## 주의사항

- **NotebookLM 로그인은 로컬 환경에서만 가능하다.** 서버/CI 환경에서는 `notebooklm login`이 작동하지 않는다.
- **세션 쿠키 만료 시 `notebooklm login`을 재실행해야 한다.** 인증 오류 발생 시 `notebooklm auth check`로 진단 후 재로그인.
- **NLM rate limit**: Google 서비스 특성상 슬라이드 생성 실패 시 5~10분 후 재시도한다.
- **v7 추출 파이프라인에 Gemini API key가 필수다.** `GEMINI_API_KEY` 환경변수 또는 `.env` 파일에 설정.
- **병렬 에이전트 사용 시**: `notebooklm use` 대신 `-n <notebook_id>` 플래그를 사용해 컨텍스트 충돌을 방지한다.

---

## License

MIT — see [LICENSE](LICENSE)
