import json
import re


def _as_text(value) -> str:
    """The model's field as text. DeepSeek sometimes sends the summary as a list
    of changes, and the client then failed on `.replace` (WINGMAN-CLIENT-A)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(f"- {_as_text(item)}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_as_text(item)}" for key, item in value.items())
    return str(value)


def parse_enhanced_backstory(result_text: str) -> tuple[str, str]:
    """Backstory and change summary from the model's answer.

    The prompt asks for `{"backstory": "...", "summary": "..."}`, sometimes in a
    code fence. Anything else is taken as the backstory itself.
    """
    stripped = result_text.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$", stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return result_text, ""
    if not isinstance(parsed, dict):
        return result_text, ""
    return _as_text(parsed.get("backstory", result_text)), _as_text(parsed.get("summary"))
