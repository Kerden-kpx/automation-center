import { SidebarSimple, Star } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { FormInput, FormSelect } from "../components/FormControls";
import {
  resolveTaskAppIds,
  schedulerApi,
  type SchedulerApp,
  type SchedulerTask,
  type SchedulerTaskUpsert,
} from "../api/scheduler";

type TaskFormState = {
  id?: string;
  taskName: string;
  appIds: string[];
  triggerType: "计划触发" | "手动触发" | "永久触发";
  executeTime: string;
  enabled: boolean;
};

const emptyTaskForm: TaskFormState = {
  taskName: "",
  appIds: [],
  triggerType: "手动触发",
  executeTime: "00:00",
  enabled: true,
};

const triggerFromTask = (task: SchedulerTask): "计划触发" | "手动触发" | "永久触发" => {
  if (task.run_mode === "daemon") return "永久触发";
  return task.schedule_type === "daily" ? "计划触发" : "手动触发";
};

const timeFromTask = (task: SchedulerTask): string =>
  task.schedule_type === "daily" ? task.schedule_time : "--";

export function TasksPage({
  collapsed = false,
  onToggleCollapse,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const [tasks, setTasks] = useState<SchedulerTask[]>([]);
  const [apps, setApps] = useState<SchedulerApp[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [taskEditOpen, setTaskEditOpen] = useState(false);
  const [taskCreateOpen, setTaskCreateOpen] = useState(false);
  const [taskRunConfirm, setTaskRunConfirm] = useState<{ open: boolean; task: SchedulerTask | null }>({
    open: false,
    task: null,
  });
  const [taskDeleteConfirm, setTaskDeleteConfirm] = useState<{ open: boolean; task: SchedulerTask | null }>({
    open: false,
    task: null,
  });
  const [taskForm, setTaskForm] = useState<TaskFormState>(emptyTaskForm);
  const [appPickerOpen, setAppPickerOpen] = useState(false);
  const [appPickerIds, setAppPickerIds] = useState<string[]>([]);
  const [appKeyword, setAppKeyword] = useState("");

  const appById = useMemo(() => {
    const map = new Map<string, SchedulerApp>();
    apps.forEach((app) => map.set(app.app_id, app));
    return map;
  }, [apps]);

  const filteredApps = useMemo(() => {
    const keyword = appKeyword.trim().toLowerCase();
    if (!keyword) return apps;
    return apps.filter((app) => {
      const name = String(app.app_name || "").toLowerCase();
      const module = String(app.module || "").toLowerCase();
      return name.includes(keyword) || module.includes(keyword);
    });
  }, [apps, appKeyword]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskRes, appRes] = await Promise.all([schedulerApi.listTasks(), schedulerApi.listApps()]);
      setTasks(taskRes);
      setApps(appRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openTaskCreate = () => {
    setTaskForm({ ...emptyTaskForm, appIds: [] });
    setTaskCreateOpen(true);
  };

  const openTaskEdit = (task: SchedulerTask) => {
    const appIds = resolveTaskAppIds(task);
    setTaskForm({
      id: task.task_id,
      taskName: task.name,
      appIds,
      triggerType: triggerFromTask(task),
      executeTime: task.schedule_time,
      enabled: task.enabled,
    });
    setTaskEditOpen(true);
  };

  const openAppPicker = () => {
    setAppPickerIds(taskForm.appIds);
    setAppKeyword("");
    setAppPickerOpen(true);
  };

  const buildPayload = (form: TaskFormState): SchedulerTaskUpsert => {
    const taskName = form.taskName.trim();
    if (!taskName) {
      throw new Error("任务名称不能为空");
    }
    const selectedApps = form.appIds.map((id) => appById.get(id)).filter(Boolean) as SchedulerApp[];
    if (selectedApps.length === 0) {
      throw new Error("请先选择应用");
    }
    const isComposite = selectedApps.length > 1;

    return {
      name: taskName,
      pipeline: selectedApps.map((app, idx) => ({
        app_id: app.app_id,
        order: idx + 1,
        enabled: true,
      })),
      cwd: ".",
      enabled: form.enabled,
      timeout_sec: 0,
      max_retries: 1,
      retry_delay_sec: 10,
      singleton: true,
      run_mode: form.triggerType === "永久触发" ? "daemon" : "oneshot",
      restart_policy: form.triggerType === "永久触发" ? "always" : "on-failure",
      max_stale_sec: 120,
      schedule_type: form.triggerType === "计划触发" ? "daily" : "none",
      schedule_time: form.triggerType === "计划触发" ? (form.executeTime || "00:00") : "00:00",
      priority: 100,
      resource_group: isComposite ? null : selectedApps[0].app_id,
    };
  };

  const saveTaskCreate = async () => {
    try {
      const payload = buildPayload(taskForm);
      await schedulerApi.createTask(payload);
      setTaskCreateOpen(false);
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "创建失败");
    }
  };

  const saveTaskEdit = async () => {
    if (!taskForm.id) return;
    try {
      const payload = buildPayload(taskForm);
      await schedulerApi.updateTask(taskForm.id, payload);
      setTaskEditOpen(false);
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "保存失败");
    }
  };

  const runTaskNow = async (task: SchedulerTask) => {
    setTaskRunConfirm({ open: false, task: null });
    try {
      await schedulerApi.startTask(task.task_id, "manual");
      alert(`已触发执行：${task.name}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "执行失败");
    }
  };

  const deleteTaskRow = async (task: SchedulerTask) => {
    setTaskDeleteConfirm({ open: false, task: null });
    try {
      await schedulerApi.deleteTask(task.task_id);
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
  };

  const toggleTaskEnabled = async (task: SchedulerTask) => {
    try {
      await schedulerApi.setTaskEnabled(task.task_id, !task.enabled);
      setTasks((prev) => prev.map((t) => (t.task_id === task.task_id ? { ...t, enabled: !t.enabled } : t)));
    } catch (err) {
      alert(err instanceof Error ? err.message : "更新状态失败");
    }
  };

  return (
    <main className={`flex-1 ${collapsed ? "ml-20" : "ml-56"} px-8 pt-8 pb-8 transition-all duration-300 bg-[#F7F9FB] text-gray-800 min-h-screen flex flex-col`}>
      <header className="flex justify-between items-center mb-8">
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
          <span className="text-gray-900 font-medium">Tasks</span>
        </div>
        <button
          type="button"
          onClick={openTaskCreate}
          className="h-9 px-5 rounded-xl bg-[#0C1731] text-white text-[12px] font-semibold hover:bg-[#162443] transition"
        >
          新增任务
        </button>
      </header>

      {error && <div className="mb-4 text-sm text-red-500">{error}</div>}

      <section className="bg-white p-5 rounded-3xl shadow-sm mb-0 flex-1 min-h-[420px]">
        <div className="overflow-x-auto h-full">
          <table className="w-full table-auto text-[13px]">
            <thead>
              <tr className="text-[#8B95A7] border-b border-[#EEF2F7]">
                <th className="text-center font-medium py-3 px-3">序号</th>
                <th className="text-center font-medium py-3 px-3">任务名称</th>
                <th className="text-center font-medium py-3 px-3">包含应用</th>
                <th className="text-center font-medium py-3 px-3">触发方式</th>
                <th className="text-center font-medium py-3 px-3">启用状态</th>
                <th className="text-center font-medium py-3 px-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task, idx) => {
                const appNames = resolveTaskAppIds(task)
                  .map((appId) => appById.get(appId)?.app_name || appId)
                  .filter(Boolean)
                  .join(", ");
                return (
                  <tr key={task.task_id} className="border-b border-[#F2F5FA] hover:bg-[#FAFCFF]">
                    <td className="py-4 px-3 text-[#111827] text-center">{idx + 1}</td>
                    <td className="py-4 px-3 text-[#111827] font-medium text-center">{task.name}</td>
                    <td className="py-4 px-3 text-[#111827] text-center">{appNames || "-"}</td>
                    <td className="py-4 px-3 text-[#111827] text-center">{triggerFromTask(task)}</td>
                    <td className="py-4 px-3 text-center">
                      <button
                        type="button"
                        onClick={() => toggleTaskEnabled(task)}
                        className={`relative inline-flex h-5 w-10 items-center rounded-full transition ${
                          task.enabled ? "bg-[#3B82F6]" : "bg-[#D1D5DB]"
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
                            task.enabled ? "translate-x-5" : "translate-x-1"
                          }`}
                        />
                      </button>
                    </td>
                    <td className="py-4 px-3">
                      <div className="flex items-center justify-center gap-3 text-[#3B82F6]">
                        <button type="button" className="hover:underline" onClick={() => openTaskEdit(task)}>编辑</button>
                        <button
                          type="button"
                          className="hover:underline"
                          onClick={() => setTaskRunConfirm({ open: true, task })}
                        >
                          执行
                        </button>
                        <button
                          type="button"
                          className="hover:underline text-[#EF4444]"
                          onClick={() => setTaskDeleteConfirm({ open: true, task })}
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!loading && tasks.length === 0 && (
                <tr>
                  <td className="py-12 text-center text-[#9AA3B2]" colSpan={7}>暂无任务</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {(taskEditOpen || taskCreateOpen) && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-lg rounded-3xl bg-white shadow-xl border border-[#E8EDF6] p-6">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-[16px] font-semibold text-[#111827]">{taskCreateOpen ? "新增任务" : "编辑任务"}</h3>
              <button
                type="button"
                onClick={() => {
                  setTaskEditOpen(false);
                  setTaskCreateOpen(false);
                }}
                className="w-8 h-8 rounded-full text-[#6B7280] hover:bg-[#F3F6FB]"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">任务名称</label>
                <FormInput
                  value={taskForm.taskName}
                  onChange={(e) => setTaskForm((prev) => ({ ...prev, taskName: e.target.value }))}
                  placeholder="任务名称"
                />
              </div>
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">应用名称（可多选，支持组合任务）</label>
                <div className="rounded-xl border border-[#E8EDF6] bg-[#F8FAFD] p-3">
                  <button
                    type="button"
                    onClick={openAppPicker}
                    className="w-full h-9 rounded-lg border border-[#E5EAF1] bg-white text-[#EF4444] text-[14px] hover:bg-[#FFF7F7]"
                  >
                    + 添加应用
                  </button>
                  <div className="mt-2 text-[12px] text-[#64748B]">已选 {taskForm.appIds.length} 个应用</div>
                  <div className="mt-2 space-y-1 max-h-28 overflow-auto">
                    {taskForm.appIds.map((appId, idx) => (
                      <div key={`${appId}-${idx}`} className="flex items-center justify-between rounded-lg bg-white px-3 py-1.5 border border-[#E8EDF6]">
                        <span className="text-[13px] text-[#1F2937]">{idx + 1}. {appById.get(appId)?.app_name || appId}</span>
                        <button
                          type="button"
                          className="text-[12px] text-[#EF4444] hover:underline"
                          onClick={() =>
                            setTaskForm((prev) => ({
                              ...prev,
                              appIds: prev.appIds.filter((id) => id !== appId),
                            }))
                          }
                        >
                          移除
                        </button>
                      </div>
                    ))}
                    {taskForm.appIds.length === 0 && (
                      <div className="text-[12px] text-[#94A3B8] py-2">尚未选择应用</div>
                    )}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">触发方式</label>
                  <FormSelect
                    value={taskForm.triggerType}
                    onChange={(e) =>
                      setTaskForm((prev) => ({
                        ...prev,
                        triggerType: e.target.value as "计划触发" | "手动触发" | "永久触发",
                        executeTime: e.target.value === "计划触发" ? prev.executeTime : "00:00",
                      }))
                    }
                  >
                    <option value="手动触发">手动触发</option>
                    <option value="计划触发">计划触发</option>
                    <option value="永久触发">永久触发</option>
                  </FormSelect>
                </div>
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">执行时间(HH:mm)</label>
                  <FormInput
                    value={taskForm.executeTime}
                    onChange={(e) => setTaskForm((prev) => ({ ...prev, executeTime: e.target.value }))}
                    placeholder="00:00"
                    disabled={taskForm.triggerType !== "计划触发"}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between rounded-xl bg-[#F7FAFF] px-4 py-3 border border-[#E8EDF6]">
                <span className="text-sm font-medium text-[#334155]">启用状态</span>
                <button
                  type="button"
                  onClick={() => setTaskForm((prev) => ({ ...prev, enabled: !prev.enabled }))}
                  className={`relative inline-flex h-5 w-10 items-center rounded-full transition ${
                    taskForm.enabled ? "bg-[#3B82F6]" : "bg-[#D1D5DB]"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
                      taskForm.enabled ? "translate-x-5" : "translate-x-1"
                    }`}
                  />
                </button>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setTaskEditOpen(false);
                  setTaskCreateOpen(false);
                }}
                className="px-5 h-9 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition"
              >
                取消
              </button>
              <button
                type="button"
                onClick={taskCreateOpen ? saveTaskCreate : saveTaskEdit}
                className="px-6 h-9 rounded-xl text-sm font-semibold text-white bg-[#0C1731] hover:bg-[#162443] transition"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {appPickerOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-xl rounded-3xl bg-white shadow-xl border border-[#E8EDF6] p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[16px] font-semibold text-[#111827]">选择应用</h3>
              <button
                type="button"
                onClick={() => setAppPickerOpen(false)}
                className="w-8 h-8 rounded-full text-[#6B7280] hover:bg-[#F3F6FB]"
              >
                ✕
              </button>
            </div>

            <FormInput
              value={appKeyword}
              onChange={(e) => setAppKeyword(e.target.value)}
              placeholder="搜索应用名称或模块"
              className="mb-3"
            />

            <div className="max-h-72 overflow-auto rounded-xl border border-[#E8EDF6] bg-[#F8FAFD] p-2 space-y-1">
              {filteredApps.map((app) => {
                const checked = appPickerIds.includes(app.app_id);
                return (
                  <label
                    key={app.app_id}
                    className="flex items-center gap-2 rounded-lg bg-white border border-[#E8EDF6] px-3 py-2 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setAppPickerIds((prev) =>
                          checked ? prev.filter((id) => id !== app.app_id) : [...prev, app.app_id]
                        )
                      }
                      className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#93C5FD]"
                    />
                    <div className="text-[13px] text-[#1F2937]">{app.app_name}</div>
                  </label>
                );
              })}
              {filteredApps.length === 0 && (
                <div className="text-[12px] text-[#94A3B8] py-8 text-center">没有匹配的应用</div>
              )}
            </div>

            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setAppPickerOpen(false)}
                className="px-5 h-9 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => {
                  setTaskForm((prev) => ({ ...prev, appIds: appPickerIds }));
                  setAppPickerOpen(false);
                }}
                className="px-6 h-9 rounded-xl text-sm font-semibold text-white bg-[#0C1731] hover:bg-[#162443] transition"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {taskRunConfirm.open && taskRunConfirm.task && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-sm rounded-3xl bg-white shadow-xl border border-[#E8EDF6] p-6">
            <h3 className="text-[16px] font-semibold text-[#111827] mb-2">确认执行任务</h3>
            <p className="text-[13px] text-[#64748B] mb-6">
              是否立即执行任务「{taskRunConfirm.task.name}」？
            </p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setTaskRunConfirm({ open: false, task: null })}
                className="px-5 h-9 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => runTaskNow(taskRunConfirm.task as SchedulerTask)}
                className="px-6 h-9 rounded-xl text-sm font-semibold text-white bg-[#0C1731] hover:bg-[#162443] transition"
              >
                确认执行
              </button>
            </div>
          </div>
        </div>
      )}

      {taskDeleteConfirm.open && taskDeleteConfirm.task && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-sm rounded-3xl bg-white shadow-xl border border-[#E8EDF6] p-6">
            <h3 className="text-[16px] font-semibold text-[#111827] mb-2">确认删除任务</h3>
            <p className="text-[13px] text-[#64748B] mb-6">
              是否删除任务「{taskDeleteConfirm.task.name}」？
            </p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setTaskDeleteConfirm({ open: false, task: null })}
                className="px-5 h-9 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => deleteTaskRow(taskDeleteConfirm.task as SchedulerTask)}
                className="px-6 h-9 rounded-xl text-sm font-semibold text-white bg-[#0C1731] hover:bg-[#162443] transition"
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
