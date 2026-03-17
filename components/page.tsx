"use client";

import { useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import ProcessingAnimation from "@/components/ProcessingAnimation";
import RumourCard from "@/components/RumourCard";
import ActionPanel from "@/components/ActionPanel";
import SummaryStats from "@/components/SummaryStats";
import PatternBar from "@/components/PatternBar";
import AnalyzedArticle from "@/components/AnalyzedArticle";
import Navbar from "@/components/Navbar";
import {
  DEMO_SCENARIO,
  DEMO_SOURCES,
  type RumourPrediction,
  type HistoricalPattern,
} from "@/data/demo-scenario";
import type { StepStatus, TopicsData } from "@/components/ProcessingAnimation";
import type { AnalyzeResponse } from "@/lib/types";

const AnnouncementInput = dynamic(() => import("@/components/AnnouncementInput"), { ssr: false });

type Step = "input" | "analyzing" | "results";

export default function DashboardPage() {
  const [step, setStep] = useState<Step>("input");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [expandedRumour, setExpandedRumour] = useState<number | null>(null);
  const [visibleRumours, setVisibleRumours] = useState(0);
  const [announcementText, setAnnouncementText] = useState(DEMO_SCENARIO.announcementText);
  const [inputMode, setInputMode] = useState<"text" | "pdf">("text");
  const [predictions, setPredictions] = useState<RumourPrediction[]>(DEMO_SCENARIO.predictions);
  const [historicalPatterns, setHistoricalPatterns] = useState<HistoricalPattern[]>(DEMO_SCENARIO.historicalPatterns);
  const [communityLeadersCount, setCommunityLeadersCount] = useState(DEMO_SCENARIO.communityLeadersCount);
  const [constituencies, setConstituencies] = useState(DEMO_SCENARIO.constituencies);
  const [displaySources, setDisplaySources] = useState<{ label: string; url: string }[]>([]);
  const [stepStatuses, setStepStatuses] = useState<Record<string, StepStatus>>({
    topics: "pending", sources: "pending", analyze: "pending",
  });
  const [topicsData, setTopicsData] = useState<TopicsData | null>(null);

  const apiResultRef = useRef<AnalyzeResponse | null>(null);
  const animationDoneRef = useRef(false);
  const [isWaitingForApi, setIsWaitingForApi] = useState(false);

  const applyResults = useCallback((data: AnalyzeResponse) => {
    setPredictions(data.predictions);
    setHistoricalPatterns(data.historicalPatterns);
    setCommunityLeadersCount(data.communityLeadersCount);
    setConstituencies(data.constituencies);
    if (data.sources?.length) setDisplaySources(data.sources);
  }, []);

  const showResults = useCallback((data: AnalyzeResponse) => {
    applyResults(data);
    setIsWaitingForApi(false);
    setStep("results");
    let r = 0;
    const interval = setInterval(() => {
      r++;
      setVisibleRumours(r);
      if (r >= data.predictions.length) clearInterval(interval);
    }, 350);
  }, [applyResults]);

  const handleAnalyse = useCallback(() => {
    setStep("analyzing");
    setDisplaySources([]);
    setTopicsData(null);
    setStepStatuses({ topics: "pending", sources: "pending", analyze: "pending" });
    apiResultRef.current = null;
    animationDoneRef.current = false;
    setIsWaitingForApi(false);

    fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: announcementText }),
    })
      .then(async (res) => {
        if (!res.body) throw new Error("No stream body");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          let currentEvent = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              currentEvent = line.slice(7);
            } else if (line.startsWith("data: ")) {
              const data = JSON.parse(line.slice(6));
              if (currentEvent === "step") {
                setStepStatuses((prev) => ({ ...prev, [data.id]: data.status }));
                if (data.id === "topics" && data.status === "done" && data.data) {
                  setTopicsData(data.data as TopicsData);
                }
              } else if (currentEvent === "source") {
                setDisplaySources((prev) => [...prev, { label: data.label, url: data.url }]);
              } else if (currentEvent === "result") {
                const result = data as AnalyzeResponse;
                if (animationDoneRef.current) showResults(result);
                else apiResultRef.current = result;
              }
            }
          }
        }
      })
      .catch(() => {
        const fallback: AnalyzeResponse = {
          predictions: DEMO_SCENARIO.predictions,
          historicalPatterns: DEMO_SCENARIO.historicalPatterns,
          communityLeadersCount: DEMO_SCENARIO.communityLeadersCount,
          constituencies: DEMO_SCENARIO.constituencies,
          sources: DEMO_SOURCES,
          fallback: true,
        };
        if (animationDoneRef.current) showResults(fallback);
        else apiResultRef.current = fallback;
      });
  }, [announcementText, showResults]);

  const handleProcessingComplete = useCallback(() => {
    animationDoneRef.current = true;
    if (apiResultRef.current) showResults(apiResultRef.current);
    else setIsWaitingForApi(true);
  }, [showResults]);

  const handleReset = () => {
    setStep("input");
    setExpandedRumour(null);
    setVisibleRumours(0);
    setPredictions(DEMO_SCENARIO.predictions);
    setHistoricalPatterns(DEMO_SCENARIO.historicalPatterns);
    setCommunityLeadersCount(DEMO_SCENARIO.communityLeadersCount);
    setConstituencies(DEMO_SCENARIO.constituencies);
    setDisplaySources([]);
    setTopicsData(null);
    setStepStatuses({ topics: "pending", sources: "pending", analyze: "pending" });
    apiResultRef.current = null;
    animationDoneRef.current = false;
    setIsWaitingForApi(false);
  };

  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-[960px] px-5 py-8">
        {/* /distill: removed glow dot  /distill: removed gradient text  /clarify: status label in sans */}
        <div className="mb-10">
          <div className="mb-2 flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-status-green" />
            <span className="text-[12px] font-medium text-text-muted">System active</span>
          </div>
          <h1 className="mb-1 text-[34px] font-black tracking-tight text-text-primary">
            ContextGuard
          </h1>
          <p className="text-[14px] text-text-muted">
            Rumour Pre-Mortem Engine — Singapore
          </p>
        </div>

        {step === "input" && (
          <AnnouncementInput
            file={uploadedFile}
            onFileUpload={setUploadedFile}
            onAnalyse={handleAnalyse}
            announcementText={announcementText}
            onTextChange={setAnnouncementText}
            mode={inputMode}
            onModeChange={setInputMode}
          />
        )}

        {step === "analyzing" && (
          <ProcessingAnimation
            stepStatuses={stepStatuses}
            sources={displaySources}
            topicsData={topicsData}
            onComplete={handleProcessingComplete}
            isWaiting={isWaitingForApi}
          />
        )}

        {step === "results" && (
          <div style={{ animation: "fadeIn 0.5s ease" }}>
            <div className="mb-7 grid grid-cols-[auto_1fr] gap-3">
              <SummaryStats predictionsCount={predictions.length} />
              <AnalyzedArticle text={announcementText} />
            </div>

            {/* Historical patterns */}
            <div
              className="mb-7"
              style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.07)",
                borderRadius: 10,
                padding: "18px 20px",
              }}
            >
              {/* /clarify: section heading in sans, primary tier */}
              <div className="mb-3.5 text-[13px] font-semibold text-text-secondary">
                Corpus pattern matches
              </div>
              {historicalPatterns.map((p, i) => (
                <div key={i} className={i < historicalPatterns.length - 1 ? "mb-2.5" : ""}>
                  <div className="mb-1 flex items-center gap-2 text-[12px] text-text-secondary">
                    <span>{p.event}</span>
                    {p.source && (
                      <a
                        href={p.source}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="shrink-0 text-[11px] text-text-muted transition-colors hover:text-text-secondary"
                      >
                        {new URL(p.source).hostname.replace(/^www\./, "")} →
                      </a>
                    )}
                  </div>
                  <PatternBar similarity={p.similarity} />
                </div>
              ))}
            </div>

            {/* Predicted rumours */}
            {/* /clarify: section heading in sans, primary tier */}
            <div className="mb-3.5 text-[13px] font-semibold text-text-secondary">
              Predicted false narratives
            </div>

            <div className="space-y-3">
              {predictions.map((prediction, i) => (
                <div
                  key={prediction.id}
                  style={{
                    opacity: i < visibleRumours ? 1 : 0,
                    transform: i < visibleRumours ? "translateY(0)" : "translateY(16px)",
                    transition: "all 0.5s cubic-bezier(0.22,1,0.36,1)",
                    transitionDelay: `${i * 0.08}s`,
                  }}
                >
                  <RumourCard
                    prediction={prediction}
                    isExpanded={expandedRumour === prediction.id}
                    onToggle={() => setExpandedRumour(expandedRumour === prediction.id ? null : prediction.id)}
                  />
                </div>
              ))}
            </div>

            <div className="mt-7">
              <ActionPanel
                communityLeadersCount={communityLeadersCount}
                constituencies={constituencies}
                predictions={predictions}
              />
            </div>

            {/* /clarify: reset as plain text link not ghost button with mono */}
            <button
              onClick={handleReset}
              className="mt-4 cursor-pointer text-[12px] font-medium text-text-muted transition-colors hover:text-text-secondary"
              style={{ background: "none", border: "none", padding: 0 }}
            >
              ← New analysis
            </button>
          </div>
        )}
      </div>
    </>
  );
}
