---
name: notebook-lm
description: NotebookLM custom slide generator with style keywords and quality checklist
---

# NLM 슬라이드 커스텀 제작

> NLM CLI 기본 사용법(인증, 소스 관리, 기타 아티팩트)은 [cli-reference.md](cli-reference.md) 참조. `notebooklm --help`로도 확인 가능.

## 전체 파이프라인 & 최종 아웃풋

NLM 슬라이드를 편집 가능한 PPTX로 변환하는 4-Phase 파이프라인.

```
Phase A: NLM 생성   → 소스 준비 → 가이드 → 프롬프트 → 슬라이드 생성 → PDF 다운로드
Phase B: 추출+변환  → Gemini Vision 추출 → 인페인팅 → 1차 렌더링
Phase C: 정밀 보정  → 시각 비교 피드백 루프 (원본 vs 렌더 → 좌표 보정 × 3라운드)
Phase D: 최종 QA    → 구조 검증 + 시각 검수 → 편집 가능한 .pptx 완성
```

### Phase A: NLM 슬라이드 생성

| 단계 | 도구 | 아웃풋 |
|------|------|--------|
| A-1 노트북 생성 | `notebooklm create "Slides: [주제]"` | NLM 노트북 |
| A-2 소스 준비 | `notebooklm source add` | 소스 등록 |
| A-3 가이드 생성 | `notebooklm ask --save-as-note` | 슬라이드 가이드 |
| A-4 프롬프트 설계 | 5요소 구조 + 스타일 키워드 | 커스텀 프롬프트 |
| A-5 슬라이드 생성 | `notebooklm generate slide-deck` | NLM 슬라이드 |
| A-6 PDF 다운로드 | `notebooklm download slide-deck` | `slides.pdf` |

### Phase B: 추출 + 인페인팅 + 1차 렌더링

| 단계 | 스크립트 | 설명 | 아웃풋 |
|------|---------|------|--------|
| B-1 추출 | `nlm_extract.py` | Gemini Vision 멀티패스 — 텍스트/역할/좌표/차트/테이블 | `extracted.json` |
| B-2 인페인팅 | `nlm_inpaint.py` | Gemini 이미지 모델로 텍스트 제거 (5패스) + 업스케일 | `clean/slide_NN_clean.png` |
| B-3 렌더링 | `nlm_render.js` | 클린 배경 이미지 + 흰색 마스크 + 텍스트 오버레이 | `output.pptx` |

### Phase C: 시각 비교 피드백 루프 (★ 품질 결정 단계)

| 단계 | 스크립트 | 설명 |
|------|---------|------|
| C-1 썸네일 추출 | PowerShell COM | 렌더된 PPTX → JPG |
| C-2 시각 비교 | `nlm_visual_refine.py` | 원본 PDF PNG + 렌더 JPG → Gemini 비교 → Δx%, Δy% 보정값 |
| C-3 좌표 보정 | 자동 적용 | `extracted.json` 좌표에 delta 반영 → `extracted_refined.json` |
| C-4 재렌더링 | `nlm_render.js` | 보정된 좌표로 재렌더링 |
| **반복** | **C-1 ~ C-4를 3라운드** | critical 0 수렴까지 반복 |

> **핵심 원칙**: 좌표를 한 번에 완벽하게 추출하려 하지 말 것. **대략 추출 → 시각 비교 → 보정 반복**이 정답.
> 3라운드 피드백으로 BeautyDecode 13장 중 9/13 critical 0 달성 (2026-04-10 실증).

### Phase D: 최종 QA

| 단계 | 도구 | 설명 |
|------|------|------|
| D-1 구조 검증 | `validate_pptx.py` | ZIP 무결성, 슬라이드 수, 폰트 일관성 등 9항목 |
| D-2 콘텐츠 확인 | `markitdown` | 텍스트 추출 + placeholder 잔존 확인 |
| D-3 시각 검수 | PowerShell COM → JPG | 최종 출력 썸네일로 시각 확인 |

### 스크립트 레퍼런스

모든 스크립트는 `~/slide-generator-app/scripts/`에 위치.

| 스크립트 | 역할 |
|---------|------|
| `nlm_extract.py` | Gemini Vision 멀티패스 추출 — 텍스트/역할/좌표/차트/테이블 |
| `nlm_inpaint.py` | Gemini 이미지 모델 텍스트 제거 (5패스) |
| `nlm_render.js` | PptxGenJS 렌더러 — 클린 배경 + 흰색 마스크 + 텍스트 오버레이 |
| `nlm_visual_refine.py` | 시각 비교 피드백 — 원본 vs 렌더 → Δ좌표 보정 |
| `nlm_bbox_extract.py` | (보조) 픽셀 정밀 bbox 추출 — 표 전용 |

### 인페인팅 설정

| 항목 | 값 |
|------|---|
| 모델 | `gemini-3.1-flash-image-preview` |
| 패스 | 5회 (1차 제거 + 4차 잔상 제거) |
| 입력 DPI | 300 |
| 출력 해상도 | ~1376x768 (모델 제한) → LANCZOS 업스케일 |
| 업스케일 타겟 | 원본 PDF 해상도 (예: 5734x3200) |

### 실행 예시

```bash
WS=/mnt/c/Users/daniel/Desktop/프레젠테이션/workspace/nlm_주제_YYYYMMDD
cd $WS

# === Phase B ===
# B-1: 추출
python3 ~/slide-generator-app/scripts/nlm_extract.py slides.pdf -o extracted.json

# B-2: 인페인팅 (5패스 + 업스케일)
python3 ~/slide-generator-app/scripts/nlm_inpaint.py slides.pdf \
  --slides 1,2,...,N --output ./clean/
python3 -c "
from PIL import Image
for i in range(1, N+1):
    p = f'clean/slide_{i:02d}_clean.png'
    Image.open(p).resize((5734, 3200), Image.LANCZOS).save(p)
"

# B-3: 1차 렌더링
node ~/slide-generator-app/scripts/nlm_render.js extracted.json --clean ./clean/ -o output.pptx

# === Phase C === (3라운드 반복)
# C-1: 썸네일 추출
powershell.exe -Command "... Export(...,'JPG',1280,720) ..."

# C-2~3: 시각 비교 + 보정 (R1)
python3 ~/slide-generator-app/scripts/visual_refine.py
# → extracted_refined.json

# C-4: 재렌더링
node ~/slide-generator-app/scripts/nlm_render.js extracted_refined.json --clean ./clean/ -o output_r1.pptx
# 썸네일 추출 → R2, R3 반복...

# === Phase D ===
python3 ~/slide-generator-app/scripts/validate_pptx.py output_final.pptx
python3 -m markitdown output_final.pptx | head -100
```

## NLM 슬라이드 생성 워크플로우 (상단 파이프라인 ⓪~④ 상세)

"딸깍 자동화는 없다 — 소스 품질과 스타일 프롬프트, 두 가지를 사전에 챙겨야 한다."

> 아래 Step 1~5는 Phase A (NLM 슬라이드 생성) 구간을 상세 설명한다. Phase B~D(PDF → 편집 가능 PPTX)는 상단 "전체 파이프라인" 섹션 참조.

**역할 분담:** AI가 80%(취합·분석·요약·생성·디자인), 사람이 20%(인사이트 도출·스토리텔링·최종 검토)

