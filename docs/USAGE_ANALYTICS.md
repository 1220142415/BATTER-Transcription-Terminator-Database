# 访问统计

参照 promoter 项目 RAPPTOR 的公开统计页，BTED 提供 `usage.html`（Worker 上也可访问 `/usage`）。顶部导航和页脚均有 **Usage** 入口。只统计访问次数，不统计独立 IP 或访客。

## 口径

- 成功的 GET HTML 文档打开计一次；刷新会再次计数。
- 仅计首页、基因组目录、Data notes、基因组详情页。合并 `.html` 和无扩展名路径，去掉查询参数。独立首页上线前 `/` 的历史次数来自旧目录页，不迁移为 `/genomes`。
- 排除 API、静态资源、下载、旧入口跳转页、统计页、预取、Range 请求、JBrowse iframe 和已知爬虫。UA 过滤是启发式，不能保证过滤所有自动化访问。
- 国家／地区、区域、城市取自 Cloudflare 的 `request.cf`，忽略客户端地理位置头。IP 归属地为近似位置，可能是代理或 VPN 的出口。
- 不保存原始 IP、User-Agent、访问者标识、坐标或单次访问日志。D1 只保存按 UTC 日期汇总的计数。
- 通过 `ctx.waitUntil` 后台写入；统计失败不阻塞网页。计数从部署启用后开始，无法补回此前访问。
- 日汇总保留 400 天，每日 UTC 03:20 清理过期行；“Available history”指当前保留的历史。

## D1 表

| 表 | 字段 | 主键 |
| --- | --- | --- |
| `analytics_daily_geo` | `day`, `country_code`, `region`, `city`, `views` | 日期、国家／地区、区域、城市 |
| `analytics_daily_path` | `day`, `path`, `views` | 日期、规范化页面路径 |

两张表通过 D1 batch 原子累加，独立于科学数据版本。国家未知时用 `XX`，城市缺失时留空。排行中包含未知访问；国家／地区总数排除 `XX`。城市展示前 50，页面展示前 30。

## 部署

先创建统计表，再发布 Worker：

```powershell
npx wrangler d1 execute bted-catalog --remote --config prototype/accession-range/wrangler.jsonc --file prototype/accession-range/migrations/0003_usage_analytics.sql --yes
npx wrangler deploy --config prototype/accession-range/wrangler.jsonc
```

`BTED_ANALYTICS=on` 启用计数；其他值停止新计数，已有报告仍可读取。`assets.run_worker_first=true` 使 HTML 请求经过 Worker，响应仍由 ASSETS 提供。`GET /api/usage?days=7|30|90|365|0` 返回公开聚合，默认 30 天。统计报表不依赖科学目录的 release selection。

本地验证：`node --test tests/test_usage_analytics.mjs`。地理信息集成验证在 Cloudflare 上完成；本地预览没有真实访客位置。

## 地图来源

`site/assets/usage-world-map.json` 复用 RAPPTOR 的静态地图：Natural Earth 1:110m，微小国家／地区使用 world-atlas 1:50m 补充，公共领域数据。前端直接使用 SVG，无额外运行依赖。色阶按访问次数的对数比例绘制，表格提供准确数值。
