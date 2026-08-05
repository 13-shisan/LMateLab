// frontend/src/pages/db/PersonalDatabaseEntry.jsx
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import DbLayout from "./DbLayout";
import api from "../../api/client";

const PERSONAL_DB_OPTIONS = [
  {
    key: "vaspdb",
    label: "VASP 数据库",
    desc: "个人 VASP 数据库入口",
    path: "/dashboard/db/personal/vasp",
    icon: "🧪",
  },
  {
    key: "qeepwdb",
    label: "QE+EPW 数据库",
    desc: "个人 QE+EPW 数据库入口",
    path: "/dashboard/db/personal/qe-epw",
    icon: "⚡",
  },
];

function ownerFromCustomKey(key) {
  // VASP: custom:{alias}:{file}.db
  // QE:   custom_qe_epw:{alias}:{file}.sqlite
  const s = String(key || "").trim();
  if (!s.includes(":")) return "";

  if (s.startsWith("custom_qe_epw:")) {
    const parts = s.split(":", 3);
    return (parts[1] || "").trim();
  }
  if (s.startsWith("custom:")) {
    const parts = s.split(":", 3);
    return (parts[1] || "").trim();
  }
  return "";
}

export default function PersonalDatabaseEntry() {
  const navigate = useNavigate();

  // ---- custom lists ----
  const [customVasp, setCustomVasp] = useState([]);
  const [customQe, setCustomQe] = useState([]);
  const [loadingCustom, setLoadingCustom] = useState(false);

  // ---- current user alias (UI gating only) ----
  const [myAlias, setMyAlias] = useState("");   // 只从 /auth/me 获取
  const [loadingMe, setLoadingMe] = useState(true);


  // ---- create modal ----
  const [showCreate, setShowCreate] = useState(false);
  const [tpl, setTpl] = useState("vasp"); // vasp | qe_epw
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState("");

  // ---- delete state ----
  const [deletingKey, setDeletingKey] = useState(""); // key being deleted
  const [deleteErr, setDeleteErr] = useState("");

  async function loadMe() {
    setLoadingMe(true);
    try {
      const r = await api.get("/auth/me");
      const alias = (r.data?.alias || "").trim();
      setMyAlias(alias);
    } finally {
      setLoadingMe(false);
    }
  }

  async function loadCustom() {
    setLoadingCustom(true);
    try {
      const [r1, r2] = await Promise.all([
        api.get("/db/vasp/custom/list"),
        api.get("/db/qe_epw/custom/list"),
      ]);

      const vItems = r1.data?.items || [];
      const qItems = r2.data?.items || [];

      setCustomVasp(vItems);
      setCustomQe(qItems);
    } finally {
      setLoadingCustom(false);
    }
  }

  useEffect(() => {
    (async () => {
      await loadMe();
      await loadCustom();
    })();
  }, []);

  async function handleCreateCustom() {
    setCreateErr("");
    const nm = (name || "").trim();
    if (!nm) {
      setCreateErr("请输入自定义数据库名字");
      return;
    }

    setCreating(true);
    try {
      if (tpl === "vasp") {
        await api.post("/db/vasp/custom/create", { name: nm });
      } else {
        await api.post("/db/qe_epw/custom/create", { name: nm });
      }
      setShowCreate(false);
      setName("");
      await loadCustom();
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || String(e);
      setCreateErr(String(msg));
    } finally {
      setCreating(false);
    }
  }

  const canDeleteKey = useMemo(() => {
    return (key) => {
      const owner = ownerFromCustomKey(key);
      // ✅ 前端显示层限制：必须 owner==当前用户 alias 才显示删除按钮
      // 后端仍会二次校验，确保 root 也删不了别人的
      if (!owner) return false;
      if (!myAlias) return false;
      return owner === myAlias;
    };
  }, [myAlias]);

  async function handleDeleteCustom(kind, item) {
    // kind: "vasp" | "qe_epw"
    setDeleteErr("");
    const key = item?.key;
    const nm = item?.name || item?.safe_name || key;

    if (!key) return;

    // ✅ UI 再保险：不属于自己就直接不让点
    if (!canDeleteKey(key)) {
      setDeleteErr("只能删除自己创建的自定义库");
      return;
    }

    const ok = window.confirm(
      `确认删除自定义库「${nm}」？\n` +
      `该操作将同时删除实际数据库文件，且不可恢复。`
    );
    if (!ok) return;

    setDeletingKey(key);
    try {
      if (kind === "vasp") {
        await api.delete("/db/vasp/custom/delete", {
          params: { key, delete_file: 1 },
        });
      } else {
        await api.delete("/db/qe_epw/custom/delete", {
          params: { key, delete_file: 1 },
        });
      }

      await loadCustom();
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || String(e);
      setDeleteErr(String(msg));
    } finally {
      setDeletingKey("");
    }
  }

  return (
    <DbLayout currentSubPath="/dashboard/db/personal" currentDbType="entry" showDbTypeSelector={true}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 style={{ marginBottom: 6 }}>个人数据库</h2>
          <div style={{ fontSize: 12, color: "#6b7280" }}>
            {loadingMe ? "正在获取用户信息…" : (myAlias ? `当前用户：${myAlias}` : "获取用户信息失败")}
          </div>
        </div>

        <button
          type="button"
          onClick={() => {
            setTpl("vasp");
            setName("");
            setCreateErr("");
            setDeleteErr("");
            setShowCreate(true);
          }}
          style={{
            height: 34,
            borderRadius: 10,
            padding: "0 12px",
            border: "1px solid #d1d5db",
            background: "white",
            cursor: "pointer",
          }}
        >
          自定义数据库
        </button>
      </div>

      {/* 上半：默认数据库 */}
      <div style={{ marginTop: 14, marginBottom: 14, fontWeight: 800, color: "#111827" }}>
        默认数据库
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
        {PERSONAL_DB_OPTIONS.map((x) => (
          <button
            key={x.key}
            type="button"
            onClick={() => navigate(x.path)}
            style={{
              textAlign: "left",
              border: "1px solid #e5e7eb",
              borderRadius: 14,
              padding: 14,
              background: "white",
              cursor: "pointer",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 22 }}>{x.icon}</div>
              <div style={{ fontWeight: 700, color: "#111827" }}>{x.label}</div>
            </div>
            <div style={{ marginTop: 8, fontSize: 13, color: "#6b7280" }}>{x.desc}</div>
          </button>
        ))}
      </div>

      {/* 下半：自定义数据库 */}
      <div style={{ marginTop: 22, marginBottom: 10, fontWeight: 800, color: "#111827" }}>
        自定义数据库
      </div>

      {deleteErr ? (
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            borderRadius: 12,
            background: "rgba(254,242,242,.9)",
            border: "1px solid rgba(252,165,165,.8)",
            color: "#991b1b",
            fontSize: 13,
          }}
        >
          {deleteErr}
        </div>
      ) : null}

      {loadingCustom ? (
        <div style={{ color: "#6b7280" }}>加载中…</div>
      ) : (
        <>
          {/* VASP custom */}
          <div style={{ marginBottom: 10, color: "#374151", fontWeight: 800 }}>VASP 自定义库</div>
          {customVasp.length === 0 ? (
            <div style={{ color: "#6b7280", marginBottom: 16 }}>暂无 VASP 自定义数据库</div>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                gap: 12,
                marginBottom: 16,
              }}
            >
              {customVasp.map((c) => {
                const deleting = deletingKey === c.key;
                const showDelete = canDeleteKey(c.key);

                return (
                  <div
                    key={c.key}
                    onClick={() =>
                      navigate(`/dashboard/db/personal/vasp?scope=custom&db=${encodeURIComponent(c.key)}`)
                    }
                    style={{
                      textAlign: "left",
                      border: "1px solid #e5e7eb",
                      borderRadius: 14,
                      padding: 14,
                      background: "white",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
                      <div>
                        <div style={{ fontWeight: 900, color: "#111827" }}>VASP 自定义库：{c.name}</div>
                        <div style={{ marginTop: 8, fontSize: 13, color: "#6b7280" }}>
                          存储于 Customized_database/vasp
                        </div>
                        <div style={{ marginTop: 6, fontSize: 12, color: "#9ca3af" }}>
                          key: {c.key}
                        </div>
                      </div>

                      {showDelete ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteCustom("vasp", c);
                          }}
                          disabled={deleting}
                          style={{
                            height: 32,
                            borderRadius: 10,
                            padding: "0 12px",
                            border: "1px solid rgba(239,68,68,0.55)",
                            background: deleting ? "rgba(243,244,246,1)" : "rgba(254,242,242,1)",
                            color: deleting ? "#6b7280" : "#991b1b",
                            fontWeight: 900,
                            cursor: deleting ? "not-allowed" : "pointer",
                            flex: "0 0 auto",
                          }}
                          title="删除自定义库（仅能删除自己创建的）"
                        >
                          {deleting ? "删除中…" : "删除"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* QE+EPW custom */}
          <div style={{ marginBottom: 10, color: "#374151", fontWeight: 800 }}>QE+EPW 自定义库</div>
          {customQe.length === 0 ? (
            <div style={{ color: "#6b7280" }}>暂无 QE+EPW 自定义数据库</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
              {customQe.map((c) => {
                const deleting = deletingKey === c.key;
                const showDelete = canDeleteKey(c.key);

                return (
                  <div
                    key={c.key}
                    onClick={() =>
                      navigate(`/dashboard/db/personal/qe-epw?scope=custom&db=${encodeURIComponent(c.key)}`)
                    }
                    style={{
                      textAlign: "left",
                      border: "1px solid #e5e7eb",
                      borderRadius: 14,
                      padding: 14,
                      background: "white",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
                      <div>
                        <div style={{ fontWeight: 900, color: "#111827" }}>QE+EPW 自定义库：{c.name}</div>
                        <div style={{ marginTop: 8, fontSize: 13, color: "#6b7280" }}>
                          存储于 Customized_database/qe_epw
                        </div>
                        <div style={{ marginTop: 6, fontSize: 12, color: "#9ca3af" }}>
                          key: {c.key}
                        </div>
                      </div>

                      {showDelete ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteCustom("qe_epw", c);
                          }}
                          disabled={deleting}
                          style={{
                            height: 32,
                            borderRadius: 10,
                            padding: "0 12px",
                            border: "1px solid rgba(239,68,68,0.55)",
                            background: deleting ? "rgba(243,244,246,1)" : "rgba(254,242,242,1)",
                            color: deleting ? "#6b7280" : "#991b1b",
                            fontWeight: 900,
                            cursor: deleting ? "not-allowed" : "pointer",
                            flex: "0 0 auto",
                          }}
                          title="删除自定义库（仅能删除自己创建的）"
                        >
                          {deleting ? "删除中…" : "删除"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* ---- Create Modal ---- */}
      {showCreate ? (
        <div
          onClick={() => {
            if (!creating) setShowCreate(false);
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 18,
            zIndex: 9999,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(520px, 96vw)",
              borderRadius: 14,
              background: "white",
              border: "1px solid rgba(229,231,235,1)",
              padding: 14,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 900, color: "#111827" }}>创建自定义数据库</div>
              <button
                type="button"
                onClick={() => {
                  if (!creating) setShowCreate(false);
                }}
                style={{
                  height: 32,
                  borderRadius: 10,
                  padding: "0 10px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: "white",
                  cursor: "pointer",
                }}
                disabled={creating}
              >
                关闭
              </button>
            </div>

            <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
              <div>
                <div style={{ fontSize: 12, color: "#374151", fontWeight: 700, marginBottom: 6 }}>模板</div>
                <select
                  value={tpl}
                  onChange={(e) => setTpl(e.target.value)}
                  disabled={creating}
                  style={{
                    height: 36,
                    borderRadius: 10,
                    border: "1px solid #d1d5db",
                    padding: "0 10px",
                    background: "white",
                    width: "100%",
                  }}
                >
                  <option value="vasp">VASP（ASE DB）</option>
                  <option value="qe_epw">QE+EPW（SQLite）</option>
                </select>
              </div>

              <div>
                <div style={{ fontSize: 12, color: "#374151", fontWeight: 700, marginBottom: 6 }}>
                  数据库名字
                </div>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如：myset1"
                  disabled={creating}
                  style={{
                    height: 36,
                    borderRadius: 10,
                    border: "1px solid #d1d5db",
                    padding: "0 10px",
                    width: "100%",
                  }}
                />
              </div>

              {createErr ? (
                <div
                  style={{
                    padding: "10px 12px",
                    borderRadius: 12,
                    background: "rgba(254,242,242,.9)",
                    border: "1px solid rgba(252,165,165,.8)",
                    color: "#991b1b",
                    fontSize: 13,
                  }}
                >
                  {createErr}
                </div>
              ) : null}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 6 }}>
                <button
                  type="button"
                  onClick={() => {
                    if (!creating) setShowCreate(false);
                  }}
                  disabled={creating}
                  style={{
                    height: 36,
                    borderRadius: 12,
                    padding: "0 14px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    cursor: "pointer",
                  }}
                >
                  取消
                </button>

                <button
                  type="button"
                  onClick={handleCreateCustom}
                  disabled={creating}
                  style={{
                    height: 36,
                    borderRadius: 12,
                    padding: "0 14px",
                    border: "1px solid rgba(37,99,235,1)",
                    background: "rgba(37,99,235,1)",
                    color: "white",
                    fontWeight: 900,
                    cursor: "pointer",
                  }}
                >
                  {creating ? "创建中…" : "创建"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </DbLayout>
  );
}
