# memory.md — SEA-LION Tool Calling Best Practices

Sources:
- https://docs.sea-lion.ai/guides/tool_calling
- https://docs.sea-lion.ai/guides/tool_calling/tool_examples

---

## 1. Model Selection — Know Which Model You Are Using

Each SEA-LION model handles tool calling differently. Using the wrong approach causes silent
failures or redundant tool calls.

| Model | Tool Calling Style | Use `tools` param? | Returns `tool_calls`? |
|---|---|---|---|
| `Llama-SEA-LION-v3-70B-IT` | Native OpenAI-style | Yes + `tool_choice: "auto"` | Yes |
| `Gemma-SEA-LION-v4-27B-IT` | Text-based (parse from content) | Only if enforcing specific tool | No (unless forced) |
| `Llama-SEA-LION-v3.5-70B-R` | Reasoning model — text parse only | No | No |

**Rule: Detect model type before building the request:**

```python
def is_reasoning_model(model_name: str) -> bool:
    return model_name.endswith('-R')

def is_gemma_model(model_name: str) -> bool:
    return "Gemma" in model_name
```

---

## 2. Request Configuration Per Model

### Llama-SEA-LION-v3-70B-IT (recommended for production tool calling)
```python
request_data = {
    "model": "aisingapore/Llama-SEA-LION-v3-70B-IT",
    "messages": messages,
    "temperature": 0,
    "tools": build_tool_schema(),
    "tool_choice": "auto"
}
```

### Gemma-SEA-LION-v4-27B-IT (text-based, no tools param by default)
```python
# Default: no tools param — parse tool call from message content
request_data = {
    "model": "aisingapore/Gemma-SEA-LION-v4-27B-IT",
    "messages": messages,
    "temperature": 0,
    # No tools or tool_choice
}

# Only add tools if enforcing a specific tool call
request_data["tools"] = build_tool_schema()
request_data["tool_choice"] = {"type": "function", "function": {"name": "my_tool"}}
```

### Llama-SEA-LION-v3.5-70B-R (reasoning — never add tools)
```python
request_data = {
    "model": "aisingapore/Llama-SEA-LION-v3.5-70B-R",
    "messages": messages,
    "temperature": 0,
    # Never add tools or tool_choice to reasoning models
}
```

---

## 3. Tool Schema Definition

Always use OpenAI-compatible schema format with `additionalProperties: False`:

```python
def build_tool_schema():
    return [
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "Clear description of what the tool does.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "param": {
                            "type": "string",
                            "description": "What this parameter is for"
                        }
                    },
                    "required": ["param"],
                    "additionalProperties": False,   # always include this
                },
            },
        }
    ]
```

---

## 4. Response Parsing — Extract Tool Calls Correctly

### For Llama (native tool_calls):
```python
def extract_tool_calls(data: dict):
    choice = data.get("choices", [{}])[0]
    return choice.get("message", {}).get("tool_calls")
```

### For Gemma / Reasoning models (parse from text):
```python
import re, json

def parse_tool_calls_from_text(content: str):
    if not content or not isinstance(content, str):
        return None

    # Extract from ```tool_code blocks
    tool_code_pattern = r'```tool_code\s*([\s\S]*?)\s*```'
    matches = re.findall(tool_code_pattern, content)
    search_content = '\n'.join(matches) if matches else content

    patterns = [
        (r'my_tool\s*\(\s*param\s*=\s*[\'"]([^\'"]+)[\'"]\s*\)', "my_tool", "param"),
        # Add one tuple per tool
    ]

    results = []
    for pattern, func_name, param_name in patterns:
        for i, match in enumerate(re.findall(pattern, search_content)):
            results.append({
                "id": f"text_parsed_{func_name}_{i}",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps({param_name: match})
                }
            })
    return results if results else None
```

### For reasoning models — strip `<think>` block first:
```python
# Prevent redundant tool calls from reasoning content
if is_reasoning_model(model_name):
    content = content.split("</think>")[1].strip()
