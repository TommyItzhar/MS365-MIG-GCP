import { C } from "../theme.js";

export const Card = ({ children, style = {}, padding = 20 }) => (
  <div style={{
    background: C.surface, border: `1px solid ${C.border}`,
    borderRadius: 8, padding,
    boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
    ...style,
  }}>
    {children}
  </div>
);

export const SectionHeader = ({ title, subtitle, accent = C.ms, action }) => (
  <div style={{
    display: "flex", justifyContent: "space-between", alignItems: "flex-end",
    marginBottom: 24, paddingBottom: 16, borderBottom: `1px solid ${C.border}`,
  }}>
    <div>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: C.text, letterSpacing: "-0.01em" }}>
        {title}
      </h1>
      {subtitle && (
        <p style={{ margin: "4px 0 0", color: C.textMuted, fontSize: 13 }}>
          {subtitle}
        </p>
      )}
    </div>
    {action}
  </div>
);

export const StatCard = ({ label, value, hint, accent = C.ms, icon }) => (
  <Card>
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, letterSpacing: "0.06em", textTransform: "uppercase" }}>
          {label}
        </div>
        <div style={{ fontSize: 26, fontWeight: 700, color: C.text, marginTop: 4, letterSpacing: "-0.02em" }}>
          {value}
        </div>
        {hint && (
          <div style={{ fontSize: 11, color: C.textLight, marginTop: 2 }}>
            {hint}
          </div>
        )}
      </div>
      {icon && (
        <div style={{
          width: 36, height: 36, borderRadius: 8,
          background: `${accent}15`, color: accent,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 16,
        }}>
          {icon}
        </div>
      )}
    </div>
  </Card>
);

export const Badge = ({ children, color = "info", size = "md" }) => {
  const colors = {
    success: { bg: C.successLight, fg: C.success },
    warning: { bg: C.warningLight, fg: C.warning },
    danger:  { bg: C.dangerLight,  fg: C.danger },
    info:    { bg: C.infoLight,    fg: C.info },
    neutral: { bg: C.slateLight,   fg: C.slate },
  }[color] || { bg: C.slateLight, fg: C.slate };
  const padding = size === "sm" ? "1px 8px" : "3px 10px";
  const fontSize = size === "sm" ? 10 : 11;
  return (
    <span style={{
      padding, borderRadius: 12, fontSize, fontWeight: 700,
      background: colors.bg, color: colors.fg,
      letterSpacing: "0.02em", textTransform: "uppercase", display: "inline-block",
    }}>
      {children}
    </span>
  );
};

export const Button = ({ children, onClick, variant = "primary", size = "md", disabled, style = {} }) => {
  const sizes = {
    sm: { padding: "5px 12px", fontSize: 12 },
    md: { padding: "8px 16px", fontSize: 13 },
    lg: { padding: "10px 20px", fontSize: 14 },
  };
  const variants = {
    primary:   { bg: C.ms, fg: "#fff", border: "none" },
    secondary: { bg: "transparent", fg: C.ms, border: `1.5px solid ${C.ms}` },
    success:   { bg: C.success, fg: "#fff", border: "none" },
    danger:    { bg: "transparent", fg: C.danger, border: `1.5px solid ${C.danger}` },
    ghost:     { bg: "transparent", fg: C.textMuted, border: `1px solid ${C.border}` },
  };
  const s = sizes[size];
  const v = variants[variant];
  return (
    <button onClick={onClick} disabled={disabled}
      style={{
        ...s, borderRadius: 6, fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        background: v.bg, color: v.fg, border: v.border,
        opacity: disabled ? 0.5 : 1, transition: "all 0.15s",
        ...style,
      }}>
      {children}
    </button>
  );
};

export const Empty = ({ icon = "📄", title, subtitle, action }) => (
  <div style={{
    padding: "60px 20px", textAlign: "center",
    border: `1px dashed ${C.borderStrong}`, borderRadius: 12,
    background: C.surfaceAlt,
  }}>
    <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.5 }}>{icon}</div>
    <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 6 }}>{title}</div>
    {subtitle && <div style={{ fontSize: 13, color: C.textMuted, marginBottom: 16, maxWidth: 480, margin: "0 auto 16px" }}>{subtitle}</div>}
    {action}
  </div>
);
