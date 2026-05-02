# AUTOMATION.md

## 自动化目标

Better Review 需要两个主动流程：

- 每日扫描：按用户选择时间检查新评论、评分变化和数据缺口变化。
- 每周报告：每周一汇总过去一周表现并输出行动建议。

## 每日扫描

触发条件：

- 到达 `data/preferences.json` 中的 `daily_scan_time`。

执行顺序：

1. 使用 `review-ingestion-storage`，模式为 `daily`。
2. 如果 `data/review-store.json` 中有 `new_review_keys`、评分/评论数变化或新的数据缺口，继续执行。
3. 使用 `review-response-coaching`，模式为 `daily`。
4. 向用户发送每日提醒。

提醒内容：

- 用户餐厅新评论：平台、星级、日期、评论人、正文、回复草稿、内部处理建议。
- 竞品新评论：平台、餐厅、星级、日期、正文、运营信号。
- 数据缺口：平台、原因、是否会重试。

如果没有新评论、评分变化或重要数据缺口变化，不主动打扰用户。

## 每周报告

触发条件：

- 每周一，使用用户本地时区。

执行顺序：

1. 使用 `review-ingestion-storage`，模式为 `weekly`。
2. 使用 `reputation-analysis-reporting`，模式为 `weekly`。
3. 使用 `review-response-coaching`，模式为 `weekly`。
4. 向用户发送周报。

周报内容：

- 本周评论总览
- Google Maps 与 Yelp 平台差异
- 用户餐厅高频主题
- 竞品本周信号
- 评分和评论数变化
- 风险、机会点和下周行动清单
- 数据缺口与重试状态

## 失败处理

- 缺少 API key：告诉用户需要配置凭证，保留已完成的数据，不删除文件。
- API 限流或超时：记录为可重试缺口，下次自动重试。
- key 已存在但运行环境无法解析域名或禁止外部网络：说明这是运行环境外网限制，不是 API key 或餐厅信息错误；保留数据并在后续扫描中重试。
- 平台匹配失败：继续监控已匹配平台，并在用户愿意时重新匹配。
- 评论正文不可见：只基于评分、日期、平台和快照做降级提示，不编造正文。

## 本地数据

自动化流程读写以下文件：

- `data/source-profile.json`
- `data/competitors.json`
- `data/review-store.json`
- `data/reputation-report.json`
- `data/response-suggestions.json`
- `data/preferences.json`
