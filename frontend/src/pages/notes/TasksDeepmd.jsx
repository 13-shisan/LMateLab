// src/pages/notes/TasksDeepmd.jsx
import React from "react";
import TasksLayout from "./TasksLayout";

export default function TasksDeepmd() {
  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksall"
      currentTaskType="deepmd"
      showTaskTypeSelector={true}
    >
      <h2 style={{ marginBottom: 8 }}>DeepMD 任务总览</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里可以展示 DeepMD 训练与模拟相关任务。
      </p>
    </TasksLayout>
  );
}