### Step 1: 사용자 확인 + 소스 준비 (A/B 바구니 시스템)

사용자에게 아래 항목을 먼저 확인한다:

| 항목 | 필수 | 기본값 |
|------|------|--------|
| 주제 | Y | - |
| 목적 (보고, 제안, 교육, 소개) | Y | 보고 |
| 청중 | Y | 일반 |
| 슬라이드 수 | Y | 소스 양 기반 자동 결정 (미지정 시) |
| 스타일 선호 | N | 주제에 맞게 자동 선택 (49종 중) |

**주제만 주어진 경우** 나머지는 합리적 기본값으로 진행. 불필요한 질문으로 지연하지 않는다.

그 후 소스를 **두 바구니**로 분류하여 준비한다:

```
"혹시 참고할 자료가 있으신가요?"
  → 사업계획서, 보고서, 데이터 파일 (A바구니 — 내용 자료)
  → 참고하고 싶은 슬라이드 디자인 — PPT, PDF, 링크, 이미지 (B바구니 — 디자인 레퍼런스)
```

**바구니 A — 내용 자료 (NLM 소스로 활용)**

| 유형 | 예시 |
|------|------|
| 문서 | PDF, DOCX, TXT, 마크다운 |
| 웹 | URL (기사, 리서치, 블로그) |
| 데이터 | CSV, Excel |
| 원고 | 발표 대본, 보고서 초안 |
| 기존 슬라이드 | PDF, PPT |
| 음성/이미지 | MP3, PNG (멀티소스) |

**바구니 B — 디자인 레퍼런스 (JSON Slide Master 추출용)**

| 유형 | 예시 |
|------|------|
| 참고 슬라이드 | PPT, PDF (NLM에 업로드해 JSON 추출) |
| 참고 이미지 | Behance/Dribbble 캡처, 스크린샷 |
| 브랜드 | 컬러 코드, 브랜드 가이드라인 |

**B바구니 있을 때:** NLM에 업로드 → JSON Slide Master 추출 (아래 'JSON Slide Master 추출 가이드' 참조)
**B바구니 없을 때:** 에이전트가 주제/목적 기반으로 비주얼 디렉팅을 직접 작성한다. 50종 메뉴에서 "선택"하지 않음.

```bash
# ⚠️ create는 자동으로 컨텍스트를 전환하지 않음 — 반드시 use 필요
notebooklm create "Slides: [주제]"
notebooklm use <생성된_notebook_id>

# A바구니 — 내용 자료 업로드
notebooklm source add ./company-data.pdf
notebooklm source add "https://relevant-article.com"
# Research 자동 소싱 (실패 가능 — 실패 시 WebSearch + URL 직접 추가로 대체)
notebooklm source add-research "[주제] 최신 트렌드" --mode fast --import-all

# B바구니 — 디자인 레퍼런스 업로드 (있을 때만)
notebooklm source add ./company-template.pdf  # JSON Slide Master 추출용
```

자료가 없으면 에이전트가 소스 자동 소싱 + 스타일 직접 작성.

### Step 2: 슬라이드 가이드 생성 (메모 → 소스 전환)

채팅으로 슬라이드 구조를 먼저 텍스트로 정리한 뒤, 메모 저장 → 소스로 변환한다. 사용자가 직접 제어 가능한 항목은 **콘텐츠**(무엇을 담을지)와 **스타일**(어떻게 보일지) 두 가지다.

**소스 기반 슬라이드 장수 결정:**

사용자가 장수를 지정하지 않으면, Step 1에서 등록한 소스 양을 기준으로 자동 결정한다:

| 소스 양 | 적정 장수 | 기준 |
|---------|-----------|------|
| 짧은 소스 1-2건 | 5-7장 | 콘텐츠 부족 시 억지로 늘리면 빈약 |
| 중간 소스 3-5건 | 8-12장 | 표준 발표 분량 |
| 풍부한 소스 5건+ | 13-20장 | 밀도 있게 확장 가능 |
| 사업계획서/보고서 원본 | 15-25장 | 피칭/심사용 고밀도 |

에이전트는 소스를 NLM에 등록한 후, 소스 목록(`notebooklm source list`)의 건수와 크기를 확인하여 장수를 결정한다. 사용자가 직접 장수를 지정하면 그것을 우선한다.

**슬라이드 가이드 내용 보강:**

가이드를 생성할 때 소스의 핵심 데이터를 먼저 파악(`notebooklm ask "소스별 핵심 주제와 수치 데이터를 정리해주세요"`)한 후, 각 슬라이드에 어떤 소스의 어떤 데이터가 들어갈지 매핑하여 가이드에 포함한다. 이렇게 하면 슬라이드 생성 시 NLM이 데이터를 누락하지 않는다.

```bash
notebooklm ask "아래 조건에 맞는 슬라이드 제작 가이드를 작성해주세요.

### 슬라이드 주제
[주제] : (사용자 입력)
[슬라이드 장수] : (소스 기반 자동 결정 또는 사용자 지정)

### 작성 규칙
1. 첫 번째 슬라이드는 표지(타이틀), 마지막은 마무리(요약 또는 CTA)
2. 나머지 슬라이드는 논리적 흐름(문제 → 원인 → 해결 → 결론)에 따라 구성
3. 슬라이드 1장당 항목은 최대 3개, 초과 시 슬라이드 분리

### 출력 형식 (반드시 준수)
[슬라이드 N] 대주제 제목
* 항목 1
* 항목 2
* 항목 3" --save-as-note --note-title "+슬라이드 가이드"
```

**메모 → 소스 변환 (CLI 우선):**
```bash
# CLI로 메모 내용을 추출하여 소스로 재등록 (웹 UI 불필요)
notebooklm note get <note_id> > /tmp/slide_guide.txt
notebooklm source add /tmp/slide_guide.txt
```
또는 NLM 웹 UI에서: 메모 더보기(⋯) → '소스로 변환' 클릭. 소스 이름 앞에 `+`를 붙여 상단 정렬.

### Step 3: 맞춤형 프롬프트 5요소 구조

슬라이드 생성 시 커스텀 프롬프트에 다음 5가지를 포함하면 정교한 결과를 얻는다:

| 요소 | 설명 | 예시 |
|------|------|------|
| ① 역할 부여 (Role) | NLM이 취할 전문가 페르소나 | "10년 차 마케팅 기획자" |
| ② 배경·목적 (Context) | 업로드된 문서의 성격과 작업 목적 | "신제품 런칭 발표용" |
| ③ 핵심 지시 (Task) | 어떤 정보를 추출·가공할지 단계별 지시 | "시장 규모 → 경쟁 분석 → 전략" |
| ④ 제약 조건 (Constraints) | 소스 내 정보만 사용, 환각 방지, 쉬운 용어 | "문서에서 확인 불가 시 명시" |
| ⑤ 출력 형식 (Output) | 시각적 형태 지정 | "15장 이내, 항목 3개/장" |

**비즈니스 슬라이드 품질 극대화 규칙:**

NLM 슬라이드의 최종 목표는 **비즈니스 프레젠테이션 수준의 슬라이드**를 NLM 자체에서 완성하는 것이다. PPTX 변환이 필요하면 slide-pptx 스킬로 넘긴다.

커스텀 프롬프트의 ④ 제약 조건에 아래를 반드시 포함:

