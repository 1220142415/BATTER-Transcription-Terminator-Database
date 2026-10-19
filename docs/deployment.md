# 本地组装与运行

2026-10-19 GitHub 源码以已验证的 Cloudflare Worker `6c7035d5-50c2-4cdf-a2ff-7f84c26364ee` 为同步基准：JBrowse 应用仍为 4.3.0，BTED 插件配置为 v=39，公开目录为 `386304acab62868a458e16be`。同步已有的条件轨道、专业条件名称、原 GEM 分类及联动筛选源码和测试，不重新部署 Cloudflare，不修改 D1 或 HF 数据。CI 执行全部 Node 回归；组装失败时将具体原因显示在 GitHub 错误注释中，避免检查页只有退出码。

2026-10-16 基因组目录首屏 Phylum 筛选改为按当前筛选范围内的基因组数量降序，同数量按名称升序。首屏使用已有发布摘要，不新增 D1 查询；筛选后的门数量使用分组聚合及现有缓存，忽略自身选择和下级分类限制，沿用联动规则。目录响应缓存升为 directory-v3，Worker 为 `6c7035d5-50c2-4cdf-a2ff-7f84c26364ee`。17 项 Node 目录／排序／缓存测试、24 项 Python 筛选和 Worker 测试、站点验证及发布预检通过。目录版本和分类数据沿用前次发布；没有写入 D1。线上 8 组 API 的门选项顺序与全部 42,923 行目录独立计算一致；真实浏览器验证首屏、来源和注释联动后顺序及清除恢复，无页面错误。发布及核验记录位于 `dist/phylum-sort-2026-10-16/`。

2026-10-15 基因组目录筛选联动已发布，Worker 为 `53abb126-28cc-42ec-89d1-13743b5e0c5d`。来源、基因组类型、注释状态、数据类型和分类层级的选项现在随其他已选条件及搜索结果更新；分类菜单按上级解锁，切换父级时清空下级。每个菜单忽略自身的当前选择，以便切换备选值；父级分类同时忽略下级限制。零结果保留明确选择及共享链接，不默默扩大查询范围。后端复用目录索引和现有缓存，相同条件的多个菜单合并聚合，首屏沿用发布摘要，翻页／排序复用菜单结果；前端保持专业选项名称并恢复共享链接。目录响应缓存升为 directory-v2，其他 API 为 public-api-20261015-v9。91 项 Python 测试通过（6 项跳过），14 项 Node 回归通过；线上 8 组 API 的数量和全部选项与本地 42,923 行目录计算结果一致，真实 Chromium 验证 Almeida 类型／分类联动、实验来源联动、父级清空、共享链接、零结果、清除及分页，无页面异常。验证、截图和发布记录位于 `dist/linked-filters-2026-10-15/`。目录数据版本沿用 `386304acab62868a458e16be`，本次没有写入 D1 科学数据。

2026-10-15 分类统一到 GEM 原始汇总目录的 GTDB 注释，Worker 为 `f579301b-5580-4514-b244-c601aa3a4860`，目录公开版本为 `386304acab62868a458e16be`，沿用物理索引版本 `b6d6dcaa5e9de931d43a25c3`。七种 Genome source 保留各自的原始数据库／研究来源，42,904 个计算基因组的来源、OTU 和分类均与 GEM 原始表一致。21 个实验参考中，16 个按完整组装编号匹配原 GEM 分类，5 个未匹配并显示未分配；论文物种名、参考菌株和 NCBI TaxID 保留，具体名单及差异见 [基因组元数据](GENOME_METADATA.md)。D1 只增量更新 21 行分类与搜索字段，筛选、首页统计和详情页同步。90 项 Python 测试通过（6 项跳过），11 项 Node 回归通过；线上 25 个页面／静态文件与发布产物相同，七种来源数量、分类筛选、Almeida 的 602 条浏览结果及 S021 两条件标签均通过核验。更正、回退、证据与浏览器截图位于 `dist/gem-taxonomy-2026-10-15/`。插件仍为 v=39，参考、端点、预测和 BigWig 科学资产版本不变。

2026-10-15 条件专业标注已发布，Worker 为 `4f8a7ece-0d8e-485a-b822-2ca4e853482b`，插件沿用 v=39。S021 的两个条件名称写为 Mid-logarithmic phase / Temperature-shifted stationary phase，详情明确 BSK-II 培养基以及 35°C → 约23°C 48 h → 35°C 48 h 的温度处理。四个已有样本标明 medium，S005 写为 MOPS complete medium + 3% NaCl，详情注明盐为额外添加；按照 GEO growth protocol 填写培养温度及收样 OD590，片段化处理另行注明。六条 D1 条件元数据修改均已远程回读匹配，静态配置同步四个样本的名称和详情，缓存命名空间更新。样本编号、物种、参考组装、文件地址与数值不变。原始记录链接及更正、回退文件位于 `dist/s021-condition-browser-2026-10-15/`。

2026-10-15 条件轨道名称更新已发布，Worker 为 `74a44adf-1515-4eb3-ad74-9dd7153bee14`，插件仍为 v=39。S021 标题保留 log / TS-stationary，去掉 mean (n=3)，三重复均值方法仍保存在 About track 和原溯源文件。四个默认样本 BigWig 标题分别增加 MOPS complete、LB、PYE、MOPS complete, 3% NaCl；沿用已核实的样本条件，保留 GSM 编号与详细处理信息。旧版非默认信号没有已核实条件，未推定套用样本条件。只修改显示名称与配置缓存版本，D1 和 HF 科学数据沿用前次核验结果。13 项 Python 与 5 项 Node 定向测试、站点检查、diff 和发布预检通过；线上 5 个基因组的静态／动态配置共 10 项标题和默认显示检查通过。真实浏览器确认 S021 两条绿色正链／红色负链信号均渲染、标题无均值后缀、窗口高度 1264 px 且不截断第二条件，无页面或控制台错误。记录和截图位于 `dist/s021-condition-browser-2026-10-15/`。

2026-10-15 S021 的 log 和 TS-stationary 三生物学重复均值信号已接入浏览器，Worker 为 `c0b6c198-3558-4afe-8d55-53b0b58e58c4`，插件及配置为 v=39。现有静态配置 URL 由 Worker 读取 D1 `signal_conditions` 补充轨道，动态配置接口复用相同逻辑；条件均值不使用单个 GSM 样本编号。4 个原始尺度 BigWig 固定到 HF `b3d2111f399e169e255e3da437e87636bfc085e6`。22 条作者参考序列与网站参考按 UCSC 2bit IUPAC-to-N 规则比较一致，D1 保存已验证的原生别名；不修改 BigWig 坐标或数值。插件优先直读 HF，网络失败时核对 D1 登记并代理相同固定文件；内嵌窗口按实际轨道高度展开。实验配置边缘缓存为 5 分钟，后续更新符合该结构的 D1 条件登记即可刷新轨道，无须为每个条件重新构建静态配置。回退 SQL、序列证据、测试、线上配置和浏览器截图位于 `dist/s021-condition-browser-2026-10-15/`。

2026-10-15 移除镜像 BigWig 图中常驻的全局尺度文字，尺度选项保留在轨道菜单；全局固定对数显示、原始值与轨道高度沿用 v=36。当前 Worker 为 `b9facf13-b6ed-4cfe-9c3d-c9cdb28d82d3`，插件和配置为 v=37。插件测试、站点、语法、diff、发布预检通过；线上插件和配置匹配发布产物，核验见 `dist/signal-label-2026-10-15/`。

2026-10-15 修复局部 BigWig 信号在全局线性最大值下几乎不可见的问题，Worker 为 `fe52db5f-a549-480c-9bda-6da98bd22ccb`，插件与配置为 v=36。GSM2500131 全局共同最大值为 367,957；用户窗口正链最大值 572、负链 12，在原线性显示下最高仅约 0.12／0.0025 px。默认改为固定全局 `log(1 + value)`，共享正负链尺度，零值仍为零；保留原生菜单切回线性，图中标明当前尺度，悬停和下载保留原始数值。未引入窗口缩放、D1 查询或科学文件修改。

