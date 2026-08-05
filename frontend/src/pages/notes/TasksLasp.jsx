// src/pages/notes/TasksLasp.jsx
import React from "react";
import TasksLayout from "./TasksLayout";

export default function TasksLasp() {
  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksall"
      currentTaskType="lasp"
      showTaskTypeSelector={true}
    >
      <h2 style={{ marginBottom: 8 }}>LASP 任务总览</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里可以展示 LASP 结构搜索任务的进度和统计。
      </p>
    </TasksLayout>
  );
}
