# SpecialsFixer — 整理记录季集修正

> 对 **TMDB 查无该集**的整理记录识别特别篇，把季/集修正为 Season 00 与正确集号，再交回 MP 自身流程重新整理。**不自行刮削、不写媒体元数据。**

![version](https://img.shields.io/badge/version-1.0.0-blue)

<img src="../icons/specialsfixer.png" width="72" alt="icon">

仓库：<https://github.com/2804826634/MoviePilot-Plugins>
安装：插件市场搜「整理记录季集修正」→ 安装 → 启用

---

对**TMDB 查无该集**的整理记录，识别其是否为特别篇，确认后把该记录的季数与集数
修正到 `Season 00` 与正确集号，并**重新触发 MP 自身的整理流程**完成归位。

## 职责边界（严格）

| 做 | 不做 |
| --- | --- |
| 判定「TMDB 是否收录该集」 | ✗ 不调用 TMDB 刮削 |
| 识别特别篇（SP / OVA / 特典 / 总集篇） | ✗ 不写 NFO、图片等媒体元数据 |
| 修正 `TransferHistory` 的 `seasons` / `episodes` | ✗ 不自行移动/重命名文件 |
| 调用 `manual_transfer` 触发 MP 重新整理 | ✗ 不干预 MP 的刮削流程 |

元数据仍然只由 MoviePilot 自己的机制生成。测试里有三条断言专门守住这条线
（不含 `manual_scrape`、不含刮削模块、不含 NFO 写入）。

### 一、匹配失败的判定条件

核心原则：**把「确认不存在」与「查不到」严格分开**。网络抖动绝不能当成数据缺失，
否则会误改用户的整理记录。

`MatchProbe` 用三态表达：

| `found` | `season_count` | 含义 | 是否允许修正 |
| --- | --- | --- | --- |
| `False` | 有值 | 接口正常、该季有效，但这一集不在 `episodes` 里 | **允许** |
| `True` | 有值 | 该集本来就在 TMDB 里，属正常正片 | 不允许 |
| `None` | `None` | 网络失败 / Key 无效 / 官方无此季数据 | **不允许** |

`is_match_failure()` 只在第一种情况返回真。任何「取不到」都直接跳过并记 debug 日志。

对应的 TMDB 客户端也做了区分：HTTP 404/422 返回哨兵 `{"_not_found": True}`
（= 确认没有这个资源），网络异常返回 `None`（= 取不到）。两者在上层走完全不同的分支。

### 二、特别篇的识别依据

四路证据加权，满分封顶 1.0：

| 证据 | 权重 | 说明 |
| --- | --- | --- |
| A. TMDB 确认未收录该集 | 0.60 | 必要前提，不满足直接不判 |
| B. 文件名关键词 | 0.55 | `SP / OVA / 特典 / 总集篇 / 番外 / 总集編 / Omake` 等 |
| C. 命中 TMDB Season 0 标题 | 0.80 | 最强证据，官方就把它登记为特别篇 |
| D. 集号越界 | 0.30 | `ep > 官方集数`，如 E24 > E23 |

判定为特别篇需**同时**满足：匹配失败成立（A 成立）且总置信度 ≥ `threshold`（默认 0.6）。

关键安全性：**C 命中时若该集在 TMDB 存在，仍不动** —— 避免文件名带 "SP"
的正片集被误改。测试 `正片集不受影响` 专门覆盖这一点。

实测（《无职转生》94664，TMDB S1=23 集、Season0=3 条）：

| 文件名 | 置信度 | 判定 |
| --- | --- | --- |
| `无职转生 - S01E24 总集篇.mkv` | 1.00 | 特别篇 |
| `[无职转生] - 24 SP [1080p].mkv` | 1.00 | 特别篇 |
| `无职转生 - S01E24.mkv` | 0.90 | 特别篇 |
| `无职转生 - S01E12 SP.mkv`（官方有 E12） | 0.55 | **不动** |

### 三、季数与集数的修正规则

| 字段 | 修正规则 |
| --- | --- |
| `seasons` | 一律改为 `0`（TMDB / Plex 的 Specials 季规范），可配置 |
| `episodes` | 优先取 TMDB Season 0 的**官方集号**（C 证据命中时）；否则顺延到 Season 00 目录的**最小空位**，绝不重号 |
| 目标文件名 | `<标题> - S00Exx`，自动剥离 `{tmdbid=xxx}`，与 MP 默认 `TV_RENAME_FORMAT` 一致 |

写入格式：`episodes` 存 `str(sorted(set(...)))`，即 `[3]`，读回时取列表最大值（与 MP 内部一致）。

已占用的 Season 00 集号通过扫描目标 `Season 00` 目录实际内容得出，不是靠猜 ——
已有 S00E01、S00E02 时新文件会得到 S00E03。

### 四、重新触发整理的调用入口

用的是 MP **官方入口** `TransferChain().manual_transfer()`：

```python
TransferChain().manual_transfer(
    storage="local",
    in_path=in_path,                     # dest 存在则用 dest（重新归位），否则 src
    filetype="file",
    tmdbid=plan.tmdbid,
    mtype=MediaType.TV,
    season=0,                            # 覆盖季号 -> 文件落入 Season 00 目录
    epformat=EpisodeFormat(detail="3"),  # 强制按 S00E03 识别集数
    scrape=True,                         # 刮削交给 MP 自身
    force=True,                          # 允许重整已入库文件
)
```

为什么这三个参数是关键（源码依据 `app/chain/transfer.py`）：

- `season` 非空时执行 `file_meta.begin_season = season` —— 直接覆盖识别到的季号；
- `epformat` 非空时由 `FormatParser.split_episode()` 强制改写 `begin_episode`；
- `force=True` 绕过「已成功转移过就跳过」的短路逻辑（`transferhis.get_by_src`）。

对应 HTTP 层面即 `POST /api/v1/transfer/manual?logid=<id>`，
本插件直接调 Python 接口，避免走网络往返。

改记录的写法用 MP 原生 `@db_update` 装饰器（自动 commit / rollback），只动 `seasons` 与 `episodes` 两个字段。

### 五、识别失败时的兜底处理

| 情况 | 处理 |
| --- | --- |
| TMDB 查询失败（网络 / Key 无效） | **不改记录**，记 debug 日志，等下次巡检 |
| 官方没有这一季的数据 | 不改 —— 无法确认官方集数边界，风险太高 |
| 该集在 TMDB 中存在 | 不改，正常正片 |
| 置信度低于阈值 | 不改，只在数据页列出「非特别篇」供人工判断 |
| `tmdbid` 缺失 / 非电视剧类型 | 跳过 |
| 季号已是 0（已在 Season 00） | 跳过，保证幂等 |
| 集号解析不出 | 跳过 |
| `src` / `dest` 路径均不存在 | 重整前检查，缺路径直接放弃并告警 |
| 重新整理返回失败 | 记录已在上一行改过，日志明确记录失败原因，不静默 |

三道闸门默认全关，逐级放开：

1. `fix_mode = report` —— 只报告，默认值；
2. `auto_apply = false` —— 即使是 `auto` 模式也不执行，需人工触发；
3. `dry_run = true` —— 只展示「将做什么」，不改记录不重整。

**建议路径**：先 `report` 模式巡检，看数据页确认判定 → 再 `dry_run` 看修正预览 → 最后才开 `auto_apply`。

### 六、涉及接口

| 用途 | 接口 |
| --- | --- |
| 整理记录模型 | `app.db.models.transferhistory.TransferHistory`（`seasons` / `episodes` 均为 String，可直接改写） |
| 读写数据库 | `app.db.db_update` 装饰器 / `TransferHistory.list_by_date` |
| 重新整理 | `app.chain.transfer.TransferChain().manual_transfer()` |
| 强制集号 | `app.schemas.transfer.EpisodeFormat` + `app.helper.format.FormatParser` |
| 事件钩子 | `app.core.event.eventmanager` + `EventType.TransferComplete` |
| 插件基类 | `app.plugins._PluginBase` |
| 配置读取 | `app.core.config.settings`（`TMDB_API_KEY` / `TMDB_LOCALE` / `PROXY_HOST`） |

### 七、局限

1. **依赖 `TransferHistory` 存在**。插件修的是整理记录；若记录被清理过，可改用 `SpecialsRelocate`（目录扫描 + 直接改文件）那条路线。
2. **只处理剧集**，电影一律跳过。
3. **`episodes` 取列表最大值**。若一条记录里混了多集且正好是最超集的那集才会命中；若多集混合的记录里有正片也有特别篇，会整条跳过（保守取向，宁漏勿错）。
4. **重新整理会重跑 MP 的完整转移流程**，包括硬链接/移动。大目录下耗时较长，`TRANSFER_TASK_TIMEOUT`（默认 120 秒）需留意。

---
