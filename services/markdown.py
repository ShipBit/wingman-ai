import re
from io import StringIO
from markdown import Markdown


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


def remove_links(text: str):
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
    # Regular expression pattern to match code blocks enclosed in triple backticks
    code_block_pattern = re.compile(r"```.*?```", re.DOTALL)

    # Find all code blocks in the text
    code_blocks = code_block_pattern.findall(text)
    contains_code_blocks = bool(code_blocks)

    # Replace all code blocks with an empty string
    cleaned_text = code_block_pattern.sub("", text)

    return cleaned_text, contains_code_blocks


def unmark_element(element, stream=None):
    if stream is None:
        stream = StringIO()
    if element.text:
        stream.write(element.text)
    for sub in element:
        unmark_element(sub, stream)
    if element.tail:
        stream.write(element.tail)
    return stream.getvalue()


# patching Markdown
Markdown.output_formats["plain"] = unmark_element
__md = Markdown(output_format="plain")
__md.stripTopLevelTags = False


def remove_markdown(text: str):
    return __md.convert(text)


def cleanup_text(text: str):
    text = remove_markdown(text)
    text, contains_links = remove_links(text)
    text, contains_code_blocks = remove_code_blocks(text)
    text = remove_emote_text(text)

    return text, contains_links, contains_code_blocks
