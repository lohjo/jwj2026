import Link from "next/link";

export default function HeroSection() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-5">
      {/* /distill: removed glow dot  /clarify: "System Active" label in sans */}
      <div className="mb-4 flex items-center gap-2">
        <div className="h-2 w-2 rounded-full bg-status-green" />
        <span className="text-[12px] font-medium text-text-muted">
          System active
        </span>
      </div>

      {/* /distill: removed gradient text — plain text-primary on dark is already clear */}
      <h1 className="mb-2 text-[48px] font-black tracking-tight text-text-primary">
        ContextGuard
      </h1>
      <p className="mb-10 text-[15px] text-text-tertiary">
        Rumour Pre-Mortem Engine — Singapore
      </p>

      <div className="flex gap-3">
        {/* /distill: flat solid accent, no gradient, no glow shadow  /colorize: teal not red */}
        <Link
          href="/dashboard"
          className="rounded-lg px-8 py-3 text-[13px] font-bold tracking-wide text-white no-underline transition-colors hover:bg-accent-hover"
          style={{ background: "var(--accent)" }}
        >
          News Outlet Dashboard
        </Link>
        <Link
          href="/community"
          className="rounded-lg border border-border-subtle px-8 py-3 text-[13px] font-semibold text-text-tertiary no-underline transition-colors hover:border-border-active hover:text-text-primary"
        >
          Community Leader Portal
        </Link>
      </div>
    </div>
  );
}
