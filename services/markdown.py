import re
from io import StringIO
from markdown import Markdown

# Maximum number of list items per list block before stripping that list for TTS
MAX_LIST_ITEMS_FOR_TTS = 15


def remove_emote_text(text: str):
    """Removes emotes from text responses, which LLMs tend to place between *.

    Args:
        text (str): The response text passed, which may contain emotes.

    Returns:
        text: The response string with any strings between * removed.
    """
    while True:
        start = text.find("*")
        if start == -1:
            break
        end = text.find("*", start + 1)
        if end == -1:
            break
        text = text[:start] + text[end + 1 :]
    return text


def remove_emojis(text: str) -> str:
    """Removes emoji characters from text.

    Emojis don't work well with TTS - they either get skipped, read as
    "emoji" or produce weird sounds depending on the provider.

    Args:
        text (str): The text that may contain emojis.

    Returns:
        str: The text with emojis removed.
    """
    # Comprehensive emoji pattern covering most Unicode emoji ranges
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f1e0-\U0001f1ff"  # flags (iOS)
        "\U00002702-\U000027b0"  # dingbats
        "\U000024c2-\U0001f251"  # enclosed characters
        "\U0001f900-\U0001f9ff"  # supplemental symbols & pictographs
        "\U0001fa00-\U0001fa6f"  # chess symbols
        "\U0001fa70-\U0001faff"  # symbols & pictographs extended-A
        "\U00002600-\U000026ff"  # misc symbols
        "\U00002700-\U000027bf"  # dingbats
        "\U0001f000-\U0001f02f"  # mahjong tiles
        "\U0001f0a0-\U0001f0ff"  # playing cards
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text)


def extract_markdown_link_text(text: str) -> str:
    """Extracts link text from Markdown links, removing the URL.

    Converts [link text](url) to just "link text" so TTS reads the
    descriptive text instead of the URL.

    Args:
        text (str): Text that may contain Markdown links.

    Returns:
        str: Text with Markdown links converted to just the link text.
    """
    # Pattern matches [link text](url) and captures just the link text
    markdown_link_pattern = re.compile(r"\[([^\]]+)\]\([^)]+\)")
    return markdown_link_pattern.sub(r"\1", text)


def remove_links(text: str):
    """Removes standalone URLs from text.

    Note: Call extract_markdown_link_text() first to preserve link text
    from Markdown links before this strips remaining raw URLs.

    Args:
        text (str): Text that may contain URLs.

    Returns:
        tuple: (cleaned_text, contains_links)
    """
    # Regular expression pattern to match URLs
    url_pattern = re.compile(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
    )

    # Find all URLs in the text
    urls = url_pattern.findall(text)
    contains_links = bool(urls)

    # Replace all URLs with an empty string
    cleaned_text = url_pattern.sub("", text)

    return cleaned_text, contains_links


def remove_code_blocks(text: str):
    """Removes code blocks enclosed in triple backticks."""
    code_block_pattern = re.compile(r"```.*?```", re.DOTALL)

    code_blocks = code_block_pattern.findall(text)
    contains_code_blocks = bool(code_blocks)

    cleaned_text = code_block_pattern.sub("", text)

    return cleaned_text, contains_code_blocks


def remove_tables(text: str) -> str:
    """Removes markdown tables entirely — they never sound good in TTS.

    Matches table blocks: lines starting with |, including the separator row
    (e.g. |---|---|). Consecutive table lines are removed as a block.

    Args:
        text (str): Raw markdown text.

    Returns:
        str: Text with all tables removed.
    """
    # Match consecutive lines that start with | (table rows)
    table_pattern = re.compile(
        r"(^\|.+\|[ \t]*\n?){2,}",
        re.MULTILINE,
    )
    return table_pattern.sub("", text)


def _parse_list_block(lines: list[str]) -> list[dict]:
    """Parses a block of markdown list lines into a structured representation.

    Returns a list of top-level items, each with optional sub-items:
        [{"text": "Combat Ships", "children": ["Avenger Stalker", "Redeemer"]}, ...]
    """
    items: list[dict] = []
    current_item: dict = {"text": "", "children": []}
    has_current = False

    # Patterns for top-level and nested list items
    top_level = re.compile(r"^(?:\d+[.)]\s+|[-*+]\s+)(.+)")
    nested = re.compile(r"^(?:\s{2,}|\t)(?:\d+[.)]\s+|[-*+]\s+)(.+)")

    for line in lines:
        m_nested = nested.match(line)
        m_top = top_level.match(line)

        if m_nested and has_current:
            # It's a sub-item of the current top-level item
            current_item["children"].append(m_nested.group(1).strip())
        elif m_top:
            # New top-level item
            current_item = {"text": m_top.group(1).strip(), "children": []}
            has_current = True
            items.append(current_item)

    return items


def _count_list_items(items: list[dict]) -> int:
    """Counts total items including children."""
    return sum(1 + len(item["children"]) for item in items)


def _format_list_for_tts(items: list[dict]) -> str:
    """Formats parsed list items into natural speech.

    Examples:
        - Simple list: "Avenger Stalker, Redeemer, and Hammerhead."
        - With sub-items: "Combat Ships: Avenger Stalker, Redeemer. Mining Ships: Prospector, Mole."
    """
    parts: list[str] = []

    for item in items:
        if item["children"]:
            children_text = ", ".join(item["children"])
            parts.append(f'{item["text"]}: {children_text}')
        else:
            parts.append(item["text"])

    # If all items are simple (no children), join with commas
    if all(not item["children"] for item in items):
        if len(parts) == 1:
            return parts[0] + "."
        elif len(parts) == 2:
            return f"{parts[0]} and {parts[1]}."
        else:
            return ", ".join(parts[:-1]) + f", and {parts[-1]}."

    # Items with sub-items get joined with periods
    return ". ".join(parts) + "."


