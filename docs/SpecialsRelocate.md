# SpecialsRelocate — 特别篇归位

> 比对本地集数与 TMDB 官方季集数，识别超出范围的剧集并判定特别篇，按 Plex / TMDB 规范移入 Season 00 并重编号。

![version](https://img.shields.io/badge/version-1.0.0-blue)

<img src="../icons/specialsrelocate.png" width="72" alt="icon">

仓库：<https://github.com/2804826634/MoviePilot-Plugins>
安装：插件市场搜「特别篇归位」→ 安装 → 启用

---

自动比对本地剧集集数与 TMDB 官方季集数，识别**超出官方范围的剧集**，
判定其是否属于特别篇（SP / OVA / 总集篇 / 番外 / 特典），确认后按
Plex / TMDB 规范移入 `Season 00` 并重编号，**正片完全不受影响**。

以《无职转生》第一季为例：TMDB 官方 23 集，本地 24 集，
多出的 E24 实为特别篇，插件会把它移到 `Season 00` 并改名为 `S00E01`。

### 一、判定逻辑

**1. 集数比对**

- 扫描季目录，用多种命名规则提取本地集号：`S01E24` / `1x02` / `第 12 集` / `- 24 -` / 独立成词的 `24`；
- 取 TMDB `season/{n}` 接口 `episodes` 数组的**实际长度**作为官方集数（不信 `number_of_episodes` 汇总字段）；
- `本地最大集号 > 官方集数 + 容差` → 该集为**超集**。

**2. 特别篇判定（三重证据加权）**

| 证据 | 权重 | 说明 |
| --- | --- | --- |
| 文件名关键词 | 0.55 | `SP / OVA / 总集篇 / 特别篇 / 特典 / 番外 / 总集編` 等 |
| 时长显著偏离 | 0.30 | 明显短于或长于正片中位数（需 ffprobe） |
| TMDB Season 0 标题匹配 | 0.85 | 与该剧 Season 0 条目标题做归一化互查 |

置信度 ≥ 阈值（默认 0.5）才判为特别篇并执行迁移；不足则**仅在报告里列出，不动文件**。

**3. 安全设计**

- **默认预演模式**（`dry_run=True`），只出报告不落盘；
- **季号解析不出就跳过**，绝不用 `0` 兜底猜季；
- **第 0 季目录（Season 00 / Specials）本身不处理**；
- 移动采用「复制 → 校验大小 → 删源 → 原子 rename」，中途失败源文件仍在；
- 目标同名自动加 `(1)` 后缀，**绝不覆盖**；
- 附属文件（字幕 / 截图 / NFO）按**集号**匹配同集视频一起迁移；
- 幂等：已迁走的集不会二次处理。

### 二、触发时机

| 方式 | 开关 | 说明 |
| --- | --- | --- |
| 整理完成时自动检查 | `trigger_on_transfer` | 监听 `EventType.TransferComplete`，只查本次入库的那一季，秒级 |
| 定时全量扫描 | `cron` | 默认每天凌晨 4:00 |
| 手动触发 | `get_command()` | 命令面板两个命令：预演扫描 / 直接执行 |
| 保存配置后跑一次 | `auto_run_after_save` | 改完配置立刻验证 |
| REST API | `/scan` `/result` | `GET /api/v1/plugin/SpecialsRelocate/scan?token=xxx` |

### 三、可配置项

**判定**

- `min_confidence`：判定阈值 `0.30` 激进 / `0.50` 均衡（默认）/ `0.70` 保守 / `0.85` 极保守；
- `tolerance`：集数容差。`tolerance=1` 时「官方 23 集 / 本地 24 集」不动；
- `detect_duration`：是否用 ffprobe 探测时长作辅助证据（更准但更慢）。

**动作**

- `dry_run`：预演开关；
- `do_move`：是否移动到 Season 00；
- `do_rename`：是否按 `S00Exx` 重命名；
- `write_nfo`：是否写单集 NFO（`<season>0</season>`）；
- `s00_dir_style`：`Season 00`（Plex 规范，默认）/ `Specials`（Kodi）/ `特别篇`（中文）；
- `cleanup_empty_season`：迁完后季目录空了是否删除。

**范围与通知**

- `media_roots`：媒体库根目录，留空自动读 MP 配置；
- `exclude_paths`：排除路径；
- `notify` / `notify_only_when_changed`。

**TMDB**

- `tmdb_api_key` / `tmdb_api_domain` / `tmdb_locale`：留空自动沿用 MoviePilot 配置；
- 域名默认依次尝试 `api.themoviedb.org` 与 `api.tmdb.org`，含退避重试。

### 四、涉及接口

| 用途 | 接口 |
| --- | --- |
| 事件钩子 | `app.core.event.eventmanager` + `EventType.TransferComplete`（数据含 `meta` / `mediainfo` / `transferinfo`） |
| 插件基类 | `app.plugins._PluginBase`：`init_plugin` / `get_state` / `get_service` / `get_command` / `get_api` / `get_form` / `get_page` / `stop_service` / `update_config` / `post_message` |
| 配置读取 | `app.core.config.settings`（`TMDB_API_KEY` / `TMDB_LOCALE` / `PROXY_HOST` / `LIBRARY_PATHS`） |
| 通知 | `post_message(mtype=NotificationType.Plugin, ...)` |
| 定时任务 | `apscheduler.triggers.cron.CronTrigger` |
| TMDB | `season/{n}` 官方集数、`season/0` 特别篇条目 |

**季目录命名对齐**：MP 默认 `TV_RENAME_FORMAT` 为
`{{title}} ({{year}})/Season {{season}}/{{title}} - {{season_episode}}...`，
所以本插件默认生成 `Season 00`，与 MP 自身产物完全一致。

### 五、实测局限

1. **依赖目录名带 `{tmdbid=xxx}` 或 `tvshow.nfo`**。取不到剧集 id 的目录会被跳过（可用 `NfoGapFill` 补全元数据后重跑）。
2. **官方集数本身可能不准**。少数剧 TMDB 少登记集数，此时应调大 `tolerance`。
3. **`总集数 > 官方` 但内容其实是正片**（例如官方漏登记第 24 集）：提高阈值到 0.70 以上即可只报告不动。
4. **时长证据依赖 ffprobe**。容器内无 ffprobe 时自动跳过该证据，置信度上限降到 0.85（关键词 + S0 标题仍可判定）。
5. **不处理「官方集数 > 本地」的缺集问题**，那是补集逻辑，不属于本插件职责。

---
