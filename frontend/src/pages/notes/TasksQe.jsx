// src/pages/notes/TasksQe.jsx
import React from "react";
import TasksLayout from "./TasksLayout";

export default function TasksQe() {
  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksall"
      currentTaskType="qe"
      showTaskTypeSelector={true}
    >
      <h2 style={{ marginBottom: 8 }}>Quantum ESPRESSO 任务总览</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里是 QE 任务的专用统计视图。
      </p>
    </TasksLayout>
  );
}
