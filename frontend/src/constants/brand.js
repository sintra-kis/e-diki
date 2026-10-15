import { useState } from "react";

export const LOGO = "https://customer-assets-7cd3h4nn.emergentagent.net/job_court-status-1/artifacts/8g1p368q_9519CD99-02D9-45EC-8498-7F28C7332E12.png";

export function Logo({ size = 36, className = "" }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;   // never show a broken-image icon if the asset is unreachable
  return (
    <img src={LOGO} alt="" width={size} height={size} onError={() => setFailed(true)}
      style={{ width: size, height: size, objectFit: "contain" }}
      className={className} data-testid="brand-logo" />
  );
}

export function Wordmark({ logoSize = 32, className = "" }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <Logo size={logoSize} />
      <span className="font-bold text-[17px] tracking-tight">
        e-diki<span style={{ color: "var(--gold)" }}>Μου</span>
      </span>
    </div>
  );
}