6 项插件测试覆盖实际弱峰数值的可见高度、全局强峰、不随窗口变化、零值和原始分数不变；1 项信号 builder、12 项 Worker、站点、diff、语法与发布预检通过。21 份配置只改变显示尺度、默认会话尺度和插件版本，科学内容完整相同；线上插件及静态／动态配置逐项验证。数值来自已核验 BigWig 的实际索引和数据块，证据位于 `dist/signal-visibility-2026-10-15/`。此次没有实时浏览器图形核验。

2026-10-15 BigWig 显示尺度与轨道空间已调整，Worker 版本 `dc157ef2-d770-42d9-a85a-9b6ac03339a4`，插件与内嵌配置为 v=35。镜像信号复用 JBrowse 原生全局统计，使用正负链文件摘要中共同的最大值作为固定线性显示尺度；平移、缩放和切换 contig 不按窗口重算范围。原始 BigWig 值不变，零值不绘制，不再使用最小 1 px 信号高度。该统计来自 BigWig 文件头，不增加 D1 查询。实验轨道改为 140 px，预测轨道为 160 px；实验／预测／增强采用 JBrowse 原生紧凑标题独立行，保留 records／regions 计数，浏览区域同步扩高。

6 项插件测试（含强弱窗口高度一致、零值和 renderer 全局最大值）、12 项 Worker、7 项页面构建、2 项信号／预测 helper 和 2 项预测运行时检查通过，站点、布局、diff、语法与 Wrangler dry-run 通过。21 份配置的科学内容逐项保持一致。线上插件、静态／动态配置核对通过；内置浏览器新线上导航超时，同一发布产物通过本地固定资产代理核验全局峰值、弱窗口及原生标题留空，截图和核验记录见 `dist/signal-scale-2026-10-15/`。HF 固定版本、D1 数据与原始坐标均未修改，未提交或推送 Git。

2026-10-14 实验基因组预测结果已接入，Worker 版本 `bb195db9-b0a4-42e4-ae41-7367f587fcfc`，插件参数为 v=34。固定快照中 19 个 experimental-only 组装共 116,229 个 BATTER-TPE 预测区间，BED、GFF3、Tabix 索引、参考序列和组装版本逐项核对；18 个沿用现有网站参考，GCF_000005845.2 使用对应的 NC_000913.3 参考。新增预测文件登记 59 条，D1 写入 432 行，数据库为 164,941,824 字节。原实验端点、4 个 BigWig 样本、审计-only 论文和已有资产均保持不变。目录只更新 19 行预测计数，首屏和预测排序仍使用已有分页索引。

基因组列表列名改为 `Transcript 3′-end data`。数量为 0 的标签隐藏，整列没有数据时显示破折号；预测轨道标为 `Model prediction`，不归入实验记录。完整 BED/GFF3 坐标、链向、Tabix contig 计数、D1 全量重建和增量回退核验记录在 `dist/bigwig-integration-2026-10-14/`。

2026-10-14 D1 标量结构优化已发布，当前 Worker 为 `22194ff8-595c-4cc2-bcdf-3a63d93aae5e`，`BTED_RUNTIME_FIELDS=on`。D1 实测由 431,210,496 降至 164,818,944 字节，减少 61.78%。基因组页面、metadata、配置、文件代理和目录分页改读当前字段表；不再查询逐基因组 JSON。42,904 个计算基因组和 328,721 条当前文件大小／校验记录逐字段重建核对通过，路径按根目录、批次和文件类型生成。按用户要求不保存 1,019 条历史坐标修正日志；发布的 GFF3 已含最新坐标，本次没有重算或改动科学文件。原实验库仍为 21 组装、25 来源、29,460 端点，目录仍为 42,923 / 14,593 Available / 28,330 Missing。

首屏仍只返回 25 条，实测完全冷查询读取 1 + 1 + 25 + 32 = 59 行，前版为 76；metadata 样本冷查询读取 11 行，后续共享缓存，边缘命中不查 D1。原 JSON 表与完整路径登记表已在生产导出恢复和全部字段核对、线上切换核验后移除。保留当前字段表、实验表、分页索引以及完整目录兼容接口所需的小型目录页；生产只保存一个当前运行快照。迁移、恢复、额度及回退要求见 [D1 metadata](D1_METADATA.md)，证据位于 `dist/d1-runtime-current-2026-10-14/`。全部 Node 回归、站点及文档检查通过，线上新请求、筛选、缓存、配置与 206 下载检查通过。插件与科学资产仍为 v=32，静态资产未变化，公开实验、参考和恢复注释版本保持下文固定值。

2026-10-14 HF 目录合并与 D1 分页已发布，当前 Worker 为 `24fa89c6-8823-411e-9fae-5648cd3c7771`，插件与科学资产保持 v=32。恢复注释移入 `v0.5.0/genomes/batter-<batch>/<genome>/annotations/recovered/`，当前 HF 主分支不再有 `v0.5.1`；注释固定到 `2acf28d9cf0a276f05e6a1456d56c92ccc2292b7`，原参考版本与实验快照不变。新注释清单只保存一次根目录，路径按批次、基因组编号和固定文件名生成；校验值及来源核对保留。全部 515 个远端文件对象身份、大小及五个完整下载样本已验证，见 `dist/annotation-recovery-2026-10-14/merge-object-verified.json` 与 `merge-receipt.json`。

`/genomes` 首屏只查询当前 25 条，无全目录下载或预取。翻页、搜索、筛选和排序使用 `/api/genome-directory`；浏览器只复用最多 12 个已访问结果，页面响应按筛选和页码分开缓存。D1 独立投影版本为 `b6d6dcaa5e9de931d43a25c3`，已校验并标为 ready，实际数据库大小为 431,210,496 字节。首屏三条实测查询读取 1、25、50 行，共 76 行；边缘命中无需 D1，较深分页和组合筛选可能读取更多行。首次压缩目录响应 2,648 字节，第二页 2,921 字节；本机 API 检查约 0.6–1.1 秒，包含网络。总数与 Available/Missing 保持 42,923 / 14,593 / 28,330。线上静态文件、两页顺序、查询、分类、排序、缓存及合并注释的参考哈希与 206 下载全部通过，证据位于 `dist/d1-directory-merged-2026-10-14/`。

重建继续使用 `dist/plain-copy-2026-10-14/rebuild.py`；标准浏览器构建自动读取 `data/registry/genome-directory.json`，输入改变时拒绝复用旧投影。此记录替代下文全目录下载方案；原 metadata、文件登记和实验表未修改。此前 108 MB 投影导入因容量风险被自动审批拒绝，未执行；缩减为 68.5 MB 并完成全量本地验证后，新方案通过审批并已导入。

2026-10-14 目录请求与计算优化已发布，当前 Worker 为 `4fb542e6-1404-451d-97fd-9d883ecb13b6`，插件和科学资产继续使用 v=32。目录 URL 固定参考版本、注释补充版本及表示版本，浏览器可长期复用；目录边缘缓存为 7 天，独立于插件样式版本。同一 isolate 内的并发冷加载共用既有 60 秒内存缓存，一次完整冷读取仍为 431 行，不增加筛选或分页 D1 查询。翻页不再重新排序，查询分词和搜索文本避免重复处理。42,923 条总数、14,593 个 Available 和 28,330 个 Missing 保持；线上完整计算目录与变更前逐字段一致。重建仍使用 `dist/plain-copy-2026-10-14/rebuild.py`。性能对照、线上缓存及截图记录位于 `dist/genomes-performance-2026-10-14/`；本机网络首次下载仍受约 1.46 MB 压缩目录传输速度影响。

2026-10-14 网页与 JBrowse 文案整理已发布，文案版本 Worker 为 `5e3322cc-548d-4fe1-aea6-ac1d0cddba6b`，插件、静态配置和内嵌配置参数同步为 v=32。移除网页 SHA、内部 FASTA 路径、来源编号和重复说明；缩短轨道标题、About track 与悬停信息。计数、部分注释覆盖范围、科学文件、固定版本和 D1 数据未改动。52 个线上静态文件与本地产物一致，20 份配置的科学数据部分保持一致；记录见 `dist/plain-copy-2026-10-14/`。重建本次发布产物使用该目录的 `rebuild.py`，调用原有固定快照页面构建并同步静态轨道文案。

