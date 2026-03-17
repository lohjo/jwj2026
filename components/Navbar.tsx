"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/dashboard", label: "Dashboard" },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-border-subtle bg-bg-primary/80 backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-[960px] items-center justify-between px-5">
        {/* /distill: removed glow shadow from dot  /clarify: logo in sans not mono */}
        <Link
          href="/"
          className="flex items-center gap-2 text-sm font-semibold tracking-tight text-text-primary"
        >
          <div className="h-2 w-2 rounded-full bg-status-green" />
          <span className="text-[13px] font-semibold text-text-secondary">
            ContextGuard
          </span>
        </Link>
        {/* /clarify: nav links in sans, not mono */}
        <div className="flex gap-0.5">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                pathname === link.href
                  ? "bg-[rgba(255,255,255,0.07)] text-text-primary"
                  : "text-text-muted hover:text-text-secondary"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
