import React from "react";

export const parseTagList = (value: any): string[] => {
  if (Array.isArray(value)) {
    return value.map((tag) => String(tag).trim()).filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(/[,，;|/、]/)
      .map((tag) => tag.trim())
      .filter(Boolean);
  }
  return [];
};

type TagPillListProps = {
  value?: any;
  tags?: string[];
  toneClass?: string;
  emptyText?: string;
  stack?: boolean;
  className?: string;
  pillClassName?: string;
  itemWrapperClassName?: string;
};

export const TagPillList: React.FC<TagPillListProps> = ({
  value,
  tags,
  toneClass = "bg-blue-50 text-[#3B9DF8] border border-blue-100/50",
  emptyText = "未选择",
  stack = false,
  className = "",
  pillClassName = "text-[10px] px-2 py-0.5 rounded-md font-semibold",
  itemWrapperClassName = "",
}) => {
  const list = tags ?? parseTagList(value);
  if (!list.length) {
    return <span className="text-xs text-gray-300">{emptyText}</span>;
  }
  const containerClass = stack ? "flex flex-col gap-2" : "flex flex-wrap gap-1.5";
  const wrapperClass = stack ? "w-full" : "";
  return (
    <div className={`${containerClass} ${className}`}>
      {list.map((tag, idx) => (
        <div key={`${tag}-${idx}`} className={`${wrapperClass} ${itemWrapperClassName}`}>
          <span className={`${pillClassName} ${toneClass}`}>{tag}</span>
        </div>
      ))}
    </div>
  );
};

type TagGroupProps = {
  label: string;
  tags?: string[];
  value?: any;
  toneClass?: string;
  emptyText?: string;
  labelClassName?: string;
};

export const TagGroup: React.FC<TagGroupProps> = ({
  label,
  tags,
  value,
  toneClass,
  emptyText = "无",
  labelClassName = "text-[10px] font-bold text-gray-400",
}) => {
  return (
    <div className="flex flex-col gap-1.5">
      <span className={labelClassName}>{label}</span>
      <TagPillList tags={tags} value={value} toneClass={toneClass} emptyText={emptyText} />
    </div>
  );
};
