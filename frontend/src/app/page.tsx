"use client";

import MeguribiDashboardPreview from "../components/MeguribiDashboardPreview";

export default function Page() {
  return (
    <>
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          zIndex: 9999,
          background: "red",
          color: "white",
          padding: "4px 8px",
          fontSize: "12px",
        }}
      >
        DEBUG: Meguribi PREVIEW v1
      </div>
      <MeguribiDashboardPreview />
    </>
  );
}
