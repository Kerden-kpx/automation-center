import { CheckCircle, GridFour, MagnifyingGlass, Tag } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

import { FormInput } from "./FormControls";

type ConfirmConfig = {
  title: string;
  message: string;
  onConfirm: () => void;
};

type TagManagerModalProps = {
  open: boolean;
  title?: string;
  subtitle?: string;
  initialSelected: string[];
  libraryTags: string[];
  customLibraryTags: string[];
  setCustomLibraryTags: Dispatch<SetStateAction<string[]>>;
  hiddenLibraryTags: string[];
  setHiddenLibraryTags: Dispatch<SetStateAction<string[]>>;
  onSave: (tags: string[]) => void;
  onClose: () => void;
  saving?: boolean;
  error?: string | null;
};

const normalizeTag = (value: string) => value.trim();

const uniqueTags = (tags: string[]) => Array.from(new Set(tags.map((tag) => tag.trim()).filter(Boolean)));

export function TagManagerModal({
  open,
  title = "管理标签",
  subtitle = "为当前 ASIN 添加或移除标签",
  initialSelected,
  libraryTags,
  customLibraryTags,
  setCustomLibraryTags,
  hiddenLibraryTags,
  setHiddenLibraryTags,
  onSave,
  onClose,
  saving = false,
  error = null,
}: TagManagerModalProps) {
  const [tagDraft, setTagDraft] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [tagMotion, setTagMotion] = useState<{ tag: string; direction: "in" | "out" } | null>(null);
  const [confirmConfig, setConfirmConfig] = useState<ConfirmConfig | null>(null);

  const initialKey = useMemo(() => uniqueTags(initialSelected).sort().join("|"), [initialSelected]);

  useEffect(() => {
    if (!open) return;
    setTagDraft(uniqueTags(initialSelected));
    setTagInput("");
    setConfirmConfig(null);
  }, [open, initialKey, initialSelected]);

  const triggerTagMotion = (tag: string, direction: "in" | "out") => {
    setTagMotion({ tag, direction });
    window.setTimeout(() => {
      setTagMotion((prev) => (prev && prev.tag === tag && prev.direction === direction ? null : prev));
    }, 240);
  };

  const showConfirm = (titleText: string, message: string, onConfirm: () => void) => {
    setConfirmConfig({ title: titleText, message, onConfirm });
  };

  const mergedLibraryTags = useMemo(() => {
    const set = new Set<string>();
    libraryTags.forEach((tag) => {
      const normalized = normalizeTag(String(tag));
      if (normalized) set.add(normalized);
    });
    customLibraryTags.forEach((tag) => {
      const normalized = normalizeTag(String(tag));
      if (normalized) set.add(normalized);
    });
    tagDraft.forEach((tag) => {
      const normalized = normalizeTag(String(tag));
      if (normalized) set.add(normalized);
    });
    return Array.from(set).filter((tag) => !hiddenLibraryTags.includes(tag));
  }, [libraryTags, customLibraryTags, tagDraft, hiddenLibraryTags]);

  const filteredLibraryTags = useMemo(() => {
    const keyword = tagInput.trim().toLowerCase();
    if (!keyword) return mergedLibraryTags;
    return mergedLibraryTags.filter((tag) => tag.toLowerCase().includes(keyword));
  }, [mergedLibraryTags, tagInput]);

  const createTagValue = tagInput.trim();
  const createTagLower = createTagValue.toLowerCase();
  const canCreateTag =
    !!createTagValue &&
    !mergedLibraryTags.some((tag) => tag.toLowerCase() === createTagLower) &&
    !tagDraft.some((tag) => tag.toLowerCase() === createTagLower);

  const addTagToLibrary = (value: string) => {
    const tag = normalizeTag(value);
    if (!tag) return;
    triggerTagMotion(tag, "out");
    setCustomLibraryTags((prev) => (prev.includes(tag) ? prev : [...prev, tag]));
    setHiddenLibraryTags((prev) => prev.filter((hidden) => hidden !== tag));
  };

  const removeSelectedTag = (value: string) => {
    showConfirm("移除标签", `确认从已选标签中移除「${value}」吗？`, () => {
      triggerTagMotion(value, "out");
      setTagDraft((prev) => prev.filter((tag) => tag !== value));
    });
  };

  const toggleTag = (value: string) => {
    setTagDraft((prev) => {
      const exists = prev.includes(value);
      if (exists) {
        showConfirm("移除标签", `确认从已选标签中移除「${value}」吗？`, () => {
          triggerTagMotion(value, "out");
          setTagDraft((current) => current.filter((tag) => tag !== value));
        });
        return prev;
      }
      triggerTagMotion(value, "in");
      return [...prev, value];
    });
  };

  const removeFromLibrary = (value: string) => {
    showConfirm("删除标签", `确认删除标签「${value}」吗？`, () => {
      setHiddenLibraryTags((prev) => (prev.includes(value) ? prev : [...prev, value]));
      setCustomLibraryTags((prev) => prev.filter((tag) => tag !== value));
    });
  };

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 backdrop-blur-sm bg-black/40 overflow-y-auto">
        <div className="w-full max-w-3xl bg-white rounded-[2rem] shadow-2xl border border-gray-100 my-6 animate-in fade-in zoom-in duration-200 min-h-[720px] max-h-[90vh] overflow-hidden">
          <div className="p-8 h-full overflow-y-auto custom-scrollbar">
            <div className="flex items-start justify-between mb-5">
              <div>
                <h3 className="text-lg font-black text-gray-900">{title}</h3>
                <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  className="w-10 h-10 flex items-center justify-center rounded-2xl bg-gray-50 text-gray-400 hover:text-gray-900 hover:bg-gray-100 transition-all"
                  onClick={onClose}
                >
                  <span className="text-xl">✕</span>
                </button>
              </div>
            </div>

            <div className="mb-6">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <MagnifyingGlass size={14} className="absolute left-4 top-3.5 text-gray-400" />
                  <FormInput
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    placeholder="搜索或输入新标签..."
                    className="pl-10 pr-4 py-2.5 rounded-2xl"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && canCreateTag) {
                        e.preventDefault();
                        addTagToLibrary(createTagValue);
                        setTagInput("");
                      }
                    }}
                  />
                </div>
                <button
                  type="button"
                  className="px-5 py-2.5 rounded-2xl text-sm font-bold text-white bg-gray-900 hover:bg-black active:scale-95 disabled:opacity-40 transition-all"
                  onClick={() => {
                    if (!canCreateTag) return;
                    addTagToLibrary(createTagValue);
                    setTagInput("");
                  }}
                  disabled={!canCreateTag}
                >
                  添加
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-center mb-3 px-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-bold text-gray-600">
                  <CheckCircle size={16} className="text-[#3B9DF8]" />
                  已选标签
                </div>
                <span className="text-[11px] font-semibold text-gray-400">{tagDraft.length} Selected</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-bold text-gray-600">
                  <GridFour size={16} className="text-[#3B9DF8]" />
                  标签库
                </div>
                <span className="text-[11px] font-semibold text-gray-400">{filteredLibraryTags.length} Tags</span>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
              <div className="rounded-3xl bg-gray-50/80 p-5 border border-gray-100/60 flex flex-col min-h-[420px]">
                <div className="flex-1 p-4 rounded-2xl bg-white/90 border border-gray-100/60 min-h-[300px]">
                  {tagDraft.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center py-8 text-center">
                      <Tag size={24} className="text-gray-200 mb-2" />
                      <p className="text-xs text-gray-400">目前没有任何标签<br />从右侧选择或手动添加</p>
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {tagDraft.map((tag) => (
                        <button
                          key={tag}
                          type="button"
                          className={`group flex items-center gap-1.5 pl-3 pr-2 py-1.5 rounded-full text-xs font-semibold bg-white border border-gray-100 text-gray-700 shadow-sm hover:border-red-200 hover:text-red-500 transition-all ${tagMotion?.tag === tag
                            ? tagMotion.direction === "in"
                              ? "tag-move-in"
                              : "tag-move-out"
                            : ""}`}
                          onClick={() => removeSelectedTag(tag)}
                        >
                          {tag}
                          <span className="opacity-40 group-hover:opacity-100 transition-opacity">✕</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-3xl bg-gray-50/80 p-5 border border-gray-100/60 flex flex-col min-h-[420px]">
                <div className="flex-1 p-3 rounded-2xl bg-white/90 border border-gray-100/60 overflow-y-auto max-h-[380px] custom-scrollbar">
                  <div className="flex flex-col gap-2">
                    {filteredLibraryTags.length === 0 ? (
                      <div className="py-10 text-center text-xs text-gray-400">暂无可用标签</div>
                    ) : (
                      [...filteredLibraryTags]
                        .sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true }))
                        .map((tag) => {
                          const active = tagDraft.includes(tag);
                          const motionClass =
                            tagMotion?.tag === tag
                              ? tagMotion.direction === "in"
                                ? "tag-move-out"
                                : "tag-move-in"
                              : "";
                          return (
                            <div key={tag} className="group flex items-center w-full">
                              <button
                                type="button"
                                className={`flex-1 flex items-center justify-between pl-4 pr-3 py-2 rounded-full text-xs font-semibold transition-all duration-200 border ${active
                                  ? "bg-[#E6F0FF] text-[#2563EB] border-[#C7DBFF]"
                                  : "bg-gray-50 text-gray-500 border-gray-100 hover:border-gray-200 hover:bg-gray-100"
                                  } ${motionClass}`}
                                onClick={() => toggleTag(tag)}
                              >
                                <span>{tag}</span>
                                <span
                                  className="opacity-40 hover:opacity-100 hover:text-red-500 transition-opacity p-1 -mr-1"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    removeFromLibrary(tag);
                                  }}
                                  title="从库中移除"
                                >
                                  ✕
                                </span>
                              </button>
                            </div>
                          );
                        })
                    )}
                  </div>
                </div>
              </div>
            </div>

            {error && (
              <div className="mt-4 p-3 rounded-xl bg-red-50 text-red-500 text-xs font-bold flex items-center gap-2">
                <span className="text-lg">⚠️</span> {error}
              </div>
            )}

            <div className="flex justify-end gap-3 mt-10">
              <button
                className="px-8 py-3 rounded-2xl text-sm font-bold text-gray-500 hover:text-gray-900 hover:bg-gray-50 active:scale-95 transition-all"
                onClick={onClose}
                disabled={saving}
              >
                取消
              </button>
              <button
                className="px-10 py-3 rounded-2xl text-sm font-bold text-white bg-gray-900 hover:bg-black active:scale-95 disabled:opacity-40 transition-all flex items-center gap-2"
                onClick={() => onSave(tagDraft)}
                disabled={saving}
              >
                {saving ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    保存中...
                  </>
                ) : (
                  "确定"
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {confirmConfig && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center p-4 backdrop-blur-sm bg-black/20 animate-in fade-in duration-200">
          <div className="w-full max-w-sm bg-white rounded-3xl shadow-2xl border border-gray-100 p-8 animate-in zoom-in duration-200">
            <h3 className="text-lg font-black text-gray-900 mb-2">{confirmConfig.title}</h3>
            <p className="text-sm text-gray-500 mb-8 leading-relaxed">{confirmConfig.message}</p>
            <div className="flex gap-3">
              <button
                className="flex-1 py-3 rounded-xl text-sm font-bold text-gray-400 hover:text-gray-900 hover:bg-gray-50 transition-all"
                onClick={() => setConfirmConfig(null)}
              >
                取消
              </button>
              <button
                className="flex-1 py-3 rounded-xl text-sm font-bold text-white bg-gray-900 hover:bg-black transition-all"
                onClick={() => {
                  confirmConfig.onConfirm();
                  setConfirmConfig(null);
                }}
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
