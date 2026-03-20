import React from "react";

export type InputSize = "sm" | "md" | "lg";

const BASE_INPUT =
  "w-full bg-gray-50 border border-gray-100 text-gray-700 placeholder:text-gray-400 focus:bg-white focus:ring-2 focus:ring-blue-100 outline-none transition-all disabled:opacity-60 disabled:cursor-not-allowed";

const SIZE_CLASS: Record<InputSize, string> = {
  sm: "px-3 py-2 text-xs rounded-lg",
  md: "px-4 py-2 text-sm rounded-xl",
  lg: "px-5 py-3 text-sm rounded-2xl",
};

type InputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> & {
  size?: InputSize;
};

export const FormInput = React.forwardRef<HTMLInputElement, InputProps>(
  ({ size = "md", className = "", ...props }, ref) => (
    <input
      ref={ref}
      {...props}
      className={`${BASE_INPUT} ${SIZE_CLASS[size]} ${className}`}
    />
  )
);

FormInput.displayName = "FormInput";

type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> & {
  size?: InputSize;
};

export const FormSelect = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ size = "md", className = "", ...props }, ref) => (
    <select
      ref={ref}
      {...props}
      className={`${BASE_INPUT} ${SIZE_CLASS[size]} ${className}`}
    />
  )
);

FormSelect.displayName = "FormSelect";
