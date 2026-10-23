/**
 * Renders the SVG diagrams from diagrams.cjs to PNG (2x for print) with
 * headless Chromium via Playwright, into docs/images/.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const { diagrams } = require("./diagrams.cjs");

async function render(outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 2 });
  const results = {};
  for (const [name, svg] of Object.entries(diagrams)) {
    fs.writeFileSync(path.join(outDir, `${name}.svg`), svg);
    const width = Number(/width="(\d+)"/.exec(svg)[1]);
    const height = Number(/height="(\d+)"/.exec(svg)[1]);
    await page.setViewportSize({ width, height });
    await page.setContent(`<html><body style="margin:0">${svg}</body></html>`, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    const file = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: file, clip: { x: 0, y: 0, width, height } });
    results[name] = { file, width, height };
  }
  await browser.close();
  return results;
}

module.exports = { render };

if (require.main === module) {
  render(path.resolve(__dirname, "../images")).then((r) => console.log(Object.keys(r).join("\n")));
}
