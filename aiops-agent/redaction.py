"""Redact agent-bound telemetry recursively before context limiting or transmission."""
import re
import ipaddress


def ipv6_replacement(match):
    try:
        ipaddress.IPv6Address(match.group())
        return "[REDACTED_IP]"
    except ipaddress.AddressValueError:
        return match.group()

SENSITIVE_KEYS = re.compile(r"(?:password|passwd|secret|token|authorization|credential|api[_-]?key|email|user[_-]?id|client[_-]?ip|phone|address|cookie|couponcode)", re.I)
PATTERNS = [
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
    (re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.I), "[REDACTED_AUTH]"),
    (re.compile(r"\b(?:sk|sk-proj|ghp|github_pat)-?[A-Za-z0-9_-]{16,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bgsk_[A-Za-z0-9_-]{16,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED_JWT]"),
    (re.compile(r"((?:password|passwd|secret|token|api[_-]?key|credential|email|user[_-]?id|client[_-]?ip|cookie)\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", re.I), r"\1[REDACTED]"),
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F]{0,4}(?![\w:])"), ipv6_replacement),
    (re.compile(r"(?<!\w)(?:\+\d{1,3}[ -]?)?\(?\d{3}\)?[ -]\d{3}[ -]\d{4}(?!\w)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)"), "[REDACTED_IDENTIFIER]"),
]
SAFE_COUNT_KEYS = {"prompt_tokens", "completion_tokens", "total_tokens", "max_output_tokens",
                   "reserved_output_tokens", "max_total_output_tokens", "input_tokens", "output_tokens"}


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k not in SAFE_COUNT_KEYS and SENSITIVE_KEYS.search(k) else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED_SECRET]")
        for pattern, replacement in PATTERNS:
            value = pattern.sub(replacement, value)
    return value
