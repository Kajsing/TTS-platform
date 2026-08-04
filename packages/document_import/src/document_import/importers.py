from __future__ import annotations

import hashlib
import io
import posixpath
import re
import stat
import time
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import PurePosixPath
from threading import Event
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from .errors import (
    ImportArchiveUnsafeError,
    ImportCancelledError,
    ImportInvalidError,
    ImportTooLargeError,
    ImportUnsupportedError,
)
from .models import (
    ImportedBlock,
    ImportedDocument,
    ImportedSection,
    ImportLimits,
    ImportOptions,
    ImportSource,
    ImportWarning,
)

IMPORTER_VERSION = "2"
SUPPORTED_FORMATS = ("txt", "md", "html", "docx", "epub")
_SPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n[ \t]*\n+")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_XML_FORBIDDEN = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


class ImportContext:
    def __init__(self, limits: ImportLimits, cancellation: Event | None) -> None:
        self.limits = limits
        self.cancellation = cancellation
        self.deadline = time.monotonic() + limits.timeout_seconds

    def check(self) -> None:
        if self.cancellation is not None and self.cancellation.is_set():
            raise ImportCancelledError("Document import was cancelled.")
        if time.monotonic() > self.deadline:
            raise ImportCancelledError("Document import exceeded its time limit.")