```
⛔ 장식 이미지, AI 생성 일러스트, 배경 사진 금지
✅ 다이어그램, 인포그래픽, 도형, 차트, 테이블, 아이콘만 사용
✅ 텍스트는 도형 안에 배치 (플로팅 텍스트 최소화)
✅ 데이터가 있으면 반드시 차트로 시각화 (표보다 차트 우선)
✅ 슬라이드당 핵심 메시지 1개 + 뒷받침 데이터 2-3개
```

**비즈니스 프롬프트 강화 패턴:**

```
# 프롬프트 마지막에 추가하면 비즈니스 품질 향상
- 모든 슬라이드는 컨설팅 보고서 수준의 깔끔한 레이아웃으로 생성합니다.
- 수치 데이터는 반드시 차트(bar, pie, line)로 시각화하세요. 표만으로 구성된 슬라이드는 최대 1장.
- 각 슬라이드 상단에 핵심 메시지를 한 문장으로 배치하고, 아래에 근거 데이터를 배치합니다.
- 장식 이미지 대신 다이어그램, 프로세스 플로우, 비교 매트릭스를 사용합니다.
- 색상은 절제된 기업 톤(남색, 회색, 틸)으로, 3색 이내로 유지합니다.
```

### Step 4: 노트북 구성 맞춤 설정 (품질 극대화)

NLM 채팅 > 노트북 구성 > 대화 스타일 > 맞춤 설정에 아래 프롬프트를 넣으면, **해당 노트북의 모든 응답이 이 지침을 따른다.** 슬라이드 생성 전 한 번만 설정하면 됨.

```markdown
당신은 비즈니스 프레젠테이션 전문가입니다.
- 모든 슬라이드는 컨설팅 보고서 수준의 깔끔한 레이아웃으로 생성합니다.
- 수치 데이터는 반드시 차트(bar, pie, line)로 시각화하세요.
- 각 슬라이드 상단에 핵심 메시지를 한 문장으로 배치합니다.
- 장식 이미지 대신 다이어그램, 프로세스 플로우, 비교 매트릭스를 사용합니다.
- 소스에서 확인할 수 없는 내용은 "확인 불가"로 명시합니다.
```

### Step 5: 통합 프롬프트 조합법 (★ 품질 결정 요소)

> **핵심:** 주제 설명 + 소스 참조 + 슬라이드 가이드 + 스타일 프롬프트를 **하나의 프롬프트에 합쳐서** 입력해야 최고 품질이 나온다. 분리하면 NLM이 맥락을 놓침.

```markdown
[주제] 슬라이드를 생성합니다.

[역할]: (5요소 ① — 전문가 페르소나)
[배경·목적]: (5요소 ② — 누구를 위한, 왜)

- [+슬라이드 가이드] : 해당 소스의 가이드를 참고합니다.
- [+주제 소스명] : 이 소스의 내용을 기반으로 구성합니다.

[핵심 지시]: (5요소 ③ — 단계별 지시)

[제약 조건]:
⛔ 장식 이미지, AI 생성 일러스트, 배경 사진 금지
✅ 다이어그램, 인포그래픽, 도형, 차트, 아이콘만 사용
✅ 데이터가 있으면 반드시 차트로 시각화
✅ 소스 내 정보만 사용, 확인 불가 시 명시

[출력 형식]: (5요소 ⑤ — 장수, 항목 수)

스타일: (49종 중 선택한 영문 프롬프트를 맨 마지막에 붙여넣기)
```

### Step 6: 슬라이드 생성 및 PDF 다운로드

```bash
# 슬라이드 생성 (특정 소스 지정)
notebooklm generate slide-deck "커스텀 프롬프트 내용" \
  -s <가이드_소스_id> -s <주제_소스_id> --format detailed --json

# 완료 대기 후 PDF 다운로드 (슬라이드 생성 5~15분 소요, 기본 120s 타임아웃은 부족)
notebooklm artifact wait <artifact_id> --timeout 900
# 타임아웃 시: notebooklm artifact list 로 상태 확인 후 재대기
notebooklm download slide-deck ./slides.pdf
```

> **왜 PDF?** NLM의 PPTX 직접 다운로드(`--format pptx`)도 가능하지만, 이미지/텍스트가 완전히 편집 가능하지 않다. v7 추출 파이프라인(⑥~⑧)을 거쳐야 진정한 편집 가능 PPTX가 나온다.

### Step 7: 개별 슬라이드 수정

```bash
# 특정 슬라이드 수정 (0-indexed)
notebooklm generate revise-slide "차트를 막대그래프에서 원형으로 변경" \
  --artifact <artifact_id> --slide 2 --wait

# 수정 후 전체 덱 재다운로드
notebooklm download slide-deck ./slides_revised.pptx --format pptx
```

**주의:** 슬라이드 수정 시 생성 횟수 1회 차감. 원본은 유지됨.

### 캐릭터 활용 슬라이드

캐릭터 이미지를 소스에 추가하고 스타일을 지정하면 캐릭터 기반 슬라이드 생성 가능:

```bash
notebooklm source add ./character.png
notebooklm generate slide-deck "[주제]를 알려주는 애니메이션 스타일 슬라이드를 생성합니다.
- [+슬라이드 가이드] : 해당 소스의 가이드를 참고합니다.
- [character.png] : 이미지의 캐릭터로 슬라이드를 생성하세요." \
  -s <가이드_id> -s <캐릭터_id>
```

**기업 캐릭터 가이드북 (2D → 3D 마스코트 변환):**

2D 캐릭터를 Pixar/C4D 스타일 3D 마스코트로 변환하여 캐릭터 가이드북을 제작할 수 있다:

```bash
notebooklm source add ./company-character.png
notebooklm generate slide-deck "첨부된 [company-character.png] 2D 캐릭터를 기반으로 고품질 3D 마스코트 캐릭터의 캐릭터 가이드북을 제작합니다.
[스타일 및 재질]: 귀여운 캐릭터, 3D 렌더링 스타일, 전체적으로 따뜻하고 친근한 느낌의 Pixar 스타일이나 C4D 렌더링 느낌을 적용합니다.

[핵심 원칙]: 모든 슬라이드에서 기존 캐릭터의 외형을 절대적으로 보존하고 유지합니다.
- 얼굴: 원본과 동일한 얼굴형, 눈 크기/모양/색상, 코, 입, 표정 스타일
- 헤어: 원본과 동일한 헤어스타일, 머리카락 색상, 길이, 방향
- 의상: 원본과 동일한 옷 디자인, 색상, 패턴, 액세서리
- 체형: 원본과 동일한 머리-몸 비율(등신), 체형, 키 비율
- 색상 팔레트: 원본에 사용된 모든 색상 코드를 정확히 유지
※ 원본에 없는 요소를 추가하거나, 있는 요소를 생략하지 않습니다.

[조명 및 배경]: 부드러운 스튜디오 조명, 깨끗한 단색 화이트 배경
[출력]: 총 5개의 서로 다른 포즈를 각 슬라이드에 한 장씩 담아서 생성합니다." \
  -s <캐릭터_id>
```

### 사진 안내문 슬라이드

스크린샷 이미지를 소스에 추가하면 단계별 안내문 슬라이드를 자동 생성할 수 있다. 시니어·초보자 대상 매뉴얼에 유용:

