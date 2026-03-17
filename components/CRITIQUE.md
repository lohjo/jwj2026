# /critique — ContextGuard Design Audit
# Source: lohjo/hackomania2026-teamBANLUCK (actual source, not reconstructed)
# Date: 2026-03-17

---

## VERDICT: 7 distinct anti-patterns. Commands: /distill /clarify /colorize

---

## Anti-Pattern 1 — Dot-grid body::before [DISTILL]
**File**: app/globals.css, line ~57
```css
body::before {
  background-image: radial-gradient(rgba(255,255,255,0.015) 1px, transparent 1px);
  background-size: 32px 32px;
}
```
No meaning. One of the top-3 most-cargo-culted AI UI motifs of 2024.
**Fix**: Delete.

---

## Anti-Pattern 2 — Gradient text on every H1 [DISTILL]
**Files**: components/HeroSection.tsx, app/dashboard/page.tsx
```tsx
style={{
  background: "linear-gradient(135deg, #e2e4ea 0%, #8b8fa3 100%)",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
}}
```
Grey → grey gradient. Adds zero information, creates visual shimmer noise.
**Fix**: `className="text-text-primary"` — the text is already near-white on dark. Done.

---

## Anti-Pattern 3 — JetBrains Mono used as general UI chrome [CLARIFY]
**Every** component uses font-mono for things that are not machine output:

| Component | Misuse |
|-----------|--------|
| Navbar.tsx | Logo text "ContextGuard" in font-mono |
| Navbar.tsx | Nav links (Home, Dashboard) in font-mono |
| HeroSection.tsx | "System Active" status label in font-mono |
| dashboard/page.tsx | "System Active" + section labels in font-mono |
| AnnouncementInput.tsx | Tab buttons ("Paste Text", "Upload PDF") in font-mono |
| AnnouncementInput.tsx | Char counter in font-mono |
| AnnouncementInput.tsx | **TEXTAREA** in font-mono — user types their announcement in monospace |
| CopyButton.tsx | Button label in font-mono |
| RiskBadge.tsx | Risk level labels (CRITICAL/HIGH) in font-mono |
| ProcessingAnimation.tsx | "ANALYZING" header in font-mono |
| ProcessingAnimation.tsx | Step section labels (Topics, Communities, Triggers) in font-mono |
| CounterNarrativeDisplay.tsx | "Ready-to-Deploy Counter-Narrative" in font-mono |
| CounterNarrativeDisplay.tsx | "Sources:" in font-mono |
| RumourCard.tsx | "Historical Pattern Match" label in font-mono |
| SummaryStats.tsx | Stat labels use uppercase tracking (borderline) |

Mono is reserved for machine output (JSON panels, raw API responses, confidence scores).
Everything in the table above is human-facing UI chrome.
**Fix**: Replace `font-mono text-[11px]` → `text-xs font-medium` (Source Sans 3 via --font-sans).

---

## Anti-Pattern 4 — Glowing status dots [DISTILL]
**Files**: Navbar.tsx, HeroSection.tsx, dashboard/page.tsx (all three)
```tsx
<div className="h-2 w-2 rounded-full bg-accent-green shadow-[0_0_10px_rgba(34,197,94,0.5)]" />
```
The `shadow-[0_0_10px_...]` bloom was a Vercel/Linear trope in 2023. Here it signals "system online" for what is a demo tool.
**Fix**: Remove shadow. Keep the dot as a flat circle indicator. Or remove entirely — "System Active" is obvious if the page loads.

---

## Anti-Pattern 5 — Gradient CTA buttons [DISTILL]
**Files**: AnnouncementInput.tsx, ActionPanel.tsx, HeroSection.tsx
```tsx
// AnnouncementInput.tsx
background: "linear-gradient(135deg, #ef4444, #dc2626)"
boxShadow: "0 4px 24px rgba(239,68,68,0.25)"

// ActionPanel.tsx
background: "linear-gradient(135deg, #22c55e, #16a34a)"
boxShadow: "0 4px 20px rgba(34,197,94,0.25)"
```
Two-stop same-hue gradient that only diverges by ~15% lightness. Functionally invisible; adds no affordance, just complexity. The glow shadow blooms off the button.
**Fix**: Flat `#dc2626` and `#16a34a`. Remove boxShadow.

---

## Anti-Pattern 6 — RiskBadge glow shadows [DISTILL]
**File**: components/RiskBadge.tsx
```tsx
CRITICAL: { glow: "0 0 12px rgba(239,68,68,0.2)" },
HIGH:     { glow: "0 0 12px rgba(245,158,11,0.15)" },
```
Risk badges are semantic data labels. They should communicate risk level through colour alone. Ambient glows don't add signal; they add visual noise.
**Fix**: Remove all `glow` properties from the styles record.

---

## Anti-Pattern 7 — UPPERCASE tracking label pattern used on everything [CLARIFY]
Throughout the app, section labels follow this pattern:
```tsx
className="font-mono text-[10px] font-bold tracking-[0.08em] uppercase text-text-tertiary"
```
Applied to: "Historical Pattern Match", "Ready-to-Deploy Counter-Narrative", "Sources:", 
"Topics", "Affected Communities", "Emotional Triggers", "ANALYZING", "Corpus Pattern Matches",
"Predicted False Narratives", "Predicted Rumours" stat label.

Uppercase tracking labels are a design shorthand for "category header" — but when every single
section uses the exact same treatment, hierarchy collapses. There is no visual difference between
a primary section heading and a tertiary metadata label.
**Fix**: Two tiers only:
  - Primary section headings: `text-[13px] font-semibold text-text-secondary` (no uppercase, no mono)
  - Tertiary metadata micro-labels: `text-[11px] text-text-muted tracking-[0.05em] uppercase` (sans, not mono)

---

## BONUS — pdfjs worker hardcoded to unpkg CDN [TECHNICAL]
**File**: components/AnnouncementInput.tsx line 7
```ts
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
```
If unpkg is down, PDF upload silently breaks with no error state.
**Fix**: Bundle the worker locally via next.config.ts, or use a `try/catch` with user-facing error.

---

## COMMANDS TO RUN (in order)

1. `/distill` — dot-grid, gradient text, gradient buttons, glow shadows, status dot bloom
2. `/clarify` — font-mono overuse in all UI chrome, uppercase label hierarchy collapse, textarea in monospace
3. `/colorize` — optional: the red (#ef4444) primary accent reads as "error/danger" system-wide even on neutral actions (Analyse CTA, focus ring, selection highlight). Consider shifting primary action colour to a less alarming hue — deep teal or forest green for trust register.

