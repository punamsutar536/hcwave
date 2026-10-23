/** Entry point: completes any MSAL redirect, then renders the app. */
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { msal } from "./auth";
import "./styles.css";

async function start(): Promise<void> {
  if (msal) {
    await msal.initialize();
    const result = await msal.handleRedirectPromise();
    if (result?.account) msal.setActiveAccount(result.account);
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

void start();
