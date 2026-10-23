/** Front desk: today's appointments and WhatsApp consent capture at registration. */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Appointment } from "../types";

export function FrontDesk() {
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [form, setForm] = useState({ phone: "", full_name: "", note: "" });
  const [result, setResult] = useState("");

  useEffect(() => {
    void api.appointments(day).then(setAppointments);
  }, [day]);

  const capture = async (optIn: boolean) => {
    try {
      const response = await api.consent({ ...form, opt_in: optIn });
      setResult(`Saved: ${response.status.replace("_", " ")}`);
      setForm({ phone: "", full_name: "", note: "" });
    } catch (e) {
      setResult((e as Error).message);
    }
  };

  return (
    <div className="split">
      <section>
        <div className="toolbar">
          <label>
            Date <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
        </div>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Patient</th>
              <th>Doctor</th>
              <th>Status</th>
              <th>Channel</th>
            </tr>
          </thead>
          <tbody>
            {appointments.map((a) => (
              <tr key={a.id}>
                <td>{new Date(a.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                <td>
                  {a.patient_name}
                  <br />
                  <small className="muted">{a.patient_phone}</small>
                </td>
                <td>
                  {a.doctor}
                  <br />
                  <small className="muted">{a.department}</small>
                </td>
                <td>{a.status.replace("_", " ")}</td>
                <td>{a.channel}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card">
        <h2>WhatsApp consent</h2>
        <p className="muted">Record the patient's consent given on the registration form (DPDP).</p>
        <label>
          Mobile number
          <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} inputMode="tel" />
        </label>
        <label>
          Patient name (new patients)
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </label>
        <label>
          Note / form reference
          <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </label>
        <div className="actions">
          <button disabled={!form.phone} onClick={() => void capture(true)}>
            Consent given
          </button>
          <button disabled={!form.phone} onClick={() => void capture(false)}>
            Consent refused
          </button>
        </div>
        {result && <p>{result}</p>}
      </section>
    </div>
  );
}
