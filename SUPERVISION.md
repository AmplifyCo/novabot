# Nova — Supervision Method Registry

**Version**: 1.0 — February 2026
**Owner**: Nova's User (sole operator)
**Reference**: Documentation schema from "Supervision of AI Systems" (arxiv 2507.03525v2)

---

## Schema

Each method is documented with:

| Field | Description |
|---|---|
| **Time-scope** | Ex-ante (before processing) / In-flight (during execution) / Ex-post (after action) |
| **Layer** | Technical / Sociotechnical / Governance |
| **Human Involvement** | None / HITL (Human-in-the-loop) / HOTL (Human-on-the-loop) / HATL (Human-after-the-loop) |
| **Risks Mitigated** | Links to RISKS.md entries |
| **Feasibility Conditions** | Assumptions required for this method to work |
| **Failure Modes** | How this method can fail or be bypassed |
| **Review Plan** | When and how this method is evaluated |

---

## SM-01 — LLM Security Guard

**Description**: 14-layer security guard applied to every message before and after LLM processing. Detects prompt injection via 38+ regex patterns (direct overrides, role hijacking, jailbreaks, delimiter injection, encoding tricks). Filters sensitive content from outputs. Validates tool use semantically via Claude Haiku.

| Field | Value |
|---|---|
| **Time-scope** | Ex-ante (input) + Ex-post (output filtering) |
| **Layer** | Technical |
| **Human Involvement** | None (fully automated) |
| **Risks Mitigated** | RISK-S01, RISK-S02, RISK-S03, RISK-S04, RISK-S06 |
| **Implementation** | `src/core/security/llm_security.py` |

**Feasibility Conditions**: Effective against known injection patterns. Regex library must be updated as new attack patterns emerge publicly. Semantic validation adds an LLM-based judgment layer but adds latency.

**Failure Modes**:
- Novel jailbreak patterns not yet in the regex library bypass the input layer
- Semantic validation (Haiku) may itself be tricked by sophisticated multi-step prompts
- Output filtering may miss newly invented credential formats

**Review Plan**: Review regex pattern library after any security incident (RISK-S01/S02). Annual review of known jailbreak techniques to update patterns.

---

## SM-02 — Policy Gate

**Description**: Deterministic permission check before every tool execution. Classifies each tool+operation as READ / WRITE / IRREVERSIBLE. Blocks or logs high-risk operations. Enforces per-tool rate limits (max 20 calls per agent run). All WRITE and IRREVERSIBLE actions are logged.

| Field | Value |
|---|---|
| **Time-scope** | In-flight (before tool execution) |
| **Layer** | Technical |
| **Human Involvement** | HOTL for IRREVERSIBLE actions (pauses for owner confirmation) |
| **Risks Mitigated** | RISK-S05, RISK-O01, RISK-O02, RISK-O03, RISK-O05 |
| **Implementation** | `src/core/nervous_system/policy_gate.py` |

**Feasibility Conditions**: All tool calls must route through the ExecutionGovernor. Direct API calls made by tools themselves (not routed through the registry) bypass this gate.

**Failure Modes**:
- Tool registered with wrong risk level (e.g., email marked WRITE instead of IRREVERSIBLE)
- New tool added to registry without assigning correct risk level
- Rate limiting counters reset on restart — per-session limit, not per-day

**Review Plan**: Review risk-level mapping for all tools whenever a new tool is added to the registry.

---

## SM-03 — Audit Logger

**Description**: Writes structured JSONL audit logs (`logs/security_audit.jsonl`) for all security violations, bash commands, file operations, tool executions, API calls, and sensitive data access. Queryable for recent events by type and severity.

| Field | Value |
|---|---|
| **Time-scope** | In-flight + Ex-post |
| **Layer** | Technical |
| **Human Involvement** | HATL — owner reviews logs when something seems off (ad-hoc) |
| **Risks Mitigated** | RISK-O01, RISK-O04, RISK-O05, RISK-O06, RISK-P01 |
| **Implementation** | `src/core/security/audit_logger.py` → `logs/security_audit.jsonl` |

**Feasibility Conditions**: Requires writable log directory on EC2. Log rotation must be managed to prevent disk exhaustion. Useful only when owner reviews logs after incidents.

**Failure Modes**:
- Disk full — logging silently fails; no alarm raised
- Logs never reviewed proactively — problems accumulate undetected
- Log format changes across versions break historical queries

