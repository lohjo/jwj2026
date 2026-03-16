# Verify Hackathon Compliance

Run a full compliance check against the Gemini Live Agent Challenge requirements.
Produces a checklist showing exactly what is and is not satisfied before submission.

## What to check

Read `CLAUDE.md` → "Hackathon Compliance Map" and "Hackathon Submission Checklist".
Then verify each item against the live codebase and deployment.

## Technical requirements audit

### 1. Gemini model usage
```bash
grep -rn "gemini" pipeline/ media/ config.py --include="*.py"
```
Must find: `gemini-2.5-flash` for detection AND `gemini-2.0-flash-live-001` for Live API.

### 2. Google GenAI SDK or ADK
```bash
grep -rn "from google" pipeline/ media/ --include="*.py"
grep -rn "google.adk" pipeline/ --include="*.py"
```
Must find: `from google import genai` AND `google.adk` usage.

### 3. Google Cloud service
```bash
gcloud run services describe sentinel --region asia-southeast1 2>&1
```
Must return a live service URL, not an error.

### 4. Live API mandatory tech (Live Agents category)
```bash
cat media/live.py
grep -n "live.connect\|LiveConnectConfig\|live_voice_exchange" media/live.py
grep -n "live_voice_exchange\|handle_audio" telegram_bot.py
```
Must find: Live API WebSocket usage wired into `handle_audio`.

### 5. Multimodal inputs
```bash
grep -n "handle_text\|handle_photo\|handle_audio\|handle_video" telegram_bot.py
```
Must find all four handlers registered.

## Submission artifacts audit

For each required submission item, report status:

```
[ ] Text description — DevPost draft written?
      Check: does docs/devpost_submission.md exist?

[ ] Public GitHub repo with README
      Check: git remote -v shows a public repo URL
      Check: README.md has spin-up instructions (docker run or pip install steps)

[ ] GCP deployment proof
      Check: gcloud run services describe sentinel returns active URL
      Check: does docs/gcp_proof.mp4 or docs/gcp_proof.png exist?

[ ] Architecture diagram
      Check: does docs/architecture_diagram.png exist?
      Note: ARCHITECTURE.md has the text version — export it as PNG for DevPost

[ ] Demo video
      Check: does docs/demo_video.mp4 exist? Is it under 4 minutes?
      Must show: voice note in → spoken verdict out (Live API)
      Must show: image manipulation detection working
      Must show: multilingual input (ZH or MS)
```

## Bonus points audit

```
[ ] Social post with #GeminiLiveAgentChallenge published?
[ ] cloudbuild.yaml committed to repo?
[ ] Google Developer Group profile linked?
```

## Output format

Produce a table:

| Requirement | Status | Evidence | Action needed |
|---|---|---|---|
| Gemini model | ✅/❌ | file:line | ... |
| GenAI SDK or ADK | ✅/❌ | file:line | ... |
| GCP hosting | ✅/❌ | Cloud Run URL | ... |
| Live API | ✅/❌ | media/live.py:N | ... |
| Multimodal | ✅/❌ | telegram_bot.py | ... |
| Demo video | ✅/❌ | file path | ... |
| Architecture diagram | ✅/❌ | file path | ... |
| GCP proof | ✅/❌ | file path | ... |
| Public repo + README | ✅/❌ | git remote | ... |

Then list all action items ordered by deadline risk (most blocking first).

## Arguments

$ARGUMENTS
