All four tools are real and I can give you a concrete breakdown of each. One small correction — it's **MiroFish**, not Microfish.

---

## Tool-by-Tool Breakdown

---

### 1. Promptfoo — Prompt Testing + Red Teaming
Open source CLI and library for evaluating and red-teaming LLM apps. Runs completely locally — evals run on your machine and talk directly with the LLM. No data leaves your environment.

**What it does for SENTINEL:**
- Tests every prompt in `pipeline/insights.py`, `pipeline/detector.py`, `pipeline/guard.py` against expected outputs
- Red teams across multiple languages — particularly valuable since many LLMs have weaker safety protections in non-English languages. Critical for SENTINEL's EN/ZH/MS/TA/Singlish support
- OWASP LLM Top 10, MITRE ATLAS, and custom policy presets built in — tests jailbreaks, prompt injection, PII leakage, harmful output

**Install:**
```bash
npm install -g promptfoo
promptfoo redteam init sentinel-redteam
```

**SENTINEL-specific config (`promptfooconfig.yaml`):**
```yaml
prompts:
  - file://pipeline/insights.py:SENTINEL_LIVE_PERSONA
  - file://pipeline/detector.py:MISINFO_PROMPT

targets:
  - id: gemini
    config:
      apiKey: ${GEMINI_API_KEY}
      model: gemini-2.5-flash

redteam:
  purpose: >
    AI content detection assistant for Singapore users.
    Analyses text, images, audio and video for AI generation
    and misinformation. Serves general public including minors.
  language:
    - en
    - zh
    - ms
    - ta
  plugins:
    - harmful          # tests violent, hate, self-harm outputs
    - pii              # tests personal data leakage
    - prompt-injection # tests instruction hijacking
    - jailbreak        # tests safety bypass
    - owasp:llm        # full OWASP LLM Top 10
  numTests: 50
```

---

### 2. MiroFish — Swarm Intelligence Prediction Engine
Extracts real-world seed data such as breaking news, policy drafts and financial signals, builds a knowledge graph, then simulates thousands of AI agents with personalities, memory and behavioural logic interacting within a digital sandbox. At the end users can review results and chat with simulated individuals to understand the reasoning behind their decisions.

Generates thousands of AI Agents, each with independent personalities, memories, and behavior logic. Lets these Agents interact freely on simulated Twitter and Reddit.

**What it does for SENTINEL:**

This is your proactive threat intelligence layer. Instead of waiting for users to send content for detection, MiroFish simulates how a piece of misinformation would spread — predicting scam narratives, fake news patterns, and AI-generated content trends *before* they reach your users.

**Integration with `research_agent/`:**
```python
# research_agent/predictor.py
# Feed MiroFish seed data from Firecrawl search results
# → MiroFish simulates spread across Singapore social networks
# → Output: predicted scam/misinformation trends
# → Store in research/skills/ for SENTINEL's detection context

async def predict_misinfo_trends(topic: str) -> dict:
    """
    1. Firecrawl scrapes current news on topic
    2. MiroFish seeds agents with this data
    3. Simulates spread across SG social groups
    4. Returns predicted narrative patterns
    """
```

**Important caveat:** LLM costs add up — running hundreds of agents through multiple simulation rounds means lots of API calls. The README recommends starting with fewer than 40 rounds to manage costs. It's still at v0.1.0 — powerful in concept but still maturing.

---

### 3. Impeccable — Frontend Design Skills
Enhanced frontend-design skill with deeper expertise and more control. 17 commands that form the language of design. Works with Cursor, Claude Code, Gemini CLI, and Codex CLI.

Explicit anti-patterns: overused fonts, gray text on colored backgrounds, nesting cards excessively, bad easing curves.

**Install for Claude Code:**
```bash
npx skills add pbakaus/impeccable
# Auto-detects Claude Code and places files in .claude/
```

**The three commands you mentioned:**

| Command | What it does for SENTINEL |
|---|---|
| `/distill` | Strips the web frontend (for the Live API demo page) to its essential form — removes clutter, enforces hierarchy |
| `/colorize` | Applies SENTINEL brand colours (orange `#F97316` + dark `#111827` from the pitch deck) strategically |
| `/animate` | Adds purposeful micro-interactions to the live audio waveform, detection result reveals, and verdict cards |

**The full 17 commands also include** `/audit` (accessibility + contrast check), `/polish` (pre-ship refinement), `/bolder` (makes safe designs more visually interesting), and `/delight` (adds personality).

---

### 4. OpenViking — Agent Context Database
Unifies the management of context — memory, resources, and skills — through a file system paradigm, enabling hierarchical context delivery and self-evolving agents.

L0/L1/L2 tiered context loading: agents read summaries first and load full content only when needed, reducing token usage. L0 is a one-sentence abstract (~100 tokens), L1 is an overview with core information (~2k tokens), L2 is full original content loaded only when necessary.

**Install:**
```bash
pip install openviking
```

**What it replaces in SENTINEL:**

Right now `research_agent/skill_cache.py` uses flat `.md` files with cosine similarity. OpenViking replaces this with a proper hierarchical context database:

```
viking://
├── resources/
│   ├── detection/          # SEA-LION GUARD docs, Gemini API docs
│   ├── singapore/          # SG-specific scam/misinfo knowledge
│   └── firecrawl_cache/    # Scraped pages from research agent
├── memory/
│   ├── user/               # Per-user language preference, history
│   └── agent/              # SENTINEL's accumulated detection patterns
└── skills/
    ├── guard_detection/     # How to interpret GUARD verdicts
    ├── misinfo_detection/   # Known misinfo patterns by type
    └── image_manipulation/  # Visual artifact signatures
```

**The key benefit for SENTINEL:** When `research_agent` builds skill cards, instead of loading the entire `.md` into the context window, OpenViking loads L0 (~100 tokens) first, then L1 (~2k tokens) if relevant, and only L2 (full content) if the detection task actually needs it. This loop enables Agents to refine their internal logic and learn from historical interactions without manual data restructuring.

---

## How They Work Together in SENTINEL

```
User sends content to Telegram
         ↓
OpenViking L0/L1 loads relevant detection context (low token cost)
         ↓
Detection pipeline runs (guard + misinfo + manipulation)
         ↓
MiroFish prediction context injected (is this a known emerging scam pattern?)
         ↓
Gemini Live API delivers spoken verdict
         ↓
Promptfoo CI/CD gate ran before this deploy — confirmed no jailbreaks, no PII leakage
         ↓
Impeccable-designed web frontend shows result visually
         ↓
OpenViking session manager extracts this detection as agent memory for next time
```

---

## Priority for the Hackathon

Given the March 16 deadline:

| Tool | Effort | Hackathon value | Do it? |
|---|---|---|---|
| **Impeccable** | 30 min (one install command) | High — demo looks professional | ✅ Now |
| **Promptfoo** | 2 hours (write config + run) | High — judges care about safety | ✅ Today |
| **OpenViking** | Half day | Medium — token savings visible in demo | ⚠️ If time |
| **MiroFish** | Full day + API costs | Medium — impressive but v0 maturity risk | ⚠️ Post-hackathon |