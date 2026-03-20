# Caller Intents Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 8 new caller intents (emergency, cancellation, reschedule, eta_request, warranty, billing, complaint, commercial) to the voice agent.

**Architecture:** Playbook JSON defines step sequences per intent. Two new action functions (`dispatch_oncall_tech`, `check_emergency_confirmed`) added to the registry. Compiler generates updated system prompt with all intent labels, emergency qualifiers, and expanded field name list. StepExecutor and agent.py are unchanged — the architecture handles new intents generically.

**Tech Stack:** Python, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-03-19-caller-intents-expansion-design.md`

---

### Task 1: Add `dispatch_oncall_tech` action function

**Files:**
- Test: `tests/test_actions.py`
- Modify: `src/actions.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_actions.py`. First, add `closing_dispatched` to the test PLAYBOOK's scripts dict and import the new function:

```python
# Add to the imports at the top:
from src.actions import (
    check_fee_approved,
    check_service_area,
    confirm_booking,
    dispatch_oncall_tech,
    take_message,
)

# Add to PLAYBOOK["scripts"]:
#   "closing_dispatched": "Technician dispatched. We'll call {phone}.",
```

Then add the test:

```python
@pytest.mark.asyncio
async def test_dispatch_oncall_tech_resolves_template():
    executor = StepExecutor(PLAYBOOK)
    executor.collected = {"phone": "337-232-2341", "name": "Eric", "address": "456 Cypress St"}
    session = make_mock_session()
    result = await dispatch_oncall_tech(executor, session)
    assert "[call_ended]" in result
    assert "Technician dispatched. We'll call 337-232-2341." in result
    assert executor.outcome == "dispatched"
    session.say.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_actions.py::test_dispatch_oncall_tech_resolves_template -v`
Expected: FAIL — `ImportError: cannot import name 'dispatch_oncall_tech'`

- [ ] **Step 3: Write the implementation**

Add to `src/actions.py`, before the `ACTION_REGISTRY` dict:

```python
async def dispatch_oncall_tech(executor, session) -> str:
    closing = resolve_template(
        executor.playbook["scripts"]["closing_dispatched"], executor.collected
    )
    executor.outcome = "dispatched"
    return f'Say EXACTLY: "{closing}" [call_ended]'
```

Add to `ACTION_REGISTRY`:
```python
"dispatch_oncall_tech": dispatch_oncall_tech,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_actions.py::test_dispatch_oncall_tech_resolves_template -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/actions.py tests/test_actions.py
git commit -m "feat: add dispatch_oncall_tech action function"
```

---

### Task 2: Add `check_emergency_confirmed` action function

**Files:**
- Test: `tests/test_actions.py`
- Modify: `src/actions.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_actions.py`. Import the new function (add `check_emergency_confirmed` to the import block). Then add two tests:

```python
@pytest.mark.asyncio
async def test_check_emergency_confirmed_yes_advances():
    """When caller confirms, advance to next step (dispatch_oncall_tech)."""
    playbook = {
        "meta": {"company_name": "Test Co", "timezone": "America/Chicago"},
        "intents": {
            "emergency": {
                "label": "Emergency",
                "steps": [
                    {"type": "collect", "field": "emergency_confirmed", "mode": "guided", "prompt": "Confirm dispatch."},
                    {"type": "action", "fn": "check_emergency_confirmed"},
                    {"type": "action", "fn": "dispatch_oncall_tech"},
                ],
            },
            "_fallback": {"label": "Fallback", "steps": [{"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"}]},
        },
        "service_areas": [],
        "scripts": {"closing_dispatched": "Tech sent to {phone}."},
    }
    executor = StepExecutor(playbook)
    executor.current_intent = "emergency"
    executor.current_step_index = 1  # on the check_emergency_confirmed action step
    executor.collected = {"name": "Eric", "phone": "337-232-2341", "address": "456 Cypress St", "emergency_confirmed": "yes"}
    session = make_mock_session()
    result = await check_emergency_confirmed(executor, session)
    # Should advance through dispatch_oncall_tech and return closing
    assert "[call_ended]" in result
    assert executor.outcome == "dispatched"


