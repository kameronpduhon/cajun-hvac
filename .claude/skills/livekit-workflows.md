# LiveKit Workflows, Tasks & Handoffs

Use this skill when designing or implementing multi-agent workflows, call routing, data collection flows, or agent handoffs.

## Architecture Overview

LiveKit provides four constructs for structuring voice agent logic:

| Construct | Purpose | Lifespan |
|-----------|---------|----------|
| **AgentSession** | Main orchestrator of the voice app | Entire call |
| **Agent** | Holds long-lived control, has instructions + tools | Until handoff |
| **AgentTask** | Short-lived, runs to completion, returns typed result | Until complete |
| **TaskGroup** | Ordered sequence of tasks with backtracking (beta) | Until all complete |

## When to Use What

- **Separate agents** — when you need distinct reasoning behavior or different tool access (e.g., greeter vs emergency handler)
- **Tasks** — for operations that must complete before continuing (consent, data capture, verification, booking confirmation)
- **Tools** — for actions the LLM decides to invoke (lookups, API calls, field recording)
- **TaskGroup** — for ordered multi-step flows where the user might need to go back and correct earlier steps

## Agent Handoffs

An agent can transfer control to another agent by returning it from a tool:

```python
from livekit.agents import Agent, function_tool, RunContext

class GreeterAgent(Agent):
    def __init__(self):
        super().__init__(instructions="Greet the caller and determine their intent.")

    @function_tool()
    async def route_to_emergency(self, context: RunContext):
        """Use when the caller has an emergency (no heat, gas leak, flooding)."""
        return EmergencyAgent(), "I'll connect you with our emergency team right away."

    @function_tool()
    async def route_to_scheduling(self, context: RunContext):
        """Use when the caller wants to schedule routine service."""
        return SchedulingAgent(), "Let me help you schedule that service."
```

Key points:
- Return `(AgentInstance(), "transition message")` from a tool
- The new agent gets control of the session
- Chat context carries over by default
- Each agent has its own instructions and tools — keeps context focused

## Tasks for Data Collection

Tasks are ideal for collecting structured information:

```python
from livekit.agents import AgentTask, function_tool, RunContext
from dataclasses import dataclass

@dataclass
class CallerInfo:
    name: str
    phone: str
    address: str

class CollectCallerInfoTask(AgentTask[CallerInfo]):
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions="""Collect the caller's name, phone number, and address.
            Ask for each piece of information one at a time.
            Only record real values provided by the caller — NEVER use placeholders.""",
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions="Ask for the caller's name."
        )

    @function_tool()
    async def record_caller_info(self, context: RunContext, name: str, phone: str, address: str):
        """Record the caller's contact information once all fields are collected."""
        self.complete(CallerInfo(name=name, phone=phone, address=address))
```

Run from an agent:
```python
class ServiceAgent(Agent):
    async def on_enter(self):
        info = await CollectCallerInfoTask(chat_ctx=self.chat_ctx)
        # info.name, info.phone, info.address are now available
```

## Unordered Collection (Flexible Field Gathering)

When fields can be collected in any order:

```python
class FlexibleCollectionTask(AgentTask[CallerInfo]):
    def __init__(self):
        super().__init__(instructions="Collect name, phone, and address in any order.")
        self._fields = {}

    @function_tool()
    async def record_name(self, context: RunContext, name: str):
        """Record the caller's name."""
        self._fields["name"] = name
        self._check_complete()

    @function_tool()
    async def record_phone(self, context: RunContext, phone: str):
        """Record the caller's phone number."""
        self._fields["phone"] = phone
        self._check_complete()

    @function_tool()
    async def record_address(self, context: RunContext, address: str):
        """Record the caller's address."""
        self._fields["address"] = address
        self._check_complete()

    def _check_complete(self):
        if {"name", "phone", "address"} <= self._fields.keys():
            self.complete(CallerInfo(**self._fields))
        else:
            remaining = {"name", "phone", "address"} - self._fields.keys()
            self.session.generate_reply(
                instructions=f"Ask for the caller's {', '.join(remaining)}."
            )
```

## TaskGroup (Beta — Ordered Steps)

For sequential multi-step flows with backtracking support:

```python
from livekit.agents.beta.workflows import TaskGroup

task_group = TaskGroup(chat_ctx=self.chat_ctx)

task_group.add(lambda: CollectContactTask(), id="contact", description="Collect name and phone")
task_group.add(lambda: CollectAddressTask(), id="address", description="Collect service address")
task_group.add(lambda: ConfirmBookingTask(), id="confirm", description="Confirm the appointment")

results = await task_group
# results.task_results has each task's typed result
```

TaskGroup options:
- `summarize_chat_ctx=True` — summarize interactions between tasks
- `return_exceptions=False` — stop on first error vs continue
- `on_task_completed=callback` — hook after each task completes

## Design Principles for This Project

From lessons learned in the prior voice agent build:

1. **Tools return speech instructions** — the LLM speaks what tools return. Never use `generate_reply` AND return speech from the same tool (causes double-speak).

2. **Keep agent scopes narrow** — each agent/task should have focused instructions and only the tools it needs. This reduces latency and improves reliability.

3. **Use hard language in prompts** — "DO NOT", "NEVER", not "try to" or "please avoid".

4. **No placeholder values** — system prompt must forbid recording placeholder data like "[Name]" or "TBD".

5. **Intent routing happens once** — after the greeting, intent is set once and never changed mid-call.

6. **Combine speak + collect** — if a speak step is followed by a collect step, combine them to avoid awkward silence.

## Workflow Pattern for This Project

Recommended call flow using LiveKit's constructs:

```
Call connects
  → GreeterAgent (identify intent)
    → handoff to IntentAgent (e.g., RoutineServiceAgent, EmergencyAgent)
      → CollectInfoTask (name, phone, address)
      → Intent-specific tasks (booking, dispatch, message)
      → Post-call summary to API
```
