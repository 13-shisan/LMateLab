// src/pages/notes/TasksCp2k.jsx
import React from "react";
import TasksLayout from "./TasksLayout";

export default function TasksCp2k() {
  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksall"
      currentTaskType="cp2k"
      showTaskTypeSelector={true}
    >
      <h2 style={{ marginBottom: 8 }}>CP2K 任务总览</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里可以展示 CP2K 分子动力学与量子化学任务的统计信息。
      </p>
    </TasksLayout>
  );
}