@pytest.mark.asyncio
async def test_check_emergency_confirmed_no_asks_what_to_change():
    """When caller says no, return guided prompt asking what to change."""
    executor = StepExecutor(PLAYBOOK)
    executor.collected = {"emergency_confirmed": "no"}
    session = make_mock_session()
    result = await check_emergency_confirmed(executor, session)
    assert "what" in result.lower() and "change" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_actions.py -k "check_emergency_confirmed" -v`
Expected: FAIL — `ImportError: cannot import name 'check_emergency_confirmed'`

- [ ] **Step 3: Write the implementation**

Add to `src/actions.py`, before the `ACTION_REGISTRY` dict:

```python
async def check_emergency_confirmed(executor, session) -> str:
    confirmed = executor.collected.get("emergency_confirmed", "").lower()
    if confirmed in ("no", "n", "nope", "not yet", "hold on", "wait"):
        return "The caller wants to correct something. Ask what they'd like to change — their name, phone number, or address."
    return await executor.advance(session)
```

Add to `ACTION_REGISTRY`:
```python
"check_emergency_confirmed": check_emergency_confirmed,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_actions.py -k "check_emergency_confirmed" -v`
Expected: PASS

- [ ] **Step 5: Run full action test suite**

Run: `uv run pytest tests/test_actions.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/actions.py tests/test_actions.py
git commit -m "feat: add check_emergency_confirmed action function"
```

---

### Task 3: Add all 8 intents to playbook JSON

**Files:**
- Modify: `playbooks/cajun-hvac.json`

- [ ] **Step 1: Add `emergency_qualifiers` and `closing_dispatched` script**

Add `emergency_qualifiers` array after `service_areas` in `playbooks/cajun-hvac.json`:

```json
"emergency_qualifiers": ["no heat", "no cooling", "no AC", "gas leak", "gas smell", "flooding", "water leak", "pipe burst", "electrical fire", "sparking", "no hot water"],
```

Add `closing_dispatched` to the `scripts` object:

```json
"closing_dispatched": "I've contacted our on-call technician. They'll be reaching out to you shortly at {phone}. Thank you for calling Cajun HVAC."
```

- [ ] **Step 2: Add `emergency` intent**

Add to the `intents` object in `playbooks/cajun-hvac.json`, before `_fallback`:

```json
"emergency": {
  "label": "Emergency Service",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "address", "mode": "guided", "prompt": "Ask for the full service address including zip code." },
    { "type": "collect", "field": "emergency_confirmed", "mode": "guided", "prompt": "Summarize back to the caller — their name, phone number, and service address — and confirm that a technician is being sent. Do NOT repeat the emergency description back." },
    { "type": "action", "fn": "check_emergency_confirmed" },
    { "type": "action", "fn": "dispatch_oncall_tech" }
  ]
},
```

- [ ] **Step 3: Add 6 message-taking intents**

Add these to the `intents` object, before `_fallback`:

```json
"cancellation": {
  "label": "Cancel Appointment",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "cancellation_reason", "mode": "guided", "prompt": "Ask the reason for the cancellation." },
    { "type": "action", "fn": "take_message" }
  ]
},
"reschedule": {
  "label": "Reschedule Appointment",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "preferred_time", "mode": "guided", "prompt": "Ask when they'd like to reschedule to." },
    { "type": "action", "fn": "take_message" }
  ]
},
"eta_request": {
  "label": "Technician ETA Request",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "action", "fn": "take_message" }
  ]
},
"warranty": {
  "label": "Warranty Claim",
  "steps": [
    { "type": "speak", "mode": "verbatim", "text": "All of our work comes with a one-year parts and labor warranty. Let me get your information so we can look into this for you." },
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "issue_description", "mode": "guided", "prompt": "Ask what warranty issue they're experiencing." },
    { "type": "action", "fn": "take_message" }
  ]
},
"billing": {
  "label": "Billing Question",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "issue_description", "mode": "guided", "prompt": "Ask about their billing question or concern." },
    { "type": "action", "fn": "take_message" }
  ]
},
"complaint": {
  "label": "Customer Complaint",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "issue_description", "mode": "guided", "prompt": "Ask them to describe their complaint." },
    { "type": "action", "fn": "take_message" }
  ]
},
"commercial": {
  "label": "Commercial Service Request",
  "steps": [
    { "type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for the caller's full name." },
    { "type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for a callback phone number." },
    { "type": "collect", "field": "issue_description", "mode": "guided", "prompt": "Ask what commercial service they need." },
    { "type": "action", "fn": "take_message" }
  ]
},
```

- [ ] **Step 4: Validate JSON syntax**

Run: `uv run python -c "import json; json.load(open('playbooks/cajun-hvac.json'))"`
Expected: No error (valid JSON)

- [ ] **Step 5: Commit**

```bash
git add playbooks/cajun-hvac.json
git commit -m "feat: add 8 new intents and emergency_qualifiers to playbook"
```

---

### Task 4: Update compiler system prompt

**Files:**
- Test: `tests/test_compiler.py`
- Modify: `compiler/compile.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_compiler.py`:

```python
def test_compile_system_prompt_includes_emergency_qualifiers():
    pb = json.loads(json.dumps(VALID_PLAYBOOK))
    pb["emergency_qualifiers"] = ["no heat", "gas leak"]
    pb["intents"]["emergency"] = {
        "label": "Emergency Service",
        "steps": [{"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"}],
    }
    result = compile_playbook(pb, "test.json")
    prompt = result["system_prompt"]
    assert "no heat" in prompt
    assert "gas leak" in prompt
    assert "emergency" in prompt.lower()


