# LiveKit Agent Testing

Use this skill when writing or running tests for the voice agent.

## Setup

Dependencies are already in `pyproject.toml`:
```
pytest
pytest-asyncio
```

Config in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

Run tests: `uv run pytest tests/ -v`
Verbose with logs: `LIVEKIT_EVALS_VERBOSE=1 uv run pytest -s`

## Test Structure

Every test follows this pattern:
1. Create an LLM instance for judgment
2. Create an `AgentSession`
3. Start the agent with `session.run()`
4. Assert expected outcomes
5. Verify no unexpected events

```python
import pytest
from livekit.agents import AgentSession, inference

@pytest.fixture
def llm():
    return inference.LLM(model="openai/gpt-4.1-mini")

async def test_greeting(llm):
    session = AgentSession()
    result = await session.run(agent=MyAgent(), user_input="Hello")

    # Check the agent responded appropriately
    await result.expect.next_event().is_message(role="assistant").judge(
        llm, intent="greeted the user and asked how to help"
    )
```

## Assertion Methods

### Message Assertions
```python
# Validate specific message
result.expect.next_event().is_message(role="assistant")

# LLM-based qualitative check
await result.expect.next_event().is_message(role="assistant").judge(
    llm, intent="described the service fee"
)

# Order-agnostic search
result.expect.contains_message(...)
```

### Tool Call Assertions
```python
# Validate tool was called
result.expect.next_event().is_function_call(name="set_intent")

# Validate tool output
result.expect.next_event().is_function_call_output()

# Then check the agent's response after the tool
await result.expect.next_event().is_message(role="assistant").judge(llm, ...)
```

### Navigation
```python
result.expect.next_event()          # Move cursor forward
result.expect.skip_next()           # Skip without validating
result.expect.skip_next_event_if()  # Conditional skip
result.expect[0]                    # Index access
result.expect[0:2]                  # Range access
```

## Multi-Turn Testing

Call `session.run()` multiple times — chat history builds automatically:

```python
async def test_full_call_flow(llm):
    session = AgentSession()

    # Turn 1: greeting
    r1 = await session.run(agent=MyAgent(), user_input="Hi, I need to schedule a service")
    await r1.expect.next_event().is_message(role="assistant").judge(
        llm, intent="identified caller needs service"
    )

    # Turn 2: provide info
    r2 = await session.run(user_input="My name is John Smith")
    r2.expect.next_event().is_function_call(name="update_field")
```

## Tool Mocking

Test edge cases without external dependencies:

```python
from livekit.agents import mock_tools

async def test_out_of_area(llm):
    async def mock_check_area(location: str):
        return "Out of service area"

    with mock_tools(MyAgent, {"check_service_area": mock_check_area}):
        session = AgentSession()
        result = await session.run(agent=MyAgent(), user_input="I'm at 123 Main St, ZIP 99999")
        # Assert agent handles out-of-area correctly

```

## Chat Context Preloading

Set up conversation history before a test:

```python
from livekit.agents.llm import ChatContext

async def test_mid_conversation():
    chat_ctx = ChatContext()
    chat_ctx.add_message(role="user", content="I need emergency service")
    chat_ctx.add_message(role="assistant", content="I understand this is an emergency. Let me get your information.")

    session = AgentSession()
    agent = MyAgent()
    await agent.update_chat_ctx(chat_ctx)
    result = await session.run(agent=agent, user_input="My name is Jane Doe")
```

## What to Test

From AGENTS.md — when modifying core agent behavior (instructions, tool descriptions, tasks/workflows/handoffs), always use TDD:

1. **Expected behavior** — correct intent, tone, responses
2. **Tool usage** — right tools called with right arguments
3. **Error handling** — invalid inputs, tool failures
4. **Grounding** — no hallucination, stays factual
5. **Misuse resistance** — handles manipulation attempts

## CI Notes

- Tests do NOT require LiveKit API keys
- Tests DO require LLM provider credentials (OPENAI_API_KEY, DEEPGRAM_API_KEY)
- Use environment variables, never commit keys
