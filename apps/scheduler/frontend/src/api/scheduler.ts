const API_BASE = (import.meta.env.VITE_SCHEDULER_API_BASE || "").trim();

const withBase = (path: string) => `${API_BASE}${path}`;

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(withBase(path), init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `${path} -> ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export type SchedulerTask = {
  task_id: string;
  name: string;
  pipeline: SchedulerPipelineStep[];
  cwd?: string | null;
  enabled: boolean;
  timeout_sec: number;
  max_retries: number;
  retry_delay_sec: number;
  singleton: boolean;
  run_mode: "oneshot" | "daemon";
  restart_policy: "never" | "on-failure" | "always";
  max_stale_sec: number;
  schedule_type: "none" | "daily";
  schedule_time: string;
  priority: number;
  resource_group?: string | null;
};

export type SchedulerPipelineStep = {
  app_id: string;
  order: number;
  enabled: boolean;
};

export type SchedulerTaskUpsert = Omit<SchedulerTask, "task_id">;

export type SchedulerRun = {
  run_id: string;
  task_id: string;
  status: "queued" | "running" | "success" | "failed" | string;
  started_at?: string | null;
  ended_at?: string | null;
  return_code?: number | null;
  log_tail: string[];
  attempt: number;
  max_retries: number;
  trigger_type: string;
  error_message?: string | null;
  last_heartbeat_at?: string | null;
};

export type SchedulerApp = {
  app_id: string;
  app_name: string;
  module: string;
  cwd: string;
  enabled: boolean;
};

export type SchedulerAppUpdate = {
  app_name: string;
  enabled: boolean;
};

export type SchedulerStats = {
  task_count: number;
  run_count: number;
  status_counts: Record<string, number>;
  window_24h: {
    total_runs: number;
    success_runs: number;
    success_rate: number;
  };
  recent_failures: Array<{
    run_id: string;
    task_id: string;
    started_at?: string | null;
    error_message?: string | null;
  }>;
};

export const schedulerApi = {
  listTasks: () => requestJson<SchedulerTask[]>("/tasks"),
  createTask: (payload: SchedulerTaskUpsert) =>
    requestJson<SchedulerTask>("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateTask: (taskId: string, payload: SchedulerTaskUpsert) =>
    requestJson<SchedulerTask>(`/tasks/${encodeURIComponent(taskId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTask: (taskId: string) =>
    requestJson<{ ok: boolean; task_id: string }>(`/tasks/${encodeURIComponent(taskId)}`, {
      method: "DELETE",
    }),
  setTaskEnabled: (taskId: string, enabled: boolean) =>
    requestJson<SchedulerTask>(`/tasks/${encodeURIComponent(taskId)}/enabled`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  startTask: (taskId: string, trigger_type = "manual") =>
    requestJson<SchedulerRun>(`/tasks/${encodeURIComponent(taskId)}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trigger_type }),
    }),
  listApps: () => requestJson<SchedulerApp[]>("/apps"),
  updateApp: (appId: string, payload: SchedulerAppUpdate) =>
    requestJson<SchedulerApp>(`/apps/${encodeURIComponent(appId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  listRuns: () => requestJson<SchedulerRun[]>("/runs"),
  listRunLogs: (runId: string, limit = 500, offset = 0) =>
    requestJson<{ run_id: string; count: number; items: Array<{ id: number; run_id: string; ts: string; line: string }> }>(
      `/runs/${encodeURIComponent(runId)}/logs/query`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit, offset }),
      }
    ),
  stats: () => requestJson<SchedulerStats>("/stats"),
};

export const resolveTaskAppIds = (task: Pick<SchedulerTask, "pipeline">): string[] => {
  const pipeline = Array.isArray(task.pipeline) ? task.pipeline : [];
  return [...pipeline]
    .sort((a, b) => (a.order || 0) - (b.order || 0))
    .filter((step) => step.enabled !== false)
    .map((step) => String(step.app_id || "").trim())
    .filter(Boolean);
};
