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

## Phase 2: Anticipatory Intelligence
*From reactive to predictive — Nova acts before you ask*

### 2A. Pattern Detection Engine
Scan episodic memory weekly. Extract time-action patterns ("You post on LinkedIn every Tuesday"). Store as patterns.json. Feed to attention engine.
**New file**: brain/pattern_detector.py

### 2B. Proactive Drafts
Attention engine evolves from "observe and report" to "observe, predict, prepare." Tuesday morning: "I've drafted your LinkedIn post based on this week's work." Before meetings: surface context from last conversation with that person.
**Modify**: brain/attention_engine.py

### 2C. Smart Scheduling (Circadian Rhythm)
Time-based behavior modifiers. Morning = briefing mode. Work hours = professional, action-oriented. Evening = lighter, reflective. Weekend = minimal interruption.
**New file**: brain/circadian_rhythm.py

### 2D. Contact Intelligence
Remember relationships, not just names. Track interaction history and communication preferences per contact. "Last time you emailed Sarah, she asked about Q2 — you never replied."
**Modify**: brain/digital_clone_brain.py (extend contact store)

---

## Phase 3: Reasoning & Judgment
*From command executor to thinking partner*

### 3A. Pushback & Alternatives
Post-draft evaluation layer. Before irreversible actions, check timing, tone, consistency. "You could post this now, but spacing it to Monday would get better engagement."
**New file**: brain/judgment_engine.py

### 3B. Reasoning Transparency
Task runner and goal decomposer expose reasoning as brief "APPROACH" preamble. "I'm doing this in two steps: research then draft. I'll check in after step 1."
**Modify**: task_runner.py, goal_decomposer.py

### 3C. Quality Self-Assessment
Every substantive response gets lightweight self-eval (confidence: high/medium/low). Low-confidence sections flagged. "I'm confident about the data but the competitor analysis is thin — want me to dig deeper?"
**Modify**: conversation_manager.py (extend CriticAgent)

### 3D. Multi-Turn Reasoning (Deliberation)
For complex questions, Nova gathers evidence from multiple sources, weighs them, produces structured recommendation with trade-offs. Triggered by intent classification detecting "needs judgment."
**New file**: brain/deliberation.py

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