```bash
# 단계별 스크린샷 이미지를 소스에 추가
notebooklm source add ./step1.png
notebooklm source add ./step2.png
notebooklm source add ./step3.png

notebooklm generate slide-deck "각 번호의 png 이미지를 사용해서, 아래 순서에 따라 [서비스명의 이용 절차]를 설명하는 사용자 안내 슬라이드를 생성하세요.
- 디지털 기기에 익숙하지 않은 어르신(시니어) 대상 자료입니다. 전문 용어나 외래어 사용을 최소화하고, 일상에서 쓰는 쉬운 단어로 설명합니다.
- 각 슬라이드에는 해당 단계의 실제 사진을 배치하고 사용자가 수행해야 할 동작을 간결하게 안내합니다.
- 각 단계에서 눌러야 할 버튼이나 선택해야 할 항목은 빨간 동그라미 또는 화살표로 강조합니다." \
  -s <step1_id> -s <step2_id> -s <step3_id>
```

**활용 예시:** 스터디카페 이용권 구매 절차, 쿠팡 와우 해지 절차, 앱 설치 가이드 등

## 스타일 가이드 레퍼런스

### NLM 내장 슬라이드 스타일

| 스타일 | 용도 | 추천 상황 |
|--------|------|-----------|
| `detailed` | 본문 중심, 텍스트 풍부 | 보고서형 발표, 상세 자료 배포 |
| `presenter` | 키워드 중심, 여백 활용 | 발표자 노트와 함께 사용 |

### NLM 인포그래픽/비디오 스타일 (시각 레퍼런스용)

슬라이드 커스텀 프롬프트에서 시각 스타일을 기술할 때 다음을 참조:

**비즈니스 추천 TOP 5:**

| 순위 | 스타일 | 특징 | 적합한 상황 |
|------|--------|------|-------------|
| 1 | `professional` | 깔끔한 레이아웃, 데이터 시각화 | 사업 제안서, 경영 보고 |
| 2 | `editorial` | 매거진풍, 타이포그래피 강조 | 브랜드 프레젠테이션, 마케팅 |
| 3 | `bento-grid` | 격자 카드 배치, 모던 | 제품 소개, 포트폴리오 |
| 4 | `scientific` | 학술 논문풍, 정밀한 도표 | 연구 발표, 기술 보고 |
| 5 | `retro-print` | 빈티지 인쇄풍 | 브랜드 스토리, 역사 소개 |

**교육 추천 TOP 5:**

| 순위 | 스타일 | 특징 | 적합한 상황 |
|------|--------|------|-------------|
| 1 | `sketch-note` | 손그림풍, 친근한 느낌 | 강의 자료, 워크숍 |
| 2 | `instructional` | 단계별 안내, 명확한 구조 | 매뉴얼, 튜토리얼 |
| 3 | `kawaii` | 귀여운 캐릭터, 파스텔톤 | 초등교육, 시니어 안내 |
| 4 | `anime` | 일본 애니메이션풍 | 청소년 대상, 창의 수업 |
| 5 | `whiteboard` | 화이트보드 스케치풍 | 브레인스토밍, 개념 설명 |

**스타일을 커스텀 프롬프트에 적용하는 방법:**
```
[주제] 발표 슬라이드를 생성합니다.
- 전체적으로 professional 스타일의 깔끔한 레이아웃을 적용합니다.
- 데이터가 포함된 슬라이드는 차트와 표를 활용합니다.
- 색상 톤: 남색(#1B2D6E) 기반, 배경은 순백(#FFFFFF)
```

> **⚠️ HEX 색상 vs 스타일 키워드 우선순위:**
> NLM 슬라이드 생성에서 HEX 색상 코드(예: `#1B2D6E`)는 **참고용**일 뿐, NLM이 정확히 해당 색상을 재현하지 않는다. NLM은 텍스트 기반 프롬프트를 해석하여 자체적으로 색상을 결정한다. 따라서 **스타일 키워드**(예: `professional`, `dark navy tone`, `warm pastel`)가 실제 결과에 더 큰 영향을 미친다.
> - HEX 코드: 의도를 전달하는 참고값 (정확히 반영되지 않음)
> - 스타일 키워드: NLM이 실제로 해석하는 주요 입력 (우선)
> - JSON Slide Master의 `color_palette`: PDF 시각 소스와 함께 사용할 때만 효과적

## 49종 스타일 키워드 레퍼런스

슬라이드 생성 시 커스텀 프롬프트 마지막에 영문 스타일 프롬프트를 붙여넣으면 해당 스타일로 생성된다.
에이전트는 주제/목적에 맞는 스타일을 자동 판단하되, 사용자가 특정 스타일을 요청하면 해당 프롬프트를 사용한다.

### 비즈니스 TOP 10

| # | 스타일 | 영문 프롬프트 | 추천 시나리오 |
|---|--------|--------------|-------------|
| 33 | 프리미엄 컨설팅 | `Consulting deck visual, premium business slide aesthetic, clean layouts, subtle corporate color palette, sharp icons, minimal data elements, strategy presentation style, polished and executive-friendly --ar 16:9` | 투자 발표, 경영 전략, 컨설팅 보고 |
| 2 | 비즈니스 미니멀 | `Minimalist timeline infographic, simple flat vector art, clean data visualization, geometric shapes, corporate color palette, white background, highly legible --ar 16:9` | 타임라인, 프로젝트 현황, 분기 보고 |
| 1 | 벤토 그리드 | `Bento grid UI layout, tech minimalist design, clean web interface, soft lighting, modern corporate aesthetic, vector flat style, UI/UX --ar 16:9` | 제품 소개, 포트폴리오, SaaS 랜딩 |
| 27 | SaaS 대시보드 | `SaaS dashboard infographic, clean enterprise UI, cards and charts, modern workplace software aesthetic, white and blue corporate palette, minimal interface, high clarity, presentation-ready, vector UI illustration --ar 16:9` | 매출 대시보드, KPI 보고, SaaS 소개 |
| 23 | 뉴스레터 에디토리얼 | `Magazine editorial layout, modern business newsletter, elegant serif typography, two-column grid, muted earth tone palette, professional photography style --ar 16:9` | 뉴스레터, 사내 매거진, 브랜드 소식 |
| 32 | 데이터 스토리텔링 | `Data storytelling poster, one key metric highlighted, clean chart-driven composition, modern corporate poster design, bold typography, minimal geometric elements, presentation-friendly --ar 16:9` | 광고 포스터, 핵심 지표 강조, 캠페인 |
| 28 | Before/After 비교 | `Before and after comparison card layout, split screen infographic, clean corporate design, organized workflow transformation, minimal icons, white background, highly legible, business presentation style --ar 16:9` | 도입 전후 비교, 서비스 개선 사례 |
| 18 | 플랫 코퍼레이트 | `Corporate flat illustration, Alegria style, modern tech startup blog art, simplified vector characters working in office, minimal background, bright professional colors --ar 16:9` | 회사 소개, 채용 발표, 문화 소개 |
| 25 | 그라디언트 모던 | `Abstract gradient background, modern corporate cover design, smooth color transitions, geometric light effects, premium minimalist aesthetic, clean title space --ar 16:9` | 표지 슬라이드, 이벤트 배너, 브랜딩 |
| 48 | 스위스 그리드 | `Swiss grid editorial design, ultra-clean modular layout, structured typography, asymmetric grid, modernist corporate poster, restrained color palette, highly legible, presentation-ready --ar 16:9` | 연간 보고서, 정보 밀도 높은 발표 |

