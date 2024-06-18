"""Code for handling HTML clipboard data."""

import re
from typing import List
from typing import Optional
from typing import TypeVar


ENCODING = "UTF-8"
HTML_ENCODING = ENCODING


B = TypeVar("B", str, bytes)


class HTMLTemplate:
    """Windows HTML template for storing clipboard HTML data."""

    version = 0.9
    template = """
    Version:{version}
    StartHTML:{start_html_byte}
    EndHTML:{end_html_byte}
    StartFragment:{start_fragment_byte}
    EndFragment:{end_fragment_byte}
    SourceURL:{source_url}
    <html>
    <body>
    <!--StartFragment-->
    {fragment}
    <!--EndFragment-->
    </body>
    </html>
    """
    template = "\n".join(
        [i for i in map(str.strip, template.splitlines()) if i]
    )

    def __init__(self, content: str = ""):
        self.fragments: List[str] = []

        self.start_html: int = -1
        self.end_html: int = -1

        self.start_fragment: int = -1
        self.end_fragment: int = -1

        # Optional
        self.start_selection: Optional[str] = None
        self.end_selection: Optional[str] = None

        # Target Content
        self.content: str = content

    def generate(self) -> str:
        """Generate the HTML template."""
        fragments: List[str] = (
            self.fragments if self.fragments else [self.content]
        )

        # Generate Fragments
        result: str = self._generate_fragments(fragments)
        # Generate HTML
        result = self._generate_html(result)
        # Add Header
        result = self._generate_header(result)
        # Get Byte Counts
        result = self._add_byte_counts(result)

        return result

    @staticmethod
    def _generate_fragments(fragments: List) -> str:
        """Generate the HTML fragments."""
        results: List[str] = []
        for fragment in fragments:
            results.append("<!--StartFragment-->")
            results.append(f"{fragment}")
            results.append("<!--EndFragment-->")

        # Clean
        result: str = "\n".join(results)

        return result

    @staticmethod
    def _generate_html(string: str) -> str:
        """Generate the HTML document."""
        lines = string.splitlines()
        body = ["<body>"] + lines + ["</body>"]
        html = ["<html>"] + body + ["</html>"]

        return "\n".join(html)

    def _generate_header(self, string: str) -> str:
        """Generate the header for the HTML document."""
        lines = string.splitlines()

        version = self.version
        start_html_byte = self.start_html
        end_html_byte = self.end_html
        start_fragment_byte = self.start_fragment
        end_fragment_byte = self.end_fragment
        source_url = None

        if source_url is not None:
            lines.insert(0, f"SourceURL:{source_url}")
        lines.insert(0, f"EndFragment:{end_fragment_byte}")
        lines.insert(0, f"StartFragment:{start_fragment_byte}")
        lines.insert(0, f"EndHTML:{end_html_byte}")
        lines.insert(0, f"StartHTML:{start_html_byte}")
        lines.insert(0, f"Version:{version}")

        return "\n".join(lines)

    def _add_byte_counts(self, content: str) -> str:
        """Add byte counts to the HTML content."""
        # Check
        current_values = self._get_byte_values(content)
        if all((i is not None and i != -1) for i in current_values.values()):
            content = self._update_byte_counts(content)
            return content

        # Setup
        content_bytes: bytes = content.encode(encoding=HTML_ENCODING)

        # Blocks to find
        html_start = "<html>".encode(encoding=HTML_ENCODING)
        html_end = "</html>".encode(encoding=HTML_ENCODING)
        fragment_start = "<!--StartFragment-->".encode(encoding=HTML_ENCODING)
        fragment_end = "<!--EndFragment-->".encode(encoding=HTML_ENCODING)

        # Find Values
        found_html_start = content_bytes.find(html_start)
        found_html_end = content_bytes.find(html_end)
        found_fragment_start = content_bytes.find(fragment_start)
        found_fragment_end = content_bytes.find(fragment_end)

        # Fix Values
        if HTML_ENCODING == "UTF-8":
            found_html_end += len(html_end)
            found_fragment_start += len(fragment_start)

        # Set Values
        self.start_html = found_html_start
        self.end_html = found_html_end
        self.start_fragment = found_fragment_start
        self.end_fragment = found_fragment_end

        # Update
        content_bytes = self._update_byte_counts(content_bytes)

        # Clean Up
        result = content_bytes.decode(encoding=HTML_ENCODING)

        return self._add_byte_counts(result)

    @staticmethod
    def _get_byte_values(content: str) -> dict:
        """Get the byte values from the HTML content."""
        re_start_html = re.compile(r"StartHTML:(\d+)", flags=re.MULTILINE)
        start_html = int(
            re_start_html.findall(content)[0]
            if re_start_html.findall(content)
            else -1
        )

        re_end_html = re.compile(r"EndHTML:(\d+)", flags=re.MULTILINE)
        end_html = int(
            re_end_html.findall(content)[0]
            if re_end_html.findall(content)
            else -1
        )

        re_start_fragment = re.compile(
            r"StartFragment:(\d+)", flags=re.MULTILINE
        )
        start_fragment = int(
            re_start_fragment.findall(content)[0]
            if re_start_fragment.findall(content)
            else -1
        )

        re_end_fragment = re.compile(r"EndFragment:(\d+)", flags=re.MULTILINE)
        end_fragment = int(
            re_end_fragment.findall(content)[0]
            if re_end_fragment.findall(content)
            else -1
        )

        return {
            "StartHTML": start_html,
            "EndHTML": end_html,
            "StartFragment": start_fragment,
            "EndFragment": end_fragment,
        }

    def _update_byte_counts(self, content: B) -> B:
        """Update the byte counts in the HTML content."""
        data: str
        if isinstance(content, bytes):
            data = content.decode(encoding=HTML_ENCODING)
        elif isinstance(content, str):
            data = content
        else:
            raise TypeError(f"{type(content)} is not a valid type")

        re_value = r"(None|-?\d+)"

        re_start_html = re.compile(rf"StartHTML:{re_value}", flags=re.MULTILINE)
        re_end_html = re.compile(rf"EndHTML:{re_value}", flags=re.MULTILINE)
        re_start_fragment = re.compile(
            rf"StartFragment:{re_value}", flags=re.MULTILINE
        )
        re_end_fragment = re.compile(
            rf"EndFragment:{re_value}", flags=re.MULTILINE
        )

        data = re.sub(re_start_html, rf"StartHTML:{self.start_html}", data)
        data = re.sub(re_end_html, rf"EndHTML:{self.end_html}", data)
        data = re.sub(
            re_start_fragment, rf"StartFragment:{self.start_fragment}", data
        )
        data = re.sub(
            re_end_fragment, rf"EndFragment:{self.end_fragment}", data
        )

        if isinstance(content, bytes):
            return data.encode(encoding=HTML_ENCODING)
        elif isinstance(content, str):
            return data
        else:
            raise TypeError(f"{type(content)} is not a valid type")
