# Local Model Setup Guide

## Overview

The autonomous agent now supports **multi-tier model routing** with optional local model integration for CPU-based inference. This allows you to:

- **Reduce costs** by using local models for simple tasks
- **Eliminate rate limits** for basic operations
- **Maintain quality** by intelligently routing to better models when needed

## Model Tiers

### Architecture Philosophy

**PRIORITY: Clarity and quality over cost savings**

The model router intelligently selects the appropriate model based on task complexity:

| Tier | Model | Use Case | Priority |
|------|-------|----------|----------|
| **Architect** | Opus 4.6 | Complex planning, feature building, orchestration | Always use for building |
| **Worker** | Sonnet 4.5 | Implementation, general conversation, moderate tasks | **DEFAULT** for quality |
| **Assistant** | Haiku 4.5 | Simple queries, intent parsing | Only when safe |
| **Basic** | Local (CPU) | Ultra-simple predefined responses (optional) | Rare, trivial only |

### Model Selection Logic

```
Task → Router Assessment → Model Selection

1. COMPLEX (building, unclear) → Opus Architect
2. MODERATE (conversation)     → Sonnet Worker (DEFAULT)
3. SIMPLE (status, logs)       → Haiku Assistant
4. TRIVIAL (predefined only)   → Local (if enabled)
```

**Key Principle**: When in doubt, escalate to a better model. Quality matters.

## Configuration

### 1. Environment Variables

Update your `.env` file:

```bash
# Multi-Tier Models
DEFAULT_MODEL=claude-opus-4-6          # Architect
SUBAGENT_MODEL=claude-sonnet-4-5       # Workers
CHAT_MODEL=claude-sonnet-4-5           # Chat (Sonnet for clarity!)
INTENT_MODEL=claude-haiku-4-5          # Intent parsing

# Optional: Local Model
LOCAL_MODEL_ENABLED=false
LOCAL_MODEL_NAME=nvidia/personaplex-7b-v1
LOCAL_MODEL_ENDPOINT=http://localhost:8000
LOCAL_MODEL_FOR=trivial                # Very conservative
```

### 2. YAML Configuration

The `config/agent.yaml` file includes:

```yaml
agent:
  models:
    default: "claude-opus-4-6"      # Architect
    subagent: "claude-sonnet-4-5"   # Workers
    chat: "claude-sonnet-4-5"       # Chat (quality!)
    intent: "claude-haiku-4-5"      # Intent

local_model:
  enabled: false
  name: "nvidia/personaplex-7b-v1"
  endpoint: null
  use_for: "trivial"
  max_tokens: 512
  temperature: 0.7
  device: "cpu"
```

## Local Model Options

### Option 1: Direct CPU Inference (Simple)

Use transformers library directly:

```bash
# Install dependencies
pip install transformers torch

# Enable in .env
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=nvidia/personaplex-7b-v1
LOCAL_MODEL_ENDPOINT=  # Leave empty for direct inference
```

**Pros**: Simple setup, no server needed
**Cons**: Slower, loads model on each request

### Option 2: vLLM Server (Recommended)

Run a local inference server:

```bash
# Install vLLM
pip install vllm

# Start server
python -m vllm.entrypoints.openai.api_server \
  --model nvidia/personaplex-7b-v1 \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float32

# Update .env
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=nvidia/personaplex-7b-v1
LOCAL_MODEL_ENDPOINT=http://localhost:8000
```

**Pros**: Fast, efficient, OpenAI-compatible API
**Cons**: Requires running separate server

### Option 3: Ollama (Easiest)

Use Ollama for easy model management:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model
ollama pull mistral:7b

# Ollama runs at http://localhost:11434 by default

