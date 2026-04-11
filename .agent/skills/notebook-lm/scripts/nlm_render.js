#!/usr/bin/env node
/**
 * render_nlm_v9.js — Nano Banana Pro 클린 배경 + 텍스트 오버레이 렌더러
 *
 * 워크플로우:
 *   1. remove_text_v9.py → slide_NN_clean.png (텍스트 제거 클린 배경)
 *   2. 이 스크립트: 클린 배경 이미지(전체화면) + 추출 텍스트를 좌표에 맞게 오버레이
 *
 * 도형/이미지는 클린 배경에 이미 포함되어 있으므로 텍스트+차트+표만 추가한다.
 *
 * Usage:
 *   node render_nlm_v9.js extracted.json --clean ./clean/ -o output.pptx
 */

const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const SLIDE_W = 10;
const SLIDE_H = 5.625;
const DEFAULT_FONT = "Pretendard";

const ROLE_DEFAULTS = {
  title:    { fontSize: 28, bold: true,  align: "left",   valign: "top",    color: "1B2D6E" },
  subtitle: { fontSize: 13, bold: false, align: "left",   valign: "middle", color: "555555" },
  stat:     { fontSize: 36, bold: true,  align: "center", valign: "middle", color: "1B2D6E" },
  body:     { fontSize: 12, bold: false, align: "left",   valign: "top",    color: "333333" },
  label:    { fontSize: 11, bold: false, align: "left",   valign: "middle", color: "444444" },
  caption:  { fontSize:  9, bold: false, align: "left",   valign: "middle", color: "888888" },
};

const CHART_TYPE_MAP = {
  bar: "bar", line: "line", pie: "pie",
  doughnut: "doughnut", area: "area",
  "stacked-bar": "bar", "grouped-bar": "bar",
};

// ─── 유틸 ───────────────────────────────────────────────────────────────────

