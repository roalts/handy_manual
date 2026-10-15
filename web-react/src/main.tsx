import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AnnounceProvider } from "./app/announce";
import { App } from "./app/App";
import { queryClient } from "./app/query";
import { rewritePathRoute } from "./lib/router";
import "./index.css";

rewritePathRoute();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AnnounceProvider>
        <App />
      </AnnounceProvider>
    </QueryClientProvider>
  </StrictMode>,
);
