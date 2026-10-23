/** Shapes returned by the staff API (see backend api/routes/staff.py). */

export interface Me {
  name: string;
  email: string;
  roles: string[];
  hospitals: { id: string; name: string }[];
}

export interface Conversation {
  id: string;
  phone: string;
  patient_name: string | null;
  status: "bot" | "handover_pending" | "human";
  handover_reason: string | null;
  language: string;
  assigned_staff_id: string | null;
  last_inbound_at: string | null;
  handover_at: string | null;
  session_open: boolean;
}

export interface ChatMessage {
  id: string;
  direction: "inbound" | "outbound";
  sender: "patient" | "bot" | "staff" | "system";
  kind: string;
  body: string;
  status: string;
  intent: string | null;
  created_at: string;
}

export interface Ticket {
  id: string;
  category: string;
  severity: string;
  summary: string;
  status: string;
  patient_name: string | null;
  patient_phone: string | null;
  due_at: string;
  overdue: boolean;
  created_at: string;
  resolution_note: string | null;
}

export interface Appointment {
  id: string;
  start_at: string;
  status: string;
  channel: string;
  patient_name: string;
  patient_phone: string;
  doctor: string;
  department: string;
}

export type EmbedConfig =
  | { type: "builtin"; summary_url: string }
  | { type: "grafana"; url: string }
  | { type: "powerbi"; report_id: string; embed_url: string; access_token: string; expiration: string };

export type Summary = Record<string, Record<string, unknown>>;
