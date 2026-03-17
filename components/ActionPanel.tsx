"use client";

import { useState, useEffect } from "react";
import { type RumourPrediction } from "@/data/demo-scenario";

interface ActionPanelProps {
  communityLeadersCount: number;
  constituencies: number;
  predictions: RumourPrediction[];
}

export default function ActionPanel({ communityLeadersCount, constituencies, predictions }: ActionPanelProps) {
  const [showModal, setShowModal] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [isErrorToast, setIsErrorToast] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
  const [telegramMemberCount, setTelegramMemberCount] = useState<number | null>(null);

  useEffect(() => {
    const fetchMemberCount = async () => {
      try {
        const res = await fetch("/api/telegram?action=count", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chatId: "@LIMIT_TEST_HACKOMAINA", message: "count_only" }),
        });
        const data = await res.json();
        if (data.memberCount) setTelegramMemberCount(data.memberCount);
      } catch {}
    };
    fetchMemberCount();
  }, []);

  useEffect(() => {
    if (showToast) {
      const timer = setTimeout(() => setShowToast(false), 5000);
      return () => clearTimeout(timer);
    }
  }, [showToast]);

  const handleConfirm = async () => {
    setIsDeploying(true);
    let hasError = false;
    let errorMessage = "";
    let memberCountStr = "";

    try {
      const counterNarrativesText = predictions
        .map(
          (p) =>
            `🚨 ${p.title}\n` +
            `EN: ${p.counterNarratives.en}\n\n` +
            `ZH: ${p.counterNarratives.zh}\n\n` +
            `MS: ${p.counterNarratives.ms}\n\n` +
            `TA: ${p.counterNarratives.ta}`
        )
        .join("\n\n=========================\n\n");

      const messageText = `🛡️ ContextGuard Alert 🛡️\n\n=========================\n\n${counterNarrativesText}`;

      const res = await fetch("/api/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chatId: "@LIMIT_TEST_HACKOMAINA", message: messageText }),
      });

      const data = await res.json();

      if (!res.ok) {
        hasError = true;
        errorMessage = data.error || "Failed to send message";
      } else {
        memberCountStr = data.memberCount ? ` and ${data.memberCount} Telegram users` : " and Telegram";
        if (data.memberCount) setTelegramMemberCount(data.memberCount);
      }
    } catch (error: any) {
      hasError = true;
      errorMessage = error.message || "Network error";
    } finally {
      setIsDeploying(false);
      setShowModal(false);
      setToastMessage(
        hasError
          ? `Error: ${errorMessage}`
          : `✓ Counter-narratives sent to ${communityLeadersCount} community leaders${memberCountStr}`
      );
      setIsErrorToast(hasError);
      setShowToast(true);
    }
  };

  const displayCount = telegramMemberCount ?? communityLeadersCount;

  return (
    <>
      {/* /distill: flat solid green, no gradient, no glow shadow */}
      <div
        className="flex flex-wrap items-center justify-between gap-3"
        style={{
          padding: "18px 22px",
          background: "rgba(34,197,94,0.06)",
          border: "1px solid rgba(34,197,94,0.14)",
          borderRadius: 10,
        }}
      >
        <div>
          <div className="text-[13px] font-semibold text-text-primary">
            Deploy to community network
          </div>
          <div className="mt-0.5 text-[12px] text-text-muted">
            Push counter-narratives to {displayCount} verified users across {constituencies} constituencies
          </div>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="cursor-pointer rounded-lg text-[13px] font-bold tracking-wide text-white transition-colors"
          style={{
            padding: "10px 28px",
            background: "#16a34a",
            border: "none",
          }}
        >
          Deploy now →
        </button>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div
            className="mx-4 w-full max-w-md"
            style={{
              background: "#141519",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 12,
              padding: 24,
              animation: "fadeInUp 0.2s ease-out",
            }}
          >
            <h3 className="mb-2 text-base font-bold text-text-primary">Confirm deployment</h3>
            <p className="mb-6 text-[13px] text-text-secondary">
              Counter-narratives will be sent to{" "}
              <span className="font-semibold text-text-primary">{displayCount} verified community leaders</span>{" "}
              across {constituencies} constituencies in 4 languages.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowModal(false)}
                disabled={isDeploying}
                className="cursor-pointer text-[12px] font-medium text-text-tertiary disabled:opacity-50"
                style={{ padding: "8px 16px", background: "transparent", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6 }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={isDeploying}
                className="flex cursor-pointer items-center justify-center gap-2 rounded-md text-[13px] font-bold text-white disabled:opacity-70"
                style={{ padding: "8px 20px", background: "#16a34a", border: "none" }}
              >
                {isDeploying ? (
                  <>
                    <div className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    Deploying…
                  </>
                ) : "Confirm & deploy"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showToast && (
        <div
          className="fixed top-4 right-4 z-50 max-w-md"
          style={{
            padding: "12px 18px",
            background: isErrorToast ? "rgba(239,68,68,0.15)" : "rgba(34,197,94,0.15)",
            border: isErrorToast ? "1px solid rgba(239,68,68,0.3)" : "1px solid rgba(34,197,94,0.3)",
            borderRadius: 8,
            animation: "fadeIn 0.3s ease",
          }}
        >
          <span className={`text-[13px] font-semibold ${isErrorToast ? "text-status-red" : "text-status-green"}`}>
            {toastMessage}
          </span>
        </div>
      )}
    </>
  );
}
