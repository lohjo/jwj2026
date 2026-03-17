"use client";

import { useState } from "react";
import { type RumourPrediction, type Language } from "@/data/demo-scenario";
import RiskBadge from "./RiskBadge";
import CounterNarrativeDisplay from "./CounterNarrativeDisplay";

interface RumourCardProps {
  prediction: RumourPrediction;
  isExpanded: boolean;
  onToggle: () => void;
}

export default function RumourCard({ prediction, isExpanded, onToggle }: RumourCardProps) {
  const [language, setLanguage] = useState<Language>("en");

  return (
    <div
      className="rumour-card"
      style={{
        background: isExpanded ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.025)",
        border: `1px solid ${isExpanded ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.06)"}`,
        borderRadius: 10,
        overflow: "hidden",
        transition: "all 0.3s ease",
      }}
    >
      {/* Header */}
      <div
        onClick={onToggle}
        className="flex cursor-pointer items-start gap-3.5"
        style={{ padding: "16px 20px" }}
      >
        <div className="min-w-[24px] pt-0.5 text-center text-sm text-text-muted">
          {isExpanded ? "▾" : "▸"}
        </div>
        <div className="flex-1">
          <div className="mb-2">
            <RiskBadge risk={prediction.risk} />
          </div>
          <h3 className="m-0 text-[15px] font-semibold leading-[1.4] text-text-primary">
            &ldquo;{prediction.title}&rdquo;
          </h3>
          {/* /clarify: metadata labels in sans not mono */}
          <div className="mt-2 flex flex-wrap gap-4">
            <span className="text-[12px] text-text-muted">
              <span className="text-text-tertiary">Channel:</span>{" "}
              {prediction.channel}
            </span>
            <span className="text-[12px] text-text-muted">
              <span className="text-text-tertiary">Trigger:</span>{" "}
              {prediction.trigger}
            </span>
          </div>
        </div>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div style={{ padding: "0 20px 20px 56px", animation: "fadeIn 0.3s ease" }}>
          {/* Historical match */}
          <div
            style={{
              background: "rgba(245,158,11,0.06)",
              border: "1px solid rgba(245,158,11,0.12)",
              borderRadius: 8,
              padding: "12px 14px",
              marginBottom: 16,
            }}
          >
            {/* /clarify: label in sans not mono */}
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-risk-high">
              Historical pattern
            </div>
            <p className="m-0 text-[12px] leading-[1.6] text-text-secondary">
              {prediction.historicalMatch}
            </p>
          </div>

          {/* Demographic risk */}
          <div className="mb-4 text-[12px] text-text-muted">
            <span className="font-semibold text-text-tertiary">Demographic risk:</span>{" "}
            {prediction.demographicRisk}
          </div>

          <CounterNarrativeDisplay
            counterNarratives={prediction.counterNarratives}
            sources={prediction.sources}
            policyRecommendations={prediction.policyRecommendations}
            selectedLanguage={language}
            onLanguageChange={setLanguage}
          />
        </div>
      )}
    </div>
  );
}
