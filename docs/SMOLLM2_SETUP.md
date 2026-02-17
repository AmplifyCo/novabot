# SmolLM2 Setup Guide - CPU-Optimized Local Models

## Why SmolLM2?

**SmolLM2** is specifically designed for edge and CPU deployment, making it **perfect** for your autonomous agent's local inference needs.

### Key Advantages

✅ **CPU-Optimized** - Designed from the ground up for edge devices
✅ **Fast Inference** - 10-50x faster than 7B models on CPU
✅ **Low Memory** - Runs on limited RAM (1-4GB)
✅ **Good Quality** - Impressive performance for the size
✅ **Instruction-Tuned** - Ready for chat and task completion
✅ **No Rate Limits** - Free, unlimited local inference

### Performance Comparison

```
CPU Inference Speed (tokens/second):

SmolLM2-360M:   50-100 tok/s  ⚡⚡⚡ Ultra-fast
SmolLM2-1.7B:   20-40 tok/s   ⚡⚡  Very fast (RECOMMENDED)
Phi-3-mini:     10-20 tok/s   ⚡    Fast
Mistral-7B:     2-5 tok/s     🐌    Slow
```

## Recommended Configuration

### SmolLM2-1.7B-Instruct (Recommended)

Best balance of speed and quality:

```bash
# .env
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=HuggingFaceTB/SmolLM2-1.7B-Instruct
LOCAL_MODEL_ENDPOINT=  # Leave empty for direct inference
LOCAL_MODEL_FOR=trivial,simple
```

**When to use:**
- Simple status checks
- Intent classification
- Basic Q&A
- Predefined responses
- Quick confirmations

### SmolLM2-360M-Instruct (Ultra-Fast)

For maximum speed with simple tasks:

```bash
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=HuggingFaceTB/SmolLM2-360M-Instruct
LOCAL_MODEL_FOR=trivial  # Only ultra-simple tasks
```

**When to use:**
- Status checks only
- Intent parsing only
- When speed is critical

## Quick Start

### Option 1: Direct Inference (Simplest)

```bash
# Install dependencies
pip install transformers torch

# Update your .env
cat >> .env << 'EOF'
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=HuggingFaceTB/SmolLM2-1.7B-Instruct
LOCAL_MODEL_ENDPOINT=
LOCAL_MODEL_FOR=trivial,simple
EOF

# Restart agent
sudo systemctl restart claude-agent
```

**First run:** Model will download (~3.4GB for 1.7B variant)

### Option 2: vLLM Server (Faster)

For better performance with concurrent requests:

```bash
# Install vLLM
pip install vllm

# Start server
python -m vllm.entrypoints.openai.api_server \
  --model HuggingFaceTB/SmolLM2-1.7B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype float32

# Update .env
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=HuggingFaceTB/SmolLM2-1.7B-Instruct
LOCAL_MODEL_ENDPOINT=http://localhost:8000
LOCAL_MODEL_FOR=trivial,simple
```

### Option 3: Ollama (Easiest Management)

**Note:** Check if SmolLM2 is available in Ollama first.

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Check available models
ollama list | grep smol

# If available, pull and use
ollama pull smollm2:1.7b
```

## Usage Examples

### With Your Telegram Agent

Once enabled, the router will automatically use SmolLM2 for simple tasks:

```
User: "What's your status?"
→ Router: TRIVIAL task
→ Model: SmolLM2-1.7B (local, instant, free)
→ Response: "✅ Agent running. Uptime: 2h 15m..."

User: "How can I improve my code architecture?"
→ Router: MODERATE task (needs understanding)
→ Model: Sonnet 4.5 (quality conversation)
→ Response: [Detailed architectural advice]

User: "Build a user authentication system"
→ Router: COMPLEX task
→ Model: Opus 4.6 (architect) → Spawns Sonnet workers
→ Result: [Multi-agent feature building]
```

## Model Comparison

### SmolLM2 Variants

| Variant | Parameters | RAM | Speed | Quality | Best For |
|---------|-----------|-----|-------|---------|----------|
| **SmolLM2-135M** | 135M | ~1GB | ⚡⚡⚡⚡ | Basic | Ultra-simple only |
| **SmolLM2-360M** | 360M | ~2GB | ⚡⚡⚡ | Good | Status, intent |
| **SmolLM2-1.7B** | 1.7B | ~4GB | ⚡⚡ | Very Good | **Recommended** |

### vs Other Models

| Model | Size | CPU Speed | Quality | RAM | Verdict |
|-------|------|-----------|---------|-----|---------|
| **SmolLM2-1.7B** | 1.7B | ⚡⚡ Fast | Very Good | ~4GB | ✅ Best for CPU |
| Phi-3-mini | 3.8B | ⚡ Medium | Good | ~8GB | ✅ Good alternative |
| Llama-3.2-3B | 3B | ⚡ Medium | Good | ~6GB | ✅ Good alternative |
| Mistral-7B | 7B | 🐌 Slow | Excellent | ~14GB | ❌ Too slow for CPU |
| Llama-3.1-8B | 8B | 🐌 Very slow | Excellent | ~16GB | ❌ Too slow for CPU |

## Configuration Guide

### Model Routing with SmolLM2

The intelligent router uses SmolLM2 only for appropriate tasks:

```python
# Router decision tree with SmolLM2

