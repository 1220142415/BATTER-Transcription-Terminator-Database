# Pages、Worker 与 D1 运行手册

仓库当前使用的数据版本是 `v0.3.0`。GitHub Pages 提供网页和 JBrowse 程序；研究文件、参考基因组及浏览器轨道从 Hugging Face 数据集读取。Worker 与网站使用同一个不可变 Hugging Face revision，Worker 代理也从这个版本读取已登记的浏览器文件。

Worker 使用的 D1 绑定名是 `BTED_DB`，数据库名是 `bted-catalogue-v03-preview`。组装前先用 `scripts/stage_site.py` 生成 Worker 静态文件。当前网站和 Worker 固定使用 Hugging Face revision `90651318aedf5a5ca26b8308070927d36fd3d6c9`：

```text
https://huggingface.co/datasets/liurulong/terminator/resolve/90651318aedf5a5ca26b8308070927d36fd3d6c9/v0.3.0
```

上传的 211 个对象按本地大小和 SHA-256 核对。改用新的 Hugging Face revision 时，要同时更新 Pages/CI 工作流中的 `HF_DATA_BASE_URL`，并重新组装网站。不要使用 `main` 等可移动分支地址。

v0.2.0 的 153 个旧文件已打包为 `data/archive/BTED-v0.2.0.tar.gz`，不再逐个放在 `data/public/`。归档自身和归档内文件的 SHA-256 校验文件也在 `data/archive/`。需要查看旧数据时，在仓库根目录把归档解压到临时目录：

```bash
mkdir -p /tmp/bted-v02-archive
tar -xzf data/archive/BTED-v0.2.0.tar.gz -C /tmp/bted-v02-archive
```

PowerShell 示例：

```powershell
tar -xzf data/archive/BTED-v0.2.0.tar.gz -C $env:TEMP
```

在仓库根目录运行 `python3 scripts/validate_bted_v0_3.py`，可检查归档文件、归档内路径和每个旧文件的 SHA-256，也会检查当前 v0.3.0 发布文件。旧文件的逐项清单是 `data/archive/BTED-v0.2.0.SHA256SUMS.txt`。

## 组装 Pages 和 Worker 静态文件

Pages 和 Worker 都用 `scripts/stage_site.py` 组装。JBrowse 页面程序来自 `preview-v0.2.0` 的 Release 归档；组装时会生成 v0.3.0 端点轨道，保留参考序列和信号轨道。来源页、下载链接和 JBrowse 配置由当前发布数据生成，所有文件链接都指向上面的固定 revision。归档必须与配套 SHA-256 文件一起下载并校验。站点只包含网页和 JBrowse 程序，不复制大型研究文件或参考基因组；这些文件由 Hugging Face 提供，Worker 资产代理沿用同一版本。公开文件位于 `v0.3.0/studies/PMID_<pmid>/`，版本目录另含 `release.json` 和 `SHA256SUMS.txt`。

在仓库根目录执行：

```bash
RELEASE_TAG=preview-v0.2.0
HF_DATA_BASE_URL=https://huggingface.co/datasets/liurulong/terminator/resolve/90651318aedf5a5ca26b8308070927d36fd3d6c9/v0.3.0
gh release download "$RELEASE_TAG" \
  --pattern "BTED-v0.2.0-jbrowse-assets.tar.gz" \
  --pattern "BTED-v0.2.0-jbrowse-assets.tar.gz.sha256" \
  --dir dist/jbrowse-release

python3 scripts/stage_site.py \
  --mode pages \
  --release-archive dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz \
  --release-sha256-file dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz.sha256 \
  --hf-data-base-url "$HF_DATA_BASE_URL" \
  --output-dir dist/pages-site

python3 scripts/stage_site.py \
  --mode worker \
  --release-archive dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz \
  --release-sha256-file dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz.sha256 \
  --hf-data-base-url "$HF_DATA_BASE_URL" \
  --output-dir dist/worker-site
```

这些输出目录是本地生成的文件，不要提交到 Git。组装脚本不会覆盖其他程序创建的目录，也不会改写 `site/` 或 `data/`。GitHub Pages 工作流会检查发布数据和站点，再用同一归档组装到 `_site/`；向 `main` 推送或手动运行 `Deploy BTED Pages` 工作流会发布网站。

Pages 组装成功后，完整 JBrowse 包位于 `dist/pages-site/jbrowse/`，供下节的 `--jbrowse-bundle-root` 使用。

在本机检查 Pages 页面时，运行：

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist/pages-site
```

打开 `http://127.0.0.1:8000/`，检查页面、下载链接和 JBrowse。这个静态服务器没有目录 API，也不转发浏览器文件；要检查这些功能，先按下文导入 D1，再启动本地 Worker。

