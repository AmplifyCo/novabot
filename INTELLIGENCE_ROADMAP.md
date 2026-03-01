# Nova Intelligence Roadmap — From Prompt-Taker to Thinking Agent

## Phase 1: Visible Intelligence (IMPLEMENTED)
*Make what Nova already knows felt in every interaction*

### 1A. Context Callbacks
When Nova uses recalled episodic memory, corrections, or preferences, it naturally references them.
"Based on what worked last time...", "You mentioned you prefer..."

### 1B. Conversation Continuity
Open threads tracked across sessions (max 3, 48h expiry). Session greeting when user returns after 30+ min gap.
"Welcome back — we were working on that LinkedIn post, want to continue?"

### 1C. Visible Correction Learning
Corrections acknowledged immediately ("Got it, adjusting") and stored in working memory. Future similar tasks reference past corrections.

### 1D. Preference Profiling
Structured preference model built incrementally from learning extraction. Injected into all prompts so Nova consistently references known preferences.

**Files**: working_memory.py (+159 lines), conversation_manager.py (+92 lines)
**Latency**: Zero new LLM calls

---

## Phase 2: Anticipatory Intelligence (IMPLEMENTED — 2A, 2C, 2D)
*From reactive to predictive — Nova acts before you ask*

### 2A. Pattern Detection Engine (IMPLEMENTED)
Background 12h scan of episodic memory. Extracts time-action patterns ("You post on LinkedIn every Tuesday"). Stores as patterns.json. Fed to attention engine for proactive suggestions.
**New file**: brain/pattern_detector.py
**Wired into**: attention_engine.py, main.py
**Latency**: +1 Gemini Flash call per 12h (background)

### 2B. Proactive Drafts
Attention engine evolves from "observe and report" to "observe, predict, prepare." Tuesday morning: "I've drafted your LinkedIn post based on this week's work." Before meetings: surface context from last conversation with that person.
**Status**: Not yet implemented

### 2C. Smart Scheduling (Circadian Rhythm) (IMPLEMENTED)
Time-based behavior modifiers injected into all conversation prompts. Morning = briefing mode. Work hours = professional (default). Evening = lighter, reflective. Late night = minimal.
**New file**: brain/circadian.py
**Wired into**: conversation_manager.py (_build_system_prompt + _chat)
**Latency**: Zero (rule-based, static methods)

### 2D. Contact Intelligence (IMPLEMENTED)
Per-contact interaction history tracked in JSON. Surfaces "Last time you emailed Sarah..." and pending follow-ups in execution plans. Stale contacts surfaced by attention engine.
**New file**: brain/contact_intelligence.py
**Wired into**: conversation_manager.py, attention_engine.py, main.py
**Latency**: Zero (structured data, no LLM calls)

---

## Phase 3: Reasoning & Judgment (IMPLEMENTED — 3B, 3C, 3D)
*From command executor to thinking partner*

### 3A. Pushback & Alternatives
Post-draft evaluation layer. Before irreversible actions, check timing, tone, consistency. "You could post this now, but spacing it to Monday would get better engagement."
**Status**: Not yet implemented

### 3B. Reasoning Transparency (IMPLEMENTED)
Preflight APPROACH section surfaced to user via progress callback before agent execution. Task runner plan notifications enhanced with tools summary and approach reasoning.
**Modified**: conversation_manager.py (_extract_approach + progress_callback), task_runner.py (_notify_plan)
**Latency**: Zero (uses existing preflight reasoning, just surfaces it)

### 3C. Quality Self-Assessment (IMPLEMENTED)
Substantive responses (>150 chars) get lightweight Gemini Flash self-eval (high/medium/low confidence). Only low-confidence areas surfaced naturally: "The competitor analysis is thin — want me to dig deeper?"
**New file**: brain/self_assessor.py
**Wired into**: conversation_manager.py (action + question blocks), main.py
**Latency**: +1 Gemini Flash call per substantive response (~1s, fail-open)

### 3D. Multi-Turn Reasoning (Deliberation) (IMPLEMENTED)
Keyword-triggered ("should I", "pros and cons", "compare") → gathers evidence from brain context + episodic memory → produces EVIDENCE/TENSIONS/RECOMMENDATION/CAVEATS structure. Replaces standard preflight for judgment questions.
**Uses**: brain/self_assessor.py (SelfAssessor.deliberate + needs_deliberation)
**Wired into**: conversation_manager.py (preflight upgrade), main.py
**Latency**: +1 Gemini Flash call for judgment questions only (~2s, fail-open)

---

## Phase 4: Autonomous Growth
*Nova improves itself without being told*

### 4A. Skill Acquisition
Periodic review of episodic memory. Extract patterns from successful actions into skills/ JSON files. After 10 LinkedIn posts, auto-extract a style guide from approved posts.
**New file**: brain/skill_learner.py

### 4B. Feedback Loop Closure
Track outcomes, not just actions. Poll LinkedIn API for engagement after 24h. Track email replies within 48h. Store outcomes in episodic memory. Pattern detector uses these for calibration.
**Modify**: episodic_memory.py, attention_engine.py

### 4C. Knowledge Base Building
Research results chunked and stored with topic tags. Next time user asks about same topic, Nova doesn't start from scratch — it builds on existing knowledge.
**New file**: brain/knowledge_base.py

### 4D. Self-Monitoring & Growth Reports
Weekly: "23 requests handled, 3 corrections received (all about tone), approval rate up from 60% to 85%." Monthly: areas to improve, self-directed learning goals.
**New file**: brain/self_monitor.py

---

## Summary

| Phase | Theme | Nova Feels Like... | Key Shift |
|-------|-------|--------------------|-----------|
| 1     | Visible Intelligence | "It remembers me" | Show existing intelligence |
| 2     | Anticipatory | "It knows what I need" | React to Predict |
| 3     | Reasoning | "It thinks for itself" | Execute to Judge |
| 4     | Autonomous Growth | "It's getting better" | Static to Evolving |
