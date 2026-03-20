import { SidebarSimple, Star } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { schedulerApi, type SchedulerRun, type SchedulerTask } from "../api/scheduler";

type LogDialogState = { open: boolean; row: SchedulerRun | null; text: string; loading: boolean };

const statusLabel = (status: string) => {
  if (status === "success") return "完成";
  if (status === "failed") return "失败";
  if (status === "running" || status === "queued") return "运行中";
  return status;
};

const statusClass = (status: string) => {
  if (status === "success") return "bg-[#ECFDF3] text-[#16A34A]";
  if (status === "failed") return "bg-[#FEF2F2] text-[#DC2626]";
  return "bg-[#EFF6FF] text-[#2563EB]";
};

const formatTime = (v?: string | null) => {
  if (!v) return "--";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}:${ss}`;
};

const formatDurationMinutes = (run: SchedulerRun) => {
  if (!run.started_at) return "--";
  const start = new Date(run.started_at).getTime();
  if (Number.isNaN(start)) return "--";
  const isActive = run.status === "running" || run.status === "queued";
  const endRaw = !isActive && run.ended_at ? new Date(run.ended_at).getTime() : Date.now();
  if (Number.isNaN(endRaw)) return "--";
  const durationMs = Math.max(0, endRaw - start);
  return String(Math.floor(durationMs / 60000));
};

export function ExecutionRecordPage({
  collapsed = false,
  onToggleCollapse,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const [tasks, setTasks] = useState<SchedulerTask[]>([]);
  const [runs, setRuns] = useState<SchedulerRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logDialog, setLogDialog] = useState<LogDialogState>({ open: false, row: null, text: "", loading: false });

  const taskMap = useMemo(() => {
    const map = new Map<string, string>();
    tasks.forEach((t) => map.set(t.task_id, t.name));
    return map;
  }, [tasks]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskRes, runRes] = await Promise.all([schedulerApi.listTasks(), schedulerApi.listRuns()]);
      setTasks(taskRes);
      setRuns(runRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openLogDialog = async (row: SchedulerRun) => {
    setLogDialog({ open: true, row, text: "", loading: true });
    try {
      const resp = await schedulerApi.listRunLogs(row.run_id, 500, 0);
      const text = (resp.items || []).map((item) => `${formatTime(item.ts)}  ${item.line}`).join("\n");
      setLogDialog({ open: true, row, text: text || "暂无日志", loading: false });
    } catch (err) {
      setLogDialog({
        open: true,
        row,
        text: err instanceof Error ? err.message : "日志加载失败",
        loading: false,
      });
    }
  };

  return (
    <main className={`flex-1 ${collapsed ? "ml-20" : "ml-56"} px-8 pt-8 pb-0 transition-all duration-300 bg-[#F7F9FB] min-h-screen text-gray-800 flex flex-col`}>
      <header className="flex items-center mb-8">
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
          <span className="text-gray-900 font-medium">Execution Record</span>
        </div>
      </header>

      {error && <div className="mb-4 text-sm text-red-500">{error}</div>}

      <section className="bg-white p-5 rounded-3xl shadow-sm mb-0 flex-1 min-h-[420px]">
        <div className="overflow-x-auto h-full">
          <table className="w-full table-auto text-[13px]">
            <thead>
              <tr className="text-[#8B95A7] border-b border-[#EEF2F7]">
                <th className="py-3 px-3 text-center font-medium">序号</th>
                <th className="py-3 px-3 text-center font-medium">任务名称</th>
                <th className="py-3 px-3 text-center font-medium">状态</th>
                <th className="py-3 px-3 text-center font-medium">开始时间</th>
                <th className="py-3 px-3 text-center font-medium">结束时间</th>
                <th className="py-3 px-3 text-center font-medium">运行时长(分钟)</th>
                <th className="py-3 px-3 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run, idx) => (
                <tr key={run.run_id} className="border-b border-[#F2F5FA] hover:bg-[#FAFCFF]">
                  <td className="py-4 px-3 text-[#111827] font-medium text-center">{idx + 1}</td>
                  <td className="py-4 px-3 text-[#111827] font-medium text-center">{taskMap.get(run.task_id) || run.task_id}</td>
                  <td className="py-4 px-3 text-center">
                    <span className={`inline-flex px-2 py-0.5 rounded text-[12px] font-medium ${statusClass(run.status)}`}>
                      {statusLabel(run.status)}
                    </span>
                  </td>
                  <td className="py-4 px-3 text-[#111827] text-center">{formatTime(run.started_at)}</td>
                  <td className="py-4 px-3 text-[#111827] text-center">{formatTime(run.ended_at)}</td>
                  <td className="py-4 px-3 text-[#111827] text-center">{formatDurationMinutes(run)}</td>
                  <td className="py-4 px-3 text-center">
                    <button type="button" className="text-[#2563EB] hover:underline font-medium" onClick={() => openLogDialog(run)}>
                      详情
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && runs.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#9AA3B2]">暂无执行记录</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {logDialog.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4 backdrop-blur-[1px]">
          <div className="w-full max-w-2xl rounded-3xl bg-white shadow-xl border border-[#E8EDF6]">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#EEF2F7]">
              <h3 className="text-[15px] font-semibold text-[#111827]">
                执行日志 - {logDialog.row ? (taskMap.get(logDialog.row.task_id) || logDialog.row.task_id) : ""}
              </h3>
              <button
                type="button"
                onClick={() => setLogDialog({ open: false, row: null, text: "", loading: false })}
                className="w-8 h-8 rounded-full text-[#6B7280] hover:bg-[#F3F6FB]"
              >
                x
              </button>
            </div>
            <div className="px-6 py-5">
              <pre className="m-0 max-h-[420px] overflow-auto rounded-xl bg-[#F7F9FC] border border-[#E8EDF6] p-4 text-[12px] leading-6 text-[#334155] whitespace-pre-wrap">
                {logDialog.loading ? "日志加载中..." : logDialog.text}
              </pre>
            </div>
            <div className="px-6 py-4 border-t border-[#EEF2F7] flex justify-end">
              <button
                type="button"
                onClick={() => setLogDialog({ open: false, row: null, text: "", loading: false })}
                className="h-9 px-5 rounded-xl bg-[#0C1731] text-white text-[12px] font-semibold hover:bg-[#162443]"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