**Review Plan**: Owner reviews logs when an incident is noticed. Self-Healing Monitor (SM-07) provides passive automated scanning. **Bi-weekly proactive review** — spend ~5 minutes every two weeks scanning `logs/security_audit.jsonl` for patterns or anomalies even when nothing has gone wrong.

---

## SM-04 — Durable Outbox (Idempotency)

**Description**: SHA256 idempotency keys prevent duplicate side-effects (emails, X posts) on retry. Intent is recorded before execution; sent/failed status recorded after. A duplicate check prevents re-send if a task retries the same operation.

| Field | Value |
|---|---|
| **Time-scope** | In-flight (wraps side-effect execution) |
| **Layer** | Technical |
| **Human Involvement** | None |
| **Risks Mitigated** | RISK-S05, RISK-O01 |
| **Implementation** | `src/core/nervous_system/outbox.py` |

**Feasibility Conditions**: Effective only for tools explicitly registered as side-effect tools (currently: email, x_post). New side-effect tools must be added to the outbox's tool list at integration time.

**Failure Modes**:
- New side-effect tool (e.g., WhatsApp send) not registered in outbox → double-send possible
- Outbox persistent store corrupted or deleted → idempotency broken on restart

**Review Plan**: Review side-effect tool list whenever a new outbound integration is added.

---

## SM-05 — Dead Letter Queue

**Description**: After 3 failed retries, a failing message or tool call is parked in the DLQ rather than retried indefinitely. Prevents infinite loops that could cause repeated unintended actions or resource exhaustion.

| Field | Value |
|---|---|
| **Time-scope** | In-flight + Ex-post |
| **Layer** | Technical |
| **Human Involvement** | HATL — DLQ items require manual owner review to decide retry or discard |
| **Risks Mitigated** | RISK-O06 |
| **Implementation** | `src/core/nervous_system/dead_letter_queue.py` |

**Feasibility Conditions**: Requires owner to periodically check DLQ. Items in DLQ represent work that was silently abandoned after max retries.

**Failure Modes**:
- DLQ items never reviewed → legitimate tasks silently dropped with no owner awareness
- max_retries set too low → transient failures dead-lettered prematurely

**Review Plan**: Check DLQ when tasks appear to have been silently dropped. No automated alert currently when DLQ is non-empty — this is a known gap.

---

## SM-06 — State Machine + Cancellation

**Description**: Agent execution tracked through named states: IDLE → PARSING_INTENT → THINKING → EXECUTING → REFLECTING → RESPONDING → AWAITING_APPROVAL. Owner can request cancellation from any non-terminal state. Cancellation propagates to task runner.

| Field | Value |
|---|---|
| **Time-scope** | In-flight |
| **Layer** | Technical + Sociotechnical |
| **Human Involvement** | HOTL — owner issues cancel command via Telegram |
| **Risks Mitigated** | RISK-O01, RISK-O06 |
| **Implementation** | `src/core/nervous_system/state_machine.py` |

**Feasibility Conditions**: Owner must know a task is running and be at their Telegram client. Background tasks completing faster than Telegram round-trip may finish before cancel arrives.

**Failure Modes**:
- Irreversible action completes before cancel signal arrives (race condition)
- Owner unaware task is running — no proactive "task started" notification currently
- Owner uses phrasing not matched by the interrupt regex patterns

**Review Plan**: Review if a cancellation attempt fails to stop a running task.

---

## SM-07 — Self-Healing Monitor

**Description**: Background process scanning logs every 12 hours for 10+ error type patterns across 4 severity levels. Auto-fixes detected issues where possible. Notifies owner via Telegram of errors and applied fixes. Also scans for capability gaps ("I cannot do X") and attempts to add the missing capability.

| Field | Value |
|---|---|
| **Time-scope** | Ex-post |
| **Layer** | Technical |
| **Human Involvement** | HATL — owner notified after auto-fix is deployed |
| **Risks Mitigated** | RISK-O04, RISK-R01, RISK-R02 |
| **Implementation** | `src/core/self_healing/monitor.py`, `src/core/self_healing/error_detector.py` |

**Feasibility Conditions**: Requires writable codebase on EC2. Auto-fix capability depends on the error type being addressable programmatically. Owner must review Telegram notifications promptly.

**Failure Modes**:
- Auto-fix introduces a new bug or security regression (RISK-O04)
- Error pattern not in library — error missed
- Monitor itself crashes → no error detection until manual restart
- Owner doesn't review Telegram notifications → problems compound silently