### 교육 TOP 5

| # | 스타일 | 영문 프롬프트 | 추천 시나리오 |
|---|--------|--------------|-------------|
| 3 | 칠판 | `Chalkboard sketch, educational diagram, white chalk on dark green board, hand-drawn aesthetic, arrows and mind maps, friendly and approachable tone` | 개념 설명, 수업 자료, 학습 정리 |
| 24 | 스케치노트 | `Sketchnote visual summary, hand-drawn icons and typography, black ink with color highlights, clean white background, educational mind map, conference note style --ar 16:9` | 강의 요약, 컨퍼런스 노트, 워크숍 |
| 38 | 핸드드로잉 필기 | `Hand-drawn notebook journal page, lined paper texture, ballpoint pen sketches and handwritten notes, casual margin doodles, highlighted key points, warm personal study aesthetic, authentic and relatable --ar 16:9` | 개인 학습, 독서 정리, 스터디 |
| 41 | 스텝 바이 스텝 | `Step-by-step instruction manual, IKEA assembly guide aesthetic, numbered sequential diagrams, simple line icons with color highlights, clean white background, universal pictogram style, highly functional and legible --ar 16:9` | 사용법 안내, 설치 가이드, 조립 설명서 |
| 29 | 화이트보드 전략 | `Whiteboard strategy meeting illustration, office team planning around a board, sticky notes and diagrams, modern business environment, clean semi-flat illustration, collaborative and intelligent tone --ar 16:9` | 브레인스토밍, 전략 회의, 아이디어 정리 |

### 크리에이티브 TOP 5

| # | 스타일 | 영문 프롬프트 | 추천 시나리오 |
|---|--------|--------------|-------------|
| 7 | 네온/사이버 펑크 | `Neon noir technological scene, cyberpunk aesthetic, dark background with glowing neon accents, glowing data streams, highly detailed, futuristic` | 게임 소개, 테크 이벤트, SF 콘텐츠 |
| 10 | 클레이 애니메이션 | `Claymation style, tactile 3D illustration, cute office worker figurine, soft smooth lighting, playful stop-motion aesthetic, vibrant pastel colors` | 어린이 교육, 제품 소개, 브랜드 스토리 |
| 4 | 일본 만화책 | `Manga instructional comic panel, clean line art, monochrome with screentones, informative speech bubbles, office worker character, tutorial style, expressive` | 스토리텔링, 절차 설명, 청소년 교육 |
| 12 | 카와이/파스텔 | `Kawaii illustration, girly pastel colors, soft and fluffy aesthetic, cute minimalist characters, warm lighting, dreamlike` | 초등교육, 시니어 안내, 소셜 카드 |
| 20 | 페이퍼 컷아웃 | `Layered paper cutout art, conceptual office desk, soft shadows, pastel colored paper, clean and minimal storytelling, tactile texture --ar 16:9` | 핸드메이드 브랜드, 감성 마케팅, 문화 소개 |

### 테크/모던 TOP 5

| # | 스타일 | 영문 프롬프트 | 추천 시나리오 |
|---|--------|--------------|-------------|
| 5 | 뉴 모피즘 | `Neumorphic tech schematic, soft UI, drop shadows, subtle gradients, clean tech blueprint, modern app interface, minimalist 3D layout` | 앱 소개, 테크 스타트업, UI/UX 발표 |
| 19 | 글래스 모피즘 3D | `3D glassmorphism icons, frosted glass UI elements, modern tech aesthetic, soft studio lighting, clean white background, high-end corporate presentation style` | AI/SaaS 제품, 프리미엄 테크, 미래 기술 |
| 43 | 모던 다크 모드 | `Sleek dark mode UI presentation background, subtle glowing gradients, deep black and dark gray palette, modern minimalist tech aesthetic, elegant and premium corporate style, clean negative space --ar 16:9` | 개발자 발표, 테크 컨퍼런스, 프리미엄 IT |
| 44 | 디지털 마인드맵 | `Abstract digital node network, glowing connecting lines and dots, clean data visualization concept, mind map aesthetic, modern deep tech background, soft glowing lights --ar 16:9` | 기술 아키텍처, 네트워크 구조, 데이터 시각화 |
| 42 | 3D 아이소메트릭 | `3D isometric illustration, modern corporate workflow, clean office environment, soft clay render style, pastel and white color palette, highly detailed, soft studio lighting, tech business concept --ar 16:9` | 워크플로우 설명, 프로세스 소개, 비즈니스 구조 |

### 레트로/아트 TOP 5

| # | 스타일 | 영문 프롬프트 | 추천 시나리오 |
|---|--------|--------------|-------------|
| 13 | 레트로 팝 | `Retro pop art, playful aesthetic, 1980s Memphis design, bold outlines, vibrant flat colors, dynamic composition, energetic` | 이벤트 홍보, 세일 광고, 경쾌한 소개 |
| 14 | 빈티지 액션 코믹스 | `Vintage action comic panel, 1960s comic book style, halftone dot textures, dramatic angles, bold typography, retro coloring` | 마케팅 캠페인, 스토리 기반 발표 |
| 6 | 바우하우스 | `Bauhaus aesthetic, geometric abstraction, primary colors (red, blue, yellow), strict grid, modern minimalist poster, clean typography layout` | 디자인 발표, 건축, 현대미술 |
| 17 | 로코코 | `Elegant Rococo style, romantic ornate aesthetic, soft pastel oil painting, intricate gold floral details, vintage luxury` | 럭셔리 브랜드, 뷰티, 웨딩 |
| 46 | 폴라로이드 무드보드 | `Polaroid scrapbook layout on a wooden desk, aesthetic moodboard, sticky notes, scattered paper clips, candid team moments, warm soft lighting, nostalgic yet professional editorial style --ar 16:9` | 팀 소개, 회고록, 감성 마케팅 |

### 기타 (19종)

