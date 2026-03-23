# Time Window Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route off-hours calls to a take-a-message flow (except emergencies) so the agent doesn't promise bookings when no one is in the office.

**Architecture:** StepExecutor.set_intent() checks time_window and redirects non-emergency intents to `_after_hours` when off-hours. System prompt gets a conditional off-hours notice. on_enter() picks the right greeting script. After-hours support is optional per client (both `_after_hours` intent and `after_hours_greeting` script must be present, or neither).

**Tech Stack:** Python, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-03-23-time-window-routing-design.md`

---

### Task 1: Add `requested_intent` attribute to StepExecutor + off-hours routing tests

**Files:**
- Modify: `src/step_executor.py:15-23` (add `requested_intent` to `__init__`)
- Test: `tests/test_step_executor.py`

- [ ] **Step 1: Write failing tests for off-hours routing**

Add a playbook fixture with `_after_hours` intent, then write four tests. Add these after the existing `test_warranty_speak_then_collect` test:

```python
PLAYBOOK_WITH_AFTER_HOURS = {
    "intents": {
        "routine_service": {
            "label": "Routine Service",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for name."},
                {"type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for phone."},
            ],
        },
        "emergency": {
            "label": "Emergency Service",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for name."},
                {"type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for phone."},
                {"type": "action", "fn": "dispatch_oncall_tech"},
            ],
        },
        "cancellation": {
            "label": "Cancel Appointment",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
                {"type": "action", "fn": "take_message"},
            ],
        },
        "billing": {
            "label": "Billing Question",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
                {"type": "action", "fn": "take_message"},
            ],
        },
        "_after_hours": {
            "label": "After Hours Message",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for name."},
                {"type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for callback number."},
                {"type": "action", "fn": "take_message"},
            ],
        },
        "_fallback": {
            "label": "Fallback",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            ],
        },
    },
    "service_areas": [],
    "scripts": {},
}


# --- time window routing ---


@pytest.mark.asyncio
async def test_off_hours_routine_service_routes_to_after_hours():
    """Off-hours non-emergency intent is redirected to _after_hours."""
    executor = StepExecutor(PLAYBOOK_WITH_AFTER_HOURS)
    executor.time_window = "on_call"
    session = make_mock_session()
    result = await executor.set_intent("routine_service", session)
    assert executor.current_intent == "_after_hours"
    assert executor.requested_intent == "routine_service"
    assert "Ask for name." in result


@pytest.mark.asyncio
async def test_off_hours_emergency_keeps_full_flow():
    """Emergency intent is NOT redirected off-hours."""
    executor = StepExecutor(PLAYBOOK_WITH_AFTER_HOURS)
    executor.time_window = "after_hours"
    session = make_mock_session()
    await executor.set_intent("emergency", session)
    assert executor.current_intent == "emergency"
    assert executor.requested_intent is None


@pytest.mark.asyncio
async def test_off_hours_all_non_emergency_intents_reroute():
    """All non-emergency intents reroute to _after_hours off-hours, including _fallback."""
    non_emergency = ["routine_service", "cancellation", "billing", "_fallback"]
    for intent_name in non_emergency:
        executor = StepExecutor(PLAYBOOK_WITH_AFTER_HOURS)
        executor.time_window = "on_call"
        session = make_mock_session()
        await executor.set_intent(intent_name, session)
        assert executor.current_intent == "_after_hours", f"{intent_name} was not rerouted"
        assert executor.requested_intent == intent_name


@pytest.mark.asyncio
async def test_office_hours_no_reroute():
    """Office hours: intents route normally, no redirect."""
    executor = StepExecutor(PLAYBOOK_WITH_AFTER_HOURS)
    executor.time_window = "office_hours"
    session = make_mock_session()
    await executor.set_intent("routine_service", session)
    assert executor.current_intent == "routine_service"
    assert executor.requested_intent is None


