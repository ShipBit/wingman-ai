"""Export reusable voice-command phrases from a generated SC keybinding cache.

Usage:
    python export_command_phrase_knowledge.py R4_90
    python export_command_phrase_knowledge.py R4_90/sc_all_keybindings.json
"""

import argparse
import json
from pathlib import Path


KNOWLEDGE_FILENAME = "command_phrase_knowledge.json"


def export_command_phrase_knowledge(source: Path, destination: Path) -> int:
    """Write only reusable command phrases from a generated keybinding JSON file."""
    keybindings = json.loads(source.read_text(encoding="utf-8"))
    extracted_commands = {
        action_name: command["command-phrases"]
        for action_name, command in sorted(keybindings.items())
        if command.get("command-phrases")
    }
    commands = {}
    if destination.is_file():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing.get("schema_version") != 1:
            raise ValueError(f"Unsupported command phrase knowledge: {destination}")
        commands.update(existing.get("commands", {}))
    commands.update(extracted_commands)
    payload = {
        "schema_version": 1,
        "source_version": source.parent.name,
        "commands": dict(sorted(commands.items())),
    }
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(commands)


def resolve_source(argument: str, script_dir: Path) -> Path:
    """Resolve either a version name or a direct sc_all_keybindings.json path."""
    source = Path(argument)
    if not source.is_absolute():
        direct_source = Path.cwd() / source
        source = direct_source if direct_source.is_file() else script_dir / source
    if source.is_dir():
        source = source / "sc_all_keybindings.json"
    if not source.is_file():
        raise FileNotFoundError(f"Keybinding cache not found: {source}")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Version directory or sc_all_keybindings.json")
    parser.add_argument(
        "--output",
        type=Path,
        help=f"Output path (default: next to this script as {KNOWLEDGE_FILENAME})",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    source = resolve_source(args.source, script_dir)
    destination = args.output or script_dir / KNOWLEDGE_FILENAME
    count = export_command_phrase_knowledge(source, destination)
    print(f"Exported {count} command phrase sets to {destination}")


if __name__ == "__main__":
    main()