# Update .env
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=mistral:7b
LOCAL_MODEL_ENDPOINT=http://localhost:11434
```

**Pros**: Easiest setup, great model management
**Cons**: Limited to Ollama-supported models

## Recommended Models

### For Chat/Intent (Small, Fast)

- **nvidia/personaplex-7b-v1** (7B) - Good for conversation
- **mistral-7b-instruct** (7B) - General purpose
- **phi-3-mini** (3.8B) - Very lightweight

### For Better Quality (Larger)

- **mistral-7b** (7B) - Balanced
- **llama-3-8b-instruct** (8B) - Higher quality
- **gemma-2-9b** (9B) - Google's model

**Note**: Larger models (13B+) may be too slow on CPU. Stick to 7B or smaller.

## Usage Examples

### Telegram Interaction Examples

```
User: "What's your status?"
→ Router: SIMPLE task
→ Model: Haiku 4.5
→ Response: Fast, cheap, good enough

User: "How can I optimize database queries?"
→ Router: MODERATE task (conversation)
→ Model: Sonnet 4.5 (DEFAULT)
→ Response: Quality, thoughtful answer

User: "Build an authentication system"
→ Router: COMPLEX task
→ Model: Opus 4.6 (Architect)
→ Action: Spawns Sonnet workers for implementation
```

## Monitoring

Check logs to see model selection:

```bash
tail -f data/logs/agent.log | grep "Selected model"
```

Example output:
```
Selected haiku model for simple task
Selected sonnet model for moderate task (conversation)
Selected opus model for complex task (building)
```

## Cost Optimization

### Conservative (Current Setup)

```env
CHAT_MODEL=claude-sonnet-4-5    # Prioritize quality
LOCAL_MODEL_ENABLED=false        # Disabled
```

**Cost**: Medium | **Quality**: High ✅

### Balanced

```env
CHAT_MODEL=claude-haiku-4-5     # Haiku for simple chat
LOCAL_MODEL_ENABLED=false        # Still disabled
```

**Cost**: Low-Medium | **Quality**: Good

### Aggressive (Use Local)

```env
CHAT_MODEL=claude-haiku-4-5
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_FOR=trivial,simple
```

**Cost**: Very Low | **Quality**: Variable ⚠️

## Troubleshooting

### Model Not Loading

```bash
# Check transformers installation
pip install --upgrade transformers torch

# Test model load
python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('nvidia/personaplex-7b-v1')"
```

### vLLM Server Issues

```bash
# Check server status
curl http://localhost:8000/health

# View server logs
python -m vllm.entrypoints.openai.api_server --model <model_name> --log-level debug
```

### Poor Quality Responses

If local model gives poor responses:

1. **Disable local model**: `LOCAL_MODEL_ENABLED=false`
2. **Upgrade chat model**: `CHAT_MODEL=claude-sonnet-4-5`
3. **Check router logs**: Ensure tasks are classified correctly

## Best Practices

1. **Start conservative**: Use Claude models only, disable local
2. **Monitor quality**: Check Telegram responses for clarity
3. **Gradually optimize**: Enable local only for trivial tasks
4. **Prioritize user experience**: Never sacrifice quality for cost
5. **Use router intelligently**: Trust the complexity assessment

## Architecture Notes

### How the Router Works

```python
# Router decision flow
assess_complexity(task) → TaskComplexity
  → TRIVIAL: Predefined responses only
  → SIMPLE: Clear, straightforward
  → MODERATE: Conversation (DEFAULT to Sonnet)
  → COMPLEX: Planning, building

map_to_tier(complexity) → ModelTier
  → Local (if enabled and trivial)
  → Haiku (simple)
  → Sonnet (moderate) ← DEFAULT
  → Opus (complex)
```

### Safety Mechanisms

- **Low confidence → Escalate**: If intent parsing is uncertain, use Opus
- **Unknown intent → Escalate**: Better to over-deliver than confuse user
- **Build tasks → Always Opus**: Never compromise on architectural decisions
- **Chat → Default Sonnet**: Conversation requires understanding context

## Summary

✅ **Recommended Setup** (Current):
- Architect: Opus 4.6
- Workers: Sonnet 4.5
- Chat: **Sonnet 4.5** (prioritize clarity)
- Intent: Haiku 4.5
- Local: Disabled

This balances cost and quality, with **clarity as the priority**.

## Next Steps

1. Test current setup via Telegram
2. Monitor model selection in logs
3. Adjust `CHAT_MODEL` if needed
4. Optionally experiment with local models for ultra-simple tasks

For questions or issues, check the logs and model selection decisions.
