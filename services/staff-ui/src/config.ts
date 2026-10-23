/**
 * Runtime configuration injected by /config.js.
 *
 * The same image runs in every environment; values come from container
 * environment variables rendered into config.js at start-up.
 */
export interface RuntimeConfig {
  /** Base URL of the backend public API ("" = same origin). */
  apiBaseUrl: string;
  /** "msal" signs staff in with Microsoft Entra ID; "none" is for local dev. */
  authMode: "msal" | "none";
  /** Entra app registration (SPA) client ID. */
  clientId: string;
  /** Entra tenant ID. */
  tenantId: string;
  /** Scope exposed by the staff API app registration, e.g. api://hcwave-staff-api/access. */
  apiScope: string;
  /** Inbox refresh interval. */
  pollSeconds: number;
}

declare global {
  interface Window {
    __HCWAVE_CONFIG__?: Partial<RuntimeConfig>;
  }
}

export const config: RuntimeConfig = {
  apiBaseUrl: "",
  authMode: "none",
  clientId: "",
  tenantId: "",
  apiScope: "",
  pollSeconds: 5,
  ...window.__HCWAVE_CONFIG__,
};