if task_complexity == "TRIVIAL":
    → SmolLM2-1.7B (local, free, fast) ✅

elif task_complexity == "SIMPLE":
    → SmolLM2-1.7B or Haiku (router decides)

elif task_complexity == "MODERATE":
    → Sonnet 4.5 (quality conversation) ✅

elif task_complexity == "COMPLEX":
    → Opus 4.6 architect (building features) ✅
```

### Fine-Tuning Router Behavior

In your `.env`, control when SmolLM2 is used:

```bash
# Conservative (default) - Only trivial tasks
LOCAL_MODEL_FOR=trivial

# Balanced - Trivial and simple tasks
LOCAL_MODEL_FOR=trivial,simple

# Aggressive - Include chat (not recommended for quality)
LOCAL_MODEL_FOR=trivial,simple,chat
```

**Recommendation:** Stick with `trivial,simple` for best balance.

## Monitoring & Testing

### Check Model Usage

```bash
# Monitor logs for model selection
tail -f data/logs/agent.log | grep -E "Selected model|local"

# Example output:
# [INFO] Selected model: HuggingFaceTB/SmolLM2-1.7B-Instruct (trivial task)
# [INFO] Selected model: claude-sonnet-4-5 (moderate task)
```

### Test Performance

```python
# Test SmolLM2 directly
from transformers import AutoTokenizer, AutoModelForCausalLM
import time

model_name = "HuggingFaceTB/SmolLM2-1.7B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)

prompt = "What is your status?"
start = time.time()

inputs = tokenizer(prompt, return_tensors="pt")
outputs = model.generate(**inputs, max_new_tokens=50)
response = tokenizer.decode(outputs[0], skip_special_tokens=True)

elapsed = time.time() - start
print(f"Response: {response}")
print(f"Time: {elapsed:.2f}s")
```

## Troubleshooting

### Model Not Loading

```bash
# Check transformers version
pip install --upgrade transformers torch

# Test download
python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('HuggingFaceTB/SmolLM2-1.7B-Instruct')"
```

### Slow Performance

```bash
# Check CPU usage
top

# If CPU maxed out, reduce concurrent usage:
# In agent.yaml, reduce max_concurrent for orchestrator
```

### Poor Quality Responses

```bash
# If SmolLM2 gives poor responses, adjust routing:
# In .env, be more conservative:
LOCAL_MODEL_FOR=trivial  # Only ultra-simple tasks

# Or disable local model:
LOCAL_MODEL_ENABLED=false
```

## Cost Savings

### With SmolLM2 Enabled

```
Typical daily Telegram usage (100 messages):

Without local model:
- 30 simple queries × Haiku   = $0.15
- 50 conversations × Sonnet   = $2.50
- 20 complex tasks × Opus     = $5.00
Total: ~$7.65/day

With SmolLM2 for simple tasks:
- 30 simple queries × SmolLM2 = $0.00 (local)
- 50 conversations × Sonnet   = $2.50
- 20 complex tasks × Opus     = $5.00
Total: ~$7.50/day → Save ~$0.15/day

Annual savings: ~$55/year
Plus: No rate limits on local model!
```

## Best Practices

1. **Start Conservative**
   - Begin with `LOCAL_MODEL_FOR=trivial`
   - Monitor quality in Telegram responses
   - Gradually expand if quality is good

2. **Monitor Quality**
   - Check Telegram responses daily
   - If SmolLM2 gives poor answers, disable it
   - Trust the router's complexity assessment

3. **Use for Right Tasks**
   - ✅ Status checks
   - ✅ Intent parsing
   - ✅ Simple confirmations
   - ❌ Complex conversations
   - ❌ Feature building
   - ❌ Nuanced understanding

4. **Resource Management**
   - First run downloads ~3.4GB
   - Model stays in memory (~4GB RAM)
   - Consider server RAM capacity

## Summary

**SmolLM2-1.7B-Instruct** is the **best local model** for CPU-based inference in your autonomous agent:

✅ **10-20x faster** than Mistral-7B on CPU
✅ **Good quality** for simple tasks
✅ **Low memory** footprint
✅ **Zero cost** and no rate limits
✅ **Designed for edge** deployment

**Quick Start:**
```bash
# Update .env
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_NAME=HuggingFaceTB/SmolLM2-1.7B-Instruct

# Restart
sudo systemctl restart claude-agent
```

**Monitor:**
```bash
tail -f data/logs/agent.log | grep "Selected model"
```

Enjoy unlimited, instant local inference for simple tasks! 🚀
