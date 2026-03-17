"use client";

import { useState } from "react";

interface CopyButtonProps {
  text: string;
  label?: string;
}

export default function CopyButton({ text, label = "Copy to clipboard" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    // /clarify: sans not mono for button label
    <button
      onClick={handleCopy}
      className="text-[12px] font-medium transition-all cursor-pointer"
      style={{
        padding: "7px 14px",
        background: copied ? "rgba(34,197,94,0.15)" : "rgba(255,255,255,0.05)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 6,
        color: copied ? "#22c55e" : "rgba(255,255,255,0.45)",
      }}
    >
      {copied ? "✓ Copied" : label}
    </button>
  );
}
