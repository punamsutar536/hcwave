/**
 * Architecture diagrams as code.
 *
 * Each diagram is described with a tiny DSL (groups, nodes, edges) and
 * rendered to SVG; render.cjs screenshots the SVGs to PNG with headless
 * Chromium so the Word document can embed them. Edit the coordinates here
 * and re-run `node build.cjs` to refresh docs/images and the .docx.
 */
"use strict";

// Palette: one hue per concern, readable in print.
const C = {
  ink: "#1f2933",
  muted: "#52606d",
  line: "#7b8794",
  azure: { fill: "#e6f1fb", stroke: "#0b6bcb" },
  data: { fill: "#e7f6ec", stroke: "#1f8a4c" },
  ai: { fill: "#f1ebfb", stroke: "#6b3fb8" },
  flow: { fill: "#fff3e0", stroke: "#c26a00" },
  ext: { fill: "#f2f4f7", stroke: "#7b8794" },
  app: { fill: "#e9f7f8", stroke: "#0f7c86" },
  sec: { fill: "#fdecec", stroke: "#b42318" },
  group: { fill: "#fafbfc", stroke: "#bcccdc" },
};

const FONT = "Inter, 'DejaVu Sans', Arial, sans-serif";

function esc(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Anchor point on a node side; offset is 0..1 along that side. */
function anchor(node, side, offset = 0.5) {
  const { x, y, w, h } = node;
  switch (side) {
    case "l": return [x, y + h * offset];
    case "r": return [x + w, y + h * offset];
    case "t": return [x + w * offset, y];
    case "b": return [x + w * offset, y + h];
    default: throw new Error(`bad side ${side}`);
  }
}

/** Orthogonal route between two anchors (or explicit waypoints). */
function route(edge, nodes) {
  const a = anchor(nodes[edge.from], edge.fs || "r", edge.fo ?? 0.5);
  const b = anchor(nodes[edge.to], edge.ts || "l", edge.to_o ?? 0.5);
  if (edge.via) return [a, ...edge.via, b];
  const horizontalStart = ["l", "r"].includes(edge.fs || "r");
  const horizontalEnd = ["l", "r"].includes(edge.ts || "l");
  if (horizontalStart && horizontalEnd) {
    if (Math.abs(a[1] - b[1]) < 1) return [a, b];
    const midX = edge.midX ?? (a[0] + b[0]) / 2;
    return [a, [midX, a[1]], [midX, b[1]], b];
  }
  if (!horizontalStart && !horizontalEnd) {
    if (Math.abs(a[0] - b[0]) < 1) return [a, b];
    const midY = edge.midY ?? (a[1] + b[1]) / 2;
    return [a, [a[0], midY], [b[0], midY], b];
  }
  return horizontalStart ? [a, [b[0], a[1]], b] : [a, [a[0], b[1]], b];
}

function renderNode(n) {
  const style = n.style || C.azure;
  if (n.header) {
    return `<rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="10" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.6"/>` +
      `<text x="${n.x + 16}" y="${n.y + 26}" font-size="14" font-weight="700" fill="${style.stroke}">${esc(n.title)}</text>`;
  }
  const lines = [];
  const titleLines = Array.isArray(n.title) ? n.title : [n.title];
  const subLines = n.sub ? (Array.isArray(n.sub) ? n.sub : [n.sub]) : [];
  const total = titleLines.length * 17 + subLines.length * 15;
  let cy = n.y + n.h / 2 - total / 2 + 13;
  for (const t of titleLines) {
    lines.push(`<text x="${n.x + n.w / 2}" y="${cy}" text-anchor="middle" font-weight="600" font-size="14" fill="${C.ink}">${esc(t)}</text>`);
    cy += 17;
  }
  for (const s of subLines) {
    lines.push(`<text x="${n.x + n.w / 2}" y="${cy}" text-anchor="middle" font-size="12" fill="${C.muted}">${esc(s)}</text>`);
    cy += 15;
  }
  const dash = n.dashed ? ' stroke-dasharray="6 4"' : "";
  return `<rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="10" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.6"${dash}/>` + lines.join("");
}

function renderGroup(g) {
  const style = g.style || C.group;
  const dash = g.dashed ? ' stroke-dasharray="7 5"' : "";
  return (
    `<rect x="${g.x}" y="${g.y}" width="${g.w}" height="${g.h}" rx="14" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.4"${dash}/>` +
    `<text x="${g.x + 14}" y="${g.y + 22}" font-size="13" font-weight="700" fill="${style.stroke === C.group.stroke ? C.muted : style.stroke}" letter-spacing="0.3">${esc(g.label)}</text>`
  );
}

/** Returns [pathSvg, labelSvg] so labels can be drawn above every line. */
function renderEdge(e, nodes) {
  const pts = route(e, nodes);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ");
  const color = e.color || C.line;
  const dash = e.dashed ? ' stroke-dasharray="6 4"' : "";
  const markers = `marker-end="url(#arrow)"${e.both ? ' marker-start="url(#arrowStart)"' : ""}`;
  let label = "";
  if (e.label) {
    const [lx, ly] = e.labelAt || midpoint(pts);
    const width = e.label.length * 6.6 + 12;
    label =
      `<rect x="${lx - width / 2}" y="${ly - 10}" width="${width}" height="18" rx="9" fill="#ffffff" stroke="${color}" stroke-width="0.8"/>` +
      `<text x="${lx}" y="${ly + 3}" text-anchor="middle" font-size="11" fill="${C.ink}">${esc(e.label)}</text>`;
  }
  return [`<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"${dash} ${markers}/>`, label];
}

function midpoint(pts) {
  // Midpoint of the longest segment keeps labels off corners.
  let best = [pts[0], pts[1]];
  let bestLen = -1;
  for (let i = 1; i < pts.length; i++) {
    const len = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (len > bestLen) { bestLen = len; best = [pts[i - 1], pts[i]]; }
  }
  return [(best[0][0] + best[1][0]) / 2, (best[0][1] + best[1][1]) / 2];
}

function renderChips(chips) {
  return chips.map((c) => {
    const style = c.style || C.ext;
    return `<rect x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h || 34}" rx="17" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.2"/>` +
      `<text x="${c.x + c.w / 2}" y="${c.y + (c.h || 34) / 2 + 4}" text-anchor="middle" font-size="12" fill="${C.ink}">${esc(c.label)}</text>`;
  }).join("");
}

/** Builds a complete SVG document from a diagram spec. */
function svg(spec) {
  const nodes = Object.fromEntries((spec.nodes || []).map((n) => [n.id, n]));
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${spec.width}" height="${spec.height}" viewBox="0 0 ${spec.width} ${spec.height}" font-family="${FONT}">`);
  parts.push(`<defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${C.line}"/></marker>
    <marker id="arrowStart" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="${C.line}"/></marker>
  </defs>`);
  parts.push(`<rect width="100%" height="100%" fill="#ffffff"/>`);
  if (spec.title) parts.push(`<text x="24" y="34" font-size="20" font-weight="700" fill="${C.ink}">${esc(spec.title)}</text>`);
  if (spec.subtitle) parts.push(`<text x="24" y="56" font-size="13" fill="${C.muted}">${esc(spec.subtitle)}</text>`);
  for (const g of spec.groups || []) parts.push(renderGroup(g));
  const edges = (spec.edges || []).map((e) => renderEdge(e, nodes));
  for (const [path] of edges) parts.push(path);
  for (const [, label] of edges) parts.push(label);
  for (const n of spec.nodes || []) parts.push(renderNode(n));
  if (spec.chips) parts.push(renderChips(spec.chips));
  for (const t of spec.texts || []) {
    parts.push(`<text x="${t.x}" y="${t.y}" font-size="${t.size || 12}" font-weight="${t.bold ? 700 : 400}" fill="${t.color || C.muted}" text-anchor="${t.anchor || "start"}">${esc(t.text)}</text>`);
  }
  if (spec.legend) {
    let lx = spec.legend.x;
    for (const item of spec.legend.items) {
      parts.push(`<rect x="${lx}" y="${spec.legend.y}" width="16" height="12" rx="3" fill="${item.style.fill}" stroke="${item.style.stroke}"/>`);
      parts.push(`<text x="${lx + 22}" y="${spec.legend.y + 10}" font-size="12" fill="${C.muted}">${esc(item.label)}</text>`);
      lx += item.label.length * 6.8 + 48;
    }
  }
  parts.push("</svg>");
  return parts.join("\n");
}

/** Sequence diagram: lifelines with numbered messages. */
function sequence(spec) {
  const colW = (spec.width - 60) / spec.actors.length;
  const x = (i) => 30 + colW * i + colW / 2;
  const parts = [];
  const height = 130 + spec.messages.length * spec.step + 40;
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${spec.width}" height="${height}" viewBox="0 0 ${spec.width} ${height}" font-family="${FONT}">`);
  parts.push(`<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${C.ink}"/></marker></defs>`);
  parts.push(`<rect width="100%" height="100%" fill="#ffffff"/>`);
  parts.push(`<text x="24" y="34" font-size="20" font-weight="700" fill="${C.ink}">${esc(spec.title)}</text>`);
  if (spec.subtitle) parts.push(`<text x="24" y="56" font-size="13" fill="${C.muted}">${esc(spec.subtitle)}</text>`);
  spec.actors.forEach((a, i) => {
    const style = a.style || C.azure;
    const w = Math.min(colW - 16, 190);
    parts.push(`<rect x="${x(i) - w / 2}" y="72" width="${w}" height="46" rx="9" fill="${style.fill}" stroke="${style.stroke}" stroke-width="1.5"/>`);
    const lines = Array.isArray(a.label) ? a.label : [a.label];
    lines.forEach((l, j) => parts.push(`<text x="${x(i)}" y="${92 + j * 15 - (lines.length - 1) * 6}" text-anchor="middle" font-size="12.5" font-weight="600" fill="${C.ink}">${esc(l)}</text>`));
    parts.push(`<line x1="${x(i)}" y1="118" x2="${x(i)}" y2="${height - 20}" stroke="${C.line}" stroke-dasharray="4 4"/>`);
  });
  spec.messages.forEach((m, k) => {
    const y = 150 + k * spec.step;
    const x1 = x(m.from);
    const x2 = x(m.to);
    const dash = m.reply ? ' stroke-dasharray="6 4"' : "";
    if (m.from === m.to) {
      parts.push(`<path d="M${x1},${y - 8} h36 v16 h-34" fill="none" stroke="${C.ink}" stroke-width="1.4" marker-end="url(#arrow)"/>`);
      const selfLabel = `${k + 1}. ${m.text}`;
      parts.push(`<rect x="${x1 + 40}" y="${y - 9}" width="${selfLabel.length * 6.4 + 8}" height="17" fill="#ffffff"/>`);
      parts.push(`<text x="${x1 + 44}" y="${y + 4}" font-size="12" fill="${C.ink}">${esc(selfLabel)}</text>`);
      return;
    }
    parts.push(`<line x1="${x1}" y1="${y}" x2="${x2}" y2="${y}" stroke="${C.ink}" stroke-width="1.4"${dash} marker-end="url(#arrow)"/>`);
    const tx = (x1 + x2) / 2;
    const label = `${k + 1}. ${m.text}`;
    const lw = label.length * 6.4 + 10;
    parts.push(`<rect x="${tx - lw / 2}" y="${y - 20}" width="${lw}" height="16" fill="#ffffff"/>`);
    parts.push(`<text x="${tx}" y="${y - 7}" text-anchor="middle" font-size="12" fill="${C.ink}">${esc(label)}</text>`);
  });
  parts.push("</svg>");
  return parts.join("\n");
}

// --------------------------------------------------------------------------- //
// 1. Solution architecture
// --------------------------------------------------------------------------- //
const solution = svg({
  width: 1720,
  height: 1080,
  title: "Hospital AI Wave 1 – as-built solution architecture on Azure (Central India)",
  subtitle: "Private-by-default: every data and AI service sits behind private endpoints; workloads authenticate with managed identities.",
  groups: [
    { x: 16, y: 72, w: 254, h: 790, label: "PEOPLE & SYSTEMS" },
    { x: 288, y: 72, w: 280, h: 790, label: "CHANNEL, EDGE & EVENTS" },
    { x: 586, y: 72, w: 420, h: 640, label: "AKS · PRIVATE VNET · WORKLOAD IDENTITY", style: C.app },
    { x: 1024, y: 72, w: 320, h: 640, label: "AI & DATA (PRIVATE ENDPOINTS)" },
    { x: 1362, y: 72, w: 342, h: 790, label: "WORKFLOW & INTEGRATION" },
    { x: 16, y: 880, w: 1688, h: 180, label: "SECURITY, IDENTITY & OPERATIONS (SHARED)", style: { fill: "#fff8f7", stroke: C.sec.stroke } },
  ],
  nodes: [
    { id: "patient", x: 36, y: 110, w: 214, h: 84, title: "Patients & families", sub: ["WhatsApp · ml / en / hi", "buttons, lists, report links"], style: C.ext },
    { id: "staff", x: 36, y: 400, w: 214, h: 84, title: "Hospital staff", sub: ["front office · patient relations", "unit head (Entra ID sign-in)"], style: C.ext },
    { id: "his", x: 36, y: 740, w: 214, h: 84, title: "HIS / LIS", sub: ["schedules · visits · reports", "API, DB views or CSV"], style: C.ext },

    { id: "acs", x: 306, y: 104, w: 244, h: 84, title: "ACS Advanced Messaging", sub: ["WhatsApp templates, text,", "interactive buttons & lists"] },
    { id: "eg", x: 306, y: 214, w: 244, h: 56, title: "Event Grid", sub: "system topics (ACS, Blob)" },
    { id: "sb", x: 306, y: 296, w: 244, h: 70, title: "Service Bus Premium", sub: ["inbound · delivery · report", "queues, dead-lettering"] },
    { id: "afd", x: 306, y: 400, w: 244, h: 60, title: "Front Door Premium + WAF", sub: "TLS, OWASP & bot rules, geo" },
    { id: "agc", x: 306, y: 486, w: 244, h: 60, title: "App Gateway for Containers", sub: "WAF policy · Gateway API" },
    { id: "adf", x: 306, y: 740, w: 244, h: 84, title: "Azure Data Factory", sub: ["scheduled CSV / DB pulls", "→ his-imports container"], style: C.flow },

    { id: "worker", x: 606, y: 108, w: 380, h: 84, title: "Queue worker · LangGraph assistant", sub: ["consent → emergency → safety → language →", "flows / intent / RAG FAQ / human handover"], style: C.app },
    { id: "api", x: 606, y: 230, w: 380, h: 84, title: "FastAPI public listener :8000", sub: ["webhooks · report portal (OTP/DOB)", "staff API (takeover, tickets, dashboard)"], style: C.app },
    { id: "ui", x: 606, y: 350, w: 380, h: 70, title: "Staff app (React, MSAL)", sub: "WhatsApp takeover inbox · complaints · front desk", style: C.app },
    { id: "internal", x: 606, y: 460, w: 380, h: 70, title: "Internal job API :8001", sub: "internal load balancer – never on the public gateway", style: C.app },
    { id: "cron", x: 606, y: 572, w: 380, h: 64, title: "Kubernetes CronJobs (portable option)", sub: "same jobs as Logic Apps on other clouds", style: C.app, dashed: true },

    { id: "openai", x: 1042, y: 104, w: 284, h: 84, title: "Azure OpenAI in Foundry", sub: ["gpt-5-mini intent · gpt-5 replies", "embeddings (Claude optional)"], style: C.ai },
    { id: "search", x: 1042, y: 206, w: 284, h: 56, title: "Azure AI Search", sub: "hybrid + semantic ranker", style: C.ai },
    { id: "safety", x: 1042, y: 280, w: 284, h: 56, title: "AI Content Safety", sub: "harm filters + Prompt Shields", style: C.ai },
    { id: "translator", x: 1042, y: 354, w: 284, h: 56, title: "AI Translator", sub: "language detection", style: C.ai },
    { id: "pg", x: 1042, y: 450, w: 284, h: 80, title: "PostgreSQL Flexible Server", sub: ["row-level security per hospital", "Entra auth · HA · backups"], style: C.data },
    { id: "blob", x: 1042, y: 560, w: 284, h: 76, title: "Blob Storage (private)", sub: ["report PDFs, HIS imports", "user-delegation SAS (5 min)"], style: C.data },

    { id: "comms", x: 1380, y: 104, w: 306, h: 70, title: "ACS Email & SMS", sub: "complaint alerts · OTP fallback" },
    { id: "apim", x: 1380, y: 196, w: 306, h: 70, title: "API Management AI gateway", sub: "token quotas · usage per hospital", dashed: true },
    { id: "logic", x: 1380, y: 400, w: 306, h: 84, title: "Logic Apps Standard", sub: ["reminders · feedback · report alerts", "daily briefing · HIS sync"], style: C.flow },
    { id: "func", x: 1380, y: 512, w: 306, h: 70, title: "Durable Functions", sub: "wait 3 h → feedback → escalate", style: C.flow },
    { id: "bi", x: 1380, y: 610, w: 306, h: 60, title: "Power BI Embedded / Grafana", sub: "management dashboard", dashed: true },
    { id: "fhir", x: 1380, y: 740, w: 306, h: 84, title: "Health Data Services (FHIR)", sub: ["standard HIS APIs", "(later waves)"], style: C.flow, dashed: true },
  ],
  edges: [
    { from: "patient", to: "acs", fo: 0.45, to_o: 0.45, both: true },
    { from: "acs", fs: "b", to: "eg", ts: "t" },
    { from: "eg", fs: "b", to: "sb", ts: "t" },
    { from: "sb", to: "worker", fo: 0.5, to_o: 0.75, midX: 578, label: "consume" },
    { from: "worker", fs: "l", to: "acs", ts: "r", fo: 0.25, to_o: 0.3, label: "replies" },
    { from: "staff", to: "afd", fo: 0.35, to_o: 0.5, label: "HTTPS" },
    { from: "afd", fs: "b", to: "agc", ts: "t" },
    { from: "agc", to: "api", fo: 0.3, to_o: 0.8, midX: 578 },
    { from: "agc", to: "ui", fo: 0.7, to_o: 0.7, midX: 590 },
    { from: "worker", to: "openai", fo: 0.35, to_o: 0.5 },
    { from: "worker", to: "search", fo: 0.6, to_o: 0.5, midX: 1014 },
    { from: "worker", to: "safety", fo: 0.8, to_o: 0.5, midX: 1020 },
    { from: "api", to: "pg", fo: 0.5, to_o: 0.3, midX: 1010 },
    { from: "api", to: "blob", fo: 0.8, to_o: 0.4, midX: 1000 },
    // Logic Apps and Durable Functions share one route below the data column.
    { from: "logic", fs: "l", to: "internal", ts: "r", fo: 0.6, to_o: 0.35, via: [[1352, 450.4], [1352, 690], [1015, 690], [1015, 484.5]], label: "job API · MI token", labelAt: [1180, 690] },
    { from: "func", fs: "l", to: "internal", ts: "r", fo: 0.5, to_o: 0.35, via: [[1352, 547], [1352, 690], [1015, 690], [1015, 484.5]] },
    { from: "his", to: "adf", fo: 0.5, to_o: 0.5 },
    { from: "adf", to: "blob", fo: 0.5, to_o: 0.8, via: [[1012, 782], [1012, 621]] },
  ],
  chips: [
    { x: 36, y: 916, w: 250, label: "Microsoft Entra ID · Workload ID", style: C.sec },
    { x: 300, y: 916, w: 230, label: "Key Vault (CSI driver)", style: C.sec },
    { x: 544, y: 916, w: 270, label: "Private Endpoints + Private DNS", style: C.sec },
    { x: 828, y: 916, w: 200, label: "Container Registry", style: C.ext },
    { x: 1042, y: 916, w: 330, label: "Defender for Cloud · Azure Policy · Purview", style: C.sec },
    { x: 1386, y: 916, w: 300, label: "Azure DNS (branded links)", style: C.ext },
    { x: 36, y: 968, w: 470, label: "Azure Monitor · Application Insights · Log Analytics (+ Foundry tracing)", style: C.ext },
    { x: 520, y: 968, w: 300, label: "Azure Backup · AKS Backup · PITR", style: C.ext },
    { x: 834, y: 968, w: 410, label: "GitHub Actions / Azure DevOps · Bicep IaC · Helm", style: C.ext },
    { x: 1258, y: 968, w: 428, label: "India-region hosting · DPDP processor controls", style: C.sec },
  ],
  legend: {
    x: 36, y: 1036,
    items: [
      { label: "Azure platform service", style: C.azure },
      { label: "Application workload (AKS)", style: C.app },
      { label: "AI service", style: C.ai },
      { label: "Data store", style: C.data },
      { label: "Workflow / integration", style: C.flow },
      { label: "External / people", style: C.ext },
    ],
  },
});

// --------------------------------------------------------------------------- //
// 2. Network and security architecture
// --------------------------------------------------------------------------- //
const network = svg({
  width: 1640,
  height: 820,
  title: "Network & identity – private by default",
  subtitle: "Only the WAF-protected gateway is public. PaaS services disable public access and are reached via private endpoints in the VNet.",
  groups: [
    { x: 330, y: 80, w: 980, h: 720, label: "VNet 10.20.0.0/16 (Central India)", style: C.app },
    { x: 1330, y: 80, w: 294, h: 720, label: "PRIVATE DNS ZONES (LINKED)", style: C.group },
    { x: 16, y: 80, w: 296, h: 720, label: "PUBLIC / GLOBAL", style: C.group },
  ],
  nodes: [
    { id: "internet", x: 36, y: 120, w: 256, h: 64, title: "Patients & staff", sub: "internet (HTTPS only)", style: C.ext },
    { id: "afd", x: 36, y: 214, w: 256, h: 70, title: "Front Door Premium", sub: ["WAF: OWASP 2.1, bots,", "rate limits, India geo-filter"] },
    { id: "meta", x: 36, y: 330, w: 256, h: 64, title: "WhatsApp (Meta)", sub: "via ACS (global, data in India)", style: C.ext },
    { id: "acs", x: 36, y: 420, w: 256, h: 64, title: "ACS + Event Grid", sub: "managed-identity delivery" },
    { id: "entra", x: 36, y: 540, w: 256, h: 84, title: "Microsoft Entra ID", sub: ["staff SSO + app roles", "workload / managed identities"], style: C.sec },
    { id: "ci", x: 36, y: 660, w: 256, h: 64, title: "CI/CD (OIDC)", sub: "GitHub Actions / Azure DevOps", style: C.ext },

    { id: "agc", x: 356, y: 120, w: 300, h: 76, title: "snet-agc 10.20.4.0/24", sub: ["App Gateway for Containers", "association + WAF policy"] },
    { id: "aks", x: 356, y: 230, w: 300, h: 150, title: "snet-aks-nodes 10.20.0.0/22", sub: ["AKS (Azure CNI Overlay, Cilium)", "API · worker · staff UI pods", "Entra RBAC, local accounts off", "internal LB 10.20.3.250:8001", "NetworkPolicies: default deny"], style: C.app },
    { id: "logic", x: 356, y: 420, w: 300, h: 64, title: "snet-logicapps 10.20.7.0/24", sub: "Logic Apps VNet integration", style: C.flow },
    { id: "func", x: 356, y: 510, w: 300, h: 64, title: "snet-functions 10.20.8.0/24", sub: "Functions VNet integration", style: C.flow },
    { id: "apim", x: 356, y: 600, w: 300, h: 64, title: "snet-apim 10.20.9.0/24", sub: "APIM StandardV2 (optional)", dashed: true },
    { id: "pgsub", x: 356, y: 690, w: 300, h: 76, title: "snet-postgres 10.20.6.0/24", sub: ["PostgreSQL Flexible Server", "delegated, no public access"], style: C.data },

    { id: "pe", x: 720, y: 120, w: 566, h: 646, header: true, title: "snet-private-endpoints 10.20.5.0/24 – one private endpoint per PaaS service", style: { fill: "#ffffff", stroke: C.azure.stroke } },
  ],
  edges: [
    { from: "internet", fs: "b", to: "afd", ts: "t" },
    { from: "afd", to: "agc", fo: 0.5, to_o: 0.5, label: "Private origin" },
    { from: "agc", fs: "b", to: "aks", ts: "t", label: "pods" },
    { from: "meta", fs: "b", to: "acs", ts: "t" },
    { from: "acs", to: "pe", fo: 0.5, to_o: 0.9, via: [[318, 452], [318, 786], [700, 786], [700, 701.4]], label: "Event Grid → Service Bus (trusted services, MI)", labelAt: [520, 786] },
    { from: "logic", fs: "t", to: "aks", ts: "b", fo: 0.7, to_o: 0.7, label: "job API :8001" },
    { from: "aks", to: "pe", fo: 0.5, to_o: 0.25 },
  ],
  chips: [
    { x: 744, y: 170, w: 250, label: "Key Vault (vault)", style: C.sec },
    { x: 1010, y: 170, w: 250, label: "Container Registry (registry)" },
    { x: 744, y: 222, w: 250, label: "Blob – reports (blob)", style: C.data },
    { x: 1010, y: 222, w: 250, label: "Service Bus (namespace)" },
    { x: 744, y: 274, w: 250, label: "Foundry / Azure OpenAI (account)", style: C.ai },
    { x: 1010, y: 274, w: 250, label: "AI Search (searchService)", style: C.ai },
    { x: 744, y: 326, w: 250, label: "Content Safety (account)", style: C.ai },
    { x: 1010, y: 326, w: 250, label: "Translator (account)", style: C.ai },
    { x: 744, y: 378, w: 250, label: "Function App (sites)", style: C.flow },
    { x: 1010, y: 378, w: 250, label: "Runtime storage (blob/queue/table/file)", style: C.flow },
    { x: 744, y: 430, w: 516, label: "Public network access: Disabled · local auth / keys: Disabled", style: C.sec },
    { x: 1350, y: 120, w: 254, label: "privatelink.vaultcore.azure.net" },
    { x: 1350, y: 164, w: 254, label: "privatelink.azurecr.io" },
    { x: 1350, y: 208, w: 254, label: "privatelink.blob.core.windows.net" },
    { x: 1350, y: 252, w: 254, label: "privatelink.servicebus.windows.net" },
    { x: 1350, y: 296, w: 254, label: "privatelink.openai.azure.com" },
    { x: 1350, y: 340, w: 254, label: "privatelink.cognitiveservices…" },
    { x: 1350, y: 384, w: 254, label: "privatelink.services.ai.azure.com" },
    { x: 1350, y: 428, w: 254, label: "privatelink.search.windows.net" },
    { x: 1350, y: 472, w: 254, label: "privatelink.azurewebsites.net" },
    { x: 1350, y: 516, w: 254, label: "queue / table / file zones" },
    { x: 1350, y: 560, w: 254, label: "<env>.private.postgres…" },
  ],
  texts: [
    { x: 744, y: 500, text: "Identity model", bold: true, color: C.ink, size: 14 },
    { x: 744, y: 524, text: "• AKS pods: workload identity (federated service account) → Entra tokens" },
    { x: 744, y: 544, text: "• Logic Apps / Functions: user-assigned managed identities" },
    { x: 744, y: 564, text: "• PostgreSQL: Entra token as password – no DB password exists" },
    { x: 744, y: 584, text: "• Storage: shared keys off; report links are user-delegation SAS" },
    { x: 744, y: 604, text: "• Key Vault (RBAC): only the app HMAC key and optional 3rd-party secrets" },
    { x: 744, y: 624, text: "• Staff: Entra ID SSO, app roles FrontOffice / PatientRelations / UnitHead / Admin" },
    { x: 744, y: 644, text: "• Internal job API: MI tokens, audience + allow-listed client IDs" },
    { x: 744, y: 676, text: "Data residency", bold: true, color: C.ink, size: 14 },
    { x: 744, y: 700, text: "• All stateful services in Central India; ACS data location India" },
    { x: 744, y: 720, text: "• Azure OpenAI in an India region with regional (Standard) deployments" },
    { x: 744, y: 740, text: "• Azure Policy restricts resource locations to India regions" },
  ],
});

// --------------------------------------------------------------------------- //
// 3. Inbound message sequence
// --------------------------------------------------------------------------- //
const inbound = sequence({
  width: 1640,
  step: 46,
  title: "Inbound WhatsApp message – end-to-end processing",
  subtitle: "No public webhook: ACS publishes to Event Grid, which delivers to Service Bus with its managed identity. Nothing is lost during spikes or restarts.",
  actors: [
    { label: ["Patient", "(WhatsApp)"], style: C.ext },
    { label: ["ACS Advanced", "Messaging"] },
    { label: ["Event Grid →", "Service Bus"] },
    { label: ["Worker", "(LangGraph)"], style: C.app },
    { label: ["Content Safety /", "Translator"], style: C.ai },
    { label: ["Azure OpenAI /", "AI Search"], style: C.ai },
    { label: ["PostgreSQL", "(RLS)"], style: C.data },
  ],
  messages: [
    { from: 0, to: 1, text: "message / button / list reply" },
    { from: 1, to: 2, text: "AdvancedMessageReceived event" },
    { from: 2, to: 3, text: "queued event (at-least-once)" },
    { from: 3, to: 6, text: "route by channel ID → tenant; lock conversation; de-duplicate; log" },
    { from: 3, to: 3, text: "STOP / START keywords → consent (instant opt-out)" },
    { from: 3, to: 3, text: "emergency keywords (ml/en/hi) → emergency reply + handover" },
    { from: 3, to: 4, text: "harm filters + Prompt Shields; detect language" },
    { from: 3, to: 3, text: "button/list payload or active flow → deterministic flow step" },
    { from: 3, to: 5, text: "free text → intent (gpt-5-mini, structured output)" },
    { from: 3, to: 5, text: "FAQ → hybrid search over hospital content → grounded answer (gpt-5)" },
    { from: 3, to: 6, text: "low confidence / no answer → status handover_pending" },
    { from: 3, to: 1, text: "reply (session message) via SDK, logged with status" },
    { from: 1, to: 0, text: "message delivered" },
    { from: 1, to: 2, text: "DeliveryStatusUpdated → delivery queue → message status" },
  ],
});

// --------------------------------------------------------------------------- //
// 4. LangGraph turn graph
// --------------------------------------------------------------------------- //
const graph = svg({
  width: 1500,
  height: 790,
  title: "Assistant turn graph (LangGraph)",
  subtitle: "Order guarantees policy: STOP first, emergencies before any AI call, safety before the LLM sees text, low confidence → human.",
  nodes: [
    { id: "start", x: 40, y: 120, w: 150, h: 54, title: "Inbound turn", style: C.ext },
    { id: "consent", x: 240, y: 120, w: 180, h: 54, title: "consent", sub: "STOP / START / opt-in", style: C.sec },
    { id: "emergency", x: 470, y: 120, w: 180, h: 54, title: "emergency", sub: "keywords per language", style: C.sec },
    { id: "safety", x: 700, y: 120, w: 180, h: 54, title: "safety", sub: "Content Safety + Shields", style: C.sec },
    { id: "language", x: 930, y: 120, w: 180, h: 54, title: "language", sub: "script / Translator" },
    { id: "router", x: 1160, y: 120, w: 180, h: 54, title: "router", sub: "payload, flow, keywords", style: C.app },
    { id: "flow", x: 1160, y: 300, w: 180, h: 70, title: "flow", sub: ["booking · manage ·", "availability · feedback"], style: C.app },
    { id: "menu", x: 1360, y: 300, w: 120, h: 70, title: "menu", sub: "main list", style: C.app },
    { id: "classify", x: 860, y: 300, w: 200, h: 70, title: "classify", sub: ["intent model", "(structured output)"], style: C.ai },
    { id: "faq", x: 560, y: 300, w: 200, h: 70, title: "faq (RAG)", sub: ["search + grounded", "answer model"], style: C.ai },
    { id: "handover", x: 860, y: 470, w: 200, h: 70, title: "handover", sub: ["queue for staff", "takeover screen"], style: C.flow },
    { id: "static", x: 560, y: 470, w: 200, h: 70, title: "static replies", sub: ["medical-advice refusal", "out of scope"], style: C.ext },
    { id: "end", x: 1160, y: 470, w: 180, h: 70, title: "send replies", sub: "Messenger (policy)", style: C.data },
  ],
  edges: [
    { from: "start", to: "consent" },
    { from: "consent", to: "emergency" },
    { from: "emergency", to: "safety" },
    { from: "safety", to: "language" },
    { from: "language", to: "router" },
    { from: "router", fs: "b", to: "flow", ts: "t", label: "payload / active flow", labelAt: [1250, 280] },
    { from: "router", fs: "r", to: "menu", ts: "t", via: [[1420, 147]], label: "menu" },
    { from: "router", fs: "b", to: "classify", ts: "t", fo: 0.2, to_o: 0.7, midY: 240, label: "free text", labelAt: [1100, 240] },
    { from: "flow", fs: "l", to: "classify", ts: "r", label: "fallthrough" },
    { from: "classify", fs: "l", to: "faq", ts: "r", label: "FAQ intents" },
    { from: "classify", fs: "b", to: "handover", ts: "t", label: "low confidence" },
    { from: "classify", fs: "b", to: "static", ts: "t", fo: 0.2, to_o: 0.8, midY: 430 },
    { from: "faq", fs: "l", to: "handover", ts: "b", to_o: 0.35, via: [[530, 335], [530, 580], [930, 580]], label: "no grounded answer", labelAt: [730, 580] },
    { from: "flow", fs: "b", to: "end", ts: "t" },
    { from: "safety", fs: "b", to: "handover", ts: "b", fo: 0.6, to_o: 0.65, via: [[808, 252], [500, 252], [500, 606], [990, 606]], dashed: true, label: "safety service down (fail closed)", labelAt: [700, 252] },
  ],
  texts: [
    { x: 40, y: 644, text: "Guardrails", bold: true, color: C.ink, size: 15 },
    { x: 40, y: 670, text: "• System prompts forbid medical advice, diagnosis, medication guidance and result interpretation; the intent model routes medical questions to a fixed refusal." },
    { x: 40, y: 692, text: "• FAQ answers use only retrieved hospital passages; the model must flag confidence – otherwise staff take over. Prompt text is never logged unless explicitly enabled." },
    { x: 40, y: 714, text: "• Interactive messages drive anything structured (booking, rescheduling, feedback); the LLM is used only to understand free text and answer FAQs." },
    { x: 40, y: 736, text: "• Self-harm signals produce a crisis helpline reply and immediate handover; emergencies reply with 108 + casualty directions in the patient's language." },
  ],
});

// --------------------------------------------------------------------------- //
// 5. Report delivery sequence
// --------------------------------------------------------------------------- //
const reports = sequence({
  width: 1640,
  step: 44,
  title: "Secure report delivery – no PDFs in chat",
  subtitle: "Verified, expiring link (48 h default) → OTP or date of birth → 5-minute user-delegation SAS. Every step written to the access audit log.",
  actors: [
    { label: ["LIS / HIS"], style: C.ext },
    { label: ["Data Factory /", "Blob (imports)"], style: C.flow },
    { label: ["Worker / jobs", "(HIS sync)"], style: C.app },
    { label: ["PostgreSQL"], style: C.data },
    { label: ["ACS WhatsApp", "(+ SMS fallback)"] },
    { label: ["Patient /", "family phone"], style: C.ext },
    { label: ["Report portal", "(API :8000)"], style: C.app },
    { label: ["Blob (reports)", "private"], style: C.data },
  ],
  messages: [
    { from: 0, to: 1, text: "report marked final (export / API / FHIR)" },
    { from: 1, to: 2, text: "BlobCreated event or 5-min schedule → sync" },
    { from: 2, to: 7, text: "copy PDF to private reports container" },
    { from: 2, to: 3, text: "upsert patient, create report, token hash + expiry" },
    { from: 2, to: 4, text: "report_ready template to registered numbers only" },
    { from: 4, to: 5, text: "\"Your report is ready\" + secure link" },
    { from: 5, to: 6, text: "open link (/r/<hospital>/<token>)" },
    { from: 6, to: 4, text: "OTP via WhatsApp authentication template (SMS fallback)" },
    { from: 5, to: 6, text: "enter OTP or date of birth (lockout after 5 failures)" },
    { from: 6, to: 3, text: "audit: link_opened, verify_ok / failed, downloaded" },
    { from: 6, to: 7, text: "mint 5-minute read-only user-delegation SAS" },
    { from: 6, to: 5, text: "redirect → PDF opens (no AI interpretation)" },
  ],
});

// --------------------------------------------------------------------------- //
// 6. Ports and adapters (portability)
// --------------------------------------------------------------------------- //
function portCards() {
  const rows = [
    ["Messaging channel", "ACS WhatsApp", "Meta Cloud API · console · plugin"],
    ["Queue", "Service Bus", "Redis Streams · in-memory"],
    ["LLM", "Azure OpenAI (Foundry)", "Claude in Foundry · OpenAI-compatible"],
    ["Knowledge (RAG)", "Azure AI Search", "pgvector · Postgres full-text"],
    ["Object storage", "Blob (user-delegation SAS)", "S3 / MinIO · local"],
    ["Email", "ACS Email", "SMTP (SES, SendGrid…)"],
    ["SMS / OTP", "ACS SMS", "MSG91 (DLT)"],
    ["Language", "AI Translator", "Unicode-script heuristic"],
    ["Safety", "Content Safety + Shields", "none (dev)"],
    ["HIS", "CSV via Data Factory", "REST API · FHIR R4"],
    ["Dashboard", "Power BI Embedded", "Grafana · built-in tiles"],
    ["Scheduler", "Logic Apps / Durable Fn", "Kubernetes CronJobs"],
    ["Identity", "Entra Workload ID", "IRSA / GKE WI / keys"],
  ];
  const nodes = [];
  const left = rows.slice(0, 7);
  const right = rows.slice(7);
  const card = (r, x, y, i) => {
    nodes.push({ id: `p${i}`, x, y, w: 200, h: 56, title: r[0], style: C.app });
    nodes.push({ id: `a${i}`, x: x + 210, y, w: 230, h: 56, title: r[1], sub: "Azure (default)", style: C.azure });
    nodes.push({ id: `o${i}`, x: x + 450, y, w: 300, h: 56, title: r[2], sub: "portable / alternative", style: C.ext });
  };
  left.forEach((r, i) => card(r, 30, 150 + i * 72, i));
  right.forEach((r, i) => card(r, 870, 150 + i * 72, i + 7));
  return nodes;
}

const ports = svg({
  width: 1640,
  height: 690,
  title: "Ports & adapters – one YAML line per provider swap",
  subtitle: "Domain services and the LangGraph agent depend only on abstract ports; cloud SDKs load lazily from the plugin registry (provider: <name> or module:Class).",
  nodes: portCards(),
  texts: [
    { x: 30, y: 130, text: "Port", bold: true, color: C.ink, size: 13 },
    { x: 240, y: 130, text: "Azure adapter", bold: true, color: C.ink, size: 13 },
    { x: 480, y: 130, text: "Alternatives shipped", bold: true, color: C.ink, size: 13 },
    { x: 870, y: 130, text: "Port", bold: true, color: C.ink, size: 13 },
    { x: 1080, y: 130, text: "Azure adapter", bold: true, color: C.ink, size: 13 },
    { x: 1320, y: 130, text: "Alternatives shipped", bold: true, color: C.ink, size: 13 },
    { x: 870, y: 640, text: "Kubernetes (Helm) runs unchanged on AKS, EKS, GKE or on-prem; Postgres is any managed PostgreSQL.", color: C.ink, size: 13 },
    { x: 870, y: 662, text: "Example: messaging.provider: meta_cloud   ·   storage.provider: s3   ·   llm.profiles.reply.provider: openai_compatible", color: C.muted, size: 12 },
  ],
});

module.exports = {
  diagrams: {
    "01-solution-architecture": solution,
    "02-network-security": network,
    "03-inbound-message-flow": inbound,
    "04-assistant-graph": graph,
    "05-report-delivery": reports,
    "06-ports-and-adapters": ports,
  },
};
