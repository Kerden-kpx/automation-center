import { Calendar, CaretLeft, CaretRight } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import type { InputSize } from "./FormControls";

const SIZE_CLASS: Record<InputSize, string> = {
  sm: "px-3 py-2 text-xs rounded-lg",
  md: "px-4 py-2 text-sm rounded-xl",
  lg: "px-5 py-3 text-sm rounded-2xl",
};

const formatDate = (date: Date) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
};

const parseDate = (value: string) => {
  if (!value) return null;
  const parts = value.split("-");
  if (parts.length === 3) {
    const [y, m, d] = parts.map((v) => Number(v));
    if (!Number.isNaN(y) && !Number.isNaN(m) && !Number.isNaN(d)) {
      return new Date(y, m - 1, d);
    }
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

type AppDatePickerProps = {
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  className?: string;
  size?: InputSize;
  align?: "left" | "right";
};

export function AppDatePicker({
  value,
  onChange,
  placeholder = "选择日期",
  className = "",
  size = "md",
  align = "right",
}: AppDatePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [viewDate, setViewDate] = useState<Date>(() => parseDate(value) || new Date());
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    const parsed = parseDate(value);
    if (parsed) setViewDate(parsed);
  }, [value]);

  const daysInMonth = (year: number, month: number) => new Date(year, month + 1, 0).getDate();
  const firstDayOfMonth = (year: number, month: number) => new Date(year, month, 1).getDay();

  const handlePrevMonth = () => {
    setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1));
  };

  const handleNextMonth = () => {
    setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1));
  };

  const handleDateSelect = (day: number) => {
    const selected = new Date(viewDate.getFullYear(), viewDate.getMonth(), day);
    onChange(formatDate(selected));
    setIsOpen(false);
  };

  const renderDays = () => {
    const year = viewDate.getFullYear();
    const month = viewDate.getMonth();
    const totalDays = daysInMonth(year, month);
    const startDay = firstDayOfMonth(year, month);
    const days = [];
    const today = formatDate(new Date());

    for (let i = 0; i < startDay; i++) {
      days.push(<div key={`empty-${i}`} className="w-8 h-8" />);
    }

    for (let d = 1; d <= totalDays; d++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const isSelected = value === dateStr;
      const isToday = today === dateStr;

      days.push(
        <button
          key={d}
          onClick={() => handleDateSelect(d)}
          className={`w-8 h-8 rounded-xl text-[11px] font-bold transition-all flex items-center justify-center ${
            isSelected
              ? "bg-[#3B9DF8] text-white shadow-lg shadow-blue-200"
              : isToday
                ? "bg-blue-50 text-[#3B9DF8] border border-blue-100"
                : "text-gray-600 hover:bg-gray-100"
          }`}
        >
          {d}
        </button>
      );
    }
    return days;
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full bg-gray-50 border border-transparent text-gray-700 flex items-center justify-between hover:bg-white hover:border-gray-100 focus:ring-4 focus:ring-blue-100 outline-none transition-all ${SIZE_CLASS[size]} ${className}`}
      >
        <span className={value ? "text-gray-900 font-medium" : "text-gray-400"}>
          {value || placeholder}
        </span>
        <Calendar size={16} className="text-gray-400 shrink-0 ml-2" />
      </button>

      {isOpen && (
        <div
          className={`absolute top-full ${align === "left" ? "left-0" : "right-0"} mt-2 z-[60] min-w-[284px] max-w-[calc(100vw-24px)] p-4 bg-white rounded-2xl shadow-2xl border border-gray-100 animate-in fade-in slide-in-from-top-2 duration-200`}
        >
          <div className="flex items-center justify-between mb-4 px-1">
            <h4 className="text-sm font-black text-gray-900 whitespace-nowrap">
              {viewDate.getFullYear()}年 {viewDate.getMonth() + 1}月
            </h4>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={handlePrevMonth}
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-900 transition-all"
              >
                <CaretLeft size={16} weight="bold" />
              </button>
              <button
                type="button"
                onClick={handleNextMonth}
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-900 transition-all"
              >
                <CaretRight size={16} weight="bold" />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-7 gap-1 mb-1">
            {["日", "一", "二", "三", "四", "五", "六"].map((w) => (
              <div key={w} className="w-8 flex items-center justify-center text-[10px] font-bold text-gray-400 uppercase">
                {w}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-1">
            {renderDays()}
          </div>

          <div className="mt-4 pt-3 border-t border-gray-50 flex justify-between">
            <button
              type="button"
              onClick={() => {
                onChange("");
                setIsOpen(false);
              }}
              className="text-[10px] font-bold text-red-400 hover:text-red-500 transition-colors"
            >
              清除
            </button>
            <button
              type="button"
              onClick={() => {
                onChange(formatDate(new Date()));
                setIsOpen(false);
              }}
              className="text-[10px] font-bold text-[#3B9DF8] hover:text-blue-600 transition-colors"
            >
              今天
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