const pct = (v, dim) => (v / 100) * dim;
const normColor = (hex) => hex ? hex.replace(/^#/, "") : undefined;

/** 슬라이드 배경이 어두우면 그 색으로, 밝으면 흰색으로 마스크 색 결정 */
function getMaskColor(sd) {
  const bg = sd.background?.color;
  if (!bg) return "FFFFFF";
  const hex = bg.replace(/^#/, "");
  if (hex.length < 6) return "FFFFFF";
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  const brightness = (r + g + b) / 3;
  return brightness < 128 ? hex : "FFFFFF";
}

function clamp(x, y, w, h) {
  const cx = Math.max(0, Math.min(x, SLIDE_W - 0.05));
  const cy = Math.max(0, Math.min(y, SLIDE_H - 0.05));
  return {
    x: cx, y: cy,
    w: Math.max(0.05, Math.min(w, SLIDE_W - cx)),
    h: Math.max(0.05, Math.min(h, SLIDE_H - cy)),
  };
}

/** 메타 텍스트 필터 — font spec, HEX color 등 */
function isMeta(text) {
  if (!text || !text.trim()) return true;
  const t = text.trim();
  if (/^#[0-9a-fA-F]{3,6}$/.test(t)) return true;
  if (/^\d+px/.test(t)) return true;
  if (/^\d+%?\s+(Marketing|Business|Proposal|font|px|pt)/i.test(t)) return true;
  return false;
}

/** 중복 텍스트 제거 */
function dedup(elements) {
  const seen = new Set();
  return elements.filter((el) => {
    if (el.type !== "text") return true;
    const key = (el.content || "").trim().toLowerCase().slice(0, 50);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ─── 텍스트 렌더러 ──────────────────────────────────────────────────────────

function renderText(slide, el, fontFace, pres, maskColor) {
  if (isMeta(el.content)) return false;
  const role = el.role || "body";
  const def = ROLE_DEFAULTS[role] || ROLE_DEFAULTS.body;

  const { x, y, w, h } = clamp(
    pct(el.x_pct || 0, SLIDE_W), pct(el.y_pct || 0, SLIDE_H),
    pct(el.w_pct || 80, SLIDE_W), pct(el.h_pct || 10, SLIDE_H),
  );
  if (y >= SLIDE_H - 0.05) return false;

  const content = (el.content || "").replace(/\\n/g, "\n");
  const color = normColor(el.color) || def.color;

  // 박스 높이 기반 fontSize 캡핑 (autoFit 제거 — 박스 비대화 방지)
  const baseFontSize = el.fontSize || def.fontSize;
  const maxByHeight = Math.max(8, Math.floor(h * 65));
  const fontSize = Math.min(baseFontSize, maxByHeight);

  // 텍스트 앞에 흰색(또는 배경색) 마스크 — 배경 잔상 텍스트 숨김
  const padX = 0.05;
  const padY = 0.03;
  const mxRaw = x - padX;
  const myRaw = y - padY;
  const mwRaw = w + padX * 2;
  const mhRaw = h + padY * 2;
  const mc = maskColor || "FFFFFF";
  slide.addShape(pres.shapes.RECTANGLE, {
    x: Math.max(0, mxRaw),
    y: Math.max(0, myRaw),
    w: Math.min(mwRaw, SLIDE_W - Math.max(0, mxRaw)),
    h: Math.min(mhRaw, SLIDE_H - Math.max(0, myRaw)),
    fill: { color: mc },
    line: { type: "none" },
  });

  slide.addText(content, {
    x, y, w, h,
    fontFace,
    fontSize,
    bold: el.fontWeight === "bold" || def.bold,
    color,
    align: el.align || def.align,
    valign: def.valign,
    wrap: true,
    margin: [2, 4, 2, 4],
    lineSpacingMultiple: 1.2,
  });
  return true;
}

// ─── 테이블 렌더러 ──────────────────────────────────────────────────────────

function renderTable(slide, el, fontFace, pres, maskColor) {
  // v9b+: NLM 배경 이미지에 이미 표 구조(격자/테두리)가 있으므로
  // PptxGenJS 표 객체를 그리지 않고 각 셀 위치에 텍스트만 오버레이
  const { x, y, w, h } = clamp(
    pct(el.x_pct || 0, SLIDE_W), pct(el.y_pct || 0, SLIDE_H),
    pct(el.w_pct || 80, SLIDE_W), pct(el.h_pct || 40, SLIDE_H),
  );
  if (y >= SLIDE_H - 0.05) return;

  const headers = el.headers || [];
  const rows = el.rows || [];
  if (!headers.length && !rows.length) return;

  const numCols = headers.length > 0 ? headers.length : rows[0].length;
  const numRows = (headers.length > 0 ? 1 : 0) + rows.length;
  const cellW = w / numCols;
  const cellH = h / numRows;
  const mc = maskColor || "FFFFFF";

  // 헤더 셀 — 마스크 먼저, 텍스트 위에 오버레이
  if (headers.length > 0) {
    headers.forEach((hd, ci) => {
      const cellX = x + ci * cellW;
      const cellY = y;
      slide.addShape(pres.shapes.RECTANGLE, {
        x: cellX, y: cellY, w: cellW, h: cellH,
        fill: { color: mc },
        line: { type: "none" },
      });
      slide.addText(String(hd), {
        x: cellX, y: cellY,
        w: cellW, h: cellH,
        fontSize: 11, fontFace,
        bold: true, color: "1B2D6E",
        align: "center", valign: "middle",
        margin: [2, 4, 2, 4],
      });
    });
  }

  // 본문 셀 — 마스크 먼저, 텍스트 위에 오버레이
  rows.forEach((row, ri) => {
    row.forEach((cell, ci) => {
      const cellX = x + ci * cellW;
      const cellY = y + (headers.length > 0 ? (ri + 1) : ri) * cellH;
      slide.addShape(pres.shapes.RECTANGLE, {
        x: cellX, y: cellY, w: cellW, h: cellH,
        fill: { color: mc },
        line: { type: "none" },
      });
      slide.addText(String(cell), {
        x: cellX, y: cellY,
        w: cellW, h: cellH,
        fontSize: 10, fontFace,
        color: "333333",
        align: "center", valign: "middle",
        margin: [2, 4, 2, 4],
        wrap: true,
      });
    });
  });
}

// ─── 차트 렌더러 ────────────────────────────────────────────────────────────

function renderChart(slide, pres, el) {
  const { x, y, w, h } = clamp(
    pct(el.x_pct || 0, SLIDE_W), pct(el.y_pct || 0, SLIDE_H),
    pct(el.w_pct || 40, SLIDE_W), pct(el.h_pct || 40, SLIDE_H),
  );
  if (y >= SLIDE_H - 0.05) return;

  const chartType = CHART_TYPE_MAP[el.chartType] || "bar";
  let datasets = el.datasets || [];
  if (!datasets.length) return;

  const chartData = datasets.map((ds) => ({
    name: ds.name || "",
    labels: el.labels?.length ? el.labels : ds.values.map((_, i) => `${i + 1}`),
    values: ds.values || [],
  }));

  const pptxChartType = {
    bar: pres.charts.BAR, line: pres.charts.LINE,
    pie: pres.charts.PIE, doughnut: pres.charts.DOUGHNUT, area: pres.charts.AREA,
  }[chartType] || pres.charts.BAR;

  const colors = datasets.flatMap((ds) => Array.isArray(ds.color) ? ds.color.map(normColor) : [normColor(ds.color)]).filter(Boolean);
  const opts = {
    x, y, w, h,
    showLegend: datasets.length > 1,
    legendPos: "b", legendFontSize: 8,
    showValue: true, dataLabelFontSize: 8,
    catAxisLabelFontSize: 9,
    ...(colors.length ? { chartColors: colors } : {}),
  };

  try {
    slide.addChart(pptxChartType, chartData, opts);
  } catch (e) {
    console.error(`    차트 렌더 실패: ${e.message}`);
  }
}

// ─── 슬라이드 렌더링 ────────────────────────────────────────────────────────

function renderSlide(pres, slideData, cleanDir, fontFace) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  const slideNum = slideData.slide;
  const cleanPath = path.join(cleanDir, `slide_${String(slideNum).padStart(2, "0")}_clean.png`);

  // 1) 클린 배경 이미지 (전체화면)
  if (fs.existsSync(cleanPath)) {
    const imgData = fs.readFileSync(cleanPath);
    const b64 = imgData.toString("base64");
    slide.addImage({
      data: `data:image/png;base64,${b64}`,
      x: 0, y: 0, w: SLIDE_W, h: SLIDE_H,
    });
  } else {
    // 클린 이미지 없으면 배경색만
    const bg = slideData.background?.color;
    if (bg) slide.background = { color: normColor(bg) || "FFFFFF" };
    console.log(`    ⚠️  클린 이미지 없음: ${path.basename(cleanPath)} — 텍스트만 렌더`);
  }

  // 2) 텍스트 + 차트 + 테이블 오버레이 (도형/이미지는 클린 배경에 이미 있음)
  const maskColor = getMaskColor(slideData);
  const elements = dedup(slideData.elements || []);
  const texts = elements.filter((e) => e.type === "text");
  const charts = elements.filter((e) => e.type === "chart");
  const tables = elements.filter((e) => e.type === "table");

  let textCount = 0;
  texts.forEach((el) => { if (renderText(slide, el, fontFace, pres, maskColor)) textCount++; });
  charts.forEach((el) => renderChart(slide, pres, el));
  tables.forEach((el) => renderTable(slide, el, fontFace, pres, maskColor));

  return { textCount, chartCount: charts.length, tableCount: tables.length };
}

// ─── 메인 ────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  let inputPath = null;
  let outputPath = "output-v9.pptx";
  let cleanDir = "./clean";
  let fontFace = DEFAULT_FONT;
  let slideFilter = null; // null = 전체

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "-o" || args[i] === "--output") outputPath = args[++i];
    else if (args[i] === "--clean") cleanDir = args[++i];
    else if (args[i] === "--font") fontFace = args[++i];
    else if (args[i] === "--slides") slideFilter = args[++i].split(",").map(Number);
    else if (!inputPath) inputPath = args[i];
  }

  if (!inputPath) {
    console.error("Usage: node render_nlm_v9.js <extracted.json> --clean <dir> -o output.pptx");
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(inputPath, "utf-8"));
  const palette = data.style_guide?.palette || {};
  let slides = data.slides || [];

  if (slideFilter) {
    slides = slides.filter((s) => slideFilter.includes(s.slide));
  }

  console.log("=".repeat(50));
  console.log("  NLM v9 — Nano Banana Pro 배경 + 텍스트 오버레이");
  console.log("=".repeat(50));
  console.log(`  입력    : ${inputPath}`);
  console.log(`  클린 폴더: ${cleanDir}`);
  console.log(`  슬라이드 : ${slides.length}장`);
  console.log(`  출력    : ${outputPath}`);
  console.log();

  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "NLM v9 Renderer";

  let totalText = 0, totalChart = 0;

  for (const sd of slides) {
    if (sd.error) { console.log(`  S${sd.slide}: 건너뜀`); continue; }

    const { textCount, chartCount } = renderSlide(pres, sd, cleanDir, fontFace);
    totalText += textCount;
    totalChart += chartCount;

    const cleanExists = fs.existsSync(path.join(cleanDir, `slide_${String(sd.slide).padStart(2, "0")}_clean.png`));
    console.log(`  S${sd.slide}: text:${textCount}, chart:${chartCount} ${cleanExists ? "✅ clean" : "⚠️ no-clean"}`);
  }

  await pres.writeFile({ fileName: outputPath });

  console.log();
  console.log("=".repeat(50));
  console.log(`  완료! → ${outputPath}`);
  console.log(`  텍스트: ${totalText}개 | 차트: ${totalChart}개`);
  console.log("=".repeat(50));
}

main().catch((e) => { console.error("ERROR:", e.message); process.exit(1); });
