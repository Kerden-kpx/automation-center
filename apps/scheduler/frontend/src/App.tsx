import {
  ChartPieSlice,
  CheckCircle,
  Cube,
  ShoppingBag,
} from "@phosphor-icons/react";
import { Suspense, lazy, useState } from "react";

type Page =
  | "overview"
  | "bsr"
  | "todo"
  | "products";

const DataCenterPage = lazy(() =>
  import("./pages/DataCenterPage").then((module) => ({ default: module.DataCenterPage })),
);
const AppsPage = lazy(() =>
  import("./pages/AppsPage").then((module) => ({ default: module.AppsPage })),
);
const TasksPage = lazy(() =>
  import("./pages/TasksPage").then((module) => ({ default: module.TasksPage })),
);
const ExecutionRecordPage = lazy(() =>
  import("./pages/ExecutionRecordPage").then((module) => ({ default: module.ExecutionRecordPage })),
);

function PageLoading({ collapsed }: { collapsed: boolean }) {
  return (
    <main
      className={`flex-1 ${collapsed ? "ml-20" : "ml-56"} p-8 transition-all duration-300 bg-[#F7F9FB] min-h-screen text-gray-800`}
    >
      <div className="text-sm text-gray-500">页面加载中...</div>
    </main>
  );
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const handleToggleCollapsed = () => setCollapsed((prev) => !prev);

  const navItems = [
    { key: "overview" as Page, icon: <ChartPieSlice weight="fill" />, label: "Overview" },
    { key: "bsr" as Page, icon: <ShoppingBag />, label: "Apps" },
    { key: "products" as Page, icon: <Cube />, label: "Tasks" },
    { key: "todo" as Page, icon: <CheckCircle />, label: "Execution Record" },
  ];

  const renderCurrentPage = () => {
    if (currentPage === "bsr") {
      return (
        <AppsPage
          collapsed={collapsed}
          onToggleCollapse={handleToggleCollapsed}
          onViewAllProducts={() => setCurrentPage("products")}
        />
      );
    }
    if (currentPage === "todo") {
      return <ExecutionRecordPage collapsed={collapsed} onToggleCollapse={handleToggleCollapsed} />;
    }
    if (currentPage === "products") {
      return <TasksPage collapsed={collapsed} onToggleCollapse={handleToggleCollapsed} />;
    }
    return <DataCenterPage collapsed={collapsed} onToggleCollapse={handleToggleCollapsed} />;
  };

  return (
    <div className="min-h-screen bg-[#F7F9FB] text-gray-800">
      <div className="flex">
        <aside className={`${collapsed ? "w-20" : "w-56"} bg-white border-r border-gray-100 flex flex-col fixed h-full z-10 left-0 top-0 overflow-y-auto no-scrollbar transition-all duration-300`}>
          <div className={`p-6 flex items-center ${collapsed ? "justify-center" : "justify-between"}`}>
            <div className="flex items-center gap-2">
              <div className="text-blue-500 text-3xl">
                <img src="/logo.png" alt="Logo" className="w-9 h-9 object-contain" />
              </div>
              {!collapsed && (
                <h1 className="text-xl font-bold tracking-tight text-gray-900">
                  Dashboards
                </h1>
              )}
            </div>
          </div>

          <nav className={`flex-1 ${collapsed ? "px-2" : "px-4"} space-y-1`}>
            {navItems.map((item) => (
              <button
                key={item.label}
                onClick={() => setCurrentPage(item.key)}
                title={collapsed ? item.label : undefined}
                className={`w-full flex items-center ${collapsed ? "justify-center" : "gap-3"} px-4 py-3 rounded-xl text-sm font-medium transition ${currentPage === item.key
                  ? "bg-gray-100 text-gray-900"
                  : "text-gray-500 hover:bg-gray-50 hover:text-gray-900"
                  }`}
              >
                <span className="text-lg">{item.icon}</span>
                {!collapsed && item.label}
              </button>
            ))}
          </nav>

        </aside>

        <Suspense fallback={<PageLoading collapsed={collapsed} />}>
          {renderCurrentPage()}
        </Suspense>
      </div>
    </div>
  );
}
