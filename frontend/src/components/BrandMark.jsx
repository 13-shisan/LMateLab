// frontend/src/components/BrandMark.jsx
import logo from "../assets/logo/Logo.png";

export default function BrandMark({ className = "" }) {
  return (
    <div
      className={className}
      style={{ display: "flex", alignItems: "center", gap: 12 }}
    >
      <img className="topbar-logo-img" src={logo} alt="Logo" />
      <div>
        <div className="topbar-title-cn">低维材料科学实验室</div>
        <div className="topbar-title-en">Low-Dimensional Materials Science Lab</div>
      </div>
    </div>
  );
}