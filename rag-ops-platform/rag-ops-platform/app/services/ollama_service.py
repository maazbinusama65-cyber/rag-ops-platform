"""
Ollama service — handles LLM inference and embedding generation.
Supports both regular and streaming responses.
"""

import json
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an expert SRE and DevOps knowledge assistant.
You answer questions using ONLY the provided context from internal runbooks and documentation.
If the context does not contain enough information to answer the question, say so clearly.
Never fabricate information. Be precise, concise, and actionable.
Format your answers with clear structure when relevant (steps, warnings, commands).
"""


class OllamaService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self.embed_model = settings.OLLAMA_EMBED_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts sequentially."""
        embeddings = []
        for text in texts:
            embedding = await self.embed(text)
            embeddings.append(embedding)
        return embeddings

    async def generate(self, prompt: str, context_docs: list[str]) -> str:
        """Generate a non-streaming response from Ollama."""
        context = "\n\n---\n\n".join(context_docs)
        full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}\n\nAnswer:"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "options": {"temperature": 0.1, "top_p": 0.9},
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["response"]

    async def generate_stream(
        self, prompt: str, context_docs: list[str]
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response from Ollama."""
        context = "\n\n---\n\n".join(context_docs)
        full_prompt = f"Context:\n{context}\n\nQuestion: {prompt}\n\nAnswer:"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": True,
                    "options": {"temperature": 0.1, "top_p": 0.9},
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            if token := chunk.get("response", ""):
                                yield token
                            if chunk.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue

    async def list_models(self) -> list[str]:
        """List available Ollama models."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False


# Singleton instance
ollama_service = OllamaService()
