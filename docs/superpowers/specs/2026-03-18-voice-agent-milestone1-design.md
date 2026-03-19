# Voice Agent Milestone 1 — Design Spec

**Date:** 2026-03-18
**Scope:** Single-intent (routine_service) end-to-end on a real phone call

---

## 1. Milestone Scope

### What "done" means
- Call comes in via Twilio → LiveKit SIP → agent connects
- Agent greets caller, identifies intent as routine_service
- StepExecutor walks through: fee disclosure → fee approval → name → phone → address → service area check → issue description → appointment time → confirm booking
- Steps use `verbatim` or `guided` mode per the playbook
- Post-call summary POSTs to the Laravel API with retry logic
- Caller hangs up, clean shutdown

### What's NOT in this milestone
- Other intents beyond routine_service and _fallback — unrecognized intents route to _fallback which takes a message (name + phone) so no caller hits a dead end
- API-based playbook loading (reads from disk via `COMPILED_PLAYBOOK_PATH`)
- Multi-client support
- The wizard / Laravel backend changes

---

## 2. Architecture Decision

**Option C: Modernized State Machine** with `generate_reply` upgrade.

### Why not LiveKit-native Agent/Task per intent?
- 400+ clients, one codebase — every client is a playbook config, not custom code
- Option A would require 10+ Agent subclasses (one per intent) and 8-12 Task subclasses (one per collect field) that all do the same thing with different names
- SDK coupling risk — LiveKit Agents is still actively evolving (1.4.x). Keeping flow logic independent means SDK upgrades are transport changes, not architecture rewrites
- The two-tool interface (`set_intent` + `update_field`) passed every live call test in the prior build

### Speech upgrade
- `session.say()` for `verbatim` steps — guaranteed exact wording for fee disclosures, legal language, closings
- `session.generate_reply(instructions=...)` for `guided` steps — LLM paraphrases naturally, avoids robotic delivery
- Per-step `mode` field in the playbook controls which method is used
- The StepExecutor checks `mode` and dispatches accordingly

---

## 3. Playbook Structure (Raw JSON)

The raw playbook is what clients fill out via the wizard. It stays clean and human-readable.

```json
{
  "company": {
    "name": "Cajun HVAC",
    "phone": "(337) 270-7004",
    "address": "Lafayette, LA",
    "timezone": "America/Chicago"
  },
  "hours": {
    "office": { "start": "08:00", "end": "17:00", "days": ["mon","tue","wed","thu","fri"] },
    "on_call": { "start": "17:00", "end": "22:00" }
  },
  "service_areas": ["70502", "70503", "70506", "70507", "70508"],
  "fees": {
    "service_call": {
      "amount": 89,
      "waived_with_work": true
    }
  },
  "contacts": {
    "oncall_tech": { "name": "Mike", "phone": "(337) 555-0199" }
  },
  "scripts": {
    "greeting": "Thank you for calling Cajun HVAC, how can I help you today?",
    "closing_booked": "You're all set! A technician will be there at {appointment_time}. Is there anything else I can help with?",
    "closing_message": "I've taken your message and someone will get back to you shortly. Have a great day!"
  },
  "intents": {
    "routine_service": {
      "label": "Routine Service Request",
      "steps": [
        { "type": "speak", "mode": "verbatim", "text": "There is an $89 service call fee that is waived if you proceed with the repair. Would you like to continue?" },
        { "type": "collect", "field": "fee_approved", "mode": "guided", "prompt": "Wait for the caller to confirm they accept the fee. Record yes or no." },
        { "type": "action", "fn": "check_fee_approved" },
        { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
        { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
        { "type": "collect", "field": "address", "mode": "guided", "prompt": "Ask for the full service address including zip code." },
        { "type": "action", "fn": "check_service_area" },
        { "type": "collect", "field": "issue_description", "mode": "guided", "prompt": "Ask what service they need or what issue they're experiencing." },
        { "type": "collect", "field": "appointment_time", "mode": "guided", "prompt": "Ask when they'd like to schedule the service appointment." },
        { "type": "action", "fn": "confirm_booking" }
      ]
    },
    "_fallback": {
      "label": "Take a Message",
      "steps": [
        { "type": "speak", "mode": "guided", "prompt": "Let the caller know you'll take a message so someone can get back to them." },
        { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's name." },
        { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback number." },
        { "type": "action", "fn": "take_message" }
      ]
    }
  }
}
```

