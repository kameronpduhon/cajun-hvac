# CLAUDE.md

## Project Overview

Voice AI agent for home service companies (HVAC, plumbing, electrical). Handles inbound phone calls via Twilio → LiveKit SIP → Python agent. Collects caller info, routes by intent, takes action (books appointments, dispatches techs, takes messages). Each client gets a playbook (JSON config) — same codebase serves every client.

## Stack

- **Agent framework:** LiveKit Agents SDK 1.4.x (Python)
- **STT:** Deepgram Nova-3 (multilingual)
- **LLM:** Google Gemini 2.5 Flash
- **TTS:** Deepgram Aura-2 (voice: "asteria")
- **Package manager:** uv
- **Tests:** pytest (asyncio_mode = auto)
- **Linter:** ruff

## Commands

```bash
uv run python src/agent.py console        # Test locally in terminal
uv run python src/agent.py dev            # Connect to LiveKit Cloud
uv run python src/agent.py download-files # Download ML models (first run)
uv run pytest tests/ -v                   # Run all tests
uv run ruff check src/ compiler/ tests/   # Lint
uv run ruff format src/ compiler/ tests/  # Format
uv run python compiler/compile.py playbooks/cajun-hvac.json  # Compile playbook
```

## Architecture

**Multi-agent with StepExecutor state machine.** Two agent classes using LiveKit's native handoff system, with StepExecutor driving per-intent call flow. **Single-voice UX goal:** callers must feel like they're talking to ONE agent the entire call — no department transfers, no "let me connect you." The multi-agent architecture is invisible to the caller.

### Agent classes
- **RouterAgent** — greets caller, identifies intent via `route_to_intent` tool, checks time window, speaks router acknowledgment (short filler like "Absolutely, one moment."), hands off to IntentAgent. Can answer simple info questions (hours, address, phone) directly without routing. Handles escalation re-entry (skips greeting, routes directly).
- **IntentAgent** — parameterized per-intent specialist. Receives one intent's config, runs that flow with `update_field` + `escalate` tools. `on_enter()` speaks continuation phrase via `session.say()` for greeted intents (routine_service/emergency/commercial), or dispatches the first step via `generate_reply(instructions=...)` for others.

### Handoff pattern
- RouterAgent → `route_to_intent` speaks router acknowledgment (if applicable) via `session.say(allow_interruptions=False)`, then returns `(IntentAgent(), "message")` → LiveKit SDK handles handoff
- IntentAgent → `escalate` returns `(RouterAgent(), "message")` → router re-enters, detects escalation via `session.userdata["escalation_requested"]`, routes directly without replaying greeting
- `session.userdata` (dict) persists across all agent handoffs — used for transcript, collected fields, outcome, post-call summary

### Router acknowledgments & continuation phrases
- **Router acknowledgments** (`scripts.router_acknowledgments`): Short, generic filler RouterAgent speaks before handoff for routine_service, emergency, commercial — covers handoff delay without implying a transfer. Other intents hand off silently. `session.say(allow_interruptions=False)` ensures full playout before agent switch.
- **Continuation phrases** (`scripts.intent_greetings`): IntentAgent speaks on enter for routine_service, emergency, commercial via `session.say()`. Sounds like the same agent shifting gears into the work, asks for name → intent prompt tells LLM "caller already asked for name, wait for response, do NOT re-ask." Step index stays at 0.
- Router acknowledgments and intent greetings must appear in matching pairs (compiler validates).

### Router info handling
- RouterAgent answers simple info questions (business hours, address, phone) directly from company info in router prompt — no routing needed.
- After answering, asks "Is there anything else I can help you with?" and routes if caller needs a service.
- Info-only calls post summary with null intent/outcome (backend handles gracefully).

### StepExecutor (unchanged core)
- Drives call flow per intent — pure Python, zero LiveKit dependency
- Constructor: `StepExecutor(playbook, intent, pre_collected=None)` — scoped to one intent at creation
- `_skip_pre_collected_steps()` advances past collect steps for fields carried from escalation
- Playbook JSON defines steps per intent (collect/speak/action)
- Per-step `mode` field: `verbatim` vs `guided` — both return text via tool result, LLM is single speech source
- Tools return `"Say EXACTLY: ..."` for verbatim text, raw prompts for guided (LLM paraphrases naturally)
- `[call_ended]` signal in tool result = call ending, shutdown session (check with `in`, not `==`)
- `update_field` allows overwriting previously collected fields without advancing