tool_calls = parse_tool_calls_from_text(content)
```

---

## 5. System Prompt for Text-Based Tool Calling (Gemma / Reasoning)

When the model does not natively parse `tools`, the system prompt must explicitly define the
format. Always use `tool_code` blocks with double-quoted parameters:

```python
def build_system_message():
    return {
        "role": "system",
        "content": (
            "When you need to use a tool, wrap the call in a tool_code block:\n\n"
            "```tool_code\n"
            "tool_name(param=\"value\")\n"
            "```\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "- Always wrap tool calls in ```tool_code blocks\n"
            "- Always use double quotes around parameter values\n"
            "- Do NOT use JSON format\n"
            "- Do NOT answer from knowledge alone when a tool is available"
        )
    }
```

---

## 6. Tool Execution Framework

Always wrap individual tool calls in try/except. Never let one tool failure crash the loop.
Return `role: "user"` for tool results (Gemma chat template requires alternating user/assistant):

```python
async def execute_tool_calls(tool_calls: list, session) -> list:
    results = []
    for call in tool_calls:
        name = call.get("function", {}).get("name")
        args = call.get("function", {}).get("arguments", {})
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            args = {}
        try:
            if name == "my_tool":
                result = await my_tool(args.get("param"), session)
            else:
                result = {"error": f"Unknown tool: {name}"}
        except Exception as e:
            result = {"name": name, "error": str(e)}

        results.append({
            "tool_call_id": call.get("id"),
            "role": "user",        # not "tool" — Gemma requires user/assistant alternation
            "name": name,
            "content": json.dumps(result)
        })
    return results
```

---

## 7. Conversation History Management

Always append every message (user, assistant, tool result) to maintain context.
Never skip tool result messages — the model needs them to generate a final response.

```python
messages.append({"role": "user", "content": user_input})
messages.append(assistant_message)          # from first API call
messages.extend(tool_results)               # from execute_tool_calls
messages.append(final_message)             # from second API call
```

---

## 8. Tool Function Implementation Rules

Every tool function must follow this pattern:

```python
async def my_tool(param: str, session) -> dict:
    # 1. Validate inputs first — raise ValueError for bad inputs
    if not param or not isinstance(param, str):
        raise ValueError("Invalid param")

    try:
        # 2. Make external call with explicit timeout
        async with session.get(url, params=params, timeout=20) as response:
            data = await response.json()

        # 3. Validate response has expected data
        if not data.get("expected_key"):
            raise ValueError("Unexpected response format")

        # 4. Return structured dict — always include a source field
        return {
            "input": param,
            "result": data,
            "source": "api-name.com"
        }
    except Exception as err:
        raise ValueError(f"Tool failed: {str(err)}")
```

---

## 9. Error Handling Checklist

- Always validate tool parameters before execution
- Wrap every external API call in try/except
- Set explicit timeouts on all HTTP requests (recommended: 20–30s)
- Validate `tool_calls` before processing: `if not tool_calls or not isinstance(tool_calls, list)`
- Return structured error dicts — never raise uncaught exceptions from tool execution
- Log tool failures without surfacing raw errors to users

---

## 10. Security Rules

- Validate all tool parameters before execution — never trust raw model output
- Sanitize user inputs before passing them into tool arguments
- Implement rate limiting for external API calls
- Consider sandboxing tool execution in production environments

---

## 11. Performance Rules

- Cache tool results where appropriate (e.g. weather data, search results for short TTL)
- Use `asyncio.gather()` for parallel tool execution when multiple tools are called
- Use connection pooling (`httpx.AsyncClient` or `aiohttp.ClientSession`) — never open a new connection per tool call
- Monitor token usage — text-based tool calling (Gemma/Reasoning) consumes more tokens than native function calling

---

## 12. Adding a New Tool — Checklist

1. Define an `async` function with input validation and error handling
2. Add its schema to `build_tool_schema()`
3. Add a branch for it in `execute_tool_calls()`
4. Add a regex pattern for it in `parse_tool_calls_from_text()` (for Gemma/Reasoning)
5. Update the system prompt to mention the new tool name and its `tool_code` usage format
6. Test on both Llama (native) and Gemma (text-parse) to confirm both paths work

---

## 13. Quick Reference — This Project's Tool Mapping

| Tool Function | Model Used | Calling Style |
|---|---|---|
| `run_guard_detection()` | `SEA-LION-GUARD` | Direct API call — not ADK tool |
| `run_insights()` | `Llama-SEA-LION-v3-70B-IT` | Native OpenAI-style tool call |
| `translate_to_english()` | `Gemma-SEA-LION-v3-9B-IT` | Text-based via ADK runner |
| `translate_from_english()` | `Gemma-SEA-LION-v3-9B-IT` | Text-based via ADK runner |
| `searxng_search()` | `Llama-SEA-LION-v3-70B-IT` | Native OpenAI-style tool call |
| `log_to_clickhouse()` | N/A | Sync function, not an LLM tool |