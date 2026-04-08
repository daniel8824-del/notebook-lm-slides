#!/usr/bin/env node
/**
 * render_nlm_v7b.js — Role 기반 템플릿 렌더러
 *
 * v7 JSON의 구조 정보(role, 내용, 색상)를 활용하되,
 * 좌표는 버리고 검증된 레이아웃 템플릿으로 배치한다.
 *
 * Usage:
 *   node render_nlm_v7b.js v7-output.json -o output.pptx
 */

const pptxgen = require("pptxgenjs");
const fs = require("fs");

const FONT = "Pretendard";

// ─── 유틸리티 ──────────────────────────────────────────────────────────

const norm = (hex) => (hex || "").replace(/^#/, "") || undefined;

function gridColumns(n, opts = {}) {
  const margin = opts.margin ?? 0.6;
  const gap = opts.gap ?? 0.25;
  const totalW = 10 - margin * 2;
  const colW = (totalW - gap * (n - 1)) / n;
  return Array.from({ length: n }, (_, i) => ({
    x: margin + i * (colW + gap),
    w: colW,
  }));
}

// ─── 슬라이드 아키타입 감지 ───────────────────────────────────────────

function detectArchetype(elements) {
  const roles = {};
  const types = {};
  for (const el of elements) {
    const r = el.role || el.type;
    roles[r] = (roles[r] || 0) + 1;
    types[el.type] = (types[el.type] || 0) + 1;
  }

  const hasChart = (types.chart || 0) > 0;
  const hasTable = (types.table || 0) > 0;
  const statCount = roles.stat || 0;
  const bodyCount = roles.body || 0;
  const titleCount = roles.title || 0;
  const total = elements.filter((e) => e.type === "text").length;

  // cover: title + subtitle, few elements
  if (total <= 4 && titleCount >= 1 && !hasChart && !hasTable && statCount === 0) {
    return "cover";
  }
  // stat_cards: stats prominent
  if (statCount >= 2) {
    return "stat_cards";
  }
  // chart_focus: chart with description
  if (hasChart && statCount <= 1) {
    return "chart_focus";
  }
  // table
  if (hasTable) {
    return "table_focus";
  }
  // content: body-heavy
  return "content";
}

// ─── 템플릿 렌더러 ───────────────────────────────────────────────────

function renderCover(pres, sd, palette) {
  const slide = pres.addSlide();
  const bg = norm(sd.background?.color) || norm(palette.backgrounds?.[0]) || "1A2B5B";
  slide.background = { color: bg };

  const els = sd.elements.filter((e) => e.type === "text");
  const title = els.find((e) => e.role === "title");
  const subtitle = els.find((e) => e.role === "subtitle");

  // 제목
  if (title) {
    slide.addText(title.content.replace(/\\n/g, "\n"), {
      x: 0.8, y: 1.2, w: 8.4, h: 2.0,
      fontSize: 40, fontFace: FONT, bold: true,
      color: norm(title.color) || "FFFFFF",
      align: "center", valign: "middle",
    });
  }

  // 구분선 (accent)
  const accent = norm(palette.accent_colors?.[0]) || "00BCD4";
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 2.5, y: 3.4, w: 5, h: 0.02,
    fill: { color: accent },
  });

  // 부제목
  if (subtitle) {
    slide.addText(subtitle.content.replace(/\\n/g, "\n"), {
      x: 1.2, y: 3.6, w: 7.6, h: 0.8,
      fontSize: 18, fontFace: FONT,
      color: norm(subtitle.color) || "B0B0B0",
      align: "center", valign: "middle",
    });
  }

  addNlmFooter(slide);
  return slide;
}