@pytest.mark.asyncio
async def test_off_hours_no_after_hours_intent_runs_normal_flow():
    """Off-hours with no _after_hours intent: runs normal flow, no crash."""
    executor = StepExecutor(MINIMAL_PLAYBOOK)  # has no _after_hours intent
    executor.time_window = "on_call"
    session = make_mock_session()
    await executor.set_intent("routine_service", session)
    assert executor.current_intent == "routine_service"
    assert executor.requested_intent is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_step_executor.py -v -k "off_hours or office_hours_no_reroute"`
Expected: FAIL — `StepExecutor` has no `requested_intent` attribute

- [ ] **Step 3: Implement off-hours routing in StepExecutor**

In `src/step_executor.py`, add `requested_intent` to `__init__` and add routing logic to `set_intent`:

```python
# In __init__, after self.call_start_time line:
self.requested_intent: str | None = None
```

Add `import logging` at the top of the file, and a logger:

```python
import logging

from src.actions import ACTION_REGISTRY

logger = logging.getLogger("agent")
```

In `set_intent`, add the routing check between the unknown-intent fallback and setting `self.current_intent`:

```python
async def set_intent(self, intent: str, session) -> str:
    if self.current_intent is not None:
        return "Intent has already been set. Continue with update_field."

    if intent not in self.playbook["intents"]:
        intent = "_fallback"

    # Off-hours routing: redirect non-emergency to _after_hours
    if (
        self.time_window is not None
        and self.time_window != "office_hours"
        and intent != "emergency"
    ):
        if "_after_hours" in self.playbook["intents"]:
            self.requested_intent = intent
            intent = "_after_hours"
        else:
            logger.warning(
                "Off-hours call but no _after_hours intent configured — running normal flow"
            )

    self.current_intent = intent
    self.current_step_index = 0
    return await self._dispatch_current_step(session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_step_executor.py -v`
Expected: All tests pass (existing + 5 new)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/step_executor.py tests/test_step_executor.py
git commit -m "feat: add off-hours routing in StepExecutor

set_intent redirects non-emergency intents to _after_hours when
time_window is not office_hours. Emergency always gets full flow.
Graceful fallback when _after_hours intent is not configured."
```

---

### Task 2: Compiler validation for after-hours pair + tests

**Files:**
- Modify: `compiler/compile.py:23-81` (add validation in `validate()`)
- Test: `tests/test_compiler.py`

- [ ] **Step 1: Write failing tests for after-hours validation**

Add these tests at the end of `tests/test_compiler.py`:

```python
def test_after_hours_intent_and_script_both_present_passes():
    """Playbook with both _after_hours intent and after_hours_greeting compiles fine."""
    pb = json.loads(json.dumps(VALID_PLAYBOOK))
    pb["scripts"]["after_hours_greeting"] = "Office is closed."
    pb["intents"]["_after_hours"] = {
        "label": "After Hours Message",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    validate(pb)  # should not raise


def test_after_hours_intent_without_script_raises():
    """_after_hours intent without after_hours_greeting script is a compiler error."""
    pb = json.loads(json.dumps(VALID_PLAYBOOK))
    pb["intents"]["_after_hours"] = {
        "label": "After Hours Message",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    with pytest.raises(CompilerError, match="after_hours_greeting"):
        validate(pb)


def test_after_hours_script_without_intent_raises():
    """after_hours_greeting script without _after_hours intent is a compiler error."""
    pb = json.loads(json.dumps(VALID_PLAYBOOK))
    pb["scripts"]["after_hours_greeting"] = "Office is closed."
    with pytest.raises(CompilerError, match="_after_hours"):
        validate(pb)


def test_no_after_hours_support_passes():
    """Playbook without _after_hours or after_hours_greeting compiles fine."""
    validate(VALID_PLAYBOOK)  # should not raise — already works, but making it explicit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compiler.py -v -k "after_hours"`
Expected: 2 tests fail (the `_raises` tests), 2 pass

- [ ] **Step 3: Add validation logic to compiler**

In `compiler/compile.py`, add the after-hours pair validation inside `validate()`, after the `_fallback` check (after line 33):

```python
# After-hours support: _after_hours intent and after_hours_greeting must both be present, or neither
has_after_hours_intent = "_after_hours" in playbook["intents"]
has_after_hours_greeting = "after_hours_greeting" in playbook.get("scripts", {})
if has_after_hours_intent and not has_after_hours_greeting:
    raise CompilerError(
        "Intent '_after_hours' is defined but 'scripts.after_hours_greeting' is missing — add the greeting or remove the intent"
    )
if has_after_hours_greeting and not has_after_hours_intent:
    raise CompilerError(
        "Script 'after_hours_greeting' is defined but intent '_after_hours' is missing — add the intent or remove the script"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_compiler.py -v`
Expected: All tests pass (existing + 4 new)

- [ ] **Step 5: Commit**

```bash
git add compiler/compile.py tests/test_compiler.py
git commit -m "feat: compiler validates after-hours intent/script pair

_after_hours intent and after_hours_greeting script must both be present
or both absent. Prevents runtime KeyError from misconfigured playbooks."
```

---

### Task 3: Add off-hours notice to system prompt + test

**Files:**
- Modify: `compiler/compile.py:83-163` (add section to `build_system_prompt()`)
- Test: `tests/test_compiler.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_compiler.py`:

```python
def test_system_prompt_includes_off_hours_notice():
    """System prompt includes conditional off-hours guidance for the LLM."""
    result = compile_playbook(VALID_PLAYBOOK, "test.json")
    prompt = result["system_prompt"]
    assert "outside of office hours" in prompt


def test_after_hours_intent_excluded_from_available_intents():
    """_after_hours (underscore prefix) must NOT appear in Available intents list."""
    pb = json.loads(json.dumps(VALID_PLAYBOOK))
    pb["scripts"]["after_hours_greeting"] = "Office is closed."
    pb["intents"]["_after_hours"] = {
        "label": "After Hours Message",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    result = compile_playbook(pb, "test.json")
    prompt = result["system_prompt"]
    # Extract the Available intents section
    intents_start = prompt.index("# Available intents")
    intents_end = prompt.index("#", intents_start + 1)
    intents_section = prompt[intents_start:intents_end]
    assert "_after_hours" not in intents_section
    assert "_fallback" not in intents_section  # confirm existing behavior too
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_compiler.py::test_system_prompt_includes_off_hours_notice -v`
Expected: FAIL — prompt does not contain "outside of office hours"

- [ ] **Step 3: Add off-hours notice to system prompt**

In `compiler/compile.py`, inside `build_system_prompt()`, add a new section in the return string. Insert it after the `# Conversation rules` section and before `# Guardrails`:

```python
# After-hours handling
- If the caller is reaching you outside of office hours, let them know the office is currently closed. If they describe an emergency, use set_intent("emergency"). For all other needs, use set_intent with their intent — the system will handle routing appropriately.
```

The exact insertion: find the line `# Guardrails` in the f-string and add the section above it:

```python
# After-hours handling
- If the caller is reaching you outside of office hours, let them know the office is currently closed. If they describe an emergency, use set_intent("emergency"). For all other needs, use set_intent with their intent — the system will handle routing appropriately.

# Guardrails
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_compiler.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add compiler/compile.py tests/test_compiler.py
git commit -m "feat: add off-hours notice to system prompt

Conditional phrasing tells the LLM to set the right tone when the
office is closed. Always present in compiled prompt (compile-time),
harmless during office hours."
```

---

### Task 4: Update playbook JSON with after-hours config + recompile

**Files:**
- Modify: `playbooks/cajun-hvac.json`
- Rebuild: `playbooks/cajun-hvac.compiled.json`

- [ ] **Step 1: Add after_hours_greeting to scripts**

In `playbooks/cajun-hvac.json`, add to the `"scripts"` object:

```json
"after_hours_greeting": "Thank you for calling Cajun HVAC. Our office is currently closed. If this is an emergency such as no heat, no cooling, or a gas leak, please let me know right away. Otherwise, I can take your information and have someone call you back during business hours."
```

- [ ] **Step 2: Add _after_hours intent**

In `playbooks/cajun-hvac.json`, add to the `"intents"` object:

```json
"_after_hours": {
  "label": "After Hours Message",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback number." },
    { "type": "action", "fn": "take_message" }
  ]
}
```

- [ ] **Step 3: Recompile and verify**

Run: `uv run python compiler/compile.py playbooks/cajun-hvac.json`
Expected: `Compiled: playbooks/cajun-hvac.compiled.json`

Verify the compiled output contains the after-hours notice and the `_after_hours` intent.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add playbooks/cajun-hvac.json playbooks/cajun-hvac.compiled.json
git commit -m "feat: add after-hours greeting and _after_hours intent to Cajun HVAC playbook

Callers off-hours hear the after-hours greeting and get routed to
take-a-message flow (except emergencies)."
```

---

### Task 5: Update on_enter() greeting selection in agent.py

**Files:**
- Modify: `src/agent.py:44-47` (update `on_enter()`)

- [ ] **Step 1: Update on_enter to check time_window**

In `src/agent.py`, replace the `on_enter` method:

```python
async def on_enter(self) -> None:
    scripts = self.playbook["scripts"]
    if (
        self.executor.time_window is not None
        and self.executor.time_window != "office_hours"
        and "after_hours_greeting" in scripts
    ):
        greeting = scripts["after_hours_greeting"]
    else:
        greeting = scripts["greeting"]
    await self.session.say(greeting)
```

This handles three cases:
- Office hours → regular greeting
- Off-hours with after_hours_greeting configured → after-hours greeting
- Off-hours without after_hours_greeting (client doesn't use it) → regular greeting

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass (on_enter is not unit tested — LiveKit dependency)

- [ ] **Step 3: Lint**

Run: `uv run ruff check src/ compiler/ tests/`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/agent.py
git commit -m "feat: on_enter picks after-hours greeting when off-hours

Checks executor.time_window and uses after_hours_greeting script when
configured. Falls back to regular greeting for office hours or clients
without after-hours config."
```

---

### Task 6: Update post-call summary with requested_intent

**Files:**
- Modify: `src/post_call.py:17-25` (add `requested_intent` to existing payload)

- [ ] **Step 1: Update post_summary payload**

In `src/post_call.py`, add one line to the existing payload dict — insert after the `"intent"` line:

```python
"requested_intent": executor.requested_intent or executor.current_intent,
```

The `"intent"` field stays as `current_intent` for backwards compatibility (it's what actually ran). `"requested_intent"` is new — what the caller originally asked for.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Lint and format**

Run: `uv run ruff check src/ compiler/ tests/ && uv run ruff format src/ compiler/ tests/`
Expected: No errors, no changes

- [ ] **Step 4: Commit**

```bash
git add src/post_call.py
git commit -m "feat: include requested_intent in post-call summary

When off-hours routing overrides the intent, requested_intent shows
what the caller actually wanted (e.g. routine_service) while intent
shows what ran (_after_hours)."
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Lint and format**

Run: `uv run ruff check src/ compiler/ tests/ && uv run ruff format src/ compiler/ tests/`
Expected: Clean

- [ ] **Step 3: Verify compiled playbook**

Run: `uv run python compiler/compile.py playbooks/cajun-hvac.json`
Spot-check: `_after_hours` intent present, `after_hours_greeting` in scripts, off-hours notice in system prompt.

- [ ] **Step 4: Update CLAUDE.md**

Add `_after_hours` to the intents list:

```
- `_after_hours` — off-hours take-a-message (name → phone → take message). Only active when time_window != office_hours.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add _after_hours intent to CLAUDE.md"
```
