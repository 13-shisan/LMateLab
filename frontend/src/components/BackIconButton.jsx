import React from "react";
import { useNavigate } from "react-router-dom";

export default function BackIconButton({
  to = "/dashboard",
  title = "返回",
  ariaLabel = "返回",
  className = "icon-btn",
  style,
}) {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      className={className}
      onClick={() => navigate(to)}
      aria-label={ariaLabel}
      title={title}
      style={style}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M15 18l-6-6 6-6"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
