"""Optional Markdown view of one original HTML/XHTML source."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, ProcessingInstruction

from .errors import UnsupportedCapabilityError
from .html_text import _HIDDEN_STYLE, _INLINE_XBRL_NS, read_html

_HIDDEN_TAGS = {"head", "script", "style", "noscript", "template"}


def html_to_markdown(content: bytes | Path, *, encoding: str | None = None) -> str:
    try:
        from markdownify import MarkdownConverter
    except ImportError as exc:
        raise UnsupportedCapabilityError(
            "Markdown requires the optional 'markdown' extra (the markdownify package)"
        ) from exc

    soup = BeautifulSoup(read_html(content, encoding), "html.parser")
    for node in soup.find_all(string=lambda value: isinstance(
        value, (Comment, Declaration, Doctype, ProcessingInstruction),
    )):
        node.extract()

    inline_prefixes = {"ix"}
    for tag in soup.find_all(True):
        inline_prefixes.update(
            name.split(":", 1)[1] for name, value in tag.attrs.items()
            if name.startswith("xmlns:") and value in _INLINE_XBRL_NS
        )
    for tag in soup.find_all(True):
        if not tag.name:
            continue
        prefix, separator, local = tag.name.partition(":")
        hidden = (
            tag.name in _HIDDEN_TAGS
            or (bool(separator) and prefix in inline_prefixes and local in {"header", "hidden"})
            or tag.has_attr("hidden")
            or bool(_HIDDEN_STYLE.search(tag.get("style") or ""))
        )
        if hidden:
            tag.decompose()
    for image in soup.find_all("img"):
        if (image.get("src") or "").lower().startswith("data:"):
            image.replace_with(image.get("alt") or "")
    for table in soup.find_all("table"):
        if not table.get_text(strip=True) and not table.find(("img", "a")):
            table.decompose()

    result = MarkdownConverter(heading_style="ATX").convert_soup(soup)
    return re.sub(r"\n{3,}", "\n\n", result).strip()
