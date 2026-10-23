/**
 * Shell: loads the signed-in user, lets them pick a hospital, and shows the
 * screens their roles allow.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { api, setHospital } from "./api";
import type { Me } from "./types";
import { Inbox } from "./pages/Inbox";
import { Tickets } from "./pages/Tickets";
import { FrontDesk } from "./pages/FrontDesk";

// The dashboard pulls in the Power BI client; load it only when opened.
const Dashboard = lazy(() => import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })));

type Tab = "inbox" | "frontdesk" | "tickets" | "dashboard";

const TAB_ROLES: Record<Tab, string[]> = {
  inbox: ["front_office", "patient_relations"],
  frontdesk: ["front_office", "patient_relations"],
  tickets: ["patient_relations"],
  dashboard: ["unit_head", "patient_relations"],
};

const TAB_LABELS: Record<Tab, string> = {
  inbox: "WhatsApp inbox",
  frontdesk: "Front desk",
  tickets: "Complaints",
  dashboard: "Dashboard",
};

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [hospital, setHospitalId] = useState("");
  const [tab, setTab] = useState<Tab>("inbox");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .me()
      .then((user) => {
        setMe(user);
        const first = user.hospitals[0]?.id ?? "";
        setHospital(first);
        setHospitalId(first);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <main className="center">Sign-in failed: {error}</main>;
  if (!me) return <main className="center">Loading…</main>;

  const allowed = (t: Tab) => me.roles.includes("admin") || TAB_ROLES[t].some((r) => me.roles.includes(r));
  const tabs = (Object.keys(TAB_LABELS) as Tab[]).filter(allowed);
  const current = tabs.includes(tab) ? tab : tabs[0];

  return (
    <div className="shell">
      <header>
        <strong>Hospital AI</strong>
        <nav>
          {tabs.map((t) => (
            <button key={t} className={t === current ? "active" : ""} onClick={() => setTab(t)}>
              {TAB_LABELS[t]}
            </button>
          ))}
        </nav>
        <select
          aria-label="Hospital"
          value={hospital}
          onChange={(e) => {
            setHospital(e.target.value);
            setHospitalId(e.target.value);
          }}
        >
          {me.hospitals.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
        <span className="muted">{me.name}</span>
      </header>
      {/* Remount pages when the hospital changes so they reload their data. */}
      <main key={hospital}>
        {current === "inbox" && <Inbox />}
        {current === "frontdesk" && <FrontDesk />}
        {current === "tickets" && <Tickets />}
        {current === "dashboard" && (
          <Suspense fallback={<p className="muted">Loading…</p>}>
            <Dashboard />
          </Suspense>
        )}
        {!current && <p>Your account has no staff role. Ask the administrator to assign one.</p>}
      </main>
    </div>
  );
}
