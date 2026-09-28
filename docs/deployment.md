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
python scripts/serve_v04_preview.py --site dist/pages-site --port 8769 \
  --proxy http://127.0.0.1:7897
```

打开 `http://127.0.0.1:8769/`，搜索基因组并进入对应页面。预览程序只代理发布清单中列出的固定 Hugging Face 文件；基因组页同时有来源说明、下载和 JBrowse。原有四个来源的正、负链 BigWig 默认可见；其他来源明确写“暂无信号轨道”。`dist/` 是本地组装结果，不提交到 Git。

## 上传 Hugging Face 后固定版本

只上传本版发布文件与新浏览器资产到现有数据集 `liurulong/terminator` 的 `v0.4.0/`。Fuchs、TERMITe 和 Cascino 排除的候选记录留在内部审计归档，不上传；旧版参考资产和 BigWig 不重复上传。上传前后都按 `data/registry/browser_assets.v0.4.0.tsv` 核对大小与 SHA-256，并检查 GFF3、FASTA、BigWig 的跨站读取和 Range 请求。

当前已上传 74 个文件，共 23,229,941 字节；逐文件下载后的大小与 SHA-256 均与本地一致。GFF3、FASTA 和旧 BigWig 的跨站 Range 请求返回 `206`。更新数据时先取得新的 **40 位提交号**，再用 `scripts/build_v04_asset_manifest.py --revision <新提交号>` 重建清单，并把该提交号同时写入 Pages/CI 和 `scripts/stage_site.py --hf-v04-data-base-url` 的参数。校验通过前不部署 Pages 或 Worker。公开版站点只保存网页与 JBrowse 程序，v0.4.0 数据由固定版本地址读取。

## Worker 与 D1

Worker 使用 `BTED_DB` 绑定和 `prototype/accession-range/wrangler.jsonc`。先从发布 GFF3、内部来源清单及已核查的远端资产清单生成本地 bundle；远端对象的大小、SHA-256 与 Range 检查完成后才标记 `--origin-verified`。

```bash
python scripts/import_bted_v03.py materialize-v04 \
  --output-dir dist/v04-d1-bundle --origin-verified
python scripts/generate_bted_d1.py \
  --bundle-dir dist/v04-d1-bundle --output-dir dist/v04-d1-sql
```

将 `dist/v04-d1-sql/` 中的 schema 和编号 SQL 文件依次导入本地 D1，再用 Wrangler 本地启动 Worker。检查 `/api/health` 的 `release_version=v0.4.0`、基因组和来源查询、端点数量、资产代理的 `206` Range 响应。API 返回 JSON 供程序读取；网页不会把原始 JSON 当作用户页面。

若 JBrowse 空白，先检查该组装的配置和参考 FASTA/FAI 是否在固定地址上可读，再查 GFF3/BigWig 的 Range 请求。某研究没有 BigWig 时只应缺少信号轨道，端点轨道仍可正常显示。旧 v0.2.0、v0.3.0 的数据可从 `data/archive/` 校验归档还原。
