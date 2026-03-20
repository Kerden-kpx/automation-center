import { ConfigProvider, theme } from "antd";
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

if (import.meta.env.DEV) {
  const apiBase = import.meta.env.VITE_API_BASE_URL || "";
  const sendDevLog = (payload: { level: string; message: string; stack?: string; context?: any }) => {
    try {
      fetch(`${apiBase}/api/dev/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => undefined);
    } catch {
      // ignore
    }
  };

  window.addEventListener("error", (event) => {
    const err = event.error as Error | undefined;
    sendDevLog({
      level: "error",
      message: event.message || err?.message || "Unknown error",
      stack: err?.stack,
      context: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      },
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason as Error | undefined;
    sendDevLog({
      level: "error",
      message: reason?.message || String(event.reason || "Unhandled rejection"),
      stack: reason?.stack,
    });
  });
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);


