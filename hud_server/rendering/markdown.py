"""
HeadsUp Overlay - PIL-based implementation with sophisticated Markdown rendering

This implementation uses ONLY:
- PIL (Pillow) for rendering (text, shapes, images)
- Win32 API for window management
"""

import copy
import os
import re
from typing import Tuple, Dict, List
import io
import urllib.request
import urllib.error

# PIL for rendering
try:
    from PIL import Image, ImageDraw, ImageFont, ImageChops
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageChops = None

# Import cache size constants (with fallback defaults for standalone usage)
try:
    from hud_server.constants import (
        MAX_IMAGE_CACHE_SIZE,
        MAX_INLINE_TOKEN_CACHE_SIZE,
        MAX_TEXT_WRAP_CACHE_SIZE,
        MAX_TEXT_SIZE_CACHE_SIZE,
    )
except ImportError:
    # Fallback defaults for standalone testing
    MAX_IMAGE_CACHE_SIZE = 20
    MAX_INLINE_TOKEN_CACHE_SIZE = 100
    MAX_TEXT_WRAP_CACHE_SIZE = 200
    MAX_TEXT_SIZE_CACHE_SIZE = 2000


class MarkdownRenderer:
    """Full-featured Markdown renderer with typewriter support.

    OPTIMIZED: Includes LRU caching for parsed inline tokens and text sizes.
    """

    def __init__(self, fonts: Dict, colors: Dict, color_emojis: bool = True):
        self.fonts = fonts
        self.colors = colors
        self.color_emojis = color_emojis  # Enable colored emoji rendering
        # Calculate line height based on font size (1.625x for good readability)
        font_size = fonts.get('_font_size', 16)
        self.line_height = int(font_size * 1.625)
        self.letter_spacing = 0  # No letter spacing
        self.char_count = 0  # For typewriter tracking
        self._text_size_cache = {}
        self._text_size_cache_max = MAX_TEXT_SIZE_CACHE_SIZE
        self._image_cache = {}  # Cache for loaded images
        self._image_cache_max = MAX_IMAGE_CACHE_SIZE
        self._image_load_failures = set()  # Track failed URLs to avoid retrying

        # LRU cache for parsed inline tokens (expensive to compute)
        # Key: text -> List[Dict] of tokens
        self._inline_token_cache = {}
        self._max_token_cache_size = MAX_INLINE_TOKEN_CACHE_SIZE

        # LRU cache for wrapped text lines
        # Key: (text, font_id, max_width) -> List[str]
        self._wrap_cache = {}
        self._max_wrap_cache_size = MAX_TEXT_WRAP_CACHE_SIZE

        # Cache statistics for monitoring
        self._cache_stats = {
            'text_size_hits': 0,
            'text_size_misses': 0,
            'token_cache_hits': 0,
            'token_cache_misses': 0,
            'wrap_cache_hits': 0,
            'wrap_cache_misses': 0,
        }

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics for performance monitoring."""
        return dict(self._cache_stats)

    def clear_caches(self):
        """Clear all caches. Call when memory pressure is high."""
        self._text_size_cache.clear()
        self._image_cache.clear()
        self._inline_token_cache.clear()
        self._wrap_cache.clear()
        # Reset stats
        for key in self._cache_stats:
            self._cache_stats[key] = 0

    def set_colors(self, text: Tuple, accent: Tuple, bg: Tuple):
        self.colors = {'text': text, 'accent': accent, 'bg': bg}

    def _load_image(self, url: str, max_width: int) -> Image.Image:
        """Load an image from URL or file path, resize to fit max_width while keeping aspect ratio.

        Returns None if loading fails.
        """
        # Check cache first
        cache_key = (url, max_width)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        # Check if we already failed to load this URL
        if url in self._image_load_failures:
            return None

        try:
            img = None

            # Check if it's a local file path
            if os.path.isfile(url):
                img = Image.open(url)
            elif url.startswith('file://'):
                # Handle file:// URLs
                file_path = url[7:]  # Remove 'file://'
                if os.path.isfile(file_path):
                    img = Image.open(file_path)
            elif url.startswith(('http://', 'https://')):
                # Download from URL with timeout
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    img_data = response.read()
                    img = Image.open(io.BytesIO(img_data))

            if img is None:
                self._image_load_failures.add(url)
                return None

            # Convert to RGBA if necessary
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            # Resize to fit max_width while keeping aspect ratio (only shrink, never enlarge)
            orig_width, orig_height = img.size
            if orig_width > max_width:
                ratio = max_width / orig_width
                new_height = int(orig_height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

            # Cache the result (limit cache size)
            if len(self._image_cache) >= self._image_cache_max:
                # Remove oldest entry
                oldest_key = next(iter(self._image_cache))
                del self._image_cache[oldest_key]

            self._image_cache[cache_key] = img
            return img

        except Exception as e:
            # Mark as failed to avoid retrying
            self._image_load_failures.add(url)
            return None

    def _get_text_size(self, text: str, font) -> Tuple[int, int]:
        """Get text size with caching.

        OPTIMIZED: Uses LRU-style cache with statistics tracking.
        """
        # Use id(font) because font objects are not hashable but are persistent in this app
        key = (text, id(font))
        if key in self._text_size_cache:
            self._cache_stats['text_size_hits'] += 1
            return self._text_size_cache[key]

        self._cache_stats['text_size_misses'] += 1

        try:
            bbox = font.getbbox(text)
            size = (int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1]))
        except:
            size = (len(text) * 8, 16)

        # Limit cache size to prevent memory leaks (simple eviction)
        if len(self._text_size_cache) > self._text_size_cache_max:
            self._text_size_cache.clear()

        self._text_size_cache[key] = size
        return size

    def _draw_text_with_spacing(self, draw, pos: Tuple[int, int], text: str, fill, font, embedded_color=False):
        """Draw text - direct draw since no letter spacing.

        Args:
            embedded_color: If True and color_emojis is enabled, renders emojis in full color.
        """
        if embedded_color and self.color_emojis:
            draw.text(pos, text, fill=fill, font=font, embedded_color=True)
        else:
            draw.text(pos, text, fill=fill, font=font)

    def _is_emoji_codepoint(self, codepoint: int) -> bool:
        """Check if a Unicode codepoint is an emoji base character."""
        return (
            (0x1F600 <= codepoint <= 0x1F64F) or  # Emoticons
            (0x1F300 <= codepoint <= 0x1F5FF) or  # Misc Symbols and Pictographs
            (0x1F680 <= codepoint <= 0x1F6FF) or  # Transport and Map
            (0x1F7E0 <= codepoint <= 0x1F7EB) or  # Colored circles (ðŸŸ ðŸŸ¡ðŸŸ¢ðŸŸ£ðŸŸ¤ðŸ”µ)
            (0x1F900 <= codepoint <= 0x1F9FF) or  # Supplemental Symbols and Pictographs
            (0x1FA70 <= codepoint <= 0x1FAFF) or  # Symbols and Pictographs Extended-A
            (0x2600 <= codepoint <= 0x26FF) or    # Misc Symbols
            (0x2700 <= codepoint <= 0x27BF) or    # Dingbats
            (0x2300 <= codepoint <= 0x23FF) or    # Misc Technical
            (0x2B50 <= codepoint <= 0x2B55) or    # Stars and circles
            (0x203C <= codepoint <= 0x3299) or    # Various symbols
            (0x1F004 == codepoint) or             # Mahjong
            (0x1F0CF == codepoint) or             # Joker
            (0x1F170 <= codepoint <= 0x1F251) or  # Enclosed Ideographic Supplement
            (0x1F1E0 <= codepoint <= 0x1F1FF) or  # Regional indicator symbols (flags)
            (0x1F910 <= codepoint <= 0x1F9FF) or  # Extended emoji
            (0x231A <= codepoint <= 0x231B) or    # Watch, hourglass
            (0x23E9 <= codepoint <= 0x23F3) or    # Media controls
            (0x23F8 <= codepoint <= 0x23FA) or    # More media
            (0x25AA <= codepoint <= 0x25AB) or    # Squares
            (0x25B6 == codepoint) or              # Play button
            (0x25C0 == codepoint) or              # Reverse button
            (0x25FB <= codepoint <= 0x25FE) or    # Squares
            (0x2614 <= codepoint <= 0x2615) or    # Umbrella, coffee
            (0x2648 <= codepoint <= 0x2653) or    # Zodiac
            (0x267F == codepoint) or              # Wheelchair
            (0x2693 == codepoint) or              # Anchor
            (0x26A1 == codepoint) or              # High voltage
            (0x26AA <= codepoint <= 0x26AB) or    # Circles
            (0x26BD <= codepoint <= 0x26BE) or    # Sports
            (0x26C4 <= codepoint <= 0x26C5) or    # Weather
            (0x26CE == codepoint) or              # Ophiuchus
            (0x26D4 == codepoint) or              # No entry
            (0x26EA == codepoint) or              # Church
            (0x26F2 <= codepoint <= 0x26F3) or    # Fountain, golf
            (0x26F5 == codepoint) or              # Sailboat
            (0x26FA == codepoint) or              # Tent
            (0x26FD == codepoint) or              # Fuel pump
            (0x2702 == codepoint) or              # Scissors
            (0x2705 == codepoint) or              # Check mark
            (0x2708 <= codepoint <= 0x270D) or    # Airplane to writing hand
            (0x270F == codepoint) or              # Pencil
            (0x2712 == codepoint) or              # Black nib
            (0x2714 == codepoint) or              # Check mark
            (0x2716 == codepoint) or              # X mark
            (0x271D == codepoint) or              # Latin cross
            (0x2721 == codepoint) or              # Star of David
            (0x2728 == codepoint) or              # Sparkles
            (0x2733 <= codepoint <= 0x2734) or    # Eight spoked asterisk
            (0x2744 == codepoint) or              # Snowflake
            (0x2747 == codepoint) or              # Sparkle
            (0x274C == codepoint) or              # Cross mark
            (0x274E == codepoint) or              # Cross mark
            (0x2753 <= codepoint <= 0x2755) or    # Question marks
            (0x2757 == codepoint) or              # Exclamation mark
            (0x2763 <= codepoint <= 0x2764) or    # Heart exclamation, red heart
            (0x2795 <= codepoint <= 0x2797) or    # Plus, minus, divide
            (0x27A1 == codepoint) or              # Right arrow
            (0x27B0 == codepoint) or              # Curly loop
            (0x27BF == codepoint) or              # Double curly loop
            (0x2934 <= codepoint <= 0x2935) or    # Arrows
            (0x2B05 <= codepoint <= 0x2B07) or    # Arrows
            (0x2B1B <= codepoint <= 0x2B1C) or    # Squares
            (0x3030 == codepoint) or              # Wavy dash
            (0x303D == codepoint) or              # Part alternation mark
            (0x1F004 == codepoint) or             # Mahjong red dragon
            (0x1F0CF == codepoint) or             # Playing card black joker
            (0x1F18E == codepoint) or             # AB button
            (0x1F191 <= codepoint <= 0x1F19A) or  # CL button to VS button
            (0x1F201 <= codepoint <= 0x1F202) or  # Japanese buttons
            (0x1F21A == codepoint) or             # Japanese button
            (0x1F22F == codepoint) or             # Japanese button
            (0x1F232 <= codepoint <= 0x1F23A) or  # Japanese buttons
            (0x1F250 <= codepoint <= 0x1F251) or  # Japanese buttons
            (0x00A9 == codepoint) or              # Copyright
            (0x00AE == codepoint) or              # Registered
            (0x2122 == codepoint)                 # Trademark
        )

    def _get_emoji_length(self, text: str, pos: int) -> int:
        """Get the length of an emoji sequence starting at pos.

        Returns 0 if the character at pos is not an emoji.
        Handles multi-character sequences like emoji + variation selector,
        ZWJ sequences (family, skin tones), and flag sequences.
        """
        if pos >= len(text):
            return 0

        codepoint = ord(text[pos])

        # Check if this is an emoji base character
        if not self._is_emoji_codepoint(codepoint):
            return 0

        # Start with the base emoji
        length = 1

        # Check for multi-character sequences
        while pos + length < len(text):
            next_char = text[pos + length]
            next_cp = ord(next_char)

            # Variation selector (makes emoji colored or text-style)
            if next_cp == 0xFE0F or next_cp == 0xFE0E:
                length += 1
                continue

            # Zero-width joiner (for combined emojis like family, skin tones)
            if next_cp == 0x200D:
                length += 1
                # The next character after ZWJ should be another emoji
                if pos + length < len(text):
                    following_cp = ord(text[pos + length])
                    if self._is_emoji_codepoint(following_cp):
                        length += 1
                        continue
                break

            # Skin tone modifiers (Fitzpatrick scale)
            if 0x1F3FB <= next_cp <= 0x1F3FF:
                length += 1
                continue

            # Regional indicator (for flags - need two)
            if 0x1F1E0 <= next_cp <= 0x1F1FF and 0x1F1E0 <= codepoint <= 0x1F1FF:
                # This is part of a flag sequence
                if pos + length < len(text):
                    following_cp = ord(text[pos + length])
                    if 0x1F1E0 <= following_cp <= 0x1F1FF:
                        length += 1
                        continue
                break

            # Combining enclosing keycap (for keycap emojis like 1ï¸âƒ£)
            if next_cp == 0x20E3:
                length += 1
                continue

            # No more emoji modifiers
            break

        return length

    def _wrap_text(self, text: str, font, max_width: int) -> List[str]:
        """Wrap text to fit within max_width.

        OPTIMIZED: Uses caching for repeated wrap calculations.
        """
        # Check cache first
        cache_key = (text, id(font), max_width)
        if cache_key in self._wrap_cache:
            self._cache_stats['wrap_cache_hits'] += 1
            return self._wrap_cache[cache_key]

        self._cache_stats['wrap_cache_misses'] += 1

        words = text.split(' ')
        lines, current = [], []
        for word in words:
            test = ' '.join(current + [word])
            w, _ = self._get_text_size(test, font)
            if w <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(' '.join(current))
                current = [word]
        if current:
            lines.append(' '.join(current))
        result = lines or ['']

        # Cache result with size limit
        if len(self._wrap_cache) >= self._max_wrap_cache_size:
            # Simple FIFO eviction
            oldest_key = next(iter(self._wrap_cache))
            del self._wrap_cache[oldest_key]

        self._wrap_cache[cache_key] = result
        return result

    # =========================================================================
    # INLINE TOKENIZER - supports all inline markdown
    # =========================================================================

    def tokenize_inline(self, text: str) -> List[Dict]:
        """Parse inline markdown into tokens.

        OPTIMIZED: Uses LRU caching for repeated tokenization of the same text.

        Each token includes:
        - 'type': The token type (text, bold, italic, code, link, etc.)
        - 'text': The visible text content (without markdown syntax)
        - 'start': The start position in the original text
        - 'end': The end position in the original text (exclusive)
        - 'content_start': Start of the actual content (after opening syntax)
        - 'content_end': End of the actual content (before closing syntax)

        This allows the typewriter effect to correctly track position in the original text.
        """
        # Check cache first - tokens are immutable once parsed
        if text in self._inline_token_cache:
            self._cache_stats['token_cache_hits'] += 1
            # Deep copy required: callers modify token positions for typewriter effect
            return copy.deepcopy(self._inline_token_cache[text])

        self._cache_stats['token_cache_misses'] += 1

        tokens = self._tokenize_inline_uncached(text)

        # Cache the result
        if len(self._inline_token_cache) >= self._max_token_cache_size:
            # Simple FIFO eviction
            oldest_key = next(iter(self._inline_token_cache))
            del self._inline_token_cache[oldest_key]

        # Cache a deep copy, return the original (saves one copy on cache miss)
        self._inline_token_cache[text] = copy.deepcopy(tokens)
        return tokens

    def _tokenize_inline_uncached(self, text: str) -> List[Dict]:
        """Internal tokenization without caching. Called by tokenize_inline."""
        tokens = []
        i = 0

        while i < len(text):
            start_pos = i

            # Image ![alt](url)
            if text[i:i+2] == '![':
                m = re.match(r'!\[([^]]*)]\(([^)]+)\)', text[i:])
                if m:
                    full_len = len(m.group(0))
                    # Content is "alt" which starts at i+2, ends before ]
                    tokens.append({
                        'type': 'image',
                        'alt': m.group(1),
                        'url': m.group(2),
                        'start': start_pos,
                        'end': start_pos + full_len,
                        'content_start': start_pos + 2,  # After ![
                        'content_end': start_pos + 2 + len(m.group(1))  # End of alt text
                    })
                    i += full_len
                    continue

            # Link [text](url) - text can contain any character except ]
            if text[i] == '[' and (i == 0 or text[i-1] != '!'):
                m = re.match(r'\[([^]]+)]\(([^)]+)\)', text[i:])
                if m:
                    full_len = len(m.group(0))
                    link_title = m.group(1)
                    link_url = m.group(2)
                    tokens.append({
                        'type': 'link',
                        'text': link_title,
                        'url': link_url,
                        'start': start_pos,
                        'end': start_pos + full_len,
                        'content_start': start_pos + 1,  # After [
                        'content_end': start_pos + 1 + len(link_title)  # End of link title
                    })
                    i += full_len
                    continue

            # Bold Italic ***text***
            if text[i:i+3] == '***':
                end = text.find('***', i + 3)
                if end != -1:
                    content = text[i+3:end]
                    tokens.append({
                        'type': 'bold_italic',
                        'text': content,
                        'start': start_pos,
                        'end': end + 3,
                        'content_start': start_pos + 3,  # After ***
                        'content_end': end  # Before closing ***
                    })
                    i = end + 3
                    continue

            # Bold **text**
            if text[i:i+2] == '**':
                end = text.find('**', i + 2)
                if end != -1:
                    content = text[i+2:end]

                    # Parse content for emojis to support emoji rendering in bold text
                    sub_tokens = []
                    j = 0
                    while j < len(content):
                        emoji_len = self._get_emoji_length(content, j)
                        if emoji_len > 0:
                            # Found an emoji - add it as a sub-token
                            emoji_text = content[j:j+emoji_len]
                            sub_tokens.append({
                                'type': 'emoji',
                                'text': emoji_text
                            })
                            j += emoji_len
                        else:
                            # Regular text
                            if sub_tokens and sub_tokens[-1].get('type') == 'text':
                                sub_tokens[-1]['text'] += content[j]
                            else:
                                sub_tokens.append({
                                    'type': 'text',
                                    'text': content[j]
                                })
                            j += 1

                    tokens.append({
                        'type': 'bold',
                        'text': content,
                        'sub_tokens': sub_tokens if len(sub_tokens) > 1 else None,  # Only include if there are mixed tokens
                        'start': start_pos,
                        'end': end + 2,
                        'content_start': start_pos + 2,  # After **
                        'content_end': end  # Before closing **
                    })
                    i = end + 2
                    continue

            # Italic *text*
            if text[i] == '*' and (i+1 < len(text) and text[i+1] != '*'):
                end = i + 1
                while end < len(text) and not (text[end] == '*' and (end+1 >= len(text) or text[end+1] != '*')):
                    end += 1
                if end < len(text):
                    content = text[i+1:end]
                    tokens.append({
                        'type': 'italic',
                        'text': content,
                        'start': start_pos,
                        'end': end + 1,
                        'content_start': start_pos + 1,  # After *
                        'content_end': end  # Before closing *
                    })
                    i = end + 1
                    continue

            # Inline code `text`
            if text[i] == '`' and text[i:i+3] != '```':
                end = text.find('`', i + 1)
                if end != -1:
                    content = text[i+1:end]
                    tokens.append({
                        'type': 'code',
                        'text': content,
                        'start': start_pos,
                        'end': end + 1,
                        'content_start': start_pos + 1,  # After `
                        'content_end': end  # Before closing `
                    })
                    i = end + 1
                    continue

            # Strikethrough ~~text~~
            if text[i:i+2] == '~~':
                end = text.find('~~', i + 2)
                if end != -1:
                    content = text[i+2:end]
                    tokens.append({
                        'type': 'strike',
                        'text': content,
                        'start': start_pos,
                        'end': end + 2,
                        'content_start': start_pos + 2,  # After ~~
                        'content_end': end  # Before closing ~~
                    })
                    i = end + 2
                    continue

            # Bold with underscores __text__
            if text[i:i+2] == '__':
                end = text.find('__', i + 2)
                if end != -1:
                    content = text[i+2:end]
                    tokens.append({
                        'type': 'bold',
                        'text': content,
                        'start': start_pos,
                        'end': end + 2,
                        'content_start': start_pos + 2,  # After __
                        'content_end': end  # Before closing __
                    })
                    i = end + 2
                    continue

            # Italic with underscores _text_
            if text[i] == '_' and (i+1 < len(text) and text[i+1] != '_'):
                end = i + 1
                while end < len(text) and not (text[end] == '_' and (end+1 >= len(text) or text[end+1] != '_')):
                    end += 1
                if end < len(text):
                    content = text[i+1:end]
                    tokens.append({
                        'type': 'italic',
                        'text': content,
                        'start': start_pos,
                        'end': end + 1,
                        'content_start': start_pos + 1,  # After _
                        'content_end': end  # Before closing _
                    })
                    i = end + 1
                    continue

            # Inline math \( text \)
            if text[i:i+2] == '\\(':
                end = text.find('\\)', i + 2)
                if end != -1:
                    content = text[i+2:end]
                    tokens.append({
                        'type': 'math',
                        'text': content,
                        'start': start_pos,
                        'end': end + 2,
                        'content_start': start_pos + 2,  # After \(
                        'content_end': end  # Before closing \)
                    })
                    i = end + 2
                    continue

            # Task list checkbox [ ] or [x]
            if text[i:i+3] in ['[ ]', '[x]', '[X]']:
                checked = text[i+1].lower() == 'x'
                tokens.append({
                    'type': 'checkbox',
                    'checked': checked,
                    'start': start_pos,
                    'end': start_pos + 3,
                    'content_start': start_pos,
                    'content_end': start_pos + 3
                })
                i += 3
                continue

            # Footnote reference [^1] or [^name]
            if text[i:i+2] == '[^':
                m = re.match(r'\[\^([^\]]+)\]', text[i:])
                if m and not text[i:].startswith('[^') or not re.match(r'\[\^[^\]]+\]:', text[i:]):
                    # It's a reference, not a definition
                    m = re.match(r'\[\^([^\]]+)\]', text[i:])
                    if m:
                        full_len = len(m.group(0))
                        fn_id = m.group(1)
                        tokens.append({
                            'type': 'footnote_ref',
                            'id': fn_id,
                            'start': start_pos,
                            'end': start_pos + full_len,
                            'content_start': start_pos + 2,  # After [^
                            'content_end': start_pos + 2 + len(fn_id)  # Before ]
                        })
                        i += full_len
                        continue

            # Emoji detection - check for multi-character emoji sequences first
            # Many emojis include variation selectors (U+FE0F) or ZWJ sequences
            emoji_len = self._get_emoji_length(text, i)
            if emoji_len > 0:
                emoji_text = text[i:i+emoji_len]
                tokens.append({
                    'type': 'emoji',
                    'text': emoji_text,
                    'start': start_pos,
                    'end': start_pos + emoji_len,
                    'content_start': start_pos,
                    'content_end': start_pos + emoji_len
                })
                i += emoji_len
                continue

            # Regular text - accumulate consecutive characters
            if tokens and tokens[-1].get('type') == 'text':
                tokens[-1]['text'] += text[i]
                tokens[-1]['end'] = i + 1
                tokens[-1]['content_end'] = i + 1
            else:
                tokens.append({
                    'type': 'text',
                    'text': text[i],
                    'start': start_pos,
                    'end': start_pos + 1,
                    'content_start': start_pos,
                    'content_end': start_pos + 1
                })
            i += 1

        return tokens

    # =========================================================================
    # BLOCK PARSER - supports all block-level markdown
    # =========================================================================

    def parse_blocks(self, text: str) -> List[Dict]:
        """Parse markdown into block elements.

        Each block includes 'start' and 'end' positions in the original text
        for typewriter effect support.
        """
        blocks = []
        lines = text.split('\n')
        i = 0

        # Calculate line start positions for mapping
        line_starts = [0]
        for line in lines[:-1]:  # Don't need position after last line
            line_starts.append(line_starts[-1] + len(line) + 1)  # +1 for \n

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            block_start = line_starts[i] if i < len(line_starts) else len(text)

            # Empty line
            if not stripped:
                block_end = block_start + len(line) + (1 if i < len(lines) - 1 else 0)
                blocks.append({'type': 'empty', 'start': block_start, 'end': block_end})
                i += 1
                continue

            # Code block ```
            if stripped.startswith('```'):
                lang = stripped[3:].strip()
                code_lines = []
                start_i = i
                i += 1
                while i < len(lines) and not lines[i].strip().startswith('```'):
                    code_lines.append(lines[i])
                    i += 1
                # Include closing ``` in end position
                block_end = line_starts[i] + len(lines[i]) + 1 if i < len(lines) else len(text)
                blocks.append({
                    'type': 'code_block',
                    'code': '\n'.join(code_lines),
                    'lang': lang,
                    'start': block_start,
                    'end': block_end
                })
                i += 1
                continue

            # Headers #
            m = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            if m:
                block_end = block_start + len(line) + (1 if i < len(lines) - 1 else 0)
                # Content starts after "# " (header marker + space)
                content_start = block_start + len(m.group(1)) + 1  # +1 for space after #
                blocks.append({
                    'type': 'header',
                    'level': len(m.group(1)),
                    'text': m.group(2),
                    'start': block_start,
                    'end': block_end,
                    'content_start': content_start,
                    'content_end': block_end - (1 if i < len(lines) - 1 else 0)
                })
                i += 1
                continue

            # Blockquote > (can start with > or have spaces before it)
            if stripped.startswith('>') or line.lstrip().startswith('>'):
                quote_lines = []
                start_i = i
                while i < len(lines):
                    current_line = lines[i].strip()
                    if current_line.startswith('>'):
                        # Remove the > and optional space
                        content = re.sub(r'^>\s?', '', current_line)
                        quote_lines.append(content)
                        i += 1
                    elif current_line == '' and quote_lines:
                        # Empty line ends blockquote
                        break
                    else:
                        break
                if quote_lines:
                    block_end = line_starts[i-1] + len(lines[i-1]) + 1 if i > 0 and i-1 < len(lines) else len(text)
                    blocks.append({
                        'type': 'blockquote',
                        'text': ' '.join(quote_lines),
                        'start': block_start,
                        'end': block_end
                    })
                continue

            # Horizontal rule ---
            if re.match(r'^[-*_]{3,}$', stripped):
                block_end = block_start + len(line) + (1 if i < len(lines) - 1 else 0)
                blocks.append({
                    'type': 'hr',
                    'start': block_start,
                    'end': block_end
                })
                i += 1
                continue

            # Table |
            if stripped.startswith('|') and '|' in stripped[1:]:
                table_lines = []
                start_i = i
                while i < len(lines) and '|' in lines[i]:
                    table_lines.append(lines[i].strip())
                    i += 1
                block_end = line_starts[i-1] + len(lines[i-1]) + 1 if i > 0 and i-1 < len(lines) else len(text)
                blocks.append({
                    'type': 'table',
                    'lines': table_lines,
                    'start': block_start,
                    'end': block_end
                })
                continue

            # Unordered list - * +
            m = re.match(r'^(\s*)([-*+])\s+(.*)$', line)
            if m:
                items = []
                start_i = i
                while i < len(lines):
                    item_m = re.match(r'^(\s*)([-*+])\s+(.*)$', lines[i])
                    if item_m:
                        items.append({'indent': len(item_m.group(1)) // 2, 'text': item_m.group(3)})
                        i += 1
                    elif lines[i].strip() == '':
                        i += 1
                        break
                    elif re.match(r'^\s+\S', lines[i]):
                        # Check for OL start (nested list of different type)
                        if re.match(r'^\s*(?:\d+\.)+\d*\s+', lines[i]):
                            break
                        if items:
                            items[-1]['text'] += ' ' + lines[i].strip()
                        i += 1
                    else:
                        break
                block_end = line_starts[i-1] + len(lines[i-1]) + 1 if i > 0 and i-1 < len(lines) else len(text)
                blocks.append({
                    'type': 'ul',
                    'items': items,
                    'start': block_start,
                    'end': block_end
                })
                continue

            # Ordered list 1.
            m = re.match(r'^(\s*)((?:\d+\.)+\d*)\s+(.*)$', line)
            if m:
                items = []
                start_i = i
                while i < len(lines):
                    item_m = re.match(r'^(\s*)((?:\d+\.)+\d*)\s+(.*)$', lines[i])
                    if item_m:
                        items.append({'indent': len(item_m.group(1)) // 2, 'num': item_m.group(2), 'text': item_m.group(3)})
                        i += 1
                    elif lines[i].strip() == '':
                        i += 1
                        break
                    elif re.match(r'^\s+\S', lines[i]):
                        # Check for UL start (nested list of different type)
                        if re.match(r'^\s*[-*+]\s+', lines[i]):
                            break
                        if items:
                            items[-1]['text'] += ' ' + lines[i].strip()
                        i += 1
                    else:
                        break
                block_end = line_starts[i-1] + len(lines[i-1]) + 1 if i > 0 and i-1 < len(lines) else len(text)
                blocks.append({
                    'type': 'ol',
                    'items': items,
                    'start': block_start,
                    'end': block_end
                })
                continue

            # Footnote definition [^1]: text or [^name]: text
            fn_match = re.match(r'^\[\^([^\]]+)\]:\s*(.*)$', stripped)
            if fn_match:
                fn_id = fn_match.group(1)
                fn_text = fn_match.group(2)
                # Collect continuation lines (indented)
                i += 1
                while i < len(lines) and (lines[i].startswith('    ') or lines[i].startswith('\t') or lines[i].strip() == ''):
                    if lines[i].strip():
                        fn_text += ' ' + lines[i].strip()
                    i += 1
                block_end = line_starts[i-1] + len(lines[i-1]) + 1 if i > 0 and i-1 < len(lines) else len(text)
                blocks.append({
                    'type': 'footnote_def',
                    'id': fn_id,
                    'text': fn_text,
                    'start': block_start,
                    'end': block_end
                })
                continue

            # Paragraph (default)
            para = []
            start_i = i
            while i < len(lines) and lines[i].strip() and not self._is_block_start(lines[i]):
                para.append(lines[i].strip())
                i += 1
            if para:
                block_end = line_starts[i-1] + len(lines[i-1]) + 1 if i > 0 and i-1 < len(lines) else len(text)
                blocks.append({
                    'type': 'paragraph',
                    'text': ' '.join(para),
                    'start': block_start,
                    'end': block_end
                })

        return blocks

    def _is_block_start(self, line: str) -> bool:
        s = line.strip()
        if s.startswith('#') or s.startswith('```') or s.startswith('>'):
            return True
        if re.match(r'^[-*_]{3,}$', s) or (s.startswith('|') and '|' in s[1:]):
            return True
        if re.match(r'^(\s*)([-*+])\s+', line) or re.match(r'^(\s*)((?:\d+\.)+\d*)\s+', line):
            return True
        # Footnote definition
        if re.match(r'^\[\^[^\]]+\]:', s):
            return True
        return False

    # =========================================================================
    # RENDERING - Modern, sleek design
    # =========================================================================

    def render(self, draw, canvas, text: str, x: int, y: int, width: int, max_chars: int = None, pre_parsed_blocks: List[Dict] = None) -> int:
        """Render markdown with optional character limit for typewriter.

        max_chars represents the position in the ORIGINAL text up to which
        characters should be shown. This correctly handles markdown syntax
        characters that are not displayed but still count towards the position.
        """
        # Store remaining chars as position in original text for typewriter effect
        self.remaining_chars = max_chars if max_chars is not None else float('inf')

        if pre_parsed_blocks:
            blocks = pre_parsed_blocks
        else:
            blocks = self.parse_blocks(text)

        current_y = y

        for block in blocks:
            block_start = block.get('start', 0)
            block_end = block.get('end', block_start)

            # Skip blocks that haven't been reached yet by typewriter
            if self.remaining_chars != float('inf') and block_start >= self.remaining_chars:
                break

            t = block['type']

            if t == 'empty':
                current_y += self.line_height // 2
            elif t == 'header':
                current_y = self._render_header(draw, block, x, current_y, width)
            elif t == 'paragraph':
                current_y = self._render_paragraph(draw, block, x, current_y, width)
            elif t == 'code_block':
                current_y = self._render_code_block(draw, canvas, block, x, current_y, width)
            elif t == 'blockquote':
                current_y = self._render_blockquote(draw, canvas, block, x, current_y, width)
            elif t == 'hr':
                current_y = self._render_hr(draw, x, current_y, width)
            elif t == 'table':
                current_y = self._render_table(draw, block, x, current_y, width)
            elif t == 'ul':
                current_y = self._render_ul(draw, canvas, block, x, current_y, width)
            elif t == 'ol':
                current_y = self._render_ol(draw, canvas, block, x, current_y, width)
            elif t == 'footnote_def':
                current_y = self._render_footnote_def(draw, block, x, current_y, width)

        return current_y

    def _render_header(self, draw, block: Dict, x: int, y: int, width: int) -> int:
        level = block['level']
        text = block['text']
        content_start = block.get('content_start', block.get('start', 0))

        # Get base font size for spacing calculations
        base_font_size = self.fonts.get('_font_size', 16)

        # Header styling for H1-H6 with spacing scaled to font size
        # Increased spacing multipliers to prevent overlap with content below (0.75x, 0.5x, 0.375x)
        header_styles = {
            1: {'font': 'h1', 'color': self.colors['accent'], 'spacing': int(base_font_size * 0.75)},
            2: {'font': 'h2', 'color': self.colors['accent'], 'spacing': int(base_font_size * 0.5)},
            3: {'font': 'h3', 'color': self.colors['accent'], 'spacing': int(base_font_size * 0.375)},
            4: {'font': 'h4', 'color': self.colors['text'], 'spacing': int(base_font_size * 0.375)},
            5: {'font': 'h5', 'color': self.colors['text'], 'spacing': int(base_font_size * 0.375)},
            6: {'font': 'h6', 'color': (160, 168, 180), 'spacing': int(base_font_size * 0.375)},
        }

        # Get style for this level (default to H6 style for levels > 6)
        style = header_styles.get(level, header_styles[6])
        font = self.fonts.get(style['font'], self.fonts.get('bold', self.fonts['normal']))
        color = style['color']
        spacing = style['spacing']

        # Render header text with inline formatting
        tokens = self.tokenize_inline(text)

        # Adjust token positions to be absolute (relative to original text)
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))
        if typewriter_pos != float('inf'):
            for token in tokens:
                token['start'] = token.get('start', 0) + content_start
                token['end'] = token.get('end', 0) + content_start
                token['content_start'] = token.get('content_start', token['start']) + content_start
                token['content_end'] = token.get('content_end', token['end']) + content_start

        final_y = self._render_tokens(draw, tokens, x, y, width, override_color=color, override_font=font, header_level=level)

        return final_y + spacing

    def _render_paragraph(self, draw, block: Dict, x: int, y: int, width: int) -> int:
        """Render a paragraph block with typewriter support."""
        text = block.get('text', '') if isinstance(block, dict) else block
        block_start = block.get('start', 0) if isinstance(block, dict) else 0

        # Handle hard line breaks (two spaces at end of line or explicit \n)
        lines = text.split('  \n') if '  \n' in text else [text]
        current_y = y

        # Calculate relative position within this block for typewriter
        # remaining_chars is the absolute position in original text
        # We need to convert it to relative position within this paragraph's content
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))

        for line in lines:
            if line.strip():
                tokens = self.tokenize_inline(line)

                # Adjust token positions to be relative to remaining_chars
                # by offsetting them based on block_start
                if typewriter_pos != float('inf'):
                    # Create adjusted tokens with positions relative to absolute typewriter position
                    for token in tokens:
                        token['start'] = token.get('start', 0) + block_start
                        token['end'] = token.get('end', 0) + block_start
                        token['content_start'] = token.get('content_start', token['start']) + block_start
                        token['content_end'] = token.get('content_end', token['end']) + block_start

                current_y = self._render_tokens(draw, tokens, x, current_y, width)

        return current_y

    def _render_code_block(self, draw, canvas, block: Dict, x: int, y: int, width: int) -> int:
        code = block['code']
        lang = block.get('lang', '')
        block_start = block.get('start', 0)
        font = self.fonts.get('code', self.fonts['normal'])

        line_h = 18
        padding = 12
        header_h = 24 if lang else 0
        code_width = width - padding * 2  # Available width for code text

        # Wrap long lines to fit within code block
        original_lines = code.split('\n')
        wrapped_lines = []
        for line in original_lines:
            if line:
                # Wrap the line if it's too long
                wrapped = self._wrap_code_line(line, font, code_width)
                wrapped_lines.extend(wrapped)
            else:
                wrapped_lines.append('')

        # Calculate typewriter position relative to code content
        # Code content starts after opening ``` line (includes lang if present)
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))
        # Estimate where actual code content starts (after ```lang\n)
        code_content_start = block_start + 3 + len(lang) + 1  # ``` + lang + \n

        # First pass: count visible lines
        chars_shown = 0
        visible_lines = 0
        for line in wrapped_lines:
            line_start_in_code = chars_shown
            if typewriter_pos != float('inf'):
                relative_pos = typewriter_pos - code_content_start
                if line_start_in_code >= relative_pos:
                    break
            visible_lines += 1
            chars_shown += len(line) + 1

        # If no lines visible yet, check if we should show the header at least
        show_header = lang and (typewriter_pos == float('inf') or typewriter_pos > block_start + 3)

        if visible_lines == 0 and not show_header:
            return y  # Nothing to show yet

        # Calculate height based on visible content
        visible_content_h = max(1, visible_lines) * line_h + padding * 2
        total_h = header_h + visible_content_h

        # Modern dark background with subtle gradient effect
        bg_color = (22, 27, 34, 250)
        border_color = (48, 54, 61)

        # Main background (fill only)
        draw.rounded_rectangle([x, y, x + width, y + total_h], radius=10, fill=bg_color)

        # Language header bar
        code_y = y + padding
        if show_header:
            header_bg = (30, 36, 44)
            # Header background
            draw.rounded_rectangle([x, y, x + width, y + header_h], radius=10, fill=header_bg)
            draw.rectangle([x, y + 10, x + width, y + header_h], fill=header_bg)

            # Language tag (text only)
            lang_text = lang.upper()
            # Draw text directly in accent color
            draw.text((x + 12, y + 4), lang_text, fill=self.colors['accent'], font=font)

            code_y = y + header_h + 8

        # Draw border on top
        draw.rounded_rectangle([x, y, x + width, y + total_h], radius=10, fill=None, outline=border_color, width=1)

        # Second pass: draw visible code lines
        chars_shown = 0
        for line in wrapped_lines:
            # Calculate visibility based on typewriter position
            line_start_in_code = chars_shown
            line_end_in_code = chars_shown + len(line)

            # Check if this line should be visible
            if typewriter_pos != float('inf'):
                relative_pos = typewriter_pos - code_content_start
                if line_start_in_code >= relative_pos:
                    break  # Haven't reached this line yet

            # Simple keyword highlighting
            if any(kw in line for kw in ['def ', 'class ', 'import ', 'from ', 'return ', 'if ', 'else:', 'for ', 'while ']):
                color = (255, 123, 114)  # Red for keywords
            elif line.strip().startswith('#') or line.strip().startswith('//'):
                color = (139, 148, 158)  # Gray for comments
            elif '"' in line or "'" in line:
                color = (165, 214, 255)  # Light blue for strings
            else:
                color = self.colors['accent']

            display_line = line
            if typewriter_pos != float('inf'):
                relative_pos = typewriter_pos - code_content_start
                visible_in_line = relative_pos - line_start_in_code
                if visible_in_line < len(line):
                    display_line = line[:max(0, int(visible_in_line))]

            # Render line with emoji support
            self._render_code_line_with_emoji(draw, display_line, x + padding, code_y, color, font)
            code_y += line_h
            chars_shown += len(line) + 1  # +1 for newline

        return y + total_h + 12

    def _render_text_with_emoji(self, draw, text: str, x: int, y: int, color: Tuple, font, emoji_y_offset: int = 5):
        """Render text with inline emoji support for titles and labels.

        Args:
            draw: ImageDraw object
            text: Text to render (may contain emojis)
            x: X position
            y: Y position
            color: Text color (RGBA tuple)
            font: Font to use for text
            emoji_y_offset: Vertical offset for emojis (default 5 for bold titles)
        """
        if not text:
            return

        current_x = x
        i = 0
        emoji_font = self.fonts.get('emoji', font)

        while i < len(text):
            # Check for emoji at current position
            emoji_len = self._get_emoji_length(text, i)
            if emoji_len > 0:
                # Render emoji with emoji font and color support
                emoji_text = text[i:i+emoji_len]
                if self.color_emojis:
                    draw.text((current_x, y + emoji_y_offset), emoji_text, fill=color, font=emoji_font, embedded_color=True)
                else:
                    draw.text((current_x, y + emoji_y_offset), emoji_text, fill=color, font=emoji_font)
                emoji_w, _ = self._get_text_size(emoji_text, emoji_font)
                # Reduce emoji width - more aggressive for variation selector emojis
                has_variation_selector = '\ufe0f' in emoji_text
                if has_variation_selector:
                    current_x += int(emoji_w * 0.55)
                else:
                    current_x += int(emoji_w * 0.85)
                i += emoji_len
            else:
                # Find the next emoji or end of text
                text_start = i
                while i < len(text) and self._get_emoji_length(text, i) == 0:
                    i += 1
                # Render text segment
                text_segment = text[text_start:i]
                if text_segment:
                    draw.text((current_x, y), text_segment, fill=color, font=font)
                    text_w, _ = self._get_text_size(text_segment, font)
                    current_x += text_w

    def _render_code_line_with_emoji(self, draw, line: str, x: int, y: int, color: Tuple, font, emoji_y_offset: int = 0, emoji_x_offset: int = 0):
        """Render a code line with emoji support.

        Args:
            emoji_y_offset: Vertical offset for emojis (default 0 for code, use 7 for normal text)
            emoji_x_offset: Horizontal offset for emojis (default 0, use negative to move left)
        """
        if not line:
            return

        current_x = x
        i = 0
        emoji_font = self.fonts.get('emoji', font)

        while i < len(line):
            # Check for emoji at current position
            emoji_len = self._get_emoji_length(line, i)
            if emoji_len > 0:
                # Render emoji with emoji font and color support
                emoji_text = line[i:i+emoji_len]
                if self.color_emojis:
                    draw.text((current_x + emoji_x_offset, y + emoji_y_offset), emoji_text, fill=color, font=emoji_font, embedded_color=True)
                else:
                    draw.text((current_x + emoji_x_offset, y + emoji_y_offset), emoji_text, fill=color, font=emoji_font)
                emoji_w, _ = self._get_text_size(emoji_text, emoji_font)
                # Reduce emoji width - more aggressive for variation selector emojis
                has_variation_selector = '\ufe0f' in emoji_text
                if has_variation_selector:
                    current_x += int(emoji_w * 0.55)
                else:
                    current_x += int(emoji_w * 0.85)
                i += emoji_len
            else:
                # Find the next emoji or end of line
                text_start = i
                while i < len(line) and self._get_emoji_length(line, i) == 0:
                    i += 1
                # Render text segment
                text_segment = line[text_start:i]
                if text_segment:
                    draw.text((current_x, y), text_segment, fill=color, font=font)
                    text_w, _ = self._get_text_size(text_segment, font)
                    current_x += text_w

    def _wrap_code_line(self, line: str, font, max_width: int) -> List[str]:
        """Wrap a code line to fit within max_width, breaking at character boundaries."""
        if not line:
            return ['']

        w, _ = self._get_text_size(line, font)
        if w <= max_width:
            return [line]

        # Need to wrap - break at character boundaries
        wrapped = []
        current = ''
        for char in line:
            test = current + char
            tw, _ = self._get_text_size(test, font)
            if tw > max_width and current:
                wrapped.append(current)
                current = '  ' + char  # Indent continuation lines
            else:
                current = test

        if current:
            wrapped.append(current)

        return wrapped if wrapped else ['']

    def _wrap_inline_code(self, text: str, font, max_width: int) -> List[str]:
        """Wrap inline code text to fit within max_width, breaking at character boundaries."""
        if not text:
            return ['']

        w, _ = self._get_text_size(text, font)
        if w <= max_width:
            return [text]

        # Need to wrap - break at character boundaries (no indent for inline code)
        wrapped = []
        current = ''
        for char in text:
            test = current + char
            tw, _ = self._get_text_size(test, font)
            if tw > max_width and current:
                wrapped.append(current)
                current = char  # No indent for inline code continuation
            else:
                current = test

        if current:
            wrapped.append(current)

        return wrapped if wrapped else ['']

    def _render_blockquote(self, draw, canvas, block: Dict, x: int, y: int, width: int) -> int:
        """Render a blockquote with typewriter support and full markdown/emoji rendering."""
        text = block.get('text', '') if isinstance(block, dict) else block
        block_start = block.get('start', 0) if isinstance(block, dict) else 0

        # Add small top margin before blockquote
        y += 4

        border_w = 4
        content_x = x + border_w + 12
        content_w = width - border_w - 16

        # Calculate typewriter position relative to blockquote content
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))
        # Content starts after "> " (2 chars)
        content_start = block_start + 2

        # Tokenize the blockquote content for proper markdown/emoji rendering
        tokens = self.tokenize_inline(text)

        # Adjust token positions to be absolute
        for token in tokens:
            token['start'] = token.get('start', 0) + content_start
            token['end'] = token.get('end', 0) + content_start
            token['content_start'] = token.get('content_start', token['start'])
            token['content_end'] = token.get('content_end', token['end'])

        # Calculate visible characters for typewriter
        max_chars = None
        if typewriter_pos != float('inf'):
            max_chars = max(0, typewriter_pos - content_start)
            if max_chars <= 0:
                return y - 4  # Nothing visible yet

        # First, estimate the height by doing a dry run
        # We'll use a simple line-based estimate
        font = self.fonts.get('italic', self.fonts['normal'])
        lines = self._wrap_text(text, font, content_w)
        line_h = self.line_height

        # Calculate how much text is visible
        if max_chars is not None:
            chars_shown = 0
            visible_lines = 0
            for line in lines:
                if chars_shown >= max_chars:
                    break
                visible_lines += 1
                chars_shown += len(line) + 1
            visible_h = max(1, visible_lines) * line_h + 12
        else:
            visible_h = len(lines) * line_h + 12

        # Draw accent border on left
        accent = self.colors['accent']
        draw.rectangle([x, y, x + border_w, y + visible_h], fill=accent)

        # Subtle background
        bg = (40, 46, 56, 180)
        draw.rounded_rectangle([x + border_w, y, x + width, y + visible_h], radius=6, fill=bg)

        # Render the blockquote content with full markdown support
        quote_color = (180, 186, 196)
        text_y = y + 6

        # Use _render_tokens for proper markdown/emoji rendering
        final_y = self._render_tokens(
            draw, tokens, content_x, text_y, content_w,
            override_color=quote_color,
            override_font=font,
            max_chars=max_chars
        )

        return y + visible_h + 10

    def _render_hr(self, draw, x: int, y: int, width: int) -> int:
        hr_y = y + 12
        # Simple horizontal line with accent color
        accent = self.colors['accent']

        # Draw the main line
        line_start_x = x
        line_end_x = x + width
        draw.line([(line_start_x, hr_y), (line_end_x, hr_y)], fill=(60, 66, 78), width=1)

        # Decorative dots at the ends and center
        dot_positions = [line_start_x, x + width // 2, line_end_x]
        for dot_x in dot_positions:
            draw.ellipse([dot_x - 2, hr_y - 2, dot_x + 2, hr_y + 2], fill=accent)

        return y + 24

    def _render_footnote_def(self, draw, block: Dict, x: int, y: int, width: int) -> int:
        """Render a footnote definition block."""
        fn_id = block.get('id', '?')
        fn_text = block.get('text', '')
        block_start = block.get('start', 0)

        font = self.fonts.get('normal', self.fonts['normal'])
        small_font = self.fonts.get('code', font)

        # Footnote styling - smaller, with left border accent
        border_w = 3
        padding = 8

        # Get typewriter position
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))

        # Calculate content start (after "[^id]: ")
        content_start = block_start + len(f'[^{fn_id}]: ')

        # Skip if typewriter hasn't reached this block yet
        if typewriter_pos != float('inf') and block_start >= typewriter_pos:
            return y

        # Draw accent border on left
        accent = self.colors['accent']

        # Calculate text area
        text_x = x + border_w + padding
        text_width = width - border_w - padding * 2

        # Prepare footnote label
        label = f'[{fn_id}]'
        label_w, label_h = self._get_text_size(label, small_font)

        # Wrap footnote text
        lines = self._wrap_text(fn_text, font, text_width - label_w - 6)
        line_h = self.line_height - 4  # Slightly smaller line height for footnotes

        # Calculate total height
        total_h = max(len(lines) * line_h, label_h) + padding

        # Draw background and border
        bg_color = (35, 40, 50, 200)
        draw.rounded_rectangle([x, y, x + width, y + total_h], radius=4, fill=bg_color)
        draw.rectangle([x, y, x + border_w, y + total_h], fill=accent)

        # Draw footnote label (moved down by 7px)
        label_y = y + padding // 2 + 7
        draw.text((text_x, label_y), label, fill=accent, font=small_font)

        # Draw footnote text (also moved down to align)
        text_start_x = text_x + label_w + 6
        text_y = y + padding // 2 + 7

        fn_color = (170, 176, 186)  # Slightly dimmed text for footnotes

        for i, line in enumerate(lines):
            # Calculate visible portion based on typewriter
            display_line = line
            if typewriter_pos != float('inf'):
                chars_before = sum(len(lines[j]) + 1 for j in range(i))
                relative_pos = typewriter_pos - content_start
                if chars_before >= relative_pos:
                    break
                visible_in_line = relative_pos - chars_before
                if visible_in_line < len(line):
                    display_line = line[:max(0, int(visible_in_line))]

            if i == 0:
                draw.text((text_start_x, text_y), display_line, fill=fn_color, font=font)
            else:
                draw.text((text_x, text_y), display_line, fill=fn_color, font=font)
            text_y += line_h

        return y + total_h + 6

    def _render_table(self, draw, block: Dict, x: int, y: int, width: int) -> int:
        """Render a table with typewriter support."""
        lines = block.get('lines', []) if isinstance(block, dict) else block
        block_start = block.get('start', 0) if isinstance(block, dict) else 0

        if len(lines) < 2:
            return y

        font = self.fonts['normal']
        bold_font = self.fonts.get('bold', font)
        line_h = self.line_height - 4

        # Parse rows (skip separator lines)
        rows = []
        row_line_indices = []  # Track which original line each row came from
        for li, line in enumerate(lines):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if cells and not all(re.match(r'^[-:]+$', c.strip()) for c in cells if c.strip()):
                rows.append(cells)
                row_line_indices.append(li)

        if not rows:
            return y

        num_cols = max(len(r) for r in rows) if rows else 0
        if num_cols == 0:
            return y

        # Calculate column widths - table uses full width like code blocks
        cell_padding = 6
        table_w = width  # Match code block width
        col_width = max(40, table_w // num_cols)
        col_widths = [col_width] * num_cols
        # Adjust last column to fill remaining space
        col_widths[-1] = table_w - sum(col_widths[:-1])

        # Calculate row heights (need to pre-calculate for proper backgrounds)
        row_heights = []
        for ri, row in enumerate(rows):
            current_font = bold_font if ri == 0 else font
            max_lines = 1
            for ci in range(num_cols):
                cell_text = row[ci].strip() if ci < len(row) else ''
                cell_w = col_widths[ci] - cell_padding * 2
                num_lines = self._count_wrapped_lines_breaking(cell_text, current_font, cell_w)
                max_lines = max(max_lines, num_lines)
            row_heights.append(max_lines * (line_h + 6) + 10)

        current_y = y

        # Calculate typewriter position and row positions
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))

        # Calculate cumulative position of each row in the original text
        row_positions = []
        pos = block_start
        for li, line in enumerate(lines):
            row_positions.append(pos)
            pos += len(line) + 1  # +1 for newline

        # Track visible rows for proper border drawing
        visible_rows = 0
        last_visible_y = y

        # Draw table rows
        for ri, row in enumerate(rows):
            # Get this row's position in original text
            orig_line_idx = row_line_indices[ri]
            row_start_pos = row_positions[orig_line_idx] if orig_line_idx < len(row_positions) else block_start

            # Skip this row if typewriter hasn't reached it yet
            if typewriter_pos != float('inf') and row_start_pos >= typewriter_pos:
                break

            visible_rows += 1
            row_h = row_heights[ri]
            is_header = (ri == 0)
            current_font = bold_font if is_header else font
            text_color = self.colors['accent'] if is_header else self.colors['text']

            # Row background
            bg = (45, 52, 64) if is_header else ((32, 38, 48) if ri % 2 == 1 else (38, 44, 54))

            # Draw row background
            if ri == 0:
                draw.rounded_rectangle([x, current_y, x + table_w, current_y + row_h], radius=8, fill=bg)
                draw.rectangle([x, current_y + row_h - 8, x + table_w, current_y + row_h], fill=bg)
            else:
                # Check if this is the last visible row
                next_row_visible = False
                if ri + 1 < len(rows):
                    next_orig_idx = row_line_indices[ri + 1]
                    next_row_pos = row_positions[next_orig_idx] if next_orig_idx < len(row_positions) else float('inf')
                    next_row_visible = (typewriter_pos == float('inf') or next_row_pos < typewriter_pos)

                if not next_row_visible or ri == len(rows) - 1:
                    # This is the last visible row - use rounded bottom
                    draw.rounded_rectangle([x, current_y, x + table_w, current_y + row_h], radius=8, fill=bg)
                    draw.rectangle([x, current_y, x + table_w, current_y + 8], fill=bg)
                else:
                    draw.rectangle([x, current_y, x + table_w, current_y + row_h], fill=bg)

            # Draw cells with typewriter support
            cell_x = x
            for ci in range(num_cols):
                cell_text = row[ci].strip() if ci < len(row) else ''
                cell_w = col_widths[ci]
                content_w = cell_w - cell_padding * 2

                # Calculate cell position in original text for typewriter
                # Approximate: row_start + position within row
                cell_start_approx = row_start_pos + sum(len(row[j]) + 1 for j in range(ci) if j < len(row))

                # Render cell with typewriter effect
                self._render_cell_content_with_pos(
                    draw, cell_text, cell_x + cell_padding, current_y + 5,
                    content_w, line_h + 6, current_font, text_color,
                    cell_start_approx, typewriter_pos
                )

                # Column separator
                if ci < num_cols - 1:
                    sep_x = cell_x + cell_w
                    draw.line([(sep_x, current_y + 4), (sep_x, current_y + row_h - 4)],
                             fill=(55, 62, 74), width=1)

                cell_x += cell_w

            last_visible_y = current_y + row_h
            current_y += row_h

        # Outer border (only around visible portion)
        if visible_rows > 0:
            draw.rounded_rectangle([x, y, x + table_w, last_visible_y], radius=8, outline=(55, 62, 74), width=1)

        return last_visible_y + 10 if visible_rows > 0 else y

    def _render_cell_content_with_pos(self, draw, text: str, x: int, y: int, max_width: int,
                                      line_h: int, base_font, base_color: Tuple,
                                      cell_start_pos: int, typewriter_pos: float):
        """Render cell content with position-based typewriter effect."""
        if not text:
            return

        # Skip if typewriter hasn't reached this cell
        if typewriter_pos != float('inf') and cell_start_pos >= typewriter_pos:
            return

        tokens = self.tokenize_inline(text)
        render_x = x
        render_y = y

        # Adjust token positions to absolute
        for token in tokens:
            token['start'] = token.get('start', 0) + cell_start_pos
            token['end'] = token.get('end', 0) + cell_start_pos
            token['content_start'] = token.get('content_start', token['start']) + cell_start_pos
            token['content_end'] = token.get('content_end', token['end']) + cell_start_pos

        for token in tokens:
            token_start = token.get('start', 0)
            content_start = token.get('content_start', token_start)
            content_end = token.get('content_end', token.get('end', token_start))

            # Skip tokens not yet reached
            if typewriter_pos != float('inf') and token_start >= typewriter_pos:
                break

            ttype = token['type']

            # Get font and color
            if ttype == 'bold':
                tfont = self.fonts.get('bold', base_font)
                tcolor = base_color
            elif ttype == 'italic':
                tfont = self.fonts.get('italic', base_font)
                tcolor = base_color
            elif ttype == 'bold_italic':
                tfont = self.fonts.get('bold_italic', base_font)
                tcolor = base_color
            elif ttype == 'code':
                tfont = self.fonts.get('code', base_font)
                tcolor = self.colors['accent']
            elif ttype == 'strike':
                tfont = base_font
                tcolor = (110, 118, 129)
            elif ttype in ('link', 'image'):
                tfont = base_font
                tcolor = self.colors['accent']
            elif ttype == 'emoji':
                tfont = self.fonts.get('emoji', self.fonts['normal'])
                tcolor = base_color
            else:
                tfont = base_font
                tcolor = base_color

            is_code = (ttype == 'code')
            is_strike = (ttype == 'strike')

            # Get display text
            if ttype == 'link':
                display_text = token.get('text', '')
            elif ttype == 'image':
                display_text = token.get('alt', 'img')
            elif ttype == 'checkbox':
                display_text = '\u2611' if token.get('checked') else '\u2610'  # ☑ ☐
            else:
                display_text = token.get('text', '')

            # Check if this token has sub-tokens (e.g., bold with emojis inside)
            sub_tokens = token.get('sub_tokens')
            if sub_tokens and ttype == 'bold':
                # Render sub-tokens with bold font for text and emoji font for emojis
                bold_font = tfont
                emoji_font = self.fonts.get('emoji', base_font)
                space_w, _ = self._get_text_size(' ', bold_font)

                for sub_idx, sub_token in enumerate(sub_tokens):
                    sub_type = sub_token.get('type')
                    sub_text = sub_token.get('text', '')

                    if not sub_text:
                        continue

                    # Choose font based on sub-token type
                    if sub_type == 'emoji':
                        sub_font = emoji_font
                        is_emoji_token = True
                    else:
                        sub_font = bold_font
                        is_emoji_token = False

                    # Render word by word
                    words = sub_text.split(' ')
                    for i, word in enumerate(words):
                        if not word and i > 0:
                            render_x += space_w
                            continue

                        # Handle space before word
                        if i > 0:
                            if render_x + space_w > x + max_width and render_x > x:
                                render_y += line_h + 4
                                render_x = x
                            else:
                                render_x += space_w

                        word_w, word_h = self._get_text_size(word, sub_font)

                        # Check if word fits on current line
                        if render_x + word_w > x + max_width and render_x > x:
                            render_y += line_h + 4
                            render_x = x

                        # Draw word with emoji support
                        emoji_y_offset = 7 if is_emoji_token else 0
                        if is_emoji_token and self.color_emojis:
                            draw.text((render_x, render_y + emoji_y_offset), word, fill=tcolor, font=sub_font, embedded_color=True)
                        else:
                            draw.text((render_x, render_y), word, fill=tcolor, font=sub_font)

                        render_x += word_w

                        # Add automatic space after emoji if next sub-token is text and doesn't start with space
                        if is_emoji_token and sub_idx + 1 < len(sub_tokens):
                            next_token = sub_tokens[sub_idx + 1]
                            next_text = next_token.get('text', '')
                            if next_token.get('type') == 'text' and next_text and not next_text.startswith(' '):
                                render_x += space_w

                continue  # Skip the normal rendering below

            # Normal rendering for tokens without sub-tokens

            # Calculate visible portion
            visible_chars = len(display_text)
            if typewriter_pos != float('inf'):
                if typewriter_pos <= content_start:
                    visible_chars = 0
                elif typewriter_pos >= content_end:
                    visible_chars = len(display_text)
                else:
                    content_len = content_end - content_start
                    if content_len > 0:
                        pos_in_content = typewriter_pos - content_start
                        visible_chars = int(pos_in_content * len(display_text) / content_len)

            if visible_chars <= 0:
                continue

            visible_text = display_text[:visible_chars]

            # Render word by word for proper wrapping
            words = visible_text.split(' ')
            space_w, _ = self._get_text_size(' ', tfont)

            for i, word in enumerate(words):
                if not word and i > 0:
                    render_x += space_w
                    continue

                # Handle space before word
                if i > 0:
                    if render_x + space_w > x + max_width and render_x > x:
                        render_y += line_h + 4
                        render_x = x
                    else:
                        render_x += space_w

                word_w, word_h = self._get_text_size(word, tfont)

                # Check if word fits on current line
                if render_x + word_w > x + max_width and render_x > x:
                    render_y += line_h + 4
                    render_x = x

                # Draw code background
                if is_code and word.strip():
                    draw.rounded_rectangle(
                        [render_x - 1, render_y - 1, render_x + word_w + 1, render_y + word_h + 1],
                        radius=2, fill=(40, 46, 56, 200)
                    )

                # Draw word (use embedded_color for colored emoji rendering)
                # Emojis need vertical offset to align with text baseline
                is_emoji = (ttype == 'emoji')
                emoji_y_offset = 7 if is_emoji else 0
                if is_emoji and self.color_emojis:
                    draw.text((render_x, render_y + emoji_y_offset), word, fill=tcolor, font=tfont, embedded_color=True)
                else:
                    draw.text((render_x, render_y), word, fill=tcolor, font=tfont)

                # Strikethrough
                if is_strike:
                    sy = render_y + word_h // 2
                    draw.line([(render_x, sy), (render_x + word_w, sy)], fill=tcolor, width=1)

                render_x += word_w

                # Add automatic space after emoji to maintain consistent spacing
                # Only if this is the last word in the emoji token and there are more tokens to render
                if is_emoji and i == len(words) - 1:
                    # Check if there's a next token that's not whitespace-only
                    token_idx = tokens.index(token) if token in tokens else -1
                    if token_idx >= 0 and token_idx + 1 < len(tokens):
                        next_token = tokens[token_idx + 1]
                        next_text = next_token.get('text', '')
                        # Add space only if next token is not already whitespace-only
                        if next_text and not next_text.isspace():
                            render_x += space_w

    def _count_wrapped_lines_breaking(self, text: str, font, max_width: int) -> int:
        """Count lines needed when breaking mid-word is allowed but word-wrap is preferred."""
        if not text or max_width <= 0:
            return 1

        # Strip markdown for sizing
        plain = re.sub(r'\*{1,3}|`|~~|\[.*?]\(.*?\)|!\[.*?]\(.*?\)', '', text)

        lines = 1
        current_width = 0
        space_width, _ = self._get_text_size(' ', font)

        words = plain.split(' ')

        for i, word in enumerate(words):
            word_w, _ = self._get_text_size(word, font)

            # Handle space before word
            if i > 0:
                if current_width + space_width > max_width and current_width > 0:
                    lines += 1
                    current_width = 0
                else:
                    current_width += space_width

            # Handle word
            if current_width + word_w > max_width and current_width > 0:
                lines += 1
                current_width = 0

            if word_w > max_width:
                # Word is too long, must break it
                for char in word:
                    char_w, _ = self._get_text_size(char, font)
                    if current_width + char_w > max_width:
                        lines += 1
                        current_width = char_w
                    else:
                        current_width += char_w
            else:
                current_width += word_w

        return max(1, lines)

    def _calculate_wrapped_lines(self, text: str, font, max_width: int) -> int:
        """Calculate how many lines the text will need when wrapped to max_width."""
        if not text or max_width <= 0:
            return 1

        # Strip markdown syntax for width calculation
        plain_text = re.sub(r'\*{1,3}|`|~~|\[.*?]\(.*?\)|!\[.*?]\(.*?\)', '', text)

        words = plain_text.split()
        if not words:
            return 1

        lines = 1
        current_width = 0
        space_width, _ = self._get_text_size(' ', font)

        for word in words:
            word_width, _ = self._get_text_size(word, font)

            if current_width == 0:
                current_width = word_width
            elif current_width + space_width + word_width <= max_width:
                current_width += space_width + word_width
            else:
                lines += 1
                current_width = word_width

        return max(1, lines)

    def _render_ul(self, draw, canvas, block: Dict, x: int, y: int, width: int) -> int:
        """Render unordered list with typewriter support."""
        items = block.get('items', []) if isinstance(block, dict) else block
        block_start = block.get('start', 0) if isinstance(block, dict) else 0

        current_y = y
        bullets = ['\u2022', '\u25E6', '\u25AA', '\u2023']  # • ◦ ▪ ‣

        # Track position within block for typewriter
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))
        item_offset = 0  # Track cumulative offset within block

        for item in items:
            indent = item.get('indent', 0)
            text = item['text']

            # Calculate item start position in original text
            # Format: "- text\n" or "  - text\n" for indented
            item_start = block_start + item_offset
            item_marker_end = item_start + 2 + (indent * 2)  # "- " or "  - " etc.

            # Skip this item entirely if typewriter hasn't reached it yet
            if typewriter_pos != float('inf') and item_start >= typewriter_pos:
                break

            indent_px = indent * 20
            bullet = bullets[min(indent, len(bullets) - 1)]
            bullet_x = x + indent_px
            text_x = bullet_x + 16

            # Only draw bullet if typewriter has reached at least the marker
            if typewriter_pos == float('inf') or typewriter_pos > item_start:
                bullet_font = self.fonts.get('bold', self.fonts['normal'])
                draw.text((bullet_x, current_y), bullet, fill=self.colors['accent'], font=bullet_font)

            # Text with inline formatting
            tokens = self.tokenize_inline(text)

            # Adjust token positions to be absolute (relative to item_marker_end)
            if typewriter_pos != float('inf'):
                for token in tokens:
                    token['start'] = token.get('start', 0) + item_marker_end
                    token['end'] = token.get('end', 0) + item_marker_end
                    token['content_start'] = token.get('content_start', token['start']) + item_marker_end
                    token['content_end'] = token.get('content_end', token['end']) + item_marker_end

            # Update offset for next item: "- " (2) + text + "\n" (1)
            item_offset += 2 + (indent * 2) + len(text) + 1

            current_y = self._render_tokens(draw, tokens, text_x, current_y, width - (text_x - x))

        return current_y + 2

    def _render_ol(self, draw, canvas, block: Dict, x: int, y: int, width: int) -> int:
        """Render ordered list with typewriter support."""
        items = block.get('items', []) if isinstance(block, dict) else block
        block_start = block.get('start', 0) if isinstance(block, dict) else 0

        current_y = y

        # Track position within block for typewriter
        typewriter_pos = getattr(self, 'remaining_chars', float('inf'))
        item_offset = 0

        for item in items:
            indent = item.get('indent', 0)
            num = item.get('num', '1')
            text = item['text']

            # Styled number
            num_text = num
            if not num_text.endswith('.'):
                num_text += '.'

            # Calculate item start position in original text
            # Format: "1. text\n" or "   1. text\n" for indented
            item_start = block_start + item_offset
            item_marker_end = item_start + len(num_text) + 1 + (indent * 3)  # "1. " + indent

            # Skip this item entirely if typewriter hasn't reached it yet
            if typewriter_pos != float('inf') and item_start >= typewriter_pos:
                break

            indent_px = indent * 20
            num_x = x + indent_px

            num_font = self.fonts.get('bold', self.fonts['normal'])
            nw, nh = self._get_text_size(num_text, num_font)

            # Only draw number if typewriter has reached at least the marker
            if typewriter_pos == float('inf') or typewriter_pos > item_start:
                draw.text((num_x, current_y), num_text, fill=self.colors['accent'], font=num_font)

            text_x = num_x + nw + 8

            # Text with inline formatting
            tokens = self.tokenize_inline(text)

            # Adjust token positions to be absolute
            if typewriter_pos != float('inf'):
                for token in tokens:
                    token['start'] = token.get('start', 0) + item_marker_end
                    token['end'] = token.get('end', 0) + item_marker_end
                    token['content_start'] = token.get('content_start', token['start']) + item_marker_end
                    token['content_end'] = token.get('content_end', token['end']) + item_marker_end

            # Update offset for next item: "1. " + text + "\n"
            item_offset += len(num_text) + 1 + (indent * 3) + len(text) + 1

            current_y = self._render_tokens(draw, tokens, text_x, current_y, width - (text_x - x))

        return current_y + 2

    def _render_tokens(self, draw, tokens: List[Dict], x: int, y: int, width: int,
                       override_color: Tuple = None, override_font = None, max_chars: int = None,
                       header_level: int = None) -> int:
        """Render inline tokens with word wrapping and styling.

        The typewriter effect uses 'remaining_chars' as a position in the ORIGINAL text.
        Each token has 'start', 'end', 'content_start', and 'content_end' positions that
        map to the original text, allowing correct character-by-character reveal even
        with markdown syntax characters.

        Args:
            max_chars: If provided, limits the number of visible characters (overrides remaining_chars)
            header_level: If provided (1-6), uses appropriately sized emoji font for headers
        """
        current_x = x
        current_y = y

        # Get actual line height from font metrics
        base_font = override_font if override_font else self.fonts['normal']
        _, base_h = self._get_text_size('Ay', base_font)  # Use 'Ay' to get proper ascender/descender height
        line_h = base_h

        # Get the typewriter limit (position in original text)
        # Use max_chars if provided, otherwise use remaining_chars
        if max_chars is not None:
            typewriter_pos = max_chars
        else:
            typewriter_pos = getattr(self, 'remaining_chars', float('inf'))

        for token in tokens:
            # Get token positions in original text
            token_start = token.get('start', 0)
            token_end = token.get('end', token_start + len(token.get('text', '')))
            content_start = token.get('content_start', token_start)
            content_end = token.get('content_end', token_end)

            # Skip tokens that haven't been reached yet by typewriter
            if typewriter_pos != float('inf') and token_start >= typewriter_pos:
                break

            ttype = token['type']

            # Determine font - emoji always uses emoji font regardless of override
            # Use header-sized emoji font when rendering in headers
            if ttype == 'emoji':
                if header_level and header_level in range(1, 7):
                    emoji_font_key = f'emoji_h{header_level}'
                    font = self.fonts.get(emoji_font_key, self.fonts.get('emoji', self.fonts['normal']))
                else:
                    font = self.fonts.get('emoji', self.fonts['normal'])
            elif override_font:
                font = override_font
            elif ttype == 'bold':
                font = self.fonts.get('bold', self.fonts['normal'])
            elif ttype == 'italic':
                font = self.fonts.get('italic', self.fonts['normal'])
            elif ttype == 'bold_italic':
                font = self.fonts.get('bold_italic', self.fonts['normal'])
            elif ttype == 'code':
                font = self.fonts.get('code', self.fonts['normal'])
            else:
                font = self.fonts['normal']

            # Determine color
            if override_color:
                color = override_color
            elif ttype == 'code':
                color = self.colors['accent']
            elif ttype in ('link', 'image'):
                color = self.colors['accent']
            elif ttype == 'strike':
                color = (140, 148, 160)
            elif ttype == 'math':
                color = (255, 203, 107)
            else:
                color = self.colors['text']

            # Get display text - links show only the title, not the URL
            if ttype == 'link':
                text = token['text']  # Just the link title, no emoji or URL
            elif ttype == 'image':
                # Try to load and render the actual image
                image_url = token.get('url', '')
                alt_text = token.get('alt', 'image')
                max_img_width = width - 10  # Leave some margin

                # Try to load the image
                loaded_img = self._load_image(image_url, max_img_width) if image_url else None

                if loaded_img is not None:
                    # Successfully loaded image - render it
                    img_width, img_height = loaded_img.size

                    # Check if image fits on current line, if not move to next line
                    if current_x > x and current_x + img_width > x + width:
                        current_y += line_h + 10
                        current_x = x

                    # We need access to the canvas to paste the image
                    # The 'draw' object has a reference to the image via draw._image (internal)
                    # or we can use the canvas passed to render()
                    try:
                        canvas = draw._image
                        # Paste the image onto the canvas
                        canvas.paste(loaded_img, (int(current_x), int(current_y)), loaded_img)

                        # Update position
                        current_y += img_height + 8
                        current_x = x
                        line_h = base_h  # Reset line height

                        # Optionally show alt text below image if present
                        if alt_text and alt_text != 'image':
                            alt_font = self.fonts.get('italic', self.fonts['normal'])
                            alt_color = (140, 148, 160)  # Gray for caption
                            draw.text((current_x, current_y), alt_text, fill=alt_color, font=alt_font)
                            _, alt_h = self._get_text_size(alt_text, alt_font)
                            current_y += alt_h + 6

                        continue  # Skip normal text rendering
                    except Exception:
                        pass  # Fall back to icon rendering

                # Fallback: render icon with alt text (image couldn't be loaded)
                icon_size = int(base_h * 0.9)
                icon_y = current_y + int((base_h - icon_size) / 2) + 3
                icon_color = self.colors['accent']

                # Draw image frame (rounded rectangle)
                draw.rounded_rectangle(
                    [current_x, icon_y, current_x + icon_size, icon_y + icon_size],
                    radius=2, fill=None, outline=icon_color, width=1
                )

                # Draw mountain/landscape symbol inside (simplified image icon)
                # Bottom triangle (mountain)
                m_left = current_x + icon_size * 0.15
                m_right = current_x + icon_size * 0.85
                m_bottom = icon_y + icon_size * 0.8
                m_peak = icon_y + icon_size * 0.35
                m_mid = current_x + icon_size * 0.5
                draw.polygon(
                    [(m_left, m_bottom), (m_mid, m_peak), (m_right, m_bottom)],
                    fill=icon_color
                )

                # Small sun/circle in top right
                sun_r = icon_size * 0.12
                sun_cx = current_x + icon_size * 0.72
                sun_cy = icon_y + icon_size * 0.28
                draw.ellipse(
                    [sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r],
                    fill=icon_color
                )

                current_x += icon_size + 4

                # Now render the alt text after the icon
                if alt_text:
                    text = alt_text
                    color = self.colors['accent']
                else:
                    continue  # No alt text, just show icon
            elif ttype == 'checkbox':
                # Render custom checkbox graphics instead of font characters
                checkbox_size = int(base_h * 0.95)  # 95% of font height
                checkbox_y = current_y + int((base_h - checkbox_size) / 2) + 4  # Move down

                if token['checked']:
                    # Draw rounded rectangle outline with checkmark (no fill)
                    check_color = self.colors['accent']  # Use configured accent color
                    draw.rounded_rectangle(
                        [current_x, checkbox_y, current_x + checkbox_size, checkbox_y + checkbox_size],
                        radius=3, fill=None, outline=check_color, width=2
                    )
                    # Draw checkmark (two lines forming a check)
                    cx, cy = current_x, checkbox_y
                    # Checkmark points - slightly larger and better positioned
                    p1 = (cx + checkbox_size * 0.18, cy + checkbox_size * 0.5)
                    p2 = (cx + checkbox_size * 0.4, cy + checkbox_size * 0.78)
                    p3 = (cx + checkbox_size * 0.85, cy + checkbox_size * 0.22)
                    draw.line([p1, p2], fill=check_color, width=2)
                    draw.line([p2, p3], fill=check_color, width=2)
                else:
                    # Draw empty rounded rectangle
                    box_color = (140, 148, 160)  # Gray
                    draw.rounded_rectangle(
                        [current_x, checkbox_y, current_x + checkbox_size, checkbox_y + checkbox_size],
                        radius=3, fill=None, outline=box_color, width=1
                    )

                current_x += checkbox_size + 6  # Move past checkbox with spacing
                continue  # Skip normal text rendering for checkbox
            elif ttype == 'footnote_ref':
                # Render footnote reference as superscript number/text in brackets
                fn_id = token.get('id', '?')
                fn_text = f'[{fn_id}]'

                # Use smaller font size for superscript effect
                fn_font = self.fonts.get('code', self.fonts['normal'])
                fn_color = self.colors['accent']

                # Get text size
                fn_w, fn_h = self._get_text_size(fn_text, fn_font)

                # Draw slightly lower (moved down)
                fn_y = current_y + 5

                # Draw the footnote reference
                draw.text((current_x, fn_y), fn_text, fill=fn_color, font=fn_font)

                current_x += fn_w + 2
                continue  # Skip normal text rendering
            elif ttype == 'math':
                text = f"\u222B {token['text']}"  # ∫ integral symbol
            else:
                text = token.get('text', '')

            if not text:
                continue

            # Calculate how much of this token's content should be shown
            # based on typewriter position in original text
            visible_chars = len(text)  # Default: show all
            fading_char_info = None  # (char, alpha) for the character being typed

            if typewriter_pos != float('inf'):
                if typewriter_pos <= content_start:
                    # Typewriter hasn't reached the content yet (might be in opening syntax)
                    visible_chars = 0
                elif typewriter_pos >= content_end:
                    # Entire content is visible
                    visible_chars = len(text)
                else:
                    # Partial content visible
                    # Map typewriter position to content position
                    content_len = content_end - content_start
                    text_len = len(text)

                    if content_len > 0:
                        # Position within content
                        pos_in_content = typewriter_pos - content_start
                        # Scale to text length (handles special tokens like image/checkbox)
                        visible_chars = int(pos_in_content * text_len / content_len)

                        # Calculate fading character
                        fraction = (pos_in_content * text_len / content_len) - visible_chars
                        if fraction > 0 and visible_chars < text_len:
                            fading_char_info = (text[visible_chars], int(fraction * 255))
                    else:
                        visible_chars = 0

            # Skip if nothing to show
            if visible_chars <= 0 and fading_char_info is None:
                continue

            # For inline code, render as single unit (don't split on spaces)
            if ttype == 'code':
                # Add spacing before inline code if not at start of line
                if current_x > x:
                    current_x += 4  # Extra space before code block

                w, h = self._get_text_size(text, font)
                pad_x = 4
                pad_y = 3
                # Align code baseline with surrounding text (move down 7 pixels)
                code_y_offset = 7
                available_width = x + width - current_x - pad_x * 2

                # Check if code fits on current line
                if w <= available_width or current_x == x:
                    # Code fits or we're at start of line - render normally
                    if w > available_width and current_x > x:
                        # Move to next line first
                        current_y += line_h + 10
                        current_x = x
                        available_width = width - pad_x * 2

                    # If still too wide, we need to wrap the code itself
                    if w > available_width:
                        # Wrap inline code at character boundaries
                        code_lines = self._wrap_inline_code(text, font, available_width)
                        chars_consumed = 0
                        for ci, code_line in enumerate(code_lines):
                            # Calculate how much of this line to show
                            line_visible = min(len(code_line), max(0, visible_chars - chars_consumed))
                            if line_visible <= 0:
                                break

                            display_line = code_line[:line_visible]
                            chars_consumed += len(code_line)

                            cw, ch = self._get_text_size(display_line, font)

                            # Draw code background pill - vertically centered with text
                            bg_top = current_y + code_y_offset - pad_y
                            bg_bottom = current_y + ch + code_y_offset + pad_y
                            draw.rounded_rectangle(
                                [current_x - pad_x, bg_top,
                                 current_x + cw + pad_x, bg_bottom],
                                radius=4, fill=(40, 46, 56, 240), outline=(60, 68, 80)
                            )
                            # Draw code text with emoji support (emojis shifted left for inline code)
                            self._render_code_line_with_emoji(draw, display_line, current_x, current_y + code_y_offset, color, font, emoji_x_offset=-4)

                            if ci < len(code_lines) - 1 and line_visible >= len(code_line):
                                # Move to next line for continuation
                                current_y += line_h + 2
                                current_x = x
                            else:
                                current_x += cw + pad_x * 2 + 4

                        line_h = max(line_h, h + pad_y * 2)
                        continue

                    # Normal single-line code rendering
                    display_text = text[:visible_chars] if visible_chars < len(text) else text

                    # Recalculate width for partial text
                    display_w = w
                    if len(display_text) < len(text):
                        display_w, _ = self._get_text_size(display_text, font)

                    # Draw code background pill - vertically centered with text
                    bg_top = current_y + code_y_offset - pad_y
                    bg_bottom = current_y + h + code_y_offset + pad_y
                    draw.rounded_rectangle(
                        [current_x - pad_x, bg_top,
                         current_x + display_w + pad_x, bg_bottom],
                        radius=4, fill=(40, 46, 56, 240), outline=(60, 68, 80)
                    )
                    self._render_code_line_with_emoji(draw, display_text, current_x, current_y + code_y_offset, color, font, emoji_x_offset=-4)

                    # Draw fading character for code
                    if fading_char_info:
                        fade_char, fade_alpha = fading_char_info
                        fade_color = color[:3] + (fade_alpha,) if len(color) >= 3 else color
                        fcw, _ = self._get_text_size(fade_char, font)
                        draw.text((current_x + display_w, current_y + code_y_offset), fade_char, fill=fade_color, font=font)
                        display_w += fcw

                    current_x += display_w + pad_x * 2 + 4
                    line_h = max(line_h, h + pad_y * 2)
                else:
                    # Move to next line and try again
                    current_y += line_h + 10
                    current_x = x
                    available_width = width - pad_x * 2

                    if w > available_width:
                        # Still need to wrap
                        code_lines = self._wrap_inline_code(text, font, available_width)
                        chars_consumed = 0
                        for ci, code_line in enumerate(code_lines):
                            line_visible = min(len(code_line), max(0, visible_chars - chars_consumed))
                            if line_visible <= 0:
                                break

                            display_line = code_line[:line_visible]
                            chars_consumed += len(code_line)

                            cw, ch = self._get_text_size(display_line, font)
                            bg_top = current_y + code_y_offset - pad_y
                            bg_bottom = current_y + ch + code_y_offset + pad_y
                            draw.rounded_rectangle(
                                [current_x - pad_x, bg_top,
                                 current_x + cw + pad_x, bg_bottom],
                                radius=4, fill=(40, 46, 56, 240), outline=(60, 68, 80)
                            )
                            self._render_code_line_with_emoji(draw, display_line, current_x, current_y + code_y_offset, color, font, emoji_x_offset=-4)
                            if ci < len(code_lines) - 1 and line_visible >= len(code_line):
                                current_y += line_h + 2
                                current_x = x
                            else:
                                current_x += cw + pad_x * 2 + 4
                    else:
                        display_text = text[:visible_chars] if visible_chars < len(text) else text
                        display_w = w
                        if len(display_text) < len(text):
                            display_w, _ = self._get_text_size(display_text, font)

                        bg_top = current_y + code_y_offset - pad_y
                        bg_bottom = current_y + h + code_y_offset + pad_y
                        draw.rounded_rectangle(
                            [current_x - pad_x, bg_top,
                             current_x + display_w + pad_x, bg_bottom],
                            radius=4, fill=(40, 46, 56, 240), outline=(60, 68, 80)
                        )
                        self._render_code_line_with_emoji(draw, display_text, current_x, current_y + code_y_offset, color, font, emoji_x_offset=-4)

                        # Draw fading character
                        if fading_char_info:
                            fade_char, fade_alpha = fading_char_info
                            fade_color = color[:3] + (fade_alpha,) if len(color) >= 3 else color
                            fcw, _ = self._get_text_size(fade_char, font)
                            draw.text((current_x + display_w, current_y + code_y_offset), fade_char, fill=fade_color, font=font)
                            display_w += fcw

                        current_x += display_w + pad_x * 2 + 4

                    line_h = max(line_h, h + pad_y * 2)

                continue

            # Word wrap and render for other token types
            # We need to track position within the visible portion of text
            visible_text = text[:visible_chars] if visible_chars < len(text) else text
            words = visible_text.split(' ') if ' ' in visible_text else [visible_text]

            # Check if we need to add a fading character after the last word
            need_fading = fading_char_info is not None

            # For strikethrough, calculate consistent line height based on font
            # Use base_h which is computed from 'Ay' for consistent baseline
            # Position at 70% for lower placement
            strike_y_offset = int(base_h * 0.70)

            # Track start position for continuous strikethrough
            strike_start_x = current_x if ttype == 'strike' else None

            for wi, word in enumerate(words):
                if not word and wi > 0:
                    # Just a space - still advance position (strikethrough will cover it)
                    space_w, _ = self._get_text_size(' ', font)
                    current_x += space_w
                    continue

                # Add space before word if needed
                if wi > 0 and current_x > x:
                    space_w, _ = self._get_text_size(' ', font)
                    current_x += space_w

                # Use emoji font for width calculation if this is an emoji
                width_font = self.fonts.get('emoji', font) if ttype == 'emoji' else font
                w, h = self._get_text_size(word, width_font)
                # Reduce emoji width to avoid extra spacing
                # Emojis with variation selectors (U+FE0F) need more reduction
                if ttype == 'emoji':
                    has_variation_selector = '\ufe0f' in word
                    if has_variation_selector:
                        w = int(w * 0.55)  # Aggressive reduction for variation selector emojis
                    else:
                        w = int(w * 0.85)
                line_h = max(line_h, h)

                # Wrap to next line if needed
                if current_x + w > x + width and current_x > x:
                    # Draw strikethrough for current line before wrapping
                    if ttype == 'strike' and strike_start_x is not None and current_x > strike_start_x:
                        sy = current_y + strike_y_offset
                        strike_color = (160, 168, 180)
                        draw.line([(strike_start_x, sy), (current_x, sy)], fill=strike_color, width=1)

                    current_y += line_h + 10  # Line spacing
                    current_x = x
                    line_h = h

                    # Reset strike start for new line
                    strike_start_x = current_x if ttype == 'strike' else None

                # Draw the word (emojis need vertical offset to align with text baseline)
                # In headlines, emojis also need a left offset to avoid collision with following text
                emoji_y_offset = 7 if ttype == 'emoji' else 0
                emoji_x_offset = -4 if (ttype == 'emoji' and header_level) else 0
                self._draw_text_with_spacing(
                    draw, (current_x + emoji_x_offset, current_y + emoji_y_offset), word, fill=color, font=font,
                    embedded_color=(ttype == 'emoji')
                )
                current_x += w

            # Draw continuous strikethrough line at the end (covers all words and spaces)
            if ttype == 'strike' and strike_start_x is not None and current_x > strike_start_x:
                sy = current_y + strike_y_offset
                strike_color = (160, 168, 180)
                draw.line([(strike_start_x, sy), (current_x, sy)], fill=strike_color, width=1)

            # Draw fading character after all visible words if needed
            if need_fading and fading_char_info:
                fade_char, fade_alpha = fading_char_info

                # Handle space before fading char if the visible text ended with space
                if visible_text and visible_text[-1] == ' ':
                    # The fading char starts a new word after a space
                    pass  # Space already added in loop
                elif visible_chars > 0 and visible_chars < len(text) and text[visible_chars - 1] != ' ' and fade_char != ' ':
                    # Fading char is part of current word, no extra space needed
                    pass
                elif fade_char == ' ':
                    # The fading char is itself a space
                    space_w, _ = self._get_text_size(' ', font)
                    # Render fading space (essentially invisible but we track position)
                    current_x += int(space_w * fade_alpha / 255)
                    # Draw fading strikethrough over the space
                    if ttype == 'strike':
                        sy = current_y + strike_y_offset
                        strike_color = (160, 168, 180, fade_alpha)
                        draw.line([(current_x - int(space_w * fade_alpha / 255), sy), (current_x, sy)], fill=strike_color, width=1)
                    continue

                fade_color = color[:3] + (fade_alpha,) if len(color) >= 3 else color
                fcw, fch = self._get_text_size(fade_char, font)

                # Check if we need to wrap before fading char
                if current_x + fcw > x + width and current_x > x:
                    current_y += line_h + 10
                    current_x = x
                    line_h = fch

                self._draw_text_with_spacing(draw, (current_x, current_y), fade_char, fill=fade_color, font=font)

                # Strikethrough for fading char - extends from current position
                if ttype == 'strike':
                    sy = current_y + strike_y_offset
                    strike_color = (160, 168, 180, fade_alpha)
                    draw.line([(current_x, sy), (current_x + fcw, sy)], fill=strike_color, width=1)


                current_x += fcw

        # Return Y position after the last line of text
        return current_y + line_h + 10


# =============================================================================
# HEADS UP OVERLAY CLASS
# =============================================================================

