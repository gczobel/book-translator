"""Parse the XML members of an EPUB, resolving the HTML entities an XHTML DOCTYPE defines.

Valid XHTML may use named entities such as `&nbsp;` that its DOCTYPE's external DTD
defines. The parser never fetches a DTD, so those entities are replaced by numeric
references from Python's local HTML entity table before parsing.
"""

import re
from html.entities import name2codepoint

from lxml import etree

_PARSER = etree.XMLParser(load_dtd=False, no_network=True)
_NAMED = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
_XML_BUILTIN = {b"amp", b"lt", b"gt", b"quot", b"apos"}


def _numeric(match: re.Match[bytes]) -> bytes:
    name = match.group(1)
    if name in _XML_BUILTIN:
        return match.group(0)
    code = name2codepoint.get(name.decode("ascii"))
    return match.group(0) if code is None else f"&#{code};".encode("ascii")


def fromstring(data: bytes) -> etree._Element:
    """Parse `data`; named HTML entities resolve locally, never over the network."""
    if b"<!DOCTYPE" in data:
        data = _NAMED.sub(_numeric, data)
    return etree.fromstring(data, _PARSER)
