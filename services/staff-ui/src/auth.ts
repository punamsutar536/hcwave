/**
 * Microsoft Entra ID sign-in (MSAL). Tokens are acquired silently for the
 * staff API scope and attached as bearer tokens by the API client.
 */
import { PublicClientApplication, InteractionRequiredAuthError } from "@azure/msal-browser";
import { config } from "./config";

export const msal =
  config.authMode === "msal"
    ? new PublicClientApplication({
        auth: {
          clientId: config.clientId,
          authority: `https://login.microsoftonline.com/${config.tenantId}`,
          redirectUri: window.location.origin,
        },
        // Session storage: tokens are cleared when the browser tab closes
        // (shared front-desk computers).
        cache: { cacheLocation: "sessionStorage" },
      })
    : null;

/** Returns a bearer token for the staff API, or null when auth is disabled. */
export async function getAccessToken(): Promise<string | null> {
  if (!msal) return null;
  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
  if (!account) {
    await msal.loginRedirect({ scopes: [config.apiScope] });
    return null;
  }
  try {
    const result = await msal.acquireTokenSilent({ scopes: [config.apiScope], account });
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await msal.acquireTokenRedirect({ scopes: [config.apiScope], account });
    }
    throw error;
  }
}
