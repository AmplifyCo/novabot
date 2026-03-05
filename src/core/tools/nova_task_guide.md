# Nova Task Tool — Usage Guidelines

## When to Queue a Task
- ONLY when the task genuinely requires 3+ steps AND multiple tools
- ONLY when a tool is blocked by PolicyGate (IRREVERSIBLE action in direct chat)
- Examples: "Research X, then draft a LinkedIn post, then post it" → multi-step, queue it

## When NOT to Queue
- Simple questions or single-tool lookups — just answer directly
- Checking status, reading data, or searching — do it inline
- If you can answer in one tool call, don't queue it
- "What's the weather?" → just search, don't queue
- "Check my calendar" → just check, don't queue

## The Golden Rule
- If in doubt, answer directly — don't queue
- Queuing adds latency and complexity for the user
- The user expects immediate responses for simple requests

## Task Description
- Write clear, specific task descriptions
- Include all context the background runner needs (names, dates, content)
- Don't assume the background task has conversation context — spell everything out
