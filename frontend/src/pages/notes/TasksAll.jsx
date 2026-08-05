// src/pages/notes/TasksAll.jsx
import React from "react";
import TasksLayout from "./TasksLayout";

export default function TasksAll() {
  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksall"
      currentTaskType="all"
      showTaskTypeSelector={true}
    >
      <h2 style={{ marginBottom: 8 }}>全部任务总览</h2>
      <p style={{ marginTop: 8, color: "#4b5563", fontSize: 14 }}>
        这里是“全部任务总览”的主页面。
        以后可以在这里放所有软件类型任务的统一统计视图，比如：
        汇总曲线、饼图、最近任务列表等。
      </p>
    </TasksLayout>
  );
}