### Key conventions
- `verbatim` steps use `"text"` field — exact words spoken via `session.say()`
- `guided` steps use `"prompt"` field — instruction for the LLM via `generate_reply()`
- `mode` is required on every `speak` and `collect` step — no defaults, validator errors if missing
- Action steps have no `mode` — they're Python functions, not speech
- Scripts use `{field_name}` templates — resolved by action functions from collected data at runtime
- `_fallback` is the catch-all intent for unrecognized caller needs

---

## 4. Compiled Playbook Structure

The compiler produces this. The agent reads this at runtime.

```json
{
  "meta": {
    "company_name": "Cajun HVAC",
    "timezone": "America/Chicago",
    "compiled_at": "2026-03-18T22:30:00Z",
    "source_file": "cajun-hvac.json"
  },
  "system_prompt": "You are a virtual receptionist for Cajun HVAC...",
  "scripts": {
    "greeting": "Thank you for calling Cajun HVAC, how can I help you today?",
    "closing_booked": "You're all set! A technician will be there at {appointment_time}. Is there anything else I can help with?",
    "closing_message": "I've taken your message and someone will get back to you shortly. Have a great day!"
  },
  "service_areas": ["70502", "70503", "70506", "70507", "70508"],
  "fees": { "service_call": { "amount": 89, "waived_with_work": true } },
  "contacts": { "oncall_tech": { "name": "Mike", "phone": "(337) 555-0199" } },
  "hours": {
    "office": { "start": "08:00", "end": "17:00", "days": ["mon","tue","wed","thu","fri"] },
    "on_call": { "start": "17:00", "end": "22:00" }
  },
  "intents": {
    "routine_service": { "label": "Routine Service Request", "steps": ["...same as raw..."] },
    "_fallback": { "label": "Take a Message", "steps": ["...same as raw..."] }
  }
}
```

### Compiler responsibilities

| Responsibility | Details |
|---|---|
| Build system prompt | Assembles from company info, hours, fees, output rules, tool instructions, guardrails, intent list. Uses hard language (DO NOT, NEVER). |
| Validate | Required fields present, step types valid, mode explicit on every speak/collect step, field names match type+mode (see table below), action functions reference known functions, _fallback exists |
| Passthrough | Intents, steps, service_areas, fees, contacts, hours copied as-is |

### Validation: required fields by type+mode

| Type | Mode | Required field | Description |
|---|---|---|---|
| `speak` | `verbatim` | `text` | Exact words to speak |
| `speak` | `guided` | `prompt` | Instruction for the LLM |
| `collect` | `guided` | `prompt`, `field` | Instruction + field name to record |
| `collect` | `verbatim` | `text`, `field` | Exact question + field name to record |
| `action` | _(none)_ | `fn` | Function name to execute |

### Compiler does NOT
- Generate step arrays (playbook owns them)
- Decide step order (playbook owns it)
- Modify step content

### System prompt contents
- Identity: "You are a virtual receptionist for {company_name}..."
- Output rules: plain text only, brief, spell out numbers
- Tool instructions: set_intent once, update_field with real values only, `[delivered]` and `[call_ended]` conventions
- Available intents with labels, _fallback description
- Company info: phone, service areas, fees, hours (formatted readably like "Mon-Fri 8am-5pm")
- Conversation rules: declined appointment time handling
- Guardrails: stay on topic, don't promise availability/timing, offer to take message for out-of-scope

---

## 5. StepExecutor & Tool Interface

### State

```python
class StepExecutor:
    def __init__(self, playbook: dict):
        self.playbook = playbook
        self.current_intent: str | None = None
        self.current_step_index: int = 0
        self.collected: dict[str, str] = {}
        self.transcript: str = ""
        self.outcome: str | None = None  # "booked", "declined", "out_of_area", "message_taken"
        self.time_window: str | None = None  # "office_hours", "on_call", "after_hours"
```

### Two tools

**`set_intent(intent: str, session)`**
1. Can only be called once — second call returns error string
2. Validates intent exists in playbook (or routes to `_fallback`)
3. Sets `current_intent`, resets `current_step_index` to 0
4. Reads step 0 and dispatches by type (same logic as `advance()`)
5. Returns the speech instruction for the LLM

