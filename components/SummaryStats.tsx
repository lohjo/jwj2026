interface SummaryStatsProps {
  predictionsCount?: number;
}

export default function SummaryStats({ predictionsCount = 4 }: SummaryStatsProps) {
  return (
    <div
      style={{
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: 10,
        padding: "16px 18px",
      }}
    >
      {/* /clarify: stat label in sans, two-tier hierarchy */}
      <div className="text-[11px] font-medium uppercase tracking-[0.05em] text-text-muted">
        Predicted rumours
      </div>
      <div className="text-[28px] font-black tracking-tight text-text-primary">
        {predictionsCount}
      </div>
      <div className="mt-0.5 text-[11px] text-text-muted">
        across {predictionsCount} language communities
      </div>
    </div>
  );
}