function renderStatCards(pres, sd, palette) {
  const slide = pres.addSlide();
  const bg = norm(sd.background?.color) || norm(palette.backgrounds?.[0]) || "1E3050";
  slide.background = { color: bg };

  const els = sd.elements;
  const title = els.find((e) => e.type === "text" && e.role === "title");
  const stats = els.filter((e) => e.type === "text" && e.role === "stat");
  const labels = els.filter((e) => e.type === "text" && e.role === "label");
  const bodies = els.filter((e) => e.type === "text" && e.role === "body");
  const charts = els.filter((e) => e.type === "chart");
  // accent: 차트 데이터 색상 > style_guide accent > 기본 시안
  const chartColor = charts.length > 0 && charts[0].datasets?.[0]?.color
    ? norm(charts[0].datasets[0].color) : null;
  const accent = chartColor || norm(palette.accent_colors?.[0]) || "00BCD4";

  // 제목 — 충분한 크기
  if (title) {
    slide.addText(title.content.replace(/\\n/g, "\n"), {
      x: 0.6, y: 0.25, w: 8.8, h: 0.65,
      fontSize: 22, fontFace: FONT, bold: true,
      color: norm(title.color) || "FFFFFF",
      align: "left",
    });
  }

  // ── 통합 카드: stat + 비율 막대 + label + body를 하나로 ──
  const n = stats.length || 1;
  const cols = gridColumns(n, { margin: 0.6, gap: 0.35 });

  // 비율 막대 높이 계산 (stat 값에서 숫자 추출)
  const values = stats.map((s) => {
    const num = parseFloat(s.content.replace(/[^0-9.]/g, "")) || 1;
    return num;
  });
  const maxVal = Math.max(...values, 1);

  const barAreaTop = 1.1;
  const barAreaH = 2.2;
  const statNumY = barAreaTop;
  const barBottom = barAreaTop + barAreaH;
  const labelY = barBottom + 0.05;
  const dividerY = labelY + 0.35;
  const bodyY = dividerY + 0.15;
  const bodyH = 5.625 - bodyY - 0.25;

  stats.forEach((stat, i) => {
    if (i >= cols.length) return;
    const c = cols[i];
    const ratio = values[i] / maxVal;
    const barH = Math.max(0.4, barAreaH * 0.85 * ratio);
    const barY = barBottom - barH;
    const barW = c.w * 0.45;
    const barX = c.x + (c.w - barW) / 2;

    // 비율 막대
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: barX, y: barY, w: barW, h: barH,
      fill: { color: accent },
      rectRadius: 0.04,
    });

    // stat 숫자 — 막대 위
    slide.addText(stat.content.replace(/\\n/g, "\n"), {
      x: c.x, y: barY - 0.65, w: c.w, h: 0.6,
      fontSize: 24, fontFace: FONT, bold: true,
      color: norm(stat.color) || "FFFFFF",
      align: "center", valign: "bottom",
    });

    // label (연도) — 막대 아래
    if (i < labels.length) {
      slide.addText(labels[i].content, {
        x: c.x, y: labelY, w: c.w, h: 0.3,
        fontSize: 13, fontFace: FONT, bold: true,
        color: "FFFFFF",
        align: "center",
      });
    }
  });

  // 구분선
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: dividerY, w: 8.8, h: 0.01,
    fill: { color: accent },
  });

  // body 텍스트 — 하단 3열
  bodies.slice(0, n).forEach((b, i) => {
    if (i >= cols.length) return;
    const c = cols[i];
    slide.addText("● " + b.content.replace(/\\n/g, " ").trim(), {
      x: c.x, y: bodyY, w: c.w, h: bodyH,
      fontSize: 10, fontFace: FONT,
      color: "CCCCCC",
      align: "left", valign: "top",
      lineSpacingMultiple: 1.3,
      autoFit: true,
    });
  });

  addNlmFooter(slide);
  return slide;
}

function renderChartFocus(pres, sd, palette) {
  const slide = pres.addSlide();
  const bg = norm(sd.background?.color) || norm(palette.backgrounds?.[0]) || "1E3050";
  slide.background = { color: bg };

  const els = sd.elements;
  const title = els.find((e) => e.type === "text" && e.role === "title");
  const charts = els.filter((e) => e.type === "chart");
  const bodies = els.filter((e) => e.type === "text" && e.role === "body");
  const accent = norm(palette.accent_colors?.[0]) || "00BCD4";

  if (title) {
    slide.addText(title.content.replace(/\\n/g, "\n"), {
      x: 0.5, y: 0.2, w: 9, h: 0.7,
      fontSize: 24, fontFace: FONT, bold: true,
      color: "FFFFFF", align: "left",
    });
  }

  if (charts.length > 0) {
    const chart = charts[0];
    const chartType = {
      bar: pres.charts.BAR, line: pres.charts.LINE,
      pie: pres.charts.PIE, doughnut: pres.charts.DOUGHNUT,
    }[chart.chartType] || pres.charts.BAR;

    const chartData = (chart.datasets || []).map((ds) => ({
      name: ds.name || "",
      labels: chart.labels || [],
      values: ds.values || [],
    }));

    if (chartData.length > 0) {
      try {
        slide.addChart(chartType, chartData, {
          x: 0.8, y: 1.1, w: 8.4, h: 3.2,
          showTitle: false,
          showValue: true,
          dataLabelPosition: "outEnd",
          dataLabelFontSize: 10,
          dataLabelColor: "FFFFFF",
          catAxisLabelColor: "FFFFFF",
          valAxisHidden: true,
          chartColors: (chart.datasets || []).map((ds) => norm(ds.color) || accent),
        });
      } catch (e) {
        console.error(`    차트 렌더 실패: ${e.message}`);
      }
    }
  }

  // 본문 텍스트 — 하단
  if (bodies.length > 0) {
    const cols = gridColumns(Math.min(bodies.length, 3), { margin: 0.6 });
    bodies.slice(0, 3).forEach((b, i) => {
      slide.addText(b.content.replace(/\\n/g, "\n"), {
        x: cols[i].x, y: 4.5, w: cols[i].w, h: 0.9,
        fontSize: 10, fontFace: FONT, color: "B0B0B0",
        align: "left", valign: "top", autoFit: true,
      });
    });
  }

  addNlmFooter(slide);
  return slide;
}

