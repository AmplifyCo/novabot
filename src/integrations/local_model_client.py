"""Local model client for CPU inference."""

import logging
import json
from typing import Optional, Dict, Any, List
import requests

logger = logging.getLogger(__name__)


class LocalModelClient:
    """Client for local model inference (CPU-based)."""

    def __init__(
        self,
        model_name: str = "mistralai/Mistral-7B-Instruct-v0.3",
        endpoint: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7
    ):
        """Initialize local model client.

        Args:
            model_name: Hugging Face model name
            endpoint: Local inference server endpoint (e.g., http://localhost:8000)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
        """
        self.model_name = model_name
        self.endpoint = endpoint
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.model = None
        self.tokenizer = None

        # Only load model if no endpoint specified (direct inference)
        if not endpoint:
            try:
                logger.info(f"Loading local model: {model_name}")
                self._load_model()
            except Exception as e:
                logger.warning(f"Failed to load local model: {e}")
                logger.warning("Local model disabled. Install transformers: pip install transformers torch")

    def _load_model(self):
        """Load model and tokenizer for direct inference."""
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch

            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)

            # Load model with CPU
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float32,  # Use float32 for CPU
                device_map="cpu",
                low_cpu_mem_usage=True
            )

            logger.info(f"✅ Loaded {self.model_name} on CPU")

        except ImportError:
            logger.error("transformers or torch not installed. Run: pip install transformers torch")
            raise
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    async def create_message(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate response using local model.

        Args:
            messages: List of message dicts with role and content
            max_tokens: Override max tokens
            temperature: Override temperature
            system: System prompt (optional)

        Returns:
            Response dict compatible with Anthropic API format
        """
        max_tokens = max_tokens or self.max_tokens
        temperature = temperature or self.temperature

        try:
            # Build prompt from messages
            prompt = self._build_prompt(messages, system)

            # Generate using endpoint or local model
            if self.endpoint:
                response_text = await self._generate_via_endpoint(prompt, max_tokens, temperature)
            else:
                response_text = self._generate_local(prompt, max_tokens, temperature)

            # Format response to match Anthropic API
            return {
                "content": [{"type": "text", "text": response_text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0}  # Approximate
            }

        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise

    def _build_prompt(self, messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
        """Build prompt from messages.

        Args:
            messages: List of messages
            system: System prompt

        Returns:
            Formatted prompt string
        """
        prompt_parts = []

        # Add system prompt if provided
        if system:
            prompt_parts.append(f"System: {system}\n")

        # Add conversation history
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                prompt_parts.append(f"User: {content}\n")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}\n")

        # Add final assistant prompt
        prompt_parts.append("Assistant:")

        return "\n".join(prompt_parts)

    def _generate_local(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate using local model.

        Args:
            prompt: Input prompt
            max_tokens: Max tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text
        """
        if not self.model or not self.tokenizer:
            raise RuntimeError("Model not loaded. Check initialization errors.")

        import torch

        # Tokenize
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)

        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.eos_token_id
            )

        # Decode
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Extract only the assistant's response (remove prompt)
        if "Assistant:" in response:
            response = response.split("Assistant:")[-1].strip()

        return response

    async def _generate_via_endpoint(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate using remote endpoint (vLLM, Ollama, etc.).

        Args:
            prompt: Input prompt
            max_tokens: Max tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text
        """
        try:
            # OpenAI-compatible API format (works with vLLM, Ollama)
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature
            }

            response = requests.post(
                f"{self.endpoint}/v1/completions",
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            return result["choices"][0]["text"].strip()

        except Exception as e:
            logger.error(f"Error calling endpoint {self.endpoint}: {e}")
            raise

    def is_available(self) -> bool:
        """Check if local model is available.

        Returns:
            True if model is loaded or endpoint is configured
        """
        if self.endpoint:
            try:
                response = requests.get(f"{self.endpoint}/health", timeout=5)
                return response.status_code == 200
            except:
                return False
        return self.model is not None and self.tokenizer is not None
