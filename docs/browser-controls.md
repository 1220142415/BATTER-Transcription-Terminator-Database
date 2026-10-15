# 内嵌基因组浏览器的操作范围

内嵌模式用于浏览已发布的 BTED 数据。以下整理针对固定的 JBrowse 4.3.0；通过 Open full browser 打开的独立页面保留原生管理菜单与显示类型。

| 操作 | 内嵌模式的处理与理由 |
| --- | --- |
| FILE / ADD / TOOLS / HELP | 隐藏整条应用菜单栏；会话导入、插件及额外视图管理移到完整浏览器。外层 Import tracks 保留用户数据导入。 |
| 坐标搜索、平移、缩放、轨道选择 | 保留，是定位和对比数据的核心操作。 |
| 轨道标题 | 使用 JBrowse 原生 overlapping 紧凑标签，关闭、菜单、拖动与 records／regions 计数位于标题旁边。 |
| About track、原文件下载 | 保留研究来源、证据说明及已发布文件的下载。白名单同时支持固定版本的 v0.3 / v0.4 实验数据与 v0.5 按基因组组织的计算数据。 |
| Track actions | 去掉禁用的设置、删除及复制操作；有原文件下载时移除重复导出，无原文件下载时保留原生可见区域数据导出。 |
| Track order | 保留排序、固定和折叠，便于比较多个来源。 |
| 端点、预测和增强区间的 Display types | 隐藏 Arc display；这些记录不表示成对位置或连接关系。保留普通特征显示。区间分数也不等同于连续测量信号。 |
| 特征布局与显示 | 保留 Expanded / Compact、标签、描述、提示及布局高度上限；不在内嵌模式提供压缩成点或合并的布局。端点及计算区间默认隐藏长编号，可重新开启标签或点击特征查看属性。 |
| 特征筛选 | 提供全链、正链、负链；基因注释另保留仅显示基因。移除表达式编辑器，以及非基因轨道上的基因字形、转录本和子特征选项。切换链筛选不会清除其他筛选。 |
| 参考序列 | 保留正向、反向、翻译、序列导出及 GC 含量显示；GC 含量由参考序列计算，有实际用途。 |
| 连续 BigWig 信号 | 固定正负链镜像渲染，保留提示、原始 BigWig 下载，以及可见区域或整个轨道的自动尺度。隐藏渲染器、填充、行聚类和排列控制。 |
| 镜像信号的数值选项 | 镜像渲染使用线性幅值及汇总区间的最大值；隐藏未实现的对数、最小值、均值及其他汇总控制，避免菜单改变后图形不按选项变化。 |
| 视图菜单 | 保留参考方向翻转、全参考概览、网格及轨道标题设置；移除返回导入表单和隐藏坐标栏的操作。无镜像信号时保留 SVG 导出；镜像渲染器不支持 SVG，显示该信号时移除此入口。 |

此调整不修改参考序列、特征属性、数值、数据版本或证据等级。样式仅在带有 `bted_bridge` 的内嵌页面启用。单视图的坐标栏顶部偏移重置为零，消除隐藏标题后原生保留的 28 px 空白；多参考视图保留各自标题。

## Feature details outside the embedded browser

The genome page frames the iframe with a 1 px outline and an 8 px inset. Feature clicks open a separate **Feature details** panel on the right, following RAPPTOR's external sidebar layout. At viewport widths of at least 1640 px, it sits beside the browser without reducing track width; otherwise it floats over the right side of the page. Its content scrolls independently. A React portal renders JBrowse's native `BaseFeatureWidget` there, preserving original attributes, subfeatures, sequence controls and their callbacks. The native drawer has no layout column while these details are open. The track selector and add-track form use this same external panel; the standalone full browser retains its native layout.

The external host is same-origin and optional: without it, JBrowse uses its original widget. A shadow root isolates native widget styles from site styles. Close (or Escape while focus is in the details section) hides the widget; Reload creates a fresh host and discards stale details. This changes presentation only, without rewriting feature values or published assets.