function renderContent(pres, sd, palette) {
  const slide = pres.addSlide();
  const bg = norm(sd.background?.color) || norm(palette.backgrounds?.[0]) || "1E3050";
  slide.background = { color: bg };

  const els = sd.elements;
  const title = els.find((e) => e.type === "text" && e.role === "title");
  const subtitle = els.find((e) => e.type === "text" && e.role === "subtitle");
  const bodies = els.filter((e) => e.type === "text" && e.role === "body");

  let yPos = 0.3;

  if (title) {
    slide.addText(title.content.replace(/\\n/g, "\n"), {
      x: 0.5, y: yPos, w: 9, h: 0.7,
      fontSize: 24, fontFace: FONT, bold: true,
      color: "FFFFFF", align: "left",
    });
    yPos += 0.9;
  }

  if (subtitle) {
    slide.addText(subtitle.content.replace(/\\n/g, "\n"), {
      x: 0.5, y: yPos, w: 9, h: 0.5,
      fontSize: 16, fontFace: FONT,
      color: "B0B0B0", align: "left",
    });
    yPos += 0.7;
  }

  bodies.forEach((b) => {
    slide.addText(b.content.replace(/\\n/g, "\n"), {
      x: 0.6, y: yPos, w: 8.8, h: 0.8,
      fontSize: 13, fontFace: FONT,
      color: "FFFFFF", align: "left", valign: "top",
      autoFit: true,
    });
    yPos += 0.9;
  });

  addNlmFooter(slide);
  return slide;
}

// ─── 공통: NLM 워터마크 ──────────────────────────────────────────────

function addNlmFooter(slide) {
  slide.addText("NotebookLM", {
    x: 8.5, y: 5.2, w: 1.2, h: 0.3,
    fontSize: 8, fontFace: FONT,
    color: "999999", align: "right",
  });
}

// ─── 메인 ─────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  let inputPath = null;
  let outputPath = "output-b.pptx";

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "-o" || args[i] === "--output") outputPath = args[++i];
    else if (args[i] === "-h" || args[i] === "--help") {
      console.log("Usage: node render_nlm_v7b.js <input.json> -o output.pptx");
      process.exit(0);
    } else if (!inputPath) inputPath = args[i];
  }

  if (!inputPath) {
    console.error("ERROR: 입력 JSON 필요");
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(inputPath, "utf-8"));
  const palette = data.style_guide?.palette || {};
  const slides = data.slides || [];

  console.log("=" .repeat(50));
  console.log("  NLM v7b — Role 기반 템플릿 렌더러");
  console.log("=" .repeat(50));
  console.log(`  입력: ${inputPath}`);
  console.log(`  슬라이드: ${slides.length}장`);
  console.log();

  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "NLM v7b Renderer";

  for (const sd of slides) {
    if (sd.error) {
      console.log(`  S${sd.slide}: 건너뜀 (error)`);
      continue;
    }

    const archetype = detectArchetype(sd.elements || []);
    console.log(`  S${sd.slide}: 아키타입=${archetype}`);

    switch (archetype) {
      case "cover":
        renderCover(pres, sd, palette);
        break;
      case "stat_cards":
        renderStatCards(pres, sd, palette);
        break;
      case "chart_focus":
        renderChartFocus(pres, sd, palette);
        break;
      default:
        renderContent(pres, sd, palette);
        break;
    }
  }

  await pres.writeFile({ fileName: outputPath });

  console.log();
  console.log("=" .repeat(50));
  console.log(`  완료! → ${outputPath}`);
  console.log("=" .repeat(50));
}

main().catch((e) => {
  console.error("ERROR:", e.message);
  process.exit(1);
});
