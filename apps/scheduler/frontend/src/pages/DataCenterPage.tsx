import { SidebarSimple, Star } from "@phosphor-icons/react";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import { schedulerApi, type SchedulerRun } from "../api/scheduler";

echarts.use([LineChart, PieChart, BarChart, TooltipComponent, GridComponent, LegendComponent, CanvasRenderer]);

const formatHours = (hours: number) => String(Math.round(hours));

const toDateKey = (value?: string | null): string => {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

const durationSec = (run: SchedulerRun): number => {
  if (!run.started_at || !run.ended_at) return 0;
  const start = new Date(run.started_at).getTime();
  const end = new Date(run.ended_at).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return 0;
  return Math.max(0, Math.round((end - start) / 1000));
};

export function DataCenterPage({
  collapsed = false,
  onToggleCollapse,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const appChartRef = useRef<HTMLDivElement>(null);
  const taskChartRef = useRef<HTMLDivElement>(null);
  const runChartRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [appsCount, setAppsCount] = useState(0);
  const [taskCount, setTaskCount] = useState(0);
  const [enabledAppsCount, setEnabledAppsCount] = useState(0);
  const [enabledTaskCount, setEnabledTaskCount] = useState(0);
  const [runs, setRuns] = useState<SchedulerRun[]>([]);

  const totalRuntimeHours = useMemo(() => {
    const totalSec = runs.reduce((sum, run) => sum + durationSec(run), 0);
    return totalSec / 3600;
  }, [runs]);

  const cumulativeSeries = useMemo(() => {
    const byDay = new Map<string, number>();
    runs.forEach((run) => {
      const key = toDateKey(run.started_at || run.ended_at);
      if (!key) return;
      byDay.set(key, (byDay.get(key) || 0) + durationSec(run) / 3600);
    });
    const keys = Array.from(byDay.keys()).sort((a, b) => a.localeCompare(b));
    let cumulative = 0;
    const values = keys.map((key) => {
      cumulative += byDay.get(key) || 0;
      return Number(cumulative.toFixed(2));
    });
    return { keys, values };
  }, [runs]);

  const runTrendSeries = useMemo(() => {
    const dayMap = new Map<string, number>();
    runs.forEach((run) => {
      const key = toDateKey(run.started_at || run.ended_at);
      if (!key) return;
      dayMap.set(key, (dayMap.get(key) || 0) + 1);
    });
    const keys = Array.from(dayMap.keys()).sort((a, b) => a.localeCompare(b));
    const values = keys.map((key) => dayMap.get(key) || 0);
    return { keys, values };
  }, [runs]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [apps, tasks, runList] = await Promise.all([
        schedulerApi.listApps(),
        schedulerApi.listTasks(),
        schedulerApi.listRuns(),
      ]);
      setAppsCount(apps.length);
      setTaskCount(tasks.length);
      setEnabledAppsCount(apps.filter((item) => item.enabled).length);
      setEnabledTaskCount(tasks.filter((item) => item.enabled).length);
      setRuns(runList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    const container = chartRef.current;
    if (!container) return;
    const chart = echarts.init(container);
    chart.setOption({
      grid: { left: 44, right: 20, top: 20, bottom: 30 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: cumulativeSeries.keys,
        axisLine: { lineStyle: { color: "#E5EAF1" } },
        axisLabel: { color: "#8B95A7", fontSize: 12 },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "#EEF2F7" } },
        axisLabel: { color: "#8B95A7", fontSize: 12 },
      },
      series: [
        {
          name: "累计运行时长(小时)",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#60A5FA", width: 2 },
          itemStyle: { color: "#3B82F6" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(96,165,250,0.35)" },
                { offset: 1, color: "rgba(96,165,250,0.05)" },
              ],
            },
          },
          data: cumulativeSeries.values,
        },
      ],
    });

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [cumulativeSeries]);

  useEffect(() => {
    const appEl = appChartRef.current;
    const taskEl = taskChartRef.current;
    const runEl = runChartRef.current;
    if (!appEl || !taskEl || !runEl) return;

    const appChart = echarts.init(appEl);
    const taskChart = echarts.init(taskEl);
    const runChart = echarts.init(runEl);

    appChart.setOption({
      tooltip: { trigger: "item" },
      legend: { bottom: 4, icon: "circle", textStyle: { color: "#8B95A7", fontSize: 12 } },
      series: [
        {
          type: "pie",
          radius: ["58%", "78%"],
          center: ["50%", "44%"],
          label: { show: false },
          data: [
            { value: enabledAppsCount, name: "启用", itemStyle: { color: "#3B82F6" } },
            { value: Math.max(0, appsCount - enabledAppsCount), name: "停用", itemStyle: { color: "#E5EAF1" } },
          ],
        },
      ],
    });

    taskChart.setOption({
      tooltip: { trigger: "item" },
      legend: { bottom: 4, icon: "circle", textStyle: { color: "#8B95A7", fontSize: 12 } },
      series: [
        {
          type: "pie",
          radius: ["58%", "78%"],
          center: ["50%", "44%"],
          label: { show: false },
          data: [
            { value: enabledTaskCount, name: "启用", itemStyle: { color: "#0F172A" } },
            { value: Math.max(0, taskCount - enabledTaskCount), name: "停用", itemStyle: { color: "#E5EAF1" } },
          ],
        },
      ],
    });

    runChart.setOption({
      grid: { left: 28, right: 16, top: 20, bottom: 28 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: runTrendSeries.keys,
        axisLine: { lineStyle: { color: "#E5EAF1" } },
        axisLabel: { color: "#8B95A7", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "#EEF2F7" } },
        axisLabel: { color: "#8B95A7", fontSize: 11 },
      },
      series: [
        {
          name: "执行次数",
          type: "bar",
          itemStyle: { color: "#3B9DF8", borderRadius: [6, 6, 0, 0] },
          barMaxWidth: 26,
          data: runTrendSeries.values,
        },
      ],
    });

    const onResize = () => {
      appChart.resize();
      taskChart.resize();
      runChart.resize();
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      appChart.dispose();
      taskChart.dispose();
      runChart.dispose();
    };
  }, [appsCount, enabledAppsCount, taskCount, enabledTaskCount, runTrendSeries]);

  return (
    <main className={`flex-1 ${collapsed ? "ml-20" : "ml-56"} px-8 pt-8 pb-8 transition-all duration-300 bg-[#F7F9FB] min-h-screen text-gray-800`}>
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
          <span className="text-gray-900 font-medium">Overview</span>
        </div>
      </header>

      {error && <div className="mb-4 text-sm text-red-500">{error}</div>}

      <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <article className="rounded-3xl bg-[#111318] text-white p-6 shadow-sm">
          <p className="text-sm text-white/70">应用个数</p>
          <p className="text-4xl font-semibold mt-2">{appsCount}</p>
        </article>
        <article className="rounded-3xl bg-[#3B9DF8] text-white p-6 shadow-sm">
          <p className="text-sm text-white/80">任务个数</p>
          <p className="text-4xl font-semibold mt-2">{taskCount}</p>
        </article>
        <article className="rounded-3xl bg-[#111318] text-white p-6 shadow-sm">
          <p className="text-sm text-white/70">累计运行时长(小时)</p>
          <p className="text-4xl font-semibold mt-2">{formatHours(totalRuntimeHours)}</p>
        </article>
        <article className="rounded-3xl bg-[#3B9DF8] text-white p-6 shadow-sm">
          <p className="text-sm text-white/80">累计执行次数(次)</p>
          <p className="text-4xl font-semibold mt-2">{runs.length}</p>
        </article>
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-6">
        <article className="bg-white rounded-3xl shadow-sm p-5 min-h-[260px]">
          <h3 className="text-[16px] font-semibold text-[#0F172A]">应用个数分布</h3>
          <p className="text-[12px] text-[#94A3B8] mt-1">启用/停用</p>
          <div ref={appChartRef} className="h-[200px] w-full mt-2" />
        </article>
        <article className="bg-white rounded-3xl shadow-sm p-5 min-h-[260px]">
          <h3 className="text-[16px] font-semibold text-[#0F172A]">任务个数分布</h3>
          <p className="text-[12px] text-[#94A3B8] mt-1">启用/停用</p>
          <div ref={taskChartRef} className="h-[200px] w-full mt-2" />
        </article>
      </section>

      <section className="bg-white rounded-3xl shadow-sm p-5 min-h-[440px]">
        <div className="mb-4">
          <h3 className="text-[16px] font-semibold text-[#0F172A]">累计运行时长</h3>
          <p className="text-[12px] text-[#94A3B8] mt-1">按天累计面积图</p>
        </div>
        {loading ? (
          <div className="h-[360px] flex items-center justify-center text-[#94A3B8]">加载中...</div>
        ) : cumulativeSeries.keys.length === 0 ? (
          <div className="h-[360px] flex items-center justify-center text-[#94A3B8]">暂无运行数据</div>
        ) : (
          <div ref={chartRef} className="h-[360px] w-full" />
        )}
      </section>

      <section className="bg-white rounded-3xl shadow-sm p-5 min-h-[360px] mt-6">
        <div className="mb-4">
          <h3 className="text-[16px] font-semibold text-[#0F172A]">累计执行次数</h3>
          <p className="text-[12px] text-[#94A3B8] mt-1">按天柱状图</p>
        </div>
        {loading ? (
          <div className="h-[280px] flex items-center justify-center text-[#94A3B8]">加载中...</div>
        ) : runTrendSeries.keys.length === 0 ? (
          <div className="h-[280px] flex items-center justify-center text-[#94A3B8]">暂无执行数据</div>
        ) : (
          <div ref={runChartRef} className="h-[280px] w-full" />
        )}
      </section>
    </main>
  );
}
