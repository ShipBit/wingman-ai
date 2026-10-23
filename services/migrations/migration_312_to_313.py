"""Migration from version 3.1.2 to 3.1.3.

- Removes the obsolete ``llama_cpp.reasoning_effort`` setting. Reasoning for the
  local support model is now decided per call (off by default, opt-in via
  ``reasoning=True`` on background tasks like memory extraction), so the global
  user-facing toggle no longer exists.
- Removes the ``llama_cpp`` sampling settings (``temperature``, ``top_p``,
  ``top_k``, ``presence_penalty``). These are now Qwen3.5-recommended defaults
  baked into the code; callers override them per call via ``SamplingPreset`` or
  explicit arguments, so they are no longer user-configurable.
"""

from services.migrations.base_migration import BaseMigration


class Migration312To313(BaseMigration):
    """Migration from 3.1.2 to 3.1.3."""

    old_version = "3_1_2"
    new_version = "3_1_3"

    # Obsolete keys to strip from the llama_cpp settings block.
    _OBSOLETE_LLAMA_CPP_KEYS = [
        "reasoning_effort",
        "temperature",
        "top_p",
        "top_k",
        "presence_penalty",
    ]

    def migrate_settings(self, old: dict) -> dict:
        llama_cpp = old.get("llama_cpp")
        if isinstance(llama_cpp, dict):
            for key in self._OBSOLETE_LLAMA_CPP_KEYS:
                if key in llama_cpp:
                    llama_cpp.pop(key, None)
                    self.log(f"- removed obsolete llama_cpp.{key}")
        return old
