# Classification Component Fidelity Design

## Goal

Restore the project/classification introduction components in the Featured SCP EPUBs so they retain the visual hierarchy, colors, backgrounds, level bars, icons, and side-by-side structure of the source pages while remaining readable and stable in Kindle KF8/AZW3 output.

The change applies to both normal EPUB and Kindle EPUB/AZW3. Narrow screens may reflow for readability; desktop proportions are not fixed and the component is not rasterized.

## Confirmed scope

The final Featured Kindle EPUB contains 69 affected documents:

- 58 documents using the modern ACS `.anom-bar-container` component.
- 11 documents using the WOED-style `.scale` / `.classified-bar` component.

The ACS set includes the three configured SCP-5170 offset attachments. Ordinary item-number paragraphs, tables, warning panels, and unrelated classification formats are outside scope.

The deliverable includes a report listing each affected slug, title, component family, and normalization status.

## Root cause

The source HTML keeps both component structures in `#page-content`, but page-local `<style>` blocks are not copied into processed XHTML.

For ACS pages, the book currently substitutes a global approximation. The normal EPUB approximation introduces a gray panel and border not present in the source component. The Kindle approximation uses table/block fallbacks but leaves disruption and risk fields stacked and reduces the hazard diamond to a plain box.

For WOED Classified Bar pages, no equivalent global EPUB/Kindle component stylesheet exists. The semantic DOM and six source bar images survive, but the layout, visibility, mask, colors, and object-class pill all depended on discarded source CSS. The result is largely unstyled text.

## Considered approaches

### Chosen: semantic Kindle-compatible reconstruction

Normalize the existing DOM into canonical real elements, then style it with separate normal EPUB and Kindle-compatible rules. Text remains selectable/searchable, images remain real assets, and narrow screens can reflow.

### Rejected: inject original page CSS

This is closest in a desktop browser but depends on Grid, Flexbox, masks, CSS variables, structural pseudo-classes, and generated `content`. Those features are unreliable in KF8 and page themes can leak into unrelated content.

### Rejected: rasterize each component

This would provide pixel-level fidelity but makes text unsearchable, prevents font-size adaptation, and requires maintaining at least 69 generated images.

## Canonical component processing

### ACS anomaly classification bar

The existing semantic content remains authoritative:

- item number and clearance level;
- containment and optional secondary class;
- disruption and risk classes;
- materialized field and diamond icons.

Transformation will:

1. keep the existing icon materialization and real clearance label;
2. remove unresolved optional class placeholders as today;
3. add a canonical lower-field wrapper around disruption and risk fields;
4. add stable component-state classes only when needed for CSS targeting;
5. preserve all readable labels as real XHTML.

Normal EPUB CSS will restore the source-like top row, colored clearance bars, full-width containment row, side-by-side disruption/risk row, and right-side hazard diamond. Kindle CSS will render the same semantics with table/block layout and no Grid, Flexbox, generated semantic content, or structural pseudo-classes.

The artificial gray panel and red outer border will be removed. Component-local backgrounds and color bands will be explicit so the component does not depend on the source page theme.

Known containment/disruption/risk class tokens select the established ACS colors. Unknown or esoteric values retain their text and icons and use a neutral fallback rather than disappearing.

### WOED Classified Bar

The existing `.scale` structure will be normalized into three real regions:

1. classification level text;
2. a real sequence of level segments derived from `data-level="lv0"` through `lv6`;
3. item number and object-class pill.

The build will not depend on masks, hidden sizing SVGs, `nth-child`, CSS variables, or generated content. Existing labels and object-class text remain real XHTML. The level segments use the source grayscale progression; the object-class pill uses explicit Safe, Euclid, Keter, Thaumiel, and Neutralized colors with a neutral fallback.

Normal EPUB displays the three regions on one responsive row when space permits. Kindle uses table/block layout and reflows into two rows on narrow screens.

## Data flow

1. `transform_page` identifies and normalizes both component families before XHTML serialization.
2. Asset localization continues to localize the real ACS icons and any retained component images.
3. `BOOK_CSS` styles the canonical normal-EPUB structure.
4. `prepare_kindle_pages` preserves the canonical structure and inserts only Kindle-required real labels/elements.
5. `styles/kindle.css` renders the same semantics using KF8-stable layout primitives.
6. A post-build scan records all affected pages and whether each component matched a known canonical shape.

If a component is malformed or lacks required children, normalization preserves the original DOM and records an `unrecognized` status. It must not delete classification text or fail the whole book.

## Testing and visual verification

Automated tests will cover:

- ACS examples SCP-713 and SCP-186;
- missing secondary class, special/esoteric classes, and clearance levels 0–6;
- real labels and icon preservation;
- containment as a full row and disruption/risk as a paired lower row;
- Classified Bar SCP-1297;
- Classified Bar levels `lv0` through `lv6` and principal object-class colors;
- preservation of readable text when a component cannot be normalized;
- normal EPUB and Kindle CSS selectors;
- Kindle CSS restrictions: no Grid, Flexbox, structural pseudo-classes, or semantic text existing only in `content`;
- a full Featured scan confirming all 69 current components normalize successfully.