| # | 스타일 | 영문 프롬프트 | 추천 시나리오 |
|---|--------|--------------|-------------|
| 8 | 도스 터미널 | `Retro CRT monitor screen, Matrix green text on black background, glowing phosphor, terminal code, vintage hacker aesthetic, scanlines` | 해커톤, 보안 발표, 개발자 밋업 |
| 9 | 복셀 3D | `Isometric voxel art, gamified office environment, highly detailed blocks, bright lighting, colorful pixel 3D, cute architectural diagram --ar 16:9` | 게이미피케이션, 메타버스, 교육 게임 |
| 11 | 식물학/과학 일러스트 | `Botanical scientific illustration, vintage field guide style, delicate line work, watercolor shading, highly detailed and precise` | 자연과학, 의학, 학술 자료 |
| 15 | 레트로 코믹 블루프린트 | `Retro-comic action blueprint, technical schematic drawing mixed with vintage comic art, blue and white colors, dynamic mechanical details` | 기술 해설, 제조업, 엔지니어링 |
| 16 | 하이 옥탄 애니메이션 | `High-octane anime style, intense dynamic action, speed lines, high energy, dramatic lighting, vivid colors, epic perspective` | 게임 홍보, 스포츠, 청소년 콘텐츠 |
| 21 | 플랫 벡터 모션그래픽 | `Flat vector illustration, science channel aesthetic, vibrant deep space colors, clean minimalist background, educational infographic, highly detailed yet simplified --ar 16:9` | 과학 교육, 유튜브 커버, 다큐멘터리 |
| 22 | 시네마틱 우주 SF | `Cinematic 3D render of a space station orbiting a gas giant, hard sci-fi aesthetic, hyper-realistic, dramatic lighting, volumetric scattering, 8k resolution, space documentary style --ar 16:9` | SF 다큐, 우주 기술, 과학 강연 |
| 26 | 도트 픽셀 아트 2D | `16-bit retro pixel art, 2D side-scrolling game scene, office worker character, bright saturated colors, nostalgic game UI elements, clean pixel grid --ar 16:9` | 레트로 게임, 이벤트 초대, 팬 콘텐츠 |
| 30 | 카드 뉴스형 | `Card news style explainer, modular information blocks, bold headings, clean Korean social media editorial aesthetic, minimal icons, bright background, business-friendly visual summary --ar 16:9` | SNS 카드 뉴스, 정보 요약, 사내 공지 |
| 31 | 서류/리서치 데스크 | `Research desk visualization, laptop with multiple documents and notes, clean analytical workspace, modern office desk, papers, charts and highlights, soft daylight, realistic editorial illustration --ar 16:9` | 리서치 보고, 데스크 리서치, 분석 발표 |
| 34 | 협업툴 메시지형 | `Collaboration app scene, modern team messaging and document sharing interface, office productivity software aesthetic, clean floating windows, minimal UI, bright professional environment --ar 16:9` | SaaS 소개, 협업 프로세스, 팀 워크플로우 |
| 35 | 포스트잇 문제 해결 | `Sticky note problem solving map, colorful structured note clusters, clean workshop board, office ideation process, modern facilitation aesthetic, highly legible, visual thinking style --ar 16:9` | 디자인 씽킹, 문제 해결 워크숍, 회고 |
| 36 | 미니멀 라인 아트 | `Minimalist line art diagram, simple continuous black lines on off-white background, step-by-step process, clean UI/UX elements, highly legible, professional and elegant` | 프로세스 다이어그램, UX 설명, 심플 가이드 |
| 37 | 프리미엄 스톡 사진 | `Candid photography of a diverse corporate team reviewing a document together in a bright modern boardroom, authentic expression, shot on 35mm lens, shallow depth of field, soft natural lighting --ar 16:9` | 회사 소개서, IR 자료, 브랜드 신뢰 |
| 39 | 아이소메트릭 인포그래픽 | `Isometric flat vector infographic, clean technical illustration, modern office workflow, soft gradient colors, organized layered structure, white background, professional and highly legible --ar 16:9` | 조직 구조, 프로세스 맵, 인프라 설명 |
| 40 | 듀오톤 그래픽 | `Duotone graphic design, two-tone color overlay on photography, bold modern contrast, Spotify cover art aesthetic, striking visual impact, clean composition, contemporary editorial style --ar 16:9` | 음악/문화 이벤트, 소셜 배너, 모던 브랜딩 |
| 45 | 볼드 타이포그래피 | `Bold typography poster design, Swiss style layout, massive clean sans-serif text layout, high contrast minimal colors, modern graphic design aesthetic, strong visual impact --ar 16:9` | 키 메시지 강조, 이벤트 포스터, 모토 발표 |
| 47 | 디지털 태블릿 다이어리 | `Digital planner interface, iPad GoodNotes aesthetic, pastel highlighters, digital handwriting, habit tracker layout, cozy personal productivity workspace, clean minimal design --ar 16:9` | 생산성 앱 소개, 개인 정리, 다이어리 |
| 49 | 포털형 카드 매거진 | `Portal-style card magazine layout, clean Korean editorial web design, modular content cards, bold headlines, soft neutral palette, user-friendly information hierarchy, modern media aesthetic --ar 16:9` | 미디어 소개, 뉴스 큐레이션, 콘텐츠 허브 |

### 스타일 선택 가이드 (비즈니스 슬라이드 기준)

49종 중 **비즈니스 문서에 적합한 스타일**과 **피해야 할 스타일**을 구분한다:

| 등급 | 스타일 | 이유 |
|------|--------|------|
| **S (최적)** | #33 프리미엄 컨설팅, #27 SaaS 대시보드, #48 스위스 그리드 | 구조적 레이아웃, 데이터 시각화 중심, 깔끔 |
| **A (추천)** | #2 비즈니스 미니멀, #1 벤토 그리드, #28 Before/After, #32 데이터 스토리텔링 | 정보 전달에 효과적, 비주얼 과하지 않음 |
| **B (상황별)** | #23 뉴스레터, #30 카드 뉴스, #36 미니멀 라인 아트, #39 아이소메트릭 | 특정 주제에 잘 맞으나 범용성 낮음 |
| **C (비즈니스 부적합)** | #7 네온, #10 클레이, #12 카와이, #16 하이옥탄, #22 우주SF | 이미지 중심 → 비즈니스 문서 부적합, 캐릭터/교육용으로만 |

**에이전트 자동 선택 규칙:** 사용자가 스타일을 지정하지 않으면, 목적에 따라 S/A 등급에서 자동 선택한다. C 등급은 사용자가 명시적으로 요청한 경우에만 사용.

### 스타일 프롬프트 적용 방법

```bash
notebooklm generate slide-deck "[주제] 슬라이드를 생성합니다.
[슬라이드 가이드 내용]
스타일: [위 표에서 선택한 영문 프롬프트]" \
  -s <가이드_소스_id> -s <내용_소스_id> --format detailed --json
```

---

## JSON Slide Master 추출 가이드

회사 PPT 디자인을 NLM 슬라이드에 재현하는 워크플로우. **핵심: PDF 소스 = 시각적 레퍼런스("이렇게 생긴 걸 만들어라"), JSON = 구조적 규칙("이 규칙을 지켜라"). 둘 다 있어야 원본에 가까운 결과가 나온다.**

### 1단계: 회사 PPT를 소스로 등록

```bash
# 회사 PPT를 PDF로 변환 후 업로드 (NLM은 PDF 소스 지원)
notebooklm source add ./company-template.pdf
# 주제 관련 소스도 추가
notebooklm source add ./project-data.pdf
```

### 2단계: JSON Slide Master 추출 (채팅)

회사 PPT 소스를 지정하여 JSON 구조를 추출한다:

```bash
notebooklm ask "### 요청사항
첨부한 프레젠테이션 슬라이드를 분석하여, 모든 슬라이드에 공통으로 적용되는 슬라이드 마스터(전체 틀) 정보를 JSON으로 정리합니다. 개별 슬라이드의 콘텐츠 배치가 아닌, PPT 슬라이드 마스터처럼 전체 슬라이드에 일관되게 적용되는 프레임만 추출합니다. 특정 슬라이드에서만 나타나는 요소는 제외하고, 전체에 반복되는 공통 틀만 정리합니다.

### 다음 항목을 포함
- slide_size: 슬라이드 비율
- color_palette: 전체 컬러 체계 (primary, secondary, accent, background, text_primary, text_secondary)
- header: 상단 영역의 구성 (좌측 텍스트, 우측 텍스트, 하단 구분선 등)
- footer: 하단 영역의 구성 (배경색, 텍스트 배치, 구분자 등)
- decorative_elements: 반복되는 장식 요소들 (꺾쇠, 도트 패턴, 반원 등의 위치, 크기, 색상)

### 출력 JSON 구조
json{
\"slide_master\": {
\"slide_size\": { \"aspect_ratio\": \"\" },
\"color_palette\": {},
\"header\": { \"position\": \"\", \"height\": \"\", \"elements\": [] },
\"footer\": { \"position\": \"\", \"height\": \"\", \"elements\": [] },
\"decorative_elements\": []
}
}" -s <template_source_id> --json
```