class _Builder:
    def __init__(
        self,
        *,
        title: str,
        source_format: str,
        source: ImportSource,
        options: ImportOptions,
        context: ImportContext,
    ) -> None:
        self.title = _clean_title(options.title or title or _stem(source.filename))
        self.source_format = source_format
        self.source = source
        self.options = options
        self.context = context
        self.sections: list[ImportedSection] = [ImportedSection(0, 1, self.title, 0)]
        self.blocks: list[ImportedBlock] = []
        self._section_stack: list[int] = [0]
        self._warning_counts: Counter[tuple[str, str]] = Counter()
        self._character_count = 0

    @property
    def current_section(self) -> int:
        return self._section_stack[-1]

    def warn(self, code: str, message: str, count: int = 1) -> None:
        self._warning_counts[(code, message)] += count

    def add_section(self, heading: str | None, level: int) -> int:
        self.context.check()
        level = max(1, min(level, 9))
        while len(self._section_stack) > 1:
            current = self.sections[self._section_stack[-1]]
            if current.level < level:
                break
            self._section_stack.pop()
        parent = self._section_stack[-1] if self._section_stack else None
        ordinal = len(self.sections)
        self.sections.append(
            ImportedSection(
                ordinal=ordinal,
                level=level,
                heading=_clean_text(heading or "") or None,
                first_block_ordinal=len(self.blocks),
                parent_ordinal=parent,
            )
        )
        self._section_stack.append(ordinal)
        return ordinal

    def add_block(
        self,
        kind: str,
        text: str,
        *,
        section_ordinal: int | None = None,
        preserve_whitespace: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.context.check()
        cleaned = _clean_code(text) if preserve_whitespace else _clean_text(text)
        if not cleaned:
            return
        if len(self.blocks) >= self.context.limits.max_blocks:
            raise ImportTooLargeError("Imported document exceeds the block limit.")
        if self._character_count + len(cleaned) > self.context.limits.max_document_characters:
            raise ImportTooLargeError("Imported document exceeds the character limit.")
        self.blocks.append(
            ImportedBlock(
                ordinal=len(self.blocks),
                kind=kind,
                text=cleaned,
                section_ordinal=(
                    self.current_section if section_ordinal is None else section_ordinal
                ),
                metadata=metadata or {},
            )
        )
        self._character_count += len(cleaned)

    def finish(self, *, metadata: dict[str, object] | None = None) -> ImportedDocument:
        if not self.blocks:
            raise ImportInvalidError("Imported document contains no readable text.")
        warnings = tuple(
            ImportWarning(code, message, count)
            for (code, message), count in sorted(self._warning_counts.items())
        )
        return ImportedDocument(
            title=self.title,
            source_format=self.source_format,
            source_sha256=hashlib.sha256(self.source.data).hexdigest(),
            source_name=_safe_filename(self.source.filename),
            importer_version=IMPORTER_VERSION,
            sections=tuple(self.sections),
            blocks=tuple(self.blocks),
            warnings=warnings,
            language_hint=self.options.language_hint,
            metadata=metadata or {},
        )


def import_document(
    source: ImportSource,
    *,
    options: ImportOptions | None = None,
    limits: ImportLimits | None = None,
    cancellation: Event | None = None,
) -> ImportedDocument:
    resolved_limits = limits or ImportLimits()
    if not source.filename.strip():
        raise ImportInvalidError("Imported file name must not be empty.")
    if not source.data:
        raise ImportInvalidError("Imported file must not be empty.")
    if len(source.data) > resolved_limits.max_file_bytes:
        raise ImportTooLargeError("Imported file exceeds the configured size limit.")
    extension = _extension(source.filename)
    if extension not in SUPPORTED_FORMATS:
        raise ImportUnsupportedError("Imported file format is not supported.")
    context = ImportContext(resolved_limits, cancellation)
    context.check()
    parser = {
        "txt": _import_text,
        "md": _import_markdown,
        "html": _import_html,
        "docx": _import_docx,
        "epub": _import_epub,
    }[extension]
    document = parser(source, options or ImportOptions(), context)
    return _with_content_type_warning(document, source.content_type, extension)


def _import_text(
    source: ImportSource, options: ImportOptions, context: ImportContext
) -> ImportedDocument:
    text = _decode_text(source.data)
    builder = _Builder(
        title=_stem(source.filename),
        source_format="txt",
        source=source,
        options=options,
        context=context,
    )
    for part in _BLANK_LINES.split(text.replace("\r\n", "\n").replace("\r", "\n")):
        cleaned = part.strip()
        if not cleaned:
            continue
        kind = "heading" if _looks_like_heading(cleaned, len(builder.blocks)) else "paragraph"
        if kind == "heading":
            section = builder.add_section(cleaned, 1)
            builder.add_block(kind, cleaned, section_ordinal=section)
        else:
            builder.add_block(kind, cleaned)
    return builder.finish()


def _import_markdown(
    source: ImportSource, options: ImportOptions, context: ImportContext
) -> ImportedDocument:
    text = _decode_text(source.data).replace("\r\n", "\n").replace("\r", "\n")
    builder = _Builder(
        title=_stem(source.filename),
        source_format="md",
        source=source,
        options=options,
        context=context,
    )
    paragraph: list[str] = []
    fenced: list[str] = []
    in_fence = False
    fence_language: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            builder.add_block("paragraph", "\n".join(paragraph))
            paragraph.clear()

    for raw_line in text.split("\n"):
        context.check()
        stripped = raw_line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_fence:
                builder.add_block(
                    "code",
                    "\n".join(fenced),
                    preserve_whitespace=True,
                    metadata=(
                        {"markdown_fence_language": fence_language}
                        if fence_language is not None
                        else None
                    ),
                )
                fenced.clear()
                in_fence = False
                fence_language = None
            else:
                flush_paragraph()
                in_fence = True
                fence_info = stripped[3:].strip()
                fence_language = (
                    fence_info.split(maxsplit=1)[0][:64].lower() if fence_info else None
                )
            continue
        if in_fence:
            fenced.append(raw_line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            heading_text = heading.group(2)
            section = builder.add_section(heading_text, level)
            builder.add_block("heading", heading_text, section_ordinal=section)
            continue
        if re.match(r"^(?:[-+*]|\d+[.)])\s+", stripped):
            flush_paragraph()
            builder.add_block("list_item", re.sub(r"^(?:[-+*]|\d+[.)])\s+", "", stripped))
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            builder.add_block("quote", stripped.lstrip("> "))
            continue
        if not stripped:
            flush_paragraph()
        else:
            paragraph.append(raw_line)
    flush_paragraph()
    if in_fence:
        builder.warn("markdown_unclosed_fence", "An unclosed code fence was preserved as code.")
        builder.add_block(
            "code",
            "\n".join(fenced),
            preserve_whitespace=True,
            metadata=(
                {"markdown_fence_language": fence_language}
                if fence_language is not None
                else None
            ),
        )
    return builder.finish()


class _SemanticHtmlParser(HTMLParser):
    _SKIP_TAGS = {
        "script",
        "style",
        "noscript",
        "nav",
        "form",
        "iframe",
        "object",
        "embed",
        "svg",
        "canvas",
        "template",
    }
    _BLOCK_TAGS = {
        "p": "paragraph",
        "li": "list_item",
        "blockquote": "quote",
        "pre": "code",
        "h1": "heading",
        "h2": "heading",
        "h3": "heading",
        "h4": "heading",
        "h5": "heading",
        "h6": "heading",
    }

    def __init__(self, builder: _Builder) -> None:
        super().__init__(convert_charrefs=True)
        self.builder = builder
        self.skip_depth = 0
        self.active_tag: str | None = None
        self.buffer: list[str] = []
        self.title_buffer: list[str] = []
        self.in_title = False
        self.table_cells: list[str] = []
        self.in_cell = False
        self.cell_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.builder.context.check()
        tag = tag.lower()
        attr = {name.lower(): (value or "") for name, value in attrs}
        hidden = (
            tag in self._SKIP_TAGS
            or "hidden" in attr
            or "inert" in attr
            or attr.get("aria-hidden", "").lower() == "true"
            or "display:none" in attr.get("style", "").replace(" ", "").lower()
            or "visibility:hidden" in attr.get("style", "").replace(" ", "").lower()
        )
        if self.skip_depth:
            self.skip_depth += 1
            return
        if hidden:
            self.skip_depth = 1
            if tag in self._SKIP_TAGS:
                self.builder.warn(
                    "html_active_content_ignored", "Active or non-reading HTML content was ignored."
                )
            else:
                self.builder.warn("html_hidden_content_ignored", "Hidden HTML content was ignored.")
            return
        if tag == "title":
            self.in_title = True
        if tag in {"td", "th"}:
            self.in_cell = True
            self.cell_buffer = []
            return
        if tag in self._BLOCK_TAGS and self.active_tag is None:
            self.active_tag = tag
            self.buffer = []
        elif tag == "br" and self.active_tag is not None:
            self.buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        if tag in {"td", "th"} and self.in_cell:
            self.table_cells.append(_clean_text("".join(self.cell_buffer)))
            self.in_cell = False
            self.cell_buffer = []
            return
        if tag == "tr" and self.table_cells:
            self.builder.add_block(
                "table_row",
                " | ".join(cell for cell in self.table_cells if cell),
                metadata={"column_count": len(self.table_cells)},
            )
            self.table_cells = []
            return
        if tag == self.active_tag:
            text = "".join(self.buffer)
            kind = self._BLOCK_TAGS[tag]
            if kind == "heading":
                level = int(tag[1])
                section = self.builder.add_section(text, level)
                self.builder.add_block(kind, text, section_ordinal=section)
            else:
                self.builder.add_block(kind, text, preserve_whitespace=tag == "pre")
            self.active_tag = None
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_buffer.append(data)
        if self.in_cell:
            self.cell_buffer.append(data)
        elif self.active_tag is not None:
            self.buffer.append(data)


def _parse_html_into(builder: _Builder, data: bytes) -> str | None:
    parser = _SemanticHtmlParser(builder)
    try:
        parser.feed(_decode_text(data))
        parser.close()
    except (UnicodeError, ValueError) as exc:
        raise ImportInvalidError("HTML input could not be parsed.") from exc
    return _clean_text("".join(parser.title_buffer)) or None


def _import_html(
    source: ImportSource, options: ImportOptions, context: ImportContext
) -> ImportedDocument:
    builder = _Builder(
        title=_stem(source.filename),
        source_format="html",
        source=source,
        options=options,
        context=context,
    )
    html_title = _parse_html_into(builder, source.data)
    if options.title is None and html_title:
        builder.title = _clean_title(html_title)
        builder.sections[0] = ImportedSection(0, 1, builder.title, 0)
    return builder.finish(metadata={"network_requests": 0})


def _import_docx(
    source: ImportSource, options: ImportOptions, context: ImportContext
) -> ImportedDocument:
    archive = _SafeArchive(source.data, context)
    if "word/document.xml" not in archive.names:
        raise ImportInvalidError("DOCX package does not contain word/document.xml.")
    builder = _Builder(
        title=_stem(source.filename),
        source_format="docx",
        source=source,
        options=options,
        context=context,
    )
    if any(name.endswith("vbaProject.bin") for name in archive.names):
        builder.warn("docx_macros_ignored", "DOCX macros were ignored.")
    if "word/comments.xml" in archive.names:
        builder.warn("docx_comments_ignored", "DOCX comments were ignored.")
    if "word/_rels/document.xml.rels" in archive.names:
        relationships = archive.read("word/_rels/document.xml.rels")
        if b'TargetMode="External"' in relationships or b"TargetMode='External'" in relationships:
            builder.warn(
                "docx_external_relationships_ignored", "External DOCX relationships were ignored."
            )
    root = _safe_xml(archive.read("word/document.xml"), "DOCX document")
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f"{namespace}body")
    if body is None:
        raise ImportInvalidError("DOCX document body is missing.")
    for child in body:
        context.check()
        if child.tag == f"{namespace}p":
            text = "".join(node.text or "" for node in child.iter(f"{namespace}t"))
            style_node = child.find(f"./{namespace}pPr/{namespace}pStyle")
            style_name = style_node.get(f"{namespace}val", "") if style_node is not None else ""
            heading_match = re.match(r"Heading\s*([1-9])", style_name, re.IGNORECASE)
            if heading_match and _clean_text(text):
                level = int(heading_match.group(1))
                section = builder.add_section(text, level)
                builder.add_block("heading", text, section_ordinal=section)
            elif child.find(f"./{namespace}pPr/{namespace}numPr") is not None:
                builder.add_block("list_item", text)
            else:
                builder.add_block("paragraph", text)
        elif child.tag == f"{namespace}tbl":
            for row in child.findall(f"./{namespace}tr"):
                cells = [
                    _clean_text("".join(node.text or "" for node in cell.iter(f"{namespace}t")))
                    for cell in row.findall(f"./{namespace}tc")
                ]
                builder.add_block(
                    "table_row",
                    " | ".join(cell for cell in cells if cell),
                    metadata={"column_count": len(cells)},
                )
        else:
            builder.warn("docx_content_ignored", "Unsupported DOCX content was ignored.")
    return builder.finish()


def _import_epub(
    source: ImportSource, options: ImportOptions, context: ImportContext
) -> ImportedDocument:
    archive = _SafeArchive(source.data, context)
    if "META-INF/encryption.xml" in archive.names:
        raise ImportArchiveUnsafeError("Encrypted EPUB content is not supported.")
    if "META-INF/container.xml" not in archive.names:
        raise ImportInvalidError("EPUB package does not contain META-INF/container.xml.")
    container = _safe_xml(archive.read("META-INF/container.xml"), "EPUB container")
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise ImportInvalidError("EPUB package does not identify an OPF document.")
    opf_name = _safe_internal_name(rootfile.get("full-path", ""))
    opf = _safe_xml(archive.read(opf_name), "EPUB package document")
    package_title = _clean_text(opf.findtext(".//{*}title") or "")
    builder = _Builder(
        title=package_title or _stem(source.filename),
        source_format="epub",
        source=source,
        options=options,
        context=context,
    )
    manifest: dict[str, tuple[str, str]] = {}
    for item in opf.findall(".//{*}manifest/{*}item"):
        item_id = item.get("id")
        href = item.get("href")
        if item_id and href:
            manifest[item_id] = (href, item.get("media-type", ""))
    spine_ids = [item.get("idref") for item in opf.findall(".//{*}spine/{*}itemref")]
    chapter_count = 0
    for idref in spine_ids:
        context.check()
        entry = manifest.get(idref or "")
        if entry is None:
            builder.warn("epub_spine_item_missing", "An EPUB spine item was missing.")
            continue
        href, media_type = entry
        if media_type not in {"application/xhtml+xml", "text/html"}:
            builder.warn(
                "epub_non_text_spine_item_ignored", "A non-text EPUB spine item was ignored."
            )
            continue
        split = urlsplit(href)
        if split.scheme or split.netloc:
            builder.warn("epub_remote_resource_ignored", "A remote EPUB resource was ignored.")
            continue
        chapter_name = _safe_internal_name(
            posixpath.normpath(posixpath.join(posixpath.dirname(opf_name), unquote(split.path)))
        )
        if chapter_name not in archive.names:
            builder.warn("epub_chapter_missing", "An EPUB chapter resource was missing.")
            continue
        chapter_count += 1
        before = len(builder.blocks)
        _parse_html_into(builder, archive.read(chapter_name))
        if len(builder.blocks) == before:
            builder.warn("epub_empty_chapter", "An EPUB chapter contained no readable text.")
    if chapter_count == 0:
        raise ImportInvalidError("EPUB spine contains no supported text chapters.")
    return builder.finish(metadata={"spine_items": chapter_count, "network_requests": 0})


class _SafeArchive:
    def __init__(self, data: bytes, context: ImportContext) -> None:
        self.context = context
        try:
            self.archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError) as exc:
            raise ImportInvalidError("Imported archive is not a valid ZIP package.") from exc
        infos = self.archive.infolist()
        if len(infos) > context.limits.max_archive_members:
            raise ImportTooLargeError("Imported archive contains too many members.")
        expanded = 0
        names: set[str] = set()
        for info in infos:
            context.check()
            name = _safe_internal_name(info.filename)
            if info.flag_bits & 0x1:
                raise ImportArchiveUnsafeError("Encrypted archive members are not supported.")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ImportArchiveUnsafeError("Archive links are not supported.")
            expanded += info.file_size
            if expanded > context.limits.max_expanded_archive_bytes:
                raise ImportTooLargeError("Imported archive exceeds the expansion limit.")
            if not info.is_dir():
                if name in names:
                    raise ImportArchiveUnsafeError(
                        "Archive contains duplicate member names."
                    )
                names.add(name)
        self.names = frozenset(names)

    def read(self, name: str) -> bytes:
        self.context.check()
        safe_name = _safe_internal_name(name)
        if safe_name not in self.names:
            raise ImportInvalidError("Imported archive is missing a required member.")
        try:
            data = self.archive.read(safe_name)
        except (KeyError, RuntimeError, zipfile.BadZipFile, OSError) as exc:
            raise ImportInvalidError("Imported archive member could not be read.") from exc
        self.context.check()
        return data


