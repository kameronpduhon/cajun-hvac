# LiveKit Voice Agent Development

Use this skill when building, modifying, or debugging the LiveKit voice agent in this project.

## Project Stack

| Layer | Tech |
|-------|------|
| Phone provider | Twilio |
| Media server | LiveKit (SIP trunk) |
| Agent framework | LiveKit Agents SDK ~1.4 (Python) |
| STT | Deepgram Nova-3 (streaming, multilingual) |
| LLM | OpenAI GPT-4.1-mini |
| TTS | Deepgram Aura-2 (voice: "andromeda") |
| VAD | Silero (prewarmed in setup_fnc) |
| Turn detection | MultilingualModel (livekit.plugins.turn_detector.multilingual) |
| Backend API | Laravel (PHP) |

## Agent Entry Point

`src/agent.py` — uses `AgentServer` + `@server.rtc_session` pattern:

```python
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli, inference, room_io

server = AgentServer()

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm

@server.rtc_session(agent_name="cajun-hvac-agent")
async def entrypoint(ctx: JobContext):
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        tts=inference.TTS(model="deepgram/aura-2", voice="andromeda"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    await session.start(agent=MyAgent(), room=ctx.room, room_options=...)
    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(server)
```

## CLI Commands

```bash
uv run python src/agent.py console        # Local terminal testing (mic + speaker)
uv run python src/agent.py dev            # Connect to LiveKit Cloud, listen for rooms
uv run python src/agent.py start          # Production mode
uv run python src/agent.py download-files # Pre-download ML model files (VAD, turn detector)
```

Always run `download-files` before first use after a fresh install.

## Agent Class Pattern

Agents extend `Agent` with `instructions` and optional tool methods:

```python
from livekit.agents import Agent, function_tool, RunContext

class MyAgent(Agent):
    def __init__(self):
        super().__init__(instructions="Your system prompt here")

    async def on_enter(self) -> None:
        # Called when this agent takes control of the session
        await self.session.generate_reply(instructions="Greet the user")

    @function_tool()
    async def my_tool(self, context: RunContext, param: str) -> str:
        """Tool description for the LLM."""
        return "Result string spoken by the agent"
```

## Function Tools

- Decorated with `@function_tool()` on Agent class methods
- First param is always `self`, second is `context: RunContext`
- Remaining params become the tool's arguments for the LLM
- Return value is converted to string and sent to the LLM
- Return `None` for silent completion (no LLM reply)
- Return `(AgentInstance(), "message")` tuple to trigger a handoff
- Raise `ToolError("message")` for errors the LLM should handle
- Use `await context.wait_for_playout()` when generating speech inside a tool

## Tasks (Structured Data Collection)

Tasks are short-lived units that collect typed results and return control:

```python
from livekit.agents import AgentTask, function_tool
from dataclasses import dataclass

@dataclass
class ContactInfo:
    name: str
    phone: str

class CollectContactTask(AgentTask[ContactInfo]):
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions="Collect the caller's name and phone number.",
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(instructions="Ask for their name.")

    @function_tool()
    async def record_contact(self, context: RunContext, name: str, phone: str):
        """Record the caller's contact information."""
        self.complete(ContactInfo(name=name, phone=phone))
```

Run a task from an agent:
```python
result = await CollectContactTask(chat_ctx=self.chat_ctx)
# result is a ContactInfo instance
```

## Agent Handoffs

Transfer control between agents by returning an agent from a tool:

```python
@function_tool()
async def transfer_to_emergency(self, context: RunContext):
    """Transfer to the emergency service agent."""
    return EmergencyAgent(), "Transferring you to our emergency line"
```

## Speech Generation

Two methods to make the agent speak:

```python
# Say exact text
await session.say("Hello, how can I help?", allow_interruptions=False)

# Let LLM generate a response
session.generate_reply(instructions="Greet the user and ask what they need")
session.generate_reply(user_input="What the user said, if injecting text")
```

## Turn Detection & Interruptions

Key `AgentSession` parameters:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `allow_interruptions` | True | User can interrupt agent speech |
| `min_interruption_duration` | 0.5s | Min speech to trigger interruption |
| `min_endpointing_delay` | 0.5s | Seconds before turn is considered complete |
| `max_endpointing_delay` | 3.0s | Max wait for continued speech |
| `preemptive_generation` | False | Start generating before turn ends |

## Noise Cancellation

SIP calls use `BVCTelephony()`, non-SIP use `BVC()`:

```python
room_options=room_io.RoomOptions(
    audio_input=room_io.AudioInputOptions(
        noise_cancellation=lambda params: (
            noise_cancellation.BVCTelephony()
            if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            else noise_cancellation.BVC()
        ),
    ),
)
```

## Testing

Use LiveKit's built-in test helpers with pytest:

```python
from livekit.agents import AgentSession, mock_tools

async def test_agent_greeting():
    session = AgentSession()
    result = await session.run(agent=MyAgent(), user_input="Hello")
    await result.expect.next_event().is_message(role="assistant").judge(llm, intent="greeted the user")
```

Run tests: `uv run pytest tests/ -v`

Key testing patterns:
- `is_message(role="assistant")` — validate messages
- `is_function_call(name="tool_name")` — validate tool calls
- `.judge(llm, intent="...")` — LLM-based qualitative check
- `mock_tools(AgentClass, {"tool_name": mock_fn})` — mock tool implementations
- Multi-turn: call `session.run()` multiple times on same session

## Prompting Best Practices for Voice Agents

Structure prompts with these sections:
1. **Identity** — "You are..." with name, role, responsibilities
2. **Output rules** — Plain text only, no markdown/emoji, spell out numbers, brief responses
3. **Tools** — General tool usage guidance
4. **Goals** — What the agent should accomplish
5. **Guardrails** — Boundaries and off-topic handling

Critical rules from this project's experience:
- Use hard language: "DO NOT", "NEVER" — not "try to" or "please avoid"
- Tools return speech instructions — the LLM speaks what tools return
- Never let the LLM generate its own dialogue for structured data collection
- No placeholder values — only real caller-provided data
- Keep prompts concise — voice users won't wait for monologues

## Environment Variables

```
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
OPENAI_API_KEY=...
DEEPGRAM_API_KEY=...
```

## Documentation Access

- `lk docs search "query"` — search LiveKit docs from terminal
- `lk docs get-page <url>` — read a specific docs page
- `lk docs overview` — browse docs structure
- Context7 MCP also available for doc queries
