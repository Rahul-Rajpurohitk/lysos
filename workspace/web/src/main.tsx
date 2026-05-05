/// <reference types="vite/client" />
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import App from "./App";
import Workbench from "./workbench/Workbench";
import { WorkbenchV3 } from "./workbench/v3/WorkbenchV3";
import "./styles.css";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

function V3Wrapper() {
  return <WorkbenchV3 apiBase={API_BASE} />;
}

function Shell() {
  return (
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        {/* Default: v3 agentic workbench. v2 + legacy designer accessible
            at /v2 + /legacy for the cutover window. */}
        <Route path="/" element={<V3Wrapper />} />
        <Route path="/workbench" element={<V3Wrapper />} />
        <Route path="/v2" element={<Workbench />} />
        <Route path="/legacy" element={<App />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Shell />
  </React.StrictMode>
);