```python
async def set_intent(self, intent: str, session) -> str:
    if self.current_intent is not None:
        return "Intent has already been set. Continue with update_field."

    if intent not in self.playbook["intents"]:
        intent = "_fallback"

    self.current_intent = intent
    self.current_step_index = 0
    step = self.current_steps[0]

    if step["type"] == "action":
        return await self.execute_action(step, session)

    if step["type"] == "speak":
        return await self.deliver_speak(step, session)

    if step["type"] == "collect":
        return step["prompt"]
```

**`update_field(field_name: str, value: str, session)`**
1. Rejects placeholder values (`[Name]`, `TBD`, `N/A`, etc.)
2. Validates `field_name` matches current step's `field` (strict one-at-a-time)
3. Stores value in `collected[field_name]`
4. Calls `advance()` to move to next step
5. Returns the next speech instruction

### advance() — shared method

Both `update_field` and action functions call this:

```python
async def advance(self, session) -> str:
    self.current_step_index += 1

    if self.current_step_index >= len(self.current_steps):
        return "[call_ended]"

    step = self.current_steps[self.current_step_index]

    if step["type"] == "action":
        return await self.execute_action(step, session)

    if step["type"] == "speak":
        return await self.deliver_speak(step, session)

    if step["type"] == "collect":
        return step["prompt"]
```

### deliver_speak() — handles mode and lookahead

```python
async def deliver_speak(self, step: dict, session) -> str:
    if step["mode"] == "verbatim":
        await session.say(step["text"])
        # Lookahead: if next step is collect, combine
        next_step = self.peek_next_step()
        if next_step and next_step["type"] == "collect":
            self.current_step_index += 1
            return next_step["prompt"]
        return "[delivered]"
    else:  # guided
        # Lookahead: if next step is collect, combine
        next_step = self.peek_next_step()
        if next_step and next_step["type"] == "collect":
            self.current_step_index += 1
            return f"{step['prompt']} Then, {next_step['prompt']}"
        return step["prompt"]
```

### Action functions

Each receives the executor and session, returns a speech instruction or signal.

Template resolution is generic — any script can reference any collected field:

```python
def resolve_template(template: str, collected: dict) -> str:
    resolved = template
    for field, value in collected.items():
        resolved = resolved.replace(f"{{{field}}}", value)
    return resolved
```

Action functions:

```python
async def check_fee_approved(executor, session):
    if executor.collected.get("fee_approved", "").lower() in ("no", "n", "decline"):
        executor.outcome = "declined"
        await session.say("No problem at all. Thank you for calling Cajun HVAC. Have a great day.")
        return "[call_ended]"
    return await executor.advance(session)

async def check_service_area(executor, session):
    address = executor.collected.get("address", "")
    zip_code = extract_zip(address)
    if zip_code not in executor.playbook["service_areas"]:
        executor.outcome = "out_of_area"
        await session.say("Unfortunately we don't service that area. I'd recommend searching online for providers near you. Thank you for calling Cajun HVAC.")
        return "[call_ended]"
    return await executor.advance(session)

async def confirm_booking(executor, session):
    closing = resolve_template(executor.playbook["scripts"]["closing_booked"], executor.collected)
    executor.outcome = "booked"
    await session.say(closing)
    return "[call_ended]"

async def take_message(executor, session):
    closing = resolve_template(executor.playbook["scripts"]["closing_message"], executor.collected)
    executor.outcome = "message_taken"
    await session.say(closing)
    return "[call_ended]"
```

### Key rules

1. `set_intent` can only be called once — second call returns an error string
2. `update_field` rejects placeholder values
3. `update_field` rejects if field_name doesn't match current step's expected field (strict one-at-a-time)
4. Action steps execute immediately on advance — the LLM never sees them
5. All verbatim speech uses `session.say()` directly, returns `"[delivered]"` or combines with next collect prompt via lookahead
6. `"[call_ended]"` signals the agent core to wait for TTS playout then disconnect
7. Consecutive action steps are valid — `advance()` → `execute_action()` → `advance()` recurses naturally and terminates when it hits a non-action step or end-of-steps (bounded by step array length)

### Future improvement
Accept any field from the current intent's remaining steps (not just the current step) to avoid re-asking when callers volunteer multiple pieces of info in one sentence.

---

## 6. Agent Integration