### Compiler
- Builds `router_prompt` (routing + info handling) + `intent_prompts` dict (one per intent, scoped fields/rules/company info)
- Router prompt: company name/address/phone, office hours, intent list, emergency routing with contrastive examples, simple info question handling, guardrails
- Intent prompts: scoped field names, company info relevant to that intent, conversation rules, "Say EXACTLY" handling, step ordering instructions, greeting-aware instructions for greeted intents
- **Field names auto-generated** by compiler from collect steps — no hardcoded list to maintain
- **Validates** router_acknowledgments/intent_greetings reference valid intents and appear in matching pairs

### Time window routing
- RouterAgent checks time window, redirects non-emergency intents to `_after_hours` IntentAgent
- Emergency always gets full flow regardless of time
- After-hours support is optional per client (compiler validates `_after_hours` intent + `after_hours_greeting` script as a pair)

## Project Structure

```
src/
├── agent.py           # RouterAgent + IntentAgent, entrypoint, transcript capture
├── step_executor.py   # State machine (zero LiveKit dependency)
├── actions.py         # Action functions + ACTION_REGISTRY
├── utils.py           # extract_zip, resolve_template, detect_time_window, format_hours
├── playbook.py        # Load compiled playbook from disk
└── post_call.py       # Post-call summary from session.userdata with retry
compiler/
└── compile.py         # Validate raw playbook → compiled JSON (router_prompt + intent_prompts)
playbooks/
├── cajun-hvac.json           # Raw playbook (client config)
└── cajun-hvac.compiled.json  # Compiled (agent reads this)
tests/
├── test_utils.py
├── test_step_executor.py
├── test_actions.py
└── test_compiler.py
```

## Key Rules

1. **step_executor.py has zero LiveKit SDK dependency** — pure call flow logic, independently testable
2. **No session.say() in tools** — causes double-speak. Tools return "Say EXACTLY:" directives; LLM is single speech source. Exception: `route_to_intent` uses `session.say()` for router acknowledgments (before handoff, not during LLM generation)
3. **Prompts use hard language** — DO NOT, NEVER (not "try to" or "please avoid")
4. **session.shutdown() is sync** — do not await it
5. **Field names must be explicit** in intent prompts — LLM guesses wrong names without them
6. **conversation_item_added** is the correct event for transcript capture
7. **Running as `python src/agent.py`** requires sys.path fix for `from src.x` imports (already in agent.py and compile.py)
8. **After modifying playbook JSON**, recompile: `uv run python compiler/compile.py playbooks/cajun-hvac.json`
9. **Transcript capture uses session.userdata** — agent instances change on handoff, session persists
10. **Escalation re-entry** — RouterAgent checks `session.userdata["escalation_requested"]` in `on_enter()` to skip greeting and route directly
11. **Greeted intents coordinate via prompt** — `session.say()` speaks greeting, intent prompt tells LLM to wait for caller response. No StepExecutor changes needed — step index stays at 0
12. **Router acknowledgments and intent greetings must be paired** — compiler validates they appear together for each intent

## Intents (10 + 1 routing)

- `routine_service` — full booking flow (name → phone → address → area check → appointment → issue → fee → confirm → book)
- `emergency` — urgent dispatch (name → phone → address → confirm → dispatch on-call tech). No fee, no service area check.
- `cancellation` — name → phone → reason → take message
- `reschedule` — name → phone → preferred time → take message
- `eta_request` — name → phone → take message
- `warranty` — speak warranty intro → name → phone → issue → take message
- `billing` — name → phone → issue → take message
- `complaint` — name → phone → issue → take message
- `commercial` — name → phone → issue → take message
- `_fallback` — name → phone → take message
- `_after_hours` — off-hours take-a-message (name → phone → take message). Only active when time_window != office_hours.

## Design Docs

- Spec (Milestone 1): `docs/superpowers/specs/2026-03-18-voice-agent-milestone1-design.md`
- Plan (Milestone 1): `docs/superpowers/plans/2026-03-18-milestone1-implementation.md`
- Spec (Intents expansion): `docs/superpowers/specs/2026-03-19-caller-intents-expansion-design.md`
- Plan (Intents expansion): `docs/superpowers/plans/2026-03-19-caller-intents-expansion.md`
- Spec (Time window routing): `docs/superpowers/specs/2026-03-23-time-window-routing-design.md`
- Plan (Time window routing): `docs/superpowers/plans/2026-03-23-time-window-routing.md`
- Plan (Multi-agent v1): `/Users/kameronduhon/Downloads/multi-agent-implementation-plan.md`
- Plan (Multi-agent v2): `/Users/kameronduhon/Downloads/multi-agent-implementation-plan-v2.md`
- Prior build reference: `DUHON_VOICE_AGENT_REFERENCE.md`

## Environment Variables (.env.local)

```
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
OPENAI_API_KEY=...
DEEPGRAM_API_KEY=...
COMPILED_PLAYBOOK_PATH=playbooks/cajun-hvac.compiled.json
BACKEND_URL=http://localhost:8000
```
