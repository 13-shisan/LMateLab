// src/pages/notes/TasksVasp.jsx
import React, { useEffect, useRef } from "react";
import TasksLayout from "./TasksLayout";
import api from "../../api/client";
import "./vasp.css";

import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  DoughnutController,
  ArcElement,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";
import zoomPlugin from "chartjs-plugin-zoom";

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  DoughnutController,
  ArcElement,
  Tooltip,
  Legend,
  Filler,
  zoomPlugin
);

export default function TasksVasp() {
  const taskCountChartRef = useRef(null);
  const taskStatusChartRef = useRef(null);
  const currentPageRef = useRef(1);
  const pageSize = 20;

  useEffect(() => {
    const ctx1 = document.getElementById("taskCountChart")?.getContext("2d");
    const ctx2 = document.getElementById("taskStatusChart")?.getContext("2d");

    // ---- Runtime(分钟) -> xhxmxxs ----
    function formatRuntime(rt) {
      if (!rt && rt !== 0) return "-";
      const num = Number(rt);
      if (Number.isNaN(num) || num < 0) return String(rt);

      const totalSeconds = Math.round(num * 60);
      if (totalSeconds < 60) return `${totalSeconds}s`;

      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;

      if (hours === 0) return `${minutes}m${seconds}s`;
      return `${hours}h${minutes}m${seconds}s`;
    }

    async function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
      }
      return new Promise((resolve, reject) => {
        try {
          const textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.style.position = "fixed";
          textarea.style.top = "-1000px";
          textarea.style.left = "-1000px";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          const ok = document.execCommand("copy");
          document.body.removeChild(textarea);
          ok ? resolve() : reject(new Error("execCommand failed"));
        } catch (err) {
          reject(err);
        }
      });
    }

    // ---- 解析 "张凯 and 吕海峰 no Failed" ----
    function buildKeywordParams(raw) {
      if (!raw) return {};
      const tokens = raw.trim().split(/\s+/).filter(Boolean);

      // 先看看整句有没有 'or'
      const hasOr = tokens.some((t) => t.toLowerCase() === "or");

      const must = [];
      const should = [];
      const not = [];

      // 初始模式：
      // - 如果出现了 "or"，就默认 OR 模式（避免第一个词误进 AND）
      // - 否则默认 AND 模式
      let mode = hasOr ? "should" : "must";

      for (let i = 0; i < tokens.length; i++) {
        const lower = tokens[i].toLowerCase();

        if (lower === "and") {
          mode = "must";
          continue;
        }
        if (lower === "or") {
          mode = "should";
          continue;
        }
        if (lower === "no" || lower === "not") {
          mode = "not";
          continue;
        }

        if (mode === "must") must.push(tokens[i]);
        else if (mode === "should") should.push(tokens[i]);
        else if (mode === "not") not.push(tokens[i]);
      }

      const params = {};
      if (must.length) params.kw_and = must.join(" ");
      if (should.length) params.kw_or = should.join(" ");
      if (not.length) params.kw_not = not.join(" ");
      return params;
    }

    // ===== 折线图 =====
    if (ctx1) {
      taskCountChartRef.current = new Chart(ctx1, {
        type: "line",
        data: {
          labels: ["加载中..."],
          datasets: [
            {
              label: "任务数量",
              data: [0],
              borderColor: "#3b82f6",
              backgroundColor: "rgba(59,130,246,.1)",
              tension: 0.3,
              fill: true,
              pointRadius: 4,
              pointHoverRadius: 5,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              type: "category",
              ticks: {
                autoSkip: true,
                maxTicksLimit: 10,
                maxRotation: 45,
                minRotation: 0,
              },
            },
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
            },
          },
          plugins: {
            legend: { display: false },
          },
        },
      });
    } else {
      console.warn("taskCountChart canvas not found");
    }

    // ===== 饼图 =====
    if (ctx2) {
      taskStatusChartRef.current = new Chart(ctx2, {
        type: "doughnut",
        data: {
          labels: [],
          datasets: [
            {
              data: [],
              backgroundColor: ["#10b981", "#ef4444", "#3b82f6", "#9ca3af"],
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "right" },
          },
        },
      });
    } else {
      console.warn("taskStatusChart canvas not found");
    }

    // ---------- 统计图 ----------
    async function loadCharts() {
      const sd = document.getElementById("startDate")?.value || "";
      const ed = document.getElementById("endDate")?.value || "";

      try {
        const resp = await api.get("/overall-stats", { params: { start: sd, end: ed } });
        const d = resp.data;

        const line = taskCountChartRef.current;
        const pie = taskStatusChartRef.current;
        if (!line || !pie) return;

        line.data.labels = d.daily_stats?.dates || [];
        line.data.datasets[0].data = d.daily_stats?.counts || [];
        line.update();

        pie.data.labels = Object.keys(d.status_stats || {});
        pie.data.datasets[0].data = Object.values(d.status_stats || {});
        pie.update();
      } catch (err) {
        console.error("统计加载失败:", err);
      }
    }

    // ---------- 列表 ----------
    async function loadTasks(page = 1) {
      const sd = document.getElementById("startDate")?.value || "";
      const ed = document.getElementById("endDate")?.value || "";
      const kwRaw = document.getElementById("keyword")?.value || "";
      const filterByDateCheckbox =
        document.getElementById("filterListByDate");
      const filterByDate = filterByDateCheckbox?.checked;

      const params = new URLSearchParams();
      params.set("page", page);
      params.set("page_size", pageSize);

      if (filterByDate) {
        if (sd) params.set("start", sd);
        if (ed) params.set("end", ed);
        params.set("ignore_date", "false");
      } else {
        params.set("ignore_date", "true");
      }

      const kwStruct = buildKeywordParams(kwRaw);
      Object.entries(kwStruct).forEach(([k, v]) => params.set(k, v));

      

      try {
        const resp = await api.get("/vasp-tasks", { params: Object.fromEntries(params.entries()) });
        const data = resp.data;

        currentPageRef.current = data.page || 1;
        const total = data.total || 0;
        const pageSizeNow = data.page_size || pageSize;

        const tbody = document.getElementById("taskTableBody");
        if (!tbody) return;

        if (!data.items || data.items.length === 0) {
          tbody.innerHTML = `
            <tr>
              <td colspan="8" class="px-6 py-4 text-center text-sm text-gray-500">
                暂无数据
              </td>
            </tr>
          `;
        } else {
          tbody.innerHTML = data.items
          .map((item) => {
            const user = item.user_cn || item.username || "-";
            const host = item.hostname || "-";
            const path = item.path || "-";
            const submit = item.submit_time || "-";
            const jobType = item.job_type || "-";
            const status = (item.status || "-").toString();

            const statusLower = status.toLowerCase();
            let statusClass = "status-badge status-queued";
            if (statusLower === "completed" || statusLower === "complete") {
              statusClass = "status-badge status-completed";
            } else if (statusLower === "failed" || statusLower === "error") {
              statusClass = "status-badge status-failed";
            } else if (statusLower === "running") {
              statusClass = "status-badge status-running";
            } else if (statusLower === "not started") {
              statusClass = "status-badge status-not-started";
            }

            const runtimeText = formatRuntime(item.runtime);
            const jobId = item.job_id || item.JobID || "";
            const safePath = (path || "").replace(/"/g, "&quot;");

            return `
              <tr>
                <td class="px-6 py-3 text-sm text-gray-900 whitespace-nowrap">${user}</td>
                <td class="px-6 py-3 text-sm text-gray-900 whitespace-nowrap">${host}</td>
                <td class="px-6 py-3 text-sm text-gray-900">
                  <div class="flex items-center space-x-1 max-w-[420px]">
                    <i class="fa-solid fa-folder text-blue-500 flex-shrink-0"></i>
                    <span class="truncate flex-1" title="${safePath}">${safePath}</span>
                    <button
                      class="copy-path-btn flex-shrink-0"
                      data-path="${safePath}"
                      title="复制路径"
                    >
                      <i class="fa-regular fa-copy text-gray-500"></i>
                    </button>
                  </div>
                </td>
                <td class="px-6 py-3 text-sm text-gray-900 whitespace-nowrap">${submit}</td>
                <td class="px-6 py-3 text-sm text-gray-900 whitespace-nowrap">${jobType}</td>
                <td class="px-6 py-3 text-sm whitespace-nowrap">
                  <span class="${statusClass}">${status}</span>
                </td>
                <td class="px-6 py-3 text-sm text-gray-900 whitespace-nowrap">${runtimeText}</td>
                <td class="px-6 py-3 text-sm text-blue-600 whitespace-nowrap">
                  <button
                    class="inline-flex items-center text-blue-600 hover:text-blue-800 detail-btn"
                    data-jobid="${jobId}"
                  >
                    <i class="fa-solid fa-circle-info mr-1"></i>
                    详情
                  </button>
                </td>
              </tr>
            `;
          })
          .join("");
        }

        // 详情按钮
        document
          .querySelectorAll("#taskTableBody .copy-path-btn")
          .forEach((btn) => {
            btn.addEventListener("click", async () => {
              const p = btn.getAttribute("data-path") || "";
              try {
                await copyText(p);
                console.log("已复制路径:", p);
              } catch (e) {
                console.error("复制失败:", e);
                alert("复制失败，可以手动选中路径复制。");
              }
            });
          });

        // 详情按钮（新增）
        document.querySelectorAll("#taskTableBody .detail-btn").forEach((btn) => {
          btn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();

            const jobId = btn.getAttribute("data-jobid") || "";
            if (!jobId) {
              console.warn("detail-btn missing jobId");
              return;
            }

            try {
              const resp = await api.get("/vasp-task-detail", { params: { job_id: jobId } });
              const detail = resp.data;
              openDetailModal(detail);
            } catch (err) {
              console.error("加载详情失败:", err);
            }
          });
        });

        // 底部“显示第 X-Y 条，共 Z 条”
        const from =
          total === 0 ? 0 : (currentPageRef.current - 1) * pageSizeNow + 1;
        const to =
          total === 0 ? 0 : Math.min(total, currentPageRef.current * pageSizeNow);

        const currentRangeSpan = document.getElementById("currentRange");
        const totalTasksSpan = document.getElementById("totalTasks");
        if (currentRangeSpan) {
          currentRangeSpan.textContent = total === 0 ? "0" : `${from}-${to}`;
        }
        if (totalTasksSpan) {
          totalTasksSpan.textContent = String(total);
        }

        // 分页
        const firstBtn = document.getElementById("firstPage");
        const lastBtn = document.getElementById("lastPage");
        const pageNumbersDiv = document.getElementById("pageNumbers");

        const totalPages = Math.max(1, Math.ceil(total / pageSizeNow));
        const current = currentPageRef.current;

        if (firstBtn) firstBtn.disabled = current <= 1;
        if (lastBtn) lastBtn.disabled = current >= totalPages;

        if (pageNumbersDiv) {
          const pages = [];
          const startPage = Math.max(1, current - 2);
          const endPage = Math.min(totalPages, current + 2);

          for (let p = startPage; p <= endPage; p++) {
            pages.push(`
              <button
                data-page="${p}"
                class="px-3 py-1 border rounded-md text-sm ${
                  p === current
                    ? "bg-blue-500 text-white border-blue-500"
                    : "bg-white hover:bg-gray-50"
                }"
              >
                ${p}
              </button>
            `);
          }

          pageNumbersDiv.innerHTML = pages.join("");
          pageNumbersDiv.querySelectorAll("button[data-page]").forEach((btn) => {
            btn.addEventListener("click", (e) => {
              const p = parseInt(
                e.currentTarget.getAttribute("data-page"),
                10
              );
              loadTasks(p);
            });
          });
        }
      } catch (err) {
        console.error("任务列表加载失败:", err);
      }
    }

    const tbody = document.getElementById("taskTableBody");
    if (tbody) {
      tbody.addEventListener("click", async (e) => {
        const detailBtn = e.target.closest(".detail-btn");
        if (detailBtn) {
          e.preventDefault();

          const jobId = detailBtn.getAttribute("data-jobid") || "";
          if (!jobId) return;

          const resp = await api.get("/vasp-task-detail", { params: { job_id: jobId } });
          const detail = resp.data;
          openDetailModal(detail);
          return;
        }

        const copyBtn = e.target.closest(".copy-path-btn");
        if (copyBtn) {
          e.preventDefault();

          const p = copyBtn.getAttribute("data-path") || "";
          try {
            await copyText(p);
          } catch (err) {
            alert("复制失败，可以手动选中路径复制。");
          }
        }
      });
    }

    // ---------- 详情模态框 ----------
    function openDetailModal(t) {
      const modal = document.getElementById("taskDetailModal");
      const title = document.getElementById("detailTitle");
      const basicBox = document.getElementById("detailBasic");
      const pathBox = document.getElementById("detailPath");
      const paramBox = document.getElementById("detailParams");
      const resultBox = document.getElementById("detailResults");
      const extraBox = document.getElementById("detailExtra");

      if (!modal) return;

      const jobId = t.JobID || t.job_id || "";
      const user = t.User || t.user_cn || t.Username || t.username || "";
      const host = t.Hostname || t.hostname || "";
      const jobType = t.JobType || t.job_type || "";
      const status = t.Status || t.status || "";
      const submit = t.SubmitTime || t.submit_time || "";
      const endTime = t.EndTime || t.end_time || "";
      const runtime = formatRuntime(t.Runtime || t.runtime);
      const path = t.Path || t.path || "";

      if (title) title.textContent = `任务详情 - ${host}_${jobId}`;

      if (basicBox) {
        basicBox.innerHTML = `
          <div class="detail-grid">
            <div class="detail-item"><div class="detail-label">任务ID</div><div class="detail-value">${jobId || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">服务器</div><div class="detail-value">${host || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">状态</div><div class="detail-value">${status || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">结束时间</div><div class="detail-value">${endTime || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">用户</div><div class="detail-value">${user || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">任务类型</div><div class="detail-value">${jobType || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">提交时间</div><div class="detail-value">${submit || "N/A"}</div></div>
            <div class="detail-item"><div class="detail-label">运行时间</div><div class="detail-value">${runtime || "N/A"}</div></div>
          </div>
        `;
      }

      if (pathBox) {
        pathBox.innerHTML = `
          <div class="detail-item">
            <div class="detail-label">路径</div>
            <div class="detail-value">${path || "N/A"}</div>
          </div>
        `;
      }

      if (paramBox) {
        const rows = [
          ["结构", t.Structure],
          ["KPOINTS", t.KPOINTS],
          ["NumCores", t.NumCores],
          ["ENCUT", t.ENCUT],
          ["EDIFF", t.EDIFF],
          ["EDIFFG", t.EDIFFG],
          ["ISPIN", t.ISPIN],
          ["ISMEAR", t.ISMEAR],
          ["ALGO", t.ALGO],
          ["ISIF", t.ISIF],
          ["IBRION", t.IBRION],
          ["NSW", t.NSW],
          ["POTIM", t.POTIM],
        ];
        paramBox.innerHTML = `
          <div class="detail-grid">
            ${rows
              .map(
                ([label, value]) => `
              <div class="detail-item">
                <div class="detail-label">${label}</div>
                <div class="detail-value">${value ?? "N/A"}</div>
              </div>`
              )
              .join("")}
          </div>
        `;
      }

      if (resultBox) {
        const rows = [
          ["TotalEnergy", t.TotalEnergy],
          ["Fermi Level", t.E_fermi],
          ["Vacuum Level", t.E_vac],
          ["Gap", t.E_Gap],
          ["Gap_up", t.E_Gap_up],
          ["Gap_down", t.E_Gap_down],
          ["VBM", t.VBM],
          ["VBM_up", t.VBM_up],
          ["VBM_down", t.VBM_down],
          ["CBM", t.CBM],
          ["CBM_up", t.CBM_up],
          ["CBM_down", t.CBM_down],
        ];
        resultBox.innerHTML = `
          <div class="detail-grid">
            ${rows
              .map(
                ([label, value]) => `
              <div class="detail-item">
                <div class="detail-label">${label}</div>
                <div class="detail-value">${value ?? "N/A"}</div>
              </div>`
              )
              .join("")}
          </div>
        `;
      }

      if (extraBox) {
        const rows = [
          ["C_MOLAR", t.C_MOLAR],
          ["EB_K", t.EB_K],
          ["IDIPOL", t.IDIPOL],
          ["LDIPOL", t.LDIPOL],
          ["LAECHG", t.LAECHG],
          ["LELF", t.LELF],
          ["LOPTICS", t.LOPTICS],
          ["LORBIT", t.LORBIT],
          ["LREAL", t.LREAL],
          ["LSOL", t.LSOL],
          ["LVHAR", t.LVHAR],
          ["LVTOT", t.LVTOT],
          ["LWAVE", t.LWAVE],
          ["MAGMOM", t.MAGMOM],
          ["NEDOS", t.NEDOS],
          ["NFREE", t.NFREE],
          ["NPAR", t.NPAR],
          ["R_ION", t.R_ION],
          ["SIGMA", t.SIGMA],
          ["ele_set", t.ele_set],
        ];
        extraBox.innerHTML = `
          <div class="detail-grid">
            ${rows
              .map(
                ([label, value]) => `
              <div class="detail-item">
                <div class="detail-label">${label}</div>
                <div class="detail-value">${value ?? "N/A"}</div>
              </div>`
              )
              .join("")}
          </div>
        `;
      }

      modal.classList.remove("hidden");
    }

    function closeDetailModal() {
      const modal = document.getElementById("taskDetailModal");
      if (modal) modal.classList.add("hidden");
    }

    const closeBtn = document.getElementById("closeDetailModal");
    const closeX = document.getElementById("detailModalCloseX");
    if (closeBtn) closeBtn.addEventListener("click", closeDetailModal);
    if (closeX) closeX.addEventListener("click", closeDetailModal);

    // 初次加载
    loadCharts();
    loadTasks(1);

    // 筛选按钮
    const filterBtn = document.getElementById("filterButton");
    if (filterBtn) {
      filterBtn.addEventListener("click", () => {
        loadCharts();
        loadTasks(1);
      });
    }

    // 首页 / 尾页
    const firstBtn = document.getElementById("firstPage");
    const lastBtn = document.getElementById("lastPage");

    if (firstBtn) {
      firstBtn.addEventListener("click", () => {
        loadTasks(1);
      });
    }
    if (lastBtn) {
      lastBtn.addEventListener("click", () => {
        const totalTasksSpan = document.getElementById("totalTasks");
        const total =
          parseInt(totalTasksSpan?.textContent || "0", 10) || 0;
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        loadTasks(totalPages);
      });
    }

    return () => {
      taskCountChartRef.current?.destroy();
      taskStatusChartRef.current?.destroy();
    };
  }, []);

  return (
    <TasksLayout
      currentSubPath="/dashboard/notes/tasksvasp"
      currentTaskType="vasp"
      showTaskTypeSelector={true}
    >
      <div className="min-h-screen" style={{ background: "transparent" }}>
        <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {/* ===== 数据筛选 ===== */}
          <div id="filterCard" className="glass-card p-6 mb-6 overflow-visible">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between">
              <h2 className="text-lg font-medium text-gray-900 mb-4 md:mb-0">
                数据筛选
              </h2>
              <div className="flex flex-col sm:flex-row sm:flex-wrap space-y-4 sm:space-y-0 sm:gap-x-4 relative">
                <div className="w-40 sm:w-48">
                  <label
                    htmlFor="startDate"
                    className="block text-sm font-medium text-gray-700 mb-1"
                  >
                    开始日期
                  </label>
                  <input
                    type="date"
                    id="startDate"
                    className="filter-input date-input"
                  />
                </div>
                <div className="w-40 sm:w-48">
                  <label
                    htmlFor="endDate"
                    className="block text-sm font-medium text-gray-700 mb-1"
                  >
                    结束日期
                  </label>
                  <input
                    type="date"
                    id="endDate"
                    className="filter-input date-input"
                  />
                </div>

                <div className="flex flex-col sm:flex-row sm:items-start gap-3">
                  <div className="w-44 sm:w-60">
                    <label
                      htmlFor="keyword"
                      className="block text-sm font-medium text-gray-700 mb-1"
                    >
                      关键词
                    </label>
                    <input
                      type="text"
                      id="keyword"
                      className="filter-input"
                      placeholder="支持 and / or / no 组合，例如：Dell and 吴 no Failed"
                    />
                  </div>

                  <button
                    type="button"
                    id="filterButton"
                    className="self-start mt-2 sm:mt-[26px] h-[38px] inline-flex items-center px-4 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                  >
                    <i className="fas fa-filter mr-2" />
                    筛选
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* ===== 图表 ===== */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <div className="glass-card p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">
                每日任务提交数量
              </h3>
              <div className="chart-container">
                <canvas id="taskCountChart" />
              </div>
            </div>

            <div className="glass-card p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">
                任务状态分布
              </h3>
              <div className="chart-container">
                <canvas id="taskStatusChart" />
              </div>
            </div>
          </div>

          {/* ===== 任务列表 ===== */}
          <div
            id="userTasksTable"
            className="glass-card overflow-hidden lg:col-span-2"
          >
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <h3 className="text-lg font-medium text-gray-900">任务列表</h3>
                <label className="inline-flex items-center text-sm text-gray-700">
                  <input
                    type="checkbox"
                    id="filterListByDate"
                    className="mr-2 h-4 w-4 text-blue-600 border-gray-300 rounded"
                  />
                  按日期过滤列表
                </label>
              </div>

              <div className="flex gap-2">
                <div className="relative">
                  <button
                    id="exportUserBtn"
                    className="px-3 py-1 bg-blue-500 text-white rounded-md hover:bg-blue-600"
                  >
                    <i className="fa-solid fa-download mr-1" />
                    导出表格
                  </button>
                </div>
                <button
                  id="batchContcarBtn"
                  className="px-3 py-1 bg-emerald-600 text-white rounded-md hover:bg-emerald-700"
                >
                  <i className="fa-solid fa-box-archive mr-1" />
                  CONTCAR 批量导出
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      用户
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      服务器
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      路径
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      提交时间
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      任务类型
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      状态
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      耗时
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody
                  className="bg-white divide-y divide-gray-200"
                  id="taskTableBody"
                >
                  <tr>
                    <td
                      colSpan={8}
                      className="px-6 py-4 text-center text-sm text-gray-500"
                    >
                      加载中...
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* 分页控件：首页 / 尾页 */}
            <div
              id="paginationControls"
              className="px-6 py-4 border-t border-gray-200 flex items-center justify-between"
            >
              <div className="text-sm text-gray-700">
                显示第 <span id="currentRange">0</span> 条，共{" "}
                <span id="totalTasks">0</span> 条
              </div>
              <div className="flex items-center space-x-2">
                <button
                  id="firstPage"
                  className="px-3 py-1 border rounded-md text-sm bg-white hover:bg-gray-50"
                  disabled
                >
                  首页
                </button>
                <div
                  id="pageNumbers"
                  className="flex items-center space-x-1"
                />
                <button
                  id="lastPage"
                  className="px-3 py-1 border rounded-md text-sm bg-white hover:bg-gray-50"
                  disabled
                >
                  尾页
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ===== 任务详情模态框：透明背景，只显示白色卡片 ===== */}
        <div
          id="taskDetailModal"
          className="hidden fixed inset-0 bg-transparent flex items-center justify-center z-[1100] pointer-events-none"
        >
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto p-6 pointer-events-auto">
            <div className="flex items-center justify-between mb-4">
              <h3
                id="detailTitle"
                className="text-lg font-semibold text-gray-900"
              >
                任务详情
              </h3>
              <button
                id="detailModalCloseX"
                className="text-gray-400 hover:text-gray-600"
              >
                <i className="fa-solid fa-xmark text-xl" />
              </button>
            </div>

            {/* 基本信息 */}
            <div className="detail-section">
              <div className="detail-title">
                <i className="fa-solid fa-circle-info" />
                基本信息
              </div>
              <div id="detailBasic" />
            </div>

            {/* 路径信息 */}
            <div className="detail-section">
              <div className="detail-title">
                <i className="fa-solid fa-folder-open" />
                路径信息
              </div>
              <div id="detailPath" />
            </div>

            {/* 关键计算参数 */}
            <div className="detail-section">
              <div className="detail-title">
                <i className="fa-solid fa-sliders" />
                关键计算参数
              </div>
              <div id="detailParams" />
            </div>

            {/* 主要计算结果 */}
            <div className="detail-section">
              <div className="detail-title">
                <i className="fa-solid fa-table" />
                主要计算结果
              </div>
              <div id="detailResults" />
            </div>

            {/* 补充参数 */}
            <div className="detail-section">
              <div className="detail-title">
                <i className="fa-solid fa-circle-plus" />
                补充参数
              </div>
              <div id="detailExtra" />
            </div>

            <div className="mt-4 flex justify-end">
              <button
                id="closeDetailModal"
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-sm rounded-md text-gray-700"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      </div>
    </TasksLayout>
  );
}