def test_compile_system_prompt_without_emergency_qualifiers():
    """emergency_qualifiers is optional — playbook without it should compile fine."""
    result = compile_playbook(VALID_PLAYBOOK, "test.json")
    # Should not crash, just no qualifiers section
    assert "system_prompt" in result


def test_compile_system_prompt_includes_new_field_names():
    result = compile_playbook(VALID_PLAYBOOK, "test.json")
    prompt = result["system_prompt"]
    assert "cancellation_reason" in prompt
    assert "preferred_time" in prompt
    assert "emergency_confirmed" in prompt


def test_compile_all_ten_intents():
    """Full playbook with all 10 intents compiles without error."""
    pb = json.loads(json.dumps(VALID_PLAYBOOK))
    pb["scripts"]["closing_dispatched"] = "Tech sent to {phone}."
    pb["emergency_qualifiers"] = ["no heat", "gas leak"]
    pb["intents"]["emergency"] = {
        "label": "Emergency Service",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "check_emergency_confirmed"},
            {"type": "action", "fn": "dispatch_oncall_tech"},
        ],
    }
    pb["intents"]["cancellation"] = {
        "label": "Cancel Appointment",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    pb["intents"]["reschedule"] = {
        "label": "Reschedule Appointment",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    pb["intents"]["eta_request"] = {
        "label": "Technician ETA Request",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    pb["intents"]["warranty"] = {
        "label": "Warranty Claim",
        "steps": [
            {"type": "speak", "mode": "verbatim", "text": "Warranty info."},
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    pb["intents"]["billing"] = {
        "label": "Billing Question",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    pb["intents"]["complaint"] = {
        "label": "Customer Complaint",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    pb["intents"]["commercial"] = {
        "label": "Commercial Service Request",
        "steps": [
            {"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"},
            {"type": "action", "fn": "take_message"},
        ],
    }
    result = compile_playbook(pb, "test.json")
    assert len(result["intents"]) == 10
    prompt = result["system_prompt"]
    # All non-underscore intents should appear in Available intents
    for intent in ["routine_service", "emergency", "cancellation", "reschedule", "eta_request", "warranty", "billing", "complaint", "commercial"]:
        assert intent in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_compiler.py -k "emergency_qualifiers or new_field_names or ten_intents" -v`
Expected: 3 of 4 tests FAIL (`test_compile_system_prompt_without_emergency_qualifiers` already passes since it only checks compilation succeeds)

- [ ] **Step 3: Update `build_system_prompt` in `compiler/compile.py`**

Three changes to `build_system_prompt`:

**3a.** After `intents = playbook["intents"]` (line 88), add:
```python
    emergency_qualifiers = playbook.get("emergency_qualifiers", [])
```

**3b.** Replace the field name list in the system prompt (line 119). Change:
```
The field names are: fee_approved, name, phone, address, issue_description, appointment_time, booking_confirmed. DO NOT invent your own field names like "full_name" or "phone_number".
```
To:
```
The field names are: fee_approved, name, phone, address, issue_description, appointment_time, booking_confirmed, cancellation_reason, preferred_time, emergency_confirmed. DO NOT invent your own field names like "full_name" or "phone_number".
```

**3c.** After the "Available intents" section (after line 128), add emergency qualifiers and routing rules. Insert between the intent list and "Company info" section:

```python
# Add this after the f-string line for intent_lines join:
emergency_section = ""
if emergency_qualifiers:
    qualifiers_str = ", ".join(emergency_qualifiers)
    emergency_section = f"""
# Emergency routing
If the caller describes any of these situations, use set_intent("emergency"): {qualifiers_str}.
For non-urgent service needs, use set_intent("routine_service") instead.
"""
```

Then include `{emergency_section}` in the f-string between "Available intents" and "Company info".

**3d.** Add to the "Conversation rules" section in the system prompt f-string:
```
- If the caller declines to give a reason for cancellation, record their response as-is.
```

- [ ] **Step 4: Also pass `emergency_qualifiers` through in `compile_playbook`**

In the `compile_playbook` function (around line 149-166), add to the returned dict:
```python
"emergency_qualifiers": playbook.get("emergency_qualifiers", []),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_compiler.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add compiler/compile.py tests/test_compiler.py
git commit -m "feat: update compiler for new intents, emergency qualifiers, field names"
```

---

### Task 5: Update agent.py tool docstring

**Files:**
- Modify: `src/agent.py:65-67`

- [ ] **Step 1: Update the `update_field` docstring**

In `src/agent.py`, change the docstring at lines 65-72 from:

```python
        """Record information the caller provided. Use the EXACT field name
        from the current step prompt. Common fields: fee_approved, name, phone,
        address, issue_description, appointment_time.

        Args:
            field_name: The exact field name for the current step (e.g. "name", "phone", "address")
            value: The caller's actual response. NEVER use placeholders.
        """
```

To:

```python
        """Record information the caller provided. Use the EXACT field name
        from the current step prompt.

        Args:
            field_name: The exact field name for the current step (e.g. "name", "phone", "address")
            value: The caller's actual response. NEVER use placeholders.
        """
```

The system prompt (generated by the compiler) is the authoritative source for field names. The docstring should not enumerate them.

- [ ] **Step 2: Commit**

```bash
git add src/agent.py
git commit -m "fix: remove stale field list from update_field docstring"
```

---

### Task 6: Add step executor tests for new intent flows

**Files:**
- Test: `tests/test_step_executor.py`

- [ ] **Step 1: Write emergency full-flow test**

Add a playbook and test to `tests/test_step_executor.py`. First, register test versions of the new actions at the top of the file (same pattern as the existing `_test_check_fee_approved`):

```python
async def _test_check_emergency_confirmed(executor, session):
    confirmed = executor.collected.get("emergency_confirmed", "").lower()
    if confirmed in ("no", "n", "nope", "not yet", "hold on", "wait"):
        return "The caller wants to correct something. Ask what they'd like to change."
    return await executor.advance(session)


async def _test_dispatch_oncall_tech(executor, session):
    executor.outcome = "dispatched"
    return 'Say EXACTLY: "Tech dispatched." [call_ended]'


actions.ACTION_REGISTRY["check_emergency_confirmed"] = _test_check_emergency_confirmed
actions.ACTION_REGISTRY["dispatch_oncall_tech"] = _test_dispatch_oncall_tech
```

Add the emergency playbook:

```python
PLAYBOOK_EMERGENCY = {
    "intents": {
        "emergency": {
            "label": "Emergency Service",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for name."},
                {"type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for phone."},
                {"type": "collect", "field": "address", "mode": "guided", "prompt": "Ask for address."},
                {"type": "collect", "field": "emergency_confirmed", "mode": "guided", "prompt": "Confirm dispatch."},
                {"type": "action", "fn": "check_emergency_confirmed"},
                {"type": "action", "fn": "dispatch_oncall_tech"},
            ],
        },
        "_fallback": {
            "label": "Fallback",
            "steps": [{"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"}],
        },
    },
    "service_areas": [],
    "scripts": {"closing_dispatched": "Tech sent."},
}
```

Add the test:

```python
@pytest.mark.asyncio
async def test_emergency_full_flow():
    """Emergency: collect name/phone/address → confirm → dispatch."""
    executor = StepExecutor(PLAYBOOK_EMERGENCY)
    session = make_mock_session()

    result = await executor.set_intent("emergency", session)
    assert result == "Ask for name."

    result = await executor.update_field("name", "Eric Tails", session)
    assert result == "Ask for phone."

    result = await executor.update_field("phone", "337-232-2341", session)
    assert result == "Ask for address."

    result = await executor.update_field("address", "456 Cypress St 70502", session)
    assert result == "Confirm dispatch."

    result = await executor.update_field("emergency_confirmed", "yes", session)
    assert "[call_ended]" in result
    assert executor.outcome == "dispatched"
```

- [ ] **Step 2: Write emergency correction flow test**

```python
@pytest.mark.asyncio
async def test_emergency_confirmed_no_allows_correction():
    """When caller says no at confirmation, they can correct a field via overwrite."""
    executor = StepExecutor(PLAYBOOK_EMERGENCY)
    session = make_mock_session()

    await executor.set_intent("emergency", session)
    await executor.update_field("name", "Eric Tails", session)
    await executor.update_field("phone", "337-232-2341", session)
    await executor.update_field("address", "456 Cypress St 70502", session)

    result = await executor.update_field("emergency_confirmed", "no", session)
    assert "change" in result.lower()

    # Overwrite a previously collected field — step stays on emergency_confirmed
    result = await executor.update_field("phone", "337-999-8888", session)
    assert executor.collected["phone"] == "337-999-8888"
    assert "emergency_confirmed" in result

    # Re-confirm
    result = await executor.update_field("emergency_confirmed", "yes", session)
    assert "[call_ended]" in result
    assert executor.outcome == "dispatched"
```

- [ ] **Step 3: Write message-taking intent test (cancellation)**

Add the playbook:

```python
PLAYBOOK_CANCELLATION = {
    "intents": {
        "cancellation": {
            "label": "Cancel Appointment",
            "steps": [
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for name."},
                {"type": "collect", "field": "phone", "mode": "guided", "prompt": "Ask for phone."},
                {"type": "collect", "field": "cancellation_reason", "mode": "guided", "prompt": "Ask reason."},
                {"type": "action", "fn": "take_message"},
            ],
        },
        "_fallback": {
            "label": "Fallback",
            "steps": [{"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"}],
        },
    },
    "service_areas": [],
    "scripts": {"closing_message": "Message taken. Goodbye."},
}
```

Register a test `take_message`:

```python
async def _test_take_message(executor, session):
    executor.outcome = "message_taken"
    return 'Say EXACTLY: "Message taken. Goodbye." [call_ended]'


actions.ACTION_REGISTRY["take_message"] = _test_take_message
```

Add the test:

```python
@pytest.mark.asyncio
async def test_cancellation_full_flow():
    """Cancellation: collect name/phone/reason → take_message."""
    executor = StepExecutor(PLAYBOOK_CANCELLATION)
    session = make_mock_session()

    result = await executor.set_intent("cancellation", session)
    assert result == "Ask for name."

    result = await executor.update_field("name", "Eric Tails", session)
    assert result == "Ask for phone."

    result = await executor.update_field("phone", "337-232-2341", session)
    assert result == "Ask reason."

    result = await executor.update_field("cancellation_reason", "Changed my mind", session)
    assert "[call_ended]" in result
    assert executor.outcome == "message_taken"
```

- [ ] **Step 4: Write warranty speak-then-collect test**

Add the playbook:

```python
PLAYBOOK_WARRANTY = {
    "intents": {
        "warranty": {
            "label": "Warranty Claim",
            "steps": [
                {"type": "speak", "mode": "verbatim", "text": "All work has a one-year warranty."},
                {"type": "collect", "field": "name", "mode": "guided", "prompt": "Ask for name."},
            ],
        },
        "_fallback": {
            "label": "Fallback",
            "steps": [{"type": "collect", "field": "name", "mode": "guided", "prompt": "Name?"}],
        },
    },
    "service_areas": [],
    "scripts": {},
}
```

Add the test:

```python
@pytest.mark.asyncio
async def test_warranty_speak_then_collect():
    """Warranty intent: speak verbatim warranty text, then collect name (lookahead merge)."""
    executor = StepExecutor(PLAYBOOK_WARRANTY)
    session = make_mock_session()

    result = await executor.set_intent("warranty", session)
    assert 'Say EXACTLY: "All work has a one-year warranty."' in result
    assert "Ask for name." in result
    assert executor.current_step_index == 1  # Lookahead advanced past speak
```

- [ ] **Step 5: Run all step executor tests**

Run: `uv run pytest tests/test_step_executor.py -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_step_executor.py
git commit -m "test: add step executor tests for emergency, cancellation, warranty flows"
```

---

### Task 7: Recompile playbook and run full test suite

**Files:**
- Regenerate: `playbooks/cajun-hvac.compiled.json`

- [ ] **Step 1: Recompile the playbook**

Run: `uv run python compiler/compile.py playbooks/cajun-hvac.json`
Expected: `Compiled: playbooks/cajun-hvac.compiled.json`

- [ ] **Step 2: Verify compiled output has all 10 intents**

Run: `uv run python -c "import json; d=json.load(open('playbooks/cajun-hvac.compiled.json')); print(len(d['intents']), 'intents:', sorted(d['intents'].keys()))"`
Expected: `10 intents: ['_fallback', 'billing', 'cancellation', 'commercial', 'complaint', 'emergency', 'eta_request', 'reschedule', 'routine_service', 'warranty']`

- [ ] **Step 3: Verify system prompt includes emergency qualifiers**

Run: `uv run python -c "import json; d=json.load(open('playbooks/cajun-hvac.compiled.json')); p=d['system_prompt']; print('qualifiers:', 'gas leak' in p); print('emergency_confirmed:', 'emergency_confirmed' in p); print('cancellation_reason:', 'cancellation_reason' in p)"`
Expected: All `True`

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Run linter**

Run: `uv run ruff check src/ compiler/ tests/`
Expected: No errors

- [ ] **Step 6: Commit compiled playbook**

```bash
git add playbooks/cajun-hvac.compiled.json
git commit -m "build: recompile playbook with all 10 intents"
```