def _safe_xml(data: bytes, label: str) -> ElementTree.Element:
    if _XML_FORBIDDEN.search(data):
        raise ImportArchiveUnsafeError(f"{label} contains a forbidden document type declaration.")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ImportInvalidError(f"{label} is not valid XML.") from exc


def _safe_internal_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name or _WINDOWS_DRIVE.match(name):
        raise ImportArchiveUnsafeError("Archive member path is unsafe.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ImportArchiveUnsafeError("Archive member path is unsafe.")
    return path.as_posix()


def _with_content_type_warning(
    document: ImportedDocument, content_type: str | None, extension: str
) -> ImportedDocument:
    expected = {
        "txt": {"text/plain"},
        "md": {"text/markdown", "text/plain"},
        "html": {"text/html", "application/xhtml+xml"},
        "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "epub": {"application/epub+zip"},
    }[extension]
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized or normalized in expected or normalized == "application/octet-stream":
        return document
    warning = ImportWarning(
        "content_type_mismatch",
        "The file extension and reported content type did not match.",
    )
    return ImportedDocument(
        title=document.title,
        source_format=document.source_format,
        source_sha256=document.source_sha256,
        source_name=document.source_name,
        importer_version=document.importer_version,
        sections=document.sections,
        blocks=document.blocks,
        warnings=(*document.warnings, warning),
        language_hint=document.language_hint,
        metadata=document.metadata,
    )


def _decode_text(data: bytes) -> str:
    encodings = (
        ("utf-8-sig", "utf-16") if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig",)
    )
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportInvalidError("Imported text is not valid UTF-8 or BOM-marked UTF-16.")


def _clean_text(text: str) -> str:
    lines = [_SPACE.sub(" ", line).strip() for line in text.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _clean_code(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _clean_title(title: str) -> str:
    cleaned = _clean_text(title).replace("\n", " ")
    if not cleaned:
        return "Imported document"
    return cleaned[:500]


def _safe_filename(filename: str) -> str:
    cleaned = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return cleaned[:255] or "imported-document"


def _stem(filename: str) -> str:
    safe = _safe_filename(filename)
    return safe.rsplit(".", 1)[0] or "Imported document"


def _extension(filename: str) -> str:
    safe = _safe_filename(filename).lower()
    extension = safe.rsplit(".", 1)[-1] if "." in safe else ""
    if extension in {"md", "markdown"}:
        return "md"
    if extension == "htm":
        return "html"
    return extension


def _looks_like_heading(text: str, ordinal: int) -> bool:
    return (
        "\n" not in text
        and len(text) <= 100
        and not text.endswith((".", "!", "?", ";"))
        and (ordinal == 0 or text.endswith(":") or text.isupper())
    )
