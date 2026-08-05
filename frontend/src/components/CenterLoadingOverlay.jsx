import React from "react";

export default function CenterLoadingOverlay({ text, defaultText = "正在加载，请不要重复和刷新界面" }) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(255,255,255,0.55)",
        backdropFilter: "blur(2px)",
        zIndex: 5,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            border: "4px solid rgba(209,213,219,1)",
            borderTopColor: "rgba(37,99,235,1)",
            animation: "spin 1s linear infinite",
          }}
        />
        <div style={{ fontSize: 13, color: "#374151", fontWeight: 700 }}>
          {text || defaultText}
        </div>
        <style>{`
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    </div>
  );
}
