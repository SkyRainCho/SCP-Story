from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from html import escape, unescape
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path

from .models import ProcessedPage


CLEARANCE_LABELS = {
    "clear-1": "PUBLIC",
    "clear-2": "RESTRICTED",
    "clear-3": "CONFIDENTIAL",
    "clear-4": "SECRET",
    "clear-5": "TOP SECRET",
    "clear-6": "COSMIC TOP SECRET",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


class KindleConversionError(RuntimeError):
    pass


def convert_epub_to_azw3(
    epub_path: Path,
    azw3_path: Path,
    *,
    executable: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> Path:
    if not epub_path.is_file():
        raise KindleConversionError(f"Kindle EPUB does not exist: {epub_path}")

    resolved = (
        str(executable)
        if executable is not None
        else shutil.which("ebook-convert")
    )
    if not resolved:
        raise KindleConversionError(
            "Calibre ebook-convert was not found; install Calibre and ensure "
            "ebook-convert is available on PATH"
        )

    azw3_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = azw3_path.with_name(f"{azw3_path.stem}.tmp{azw3_path.suffix}")
    temporary_path.unlink(missing_ok=True)
    command = [
        resolved,
        str(epub_path),
        str(temporary_path),
        "--output-profile=kindle_scribe",
        "--no-inline-toc",
    ]

    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Failed to start Calibre command {command!r}: {exc}"
        ) from exc

    if result.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        details = "\n".join(
            value.strip()
            for value in (result.stdout, result.stderr)
            if value and value.strip()
        )[-2000:]
        raise KindleConversionError(
            f"Calibre command {command!r} exited with {result.returncode}: {details}"
        )

    if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
        temporary_path.unlink(missing_ok=True)
        raise KindleConversionError(
            f"Calibre command {command!r} did not produce a nonempty AZW3"
        )

    temporary_path.replace(azw3_path)
    return azw3_path

_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@dataclass
class _HtmlElement:
    tag: str
    classes: frozenset[str]
    start_tag_end: int
    parent: _HtmlElement | None
    end_start: int | None = None
    text_parts: list[str] = field(default_factory=list)


class _XhtmlStructureParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.elements: list[_HtmlElement] = []
        self._stack: list[_HtmlElement] = []
        self._line_starts = [0]
        self._line_starts.extend(
            index + 1 for index, value in enumerate(source) if value == "\n"
        )

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        element = self._new_element(tag, attrs)
        if tag not in _VOID_ELEMENTS:
            self._stack.append(element)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._new_element(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        end_start = self._offset()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag != tag:
                continue
            self._stack[index].end_start = end_start
            del self._stack[index:]
            return

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def handle_entityref(self, name: str) -> None:
        self._append_text(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_text(f"&#{name};")

    def _new_element(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> _HtmlElement:
        raw_start_tag = self.get_starttag_text()
        classes = frozenset(
            class_name
            for name, value in attrs
            if name == "class" and value
            for class_name in value.split()
        )
        element = _HtmlElement(
            tag=tag,
            classes=classes,
            start_tag_end=self._offset() + len(raw_start_tag),
            parent=self._stack[-1] if self._stack else None,
        )
        self.elements.append(element)
        return element

    def _append_text(self, value: str) -> None:
        for element in self._stack:
            element.text_parts.append(value)

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column


def load_kindle_css() -> str:
    return (
        resources.files("scp_epub")
        .joinpath("styles/kindle.css")
        .read_text(encoding="utf-8")
    )


def prepare_kindle_pages(pages: Sequence[ProcessedPage]) -> list[ProcessedPage]:
    return [replace(page, xhtml=_prepare_kindle_xhtml(page.xhtml)) for page in pages]


def _prepare_kindle_xhtml(xhtml: str) -> str:
    parser = _XhtmlStructureParser(xhtml)
    try:
        parser.feed(xhtml)
        parser.close()
    except (AssertionError, ValueError):
        return xhtml

    insertions: list[tuple[int, str]] = []
    for container in (
        element
        for element in parser.elements
        if "anom-bar-container" in element.classes
    ):
        clearance_text = next(
            (
                label
                for class_name, label in CLEARANCE_LABELS.items()
                if class_name in container.classes
            ),
            None,
        )
        clearance = _find_descendant(
            parser.elements,
            container,
            target_class="clearance",
            ancestor_class="top-right-box",
        )
        if (
            clearance_text
            and clearance is not None
            and clearance.end_start is not None
            and not _element_text(clearance)
        ):
            insertions.append(
                (
                    clearance.end_start,
                    '<span class="kindle-clearance-label">'
                    f"{clearance_text}</span>",
                )
            )

        risk = _find_descendant(
            parser.elements,
            container,
            target_class="class-text",
            ancestor_class="risk-class",
        )
        diamond = _find_descendant(
            parser.elements,
            container,
            target_class="danger-diamond",
        )
        if (
            risk is not None
            and diamond is not None
            and not _has_descendant_class(
                parser.elements, diamond, "kindle-danger-label"
            )
        ):
            risk_text = _element_text(risk)
            if risk_text:
                insertions.append(
                    (
                        diamond.start_tag_end,
                        '<span class="kindle-danger-label">'
                        f"{escape(risk_text, quote=False)}</span>",
                    )
                )

    result = xhtml
    for offset, label in sorted(insertions, reverse=True):
        result = result[:offset] + label + result[offset:]
    return result


def _find_descendant(
    elements: Sequence[_HtmlElement],
    container: _HtmlElement,
    *,
    target_class: str,
    ancestor_class: str | None = None,
) -> _HtmlElement | None:
    for element in elements:
        if target_class not in element.classes or not _is_descendant(
            element, container
        ):
            continue
        if ancestor_class and not _has_ancestor_class(
            element, container, ancestor_class
        ):
            continue
        return element
    return None


def _has_descendant_class(
    elements: Sequence[_HtmlElement], container: _HtmlElement, class_name: str
) -> bool:
    return any(
        class_name in element.classes and _is_descendant(element, container)
        for element in elements
    )


def _is_descendant(element: _HtmlElement, container: _HtmlElement) -> bool:
    current = element.parent
    while current is not None:
        if current is container:
            return True
        current = current.parent
    return False


def _has_ancestor_class(
    element: _HtmlElement, container: _HtmlElement, class_name: str
) -> bool:
    current = element.parent
    while current is not None and current is not container:
        if class_name in current.classes:
            return True
        current = current.parent
    return False


def _element_text(element: _HtmlElement) -> str:
    return " ".join(unescape(" ".join(element.text_parts)).split())