## 生成并导入本地 D1

D1 所需的数据包（bundle）只能从通过检查的发布文件生成。首次准备或更新时，先检查发布目录，再生成数据包。以下资产地址指向一个固定版本，但仍需核实其中的 v0.3.0 文件；旧版检查结果不能代替这一步。`--jbrowse-bundle-root` 指向上节组装并校验过的 JBrowse 目录。`/tmp/bted-v03-*` 是示例路径；生成命令要求输出目录为空，重新运行时要换一个目录名，并修改后续命令中的路径。

```bash
ASSET_ORIGIN=https://huggingface.co/datasets/liurulong/terminator/resolve/90651318aedf5a5ca26b8308070927d36fd3d6c9/v0.3.0

python3 scripts/import_bted_v03.py validate \
  --release-root data/public/v0.3.0

python3 scripts/import_bted_v03.py materialize \
  --release-root data/public/v0.3.0 \
  --output-dir /tmp/bted-v03-planned \
  --asset-origin-base "$ASSET_ORIGIN" \
  --generated-at-utc 2026-08-22T00:00:00Z \
  --jbrowse-asset-inventory data/registry/jbrowse_assets.v0.2.0.json \
  --jbrowse-bundle-root dist/pages-site/jbrowse

python3 scripts/import_bted_v03.py verify-bundle \
  --bundle-dir /tmp/bted-v03-planned
```

这时的数据包状态仍是 `planned_not_verified`。旧检查报告中的文件编号和文件集合与 v0.3.0 不同，不能直接交给 `apply_v03_remote_asset_audit.py`。导入 D1 前，要按下面步骤检查当前远端文件。如果文件内容变了，先放到新的、不可改写的 HTTPS 版本地址，再更新 `ASSET_ORIGIN`。

准备需要上传的公开文件时，用 `scripts/prepare_v03_public_asset_objects.py` 从数据包生成文件清单，并核对本地文件大小和 SHA-256：

```bash
python3 scripts/prepare_v03_public_asset_objects.py \
  --materialized-bundle /tmp/bted-v03-planned \
  --inventory data/registry/jbrowse_assets.v0.2.0.json \
  --jbrowse-bundle dist/pages-site/jbrowse \
  --release-root data/public/v0.3.0 \
  --output-dir /tmp/bted-v03-public-objects
```

生成结果应列出已登记、允许公开的参考序列、注释和信号文件。研究端点 GFF3 及其元数据、研究目录内的关系 TSV 已随仓库版本化发布，不属于这里的远端浏览器文件。如果清单中的文件已在固定版本地址上，可按 `object_path` 逐项重新检查；否则先上传到新的不可改写版本地址。接着运行远端检查：

```bash
python3 scripts/audit_v03_remote_assets.py \
  --asset-objects /tmp/bted-v03-public-objects/ASSET_OBJECTS.json \
  --origin-base "$ASSET_ORIGIN" \
  --output /tmp/bted-v03-public-objects/REMOTE_ASSET_AUDIT.json
```

远端检查要求每个文件的 HEAD 请求返回 `200`、单字节 Range 请求返回 `206`，还会核对文件大小和 `Content-Range`。全部通过后运行：

```bash
python3 scripts/apply_v03_remote_asset_audit.py \
  --bundle-dir /tmp/bted-v03-planned \
  --remote-audit /tmp/bted-v03-public-objects/REMOTE_ASSET_AUDIT.json \
  --jbrowse-asset-inventory data/registry/jbrowse_assets.v0.2.0.json \
  --output-dir /tmp/bted-v03-verified

python3 scripts/import_bted_v03.py verify-bundle \
  --bundle-dir /tmp/bted-v03-verified
```

把 SQL 生成到仓库外的新目录。生成器只接受 `asset_origin_status=verified` 的数据包：

```bash
python3 scripts/generate_bted_d1.py \
  --bundle-dir /tmp/bted-v03-verified \
  --output-dir /tmp/bted-v03-d1-import \
  --batch-size 1000

npx wrangler d1 execute bted-catalogue-v03-preview --local \
  --file /tmp/bted-v03-d1-import/schema.sql \
  --config prototype/accession-range/wrangler.jsonc

for f in /tmp/bted-v03-d1-import/[0-8][0-9]*.sql; do
  npx wrangler d1 execute bted-catalogue-v03-preview --local \
    --file "$f" \
    --config prototype/accession-range/wrangler.jsonc || exit 1
done
```

按文件名顺序导入 SQL。Wrangler 4.125 的本地 D1 执行器不接受 SQL 文件里显式的 `BEGIN`/`COMMIT`；生成器只输出 INSERT 语句，批次由 D1 处理。`.wrangler/` 和 `/tmp` 下的文件是本地临时数据，不要提交。

