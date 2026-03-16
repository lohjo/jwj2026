# ContextGuard Component Library
# Source: lohjo/hackomania2026-teamBANLUCK
# Stack: Next.js 16 + React 19 + TypeScript 5 + Tailwind CSS 4 + Gemini 2.5 Flash

## Design System (app/globals.css)

### CSS Custom Properties
```css
:root {
  /* Risk colours */
  --risk-critical: #ef4444;
  --risk-high:     #f59e0b;
  --risk-medium:   #3b82f6;   /* blue, not orange */
  --risk-low:      #22c55e;

  /* Text hierarchy */
  --text-primary:   rgba(255,255,255,0.95);
  --text-secondary: rgba(255,255,255,0.75);
  --text-muted:     rgba(255,255,255,0.45);

  /* Surfaces */
  --bg-primary:   #0f172a;  /* slate-900 */
  --bg-secondary: #1e293b;  /* slate-800 */
  --bg-card:      rgba(255,255,255,0.04);

  /* Accent */
  --accent:        #f97316;  /* orange-500 */
  --accent-hover:  #ea580c;

  /* Radius */
  --radius:    12px;
  --radius-sm: 8px;
}
```

### Typography
- **Heading font**: Source Sans 3 (Google Fonts)
- **Monospace**: JetBrains Mono (used for badges, tabs, counters — overused)
- **Body**: system-ui fallback

### Tailwind CSS 4 Pattern
Uses `@theme inline` block in globals.css to bridge CSS variables → Tailwind utilities:
```css
@theme inline {
  --color-risk-critical: var(--risk-critical);
  --color-accent: var(--accent);
}
```

---

## Components

### RumourCard.tsx
**Purpose**: Expandable prediction card for a single false narrative  
**Props**: `rumour: PredictedRumour`, `index: number`  
**Patterns**:
- Click-to-expand accordion
- `useState` for open/closed
- Risk badge colour-coded by `risk_level`
- Embedded `CounterNarrativeDisplay` when expanded
- `PatternBar` for historical similarity score
- Staggered entrance: `animation-delay: {index * 100}ms`

**Design issues**:
- Card heading uses JetBrains Mono (should be sans)
- Identical card grid — every rumour card same visual weight
- No dominant card treatment for CRITICAL vs LOW

---

### AnnouncementInput.tsx
**Purpose**: Dual-mode input — plain text OR PDF upload  
**Props**: `onAnalyse: (text: string) => void`, `isLoading: boolean`  
**Patterns**:
- `react-pdf` / `pdfjs-dist` for client-side PDF parsing
- PDF worker loaded from `unpkg.com` (fragile CDN dependency)
- `next/dynamic` import (PDF.js is heavy)
- Drag-and-drop zone with dashed border on hover
- Character counter (uses JetBrains Mono — should be sans)
- Textarea uses JetBrains Mono for user input (wrong — prose, not code)

---

### ProcessingAnimation.tsx
**Purpose**: Real-time step visualization during SSE pipeline  
**Props**: `steps: PipelineStep[]`, `sources: Source[]`  
**Patterns**:
- Three-step state machine: `pending → running → done`
- Expandable "Sources" and "Topics" panels
- Opacity dimming for completed steps
- Color-coded topic tags by category
- SSE `step` and `source` events drive state updates
- **Well-designed** — this is the best component in the repo

---

### CounterNarrativeDisplay.tsx
**Purpose**: 4-language toggle for counter-narratives  
**Props**: `counterNarratives: CounterNarratives`, `sources: Source[]`  
**Patterns**:
- Language tab buttons: EN / 中文 / Bahasa / தமிழ்
- `useState` for active language
- Source citation list below narrative
- Copy-to-clipboard via `CopyButton`

---

### ActionPanel.tsx
**Purpose**: Telegram deployment confirmation modal  
**Props**: `rumours: PredictedRumour[]`, `onDeploy: () => void`  
**Patterns**:
- Modal with backdrop blur
- Async member count fetch from Telegram Bot API
- Confirmation step before send
- Uses `dialog`-like overlay (but not `<dialog>` element)
- No keyboard trap / focus management

