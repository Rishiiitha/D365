"""Scenario-independent Phase 1 configuration (all windows use UTC)."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class DetectionConfig:
    baseline_minutes: int = 15
    observation_minutes: int = 5
    min_baseline_samples: int = 10
    warning_z: float = 2.0
    strong_z: float = 3.0
    spike_ratio: float = 3.0
    min_pattern_count: int = 5
    epsilon: float = 1.0
    # Unknown metrics remain direction-unknown; deviations are not claimed harmful.
    directions: dict = field(default_factory=lambda: {
        name: "higher_worse" for name in (
            "cpu_percent", "memory_percent", "disk_used_percent", "error_rate_percent",
            "latency_ms", "latency_p50_ms", "latency_p99_ms", "query_latency_ms",
            "locks_waiting", "queue_depth")
    } | {"hit_rate_percent": "lower_worse"})

    def __post_init__(self):
        if min(self.baseline_minutes, self.observation_minutes, self.min_baseline_samples) <= 0:
            raise ValueError("Window lengths and sample minimum must be positive")
        if not 0 < self.warning_z <= self.strong_z or self.epsilon <= 0:
            raise ValueError("Invalid detection thresholds")


@dataclass
class LLMConfig:
    provider: str = "groq"
    model: str = ""
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.groq.com/openai/v1"
    temperature: float = 0.1
    max_output_tokens: int = 3000
    max_prompt_bytes: int = 48000
    max_requests: int = 24
    max_total_output_tokens: int = 48000
    max_steps: int = 5
    timeout_seconds: int = 45

    def __post_init__(self):
        if self.provider not in {"groq", "openai", "openai_compatible"}:
            raise ValueError("Supported providers: groq, openai, openai_compatible")
        if not 0 <= self.temperature <= 0.2:
            raise ValueError("LLM temperature must be 0..0.2")
        for name in ("max_output_tokens", "max_prompt_bytes", "max_requests", "max_total_output_tokens", "max_steps", "timeout_seconds"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        parsed = urlparse(self.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("Invalid LLM_BASE_URL")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("LLM_BASE_URL requires HTTPS except on loopback")
        if self.provider == "openai" and self.base_url.rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Use provider=openai_compatible for a custom endpoint")
        if self.provider == "groq" and self.base_url.rstrip("/") != "https://api.groq.com/openai/v1":
            raise ValueError("Use provider=openai_compatible for a custom endpoint")

    @classmethod
    def from_env(cls, env_file=None):
        # Read only the application's explicit .env; process variables take precedence.
        # Never search scenario folders or mutate the process environment.
        from dotenv import dotenv_values
        values = {} if env_file is False else dotenv_values(env_file or Path(__file__).with_name(".env"))
        values.update(os.environ)
        def get(name, default=""):
            return values.get(name) or default
        provider = get("LLM_PROVIDER", "groq")
        prefix = "GROQ" if provider == "groq" else "OPENAI"
        base = "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
        return cls(provider=provider,
                   model=get("LLM_MODEL") or get(f"{prefix}_MODEL"),
                   api_key=get("LLM_API_KEY") or get(f"{prefix}_API_KEY"),
                   base_url=get("LLM_BASE_URL", base),
                   temperature=float(get("LLM_TEMPERATURE", "0.1")),
                   max_output_tokens=int(get("LLM_MAX_OUTPUT_TOKENS", "3000")),
                   max_prompt_bytes=int(get("LLM_MAX_PROMPT_BYTES", "48000")),
                   max_requests=int(get("LLM_MAX_REQUESTS", "24")),
                   max_total_output_tokens=int(get("LLM_MAX_TOTAL_OUTPUT_TOKENS", "48000")),
                   max_steps=int(get("MAX_STEPS", "5")),
                   timeout_seconds=int(get("LLM_TIMEOUT_SECONDS", "45")))