2026-10-14 的 Gene annotation 界面已统一为 Available / Missing。恢复补充版本已上线，最终 Worker 版本 `aedd0eb9-00af-4b97-836f-d523e02e718f`，插件和内嵌配置缓存参数均为 v=30，补充文件固定到 HF `82180c1e12905470b9c3e3e56c80e5ea510e8460`。新增 257 个可用条目（241 个完整参考覆盖、16 个部分覆盖），线上为 14,593 个 Available、28,330 个 Missing。全部远端文件及基因组对应关系核验通过，原参考版本、公开实验快照和 D1 数据未改动，操作及核验结果见 [注释校正](ANNOTATION_RECOVERY.md)。下文早期部署记录中关于多个注释状态的描述已由本轮二类界面替代。

这里记录 v0.4.0 的 Pages、JBrowse、Worker 和 D1 操作。网页与 API 使用同一份发布清单。旧版参考序列和 8 条 BigWig 固定使用 Hugging Face v0.3.0 提交 `90651318aedf5a5ca26b8308070927d36fd3d6c9`；v0.4.0 新文件固定使用 `eea5b7225975b224a1c837f60c4fa10497fef022`。不能写成会移动的 `main` 地址。

## 先检查数据

在仓库根目录运行：

```bash
python scripts/validate_bted_v0_4.py
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
```

新基因组的 NCBI 参考包放在 `data/registry/browser_refs/`。下面的命令会核对原包、参考序列和长度，并准备 FASTA、FAI 与基因注释。Cascino 论文的 `CP000100.1` 与浏览器使用的 `NC_007604.1` 已核对为相同序列。

JBrowse 轨道说明、链向颜色和双链信号镜像由仓库内的 BTED 插件提供。现用的 JBrowse 4.3.0 已支持所需接口，无须升级。插件按锁定的依赖构建，生成文件只进入组装后的 Pages/Worker 包：

```bash
npm ci --prefix jbrowse-plugin
npm --prefix jbrowse-plugin run check
npm --prefix jbrowse-plugin run build
```

```bash
python scripts/prepare_v04_reference.py --output-root dist/v04-browser-objects
python scripts/build_v0_4_site.py --release-root data/public/v0.4.0 \
  --output-root dist/v04-browser-objects
python scripts/build_v04_asset_manifest.py
```

## 组装网页和 JBrowse

从 GitHub Release `preview-v0.2.0` 取得 `BTED-v0.2.0-jbrowse-assets.tar.gz` 及同名 `.sha256` 校验文件，放进 `dist/jbrowse-release/`。只把它当作 JBrowse 程序与已有参考资产的输入；新版页面、轨道和下载链接由当前数据重新生成。

```bash
python scripts/stage_site.py --data-version v0.4.0 --mode pages \
  --release-archive dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz \
  --release-sha256-file dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz.sha256 \
  --output-dir dist/pages-site

python scripts/stage_site.py --data-version v0.4.0 --mode worker \
  --release-archive dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz \
  --release-sha256-file dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz.sha256 \
  --output-dir dist/worker-site

python scripts/validate-site.py dist/pages-site
python scripts/validate-site.py dist/worker-site
mkdir -p dist/jbrowse-release/unpacked
tar -xzf dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz -C dist/jbrowse-release/unpacked
python scripts/serve_v04_preview.py --site dist/pages-site --port 8769 \
  --proxy http://127.0.0.1:7897 \
  --release-asset-dir dist/jbrowse-release/unpacked/BTED-v0.2.0-jbrowse \
  --browser-objects-root dist/v04-browser-objects
```

打开 `http://127.0.0.1:8769/`，搜索基因组并进入对应页面。预览程序只读取发布清单中的文件；可从已校验的本地包读取相同字节，缺少时再走固定版本地址。基因组页可以分享当前位置与可见轨道，轨道菜单可下载完整文件，端点 GFF3 也可导出当前区段。原有四个来源各有一条正负链镜像信号轨道；镜像只改变显示方向，原始 BigWig 不变。`dist/` 是本地组装结果，不提交到 Git。

## 上传 Hugging Face 后固定版本

只上传本版发布文件与新浏览器资产到现有数据集 `liurulong/terminator` 的 `v0.4.0/`。Fuchs、TERMITe 和 Cascino 排除的候选记录留在内部审计归档，不上传；旧版参考资产和 BigWig 不重复上传。上传前后都按 `data/registry/browser_assets.v0.4.0.tsv` 核对大小与 SHA-256，并检查 GFF3、FASTA、BigWig 的跨站读取和 Range 请求。

当前已上传 74 个文件，共 23,229,941 字节；逐文件下载后的大小与 SHA-256 均与本地一致。GFF3、FASTA 和旧 BigWig 的跨站 Range 请求返回 `206`。更新数据时先取得新的 **40 位提交号**，再用 `scripts/build_v04_asset_manifest.py --revision <新提交号>` 重建清单，并把该提交号同时写入 Pages/CI 和 `scripts/stage_site.py --hf-v04-data-base-url` 的参数。校验通过前不部署 Pages 或 Worker。公开版站点只保存网页与 JBrowse 程序，v0.4.0 数据由固定版本地址读取。

2026-10-03 的 `BATTER_S1_002` 许可修正已写入本仓库和 D1，Hugging Face 更新按用户要求暂缓。当前网页构建使用提交 `8132334` 的公开数据快照，匹配已发布 HF 文件及校验值；重新部署时给 `stage_site.py` 传入该快照的 `--release-root`，不要将尚未上传的 metadata 校验值与旧 HF 版本混用。更新 HF 并核对新版本后，再使用本仓库当前 `data/public/v0.4.0/` 构建。访问统计的安装和口径见 [访问统计](USAGE_ANALYTICS.md)。

## Worker 与 D1

### BATTER 训练增强浏览

`Genomes` 用一张基因组表，通过 Data type 筛选全部、实验、预测和数据增强，同一完整组装编号只显示一行。主表参照 promoter 展示 Genome ID、Genome source、Organism、Taxonomy、Assembly size、Terminator data、Annotation 七列，点击 Genome ID 进入详情。Terminator data 在同一格分行显示实验端点、预测和增强／Rfam 区间，并按有无数据使用颜色标签。Taxonomy 在独立筛选区按门→纲→目→科→属→种逐级选择；文章、方法和信号信息在详情及轨道说明中查看。增强／Rfam 为 OTU 增强区间与 Rfam 训练区间之和，不计上下文窗口。实验参考大小由已有 contig 登记汇总，计算参考大小仅采用与固定 HF 版本一致的叠加核查记录；未收录的大小显示 Not cataloged，排序时放在已收录记录之后，不按文件大小或实验端点推断。注释状态区分可用、坐标不兼容、缺失和未收录。实验与计算数据共用同一个基因组页面和 JBrowse；模型预测只展示已经发布的结果，不执行预测任务。计算数据固定到 HF 提交 `9f81698a3cee64f4eaf90b90cd36d640f38d9315`，包含批次 000–042 的 42,904 个已发布基因组；目录和发布完成记录已核对。该数字是本站发布范围，不表示覆盖所有可能的菌种或实验数据。

Genome source 来自原始批次清单的 `source_collection`，保留数据库或研究来源；NCBI-MAG/SAG 在网页显示为 NCBI GenBank。Genome ID 为原始基因组编号；有计算目录映射时，在同一单元格的第二行显示 GEM OTU（物种聚类编号），实验条目不推断 OTU。详情页用 Sequence source 单独标明实际 FASTA 来源；原始数据库编号不代替序列版本与校验核对。当前目录每个 OTU 只保留一个代表基因组，但原始聚类可包含多个成员。编号、来源及版本共同用于追溯，OTU 不作为单个基因组的主键。