---

### RiskBadge.tsx
**Purpose**: Colour-coded pill badge for CRITICAL / HIGH / MEDIUM / LOW  
**Props**: `level: RiskLevel`  
**Patterns**:
- Tailwind `cn()` for conditional class merging
- Background + text colour from CSS variables
- JetBrains Mono text (arguably appropriate for badge labels)

---

### PatternBar.tsx
**Purpose**: Historical similarity bar chart (mini bar for each matched event)  
**Props**: `patterns: HistoricalPattern[]`  
**Patterns**:
- CSS width-based bars, no canvas/SVG
- Percentage similarity drives bar width
- No accessible labels / ARIA roles on bars

---

### CopyButton.tsx
**Purpose**: Copy-to-clipboard with "Copied ✓" feedback  
**Props**: `text: string`, `className?: string`  
**Patterns**:
- `navigator.clipboard.writeText`
- 2s timeout then reset
- JetBrains Mono label (should be sans)

---

### SummaryStats.tsx
**Purpose**: Risk count summary strip (N Critical, N High, N Medium, N Low)  
**Props**: `rumours: PredictedRumour[]`  
**Patterns**:
- Four-column grid
- Each cell: large number + label
- JetBrains Mono for numbers (arguably appropriate)
- **Same visual weight as everything else** — should be part of dominant verdict block

---

### HeroSection.tsx
**Purpose**: Landing page hero — headline + CTA  
**Props**: none  
**Patterns**:
- Gradient text on H1 (`background-clip: text`) — AI slop anti-pattern
- Large orange CTA button
- Tagline text in secondary colour

---

### Navbar.tsx
**Purpose**: Top navigation bar  
**Props**: none  
**Patterns**:
- `sticky top-0 z-50`
- Logo + nav links
- Status dot (glowing green — anti-pattern)
- "System Active" label in JetBrains Mono

---

### LanguageToggle.tsx
**Purpose**: UI language preference toggle (separate from counter-narrative language)  
**Props**: `lang: string`, `onChange: (lang: string) => void`  
**Patterns**:
- Four buttons: EN / ZH / MS / TA
- Shared state via Context or prop drilling

---

### CommunityAlertCard.tsx
**Purpose**: Alert card for deploying to community leaders  
**Props**: `narrative: string`, `languages: string[]`  
**Patterns**:
- Green success variant of card
- Telegram icon
- Deploy status indicator

---

### AnalyzedArticle.tsx
**Purpose**: Source article preview card with credibility score  
**Props**: `source: Source`  
**Patterns**:
- Domain favicon
- Credibility score bar
- Expandable content preview

---

## App Shell (app/dashboard/page.tsx)

**State management**: 10+ `useState` hooks — needs `useReducer`  
**SSE consumption**:
```ts
const res = await fetch('/api/analyze', { method: 'POST', body: ... });
const reader = res.body.getReader();
// event types: 'step' | 'source' | 'result'
```
**Staggered card animation**:
```ts
setTimeout(() => setVisibleCards(prev => [...prev, i]), i * 350)
```
**Coordination pattern**:
```ts
const apiResultRef = useRef(null);
const animationDoneRef = useRef(false);
// Both must be true before showing results
```

---

## Type Definitions (lib/types.ts)

```ts
type RiskLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

interface PredictedRumour {
  id: string;
  risk_level: RiskLevel;
  claim: string;
  spread_channel: string;
  demographic_risk: string[];
  historical_match: { event: string; similarity: number };
  counter_narratives: CounterNarratives;
  sources: string[];
  policy_recommendations: string[];
}

interface CounterNarratives {
  en: string; zh: string; ms: string; ta: string;
}

interface PipelineStep {
  id: string;
  status: 'pending' | 'running' | 'done';
  label: string;
  data?: unknown;
}

interface Source {
  url: string;
  title: string;
  domain: string;
  credibility_score: number;
  snippet?: string;
}
```