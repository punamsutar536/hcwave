/**
 * Builds docs/Hospital_AI_Wave1_As-Built_Solution_Architecture.docx.
 *
 *   cd docs/generator && npm ci && node build.cjs
 *
 * Steps: render diagrams (diagrams.cjs → PNG via Chromium), then lay out the
 * content from content.cjs with docx-js (A4, Word heading styles, TOC,
 * numbered steps, tables with fixed DXA widths).
 */
"use strict";

const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  Header,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableOfContents,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");
const { render } = require("./render.cjs");
const { sections, appendices } = require("./content.cjs");

const OUT = path.resolve(__dirname, "../Hospital_AI_Wave1_As-Built_Solution_Architecture.docx");
const IMAGES = path.resolve(__dirname, "../images");

// A4 with 2 cm margins → 11906 − 2 × 1134 = 9638 DXA of text width.
const PAGE = { width: 11906, height: 16838, margin: 1134 };
const TEXT_WIDTH = PAGE.width - 2 * PAGE.margin;
const MAX_IMAGE_PX = Math.floor((TEXT_WIDTH / 1440) * 96); // 96 px per inch

const COLOR = { primary: "0B4F8C", accent: "0B6BCB", muted: "52606D", headerFill: "E6F1FB", rule: "BCCCDC", noteFill: "FFF4E5" };
const FONT = "Calibri";
const MONO = "Consolas";

let stepsInstance = 0;

/** Splits `**bold**` and `code` spans into runs. */
function runs(text, opts = {}) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((part) => {
    if (part.startsWith("**")) return new TextRun({ text: part.slice(2, -2), bold: true, ...opts });
    if (part.startsWith("`")) return new TextRun({ text: part.slice(1, -1), font: MONO, size: 18, ...opts });
    return new TextRun({ text: part, ...opts });
  });
}

function paragraph(text) {
  return new Paragraph({ children: runs(text), spacing: { after: 120, line: 276 } });
}

function heading(text, level) {
  return new Paragraph({ heading: level, children: [new TextRun(text)], keepNext: true });
}

function bullets(items) {
  return items.map((item) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: runs(item), spacing: { after: 60 } }));
}

function steps(items) {
  stepsInstance += 1;
  return items.map((item) => new Paragraph({ numbering: { reference: "steps", level: 0, instance: stepsInstance }, children: runs(item), spacing: { after: 60 } }));
}

function cell(text, width, header = false) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: header ? { type: ShadingType.CLEAR, color: "auto", fill: COLOR.headerFill } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    children: [new Paragraph({ children: runs(text, { size: 18, bold: header || undefined }) })],
  });
}

function table(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  if (Math.abs(total - TEXT_WIDTH) > 2) {
    // Scale proportionally so every table spans the text width exactly.
    widths = widths.map((w) => Math.round((w * TEXT_WIDTH) / total));
    widths[widths.length - 1] += TEXT_WIDTH - widths.reduce((a, b) => a + b, 0);
  }
  const border = { style: BorderStyle.SINGLE, size: 4, color: COLOR.rule };
  return [
    new Table({
      width: { size: TEXT_WIDTH, type: WidthType.DXA },
      columnWidths: widths,
      borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
      rows: [
        new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], true)) }),
        ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, widths[i])) })),
      ],
    }),
    new Paragraph({ children: [], spacing: { after: 120 } }),
  ];
}

function image(name, caption, sizes) {
  const { width, height } = sizes[name];
  const w = MAX_IMAGE_PX;
  const h = Math.round((height / width) * w);
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      keepNext: true,
      spacing: { before: 120, after: 60 },
      children: [new ImageRun({ type: "png", data: fs.readFileSync(path.join(IMAGES, `${name}.png`)), transformation: { width: w, height: h }, altText: { title: caption, description: caption, name } })],
    }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: caption, italics: true, size: 18, color: COLOR.muted })] }),
  ];
}

function code(text) {
  return text.split("\n").map((line, i, all) =>
    new Paragraph({
      shading: { type: ShadingType.CLEAR, color: "auto", fill: "F2F4F7" },
      spacing: { after: i === all.length - 1 ? 160 : 0, line: 240 },
      indent: { left: 120, right: 120 },
      children: [new TextRun({ text: line || " ", font: MONO, size: 16 })],
    }),
  );
}

function note(text) {
  return [
    new Paragraph({
      shading: { type: ShadingType.CLEAR, color: "auto", fill: COLOR.noteFill },
      border: { left: { style: BorderStyle.SINGLE, size: 18, color: "C26A00", space: 6 } },
      spacing: { before: 120, after: 160 },
      indent: { left: 160, right: 120 },
      children: runs(text),
    }),
  ];
}

