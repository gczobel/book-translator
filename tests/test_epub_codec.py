"""Seam 2: the EPUB codec, tested only through its public interface."""

import zipfile
from pathlib import Path

import pytest

from book_translator.epub import EpubError, open_epub

FIXTURES = Path(__file__).parent / "fixtures" / "epub"
FIXTURE_NAMES = ["plain.epub", "odd-markup.epub"]


def members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def infos(path: Path) -> list[tuple[str, int, tuple[int, int, int, int, int, int]]]:
    with zipfile.ZipFile(path) as z:
        return [(i.filename, i.compress_type, i.date_time) for i in z.infolist()]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_identity_round_trip_is_byte_identical_per_member(name: str, tmp_path: Path) -> None:
    source = FIXTURES / name
    out = tmp_path / "out.epub"

    open_epub(source).write(out)

    assert members(out) == members(source)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_round_trip_keeps_file_list_order_and_zip_metadata(name: str, tmp_path: Path) -> None:
    source = FIXTURES / name
    out = tmp_path / "out.epub"

    open_epub(source).write(out)

    assert infos(out) == infos(source)
    assert infos(out)[0][0] == "mimetype"


def test_reopening_the_rebuilt_archive_gives_the_same_book(tmp_path: Path) -> None:
    out = tmp_path / "out.epub"
    first = open_epub(FIXTURES / "plain.epub")
    first.write(out)

    second = open_epub(out)

    assert second.names == first.names
    assert second.spine() == first.spine()
    assert all(second.read(n) == first.read(n) for n in first.names)


def test_spine_lists_content_documents_in_reading_order() -> None:
    assert open_epub(FIXTURES / "plain.epub").spine() == ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"]


def test_fixture_has_toc_css_image_and_two_chapters() -> None:
    names = open_epub(FIXTURES / "plain.epub").names

    assert {"OEBPS/toc.ncx", "OEBPS/style.css", "OEBPS/images/dot.png"} <= set(names)
    assert len([n for n in names if n.endswith(".xhtml")]) >= 2


def test_malformed_xml_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "broken.epub"
    with zipfile.ZipFile(FIXTURES / "plain.epub") as src, zipfile.ZipFile(broken, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "OEBPS/ch1.xhtml":
                data = data.replace(b"</body>", b"")
            dst.writestr(info, data)

    with pytest.raises(EpubError, match="ch1.xhtml"):
        open_epub(broken)


def test_non_zip_is_rejected(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.epub"
    bogus.write_bytes(b"not a zip")

    with pytest.raises(EpubError):
        open_epub(bogus)