**추출된 JSON 예시 구조:**
```json
{
  "slide_master": {
    "slide_size": { "aspect_ratio": "16:9" },
    "color_palette": {
      "primary": "#1B2D6E",
      "secondary": "#E8EAF0",
      "accent": "#4A5899",
      "background": "#FFFFFF",
      "text_primary": "#1B2D6E",
      "text_secondary": "#FFFFFF"
    },
    "header": { "position": "top", "height": "8%", "elements": [...] },
    "footer": { "position": "bottom", "height": "6%", "elements": [...] },
    "decorative_elements": [...]
  }
}
```

### 3단계: JSON + 시각 소스로 슬라이드 생성

추출한 JSON을 커스텀 프롬프트에 포함하고, 반드시 템플릿 PDF 소스를 함께 선택:

```bash
notebooklm generate slide-deck "[주제] 슬라이드를 생성합니다.
[대상/톤] 설명
- [+템플릿 PDF 소스명] : 이 소스의 디자인을 시각적으로 참조하여 동일한 스타일로 제작합니다.
- [+주제 소스명] : 이 소스의 내용을 기반으로 슬라이드 콘텐츠를 구성합니다.
아래 JSON 구조와 시각적 스타일 가이드를 엄격히 준수하여 모든 슬라이드에 동일한 헤더, 장식 요소, 컬러 체계를 적용합니다.

# 시각적 스타일 가이드
- 배경은 반드시 순수 흰색(#FFFFFF)
- 모든 텍스트와 강조 요소는 (primary 색상)
- 헤더/푸터/장식 요소 배치 규칙 기술...

# 절대 하지 말 것
- 배경에 색상이나 그라데이션 넣지 말 것
- 장식 요소를 빠뜨리지 말 것
- 헤더 구분선을 생략하지 말 것

# 슬라이드 마스터 JSON
(추출한 JSON 붙여넣기)" \
  -s <template_source_id> -s <content_source_id> --format detailed --json
```

**JSON만 넣고 PDF 소스를 빼면** 장식 요소를 시각적으로 재현하지 못한다. 반드시 PDF 소스 + JSON 구조를 함께 사용할 것.

## NLM 슬라이드 PDF → 편집 가능한 PPTX (Phase B~D 상세)

상단 "전체 파이프라인" Phase B~D의 상세 설명. **이 스킬 내에서 완결되며, 다른 스킬 전환 불필요.**

### Phase B: 추출 + 인페인팅 + 1차 렌더링

1. `nlm_extract.py` — PDF → 이미지 변환 → Gemini Vision이 각 페이지의 텍스트/역할/좌표/차트/테이블을 추출 → JSON 출력
2. `nlm_inpaint.py` — Gemini 이미지 모델(`gemini-3.1-flash-image-preview`)로 5패스 텍스트 제거 → 클린 배경 PNG + LANCZOS 업스케일
3. `nlm_render.js` — PptxGenJS로 클린 배경 이미지(전체 슬라이드) + 흰색 마스크 + 텍스트 오버레이 → 편집 가능 PPTX

### Phase C: 시각 비교 피드백 루프

`nlm_visual_refine.py` — 원본 PDF PNG와 렌더된 JPG를 Gemini 2.5 Flash에 전달. Gemini가 텍스트별 위치 오차(Δx%, Δy%)를 JSON으로 반환. 이 delta를 extracted.json 좌표에 누적 반영 후 재렌더링. **3라운드 반복으로 critical 0 수렴까지.**

### Phase D: 최종 QA

`validate_pptx.py` + `markitdown` + PowerShell COM JPG 추출로 구조/콘텐츠/시각 검증.

## 소스 품질 체크리스트

슬라이드 품질은 소스 품질에 비례한다. 생성 전에 반드시 소스를 정제한다.

### 1단계: 소스 종합 평가

NLM 채팅에서 다음 프롬프트로 소스를 평가한다:

```bash
notebooklm ask "업로드된 각 소스를 아래 기준으로 평가해 표로 정리합니다.

### 소스 종합 평가표
| 소스명 | 핵심 요약 | 발행일 | 저자명/소속 | 소스 구분 | 신뢰도 | 참고가치 점수 |

### 작성기준
- 핵심요약 : 30자 이내, 한줄로 작성
- 소스 구분: 1차 자료(원자료·공식 발표·직접 연구) / 2차 분석(해설·요약·분석) / 의견·칼럼
- 신뢰도: ★★★☆☆ 형식 (5점: 공신력 있는 자료 ~ 1점: 출처 불명확·주관적)
- 참고가치: 1~10점 (10점: 핵심 근거로 직접 인용 가능 ~ 1점: 참고 가치 낮음)"
```

**평가 후 조치:**
- 신뢰도 ★★☆☆☆ 이하 → `notebooklm source delete <id>` 로 제거
- 3차 자료(의견·칼럼) → 핵심 근거로 사용하지 말고, 보조 참고만
- Research 기능으로 양질의 소스 보충: `notebooklm source add-research "query" --mode fast --import-all`

### 2단계: 주제별 대표 소스 선정

```bash
notebooklm ask "이 노트북에 포함된 모든 소스를 면밀히 검토하여, 가장 비중있게 다뤄진 주제·관점 5가지를 선정하세요.
각 주제별로 가장 풍부하게 다룬 소스 1개를 선정해 아래 표로 정리하세요.

### 주제별 대표 소스
| 순위 | 핵심 주제 / 주요 관점 | 대표 소스 | 선정 근거 |

### 작성기준
- 순위는 소스 전체에서의 언급 빈도와 서술 비중을 기준으로 매깁니다.
- 선정 근거는 해당 소스의 표현·논조·주장 방식을 직접 근거로 작성하세요.
- 외부 지식과 개인적 해석은 포함하지 마세요.
- 소스에서 확인되지 않는 내용은 \"명시되지 않음\"으로 표기하세요."
```

### 소스 정렬 팁

소스 이름 앞에 접두어를 붙여 우선순위를 관리한다:
- `!1 핵심소스명` — 가장 중요한 소스 (맨 위 정렬)
- `!2 보조소스명` — 차순위 소스
- `+슬라이드 가이드` — 가이드 소스 구분

CLI에서 소스 이름 변경은 웹 UI를 사용한다. 이렇게 정리하면 특정 소스만 `-s` 플래그로 선택하여 생성할 때 편리하다.

## 활용 사례 (6가지 실전 예제)

### 사례 1: 슬라이드 가이드 메모 → 소스 전환

채팅으로 슬라이드 구조를 텍스트로 정리 → 메모 저장 → 소스로 변환하여 슬라이드 생성에 활용.