## Reusing genome data across visits

Pinned HF files use the browser's HTTP cache. In addition, Cache Storage retains successfully read slices up to 512 KiB each, with a maximum of 128 entries (about 64 MiB). Keys contain the full immutable asset URL and exact Range, so revisions and intervals cannot mix. Registered, versioned same-origin backup files can use the same cache. Partial responses retain their original 206 status and Range headers when reused. Unversioned URLs, errors, conditional requests, explicit `no-store` requests and larger reads bypass this slice cache. Storage failures fall back to normal fetching.

Content-hashed JBrowse JS/CSS and the current versioned plugin receive one-year immutable HTTP caching. HTML and configuration do not receive that policy. Opening the browser still initializes JBrowse; first visits, new intervals and evicted cache entries still require data loading. Reload restores the browser while reusing valid data; it does not clear the data cache.

## Track directory and user comparisons

The outer **Tracks** button opens JBrowse's native searchable, grouped checkbox directory in the external panel. The directory has no persistent selection hint. Opening the panel does not hide tracks automatically or change defaults. Hiding a track only changes visibility. User session tracks also appear in this directory.

**Import tracks** opens an importer with Local file and Remote URL modes. The local mode uses one file picker: plain BED/GFF3 and BigWig need one file; BAM, CRAM and indexed compressed formats require the main file and its existing matching index to be selected together. File names are matched automatically, with errors for missing or incompatible indexes. BTED does not generate indexes or sort alignment files in the browser. Examples include BED/GFF3 features, BigWig coverage and indexed BAM alignments. Users must choose the matching reference assembly and contig names; the form supports assembly selection and adapter confirmation. It does not align raw sequencing reads or change published BTED data. Local files remain in the browser and may need to be selected again after reload. Remote files require browser-accessible URLs and appropriate CORS headers. BTED share links include only registered public tracks and explicitly warn when visible user tracks are omitted.

The external importer uses an ordinary HTML file input and JBrowse's blob registry because the iframe's File System picker lacks activation from a click in the outer document. Files are recreated in the iframe's File realm without reading the entire file into an ArrayBuffer, preserving native RPC handling. The native adapter, confirmation and add actions are retained; the advanced workflow selector is hidden in the embedded importer. Switching source mode clears the previous selection. Published-track menu simplification is not applied to user tracks, whose data may require other displays or actions.

## Training sequence context

The combined computational track is named **BATTER · augmentation / Rfam regions**. Its count uses regions and combines OTU augmentation with Rfam-derived training spans, excluding both training_sequence_window and rfam_training_window records. Training context windows are hidden by default and can be enabled with **Feature filters > Show sequence context windows**. Toggling this option preserves strand filters. Regions use green for + strand and red for − strand, matching reference annotations; light blue and lavender windows show the surrounding sequence supplied as model input. They are separate GFF3 records, not additional terminators or called transcript boundaries. A context-specific hover label and Data notes explain this distinction without rewriting source attributes. Reference annotation tracks hide chromosome-wide `region` features and long descriptions by default, retaining gene labels. **Show reference-region annotations** restores region records; source files and their attributes remain unchanged. For GCF_000009765.2, the window NC_003155.5:641563-642123 contains the augmented span 641814-641872. Coordinates here use the source GFF3's 1-based inclusive convention.

The embedded reference overview and navigation toolbar use stronger plum backgrounds, borders, labels and controls. Feature coordinates and strand directions are unchanged. Computational intervals use a softer palette described below.

## Small-file origin recovery

The computational asset proxy reads registered files up to 512 KiB through the same immutable Cloudflare cache used for config generation, checking full size and SHA-256 before serving any bytes. It produces valid complete or partial responses (including suffix and open-ended ranges), handles HEAD and rejects invalid ranges. Larger files still stream upstream. The browser can also fall back to registered, version-matched backups for HTTP 403/408/429/5xx, as well as network/CORS failures. No arbitrary URL is accepted.

