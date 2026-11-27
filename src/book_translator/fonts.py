"""Embedded-font glyph coverage for the target language (ADR 0002).

The build fails loudly when a font embedded in the book lacks glyphs the target language
needs, rather than letting readers see tofu boxes or silent fallback fonts.
"""

import hashlib
import io
import posixpath
from urllib.parse import unquote

from fontTools.ttLib import TTFont
from lxml import etree

from book_translator.epub import Epub, EpubError

_OPF = "{http://www.idpf.org/2007/opf}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_ENC = "{http://www.w3.org/2001/04/xmlenc#}"
_ENCRYPTION = "META-INF/encryption.xml"
_IDPF = "http://www.idpf.org/2008/embedding"
_FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".woff")

__all__ = ["FontCoverageError", "check_font_coverage"]

_PUNCTUATION = "«»“”‘’—"
_REQUIRED: dict[str, str] = {
    "es": "áéíóúüñÁÉÍÓÚÜÑ¿¡" + _PUNCTUATION,
}


class FontCoverageError(Exception):
    """An embedded font lacks glyphs the target language needs."""


def check_font_coverage(epub: Epub, language: str) -> None:
    """Raise `FontCoverageError` naming each embedded font and its missing glyphs."""
    required = _REQUIRED.get(language.split("-")[0].lower(), "")
    problems = []
    obfuscated = _obfuscated(epub)
    for name in _embedded_fonts(epub):
        try:
            data = epub.read(name)
        except EpubError:
            problems.append(f"{name} is in the manifest but missing from the archive")
            continue
        if name in obfuscated:
            if obfuscated[name] != _IDPF:
                problems.append(f"{name} is obfuscated with an unsupported algorithm")
                continue
            data = _idpf_deobfuscate(data, _unique_identifier(epub))
        cmap = TTFont(io.BytesIO(data), lazy=True, fontNumber=0).getBestCmap() or {}
        missing = [c for c in required if ord(c) not in cmap]
        if missing:
            problems.append(f"{name} lacks {' '.join(missing)}")
    if problems:
        raise FontCoverageError(
            f"embedded fonts miss glyphs for language {language!r}: " + "; ".join(problems)
        )


def _embedded_fonts(epub: Epub) -> list[str]:
    opf = etree.fromstring(epub.read(epub.opf_path))
    base = posixpath.dirname(epub.opf_path)
    fonts = []
    for item in opf.iterfind(f".//{_OPF}manifest/{_OPF}item"):
        href = unquote(item.get("href", ""))
        if href.lower().endswith(_FONT_SUFFIXES) or "font" in item.get("media-type", ""):
            fonts.append(posixpath.normpath(posixpath.join(base, href)))
    return fonts


def _obfuscated(epub: Epub) -> dict[str, str]:
    """Members listed in `encryption.xml`, with their algorithm URI."""
    if _ENCRYPTION not in epub.names:
        return {}
    root = etree.fromstring(epub.read(_ENCRYPTION))
    found = {}
    for data in root.iter(f"{_ENC}EncryptedData"):
        method = data.find(f"{_ENC}EncryptionMethod")
        ref = data.find(f".//{_ENC}CipherReference")
        if method is not None and ref is not None:
            found[unquote(ref.get("URI", ""))] = method.get("Algorithm", "")
    return found


def _unique_identifier(epub: Epub) -> str:
    opf = etree.fromstring(epub.read(epub.opf_path))
    wanted = opf.get("unique-identifier")
    for element in opf.iter(f"{_DC}identifier"):
        if element.get("id") == wanted:
            return "".join((element.text or "").split())
    return ""


def _idpf_deobfuscate(data: bytes, identifier: str) -> bytes:
    """Undo the IDPF font obfuscation: XOR the first 1040 bytes with SHA-1 of the identifier."""
    key = hashlib.sha1(identifier.encode()).digest()
    head = bytes(b ^ key[i % len(key)] for i, b in enumerate(data[:1040]))
    return head + data[1040:]