def convert_lists_for_tts(text: str) -> str:
    """Converts markdown lists to TTS-friendly natural language.

    Short lists are converted to spoken enumerations.
    Long lists (> MAX_LIST_ITEMS_FOR_TTS total items in a single list block)
    are stripped entirely.

    Tolerates blank lines between list items (common in LLM output).

    Args:
        text (str): Raw markdown text.

    Returns:
        str: Text with lists converted to natural speech or removed.
    """
    lines = text.split("\n")
    result_lines: list[str] = []
    list_block: list[str] = []
    blank_buffer: list[str] = []  # blank lines that might be inside a list
    list_item_pattern = re.compile(r"^(\s*)(?:\d+[.)]\s+|[-*+]\s+)")

    def flush_list_block():
        """Process accumulated list lines and append result."""
        if not list_block:
            return
        items = _parse_list_block(list_block)
        if not items:
            # Couldn't parse — re-add raw lines
            result_lines.extend(list_block)
            list_block.clear()
            return
        total = _count_list_items(items)
        if total <= MAX_LIST_ITEMS_FOR_TTS:
            result_lines.append(_format_list_for_tts(items))
        # else: too long, strip entirely
        list_block.clear()

    for line in lines:
        if list_item_pattern.match(line):
            # This is a list item — absorb any buffered blank lines into the list
            # (they were just spacing between items)
            blank_buffer.clear()
            list_block.append(line)
        elif line.strip() == "" and list_block:
            # Blank line while we're inside a list — buffer it
            # (might be spacing between list items, or end of list)
            blank_buffer.append(line)
        else:
            # Non-blank, non-list line — the list has ended
            flush_list_block()
            # The buffered blank lines were actually between the list and this text
            result_lines.extend(blank_buffer)
            blank_buffer.clear()
            result_lines.append(line)

    # Flush any trailing list block
    flush_list_block()
    # Don't forget trailing blank lines
    result_lines.extend(blank_buffer)

    return "\n".join(result_lines)


def _write_with_tracking(
    stream: StringIO, text: str, last_emitted_char: list[str | None]
):
    """Write text to stream and track the last emitted character."""
    if not text:
        return
    stream.write(text)
    last_emitted_char[0] = text[-1]


def unmark_element(element, stream=None, last_emitted_char=None):
    """Convert a Markdown HTML element tree to plain text with proper spacing.

    Inserts spaces/newlines between block-level elements so that TTS
    engines get proper word boundaries instead of words running together.
    """
    if stream is None:
        stream = StringIO()
    if last_emitted_char is None:
        last_emitted_char = [None]

    # Block-level tags that need separation
    block_tags = {
        "p",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "br",
        "hr",
        "blockquote",
        "pre",
    }

    if element.text:
        _write_with_tracking(stream, element.text, last_emitted_char)

    for sub in element:
        sub_tag = getattr(sub, "tag", None)
        # Add spacing before block-level child elements
        if sub_tag in block_tags:
            last_char = last_emitted_char[0]
            if last_char and last_char not in ("\n", " "):
                # If we already end with sentence-ending punctuation, add a space.
                # Otherwise add a sentence boundary to prevent word run-on.
                if last_char in (".", "!", "?"):
                    _write_with_tracking(stream, " ", last_emitted_char)
                else:
                    _write_with_tracking(stream, ". ", last_emitted_char)
        unmark_element(sub, stream, last_emitted_char)

    if element.tail:
        _write_with_tracking(stream, element.tail, last_emitted_char)

    return stream.getvalue()


# patching Markdown
Markdown.output_formats["plain"] = unmark_element
__md = Markdown(output_format="plain")
__md.stripTopLevelTags = False


def remove_markdown(text: str):
    """Converts markdown formatting to plain text.

    Note: The Markdown instance needs to be reset between calls to avoid
    state leaking between conversions.
    """
    __md.reset()
    return __md.convert(text)


def cleanup_text(text: str):
    """Cleans up text for TTS playback.

    Removes/transforms elements that don't work well with text-to-speech:
    - Removes code blocks (``` ... ```)
    - Removes tables entirely
    - Converts short lists to natural speech enumerations
    - Strips long lists per list block
    - Extracts link text from Markdown links [text](url) → text
    - Removes standalone URLs
    - Removes remaining Markdown formatting
    - Removes emote text (*action*)
    - Removes emojis

    Args:
        text (str): The raw text from LLM response.

    Returns:
        tuple: (cleaned_text, contains_links, contains_code_blocks)
    """
    # Remove code blocks first (before any text processing)
    text, contains_code_blocks = remove_code_blocks(text)
    # Remove tables entirely — they never sound good in TTS
    text = remove_tables(text)
    # Convert lists to natural speech (or strip if too long)
    text = convert_lists_for_tts(text)
    # Extract link text from Markdown links before removing markdown
    text = extract_markdown_link_text(text)
    # Remove remaining markdown formatting (bold, italic, headers, etc.)
    text = remove_markdown(text)
    # Remove standalone URLs (Markdown link URLs already handled above)
    text, contains_links = remove_links(text)
    # Remove emote text between asterisks
    text = remove_emote_text(text)
    # Remove emojis
    text = remove_emojis(text)
    # Clean up extra whitespace that may result from removals
    text = re.sub(r"[ \t]+", " ", text)  # collapse horizontal whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excessive newlines
    text = text.strip()

    return text, contains_links, contains_code_blocks