After tests, rebuild normal EPUB, Kindle EPUB, and AZW3. Extract SCP-713, SCP-186, and SCP-1297 from both EPUB variants, render them in Chromium, and compare them with the supplied source-page screenshots. Final acceptance requires the component colors, level bars, icons, backgrounds, and principal row/column arrangement to be present, with responsive reflow allowed on narrow screens.

## Non-goals

- Reproducing complete source-page themes, sidebars, headers, or full-page background colors.
- Copying arbitrary page-local CSS into EPUB chapters.
- Rasterizing classification text.
- Changing classification content, titles, page order, or Featured selection.

## Affected document inventory

### ACS anomaly classification bar (58)

- `scp-713` — SCP-713 - 哪里不会点哪里
- `scp-186` — SCP-186 - 为了终结一切战争
- `scp-1131` — SCP-1131 - 奥斯卡蚊
- `scp-4175` — SCP-4175 - 交上朋友，然后 消失
- `scp-4233` — SCP-4233 - 无畏之人
- `scp-5140` — SCP-5140 - 珠穆朗玛峰
- `scp-4823` — SCP-4823 - 全世界都开始蕉躁起来了！
- `scp-5721` — SCP-5721 - 数字时代的信仰形式
- `scp-5514` — SCP-5514 - 屠龙者
- `scp-5109` — SCP-5109 - 一次性密码
- `scp-5494` — SCP-5494 - 下界之主
- `scp-5464` — SCP-5464 - 承担熊任
- `scp-5787` — SCP-5787 - 费城大恶事
- `scp-5170_offset_1` — #1附件A
- `scp-5170_offset_2` — #2附件B
- `scp-5170_offset_3` — #3附件C
- `scp-6033` — SCP-6033 - 有很多胳膊的朋友
- `scp-6868` — SCP-6868 - 橡皮鸭鸭泡泡Bobby
- `scp-6061` — SCP-6061 - 有罪。有罪。有罪。
- `scp-6622` — SCP-6622 - 海狸电力
- `scp-5657` — SCP-5657 - Nicki全知道
- `scp-5783` — SCP-5783 - 事出有因 另一翻译版本
- `scp-6715` — SCP-6715 - 天堂之路
- `scp-6747` — SCP-6747 - 混沌学说
- `scp-6599` — SCP-6599 - 野猪排
- `scp-5863` — SCP-5863 - Myths Made Plain
- `scp-7595` — SCP-7595 - 心灵感应青蛙
- `scp-6373` — SCP-6373 - 舞台枯萎
- `scp-6445` — SCP-⌘ - 在颤抖王国之下
- `scp-7593` — SCP-7593 - House的地狱游记
- `scp-7261` — SCP-7261 - 夜访墨西哥吸血鬼
- `scp-7503` — SCP-7503 - 神聖人類帝國
- `scp-6183` — SCP-6183 - 黑 色 匣 子
- `scp-6596` — SCP-6596 - 8英里：欲与恨生之兽
- `scp-7069` — SCP-7069 - VKTM出品：读者x你！
- `scp-5595` — SCP-5595 - Geoffrey Quincy Harrison三世：站点主管，口香糖机
- `scp-7472` — SCP-7472 - 圆形监狱 5：亲力亲为
- `scp-7522` — SCP-7522 - Jamie Goodworth Mcdonald一世：金融专家，天体结构
- `scp-6764` — SCP-6764 - Maddie
- `scp-8595` — SCP-8595 - 我们都是 测评家
- `scp-7838` — SCP-7838 - 拼布国王与剥皮人宫廷
- `scp-8593` — SCP-8593 - 与Fazool一起来意面
- `scp-8212` — SCP-8212 - 星光餐馆的清晨
- `scp-8093` — SCP-8093 - 忒修斯之船（但是是骨头！）
- `scp-8598` — SCP-8598 - 神射手
- `scp-8430` — SCP-8430 - 进步恐惧症：满足
- `scp-8306` — SCP-8306 - 领班
- `scp-8304` — SCP-8304 - 现代安慰
- `scp-8597` — SCP-8597 - 你的月份，你推的人
- `scp-8274` — SCP-8274 - 帝王蝶
- `scp-9000` — SCP-9000 - 壕沟
- `scp-821` — SCP-821 - 南部乐园
- `scp-7875` — SCP-7875 - 患上正常症
- `scp-9777` — SCP-9777 - 二鹰美浓 - 模仿是最真诚的形态
- `scp-9593` — SCP-9593 - 威望TV
- `scp-7646` — SCP-7646 - Alex Thorley卷入了杜邦特氟龙丑闻
- `scp-2003` — SCP-2003 - 时间机器与首选未来
- `scp-9928` — SCP-9928 - 斯芬克斯的谜题

### WOED Classified Bar (11)

- `scp-1297` — SCP-1297 - 逆时指甲罐
- `scp-4497` — SCP-4497 - 谁是大厨神?!
- `scp-4161` — SCP-4161 - 轮回。
- `scp-5380` — SCP-5380 - 吾的世界
- `scp-5762` — SCP-5762 - 一日一医生
- `scp-1534` — SCP-1534 - 绝佳方案
- `scp-6556` — SCP-6556 - DINOVLOGS！
- `scp-6542` — SCP-6542 - 童贞乳品场
- `scp-4386` — SCP-4386 - 空穴来蜂
- `scp-9100` — SCP-9100 - 白日梦
- `scp-8683` — SCP-8683 - 我制造了免疫球蛋白
