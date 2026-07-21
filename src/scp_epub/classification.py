from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bs4 import BeautifulSoup

from .models import ProcessedPage


@dataclass(frozen=True)
class ClassificationComponentRecord:
    slug: str
    title: str
    family: str
    component_count: int
    status: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "slug": self.slug,
            "title": self.title,
            "family": self.family,
            "component_count": self.component_count,
            "status": self.status,
        }


def classification_component_inventory(
    pages: Sequence[ProcessedPage],
) -> list[ClassificationComponentRecord]:
    records: list[ClassificationComponentRecord] = []
    for page in pages:
        soup = BeautifulSoup(f"<root>{page.xhtml}</root>", "html.parser")
        families: dict[str, list[str]] = {}
        for component in soup.select("[data-epub-classification-family]"):
            family = str(
                component.get("data-epub-classification-family", "")
            ).strip()
            status = str(
                component.get(
                    "data-epub-classification-status",
                    "unrecognized",
                )
            ).strip()
            if family:
                families.setdefault(family, []).append(status)
        for family, statuses in families.items():
            records.append(
                ClassificationComponentRecord(
                    slug=page.entry.slug,
                    title=page.entry.title,
                    family=family,
                    component_count=len(statuses),
                    status=(
                        "normalized"
                        if all(status == "normalized" for status in statuses)
                        else "unrecognized"
                    ),
                )
            )
    return records