当前数据包应包含 1 个发布版本、13 篇论文、20 个参考基因组组装、47 条参考序列、22 份来源数据、32 个原始数据登录号、84 个浏览器文件、22 条轨道和 28,399 条端点记录。按现有许可登记，其中 17 条轨道可由 Worker 公开。D1 内容从 v0.3.0 各 study 的 GFF3 和所属压缩 TSV 生成；端点补充信息、基因对应记录及条件观察的原始值仍保存在对应研究文件夹中。

## 启动与检查本地 Worker

先完成 Worker 站点组装和 D1 导入，再从仓库根目录运行：

```bash
npx wrangler dev --local \
  --config prototype/accession-range/wrangler.jsonc \
  --port 8787 --ip 127.0.0.1
```

检查以下 API 返回有效 JSON 和预期数据：

```text
/api/health
/api/stats
/api/catalogue?page_size=1
/api/sources
/api/sources/{source_id}
/api/assemblies
/api/assemblies/{accession}
/api/endpoints?page_size=1
/api/endpoints/{end_id}
/api/assemblies/{accession}/jbrowse-config
```

从 JBrowse 配置中选一个已登记且允许公开的 `asset_key`，填入变量，再检查代理是否支持 HEAD 和单字节 Range 请求：

```bash
ASSET_KEY='<registered_public_asset_key>'
curl -I "http://127.0.0.1:8787/api/assets/$ASSET_KEY"
curl -i -H 'Range: bytes=0-0' \
  "http://127.0.0.1:8787/api/assets/$ASSET_KEY"
```

公开文件应分别返回 HEAD `200` 和 Range `206`；单字节响应应包含 `Content-Range: bytes 0-0/<总字节数>`。`/api/remote-data/{asset_key}` 使用同一代理。未知或非公开的 key，以及 `?url=` 参数，都应被拒绝，避免代理转发任意网址。

## 故障排查与远端预览

- `502 asset_origin_unavailable` 表示 Worker 当前连不上登记的文件地址，不一定是文件登记或校验值有误。先检查 D1 中的 `asset_key`、`logical_path`、公开状态和校验值，再检查本机网络及固定 HTTPS 地址。
- 如果本地 Wrangler 连不上 Hugging Face，可在本机 `127.0.0.1` 上只读提供已校验的文件，并给本地 Worker 设置 `LOCAL_ASSET_BASE`。本地服务器提供文件的路径必须与登记的 `logical_path` 一致：

  ```bash
  python3 -m http.server 8790 --bind 127.0.0.1 --directory /path/to/verified-object-tree
  ```

  ```bash
  LOCAL_ASSET_BASE=http://127.0.0.1:8790 \
    npx wrangler dev --local \
      --config prototype/accession-range/wrangler.jsonc \
      --port 8787 --ip 127.0.0.1
  ```

  Worker 只在本机访问时接受这个 HTTP 地址；地址不能带账号、密码、查询参数或片段。其他请求仍使用固定 HTTPS 地址和允许访问的主机列表。
- 如果 JBrowse 显示空白，检查参考基因组配置、公开的 FASTA/FAI、轨道对应的 GFF3/TBI/BigWig 文件，以及这些文件的 HEAD 和 Range 响应；再查看浏览器控制台。端点轨道应使用 GFF3 adapter，下载地址应包含版本号。
- v0.3.0 下载根目录应以 `studies/PMID_<pmid>/` 为主，并只在根目录放 `release.json` 与 `SHA256SUMS.txt`；不要新增全库 GFF3、`sources.json` 或关系 TSV。组装目录或 ZIP 中若出现 `endpoints.csv`、`endpoints.tsv` 或 `endpoints.bed`，说明生成步骤仍在使用旧下载格式，不能作为当前产物验收。
- 如果 Pages 页面能打开，但目录 API 失败，确认本机已启动 Worker；单独启动静态服务器不会提供 API。Worker 的 JBrowse 页面文件来自 `dist/worker-site/jbrowse/`，大型参考序列和轨道文件由资产代理读取。

部署 Cloudflare preview 前，先组装 `dist/worker-site/`，并用 `CI=1 npx wrangler whoami` 确认当前登录身份，再从仓库根目录执行：

```bash
npx wrangler deploy --config prototype/accession-range/wrangler.jsonc
```

预览地址为 `https://bted-catalogue-v03-preview.bted-v0-3-dynamic-service.workers.dev`。每次部署后重新检查 API 和浏览器文件；2026-08-23 的远端检查记录不能证明现在仍可用。不要把令牌、密码或带凭据的网址写入 Git、命令历史或日志；不要把预览版标为正式发布版，也不要对远端 D1 执行破坏性 SQL。
