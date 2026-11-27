"""Regenerate the synthetic EPUB 2 fixtures in this folder.

Run `uv run python tests/fixtures/epub/build_fixtures.py` after editing. The output is
deterministic (fixed zip timestamps) so the committed .epub files only change when the
content below does. Nothing here is a real book.
"""

import zipfile
from pathlib import Path

HERE = Path(__file__).parent
STAMP = (2026, 1, 1, 0, 0, 0)

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>Synthetic Tale</dc:title>
    <dc:creator opf:role="aut">Nobody</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:00000000-0000-0000-0000-000000000001</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="img" href="images/dot.png" media-type="image/png"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>
"""

NCX = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:00000000-0000-0000-0000-000000000001"/></head>
  <docTitle><text>Synthetic Tale</text></docTitle>
  <navMap>
    <navPoint id="n1" playOrder="1">
      <navLabel><text>One</text></navLabel><content src="ch1.xhtml"/>
    </navPoint>
    <navPoint id="n2" playOrder="2">
      <navLabel><text>Two</text></navLabel><content src="ch2.xhtml"/>
    </navPoint>
  </navMap>
</ncx>
"""

CSS = "p { margin: 0; }\n.scene { text-align: center; }\n"

# 1x1 transparent PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"
)

PLAIN_1 = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head><title>One</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
  <h1 id="ch1">One</h1>
  <p class="first">It was a quiet evening.</p>
  <p>She said nothing.</p>
  <p class="scene">* * *</p>
  <p><img src="images/dot.png" alt="a dot"/></p>
</body>
</html>
"""

PLAIN_2 = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head><title>Two</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
  <h1 id="ch2">Two</h1>
  <p>The next morning was <em>loud</em>.</p>
  <hr class="break"/>
  <p>Fin.</p>
</body>
</html>
"""

# Unusual but valid: named and numeric entities, extra namespaces, nested inline tags,
# attribute quoting, a processing instruction, a comment, no trailing newline, CRLF.
ODD_1 = (
    '<?xml version="1.0" encoding="utf-8"?>\r\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops" xmlns:svg="http://www.w3.org/2000/svg" '
    'xml:lang="en">\r\n'
    "<head><title>Odd &amp; Ends</title>"
    '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/></head>\r\n'
    "<body>\r\n"
    "<!-- a comment -->\r\n"
    "<?custom-pi keep me?>\r\n"
    '<h1 id="o1">Caf&#233; &amp; Cr&#232;me</h1>\r\n'
    "<p class='single'>&lt;tag&gt; &#x2014; &#8220;quoted&#8221; &amp; more</p>\r\n"
    '<p>Nested <em>a <strong>b <span class="x" id="s1">c</span></strong></em> '
    '<a href="ch2.xhtml#t">link</a><sup epub:type="noteref">1</sup>'
    "<br/>after break</p>\r\n"
    '<div><svg:svg width="1" height="1"/></div>\r\n'
    "<p>¿Qué tal? —¡Bien!</p>\r\n"
    "</body>\r\n"
    "</html>"
)


def write(name: str, files: dict[str, bytes | str]) -> None:
    members: dict[str, bytes | str] = {
        "META-INF/container.xml": CONTAINER,
        "OEBPS/content.opf": OPF,
        "OEBPS/toc.ncx": NCX,
        "OEBPS/style.css": CSS,
        "OEBPS/images/dot.png": PNG,
    }
    members.update({f"OEBPS/{k}": v for k, v in files.items()})
    with zipfile.ZipFile(HERE / name, "w") as z:
        info = zipfile.ZipInfo("mimetype", STAMP)
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
        for path, data in members.items():
            info = zipfile.ZipInfo(path, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data.encode("utf-8") if isinstance(data, str) else data)


def main() -> None:
    write("plain.epub", {"ch1.xhtml": PLAIN_1, "ch2.xhtml": PLAIN_2})
    write("odd-markup.epub", {"ch1.xhtml": ODD_1, "ch2.xhtml": PLAIN_2})


if __name__ == "__main__":
    main()
