import React from "react";
import DbLayout from "./DbLayout";

export default function GroupDatabase() {
  return (
    <DbLayout currentSubPath="/dashboard/db/group">
      <h2 style={{ marginBottom: 8 }}>全组数据库</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里放全组共享数据库入口（占位）。
      </p>
    </DbLayout>
  );
}
