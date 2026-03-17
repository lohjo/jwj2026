"use client";

import { useState, useEffect, useRef, useCallback } from "react";

export type StepStatus = "pending" | "running" | "done";

export interface TopicsData {
  topics: string[];
  affectedCommunities: string[];
  emotionalTriggers: string[];
}

interface ProcessingAnimationProps {
  stepStatuses: Record<string, StepStatus>;
  sources?: { label: string; url: string }[];
  topicsData?: TopicsData | null;
  onComplete: () => void;
  isWaiting?: boolean;
}

const STEP_DEFINITIONS = [
  { id: "topics",  label: "Reading the announcement" },
  { id: "sources", label: "Finding similar cases" },
  { id: "analyze", label: "Building your report" },
];

export default function ProcessingAnimation({
  stepStatuses,
  sources = [],
  topicsData = null,
  onComplete,
  isWaiting = false,
}: ProcessingAnimationProps) {
  const [collapsedSteps, setCollapsedSteps] = useState<Set<string>>(new Set());
  const allDone = STEP_DEFINITIONS.every((s) => stepStatuses[s.id] === "done");
  const completeFired = useRef(false);
  const stableOnComplete = useCallback(onComplete, [onComplete]);

  useEffect(() => {
    if (allDone && !isWaiting && !completeFired.current) {
      completeFired.current = true;
      const timer = setTimeout(stableOnComplete, 600);
      return () => clearTimeout(timer);
    }
  }, [allDone, isWaiting, stableOnComplete]);

  useEffect(() => {
    if (Object.values(stepStatuses).every((s) => s === "pending")) {
      completeFired.current = false;
      setCollapsedSteps(new Set());
    }
  }, [stepStatuses]);

  const toggleStep = (id: string) => {
    setCollapsedSteps((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const shouldShowDropdown = (id: string): boolean => {
    if (collapsedSteps.has(id)) return false;
    if (id === "topics") return topicsData !== null;
    if (id === "sources") return sources.length > 0;
    return false;
  };

  const hasData = (id: string) => id === "topics" ? topicsData !== null : id === "sources" ? sources.length > 0 : false;

  return (
    <div style={{ animation: "fadeIn 0.4s ease" }}>
      <div
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid rgba(255,255,255,0.07)",
          borderRadius: 12,
          padding: 32,
        }}
      >
        {/* /clarify: "ANALYZING" status in sans not mono */}
        <div className="mb-6 flex items-center gap-2.5">
          <div className="h-2 w-2 rounded-full bg-risk-high animate-[pulse_1s_infinite]" />
          <span className="text-[12px] font-semibold tracking-wide text-risk-high">
            Analysing
          </span>
        </div>

        {STEP_DEFINITIONS.map((stepDef) => {
          const status = stepStatuses[stepDef.id] ?? "pending";
          const isDone = status === "done";
          const isRunning = status === "running";
          const showDropdown = shouldShowDropdown(stepDef.id);
          const canToggle = hasData(stepDef.id);

          let label = stepDef.label;
          if (stepDef.id === "sources" && sources.length > 0) {
            label = `Finding similar cases (${sources.length} found)`;
          }

          return (
            <div key={stepDef.id}>
              <div
                className="flex items-center gap-3 transition-opacity duration-500"
                style={{
                  padding: "10px 0",
                  opacity: status === "pending" ? 0.2 : 1,
                  cursor: canToggle ? "pointer" : "default",
                }}
                onClick={() => canToggle && toggleStep(stepDef.id)}
              >
                <span className="w-6 text-center text-sm text-text-muted">
                  {isDone ? "✓" : isRunning ? (
                    <span className="inline-block h-2 w-2 rounded-full bg-risk-high animate-[pulse_1s_infinite]" />
                  ) : "○"}
                </span>
                {/* /clarify: step labels in sans not mono */}
                <span
                  className="text-[13px] font-medium transition-colors duration-400"
                  style={{
                    color: isDone ? "rgba(255,255,255,0.55)" : isRunning ? "#e0e3eb" : "rgba(255,255,255,0.22)",
                  }}
                >
                  {label}
                </span>
                {isRunning && !canToggle && (
                  <span className="ml-auto text-[11px] text-text-muted">processing…</span>
                )}
                {canToggle && (
                  <span
                    className="ml-auto text-[11px] text-text-muted transition-transform duration-200"
                    style={{ transform: showDropdown ? "rotate(180deg)" : "rotate(0deg)" }}
                  >
                    ▾
                  </span>
                )}
              </div>

              {/* Topics dropdown */}
              {stepDef.id === "topics" && showDropdown && topicsData && (
                <div style={{ marginLeft: 36, paddingBottom: 8, animation: "fadeIn 0.3s ease" }}>
                  {[
                    { key: "topics",              items: topicsData.topics,              color: "rgba(96,165,250,", label: "Topics" },
                    { key: "communities",         items: topicsData.affectedCommunities, color: "rgba(250,204,21,",  label: "Affected communities" },
                    { key: "emotionalTriggers",   items: topicsData.emotionalTriggers,   color: "rgba(239,68,68,",   label: "Emotional triggers" },
                  ].map(({ key, items, color, label }) => (
                    <div key={key} className="mb-2">
                      {/* /clarify: micro-labels in sans not mono */}
                      <span className="text-[11px] font-medium uppercase tracking-[0.05em] text-text-muted">
                        {label}
                      </span>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {items.map((t, i) => (
                          <span
                            key={i}
                            className="rounded-full px-2.5 py-0.5 text-[11px]"
                            style={{
                              background: `${color}0.12)`,
                              color: `${color}0.9)`,
                              border: `1px solid ${color}0.2)`,
                            }}
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Sources dropdown */}
              {stepDef.id === "sources" && showDropdown && sources.length > 0 && (
                <div style={{ marginLeft: 36, paddingBottom: 8, animation: "fadeIn 0.3s ease" }}>
                  {sources.map((source, i) => (
                    <div key={`${source.url}-${i}`} className="flex items-center gap-2" style={{ padding: "3px 0", animation: "fadeIn 0.3s ease" }}>
                      <span className="shrink-0 text-[11px] text-blue-400/60">→</span>
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="min-w-0 truncate text-[11px] text-blue-400/70 transition-colors hover:text-blue-400 hover:underline"
                      >
                        {source.label}
                      </a>
                      <span className="ml-auto shrink-0 text-[10px] text-text-muted/40">
                        {new URL(source.url).hostname}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {allDone && isWaiting && (
          <div
            style={{ borderTop: "1px solid rgba(255,255,255,0.06)", marginTop: 16, paddingTop: 16, animation: "fadeIn 0.4s ease" }}
            className="flex items-center gap-2.5"
          >
            <div className="h-2 w-2 rounded-full bg-status-green animate-[pulse_1s_infinite]" />
            {/* /clarify: finalising label in sans */}
            <span className="text-[12px] font-medium text-status-green">Finalising results…</span>
          </div>
        )}
      </div>
    </div>
  );
}
