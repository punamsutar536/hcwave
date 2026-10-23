/**
 * Management dashboard: Power BI Embedded, Azure Managed Grafana or the
 * built-in KPI tiles, depending on the backend's dashboard provider.
 */
import { useEffect, useRef, useState } from "react";
import { models, service, factories } from "powerbi-client";
import { api } from "../api";
import type { EmbedConfig, Summary } from "../types";

const powerbi = new service.Service(factories.hpmFactory, factories.wpmpFactory, factories.routerFactory);

function format(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "number" && value > 0 && value < 1) return `${Math.round(value * 100)}%`;
  if (Array.isArray(value)) return value.map((v) => `${(v as { category: string }).category} (${(v as { n: number }).n})`).join(", ") || "–";
  return String(value);
}

function Tiles() {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<Summary | null>(null);
  useEffect(() => {
    void api.summary(days).then(setSummary);
  }, [days]);
  if (!summary) return <p className="muted">Loading…</p>;
  const { period: _period, ...areas } = summary;
  return (
    <>
      <div className="toolbar">
        {[7, 30, 90].map((d) => (
          <button key={d} className={d === days ? "active" : ""} onClick={() => setDays(d)}>
            {d} days
          </button>
        ))}
      </div>
      {Object.entries(areas).map(([area, metrics]) => (
        <section key={area}>
          <h2>{area}</h2>
          <div className="tiles">
            {Object.entries(metrics).map(([name, value]) => (
              <div key={name} className="tile">
                <span className="muted">{name.replaceAll("_", " ")}</span>
                <strong>{format(value)}</strong>
              </div>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

export function Dashboard() {
  const [embed, setEmbed] = useState<EmbedConfig | null>(null);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api.embed().then(setEmbed);
  }, []);

  useEffect(() => {
    if (embed?.type !== "powerbi" || !container.current) return;
    powerbi.embed(container.current, {
      type: "report",
      id: embed.report_id,
      embedUrl: embed.embed_url,
      accessToken: embed.access_token,
      tokenType: models.TokenType.Embed,
      settings: { panes: { filters: { visible: false } } },
    });
    return () => powerbi.reset(container.current!);
  }, [embed]);

  if (!embed) return <p className="muted">Loading…</p>;
  if (embed.type === "powerbi") return <div ref={container} className="embed" />;
  if (embed.type === "grafana") return <iframe className="embed" src={embed.url} title="Dashboard" />;
  return <Tiles />;
}
