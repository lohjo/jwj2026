"use client";

import { useState, useCallback, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface AnnouncementInputProps {
  onAnalyse: () => void;
  file: File | null;
  onFileUpload: (file: File) => void;
  announcementText: string;
  onTextChange: (text: string) => void;
  mode: "text" | "pdf";
  onModeChange: (mode: "text" | "pdf") => void;
}

export default function AnnouncementInput({
  onAnalyse,
  file,
  onFileUpload,
  announcementText,
  onTextChange,
  mode,
  onModeChange,
}: AnnouncementInputProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (f: File) => {
      if (f.type === "application/pdf") {
        onFileUpload(f);
        onModeChange("pdf");
        setPageNumber(1);
      }
    },
    [onFileUpload, onModeChange]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const canAnalyse = mode === "text" ? announcementText.trim().length > 0 : !!file;

  return (
    <div style={{ animation: "fadeIn 0.5s ease" }}>
      <div
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid rgba(255,255,255,0.07)",
          borderRadius: 12,
          padding: 24,
        }}
      >
        {/* /clarify: mode tabs in sans not mono */}
        <div className="mb-4 flex items-center justify-between">
          <div className="flex gap-1">
            {(["text", "pdf"] as const).map((m) => (
              <button
                key={m}
                onClick={() => onModeChange(m)}
                className="cursor-pointer text-[12px] font-medium transition-all"
                style={{
                  padding: "6px 14px",
                  borderRadius: 6,
                  border: mode === m
                    ? "1px solid var(--accent-border)"
                    : "1px solid rgba(255,255,255,0.07)",
                  background: mode === m ? "var(--accent-dim)" : "transparent",
                  color: mode === m ? "var(--accent)" : "rgba(255,255,255,0.3)",
                }}
              >
                {m === "text" ? "Paste text" : "Upload PDF"}
              </button>
            ))}
          </div>
          {/* /clarify: char counter in sans not mono */}
          {mode === "text" && (
            <span className="text-[12px] text-text-muted">
              {announcementText.length} chars
            </span>
          )}
        </div>

        {/* Text mode — /clarify: textarea in sans not mono, users write prose */}
        {mode === "text" && (
          <textarea
            value={announcementText}
            onChange={(e) => onTextChange(e.target.value)}
            rows={12}
            className="w-full resize-y text-[14px] leading-[1.7] outline-none"
            style={{
              background: "rgba(0,0,0,0.25)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 8,
              padding: 16,
              color: "#c8cad2",
              boxSizing: "border-box",
              fontFamily: "var(--font-sans)",
            }}
          />
        )}

        {/* PDF mode */}
        {mode === "pdf" && (
          <>
            {!file ? (
              <div
                onDrop={handleDrop}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onClick={() => fileInputRef.current?.click()}
                className="flex cursor-pointer flex-col items-center justify-center py-16 transition-all"
                style={{
                  background: isDragging ? "var(--accent-dim)" : "rgba(0,0,0,0.2)",
                  border: `1px dashed ${isDragging ? "var(--accent-border)" : "rgba(255,255,255,0.1)"}`,
                  borderRadius: 8,
                }}
              >
                <div className="mb-3 text-3xl opacity-30">&#128196;</div>
                <p className="mb-1 text-[14px] font-medium text-text-secondary">
                  Drop your PDF announcement here
                </p>
                <p className="text-[12px] text-text-muted">or click to browse</p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
                />
              </div>
            ) : (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[12px] font-medium text-text-secondary">{file.name}</span>
                  {numPages > 1 && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
                        disabled={pageNumber <= 1}
                        className="cursor-pointer text-[11px] text-text-muted disabled:opacity-30"
                        style={{ padding: "2px 8px", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 4, background: "transparent" }}
                      >
                        Prev
                      </button>
                      <span className="text-[11px] text-text-muted">{pageNumber}/{numPages}</span>
                      <button
                        onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))}
                        disabled={pageNumber >= numPages}
                        className="cursor-pointer text-[11px] text-text-muted disabled:opacity-30"
                        style={{ padding: "2px 8px", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 4, background: "transparent" }}
                      >
                        Next
                      </button>
                    </div>
                  )}
                </div>
                <div className="flex justify-center overflow-hidden rounded-lg" style={{ background: "rgba(255,255,255,0.95)" }}>
                  <Document file={file} onLoadSuccess={({ numPages: n }) => setNumPages(n)}>
                    <Page pageNumber={pageNumber} width={560} />
                  </Document>
                </div>
              </div>
            )}
          </>
        )}

        {/* /distill: flat solid CTA, no gradient, no glow  /colorize: teal not red */}
        <button
          onClick={onAnalyse}
          disabled={!canAnalyse}
          className="mt-4 w-full cursor-pointer text-[14px] font-bold tracking-wide text-white transition-all"
          style={{
            padding: "14px 24px",
            background: canAnalyse ? "var(--accent)" : "rgba(255,255,255,0.05)",
            border: "none",
            borderRadius: 8,
            cursor: canAnalyse ? "pointer" : "not-allowed",
          }}
        >
          ▶ Run Rumour Pre-Mortem
        </button>
      </div>

      {/* Demo hint */}
      <div
        className="mt-5"
        style={{
          padding: "14px 18px",
          background: "rgba(59,130,246,0.06)",
          border: "1px solid rgba(59,130,246,0.12)",
          borderRadius: 8,
        }}
      >
        <p className="m-0 text-[12px] leading-[1.6] text-text-muted">
          <span className="font-semibold text-risk-medium">Demo mode:</span>{" "}
          Pre-loaded with MOH DORSCON Orange announcement (Feb 2020). This is the event
          that triggered the Sheng Siong rice panic. ContextGuard will predict the
          rumours that <em>actually</em> emerged.
        </p>
      </div>
    </div>
  );
}