### Agent class

```python
class Assistant(Agent):
    def __init__(self, playbook: dict):
        self.executor = StepExecutor(playbook)
        self.playbook = playbook
        super().__init__(instructions=playbook["system_prompt"])

    async def on_enter(self) -> None:
        # TODO: respect playbook greeting mode (verbatim for now)
        greeting = self.playbook["scripts"]["greeting"]
        await self.session.say(greeting)

    @function_tool()
    async def set_intent(self, context: RunContext, intent: str) -> str:
        """Identify what the caller needs. Call this once after the greeting."""
        result = await self.executor.set_intent(intent, self.session)
        if result == "[call_ended]":
            await context.wait_for_playout()
            await self.session.shutdown()
        return result

    @function_tool()
    async def update_field(self, context: RunContext, field_name: str, value: str) -> str:
        """Record information the caller provided."""
        result = await self.executor.update_field(field_name, value, self.session)
        if result == "[call_ended]":
            await context.wait_for_playout()
            await self.session.shutdown()
        return result
```

### Entrypoint

```python
@server.rtc_session(agent_name="cajun-hvac-agent")
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    playbook = load_playbook()  # From disk for now, API later
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        tts=inference.TTS(model="deepgram/aura-2", voice="andromeda"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    agent = Assistant(playbook)
    await session.start(agent=agent, room=ctx.room, room_options=room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=lambda params: (
                noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC()
            ),
        ),
    ))
    await ctx.connect()

    # Post-call summary on disconnect
    @ctx.room.on("participant_disconnected")
    async def on_disconnect(participant):
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            await post_summary(agent.executor, ctx)
```

### Post-call summary

Includes retry logic (3 attempts, exponential backoff: 1s, 2s):

```python
async def post_summary(executor, ctx):
    payload = {
        "dnis": "...",                    # from SIP headers
        "caller_number": "...",           # from SIP headers, fallback to collected["phone"]
        "intent": executor.current_intent,
        "outcome": executor.outcome,
        "collected": executor.collected,
        "transcript": executor.transcript,
        "duration_seconds": "...",        # calculated from session start time
        "time_window": executor.time_window,
    }
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as http:
                resp = await http.post(f"{BACKEND_URL}/api/call/summary", json=payload)
                resp.raise_for_status()
                return
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
            else:
                logger.error(f"Failed to post call summary after 3 attempts: {e}")
```

---

## 7. File Structure

```
cajun-hvac/
├── src/
│   ├── agent.py              # Agent class, entrypoint, session setup
│   ├── step_executor.py      # StepExecutor class, advance(), deliver_speak()
│   ├── actions.py            # Action functions (check_fee_approved, check_service_area, etc.)
│   ├── playbook.py           # load_playbook()
│   ├── post_call.py          # post_summary() with retry logic
│   └── utils.py              # extract_zip(), shared helpers
├── compiler/
│   └── compile.py            # Playbook compiler (validate, build system prompt, output compiled JSON)
├── playbooks/
│   ├── cajun-hvac.json           # Raw playbook
│   └── cajun-hvac.compiled.json  # Compiled output (agent reads this)
├── tests/
│   ├── test_step_executor.py # Unit tests for StepExecutor
│   ├── test_actions.py       # Unit tests for action functions
│   └── test_compiler.py      # Unit tests for compiler
├── pyproject.toml
├── .env.example
├── .gitignore
└── Dockerfile
```

Separation principle: `step_executor.py` has zero LiveKit SDK dependency — pure call flow logic, independently testable. `agent.py` is the LiveKit glue. `actions.py` is business logic.

---

## 8. Transcript Capture

The agent hooks into STT events to build a running transcript. This lives in `agent.py` and writes into `executor.transcript`:

```python
@session.on("conversation_item_added")
def on_conversation_item(ev):
    text = ev.item.text_content
    if text:
        role = "Caller" if ev.item.role == "user" else "Agent"
        agent.executor.transcript += f"{role}: {text}\n"
```

The `conversation_item_added` event fires for both user and agent messages when they are committed to the chat history. Registered after `session.start()` in the entrypoint. The transcript is a simple newline-delimited string — no formatting, no timestamps. Good enough for Milestone 1.

---

## 9. Time Window Detection

