# 本地组装与运行

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

## Worker 与 D1

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

若 JBrowse 空白，先检查该组装的配置和参考 FASTA/FAI 是否在固定地址上可读，再查 GFF3/BigWig 的 Range 请求。某研究没有 BigWig 时只应缺少信号轨道，端点轨道仍可正常显示。旧 v0.2.0、v0.3.0 的数据可从 `data/archive/` 校验归档还原。