**Review Plan**: Owner reviews Telegram notifications from self-healing. Full pre-deploy code review of auto-fixes is not currently enforced — acknowledged in RISK-O04.

---

## SM-08 — Circuit Breaker

**Description**: Tracks Claude API failures per time window. After 3 consecutive failures within 5 minutes, trips the breaker and routes to SmolLM2 (local Ollama fallback) for a 2-minute cooldown period before retrying the primary API.

| Field | Value |
|---|---|
| **Time-scope** | In-flight |
| **Layer** | Technical |
| **Human Involvement** | None |
| **Risks Mitigated** | RISK-R02 |
| **Implementation** | `src/core/conversation_manager.py:685` |

**Feasibility Conditions**: Requires SmolLM2 via Ollama to be running on EC2. If the fallback is also unavailable, Nova becomes unresponsive.

**Failure Modes**:
- SmolLM2/Ollama not running → breaker trips but fallback unavailable; Nova unresponsive
- 2-minute cooldown insufficient during extended API outages → repeatedly trips and retries

**Review Plan**: No scheduled review. Review if API outages cause extended unresponsiveness.

---

## SM-09 — Bash Command Guard

**Description**: Blocks hardcoded list of destructive bash commands (`rm -rf /`, `sudo rm`, `sudo shutdown`, `sudo reboot`, `mkfs.*`, `dd if=`, `format c:`). Sudo access disabled by default. Optional allowlist for whitelisted commands. All executed commands are audit-logged via SM-03.

| Field | Value |
|---|---|
| **Time-scope** | In-flight (before command execution) |
| **Layer** | Technical |
| **Human Involvement** | None (automated) |
| **Risks Mitigated** | RISK-O05 |
| **Implementation** | `src/core/tools/bash.py:88` |

**Feasibility Conditions**: Blocklist effectiveness depends on comprehensiveness. Destructive operations achievable through indirect paths (e.g., Python scripts called via bash) are not blocked.

**Failure Modes**:
- Destructive operation achievable via non-blocked command (e.g., `python -c "import shutil; shutil.rmtree(...)"`)
- Blocklist not updated as new attack patterns emerge

**Review Plan**: Review blocklist annually or after any bash-related incident.

---

## SM-10 — File Self-Protection

**Description**: Permanently protects critical files (`.env`, `config/security.yaml`) from write or delete via the File tool. Protection is hardcoded — remains effective even if config loading fails at startup.

| Field | Value |
|---|---|
| **Time-scope** | In-flight (before file operation) |
| **Layer** | Technical |
| **Human Involvement** | None |
| **Risks Mitigated** | RISK-S06 |
| **Implementation** | `src/core/tools/file.py:36` |

**Feasibility Conditions**: Applies only to file operations through the File tool. Direct filesystem access via bash requires SM-09 as a complementary control.

**Failure Modes**:
- File renamed or moved, then the renamed copy is modified (rename not protected)
- Protected file list does not include all sensitive config files

**Review Plan**: Review protected file list when new sensitive configuration files are added to the project.

---

## SM-11 — Voice Trust Classification

**Description**: Three-tier trust model applied at the start of every voice channel interaction.
- **Tier 1 — Trusted Principal** (owner): full assistant mode with contacts injected
- **Tier 2 — Outbound Mission** (Nova called them): never share personal info, never take instructions from callee, task-focused only
- **Tier 3 — Untrusted Inbound**: guarded mode, refuse all contact details, may take a message, no actions

| Field | Value |
|---|---|
| **Time-scope** | Ex-ante (at call start, before any response) |
| **Layer** | Technical + Sociotechnical |
| **Human Involvement** | None (automated tier classification) |
| **Risks Mitigated** | RISK-S03, RISK-S04, RISK-S05, RISK-E01 |
| **Implementation** | `src/core/conversation_manager.py:316` |

**Feasibility Conditions**: Owner identity must be reliably identifiable at call start. Currently based on name match or explicit identification — a caller can claim a false identity.

