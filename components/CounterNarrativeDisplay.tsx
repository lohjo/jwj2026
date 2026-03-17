"use client";

import { type Language } from "@/data/demo-scenario";
import CopyButton from "./CopyButton";
import LanguageToggle from "./LanguageToggle";

interface CounterNarrativeDisplayProps {
  counterNarratives: Record<Language, string>;
  sources?: { label: string; url: string }[];
  policyRecommendations?: string[];
  selectedLanguage: Language;
  onLanguageChange: (lang: Language) => void;
}

export default function CounterNarrativeDisplay({
  counterNarratives,
  sources,
  policyRecommendations,
  selectedLanguage,
  onLanguageChange,
}: CounterNarrativeDisplayProps) {
  const text = counterNarratives[selectedLanguage];

  return (
    <div className="space-y-3">
      {/* Counter-Narrative */}
      <div
        style={{
          background: "rgba(34,197,94,0.05)",
          border: "1px solid rgba(34,197,94,0.12)",
          borderRadius: 8,
          padding: "16px 18px",
        }}
      >
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {/* /clarify: section label in sans, two-tier hierarchy — primary sans semibold */}
          <span className="text-[12px] font-semibold text-status-green">
            Ready to deploy
          </span>
          <LanguageToggle selectedLanguage={selectedLanguage} onLanguageChange={onLanguageChange} />
        </div>
        <p className="m-0 text-[13px] leading-[1.75] tracking-[0.01em] text-text-secondary">
          {text}
        </p>
        <div className="mt-3">
          <CopyButton text={text} />
        </div>

        {sources && sources.length > 0 && (
          <div
            className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t pt-3"
            style={{ borderColor: "rgba(34,197,94,0.12)" }}
          >
            {/* /clarify: "Sources:" label in sans not mono */}
            <span className="text-[11px] font-medium uppercase tracking-[0.05em] text-text-muted">
              Sources:
            </span>
            {sources.map((source, i) => (
              <a
                key={i}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] text-status-green no-underline transition-opacity hover:opacity-75"
                style={{ textDecoration: "underline", textUnderlineOffset: 2 }}
              >
                {source.label}
              </a>
            ))}
          </div>
        )}
      </div>

      {/* Policy Recommendations */}
      {policyRecommendations && policyRecommendations.length > 0 && (
        <div
          style={{
            background: "rgba(59,130,246,0.05)",
            border: "1px solid rgba(59,130,246,0.12)",
            borderRadius: 8,
            padding: "16px 18px",
          }}
        >
          {/* /clarify: label in sans not mono */}
          <span className="mb-3 block text-[12px] font-semibold text-risk-medium">
            Recommended policy action
          </span>
          <p className="m-0 text-[13px] leading-[1.75] text-text-secondary">
            {policyRecommendations[0]}
          </p>
        </div>
      )}
    </div>
  );
}
