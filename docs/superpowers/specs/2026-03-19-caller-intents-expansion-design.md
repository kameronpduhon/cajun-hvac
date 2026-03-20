# Caller Intents Expansion — Design Spec

## Goal

Add 8 new caller intents to the voice agent, bringing the total from 2 (routine_service + _fallback) to 10. Most follow a collect-info-then-take-message pattern. Emergency has unique dispatch logic.

## New Intents

### emergency — Urgent issue, dispatch on-call tech

No fee disclosure (bad UX for someone in crisis). No service area check (you don't turn away a gas leak over a zip code). No explicit issue_description collection (the caller already described the emergency to trigger this intent — transcript captures it).

**Steps:**
```
collect: name           — "Ask for the caller's full name."
collect: phone          — "Ask for a callback phone number."
collect: address        — "Ask for the full service address including zip code."
collect: emergency_confirmed — "Summarize back to the caller — their name, phone number, and service address — and confirm that a technician is being sent. Do NOT repeat the emergency description back."
action: check_emergency_confirmed
action: dispatch_oncall_tech
```

**check_emergency_confirmed:** If caller says no, return guided prompt: "The caller wants to correct something. Ask what they'd like to change — their name, phone number, or address." The existing field overwrite logic handles corrections — LLM calls update_field on the field to fix, it overwrites the value, and the current step (emergency_confirmed) gets re-asked.

**dispatch_oncall_tech:** Resolves `closing_dispatched` template, sets outcome to `"dispatched"`, returns `Say EXACTLY: "..." [call_ended]`.

**Emergency qualifiers** added to playbook root and surfaced in system prompt so the LLM knows when to route here vs. routine_service:
`["no heat", "no cooling", "no AC", "gas leak", "gas smell", "flooding", "water leak", "pipe burst", "electrical fire", "sparking", "no hot water"]`

### cancellation — Cancel an existing appointment

```
collect: name                — "Ask for the caller's full name."
collect: phone               — "Ask for a callback phone number."
collect: cancellation_reason — "Ask the reason for the cancellation."
action: take_message
```

### reschedule — Change an existing appointment

```
collect: name           — "Ask for the caller's full name."
collect: phone          — "Ask for a callback phone number."
collect: preferred_time — "Ask when they'd like to reschedule to."
action: take_message
```

### eta_request — "Where's my technician?"

```
collect: name  — "Ask for the caller's full name."
collect: phone — "Ask for a callback phone number."
action: take_message
```

### warranty — Warranty claim or question

```
speak(verbatim): "All of our work comes with a one-year parts and labor warranty. Let me get your information so we can look into this for you."
collect: name              — "Ask for the caller's full name."
collect: phone             — "Ask for a callback phone number."
collect: issue_description — "Ask what warranty issue they're experiencing."
action: take_message
```

Warranty intro script is a placeholder. In production, each client sets their own warranty language in their playbook.

### billing — Billing question or dispute

```
collect: name              — "Ask for the caller's full name."
collect: phone             — "Ask for a callback phone number."
collect: issue_description — "Ask about their billing question or concern."
action: take_message
```

### complaint — Customer complaint

```
collect: name              — "Ask for the caller's full name."
collect: phone             — "Ask for a callback phone number."
collect: issue_description — "Ask them to describe their complaint."
action: take_message
```

Uses `issue_description` (not `complaint_description`). The intent label already identifies it as a complaint. One field name, simpler system prompt.

### commercial — Commercial/business service request

```
collect: name              — "Ask for the caller's full name."
collect: phone             — "Ask for a callback phone number."
collect: issue_description — "Ask what commercial service they need."
action: take_message
```

## Changes by File

### `playbooks/cajun-hvac.json`

- Add `emergency_qualifiers` array to root
- Add `closing_dispatched` to `scripts`: `"I've contacted our on-call technician. They'll be reaching out to you shortly at {phone}. Thank you for calling Cajun HVAC."`
  - Template must only reference fields in `executor.collected` (`{phone}`, `{name}`, `{address}`). Company name is hardcoded in the script text, not templated, to avoid a `resolve_template` miss.
- Warranty intro text goes inline in the step definition (not in `scripts`) — no `warranty_intro` script entry needed
- Add all 8 intent definitions to `intents`

### `src/actions.py`

- Add `dispatch_oncall_tech` function — resolves `closing_dispatched` template, sets outcome `"dispatched"`, returns Say EXACTLY + [call_ended]
- Add `check_emergency_confirmed` function — if "no", return guided prompt asking what to change; if yes, advance
- Register both in `ACTION_REGISTRY`

### `compiler/compile.py`

- Update `build_system_prompt` to include emergency qualifiers in system prompt (use `playbook.get("emergency_qualifiers", [])` — optional, not all clients have emergency dispatch)
- Update field name list in system prompt with new fields: `cancellation_reason`, `preferred_time`, `emergency_confirmed`
- Add system prompt rule: emergency situations route to `emergency` intent, not `routine_service`
- Add system prompt hint: "If the caller declines to give a reason for cancellation, record their response as-is."

### `src/agent.py`

- Remove hardcoded field name list from `update_field` tool docstring (line 66-67). The system prompt (generated by compiler) is the authoritative source for field names. The docstring should say to use the field name from the current step prompt, without enumerating them.

### No changes needed

- `src/step_executor.py` — handles any number of intents generically
- `src/utils.py` — resolve_template and extract_zip already work for new intents

### Tests

- `tests/test_actions.py` — add tests for `dispatch_oncall_tech` and `check_emergency_confirmed`
- `tests/test_step_executor.py` — add tests for new intent flows (at minimum: emergency full flow, one message-taking intent, intent routing to _fallback for unknown)
- `tests/test_compiler.py` — add test that playbook with all 10 intents compiles successfully

## Design Decisions

1. **No fee for emergency** — Bad UX to fee-gate someone in crisis. Company handles billing after the fact.
2. **No service area check for emergency** — Business decision to serve emergencies regardless of zip code.
3. **No explicit issue_description for emergency** — Caller already described the emergency to trigger the intent. Transcript captures it.
4. **check_emergency_confirmed uses overwrite logic, not loop-back** — Asking "what do you want to change?" then letting the LLM call update_field on the specific field is less frustrating than re-asking name/phone/address from the top.
5. **issue_description for complaints (not complaint_description)** — One field name serves the same purpose across intents. Intent label provides context.
6. **cancellation_reason is required** — "Can I ask the reason?" is normal. If they decline, LLM records that response and moves on. No optional field support needed.
7. **Emergency qualifiers in playbook** — Per-client config, not hardcoded. Different companies may have different emergency triggers.
