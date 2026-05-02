# ONBOARDING.md

## 目标

用最少问题完成 Better Review 的初始化：确认用户餐厅、匹配 Google Maps 与 Yelp 来源、发现并确认竞品、抓取首次评论数据、生成首次报告，并设置每日扫描时间。

## 步骤

### 1. 收集餐厅信息

如果还没有 `data/source-profile.json`，询问：

- 餐厅名称
- 餐厅完整地址

拿到信息后使用 `review-source-discovery`，运行来源匹配并保存 `data/source-profile.json`。

如果 Google 或 Yelp 匹配置信度为 `medium` 或 `low`，只问一个澄清问题。若平台暂时无法匹配，继续完成可用平台，并记录数据缺口。

### 2. 确认竞品

使用 `competitor-discovery-management` 生成附近竞品建议，默认 10 miles、5 家。

向用户展示每家竞品的名称、地址或区域、评分、评论数和入选理由。询问用户是否：

- 全部确认
- 删除某几家
- 替换某几家
- 增加指定竞品

如果用户不想手动选择，使用自动排序前 5 家并标记为 `auto_selected`。

### 3. 首次抓取评论

用户确认竞品后，使用 `review-ingestion-storage` 的 `initial` 模式抓取用户餐厅和竞品的公开评论，保存 `data/review-store.json`。

如果评论正文不可见、API 限流或某个平台匹配失败，继续保存评分/评论数快照，并把缺口写入数据文件。

### 4. 首次报告

使用 `reputation-analysis-reporting` 的 `initial` 模式生成 `data/reputation-report.json`。

向用户展示：

- 用户餐厅总体口碑摘要
- Google Maps 与 Yelp 差异
- 高频表扬与投诉
- 竞品对比
- 优先行动建议
- 数据缺口

### 5. 回复建议

使用 `review-response-coaching` 的 `daily` 或 `ad-hoc` 模式生成 `data/response-suggestions.json`。

只给用户餐厅评论提供回复草稿；竞品评论只提供运营信号。

### 6. 设置每日扫描时间

询问用户每天希望几点收到扫描提醒。保存到 `data/preferences.json`，字段建议：

```json
{
  "daily_scan_time": "09:00",
  "timezone": "America/Los_Angeles",
  "weekly_report_day": "Monday"
}
```

## 完成语

初始化完成后告诉用户：

- 已匹配的平台
- 已确认的竞品数量
- 首次抓取到的评论数量和数据缺口
- 每日扫描时间
- 每周一会生成周报
