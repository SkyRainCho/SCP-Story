from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from importlib import resources

from bs4 import BeautifulSoup, Tag

from .models import ProcessedPage


CLEARANCE_LABELS = {
    "clear-1": "PUBLIC",
    "clear-2": "RESTRICTED",
    "clear-3": "CONFIDENTIAL",
    "clear-4": "SECRET",
    "clear-5": "TOP SECRET",
    "clear-6": "COSMIC TOP SECRET",
}


def load_kindle_css() -> str:
    return (
        resources.files("scp_epub")
        .joinpath("styles/kindle.css")
        .read_text(encoding="utf-8")
    )


def prepare_kindle_pages(pages: Sequence[ProcessedPage]) -> list[ProcessedPage]:
    return [replace(page, xhtml=_prepare_kindle_xhtml(page.xhtml)) for page in pages]


def _prepare_kindle_xhtml(xhtml: str) -> str:
    soup = BeautifulSoup(f"<root>{xhtml}</root>", "html.parser")
    root = soup.find("root")
    if not isinstance(root, Tag):
        return xhtml

    for container in root.select(".anom-bar-container"):
        if not isinstance(container, Tag):
            continue
        classes = {str(value) for value in container.get("class", [])}
        clearance_text = next(
            (label for class_name, label in CLEARANCE_LABELS.items() if class_name in classes),
            None,
        )
        clearance = container.select_one(".top-right-box .clearance")
        if (
            clearance_text
            and isinstance(clearance, Tag)
            and not clearance.get_text(strip=True)
        ):
            label = soup.new_tag("span")
            label["class"] = "kindle-clearance-label"
            label.string = clearance_text
            clearance.append(label)

        risk = container.select_one(".risk-class .class-text")
        diamond = container.select_one(".danger-diamond")
        if (
            isinstance(risk, Tag)
            and isinstance(diamond, Tag)
            and not diamond.select_one(".kindle-danger-label")
        ):
            risk_text = risk.get_text(" ", strip=True)
            if risk_text:
                label = soup.new_tag("span")
                label["class"] = "kindle-danger-label"
                label.string = risk_text
                diamond.insert(0, label)

    return "".join(str(child) for child in root.contents).strip()
