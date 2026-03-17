import type { RiskLevel } from "@/data/demo-scenario";

interface RiskBadgeProps {
  risk: RiskLevel;
  score?: number;
}

const styles: Record<RiskLevel, { bg: string; border: string; text: string }> = {
  CRITICAL: { bg: "rgba(239,68,68,0.12)",  border: "rgba(239,68,68,0.28)",  text: "#ef4444" },
  HIGH:     { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.28)", text: "#f59e0b" },
  MEDIUM:   { bg: "rgba(59,130,246,0.10)", border: "rgba(59,130,246,0.24)", text: "#3b82f6" },
  LOW:      { bg: "rgba(34,197,94,0.10)",  border: "rgba(34,197,94,0.24)",  text: "#22c55e" },
};

export default function RiskBadge({ risk, score }: RiskBadgeProps) {
  const s = styles[risk];
  return (
    /* /distill: removed glow boxShadow  /clarify: label in sans not mono */
    <span
      className="inline-flex items-center rounded-md text-[11px] font-bold tracking-[0.05em]"
      style={{
        background: s.bg,
        border: `1px solid ${s.border}`,
        color: s.text,
        padding: "3px 10px",
        /* no boxShadow */
      }}
    >
      {risk}{score !== undefined && <>&nbsp;— {score}%</>}
    </span>
  );
}