`detect_time_window()` runs once at call start in the entrypoint, before the session begins. It reads the `hours` config from the compiled playbook and returns one of: `"office_hours"`, `"on_call"`, `"after_hours"`.

```python
def detect_time_window(playbook: dict) -> str:
    tz = ZoneInfo(playbook["meta"]["timezone"])
    now = datetime.now(tz)
    day = now.strftime("%a").lower()[:3]  # "mon", "tue", etc.
    current_time = now.strftime("%H:%M")

    office = playbook["hours"]["office"]
    if day in office["days"] and office["start"] <= current_time < office["end"]:
        return "office_hours"

    on_call = playbook["hours"].get("on_call")
    if on_call and on_call["start"] <= current_time < on_call["end"]:
        return "on_call"
    # TODO: handle on-call hours that span midnight (e.g., 17:00-06:00).
    # Current comparison breaks when end < start. Fine for Cajun HVAC (ends 22:00)
    # but will need fixing when clients have overnight on-call windows.

    return "after_hours"
```

Lives in `utils.py`. Called in the entrypoint and stored on the executor:

```python
agent.executor.time_window = detect_time_window(playbook)
```

---

## 10. Call Flow Walkthrough (routine_service happy path)

```
1. CONNECT
   Twilio → SIP trunk → LiveKit room → agent joins
   Loads compiled playbook, creates Assistant + StepExecutor

2. GREETING
   on_enter() → session.say("Thank you for calling Cajun HVAC...")

3. INTENT DETECTION
   Caller: "I need to get my AC looked at"
   LLM → set_intent("routine_service")
   StepExecutor: step 0 speak/verbatim → session.say(fee disclosure)
   Lookahead: step 1 is collect → returns collect prompt
   LLM waits for caller response

4. FEE APPROVAL
   Caller: "Yeah that's fine"
   LLM → update_field("fee_approved", "yes")
   StepExecutor: stores value → advance → action check_fee_approved
   "yes" → advance → step 3 collect/name → returns prompt

5. COLLECT NAME → PHONE → ADDRESS
   Each: caller provides info → update_field → stores → advance → next collect

6. SERVICE AREA CHECK
   advance → action check_service_area
   extract_zip → found in service_areas → advance → collect/issue_description

7. COLLECT ISSUE → APPOINTMENT TIME
   Same pattern as step 5

8. CONFIRM BOOKING
   advance → action confirm_booking
   Resolves {appointment_time} in closing script → session.say() → "[call_ended]"
   Agent waits for playout → session.shutdown()

9. POST-CALL SUMMARY
   participant_disconnected → post_summary() with retry → payload to Laravel API
```

### Alternate paths

| Scenario | Branch point | Outcome |
|---|---|---|
| Fee declined | check_fee_approved sees "no" | session.say(goodbye) → [call_ended] |
| Out of area | check_service_area, zip not in list | session.say(out of area message) → [call_ended] |
| Unknown intent | set_intent with unrecognized value | Routes to _fallback → collect name, phone → take_message |
| Declined appointment time | System prompt rule | LLM asks what works instead → update_field with new time |

---

## 11. Conventions & Signals

| Signal | Meaning | Agent behavior |
|---|---|---|
| `"[delivered]"` | Verbatim speech already spoken, nothing for LLM to do | LLM acknowledges naturally, waits for caller |
| `"[call_ended]"` | Call is ending, closing speech already spoken | Agent waits for TTS playout, then disconnects |
| Collect prompt string | Instruction for the LLM to act on | LLM speaks it naturally (guided) and waits for response |

System prompt documents these explicitly so the LLM knows how to handle each.

---

## 12. Known Limitations & Future Work

| Item | Status | Notes |
|---|---|---|
| Flexible field acceptance (multi-field in one sentence) | Future | Currently strict one-at-a-time matching |
| API-based playbook loading by DNIS | Future | Currently reads from disk |
| Multi-client support | Future | Single playbook for now |
| Additional intents beyond routine_service + _fallback | Future | Each intent just needs steps in the playbook |
| Playbook hot-reload | Future | Currently requires agent restart |
| Greeting mode from playbook | Future | Hardcoded verbatim for milestone 1 |
| Transcript capture | Milestone 1 | Hook into user_speech_committed / agent_speech_committed events (Section 8) |
| time_window detection | Milestone 1 | detect_time_window() in utils.py, called at entrypoint (Section 9) |
