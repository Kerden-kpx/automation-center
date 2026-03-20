import { SidebarSimple, Star } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { schedulerApi, type SchedulerApp } from "../api/scheduler";

export function AppsPage({
  collapsed = false,
  onToggleCollapse,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onViewAllProducts?: () => void;
}) {
  const [apps, setApps] = useState<SchedulerApp[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshConfirmOpen, setRefreshConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<SchedulerApp | null>(null);
  const [editName, setEditName] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadData = async (withNotice = false) => {
    setLoading(true);
    setError(null);
    try {
      const appRes = await schedulerApi.listApps();
      setApps(appRes);
      if (withNotice) {
        setNotice({ type: "success", text: `刷新成功，共 ${appRes.length} 个应用` });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "加载失败";
      setError(message);
      if (withNotice) {
        setNotice({ type: "error", text: `刷新失败：${message}` });
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const openEdit = (app: SchedulerApp) => {
    setEditingApp(app);
    setEditName(app.app_name);
    setEditEnabled(Boolean(app.enabled));
    setEditDialogOpen(true);
  };

  const saveEdit = async () => {
    if (!editingApp) return;
    const name = editName.trim();
    if (!name) {
      setNotice({ type: "error", text: "应用名称不能为空" });
      return;
    }
    setSaving(true);
    try {
      await schedulerApi.updateApp(editingApp.app_id, {
        app_name: name,
        enabled: editEnabled,
      });
      setEditDialogOpen(false);
      setEditingApp(null);
      await loadData(false);
      setNotice({ type: "success", text: "应用更新成功" });
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "应用更新失败" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className={`flex-1 ${collapsed ? "ml-20" : "ml-56"} px-8 pt-8 pb-8 transition-all duration-300 bg-[#F7F9FB] min-h-screen text-gray-800 flex flex-col`}>
      <header className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-4 text-sm text-gray-500">
          <button
            type="button"
            onClick={onToggleCollapse}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-800 transition"
            title={collapsed ? "展开菜单" : "收起菜单"}
          >
            <SidebarSimple className="text-xl" />
          </button>
          <Star className="text-xl text-gray-800 cursor-pointer" weight="fill" />
          <span className="text-gray-400">Dashboards</span>
          <span className="text-gray-300">/</span>
          <span className="text-gray-900 font-medium">Apps</span>
        </div>

        <button
          type="button"
          onClick={() => setRefreshConfirmOpen(true)}
          className="h-9 px-5 rounded-xl bg-[#0C1731] text-white text-[12px] font-semibold hover:bg-[#162443] transition"
        >
          刷新
        </button>
      </header>

      {error && <div className="mb-4 text-sm text-red-500">{error}</div>}

      <section className="bg-white p-5 rounded-3xl shadow-sm mb-0 flex-1 min-h-[420px]">
        <div className="overflow-x-auto h-full">
          <table className="w-full table-auto text-[13px]">
            <thead>
              <tr className="text-[#8B95A7] border-b border-[#EEF2F7]">
                <th className="py-3 px-3 text-center font-medium">序号</th>
                <th className="py-3 px-3 text-center font-medium">应用名称</th>
                <th className="py-3 px-3 text-center font-medium">模块</th>
                <th className="py-3 px-3 text-center font-medium">状态</th>
                <th className="py-3 px-3 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {apps.map((app, idx) => (
                <tr key={app.app_id} className="border-b border-[#F2F5FA] hover:bg-[#FAFCFF]">
                  <td className="py-4 px-3 text-[#111827] text-center">{idx + 1}</td>
                  <td className="py-4 px-3 text-[#111827] font-medium text-center">{app.app_name}</td>
                  <td className="py-4 px-3 text-[#111827] text-center">{app.module}</td>
                  <td className="py-4 px-3 text-center">
                    <span
                      className={`inline-flex px-2 py-0.5 rounded text-[12px] font-medium ${
                        app.enabled ? "bg-[#ECFDF3] text-[#16A34A]" : "bg-[#F1F5F9] text-[#64748B]"
                      }`}
                    >
                      {app.enabled ? "启用" : "禁用"}
                    </span>
                  </td>
                  <td className="py-4 px-3 text-center">
                    <button
                      type="button"
                      className="text-[#2563EB] hover:underline font-medium"
                      onClick={() => openEdit(app)}
                    >
                      编辑
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && apps.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#9AA3B2]">暂无应用</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {notice && (
        <div className="fixed inset-x-0 top-6 z-[80] flex justify-center pointer-events-none">
          <div
            className={`min-w-[220px] max-w-[360px] rounded-xl px-4 py-3 text-sm shadow-lg border ${
              notice.type === "success"
                ? "bg-white text-emerald-700 border-emerald-200"
                : "bg-white text-red-700 border-red-200"
            }`}
          >
            {notice.text}
          </div>
        </div>
      )}

      {refreshConfirmOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-sm rounded-3xl bg-white shadow-xl border border-[#E8EDF6] p-6">
            <h3 className="text-[16px] font-semibold text-[#111827] mb-2">确认刷新应用列表</h3>
            <p className="text-[13px] text-[#64748B] mb-6">将重新扫描 domains 并同步到应用表，是否继续？</p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setRefreshConfirmOpen(false)}
                className="px-5 h-9 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition"
              >
                取消
              </button>
              <button
                type="button"
                onClick={async () => {
                  setRefreshConfirmOpen(false);
                  await loadData(true);
                }}
                className="px-6 h-9 rounded-xl text-sm font-semibold text-white bg-[#0C1731] hover:bg-[#162443] transition"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {editDialogOpen && editingApp && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-md rounded-3xl bg-white shadow-xl border border-[#E8EDF6] p-6">
            <h3 className="text-[16px] font-semibold text-[#111827] mb-4">编辑应用</h3>
            <div className="space-y-4">
              <label className="block">
                <span className="text-[13px] text-[#64748B]">应用名称</span>
                <input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="mt-1 w-full h-10 rounded-xl border border-[#E5EAF1] px-3 text-[13px] text-[#111827] outline-none focus:border-[#3B82F6]"
                />
              </label>
              <label className="block">
                <span className="text-[13px] text-[#64748B]">状态</span>
                <select
                  value={editEnabled ? "1" : "0"}
                  onChange={(e) => setEditEnabled(e.target.value === "1")}
                  className="mt-1 w-full h-10 rounded-xl border border-[#E5EAF1] px-3 text-[13px] text-[#111827] outline-none focus:border-[#3B82F6] bg-white"
                >
                  <option value="1">启用</option>
                  <option value="0">禁用</option>
                </select>
              </label>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                type="button"
                onClick={() => {
                  setEditDialogOpen(false);
                  setEditingApp(null);
                }}
                disabled={saving}
                className="px-5 h-9 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={saveEdit}
                disabled={saving}
                className="px-6 h-9 rounded-xl text-sm font-semibold text-white bg-[#0C1731] hover:bg-[#162443] transition disabled:opacity-50"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
