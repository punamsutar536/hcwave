/**
 * Thin typed client for the staff API. Adds the bearer token and the
 * X-Hospital-Id header (staff may belong to more than one hospital).
 */
import { getAccessToken } from "./auth";
import { config } from "./config";
import type { Appointment, ChatMessage, Conversation, EmbedConfig, Me, Summary, Ticket } from "./types";

let hospitalId = "";

/** Selects the hospital all subsequent calls act for. */
export function setHospital(id: string): void {
  hospitalId = id;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (hospitalId) headers.set("X-Hospital-Id", hospitalId);
  const response = await fetch(`${config.apiBaseUrl}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("/staff/me"),
  conversations: (state: "waiting" | "mine" | "all") => request<Conversation[]>(`/staff/conversations?state=${state}`),
  messages: (id: string) => request<ChatMessage[]>(`/staff/conversations/${id}/messages`),
  takeover: (id: string) => request<Conversation>(`/staff/conversations/${id}/takeover`, { method: "POST" }),
  reply: (id: string, text: string) =>
    request<{ status: string; error: string | null }>(`/staff/conversations/${id}/reply`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  release: (id: string) => request<Conversation>(`/staff/conversations/${id}/release`, { method: "POST" }),
  tickets: (state: "open" | "all") => request<Ticket[]>(`/staff/tickets?state=${state}`),
  updateTicket: (id: string, body: { status?: string; resolution_note?: string; assign_to_me?: boolean }) =>
    request<{ status: string }>(`/staff/tickets/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  appointments: (day?: string) => request<Appointment[]>(`/staff/appointments${day ? `?day=${day}` : ""}`),
  consent: (body: { phone: string; full_name?: string; opt_in: boolean; note: string }) =>
    request<{ status: string }>("/staff/consent", { method: "POST", body: JSON.stringify(body) }),
  summary: (days: number) => request<Summary>(`/staff/dashboard/summary?days=${days}`),
  embed: () => request<EmbedConfig>("/staff/dashboard/embed"),
};
