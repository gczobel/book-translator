"""Seam 2: embedded-font glyph coverage for the target language (ADR 0002)."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from book_translator.epub import open_epub
from book_translator.fonts import FontCoverageError, check_font_coverage

FIXTURES = Path(__file__).parent / "fixtures" / "epub"
SPANISH_BASE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
SPANISH_ALL = SPANISH_BASE + "áéíóúüñÁÉÍÓÚÜÑ¿¡«»“”‘’—"


def make_font(chars: str) -> bytes:
    """A tiny TrueType font whose cmap covers exactly `chars`."""
    chars = "".join(dict.fromkeys(chars))
    names = [".notdef"] + [f"g{ord(c):04x}" for c in chars]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({ord(c): f"g{ord(c):04x}" for c in chars})
    glyph = TTGlyphPen(None).glyph()
    builder.setupGlyf({name: glyph for name in names})
    builder.setupHorizontalMetrics({name: (500, 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Tiny", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    out = io.BytesIO()
    builder.save(out)
    return out.getvalue()


IDPF = "http://www.idpf.org/2008/embedding"
ADOBE = "http://ns.adobe.com/pdf/enc#RC"
UID = "urn:uuid:00000000-0000-0000-0000-000000000001"  # plain.epub's dc:identifier


def idpf_obfuscate(font: bytes) -> bytes:
    key = hashlib.sha1(UID.encode()).digest()
    head = bytes(b ^ key[i % len(key)] for i, b in enumerate(font[:1040]))
    return head + font[1040:]


def encryption_xml(algorithm: str, *names: str) -> str:
    entries = "".join(
        f'<enc:EncryptedData xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        f'<enc:EncryptionMethod Algorithm="{algorithm}"/>'
        f'<enc:CipherData><enc:CipherReference URI="OEBPS/fonts/{n}"/></enc:CipherData>'
        f"</enc:EncryptedData>"
        for n in names
    )
    return (
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        + entries
        + "</encryption>"
    )


def epub_with_fonts(tmp_path: Path, fonts: dict[str, bytes], encryption: str | None = None) -> Path:
    """plain.epub plus embedded fonts, declared in the manifest."""
    src = zipfile.ZipFile(FIXTURES / "plain.epub")
    out = tmp_path / "with-fonts.epub"
    items = "".join(
        f'<item id="font{i}" href="fonts/{name}" media-type="font/ttf"/>'
        for i, name in enumerate(fonts)
    )
    with zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "OEBPS/content.opf":
                data = data.decode().replace("</manifest>", items + "</manifest>").encode()
            dst.writestr(info, data)
        for name, data in fonts.items():
            dst.writestr(f"OEBPS/fonts/{name}", data)
        if encryption:
            dst.writestr("META-INF/encryption.xml", encryption)
    return out


def test_font_missing_glyphs_fails_naming_font_and_glyphs(tmp_path: Path) -> None:
    path = epub_with_fonts(tmp_path, {"Tiny.ttf": make_font(SPANISH_ALL.replace("ñ", "n"))})

    with pytest.raises(FontCoverageError) as error:
        check_font_coverage(open_epub(path), "es")

    assert "Tiny.ttf" in str(error.value)
    assert "ñ" in str(error.value)
    assert "á" not in str(error.value)


def test_font_with_full_coverage_passes(tmp_path: Path) -> None:
    path = epub_with_fonts(tmp_path, {"Tiny.ttf": make_font(SPANISH_ALL)})

    check_font_coverage(open_epub(path), "es")


def test_epub_without_embedded_fonts_passes() -> None:
    check_font_coverage(open_epub(FIXTURES / "plain.epub"), "es")


def test_every_failing_font_and_inverted_punctuation_are_reported(tmp_path: Path) -> None:
    path = epub_with_fonts(
        tmp_path,
        {
            "A.ttf": make_font(SPANISH_ALL.replace("¿", "?")),
            "B.ttf": make_font(SPANISH_ALL.replace("—", "-")),
            "C.ttf": make_font(SPANISH_ALL),
        },
    )

    with pytest.raises(FontCoverageError) as error:
        check_font_coverage(open_epub(path), "es")

    message = str(error.value)
    assert "A.ttf lacks ¿" in message
    assert "B.ttf lacks —" in message
    assert "C.ttf" not in message


def test_idpf_obfuscated_font_is_read_through_its_obfuscation(tmp_path: Path) -> None:
    broken = idpf_obfuscate(make_font(SPANISH_ALL.replace("ñ", "n")))
    whole = idpf_obfuscate(make_font(SPANISH_ALL))
    path = epub_with_fonts(
        tmp_path,
        {"Broken.ttf": broken, "Whole.ttf": whole},
        encryption_xml(IDPF, "Broken.ttf", "Whole.ttf"),
    )

    with pytest.raises(FontCoverageError) as error:
        check_font_coverage(open_epub(path), "es")

    assert "Broken.ttf lacks ñ" in str(error.value)
    assert "Whole.ttf" not in str(error.value)


def test_font_obfuscated_with_unsupported_algorithm_fails_loudly(tmp_path: Path) -> None:
    path = epub_with_fonts(
        tmp_path,
        {"Adobe.ttf": b"not a readable font"},
        encryption_xml(ADOBE, "Adobe.ttf"),
    )

    with pytest.raises(FontCoverageError) as error:
        check_font_coverage(open_epub(path), "es")

    assert "Adobe.ttf" in str(error.value)
    assert "obfuscat" in str(error.value)