Configured `jexlFilters` expressions omit the `jexl:` prefix because JBrowse adds it when building active filters. Menu callbacks use the native active-filter strings, which include the prefix. Existing sessions may retain explicit display/filter settings; new sessions use the documented defaults.

## Contig record status and interval styling

Each embedded experimental track header shows its own cataloged record count for the current contig. Computational headers show verified region counts for that contig, combining both strands and excluding context windows. Augmentation tooltips give separate OTU and Rfam totals; prediction counts come from checksum-verified tabix reference statistics checked against the published genome total. Missing statistics show Count unavailable rather than zero. Display filters and zoom do not change these whole-contig totals. Counts cover the entire contig in that track, combining + and - strands, not the visible interval or sequencing coverage. Augmentation / Rfam and prediction badges use an outline flag; experimental record badges use a solid flag. Both use neutral gray, with a downward pole and no protrusion above the face, to avoid implying a strand-specific count; tooltips explicitly state that all strands are combined. Zero records and unavailable counts have separate labels; native file-loading errors remain visible. The outer Contig selector and experimental endpoint legend have been removed. Contigs are selected through native coordinate navigation; headers follow it, including hidden/restored tracks, track reordering, and separate reference views. Hover on the count explains its scope and identifies the contig. A view spanning multiple contigs does not show a misleading single-contig count.

Static counts are derived from checksum-verified published GFF3 files and checked against each source's published total. Dynamic counts use read-only grouping of the existing endpoint table and the same total check. Verified reference aliases are applied to both the adapters and count keys when experimental tracks are merged with computational tracks. Separate reference views keep their original count keys.

OTU augmentation, Rfam training and predictions use green (#0f766e) for + strand and red (#be123c) for − strand, matching reference annotations. Flags have a 6 px high face and a 12 px pole extending downward from the face top, within native training/prediction layout heights of 14 px; new default track heights are 96/80 px. Sequence context windows remain optional. Source coordinates, scores and strand directions are unchanged; explicit display heights in old shared links remain respected.

## Endpoint and region flags

BTED experimental `terminator_endpoint` records use a small solid strand flag anchored at the center of their original one-base interval. Training `augmented_terminator_span`, `rfam_training_span`, and prediction `predicted_terminator_region` features use the same flag shape with a hollow outline at the strand-oriented 3′-side boundary (end on +, start on −). Flags have a downward pole like RAPPTOR, with no short line protruding above the face; known-strand regions also show a 3 px high bar spanning their original start and end coordinates, meeting the pole foot. Hit bounds include both the full region bar and flag. All three interval types use green for + strand and red for − strand, matching reference annotations. Original interval coordinates remain available in feature details. This boundary is not a resolved single-base 3′ end site: the pinned prediction GFF3 provides only a region, strand, and score. Prediction hover shows 1-based inclusive coordinates, interval length in bp, the 3′-side region boundary, and model score; original feature attributes are retained. Reversing the reference flips the displayed flag direction while preserving the original strand color; unknown-strand intervals use a plain gray bar. Optional context windows remain pale bands.

The implementation uses JBrowse 4.3.0's pluggable GlyphType with its existing feature layout, native canvas/SVG rendering, filters, tooltips, feature lookup and external attributes. Matching requires a BTED/BATTER source and one of the scientific feature types; ordinary gene annotations and user features from other sources retain native glyphs. Endpoint hit bounds include the leftward flag: the pinned renderer builds hit indexes after draw() and otherwise ignores the native glyph's left padding. This adjusts screen hit bounds only, not feature coordinates. The symbol legend shows point and interval meanings.


The embedded genome overview uses a light neutral background, plum direction texture, and a dark-bordered translucent current-window marker. Narrow windows keep a minimum 3 px visual marker without changing navigation coordinates. Navigation icons and zoom slider have separate high-contrast styling. In both embedded and full browsers, the native overview-to-window trapezoid retains its geometry, with 32% plum fill and an opaque dark plum 1.5 px outline. Sequence and annotation colors remain unchanged.
