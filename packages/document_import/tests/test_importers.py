from __future__ import annotations

import io
import stat
import zipfile
from threading import Event

import pytest
from document_import import (
    ImportArchiveUnsafeError,
    ImportCancelledError,
    ImportLimits,
    ImportSource,
    ImportTooLargeError,
    import_document,
)


def source(name: str, data: bytes, content_type: str | None = None) -> ImportSource:
    return ImportSource(filename=name, content_type=content_type, data=data)


def zip_bytes(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"target")
    return output.getvalue()


def test_text_and_markdown_preserve_paragraphs_headings_lists_quotes_and_code() -> None:
    text = import_document(source("notes.txt", b"TITLE\n\nFirst paragraph.\n\nSecond."))
    markdown = import_document(
        source(
            "book.md",
            b"# Chapter One\n\nParagraph.\n\n- first\n\n> quote\n\n```python\ncode()\n```",
        )
    )

    assert [block.kind for block in text.blocks] == ["heading", "paragraph", "paragraph"]
    assert [block.kind for block in markdown.blocks] == [
        "heading",
        "paragraph",
        "list_item",
        "quote",
        "code",
    ]
    assert markdown.sections[1].heading == "Chapter One"
    assert markdown.blocks[-1].text == "code()"
    assert markdown.blocks[-1].metadata == {"markdown_fence_language": "python"}


def test_markdown_records_plain_text_fence_language_for_speech_preparation() -> None:
    markdown = import_document(
        source(
            "chapter.md",
            b"```text\n[SYSTEM NOTICE]\n\nContinuity protection: partial.\n```",
        )
    )

    assert markdown.blocks[0].kind == "code"
    assert markdown.blocks[0].metadata == {"markdown_fence_language": "text"}


def test_html_is_non_fetching_and_ignores_active_hidden_and_navigation_content() -> None:
    document = import_document(
        source(
            "article.html",
            b"""
            <html><head><title>Safe article</title><script>SECRET()</script></head>
            <body><nav>chrome</nav><h1>Heading</h1><p>Readable <b>text</b>.</p>
            <p hidden>hidden secret</p><form>private input</form>
            <table><tr><th>Name</th><td>Value</td></tr></table></body></html>
            """,
            "text/html",
        )
    )

    assert document.title == "Safe article"
    assert [block.kind for block in document.blocks] == [
        "heading",
        "paragraph",
        "table_row",
    ]
    combined = " ".join(block.text for block in document.blocks)
    assert "SECRET" not in combined
    assert "chrome" not in combined
    assert "hidden secret" not in combined
    assert document.metadata["network_requests"] == 0
    assert {warning.code for warning in document.warnings} == {
        "html_active_content_ignored",
        "html_hidden_content_ignored",
    }


def test_htm_extension_is_accepted_as_html() -> None:
    document = import_document(source("article.htm", b"<h1>Heading</h1><p>Text.</p>"))

    assert document.source_format == "html"
    assert [block.kind for block in document.blocks] == ["heading", "paragraph"]


def test_docx_preserves_heading_list_and_table_with_ignored_content_warnings() -> None:
    document_xml = b"""
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Chapter</w:t></w:r></w:p>
        <w:p><w:r><w:t>Paragraph text.</w:t></w:r></w:p>
        <w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>List item</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>
    """
    package = zip_bytes(
        {
            "word/document.xml": document_xml,
            "word/comments.xml": b"<comments/>",
            "word/vbaProject.bin": b"macro",
            "word/_rels/document.xml.rels": b'<Relationships TargetMode="External"/>',
        }
    )

    document = import_document(source("book.docx", package))

    assert [block.kind for block in document.blocks] == [
        "heading",
        "paragraph",
        "list_item",
        "table_row",
    ]
    assert document.blocks[-1].text == "A | B"
    assert {warning.code for warning in document.warnings} == {
        "docx_comments_ignored",
        "docx_external_relationships_ignored",
        "docx_macros_ignored",
    }


def test_epub_follows_spine_order_and_preserves_chapter_structure() -> None:
    package = zip_bytes(
        {
            "META-INF/container.xml": b"""
              <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                <rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles>
              </container>
            """,
            "OPS/content.opf": b"""
              <package xmlns="http://www.idpf.org/2007/opf">
                <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title></metadata>
                <manifest>
                  <item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>
                  <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
                </manifest>
                <spine><itemref idref="one"/><itemref idref="two"/></spine>
              </package>
            """,
            "OPS/one.xhtml": b"<html><body><h1>One</h1><p>First.</p></body></html>",
            "OPS/two.xhtml": b"<html><body><h1>Two</h1><p>Second.</p></body></html>",
        }
    )

    document = import_document(source("book.epub", package, "application/epub+zip"))

    assert document.title == "Book"
    assert [block.text for block in document.blocks] == ["One", "First.", "Two", "Second."]
    assert document.metadata == {"spine_items": 2, "network_requests": 0}


@pytest.mark.parametrize(
    "unsafe_name",
    ["../outside", "/absolute", "C:/windows"],
)
def test_docx_rejects_archive_traversal_and_absolute_paths(unsafe_name: str) -> None:
    package = zip_bytes(
        {
            "word/document.xml": b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Safe</w:t></w:r></w:p></w:body></w:document>',
            unsafe_name: b"unsafe",
        }
    )

    with pytest.raises(ImportArchiveUnsafeError):
        import_document(source("unsafe.docx", package))


def test_docx_rejects_links_entities_and_archive_expansion() -> None:
    symlink_package = zip_bytes(
        {
            "word/document.xml": b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
        },
        symlink="word/link",
    )
    entity_package = zip_bytes(
        {"word/document.xml": b'<!DOCTYPE x [<!ENTITY y "boom">]><x>&y;</x>'}
    )
    expanded_package = zip_bytes(
        {
            "word/document.xml": b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
            "word/large.bin": b"x" * 128,
        }
    )

    with pytest.raises(ImportArchiveUnsafeError):
        import_document(source("link.docx", symlink_package))
    with pytest.raises(ImportArchiveUnsafeError):
        import_document(source("entity.docx", entity_package))
    with pytest.raises(ImportTooLargeError):
        import_document(
            source("large.docx", expanded_package),
            limits=ImportLimits(max_expanded_archive_bytes=64),
        )


def test_docx_rejects_duplicate_archive_member_names() -> None:
    output = io.BytesIO()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"<first/>")
            archive.writestr("word/document.xml", b"<second/>")

    with pytest.raises(ImportArchiveUnsafeError):
        import_document(source("duplicate.docx", output.getvalue()))


def test_limits_cancellation_and_content_type_warning_are_enforced() -> None:
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ImportCancelledError):
        import_document(source("cancel.txt", b"text"), cancellation=cancelled)
    with pytest.raises(ImportTooLargeError):
        import_document(
            source("large.txt", b"12345"),
            limits=ImportLimits(max_file_bytes=4),
        )
    mismatch = import_document(source("text.txt", b"Readable", "application/pdf"))
    assert mismatch.warnings[0].code == "content_type_mismatch"


def test_book_scale_text_is_bounded_and_keeps_block_order() -> None:
    paragraphs = [f"Paragraph {index}." for index in range(20_000)]
    document = import_document(source("book.txt", "\n\n".join(paragraphs).encode()))

    assert len(document.blocks) == 20_000
    assert document.blocks[0].text == "Paragraph 0."
    assert document.blocks[-1].text == "Paragraph 19999."
