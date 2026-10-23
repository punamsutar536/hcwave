/** Service-recovery tickets for the patient relations team. */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Ticket } from "../types";

export function Tickets() {
  const [state, setState] = useState<"open" | "all">("open");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = async () => setTickets(await api.tickets(state));
  useEffect(() => {
    void load();
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = async (id: string, status: string) => {
    await api.updateTicket(id, { status, resolution_note: notes[id], assign_to_me: true });
    await load();
  };

  return (
    <section>
      <div className="toolbar">
        <button className={state === "open" ? "active" : ""} onClick={() => setState("open")}>
          Open
        </button>
        <button className={state === "all" ? "active" : ""} onClick={() => setState("all")}>
          All
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Due</th>
            <th>Patient</th>
            <th>Category</th>
            <th>Summary</th>
            <th>Status</th>
            <th>Resolution</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((t) => (
            <tr key={t.id} className={t.overdue ? "overdue" : ""}>
              <td>{new Date(t.due_at).toLocaleString()}</td>
              <td>
                {t.patient_name}
                <br />
                {t.patient_phone && <a href={`tel:${t.patient_phone}`}>{t.patient_phone}</a>}
              </td>
              <td>
                {t.category.replace("_", " ")} <span className="badge">{t.severity}</span>
              </td>
              <td>{t.summary}</td>
              <td>{t.status.replace("_", " ")}</td>
              <td>
                <input
                  placeholder="Resolution note"
                  defaultValue={t.resolution_note ?? ""}
                  onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })}
                />
                <div className="actions">
                  <button onClick={() => void update(t.id, "in_progress")}>Working</button>
                  <button onClick={() => void update(t.id, "resolved")}>Resolved</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
