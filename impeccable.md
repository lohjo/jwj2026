# Design Context — SENTINEL

## Project
SENTINEL is a multimodal AI content detection web UI. Users paste text, upload images/audio/video,
or record voice to check for misinformation, AI-generated content, and harmful material.

## Target Audience
Singapore general public — ages 30–65, receiving forwarded WhatsApp content, wanting to quickly
verify if something is real or fake. Not technical. Use English, Mandarin, Malay, Tamil, Singlish.

## Use Cases
1. Paste forwarded WhatsApp text → get a plain-language verdict (real or fake, why)
2. Upload a suspicious image → detect manipulation or AI generation
3. Record a voice note → spoken verdict back from SENTINEL
4. Upload a video → deepfake detection + transcript analysis

## Brand Personality
- **Authoritative** — like a fact-checker (Reuters, CNA, Snopes), not an AI startup demo
- **Trustworthy** — people detecting fake news need to believe the tool is reliable
- **Accessible** — Singapore public audience, not engineers or researchers
- **Calm** — verdicts should feel measured, not alarming or gamified

## Design Direction
Editorial/institutional light theme. Inspired by Gov.sg, CNA fact-check, AP Fact Check.
NOT a dark dashboard. NOT glowing neon accents. NOT sci-fi aesthetics.

## Typography
- Display/masthead: Playfair Display (700/900) — editorial authority
- Body/UI: Plus Jakarta Sans (400/500/600/700) — refined, distinctive, not Inter
- Code/data output only: IBM Plex Mono — reserved for JSON, transcripts, file names

## Color Palette (OKLCH)
```css
--ink:           oklch(18% 0.04 260);   /* near-black with blue hint */
--ink-2:         oklch(36% 0.04 260);
--ink-3:         oklch(54% 0.03 260);
--ink-4:         oklch(70% 0.02 260);
--paper:         oklch(97.5% 0.007 80); /* warm cream white */
--paper-warm:    oklch(94.5% 0.011 72);
--paper-sunken:  oklch(91% 0.015 70);
--green:         oklch(38% 0.15 155);   /* safe / genuine */
--green-bg:      oklch(95.5% 0.04 148);
--red:           oklch(40% 0.17 25);    /* unsafe / harmful */
--red-bg:        oklch(96% 0.034 22);
--amber:         oklch(52% 0.15 66);    /* warning / inconclusive */
--amber-bg:      oklch(96% 0.03 76);
--blue:          oklch(46% 0.15 252);   /* info / insights */
--blue-bg:       oklch(96% 0.028 248);
```

## What to Avoid
- Dark mode with glowing orange/cyan accents (AI slop)
- Gradient text on headings
- Monospace fonts in navigation, tabs, or headings
- Dot grid backgrounds
- Emoji in navigation tabs
- Identical card grids (icon + heading + text × N)
- Everything wrapped in bordered cards
- Technical jargon in user-facing labels (GUARD, pipeline, parse_mode)

## Component References
See ~/.components/ for ContextGuard component patterns that SENTINEL shares:
- ProcessingAnimation → .pipeline-step SSE visualizer
- RiskBadge → .risk-badge chips
- RumourCard → .detail-card disclosures
- AnnouncementInput → text panel input area

## Related Repo
https://github.com/lohjo/hackomania2026-teamBANLUCK (ContextGuard)
— same infrastructure stack, same target audience, different detection focus