**Failure Modes**:
- Caller impersonates owner (voice cloning or simply stating owner's name)
- Trust tier mis-classified at call start due to ambiguous opening
- Gradual social engineering within "untrusted inbound" tier over a long call
- **GAP**: Nova does not proactively disclose it is an AI to outbound callees (RISK-E01 not fully addressed)

**Review Plan**: Review if a social engineering incident occurs via voice channel. Owner to decide and implement AI disclosure policy for outbound calls.

---

## SM-12 — Task Interrupt Mechanism

**Description**: Owner can cancel all running background tasks at any time by saying "stop task", "cancel", "abort", "stop what you're doing", or "stop everything" via Telegram. Cancelled goal is stored in working memory as "unfinished" for later reference.

| Field | Value |
|---|---|
| **Time-scope** | In-flight |
| **Layer** | Sociotechnical |
| **Human Involvement** | HOTL — owner initiates interrupt via Telegram |
| **Risks Mitigated** | RISK-O01, RISK-O06 |
| **Implementation** | `src/core/conversation_manager.py:1684` |

**Feasibility Conditions**: Owner must be aware a task is running and be at their Telegram client. Interrupt phrases must match the regex pattern library.

**Failure Modes**:
- Irreversible subtask completes before interrupt message is processed (race condition)
- Owner unaware task is running — no proactive "task started" push notification currently
- Owner uses phrasing not covered by interrupt regex

**Review Plan**: Review if interrupt fails to stop a task. Extend regex patterns if phrase matching gaps are discovered.

---

## SM-13 — Watchdog Service

**Description**: Supervisor process monitoring Nova's main process. Detects crashes and restarts with exponential backoff. Prevents crash loops via a 5-restart-per-300-seconds limit. Streams last ~50 lines of output for crash analysis and triggers AI-powered crash analysis.

| Field | Value |
|---|---|
| **Time-scope** | Ex-post (detects crash after occurrence) |
| **Layer** | Technical |
| **Human Involvement** | None (automated restart) |
| **Risks Mitigated** | RISK-R01 |
| **Implementation** | `src/watchdog.py` |

**Feasibility Conditions**: Watchdog must itself be managed by a system supervisor (systemd or similar). Cannot recover from host EC2 going down.

**Failure Modes**:
- Watchdog process itself crashes (no supervisor for the supervisor)
- Crash loop limit reached → Nova goes offline until manually restarted
- EC2 instance unreachable → watchdog cannot help; no alert reaches owner

**Review Plan**: No scheduled review. Review if Nova goes offline without a Telegram notification.

---

## SM-14 — High-Stakes Confirmation Logic

**Description**: Intelligence principle encoded in Brain: "Confirm smartly — high-stakes → ask first, low-stakes → just do it." Requires explicit owner authorization ("send it", "go ahead", "do it") before irreversible actions. Verifies tool results before declaring task complete. For research-driven actions, presents findings before acting.

| Field | Value |
|---|---|
| **Time-scope** | In-flight (before action execution) |
| **Layer** | Sociotechnical (LLM-based judgment) |
| **Human Involvement** | HITL for high-stakes decisions |
| **Risks Mitigated** | RISK-O01, RISK-O02, RISK-O03, RISK-E02 |
| **Implementation** | `src/core/conversation_manager.py:2058`, `src/core/brain/core_brain.py` |

**Feasibility Conditions**: Depends on LLM correctly classifying an action as high vs. low stakes. Owner must respond to confirmation requests in reasonable time for time-sensitive tasks.

**Failure Modes**:
- LLM misclassifies a high-stakes action as low-stakes and proceeds without asking
- Broad phrasing (e.g., "handle my emails") interpreted as blanket authorization to send
- Confirmation fatigue — owner approves without carefully reviewing the proposed action

**Review Plan**: Review classification logic if an unsanctioned irreversible action occurs.

---

## SM-15 — PII Redaction

**Description**: Detects and redacts PII (email addresses, phone numbers, IP addresses, SSN, credit card numbers) from messages before sending to LLM. Maintains a restoration map so tools can use original values during execution.

| Field | Value |
|---|---|
| **Time-scope** | Ex-ante (before LLM call) |
| **Layer** | Technical |
| **Human Involvement** | None |
| **Risks Mitigated** | RISK-P01, RISK-P02, RISK-P03, RISK-S04 |
| **Implementation** | `src/core/security/llm_security.py:427` |

**Feasibility Conditions**: Effective for PII in standard formats covered by regex patterns. Non-standard representations (e.g., "oh four one five...") are not caught.

**Failure Modes**:
- Novel PII format not in pattern library passes through unredacted
- Restoration map misapplied in tool execution — original PII not correctly restored
- Financial or health data in free-text form not recognized as PII (off-limits categories not actively enforced)

**Review Plan**: Review PII pattern library when off-limits data categories change or when a PII leak incident occurs.

---

## Coverage Matrix

| Risk | SM-01 | SM-02 | SM-03 | SM-04 | SM-05 | SM-06 | SM-07 | SM-08 | SM-09 | SM-10 | SM-11 | SM-12 | SM-13 | SM-14 | SM-15 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| RISK-S01 Web injection | ✓ | ✓ | | | | | | | | | | | | ✓ | |
| RISK-S02 Email injection | ✓ | ✓ | | | | | | | | | | | | ✓ | |
| RISK-S03 Voice injection | ✓ | | | | | | | | | | ✓ | | | | |
| RISK-S04 Contact extraction | ✓ | | | | | | | | | | ✓ | | | | ✓ |
| RISK-S05 Unauthorized action | | ✓ | | ✓ | | | | | | | | | | | |
| RISK-S06 Credential exposure | ✓ | | | | | | | | | ✓ | | | | | |
| RISK-P01 3rd party data stored | | | ✓ | | | | | | | | | | | | ✓ |
| RISK-P02 Financial data | | | ✓ | | | | | | | | | | | | ✓ |
| RISK-P03 Health data | | | ✓ | | | | | | | | | | | | ✓ |
| RISK-P04 EC2 breach | | | | | | | | | | | | | | | |
| RISK-O01 Action w/o confirm | | ✓ | ✓ | ✓ | | ✓ | | | | | | ✓ | | ✓ | |
| RISK-O02 Wrong recipient | | | | | | | | | | | | | | ✓ | |
| RISK-O03 Wrong research action | ✓ | ✓ | | | | | | | | | | | | ✓ | |
| RISK-O04 Self-heal bug | | | ✓ | | | | ✓ | | | | | | | | |
| RISK-O05 Bash damage | | ✓ | ✓ | | | | | | ✓ | | | | | | |
| RISK-O06 Silent task failure | | | ✓ | | ✓ | ✓ | | | | | | ✓ | | | |
| RISK-R01 EC2 downtime | | | | | | | ✓ | | | | | | ✓ | | |
| RISK-R02 API outage | | | | | | | | ✓ | | | | | | | |
| RISK-R03 Hallucination | | | | | | | | | | | | | | ✓ | |
| RISK-E01 AI impersonation | | | | | | | | | | | ✓ | | | | |
| RISK-E02 Unauthorized action | | ✓ | | ✓ | | | | | | | | | | ✓ | |

---

## Known Gaps (as of v1.0)

| Gap | Affected Methods | Affected Risks | Status |
|---|---|---|---|
| Third-party message storage not enforced as summary-only | SM-03, SM-15 | RISK-P01 | ✅ Fixed — `store_conversation_turn()` summarizes via Gemini Flash for third-party channels |
| Financial / health data not filtered at memory ingestion | SM-15 | RISK-P02, RISK-P03 | ✅ Fixed — sentence-level keyword filter in `_filter_sensitive_categories()`; IBAN/routing patterns added to `redact_pii()` |
| AI disclosure not implemented for outbound voice calls | SM-11 | RISK-E01 | ✅ Fixed — hardcoded in inbound greeting and enforced via outbound mission system prompt: "Hi, I'm Nova - an AI Agent." |
| Self-heal auto-fixes deploy without pre-deploy review | SM-07 | RISK-O04 | ✅ Fixed — pre-fix Telegram notification added in `monitor.py` before `attempt_fix()` |
| No proactive "task started" notification | SM-06, SM-12 | RISK-O06 | ✅ Fixed — `_notify_started()` in `task_runner.py` notifies via Telegram when task begins |
| DLQ does not alert owner when non-empty | SM-05 | RISK-O06 | ✅ Fixed — `_add_to_dlq()` fires Telegram alert; `telegram_notifier` wired into `ExecutionGovernor` |
| No proactive audit log review cadence | SM-03 | All | ✅ Fixed — bi-weekly review scheduled (see SM-03 review plan) |

---

## Supervision Log

> Record failures, near-misses, and updates to supervision methods here. Append — do not edit prior entries.

| Date | Event | Method Affected | Action Taken |
|---|---|---|---|
| 2026-02-23 | SUPERVISION.md v1.0 created | All | Initial documentation of all supervision methods |
| 2026-02-24 | Gap closure — 6 of 7 gaps addressed | SM-03, SM-05, SM-06, SM-07, SM-12, SM-15 | Third-party summarization (Gemini Flash), financial/health filters, pre-deploy notify, task-start notify, DLQ alert, bi-weekly review cadence |
| 2026-02-24 | RISK-E01 closed — AI disclosure hardcoded | SM-11 | Inbound greeting and outbound mission prompt both enforce "Hi, I'm Nova - an AI Agent" opening |
