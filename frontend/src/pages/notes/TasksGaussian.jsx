// src/pages/notes/TasksGaussian.jsx
import React from "react";
import TasksLayout from "./TasksLayout";

export default function TasksGaussian() {
  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksall"
      currentTaskType="gaussian"
      showTaskTypeSelector={true}
    >
      <h2 style={{ marginBottom: 8 }}>Gaussian 任务总览</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里可以放 Gaussian 任务的统计信息。
      </p>
    </TasksLayout>
  );
}