```bash
# 1. 슬라이드 가이드 생성 + 메모 저장
notebooklm ask "아래 조건에 맞는 슬라이드 제작 가이드를 작성해주세요.

### 슬라이드 주제
[주제] : (사용자 입력)
[슬라이드 장수] : 7장

### 작성 규칙
1. 첫 번째 슬라이드는 표지(타이틀), 마지막은 마무리(요약 또는 CTA)
2. 나머지 슬라이드는 논리적 흐름(문제 → 원인 → 해결 → 결론)에 따라 구성
3. 슬라이드 1장당 항목은 최대 3개, 초과 시 슬라이드 분리

### 출력 형식 (반드시 준수)
[슬라이드 N] 대주제 제목
* 항목 1
* 항목 2
* 항목 3" --save-as-note --note-title "+슬라이드 가이드"

# 2. NLM 웹 UI에서 메모 더보기(⋯) → '소스로 변환' 클릭
# 3. 슬라이드 생성 시 가이드 소스를 -s 플래그로 지정
notebooklm generate slide-deck "프롬프트" -s <가이드_소스_id> --format detailed --json
```

### 사례 2: 캐릭터 활용 슬라이드 (Manga 스타일)

캐릭터 이미지를 소스에 추가하고 스타일을 지정하면 캐릭터 기반 슬라이드 생성 가능. 저작권 주의.

```bash
# 캐릭터 이미지 + 슬라이드 가이드 소스 추가
notebooklm source add ./character.png

# 프롬프트 예시
notebooklm generate slide-deck "[주제]를 알려주는 일본 애니메이션 Manga 스타일 슬라이드를 생성합니다.
- [+슬라이드 가이드] : 해당 소스의 가이드를 참고합니다.
- [character.png] : 이미지의 캐릭터로 슬라이드를 생성하세요." \
  -s <가이드_id> -s <캐릭터_id> --json
```

### 사례 3: 사진 → 안내문 슬라이드 (시니어 대상)

스크린샷 이미지를 소스에 추가하면 단계별 안내문 슬라이드 자동 생성. 시니어·초보자 대상 매뉴얼에 유용.

```bash
# 단계별 스크린샷 소스 추가
notebooklm source add ./step1.png
notebooklm source add ./step2.png
notebooklm source add ./step3.png

# 프롬프트 예시
notebooklm generate slide-deck "각 번호의 png 이미지를 사용해서, 아래 순서에 따라 [서비스명의 이용 절차]를 설명하는 사용자 안내 슬라이드를 생성하세요.
- 디지털 기기에 익숙하지 않은 어르신(시니어) 대상 자료입니다. 전문 용어나 외래어 사용을 최소화하고, 일상에서 쓰는 쉬운 단어로 설명합니다.
- 각 슬라이드에는 해당 단계의 실제 사진을 배치하고 사용자가 수행해야 할 동작을 간결하게 안내합니다.
- 각 단계에서 눌러야 할 버튼이나 선택해야 할 항목은 빨간 동그라미 또는 화살표로 강조합니다." \
  -s <step1_id> -s <step2_id> -s <step3_id> --json
```

**활용 예시:** 스터디카페 이용권 구매, 쿠팡 와우 해지, 앱 설치 가이드

### 사례 4: 멀티소스 슬라이드 (음성 + 이미지)

음성 파일(MP3) + 캐릭터 이미지를 조합하여 슬라이드 자동 생성.

```bash
# 음성 + 이미지 소스 추가
notebooklm source add ./lecture.mp3
notebooklm source add ./character.png

# 가이드 먼저 생성
notebooklm ask "아래 조건에 맞는 슬라이드 제작 가이드를 작성해주세요.
### 슬라이드 주제
[주제] : (음성 내용 기반)
[슬라이드 장수] : 7장
### 출력 형식
[슬라이드 N] 대주제 제목
* 항목 1
* 항목 2" --save-as-note --note-title "+슬라이드 가이드"

# 슬라이드 생성 (음성 + 캐릭터 + 가이드 소스 지정)
notebooklm generate slide-deck "[주제] 슬라이드 생성
- [+슬라이드 가이드] 참고
- [character.png] 캐릭터 활용" \
  -s <가이드_id> -s <음성_id> -s <캐릭터_id> --json
```

### 사례 5: 회사 템플릿 PPT (JSON Slide Master)

회사 PPT 디자인을 NLM 슬라이드에 재현. B바구니 핵심 활용법.

```bash
# 1. 회사 PPT(PDF) + 주제 소스 추가
notebooklm source add ./company-template.pdf
notebooklm source add ./project-data.pdf

# 2. JSON Slide Master 추출
notebooklm ask "### 요청사항
첨부한 프레젠테이션 슬라이드를 분석하여, 모든 슬라이드에 공통으로 적용되는 슬라이드 마스터(전체 틀) 정보를 JSON으로 정리합니다.
### 다음 항목을 포함
- slide_size, color_palette, header, footer, decorative_elements
### 출력 JSON 구조
json{ \"slide_master\": { \"slide_size\": {}, \"color_palette\": {}, \"header\": {}, \"footer\": {}, \"decorative_elements\": [] } }" \
  -s <template_source_id> --json

# 3. JSON + 시각 소스로 슬라이드 생성
notebooklm generate slide-deck "[주제] 슬라이드를 생성합니다.
- [+템플릿 PDF 소스명] : 이 소스의 디자인을 시각적으로 참조
- [+주제 소스명] : 이 소스의 내용을 기반으로 구성
아래 JSON 구조를 엄격히 준수하여 동일한 헤더, 장식 요소, 컬러 체계를 적용합니다.

# 슬라이드 마스터 JSON
(추출한 JSON 붙여넣기)" \
  -s <template_id> -s <content_id> --format detailed --json
```

**핵심:** PDF 소스(시각 레퍼런스) + JSON(구조 규칙) 둘 다 있어야 원본에 가까운 결과.

### 사례 6: 3D 마스코트 캐릭터 가이드북

2D 캐릭터를 Pixar/C4D 스타일 3D 마스코트로 변환하여 캐릭터 가이드북 제작.

```bash
# 2D 캐릭터 이미지 소스 추가
notebooklm source add ./company-character.png

# 프롬프트 예시
notebooklm generate slide-deck "첨부된 [company-character.png] 2D 캐릭터를 기반으로 고품질 3D 마스코트 캐릭터의 캐릭터 가이드북을 제작합니다.
[스타일 및 재질]: 귀여운 캐릭터, 3D 렌더링 스타일, 전체적으로 따뜻하고 친근한 느낌의 Pixar 스타일이나 C4D 렌더링 느낌을 적용합니다.

[핵심 원칙]: 모든 슬라이드에서 기존 캐릭터의 외형을 절대적으로 보존하고 유지합니다.
- 얼굴: 원본과 동일한 얼굴형, 눈 크기/모양/색상, 코, 입, 표정 스타일
- 헤어: 원본과 동일한 헤어스타일, 머리카락 색상, 길이, 방향
- 의상: 원본과 동일한 옷 디자인, 색상, 패턴, 액세서리
- 체형: 원본과 동일한 머리-몸 비율(등신), 체형, 키 비율
- 색상 팔레트: 원본에 사용된 모든 색상 코드를 정확히 유지
※ 원본에 없는 요소를 추가하거나, 있는 요소를 생략하지 않습니다.

[조명 및 배경]: 부드러운 스튜디오 조명, 깨끗한 단색 화이트 배경
[출력]: 총 5개의 서로 다른 포즈를 각 슬라이드에 한 장씩 담아서 생성합니다." \
  -s <캐릭터_id> --json
```