function blocks(list, sizes) {
  const out = [];
  for (const b of list) {
    switch (b.type) {
      case "h1": out.push(new Paragraph({ children: [new PageBreak()] }), heading(b.text, HeadingLevel.HEADING_1)); break;
      case "h2": out.push(heading(b.text, HeadingLevel.HEADING_2)); break;
      case "h3": out.push(heading(b.text, HeadingLevel.HEADING_3)); break;
      case "p": out.push(paragraph(b.text)); break;
      case "bullets": out.push(...bullets(b.items)); break;
      case "steps": out.push(...steps(b.items)); break;
      case "table": out.push(...table(b.headers, b.rows, b.widths)); break;
      case "image": out.push(...image(b.name, b.caption, sizes)); break;
      case "code": out.push(...code(b.text)); break;
      case "note": out.push(...note(b.text)); break;
      default: throw new Error(`unknown block ${b.type}`);
    }
  }
  return out;
}

function titlePage() {
  const line = (text, size, opts = {}) => new Paragraph({ alignment: AlignmentType.LEFT, spacing: { after: 160 }, children: [new TextRun({ text, size, ...opts })] });
  return [
    new Paragraph({ spacing: { before: 2400 }, children: [] }),
    line("HOSPITAL AI – WAVE 1 PLATFORM", 24, { color: COLOR.accent, bold: true }),
    line("As-Built Solution Architecture", 56, { bold: true, color: COLOR.primary }),
    line("and Execution Guide", 40, { color: COLOR.primary }),
    new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: COLOR.accent, space: 8 } }, spacing: { after: 360 }, children: [] }),
    line("WhatsApp patient assistant · Reminders · Secure report delivery · Feedback & reputation · Management dashboard", 24, { color: COLOR.muted }),
    line("Microsoft Azure (Central India) · Kubernetes (AKS) · Python FastAPI · LangGraph · Azure OpenAI in Foundry · Bicep IaC", 22, { color: COLOR.muted }),
    new Paragraph({ spacing: { before: 1600 }, children: [] }),
    ...table(
      ["Document control", ""],
      [
        ["Version", "1.0 – as built"],
        ["Date", "13 October 2026"],
        ["Status", "Released for implementation and pilot deployment"],
        ["Repository", "github.com/tanajis/hcwave"],
        ["Audience", "Solution architects, platform engineers, implementation leads, hospital IT and security reviewers"],
        ["Source", "Hospital AI – Wave 1 Build Guide and the Azure technology brief"],
      ],
      [2400, 7238],
    ),
  ];
}

async function main() {
  const sizes = await render(IMAGES);
  const doc = new Document({
    creator: "hcwave platform team",
    title: "Hospital AI – Wave 1: As-Built Solution Architecture and Execution Guide",
    description: "As-built architecture, security design and deployment instructions",
    features: { updateFields: true },
    styles: {
      default: { document: { run: { font: FONT, size: 21 } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 34, bold: true, color: COLOR.primary, font: FONT }, paragraph: { spacing: { before: 120, after: 200 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: COLOR.accent, font: FONT }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, color: COLOR.primary, font: FONT }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 } },
      ],
    },
    numbering: {
      config: [
        { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
        { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
      ],
    },
    sections: [
      {
        properties: { page: { size: { width: PAGE.width, height: PAGE.height }, margin: { top: PAGE.margin, bottom: PAGE.margin, left: PAGE.margin, right: PAGE.margin } } },
        headers: {
          default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "Hospital AI – Wave 1 · As-built solution architecture", size: 16, color: COLOR.muted })] })] }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({ text: "Page ", size: 16, color: COLOR.muted }),
                  new TextRun({ children: [PageNumber.CURRENT], size: 16, color: COLOR.muted }),
                  new TextRun({ text: " of ", size: 16, color: COLOR.muted }),
                  new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: COLOR.muted }),
                  new TextRun({ text: "   ·   Confidential – contains security architecture", size: 16, color: COLOR.muted }),
                ],
              }),
            ],
          }),
        },
        children: [
          ...titlePage(),
          new Paragraph({ children: [new PageBreak()] }),
          new Paragraph({ children: [new TextRun({ text: "Contents", bold: true, size: 34, color: COLOR.primary })], spacing: { after: 200 } }),
          new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
          new Paragraph({ children: [new TextRun({ text: "If the table of contents is empty, right-click it and choose Update Field.", italics: true, size: 18, color: COLOR.muted })] }),
          ...blocks(sections, sizes),
          ...blocks(appendices, sizes),
        ],
      },
    ],
  });
  fs.writeFileSync(OUT, await Packer.toBuffer(doc));
  console.log(`wrote ${OUT}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
