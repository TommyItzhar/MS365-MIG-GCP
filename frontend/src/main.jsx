import React from "react";
import { createRoot } from "react-dom/client";
import MigrationPlatform from "./MigrationPlatform.jsx";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <MigrationPlatform />
  </React.StrictMode>,
);
