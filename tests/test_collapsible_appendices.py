from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup

from scp_epub.collapsible_appendices import (
    CollapsibleAppendixExtractionError,
    extract_collapsible_appendices,
)
from scp_epub.models import CollapsibleAppendixSpec


SCP_3986_SAMPLE = """
<html>
  <head><style>.source-note { color: #444; }</style></head>
  <body>
    <div id="page-content">
      <div class="collapsible-block" id="admin-only">
        <div class="collapsible-block-folded">
          <a class="collapsible-block-link" href="javascript:;">管理专用</a>
        </div>
        <div class="collapsible-block-unfolded" style="display: none">
          <div class="collapsible-block-content"><p>管理内容</p></div>
        </div>
      </div>
      <div class="collapsible-block" id="golden-register">
        <div class="collapsible-block-folded">
          <a class="collapsible-block-link" href="javascript:;">+《金册》</a>
        </div>
        <div class="collapsible-block-unfolded" style="display: none">
          <div class="collapsible-block-unfolded-link">
            <a class="collapsible-block-link" href="javascript:;">-《金册》</a>
          </div>
          <div class="collapsible-block-content">
            <p class="source-note">金册正文<sup class="footnoteref"><a id="footnoteref-1" href="javascript:;">1</a></sup></p>
          </div>
        </div>
      </div>
      <div class="collapsible-block" id="shangdu-romance">
        <div class="collapsible-block-folded">
          <a class="collapsible-block-link" href="javascript:;">+《上都演义》</a>
        </div>
        <div class="collapsible-block-unfolded" style="display: none">
          <div class="collapsible-block-unfolded-link">
            <a class="collapsible-block-link" href="javascript:;">-《上都演义》</a>
          </div>
          <div class="collapsible-block-content"><p>上都正文</p></div>
        </div>
      </div>
      <div class="collapsible-block" id="file-block">
        <div class="collapsible-block-folded">
          <a class="collapsible-block-link" href="javascript:;">+文件</a>
        </div>
        <div class="collapsible-block-unfolded" style="display: none">
          <div class="collapsible-block-content"><p>文件内容</p></div>
        </div>
      </div>
      <div class="footnotes-footer">
        <div class="title">脚注</div>
        <div class="footnote-footer" id="footnote-1">1. 金册脚注</div>
      </div>
    </div>
  </body>
</html>
"""


SPECS = (
    CollapsibleAppendixSpec("《金册》", "scp-3986-golden-register", "《金册》"),
    CollapsibleAppendixSpec("《上都演义》", "scp-3986-shangdu-romance", "《上都演义》"),
)


def test_extracts_selected_blocks_and_leaves_plain_titles_with_owned_footnotes():
    result = extract_collapsible_appendices(SCP_3986_SAMPLE, SPECS)

    owner = BeautifulSoup(result.owner_html, "html.parser")
    titles = owner.select(".collapsible-appendix-title")
    assert [title.get_text(strip=True) for title in titles] == ["《金册》", "《上都演义》"]
    assert all(title.name == "p" and title.find("a") is None for title in titles)
    assert "金册正文" not in owner.get_text(" ", strip=True)
    assert "上都正文" not in owner.get_text(" ", strip=True)
    assert owner.find(id="admin-only") is not None
    assert owner.find(id="file-block") is not None
    assert owner.find(id="footnote-1") is None

    assert [item.spec.slug for item in result.appendices] == [
        "scp-3986-golden-register",
        "scp-3986-shangdu-romance",
    ]
    golden = BeautifulSoup(result.appendices[0].html, "html.parser")
    shangdu = BeautifulSoup(result.appendices[1].html, "html.parser")
    assert golden.select_one("#page-content .source-note").get_text(" ", strip=True).startswith(
        "金册正文"
    )
    assert golden.find(id="footnote-1").get_text(" ", strip=True) == "1. 金册脚注"
    assert golden.find("style") is not None
    assert shangdu.select_one("#page-content p").get_text(strip=True) == "上都正文"
    assert shangdu.select_one(".footnotes-footer") is None


def test_preserves_remaining_owner_footnotes():
    html = SCP_3986_SAMPLE.replace(
        '<div class="footnote-footer" id="footnote-1">1. 金册脚注</div>',
        '<div class="footnote-footer" id="footnote-1">1. 金册脚注</div>'
        '<div class="footnote-footer" id="footnote-99">99. 正文脚注</div>',
    )

    result = extract_collapsible_appendices(html, SPECS)

    owner = BeautifulSoup(result.owner_html, "html.parser")
    assert owner.find(id="footnote-1") is None
    assert owner.find(id="footnote-99") is not None
    assert owner.select_one(".footnotes-footer .title").get_text(strip=True) == "脚注"


@pytest.mark.parametrize(
    ("html", "specs", "expected"),
    [
        (
            SCP_3986_SAMPLE,
            (CollapsibleAppendixSpec("《缺失书籍》", "missing-book", "《缺失书籍》"),),
            "missing-book.*expected exactly one collapsible block, found 0",
        ),
        (
            SCP_3986_SAMPLE.replace(
                '<a class="collapsible-block-link" href="javascript:;">+文件</a>',
                '<a class="collapsible-block-link" href="javascript:;">+《金册》</a>',
            ),
            (CollapsibleAppendixSpec("《金册》", "duplicate-book", "《金册》"),),
            "duplicate-book.*expected exactly one collapsible block, found 2",
        ),
        (
            SCP_3986_SAMPLE.replace(
                '<div class="collapsible-block-content"><p>上都正文</p></div>',
                '<div class="missing-content"><p>上都正文</p></div>',
            ),
            (SPECS[1],),
            "scp-3986-shangdu-romance.*missing .collapsible-block-content",
        ),
        (
            SCP_3986_SAMPLE.replace(
                '<div class="footnote-footer" id="footnote-1">1. 金册脚注</div>',
                "",
            ),
            (SPECS[0],),
            "scp-3986-golden-register.*footnote-1.*found 0",
        ),
        (
            SCP_3986_SAMPLE.replace(
                '<div class="footnote-footer" id="footnote-1">1. 金册脚注</div>',
                '<div class="footnote-footer" id="footnote-1">1. 金册脚注</div>'
                '<div class="footnote-footer" id="footnote-1">1. 重复脚注</div>',
            ),
            (SPECS[0],),
            "scp-3986-golden-register.*footnote-1.*found 2",
        ),
    ],
)
def test_rejects_ambiguous_or_incomplete_collapsible_appendices(
    html: str,
    specs: tuple[CollapsibleAppendixSpec, ...],
    expected: str,
):
    with pytest.raises(CollapsibleAppendixExtractionError, match=expected):
        extract_collapsible_appendices(html, specs)


def test_normalizes_only_one_leading_fold_marker():
    html = SCP_3986_SAMPLE.replace("+《金册》", "+  《金册》", 1)

    result = extract_collapsible_appendices(html, (SPECS[0],))

    assert result.appendices[0].spec.title == "《金册》"
    assert re.search(r"<p[^>]*>《金册》</p>", result.owner_html)