`data/registry/batter-browser.json` 保存构建用目录字段、统计数和固定版本；网页通过 `/api/batter-catalogue` 读取 D1 目录。完整 genome metadata、目录和文件注册索引的导入及启用流程见 [D1 metadata](D1_METADATA.md)。只有完整快照通过校验并标记为 `ready` 后，才设置 `BTED_METADATA_REVISION` 并部署。序列、GFF3 和索引仍在 HF，Worker 从 D1 metadata 生成 `/api/batter/<genome>/config`。`batter-overlays.json` 保存重叠基因组的逐 contig 长度和序列 SHA-256 比较结果；构建后的 `assets/genome-browsers.json` 登记实验配置和叠加依据。相同序列可以叠加实验、预测、增强轨道；名称不同但序列相同的 contig 使用 JBrowse 原生别名。例如 `BA000030.4` 与 `NC_003155.5` 的长度和序列哈希一致。真正不同或尚未核对的参考在同一浏览器中保留独立坐标视图，不凭 accession 叠加。只展示 `matched` 注释。预测、OTU 增强和 Rfam 区间沿用注释的链向颜色：正链绿色、负链红色；完整区间横条在原始 3′ 侧边界连接空心旗帜，实验单碱基端点使用同形实心旗帜；旗杆从旗面顶端向下延伸，顶部无多余短线。原始区间坐标保留在详情中。浅色为上下文窗口；窗口不算额外终止子。

浏览器优先直读 HF，网络异常才使用同版本、已登记文件的同源备份；保留 Range、取消请求和 SHA-256 元数据检查。Worker 生成配置前检查参考索引、增强文件的实际大小和 SHA-256。新增浏览入口不会执行模型预测，也不改动 HF 文件或实验 D1 表。

HF 发布后，指定新 **40 位提交号** 刷新目录，再构建和部署 Worker。脚本从发布清单发现所有批次，核对 metadata 表的大小、SHA-256、基因组集合及发布完成记录；不需要手工填写批次数。

```powershell
py -3.13 scripts/prepare_batter_browser.py --download --carry-overlays --revision <HF提交号>
py -3.13 -m unittest discover -s tests -p test_prepare_batter_browser.py -q
node --test --test-isolation=none tests/test_batter_browser.mjs
```

缓存位于 `dist/hf-catalogue/<提交号>/`。离线重建可省略 `--download`，仍会核对清单中的校验值。只有所有批次与发布目录一致且完成记录通过检查，才将 `partial` 设为 false。`--carry-overlays` 仅在参考文件哈希未变化时保留已有的序列比对结果；哈希变化的记录不再叠加。`--verify-overlaps` 会读取实际 FASTA，仅在需要重新比较序列且获准时另行使用。

2026-10-07 更新固定到 HF `9f81698a3cee64f4eaf90b90cd36d640f38d9315`，使用按基因组组织的 `v0.5.0/genomes/batter-<batch>/<id>/`。metadata 中的计算记录位于 `records.batter`；文件分别位于 `reference/`、`predictions/`、`training/` 和 `annotations/batter/`。Worker 对外仍返回原有的 metadata 字段。目录共 42,904 个计算基因组，合并实验条目后为 42,923 个。21 个实验基因组的 25 个来源 metadata 与当前公开快照一致，实验 D1 表及其固定资产版本继续使用现有记录，未重新导入。核查范围与统计见 [HF 更新核查](HF_REFRESH_2026-10-07.md)。

2026-10-12 发布文案与操作区整理，Worker 版本为 `722a62f7-aad2-4b47-8f48-66c844862e6e`。仍使用公开数据快照 `8132334` 和上述固定 HF 版本，未重新导入 D1 或上传数据。内嵌浏览器保留外层分享，隐藏内层分享和会话日期；单视图隐藏重复标题，多视图保留标题，独立完整浏览器维持原有操作。插件 URL 的 `v=3` 参数和页面 CSS、脚本的内容哈希用于更新浏览器缓存；插件变化时同步更新静态配置、Worker 配置及内嵌配置的版本参数。线上关键文件比对、健康接口与参考文件 `206` Range 核验通过。

2026-10-12 继续简化内嵌浏览器，Worker 版本为 `94a2633e-03dc-4b63-9608-7ddf0bcb9b0b`（前一版本 `722a62f7-aad2-4b47-8f48-66c844862e6e`）。内嵌模式隐藏 FILE / ADD / TOOLS / HELP 所在的整条顶部菜单栏，保留坐标搜索、缩放、轨道选择及轨道操作；高级会话与视图管理仍在 Open full browser 中使用。插件及配置缓存参数同步更新到 `v=4`。11 个线上关键文件与本地构建的 SHA-256 一致，健康接口及参考文件 `206` Range 核验通过。数据快照、固定 HF 版本与 D1 数据保持不变。

2026-10-12 调整内嵌轨道布局与菜单，Worker 版本为 `7b7394d1-fb02-436f-8ee8-369b5599b8aa`，前一版本为 `94a2633e-03dc-4b63-9608-7ddf0bcb9b0b`。插件与配置参数更新到 `v=5`。去除视图阴影、粗色边及单视图坐标栏遗留的 28 px 标题偏移；轨道标题默认放在图形上方。按特征、参考序列及连续信号分别整理操作，具体取舍见 [浏览器操作范围](browser-controls.md)。修正默认标签配置，将 `showLabels` 同时写入 SvgFeatureRenderer。插件与 Worker 的 13 项测试、站点产物检查、11 个线上关键文件 SHA-256 比对、健康接口和参考文件 Range 核验通过。数据版本及已发布内容保持不变。

2026-10-12 完成轨道标题和坐标尺对齐，最终 Worker 版本为 `86050070-dc43-4062-8d70-7c9706038ab8`（前一版本 `7b7394d1-fb02-436f-8ee8-369b5599b8aa`），缓存参数为 `v=6`。轨道菜单与关闭按钮统一放在标题栏右侧；同时修正单视图坐标尺的旧标题偏移。下载白名单补充固定 v0.5 计算数据路径，未放宽到非固定版本或其他数据集。13 项测试、站点检查、11 个线上文件 SHA-256 比对、实验和计算配置接口及两类文件 `206` Range 核验通过。内置浏览器直连远端发生超时，最终界面使用同一构建产物与线上公开 API 的本地预览核对，未修改系统网络设置。

当前部署目标是 `1052596411@qq.com` 的 Cloudflare 账号（`406a94b19dd8bd8d9e851f8c5ed3a569`）。Worker 名称是 `bted`，D1 名称是 `bted-catalog`，数据库 ID 为 `c304fae8-cce6-4fc1-922d-e3bbc1c9b995`。这些标识不是密钥；登录凭据保存在本机 Wrangler 配置中，不提交到仓库。

2026-10-03 首次发布地址：[bted.1052596411.workers.dev](https://bted.1052596411.workers.dev/)。线上健康、来源元数据原文比对、基因组与端点查询、JBrowse 配置、资产读取及 `206` Range 检查通过。D1 的发布状态仍标为 `preview`，便于在后续数据整理后再正式发布。

Pages 主要提供静态网页，也能通过 Pages Functions 接入 D1。这里采用 Worker Static Assets：一个 Worker 提供网页、JBrowse 程序和 `/api/*`，并通过 `BTED_DB` 查询 D1。二者都不需要传统容器。大文件仍由固定版本的 Hugging Face 地址提供。基因组目录页面由发布文件生成，当前没有改成每次打开都查询 D1。

`sources.metadata_json` 完整保留每个来源的原始 `metadata.tsv` 字段，包括文章许可、限制和补充文件路径；标准列负责筛选和关联。`/api/sources` 和来源详情以 `metadata` 对象返回这些字段。当前是新数据库的首次导入；已有旧表的数据库需先添加此列，不能只靠 `CREATE TABLE IF NOT EXISTS` 更新表结构。

Worker 使用 `BTED_DB` 绑定和 `prototype/accession-range/wrangler.jsonc`。先从发布 GFF3、内部来源清单及已核查的远端资产清单生成本地 bundle；远端对象的大小、SHA-256 与 Range 检查完成后才标记 `--origin-verified`。

```bash
python scripts/audit_v04_remote_assets.py --output dist/v04-remote-audit.json
python scripts/import_bted_v03.py materialize-v04 \
  --output-dir dist/v04-d1-bundle --origin-verified
python scripts/generate_bted_d1.py \
  --bundle-dir dist/v04-d1-bundle --output-dir dist/v04-d1-sql
```

将 `dist/v04-d1-sql/` 中的 schema 和编号 SQL 文件依次导入本地 D1，再用 Wrangler 本地启动 Worker。检查 `/api/health` 的 `release_version=v0.4.0`、基因组和来源查询、端点数量、资产代理的 `206` Range 响应。API 返回 JSON 供程序读取；网页不会把原始 JSON 当作用户页面。

远端首次导入前确认数据库为空，并在本地 SQLite 核对完整性、外键、端点数量和原始 metadata 字段。依次执行 schema 与编号 SQL（不要使用原型 `seed.sql`）；也可将它们按相同顺序合并成 `dist/v04-d1-import.sql`，再运行：

```bash
npx wrangler d1 execute bted-catalog --remote \
  --config prototype/accession-range/wrangler.jsonc --file dist/v04-d1-import.sql --yes
npx wrangler deploy --dry-run --config prototype/accession-range/wrangler.jsonc
npx wrangler deploy --config prototype/accession-range/wrangler.jsonc
```

当前 D1 投影包括 14 篇论文、21 个基因组、48 条 contig、25 个来源、35 个外部 accession、157 个资产登记和 29,460 条端点。25 个来源中 1 个仅保留审计信息，不包含公开端点。数据增强及全基因组预测尚未导入；基因关联和条件观测仍保存在发布补充文件中。

2026-10-04 对照 promoter 增加查询缓存：基因组目录仍只加载静态清单，搜索、分类、排序和翻页不发起 D1 查询；分类按门→纲→目→科→属→种逐级解锁。Worker 用原生 Cache API 缓存公开元数据 JSON 300 秒、访问统计 JSON 60 秒，键包含主机、路径、排序后的完整查询参数、数据版本和缓存命名空间。版本或接口语义改变时更新 `cachedPublicApi` 的命名空间；直接更新 D1 后，旧元数据最多保留 5 分钟。健康检查、错误／不可缓存响应、HEAD、文件响应和 Range 请求不经过该响应缓存。

发布信息和公开文件登记在 Worker 内按 D1 绑定隔离，缓存 60 秒，最多 512 项，并合并同一登记的并发查询。缓存缺失或失败时正常查询 D1；不存在的记录和查询错误不保留。JBrowse 的 Range、文件校验和访问计数沿用原流程；统计写入没有采样或去重。未引入 KV、Durable Objects、框架或依赖。

若 JBrowse 空白，先检查该组装的配置和参考 FASTA/FAI 是否在固定地址上可读，再查 GFF3/BigWig 的 Range 请求。某研究没有 BigWig 时只应缺少信号轨道，端点轨道仍可正常显示。旧 v0.2.0、v0.3.0 的数据可从 `data/archive/` 校验归档还原。


2026-10-12 外置特征属性，Worker 版本 `6fb069cb-7b47-4ce5-9fe6-3b198d1b44ea`（前版 `86050070-dc43-4062-8d70-7c9706038ab8`）。插件及配置缓存参数同步为 `v=7`。内嵌浏览器增加 1 px 细边框和 8 px 内侧留白；特征属性用 JBrowse 原生组件展示在浏览器下方的独立详情区，保留原始属性和序列控件，打开详情不再压缩轨道。下拉菜单也使用外层详情容器。全浏览器和轨道选择器保留原生布局。仍使用公开快照 `8132334` 与既有固定 HF 版本，不导入 D1 或上传科学数据。

本地验证：4 项插件测试、10 项 Worker 资产测试、7 项页面构建测试及站点检查通过。真实基因详情打开前后轨道宽度均为 1161.4546 CSS px；序列显示、上下游序列选择、Escape 关闭验证通过。截图来自同版本本地预览，使用登记的同版本资产备份。线上 11 个关键静态文件哈希与发布产物一致，实验／计算配置使用插件 `v=7`，健康接口及参考／预测文件 `206` Range 核验通过。

2026-10-12 调整重复访问缓存与详情侧栏，Worker 版本 `fa5c4c18-e62f-4c27-985b-98c057b5492d`（前版 `6fb069cb-7b47-4ce5-9fe6-3b198d1b44ea`），插件与配置参数为 `v=8`。参考 RAPPTOR 的右侧外置属性面板：至少 1640 px 宽时并排，其余尺寸为右侧浮层，内容独立滚动，不再跳到浏览器下方或压缩轨道。保留原生属性、子特征、序列控件和细边框。

固定版本 HF 数据采用 HTTP 缓存，并用浏览器 Cache Storage 复用已读片段，键为完整固定版本 URL 和精确 Range；最多 128 条，每条不超过 512 KiB，约 64 MiB。已登记的固定版本同源备份同样适用。恢复原始 206 与响应头；不缓存错误、未固定版本、条件请求、明确 no-store 请求和超限读取，缓存不可用时正常读取。带内容哈希的 JBrowse JS/CSS 与当前版本插件设置一年 immutable HTTP 缓存，HTML 和配置不采用该策略。首次读取、新区段、缓存淘汰和 JBrowse 初始化仍需时间。

5 项插件测试、11 项 Worker 资产测试、4 项查询缓存测试、站点检查和 diff 检查通过。同版本本地预览验证了右侧属性、序列菜单和关闭操作，打开前后轨道宽度均为 1161.4546 CSS px；1800 px 宽屏保持浏览器宽度并增加 384 px 侧栏，390 px 窄屏面板未越界。预览重复打开一次测得约 1.9 秒，不作为线上速度承诺。数据快照、固定 HF 版本及 D1 数据沿用前版。

部署后 11 个关键静态文件的线上 SHA-256 与发布产物一致，实验／计算配置均返回插件 `v=8`，健康接口及参考／预测文件的 206 Range 检查通过。线上 JBrowse 哈希程序与 `v=8` 插件响应均包含 `public, max-age=31536000, immutable`；HTML 与组装配置未被设为一年缓存。界面截图使用同版本本地预览，线上核验报告位于工作区 `outputs/bted-copy-2026-10-12/cf-deployment-verified.json`。

2026-10-13 发布首页分类图与用户轨道入口，Worker 版本 `dbea6340-5b2c-48fe-b9e7-754ee4b0c286`（前版 `fa5c4c18-e62f-4c27-985b-98c057b5492d`），插件与配置参数为 `v=9`。首页 Phylum 图隐藏 Unclassified，仅统计 42,911 个有门分类记录的基因组；总目录仍为 42,923 个。外层增加带图标的 Tracks 和 Add your track 按钮：轨道目录使用原生搜索、分组、勾选控件，超过 6 条可用轨道（含参考序列）时显示选择提示，不自动隐藏默认轨道。目录和导入表单外置到现有右侧面板，保持轨道宽度。

用户可选择本地主文件与索引，或输入远程 URL，再通过原生格式、轨道类型和参考组装确认添加轨道。支持原生 BED/GFF3、BigWig、BAM 等适配器；本轮实际导入验证使用合成 BED 文件。本地文件不上传至 BTED，不增加服务端存储或账号系统，重载后可能需重新选择。用户轨道保留原生显示和管理菜单；分享链接只包含已登记公共轨道，并在省略可见用户轨道时提示。外层文件选择采用 HTML input 和 JBrowse blob registry，文件转换到 iframe File realm 以保持 RPC 序列化正常。不会处理原始 FASTQ 或修改已发布数据。

6 项插件测试、11 项 Worker 资产测试、7 项页面生成测试及站点检查通过。本地验证覆盖真实勾选隐藏与恢复、目录搜索、合成 BED 特征渲染、用户轨道管理与分享提示；右侧目录打开前后坐标工具栏宽度均为 1144.5454 CSS px。390 px 窄屏面板边界正常，7 条轨道的基因组显示选择提示。线上 11 个关键静态文件哈希、首页图表过滤、新按钮、实验／计算配置 `v=9`、健康接口、程序缓存响应头及两类数据 206 Range 检查通过。公开快照、HF 固定版本与 D1 沿用前版，未提交或推送 Git。

2026-10-13 简化导入并明确训练窗口，Worker 版本 `e6387321-dde8-49c3-a274-3e103a843503`（前版 `dbea6340-5b2c-48fe-b9e7-754ee4b0c286`），插件与配置参数为 `v=10`。入口统一为 Import tracks；本地和远程 URL 分开选择，本地只显示一个文件选择框。普通 BED、GFF3 和 BigWig 选择一个文件；BAM、CRAM 和已索引压缩格式在同一选择框选择主文件与已有索引，按名称自动配对，缺失或不匹配时明确报错并禁用继续。切换来源清空旧选择，保留原生适配器、参考组装确认和添加流程；隐藏高级导入工作流选择器。没有自动生成索引、排序 BAM 或上传本地数据。

内嵌参考概览及坐标工具栏加强紫灰底色、边线和控件对比度，不改变特征数据颜色。训练轨道改名为 Training regions and sequence context，增加上下文窗口的悬停提示及页面说明。核对固定版本 GCF_000009765.2 的 augmentation.gff3.gz 文件 SHA-256 后确认：NC_003155.5:641563-642123 是训练序列窗口，其中 641814-641872 是增强终止子区间（原始 GFF3 的 1-based inclusive 坐标）；窗口不是额外终止子或转录终止边界，原始属性保留。

6 项计算浏览器测试、6 项插件测试、11 项 Worker 资产测试、7 项页面生成测试、站点产物检查与 diff 检查通过。真实本地界面验证了单个 BED 导入并渲染、URL 模式清空选择、缺失 BAM 索引报错且 Next 禁用。线上 11 个关键静态文件哈希、Import tracks 名称、训练轨道名称和提示、实验／计算配置 v=10、健康接口、缓存响应头及参考／预测两类 206 Range 检查通过。界面截图使用同版本本地预览。公开快照、固定 HF 版本与 D1 沿用前版，未提交或推送 Git。

本轮计算训练轨道的本机预览出现 HF 读取失败，且其同源备份 Range 请求返回 `503 file_upload_unavailable`。固定 HF 源文件可通过本机代理读取且 SHA-256 与公开 metadata 一致；轨道名称及 renderer 提示已从线上配置核对，但本轮没有完成该训练轨道的实际图形与悬停验证。此读取问题不归因于界面修改，尚未定位。

2026-10-13 默认视图与训练文件读取修复，最终 Worker 版本 `a6803260-108b-4c8a-bfd2-496718d9f71d`（本轮前版 `e6387321-dde8-49c3-a274-3e103a843503`；中间版本 `738fece9-3e19-4477-8a36-4ceb97f55841`），插件及配置参数为 `v=12`。Training regions 轨道默认筛掉 training_sequence_window，保留 OTU / Rfam 区间。Feature filters 中增加 Show sequence context windows，按需恢复窗口且保留其他链筛选。默认参考注释排除整条染色体的 region 记录并关闭长描述；Show reference-region annotations 可恢复原始记录。NC_003155.5 的菌株别名长句来自 RefSeq region.note，不是基因名称。原始 GFF3 与特征属性未改动。

计算文件转发对已登记、固定版本且不超过 512 KiB 的文件，复用配置生成时使用的 immutable Cloudflare 完整文件缓存，校验大小和 SHA-256 后返回完整或精确 Range 字节。支持开放末端、后缀、HEAD、越界和无效范围处理；大文件沿用流式转发。插件遇到已登记源文件的 HTTP 403/408/429/5xx 也尝试同版本备份，不扩大 URL 白名单。修复前同一 augmentation.gff3.gz 的普通 Worker 转发返回 503，而固定源文件和配置生成的完整校验读取成功；修复后该文件全量哈希、首段和末段 Range 通过，实际蓝色区间渲染成功。

7 项计算浏览器测试、6 项插件测试、11 项 Worker 资产测试、7 项页面生成测试、站点检查及 diff 检查通过。真实界面复测发现原生配置的 jexlFilters 会自动添加前缀，因此最终配置使用不带 jexl: 的表达式，菜单运行时表达式仍保留前缀。全新访问核对了窗口开关默认未勾选；实际开关可隐藏浅蓝窗口，短蓝区间继续显示。本机同版本预览中菌株长句与训练文件错误已消失，参考、训练及预测图形正常。线上 11 个关键静态文件哈希、实验／计算 v=12 配置、默认筛选、训练文件完整 SHA-256 与首尾 206 Range、健康接口和既有缓存检查通过。未更改公开快照、HF 固定资产或 D1，未提交或推送 Git。


2026-10-13 增加按 contig 的实验记录状态并调整计算区间样式，Worker 版本 `b53faa1b-1223-4779-8995-0adf77af9b37`（前版 `a6803260-108b-4c8a-bfd2-496718d9f71d`），插件和配置参数为 `v=13`。多 contig 页面增加紧凑选择框，列出每条 contig 的实验 3′ 端记录数；原生坐标导航也会同步状态。计数覆盖整条 contig 的已收录来源，包含隐藏轨道，不根据当前视窗的特征或信号推断。零记录、缺少计数元数据、未收录实验轨道分别表述；原生读取错误保留。空实验轨道不自动删除，零记录不表示不存在终止子或没有测序覆盖。

静态配置的计数来自公开快照中已校验 SHA-256 的 GFF3，并逐来源核对发布总数；动态实验配置通过现有 D1 端点表只读分组统计并核对来源总数。合并参考时按既有序列校验产生的别名映射计数，保留不兼容参考的独立视图。未改动科学文件、HF 固定版本或 D1 数据。计算区间使用钢蓝、柔和琥珀和紫色，字形高度为 9 px；新默认训练／预测轨道高度为 96／80 px，增加文字图例，保留真实区间、链方向及预测分数。已有分享链接的显式轨道高度继续恢复。

8 项计算浏览器测试、6 项插件测试、11 项 Worker 资产测试、7 项页面构建测试及站点／diff 检查通过。同版本本地预览实际验证 NC_003155.5 的 1,159 条记录、NC_004719.1 的零记录、外层与原生坐标切换同步，以及零记录 contig 上注释和预测图形正常、实验轨道保留。线上 11 个关键静态文件哈希与发布产物一致，v=13 配置计数、别名映射和新字形样式通过，健康接口、缓存头及固定参考／训练／预测文件的完整与 206 Range 检查通过。截图保存在工作区 outputs/bted-copy-2026-10-12/contig-ui-tracks.png 和 contig-ui-empty.png。未提交或推送 Git。


2026-10-13 端点旗标与区间箭头，Worker 版本 `d8e5c2ec-31b3-434c-a7be-07c7cd2c38a2`（前版 `b53faa1b-1223-4779-8995-0adf77af9b37`），插件及配置参数为 `v=14`。实验单碱基 3′ 端记录用真实位置的竖线和链方向三角；计算训练／预测区间用连接原始边界的细线、端点短刻度和区间内方向三角。反向视图翻转箭头方向，未知链不加三角。上下文窗口保持可选浅色带，基因注释保持原生样式。采用固定 JBrowse 的 GlyphType 扩展，不增加依赖，沿用原生布局、属性、提示和 SVG 导出；补齐负链旗面的屏幕点击范围，不更改数据坐标。外层图例增加实验端点符号。

9 项计算浏览器测试、6 项插件测试、11 项 Worker 资产测试、7 项页面生成测试及站点与 diff 检查通过，包含正负链／反向绘制、单碱基锚点、区间边界与旗面点击范围。真实同版本本地预览核对了训练与预测线段及实验端点旗标；旗标点击打开原始 BA000030.4:44,108 (+) 的单碱基属性。线上 11 个静态文件哈希、新字形及图例、v=14 实验／计算配置、健康接口、缓存头及固定训练完整文件和各类 206 Range 检查通过。公开快照、HF 固定版本和 D1 数据沿用前版，未提交或推送 Git。截图为 outputs/bted-copy-2026-10-12/glyph-intervals.png。


2026-10-13 预测区间边界与概览对比度更新。预测样式部署版本为 `c80d5f21-92a8-4a5e-a8d4-1d38c473a1bc`（v=15）；最终概览版本为 `a71f1e5c-43c3-489f-895d-c9f07c430e23`（v=16）。固定预测 GFF3 只提供区间、链和分数，无独立单碱基端点。预测区间保留完整跨度，在链方向 3′ 侧边界使用空心旗标；提示显示 1-based inclusive 区间、该边界坐标和模型分数，明确非单碱基 3′ 端位点。实验端点仍为实心旗标。正负链及反向屏幕几何和点击范围测试通过。

全基因组概览改为浅底、紫色方向纹理、深边半透明视窗标记；极窄窗口最少 3 px 可见标记，不改变导航坐标。外层增加当前视窗图例，缩放轨道及滑块加强对比。实际本地预览验证概览标记随坐标导航移动，截图 outputs/bted-copy-2026-10-12/overview-contrast.png。参考序列展示未改动。9 项计算浏览器、6 项插件、11 项 Worker、7 项站点生成测试及语法、站点检查通过；线上 11 个关键文件 SHA-256、v=16 配置与预测提示、健康、缓存及各类固定资产 Range 核验通过。未修改科学文件、HF 固定版本或 D1，未提交或推送 Git。


2026-10-13 将实验计数移到轨道标题，Worker 版本 `f6f2eab3-208a-4db7-b958-e876a546fd6a`（前版 `a71f1e5c-43c3-489f-895d-c9f07c430e23`），插件及配置参数 v=17。移除外层 Contig／记录状态／概览说明栏及实验端点图例；保留原生 contig 坐标导航和计算图例。各实验轨道标题显示自身在当前整条 contig 上的记录数，悬停注明 contig 和统计范围；零记录、计数未知和跨 contig 视窗有独立表述。原生坐标变化经 MobX reaction 同步，轨道标题挂载和重新挂载时补齐徽标，不修改轨道配置名称或科学数据。

9 项计算浏览器、6 项插件、11 项 Worker、7 项页面生成测试，语法、站点和 diff 检查通过。真实同版本预览验证 NC_001318.1 的 1,423 条、NC_000948.1 的 6 条及 NC_001904.1 的 0 条；788×864 窄屏标题计数可见，外层两块信息移除。截图 outputs/bted-copy-2026-10-12/track-header-counts.png。线上 11 个静态文件哈希、v=17 实验及计算配置、健康、缓存及固定资产 Range 核验通过。公开快照、HF 固定版本与 D1 沿用前版，未提交或推送 Git。


2026-10-13 计数图标与概览梯形框，Worker 版本 `39730e65-6936-4ba7-8ae8-6ae09c24bbf8`（前版 `f6f2eab3-208a-4db7-b958-e876a546fd6a`），插件及配置参数 v=18。轨道计数徽标改为中性灰色空心旗子，悬停明确说明当前整条 contig 上该来源的正负链记录合计。实验特征的链向颜色保持原样。概览到当前视窗的原生梯形框仍然存在，之前的浅色填充与边线在新背景上不易辨认；本次以浅底、半透明紫色填充及清晰轮廓恢复对比度，沿用原生导航几何，不修改数据坐标。

9 项计算浏览器、6 项插件、11 项 Worker 测试及语法、站点、diff 检查通过。真实同版本本地预览核对了梯形框与 1,423 条计数的灰色空心图标，截图 outputs/bted-copy-2026-10-12/neutral-count-trapezoid.png。线上 11 个关键静态文件哈希、v=18 实验／计算配置、健康、缓存及固定资产完整校验与 206 Range 核验通过。未修改科学文件、HF 固定版本或 D1 数据，未提交或推送 Git。


2026-10-13 完成计算轨道命名、按 contig 计数和预测跨度说明，Worker 版本 `7f921719-4c5d-4a8d-98cf-65b37f0f2b7f`（前版 `39730e65-6936-4ba7-8ae8-6ae09c24bbf8`），插件及配置参数为 `v=19`。训练轨道改名为 `BATTER · augmentation / Rfam regions`；实验端点仍以 records 计数，增强、Rfam 和预测轨道以 regions 计数。计算计数覆盖当前整条 contig、合并正负链，不随缩放或显示筛选变化。增强计数区分 OTU 与 Rfam，并排除两种上下文窗口；预测计数从已校验的 tabix 索引统计读取，无法验证时显示 Count unavailable，不伪装成零。

修正了真实发布文件中 `rfam_training_window` 未被旧逻辑识别的问题，使 Rfam 上下文窗口默认隐藏并受 Show sequence context windows 统一控制。预测提示增加 1-based inclusive 区间长度。GCF_000009765.2 的核查位置包含 641819–641869（+，51 bp）和 641823–641866（−，44 bp）两个不同长度的原始预测区间；绘图按相同比例保留真实边界，空心旗标位于各区间链方向的 3′ 侧边界，反向浏览时方向随视图翻转。

11 项计算浏览器、6 项插件、11 项 Worker、7 项页面构建测试及全库 77 项测试通过（6 项按既有条件跳过）；站点、语法、diff 和 Wrangler dry-run 检查通过。真实同版本预览验证了主 contig 的 110 个增强／Rfam 区间（OTU 105、Rfam 5）、10,961 个预测区间和 1,159 条实验记录；第二条 contig 分别显示 0、129 和 0。截图保存在 outputs/bted-finish-2026-10-13/region-counts-main.png、region-counts-second-contig.png 和 region-counts-reversed.png。线上 11 个关键文件哈希、v=19 配置、健康、缓存和固定资产 Range 校验通过。公开快照、HF 固定版本和 D1 数据沿用前版，未提交或推送 Git。


2026-10-13 将计算区间改为窄条状，Worker 版本 `1a1a6fd1-686b-4356-92f4-9ec82c4de547`（前版 `7f921719-4c5d-4a8d-98cf-65b37f0f2b7f`），插件及配置参数为 `v=20`。OTU 增强、Rfam 训练和预测区间以居中的低饱和度实心窄条显示，条宽继续对应原始起止坐标。增强／Rfam 条保留区间内链方向箭头；预测条保留链方向 3′ 侧空心旗标。上下文窗口和实验单碱基端点沿用各自样式。

11 项计算浏览器、6 项插件、11 项 Worker 和 7 项页面构建测试，站点、语法、diff 及 Wrangler dry-run 检查通过。真实同版本预览核对了正负链条宽、方向和预测旗标，截图为 outputs/bted-finish-2026-10-13/interval-bars-v20.png。线上 11 个关键文件哈希、v=20 配置、健康、缓存和固定资产 Range 校验通过。未修改科学文件、HF 固定版本或 D1 数据，未提交或推送 Git。

2026-10-13 统一链向颜色与紧凑旗标，最终 Worker 版本 `d0795386-4dee-4b21-8ded-57a631f360d1`，插件及配置参数为 `v=22`。本轮中间版本 `d0ad8b99-18de-4b48-bb7c-c44c738d6560`（v=21）曾将增强区间改为箭头条；最终按用户要求，OTU 增强、Rfam 和预测都使用与参考注释相同的正链绿／负链红色，并统一为完整实心区间条加 3′ 侧空心旗标。旗杆与条等高，不再上下突出；实验单碱基实心旗标也去掉多余旗杆。反向浏览翻转旗标方向，颜色保持原始链向；未知链区间显示灰色普通条。图例和当前轨道说明同步更新。

11 项计算浏览器、6 项插件、11 项 Worker、7 项页面生成测试，以及站点、语法、diff（识别 Windows CRLF）和 Wrangler dry-run 检查通过。同版本真实本地预览验证了绿色 augmentation 区间和正绿／负红预测区间，截图 outputs/bted-finish-2026-10-13/strand-flags-v22.jpg。线上 11 个关键静态文件 SHA-256 与发布产物一致，v=22 实验／计算配置、健康、缓存头及固定参考／训练／预测文件完整与 206 Range 核验通过。公开快照、HF 固定版本和 D1 数据沿用前版，未提交或推送 Git。

2026-10-13 统一轨道标题计数旗帜，Worker 版本 `a1e4db72-45c2-4510-8835-45c16bb5fccf`（前版 `d0795386-4dee-4b21-8ded-57a631f360d1`），插件及配置参数为 `v=23`。augmentation / Rfam 和 predicted 标题的 regions 计数前改用空心旗帜，实验 records 计数前改用同形实心旗帜；统一为中性灰色，旗杆不突出旗面。特征图形、正负链颜色和计数口径沿用前版。

11 项计算浏览器、6 项插件、11 项 Worker、7 项页面测试及站点、diff 和 Wrangler dry-run 检查通过。真实本地预览截图 outputs/bted-finish-2026-10-13/count-flags-v23.jpg 已核对三条标题图标。线上 11 个关键文件 SHA-256、v=23 实验／计算配置、健康、缓存及固定资产完整／206 Range 核验通过。科学文件、公开快照、HF 固定版本和 D1 数据沿用前版，未提交或推送 Git。

2026-10-13 将旗帜样式应用到轨道内部特征，Worker 版本 `eaa22fd2-41d3-4ae1-a17e-037268ac756d`（前版 `a1e4db72-45c2-4510-8835-45c16bb5fccf`），插件及配置参数为 `v=24`。OTU augmentation、Rfam 和 predicted 的已知链 region 改为独立空心旗帜，实验单碱基端点使用同形实心旗帜；去掉 region 实心条及突出的旗杆。正链绿、负链红，反向视图只翻转旗帜方向。region 仍锚定原始链方向的 3′ 侧边界，实验端点仍锚定原始单碱基中心；未知链 region 保留灰条。原始区间、分数和属性保留，参考基因注释维持原生图形。

11 项计算浏览器、6 项插件、11 项 Worker、7 项页面测试及站点、语法、diff 和 Wrangler dry-run 检查通过。真实同版本预览核对空心／实心图形，并点击 augmentation 空心旗帜打开 `NC_003155.5:641,814..641,872 (+)` 的原始 59 bp 区间及属性。截图为 outputs/bted-finish-2026-10-13/region-flags-v24.jpg。线上 11 个关键文件 SHA-256、v=24 实验／计算配置、健康、缓存及固定资产完整／206 Range 核验通过。科学文件、公开快照 `8132334`、HF 固定版本和 D1 数据沿用前版，未提交或推送 Git。

2026-10-13 参考 RAPPTOR 补齐旗杆，Worker 版本 `281dc73a-ff96-4f04-a3f4-0dee3a0d3ff0`（前版 `eaa22fd2-41d3-4ae1-a17e-037268ac756d`），插件及配置参数为 `v=25`。参考 promoter 当前源码的上部旗面与向下旗杆比例，BTED 使用 6 px 旗面和 12 px 深灰旗杆；旗杆顶端与旗面顶部齐平，上方不留突出的短线。augmentation／Rfam、predicted 继续为空心旗面，实验端点继续为实心旗面，原始链向绿色／红色与锚点坐标保持。增强轨道的原生布局高度由 9 px 调为 14 px，容纳完整旗杆；标题计数图标及图例同步补杆。

11 项计算浏览器、6 项插件、11 项 Worker 测试及站点、diff 检查通过。测试覆盖正负链与反向视图的旗面、旗杆、锚点和点击横向范围；真实同版本预览核对全部三条轨道，截图为 outputs/bted-finish-2026-10-13/region-flag-poles-v25.jpg。线上 11 个关键文件 SHA-256、v=25 实验／计算配置、健康、缓存及固定资产完整／206 Range 核验通过。公开快照、HF 固定资产、科学文件及 D1 数据沿用前版，未提交或推送 Git。

2026-10-13 为计算 region 补回完整横条，Worker 版本 `9780f53d-5c09-44b2-ab34-b7eeff426de7`（前版 `281dc73a-ff96-4f04-a3f4-0dee3a0d3ff0`），插件及配置参数为 `v=26`。augmentation／Rfam 和 predicted 在原始起止边界间显示 3 px 实心横条，连接 3′ 侧空心旗帜的旗杆底部。保留上部空心旗面、向下旗杆、正绿负红与反向视图方向；实验单碱基端点继续使用实心旗帜。点击范围覆盖整段横条与旗帜，图例和轨道说明同步更新。

11 项计算浏览器、6 项插件、11 项 Worker 测试及站点、diff 检查通过。真实同版本预览核对 59 bp augmentation 及不同长度的正负链预测横条，并点击 augmentation 横条打开原始 `NC_003155.5:641,814..641,872 (+)` 属性。截图为 outputs/bted-finish-2026-10-13/region-bars-flags-v26.jpg。线上 11 个关键静态文件 SHA-256、v=26 实验／计算配置、健康、缓存与固定资产完整／206 Range 核验通过。科学文件、公开快照、固定 HF 资产和 D1 数据沿用前版，未提交或推送 Git。

2026-10-13 精简页面说明并恢复原生紧凑轨道标题，Worker 版本 `53f15378-d202-488d-8681-5940980d224f`（v=27）。移除浏览器标题下的轨道菜单说明、重复栏目副标题和常驻提示；计数口径与科学含义集中在 Data notes 和悬停信息。内嵌浏览器使用原生 overlapping 标签，保留 records／regions 计数。导航梯形采用 32% 紫色填充及不透明 1.5 px 边框，在内嵌和完整浏览器生效。About track 隐藏内部 Source ID。实际线上核对首页、目录搜索、GCF_000012525.1、GCF_000739105.1 的紧凑计数与完整浏览器梯形；截图为 outputs/bted-finish-2026-10-13/compact-tracks-copy-v27.png 和 full-browser-trapezoid-v27.png。该版完整自动线上校验因计算配置请求超时未完成；最终 v=29 已重新核验通过。

2026-10-13 完成 HF metadata 迁入 D1，最终 Worker 版本 `14cfc356-a37d-4d65-8085-dea5971c163d`，插件与配置参数为 `v=29`。中间 v=28 界面版本为 `78094750-bdfe-40cb-bbe9-202da557df4b`，移除 About track 的重复端点说明；v=29 同时移除弹窗标题中的内部来源编号，保留 PMID 与科学信息。42,923 个基因组完整 metadata、42,904 个计算目录条目及 457,805 条文件索引已导入隔离新表，网站目录和计算 metadata 改读 D1。参考长度的已验证叠加信息保留在目录头中，与原网站目录完全一致。数据库约 364 MB，原实验表和访问统计表沿用，科学文件与大型溯源归档仍在原固定 HF 地址。导入备份、激活条件和核验口径见 [D1 metadata](D1_METADATA.md)。

78 项 Python 测试通过（6 项按既有条件跳过），22 项 Node 测试通过；目录修正后的完整 SQL 本地验证、远程计数／字节／62 个原始 metadata 哈希及完整目录头均通过。线上 15 个静态文件与发布产物逐字节一致，D1 全目录及 5 个计算 metadata 接口样本匹配固定快照；健康、配置、缓存、训练完整文件 SHA-256 和参考／训练／预测 `206` Range 通过。实际界面核对了完整目录、GCF_000009765.2 搜索和 9,119,895 bp 参考长度、1,159 records／110 regions／10,961 regions、正绿负红的空心旗帜加横条、About track 与分享。截图为 outputs/bted-finish-2026-10-13/about-track-v29.png、d1-catalogue-search-v29.png、d1-browser-tracks-v29.png。公开快照 `8132334` 与科学资产固定版本未变；未提交或推送 Git。

2026-10-14 优化 D1 日常读取，Worker 版本 `766d8680-60c8-475b-a3cb-14d6fb1b00cb`，插件与配置保持 v=29。固定快照的目录、metadata 和计算配置成功响应使用 24 小时边缘缓存；复用既有 60 秒内存缓存合并 release／genome 查询，实验静态页面跳过 HF metadata 查询。目录改用不重叠的主键范围，完整冷加载读取 430 个目录页及 1 个 release 行。缓存按快照与插件版本隔离，忽略无作用查询参数，仍在命中前拒绝错误 revision 和任意 URL。

25 项 Node 与 11 项 Worker Python 测试、Markdown 链接、diff 和 Wrangler dry-run 通过。线上目录、metadata、config 均验证 MISS→HIT，完整目录与既有发布产物相同；错误参数保持 400／409，文件 `206` Range 和三项静态文件哈希通过。证据为 outputs/bted-finish-2026-10-13/verify_d1_cache_2026_10_14.json；生产只读测量为 d1-query-cost-2026-10-14.json。免费额度、统计写入、缓存淘汰和单库容量预算见 [D1 metadata](D1_METADATA.md)。未修改科学文件、固定快照、数据库内容或访问计数口径，未提交或推送 Git。
