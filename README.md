# MoviePilot-Plugins — 自用 MoviePilot 插件仓库

> 收录三个自用插件：**NFO 与图片差异比对**、**整理记录季集修正**、**特别篇归位**。

![license](https://img.shields.io/badge/license-MIT-green)
![platform](https://img.shields.io/badge/MoviePilot-v2%20%7C%20v3-9cf)
![python](https://img.shields.io/badge/python-3.9%2B-yellow)

在 MoviePilot → `设定` → `插件` → **插件市场** → **自定义仓库** 填入：

```
2804826634/MoviePilot-Plugins
```

---

## 本仓库收录的插件

| 插件 ID | 名称 | 做什么 | 版本 |
| --- | --- | --- | --- |
| `NfoGapFill` | NFO 与图片差异比对 | 本地 NFO / 海报 / 背景图与在线元数据的**内容比对**：缺失补齐、不一致替换、一致跳过 | 1.7.7 |
| `SpecialsFixer` | 整理记录季集修正 | 对 TMDB 查无该集的整理记录识别特别篇，修正季/集为 Season 00 并重新触发 MP 整理 | 1.0.0 |
| `SpecialsRelocate` | 特别篇归位 | 比对本地集数与 TMDB 官方季集数，识别超范围剧集并移入 Season 00 重编号 | 1.0.0 |

三者互不依赖，可单独安装。

### 怎么选：两个「特别篇」插件的区别

这两个插件解决的是同一个现象（番剧多出的第 24 集其实是 SP/OVA/特典，却被并进了正片季），但**介入点完全不同**，不要同时开：

| | `SpecialsFixer`（记录层） | `SpecialsRelocate`（文件层） |
| --- | --- | --- |
| 触发时机 | 整理**已完成**后，发现这集在 TMDB 查不到 | 整理**之前**的目录扫描 |
| 改什么 | 只改 `TransferHistory` 的 `seasons`/`episodes`，再调 MP 官方 `manual_transfer` 重跑 | 直接移动/重命名文件、写 episode NFO |
| 是否刮削 | **不自行刮削**，刮削完全交给 MP 自身机制 | 不碰刮削 |
| 前提 | 必须有对应的整理记录 | 不需要记录，扫目录即可 |
| 风险面 | 小（只改两个字段，出错可回滚记录） | 大（动文件） |
| 适合 | 已在用 MP 正常整理，只想让错的那几集自动归位 | 想脱离 MP 整理链路，自己控制目录结构 |

**建议**：先用 `SpecialsFixer`（保守，交给 MP 走正常流程）。只有当 MP 整理链路本身处理不了、或你要脱离 MP 自行管理目录时，才用 `SpecialsRelocate`。

---

<a id="nfogapfill"></a>

# NfoGapFill — NFO 与图片差异比对插件

> 比对本地 NFO 与在线元数据、海报/背景图：**缺失补齐、不一致替换、一致跳过**。

![version](https://img.shields.io/badge/version-1.7.7-blue)

<img src="icons/nfogapfill.png" width="96" alt="icon">

---

## 它解决什么问题

MoviePilot 官方的「媒体库刮削」（`LibraryScraper`）插件对已有文件只有两档策略：

| 官方模式 | 行为 | 问题 |
| --- | --- | --- |
| 不覆盖已有元数据 | 字段非空、图片文件存在 → 一律不动 | 错的、旧的、残缺的、低清的，永远修不掉 |
| 覆盖所有元数据和图片 | 全部重抓并覆盖 | 连你手工润色的简介、自定义标签、精挑的封面一起冲掉 |

**用户真正想要的往往是中间那一档**：内容不一样就更新，一样就别动。本插件补上了这一档，并且把它作为默认行为，**NFO 字段与图片共用同一套判定**。

之所以必须自建，是因为根因在 MoviePilot 主程序里，而且两个地方撞在同一个逻辑缺陷上：

```python
# app/chain/media.py 的 _should_scrape（官方刮削的最终决策）
if not file_exists:  return True      # 缺失 → 下载
if overwrite:        return True      # 存在 + 覆盖模式 → 无条件重下
else:                return False     # 存在 → 跳过，从不关心内容对不对
```

- **NFO**：`scrape_metadata` 判断「NFO 已存在就跳过」，存量残缺 NFO 永远不会被自动补；而 Emby / Jellyfin 优先读本地 NFO 且**按条目级**判断是否联网，条目一旦有 NFO 就不再补字段——两头都不会帮你修。
- **图片**：判定依据只有「文件在不在」。所以你库里那张 500px 的低清海报、错语言的 logo、甚至放错的图，**只要文件存在就永远不会被换掉**，除非开 `force_all` 把全部图片重洗一遍。

本插件用「内容比对」替代「存在性判断」：NFO 比字段值，图片比内容指纹。

---

## 判定规则

引擎对**每个字段**独立比对，而不是整文件覆盖：

| 本地 | 在线 | 判定 | 动作 |
| --- | --- | --- | --- |
| 空 | 有 | 仅在线有 | **补齐** |
| 有 | 空 | 仅本地有 | 保留（永不删除） |
| 有 | 有，且相同 | 相同 | **跳过**（不产生写入，不动文件 mtime） |
| 有 | 有，且不同 | 不一致 | **替换** |

比对口径（避免误判）：

- 文本：NFKC 归一化 + 反转义 + 压缩空白后比较；**写入时使用原值**，绝不把全角标点改成半角。
- 数值：按数值比较，评分容差 `0.05`（`8.4` 与 `8.40` 视为相同）。
- 日期：只比 `YYYY-MM-DD`。
- 多值字段（genre / studio / director / country）：按**集合**比较，忽略顺序。
- 演员：只比**姓名集合**（角色名或头像变化不足以触发整段重写）。
- 图片：比 **sha256 内容指纹**（详见下节）。

---

## 四种运行模式

| 模式 | 说明 |
| --- | --- |
| `sync` | **默认。** 缺失补齐 + 不一致替换 + 一致跳过 |
| `gapfill` | 只补缺失，任何已有内容都不动（等价官方「不覆盖已有元数据」） |
| `report` | 只输出差异报告，一个字节都不写 |
| `force` | 强制全部覆盖（等价官方 `force_all`，忽略保护名单，慎用） |

> 图片处理是**独立开关**（`image_mode`），与上面四种模式正交，互不干扰。

## 图片补全

### 支持的全部类型（8 类 + 季图）

落盘命名遵循 **MP / Kodi / Jellyfin 三者共同认可**的约定（对照 MP `app/chain/media.py` 的
`IMAGE_ALIASES`、`ScrapingMetadata` 与季目录命名规则实现）：

| 配置里的选项 | 落盘文件 | 适用 | 数据来源 |
| --- | --- | --- | --- |
| 海报（poster） | `poster.jpg` | 电影、剧集目录 | TMDB `posters` |
| 背景图（backdrop） | `backdrop.jpg` **+** `fanart.jpg` | 电影、剧集目录 | TMDB `backdrops` |
| 徽标（logo） | `logo.png` | 电影、剧集目录 | TMDB `logos` |
| 缩略图（thumb） | `thumb.jpg` **+** `landscape.jpg` | 电影、剧集、季目录 | **fanart.tv** `moviethumb` / `tvthumb` / `seasonthumb` |
| 横幅图（banner） | `banner.jpg` | 电影、剧集、季目录 | **fanart.tv** `moviebanner` / `tvbanner` / `seasonbanner` |
| 光盘图（disc） | `disc.png` | **仅电影目录** | **fanart.tv** `moviedisc` |
| 透明艺术图（clearart） | `clearart.png` | 电影、剧集目录 | **fanart.tv** `hdmovieclearart` 等 |
| 单集剧照（thumb） | `<视频文件名>.jpg` | 单集（需该集有 NFO） | TMDB `stills` |
| 季图 | **两处都写**：`<季目录>/poster.jpg` + `<剧集根目录>/seasonNN-poster.jpg` | 季 | TMDB `posters`（**跟随「海报」一起处理，不单独成项**） |

> **命名与 MP 官方的关系（v1.7.5 起严格对齐）**：本插件的类型集合与文件名，逐项对照 MP 的
> `app/chain/media.py`（`IMAGE_ALIASES`、各 `ScrapingTarget` 的允许集合）与其官方测试
> `tests/test_mediascrape.py` 实现：
> - MP 的 `IMAGE_ALIASES` 规定 `backdrop ⇄ fanart`、`thumb ⇄ landscape` 互为别名（同一张图写两个名），
>   所以 `thumb.jpg` 与 `landscape.jpg` 是**同一张图的两份副本**，`backdrop.jpg` 与 `fanart.jpg` 同理。
> - MP 的 `tv`（剧集）允许集合里**没有 disc**，所以剧集目录不写 `disc.png`；只有电影写。
> - MP 的季图片类型是 `poster / backdrop / banner / thumb / landscape`。其中 **季 backdrop 没有任何数据源**
>   （TMDB 的季图片接口只返回 `posters`，fanart 的季接口只有 `seasonposter / seasonbanner / seasonthumb`），
>   写了也是空转，所以本插件不列它。

> **季图的落盘规则（v1.7.6 起完全对齐 MP）**：刮某一季时**两处都写**，与 MP 的 `_get_target_fileitems_and_paths` 行为一致 —— 该季自己的目录内写通用名（`poster.jpg` / `banner.jpg` / `thumb.jpg` + `landscape.jpg` 别名，Jellyfin/Kodi 读这个），**同时**在剧集根目录写 `season01-poster.jpg` / `season01-banner.jpg` / `season01-thumb.jpg`（兼容只认根目录 `seasonNN-` 命名的服务器）。
>
> 季 0（特别篇）在根目录写作 `season-specials-poster.jpg` —— 与 MP 的 `TmdbScraper.get_season_poster` 及 `FanartModule` 的写法一致。
>
> **根目录副本不带别名**：MP 的 `_expand_with_aliases` 遇到 `season` 前缀会直接跳过，所以根目录只会出现 `season01-poster/-banner/-thumb`，不会有 `season01-fanart.jpg` 或 `season01-landscape.jpg`。本插件保持一致。
>
> 某一季在线没有海报时会**明确标注缺失**（报告里显示「N 季在线没有海报，已跳过」），并且**绝不回退**用剧集海报或其它季的海报顶替。

> **选图策略（v1.7.7 起与 MP 的取图口径对齐）**：海报 / 背景图 / 徽标来自 TMDB，
> 挑选规则是**只按语言优先级**（本语言 → 无文字版 → 英文 → 其它），同语言档位内
> **取 TMDB 返回顺序里的第一条**（TMDB 本身按官方推荐度排序，越靠前越"钦定"）。
> 早先版本还会比「分辨率越大越好 → 社区评分 → 投票数」，会挑到与 MP 不同的图
> （表现为"同一部剧两边图不一样"），现已去掉这几级排序。
>
> 根目录 / 季目录的 `thumb`、`landscape` 取自 **fanart.tv 的横版缩略图**
> （`moviethumb` / `tvthumb` / `seasonthumb`），而不是 TMDB 的 `stills`。
> TMDB 的 `stills` 是**剧照**（横竖构图都有、多为竖版人物特写），只用于**单集**缩略图。
> 早先版本把根目录的 thumb 也接到 `stills`，写出来的 `thumb.jpg` 经常是竖图 ——
> 这是与 MP 的一处偏离，已修正。
>
> ⚠️ **与 MP 的两处可解释差异**（不是故障）：
> 1. **内容可能不同**：MP 对根目录的 `poster` / `backdrop` / `logo` 直接取 TMDB
>    **主记录里那一张**（`MediaInfo.poster_path` / `backdrop_path` / `logo_path`，即 TMDB 钦定图），
>    本插件则从 `images` 接口的候选里按语言挑。语言优先能保证拿到**中文**图
>    （这是刻意的：有中文 logo / 海报时常更好），但与 MP 的钦定图不保证逐字节相同。
> 2. **产出类型可能不同**：MP 的 `thumb` / `landscape` 靠 fanart 模块动态注入
>    （`tvthumb` → `thumb_path`），**该剧 fanart 没有对应数据时就不写**；
>    本插件同样如此 —— 所以「MP 那边没有 `landscape.jpg`」通常是 fanart 缺数据的正常结果。

> **图片来源优先级（`image_sources`，v1.7.7 新增）**：同一类图两个源都能提供时，按设定顺序取
> **第一个命中**的，没给的留给下一个源兜底。默认 **`tmdb,fanart`（TMDB 优先，fanart.tv 其次）**，
> 可切换为 `fanart,tmdb`、`tmdb`（只用 TMDB）、`fanart`（只用 fanart）。
> 日志里会打印本轮实际使用的顺序（`图片来源优先级：TMDB → fanart.tv`）。
>
> ⚠️ **优先级只对「两边都有」的类型起作用**。数据源本身能力不同：
> TMDB 只有 `posters` / `backdrops` / `logos`（单集另有 `stills` 剧照）；
> 而**横幅图、光盘图、透明艺术图、横版缩略图（thumb / landscape）只有 fanart.tv 有**。
> 所以这几类无论顺序如何都只能取 fanart 的 —— 别以为「换成 fanart 优先后海报变了」。

### fanart.tv 那几类怎么配置

光盘图 / 横幅图 / 透明艺术图 / 横版缩略图 **只有 fanart.tv 有**（TMDB 只提供 海报 / 背景图 / 徽标 / 剧照）。
本插件会**自动沿用 MoviePilot 里配置的 `FANART_API_KEY`**（MP 自带默认值，所以一般什么都不用填），
语言偏好也跟随 MP 的 `FANART_LANG`（默认 `zh,en`）—— 优先要中文版，其次英文，再按社区点赞数。
键名映射与 MP 自己的 `FanartModule._FANART_NAME_MAP` 一致。

两点注意：

- 这几类**需要 TMDB API Key 走直连**（宿主刮削通道拿不到，插件会在日志里提醒）；
  剧集按 **thetvdb id** 查询 fanart.tv（插件会自动通过 TMDB 换算）。
- fanart.tv 是社区共建，**冷门影片这几类可能就是没有** —— 那不是故障。
  另外尚未支持 `characterart`（人物图），需要的话再说。

三种图片处理档位（`image_mode`）：

| 值 | 行为 |
| --- | --- |
| `sync` | **插件默认。** 缺失补齐 + 不一致替换 + 一致跳过 |
| `missing` | 只补缺失图片，已有图一律不碰 |
| `off` | 完全不处理图片（CLI 默认） |

**「一致」怎么判断？靠指纹清单。** 每次写入后，插件把「这张图来自哪个在线 URL、内容 sha256」记进 `image_manifest.json`：

```json
{
  "电影/星际穿越 (2014)/poster.jpg": {
    "url": "https://image.tmdb.org/t/p/w780/abc.jpg",
    "sha256": "9f2c…",
    "size": 184320,
    "at": "2026-10-05 23:10:02"
  }
}
```

下一轮运行时：

- URL 与 sha256 都对得上 → **判定相同，零下载跳过**（稳态下几乎不产生流量）；
- URL 变了（TMDB 换了封面）或本地文件被改过 → 重新下载并替换；
- 没有记录（首次运行）→ 下载比对，这就是「首轮有流量开销」的来源。

加个 `size`/`at` 字段只是方便你人肉排查，判定只用 URL + sha256。

另外，`<lockdata>true</lockdata>` 的条目**连图片一起跳过**（Kodi 语义：整条锁定）；`<lockedfields>` 里写 `poster`、`thumb` 也能单独锁住对应类型。

---

## 性能与速度

### 时间花在哪里

| 阶段 | 是否走网络 | 说明 |
| --- | --- | --- |
| 扫描 NFO、读写文件 | 本地 | 很快，不是瓶颈 |
| 比对字段、算图片指纹（sha256） | 本地 | 也很快（单张图才几百 KB） |
| **TMDB / fanart.tv 查询** | 网络 | 每个条目 2～4 次请求，受限速控制 |
| **图片下载** | 网络 | 首轮、或改了画质档之后最耗时的一项 |

### 怎么加快

1. **调大「并发数」**（默认 `4`，可到 `8`）：同时处理多个 NFO，把上面两项网络等待重叠起来。
   对本地磁盘与 CPU 压力很小，所以开着基本只有好处。
2. **首次运行先用「只补缺失」**（`image_mode = missing`）：只补空缺的图，先不下载已有图去比对，
   首轮能省掉全部下载流量。
3. **分批跑**：把「媒体库目录」先填成一个子目录，跑顺了再全量。
4. **稳态几乎不花时间**：图片靠指纹清单（`image_manifest.json`）判定，内容没变就**零下载**；
   真正每次都要联网的只有元数据查询。

> **并发下的限速**：单线程时 TMDB 最快 4 请求/秒；并发时按并发数等比放宽，
> 但有 **12 请求/秒的硬上限**（仍远低于 TMDB 的限制），避免把接口打到限流。
> 限速器是**全局**的 —— 不会因为开多线程就把请求速率翻倍。

---

## 三层保护

1. **NFO 内锁定** —— 遵循 Kodi 语义，遇到 `<lockdata>true</lockdata>` 或 `<lockedfields>` 时跳过对应字段与图片（可用 `respect_lock` 关闭）。
2. **保护字段** —— 配置 `protect_fields` 的字段（如 `plot,actor`）永远只补不换，保住你手工润色的内容。
3. **演练模式** —— `dry_run` 下只生成「将要修改」的清单，不落盘。

此外，写入前可选自动备份到 `<媒体库根目录>/.nfo-backup/`（NFO 与图片都会备份，首次备份为准）。

---

## 安装

### 方式 A：从插件市场安装（推荐）

1. MoviePilot → `设定` → `插件` → 右上角 **插件市场** → 打开 **自定义仓库**；
2. 填入本仓库地址：

   ```
   2804826634/MoviePilot-Plugins
   ```

   或通过环境变量固定（`docker-compose.yml`）：

   ```yaml
   environment:
     - PLUGIN_MARKET=2804826634/MoviePilot-Plugins
   ```

3. 在市场里找到你要的插件 → 安装 → 启用。

> 也可把本仓库地址**追加**到已有的 `PLUGIN_MARKET`（多个仓库用英文逗号分隔），不会影响官方市场。
>
> **仓库改名提示**：本仓库原名 `moviepilot-nfo-gapfill`，已更名为 `MoviePilot-Plugins`（对齐官方插件库命名惯例）。GitHub 会自动把旧地址重定向到新地址，但如果你在 `PLUGIN_MARKET` 里写死了旧名，建议顺手改成新名。

### 方式 B：本地插件仓库（离线、可版本管理）

```bash
git clone https://github.com/2804826634/MoviePilot-Plugins.git /path/to/mp_plugins
```

```yaml
# docker-compose.yml
volumes:
  - /path/to/mp_plugins:/mp_plugins:ro
environment:
  - PLUGIN_LOCAL_REPO_PATHS=/mp_plugins
```

重启后本地仓库会出现在插件市场来源中，可正常安装/卸载/升级。

### 方式 C：单文件手动放入（最省事，升级镜像会丢）

```bash
docker cp plugins.v2/nfogapfill/__init__.py moviepilot-v2:/config/NfoGapFill.py
# 查真实插件目录（不同镜像可能是 /app/app/plugins 或 /app/plugins）
docker exec -it moviepilot-v2 python -c "import app.plugins,os;print(os.path.dirname(app.plugins.__file__))"
docker exec -it moviepilot-v2 mv /config/NfoGapFill.py <上一步输出的目录>/
docker restart moviepilot-v2
```

---

## 配置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | 关 | 启用插件 |
| `onlyonce` | 关 | 保存配置后立即运行一次 |
| `notify` | 开 | 完成后发送通知 |
| `mode` | `sync` | 处理模式，见上表 |
| `cron` | **空** | 执行周期。**留空 = 每周日凌晨 3 点跑一次**；想更频繁再自己填 5 位 cron |
| `concurrency` | `4` | 并发数（1 = 顺序执行）。详见下面「性能与速度」 |
| `dry_run` | 关 | 演练模式，不写盘 |
| `respect_lock` | 开 | 尊重 NFO 内 `lockdata` / `lockedfields`（NFO 字段与图片都受它保护） |
| `backup` | 开 | 写入前备份 NFO 与图片到 `.nfo-backup/` |
| `cast_limit` | `20` | 演员写入上限，可选 `10` / `20` / `30` / `50` / **全部**（`0` = 不限制） |
| `paths` | 空 | 媒体库目录，每行一个；**行尾可加 `#电影` / `#电视剧` 限定该目录的类型**（见下） |
| `exclude_paths` | 空 | 排除路径片段，命中即跳过 |
| `protect_fields` | 空 | 保护字段：照常比对，但**只补不换**，永不覆盖已有内容 |
| `tmdb_api_key` | 空 | TMDB API Key。**留空 = 自动读取 MoviePilot 里配置的 `TMDB_API_KEY`** |
| `language` | `zh-CN` | 元数据语言（`zh-CN` / `zh-TW` / `en-US` / `ja-JP`） |
| `cert_country` | `US` | 分级地区码，**单选下拉**：决定 NFO 的 `<mpaa>` 取哪个地区的分级（见下） |
| `image_mode` | `sync` | 图片处理：`sync` / `missing` / `off`，见上节 |
| `tmdb_image_kinds` | 四项全选 | **TMDB 提供的图片类型**（多选下拉）：海报 / 背景图 / 徽标 / 剧集缩略图（单集剧照） |
| `fanart_image_kinds` | 五项全选 | **fanart.tv 提供的图片类型**（多选下拉）：横版缩略图 / 横幅图 / 光盘图 / 透明艺术图 / 别名 landscape |
| `image_quality` | `standard` | 画质档：`standard`（海报 w780 / 背景图 w1280 / 徽标 w500）或 `original`（最清晰、体积大） |
| `image_sources` | `tmdb,fanart` | **图片来源优先级**：`tmdb,fanart`（TMDB 优先）/ `fanart,tmdb` / `tmdb`（只用 TMDB）/ `fanart`（只用 fanart） |

> **图片类型拆成两个下拉（v1.7.7 起）**：一个列 **TMDB 能给的**（海报 / 背景图 / 徽标 / 单集剧照），
> 一个列 **fanart.tv 才有的**（横幅图 / 光盘图 / 透明艺术图 / 横版缩略图）。
> 最终处理的是**两个下拉的并集** —— 这样「哪些类型来自哪个源」在界面上一眼可见，不用再猜。
> 「缩略图（`thumb`）」两边都列了：电影 / 剧集 / 季目录的 thumb 取自 fanart 的横版图，
> 单集的 thumb 取自 TMDB 的该集剧照，**勾任意一边即可生效**（同名文件只写一次）。
> 两个下拉**都清空 = 不处理任何图片**（不会偷偷回退成全选）。
> 旧的单一 `image_kinds` 键仍被兼容：没有两个新下拉时按老值迁移（自动拆到两个下拉里）。

> 🔧 **升级自 v1.2.0 的会自动修好一个历史脏值**：那一版用复选框渲染图片类型，而宿主当时把它当单值处理，
> 于是配置里存成了 `true` / `false`，界面上会冒出一个写着 `false` 的怪 chip。
> v1.4.0 起会在插件加载时把这类历史值收敛成合法列表并回写配置（`true` → 全选，`false` → 全不选）。

### 让某个目录「只认电影」或「只认电视剧」

在「媒体库目录」的行尾加 `#电影` 或 `#电视剧` 即可：

```
/media/link/电影#电影
/media/link/电视剧#电视剧
/media/link/纪录片          ← 不加 # 则两种类型都处理
```

加了后缀的目录只会处理对应类型的 NFO，**该目录下类型不符的 NFO 会被跳过**并单独计数
（报告里的「按目录的『#类型』限定跳过 N 个 NFO」）。别名也认：
`movie` / `movies` / `影片`、`tv` / `tvshow` / `series` / `剧集`。

写法和官方「媒体库刮削」的 `scraper_paths` 一致，老配置可以直接搬过来。
路径本身含有 `#` 时不受影响 —— 认不出的后缀会当作路径的一部分保留。

CLI 同样支持：`--root "/media/link/电影#电影"`。

### 保护字段（`protect_fields`）

**照常参与比对、缺失也会补，但永远不会覆盖你已有的内容。** 想保住手工润色的简介、
自己写的一句话宣传语，就把对应字段填进来（逗号分隔）。

> ℹ️ v1.2.0 曾有一个「字段白名单」用来收窄处理范围，按用户反馈已在 v1.4.0 移除。
> 该能力仍保留在引擎与 CLI 的 `--only` 参数里。

字段名用 NFO 的标签名（小写、逗号分隔）。可用的字段：

- **电影**：`title` `originaltitle` `plot` `tagline` `year` `premiered` `runtime` `mpaa` `rating` `genre` `studio` `country` `director` `credits` `actor`
- **剧集 tvshow**：`title` `plot` `tagline` `year` `premiered` `runtime` `mpaa` `rating` `genre` `studio` `country` `actor`
- **单集 episode**：`title` `plot` `aired` `rating` `season` `episode` `director` `credits` `actor`
- **季 season**：`title` `plot` `premiered` `season`

### 分级地区码（`cert_country`）到底管什么

配置页里它是**单选下拉框，只能选一个地区**（列了 13 个常用地区）。

NFO 里的 `<mpaa>` 标签存的其实是**影视分级**（`PG-13`、`R` 这类），而 TMDB 上同一部片在不同国家分级并不一样，
这个配置就决定取哪一份：

| 填什么 | `<mpaa>` 可能得到 |
| --- | --- |
| `US`（默认） | `PG-13` / `R` / `PG` |
| `GB` | `12` / `15` / `18` |
| `JP` | `G` / `PG12` / `R15+` |
| `DE` | `FSK 12` / `FSK 16` |

> 中国大陆没有官方影视分级体系，填 `CN` 通常取不到值。若所选地区恰好缺该片的分级，
> 会自动退回到任意有值的地区，**不会留空**。

**建议首跑流程**：`mode=report` + `dry_run=开` → 详情页会列出**将要修改哪些文件** → 确认无误后切 `mode=sync`。
图片若担心首轮流量，可先设 `image_mode=missing` 只补空缺。

---

## 界面：详情页看什么

运行结束后，插件详情页的主视图是**「本次修改了哪些文件」清单**（只读文本框，可滚动）：

```
本次修改 78 个 NFO、175 张图片（按文件列出，共 29 项）

▍电影/星际穿越 (2014)/movie.nfo　电影
    字段：plot · 补齐、genre · 替换
    图片：poster → poster.jpg · 补齐

▍电影/沙丘 (2021)/沙丘 (2021).nfo　电影
    字段：year · 替换
```

- **演练 / 只报告模式下也会列出清单**，措辞是「将要修改」，方便先体检再动手。
- 清单只列**会写盘**的文件；被跳过的条目（NFO 锁定、保护字段、`gapfill` 只补缺失、图片仅补缺失等）
  不会出现——完整原因见插件数据目录下的 `last_report.txt`（仍然照常生成）。
- 顶部另有概要：本轮扫描了多少 NFO / 图片、实际改了多少；有失败条目会附在清单末尾，
  并单独给一条简短提示（不再铺满整个版面）。

> 用纯文本而不是表格，是因为表格组件在插件详情页里**实测只渲染出分页条、表体一行都不显示**。
> 能读到内容比排版好看重要 —— 如果你更希望用表格样式，可以告诉我。

> 顺带一提：数据目录通常是 `<MoviePilot>/data/plugins/NfoGapFill/`，里面有 `last_report.txt`
> （完整文本报告）与 `last_changes.json`（详情页清单用的结构化明细）。

---

## 独立命令行用法

同一份文件既是插件也是 CLI，共用完全相同的引擎。想在上 NAS 之前先在电脑上验证策略：

```bash
# 体检：只报告差异，不写盘
python plugins.v2/nfogapfill/__init__.py --root /media/link --source tmdb --api-key XXX

# 离线演练：用本地 JSON 冒充在线数据，不联网也能验证比对逻辑
python plugins.v2/nfogapfill/__init__.py --root /media/link --source file --cache remote.json

# 正式执行（先加 --dry-run 看一遍，再去掉）
python plugins.v2/nfogapfill/__init__.py --root /media/link --source tmdb --api-key XXX --mode sync --fix

# 连图片一起处理（CLI 里图片默认关闭，插件里默认开启）
python plugins.v2/nfogapfill/__init__.py --root /media/link --source tmdb --api-key XXX \
    --mode sync --fix --image-mode sync --image-quality standard
```

> 不加 `--fix` 时等价于「只报告」；图片相关的开关是 `--image-mode` / `--image-kinds` / `--image-quality` / `--image-manifest`。
> 注意：CLI 里 `--source file`（离线演练）给不了光盘图 / 横幅图这类 fanart.tv 的图 —— 它们只在线上；`--source tmdb` 或插件里则正常。

## 自测

无需联网、无需 TMDB Key，纯标准库：

```bash
python tests/_self_test.py          # 引擎行为 65 项断言（含图片补齐/别名/指纹幂等/#类型限定/并发一致性/季图双落点）
python tests/_self_test_plugin.py   # 插件面 240 项断言（伪造 MP 宿主 + 表单/页面/选图/尺寸/指纹/目录类型/脏配置修复/结构化值剥离/脏值清理/fanart/并发与限速/id 与季集号解析/网络重试与域名覆盖/图片备用源/来源优先级/图片类型双下拉与并集/MP 图片类型与命名对齐）
```

覆盖：相同字段不被触碰、缺失被补齐、不一致被替换、`lockdata` 阻止替换、写入前备份、
二次运行幂等（零写入）、保护字段生效、`gapfill` 模式不替换、表单控件与默认配置一一对应、端到端出报告并发通知；
图片部分另外覆盖：缺失补齐、`fanart` 别名同内容、季图两处都写（季目录通用名 + 剧集根目录 seasonNN 副本）、单集缩略图命名、
指纹匹配零下载幂等、错图被替换且原图入备份、`image_mode=missing/off` 行为、
`lockdata` 连图片一起锁、TMDB 选图策略（只按语言、同级取第一条）、尺寸档位按类型区分、
与 MP 官方的类型集合/文件名逐项对齐（剧集不写 disc、thumb 与 landscape 成对、季图双落点、特别篇 season-specials-poster）。

---

## 支持的字段与图片

- **电影**（`movie.nfo` / 同名 NFO）：`title`、`originaltitle`、`plot`、`tagline`、`year`、`premiered`、`runtime`、`mpaa`、`rating`、`genre`、`studio`、`country`、`director`、`credits`、`actor`，以及 `uniqueid[tmdb]` / `tmdbid`
- **剧集**：`tvshow.nfo`、`season.nfo`、单集 NFO（`episodedetails`）
- **图片**：`poster`（海报）、`backdrop`（背景图，含 `fanart` 别名）、`logo`（徽标）、`thumb`（缩略图，含 `landscape` 别名；单集为 `<视频文件名>.jpg`）、`banner`、`clearart`、`disc`（仅电影）、季图（季目录通用名 + 剧集根目录 seasonNN 副本）

> **为什么目录里会有几张「看起来一样」的图？** 这是正常的，不是写重复了：
>
> - `backdrop.jpg` 与 `fanart.jpg` —— **本来就是同一张背景图**，只是 Kodi / Emby / Jellyfin
>   认的文件名不同（`fanart` 是 `backdrop` 的别名），所以两份内容必然一致；
> - `landscape.jpg`（横版缩略图）来自 **fanart.tv**，而 fanart.tv 提供的
>   `moviethumb` / `tvthumb` **常常与背景图就是同一张** —— 这是图源本身的惯例，
>   不是插件取错图。
>
> 如果不需要这么多份，在插件配置的「处理的图片类型」里**取消勾选「横版缩略图」**
> 即可（`backdrop` 与 `fanart` 建议保留，它们兼容不同媒体服务器）。

---

## 目录结构

仓库整体结构见文末[「目录结构」](#目录结构) 一节。本插件自身涉及的文件：

```
plugins.v2/nfogapfill/__init__.py    # 插件本体（类名 NfoGapFill）
icons/nfogapfill.png                 # 图标
docs/DEPLOY.md# 部署与排错详解
tests/_self_test.py / _self_test_plugin.py / _fixture/
├── 媒体库/                # 样例媒体库（NFO）
├── images/                           # 样例在线图片（离线测图片用）
└── remote_cache.json                 # 模拟在线元数据 + 图片地址
```

> MoviePilot 约定：**类名 = 插件 ID**（`NfoGapFill`），**目录名 = 类名小写**（`nfogapfill`），入口固定为 `__init__.py`。

---

## 修复历史版本写坏过的 NFO

如果你在 Jellyfin / Emby 里看到**类型、导演、工作室**等字段显示成
`{'id': 12, 'name': '冒险'}` 这种 Python 字面量，那是 **v1.4.0 及更早版本的一个 bug**。

原因：插件走「复用 MoviePilot 刮削通道」这条路时，宿主返回的 `genres` /
`production_companies` / `directors` / `actors` 是**结构化对象**（`List[dict]`、
`List[MediaPerson]`），而旧版本对它们直接做了 `str()`，于是把 Python 字面量写进了 NFO。
Jellyfin 读 `<director>` 时还会**按逗号拆分**多值字段，所以一个坏值会裂变成一堆「假导演」，
看起来就是演职人员里多出几个叫 `{adult: False`、`'gender': 1` 的人。

**v1.4.1 已修好**：取值改为逐层剥到「名字」为止，兼容 dict 与对象两种形态。
另外加了一道**护栏** —— 即便数据源以后再犯，疑似对象字面量的值也会被跳过并写进告警日志，
绝不会再写进你的媒体库。

### 已经被写坏的文件怎么修

不用手工改。升级到 **v1.4.3 或以上**，用 `模式 = 不一致则替换`（`sync`，默认就是它）跑一轮即可：

v1.4.3 起会主动识别并清除这类脏值 —— 只要某个字段里存在「对象字面量」形态的值，
就强制整段重写一遍（即使其余内容与在线一致），并把这些脏值一并清掉。
报告里会写明「清理历史脏值 N 处」。

两个特别注意点：

- 脏值可能**不只在 `<studio>`**：也会扫描同义标签 `<network>` 里的脏值（媒体服务器常把两者算作同一栏）。
- 在线取不到该字段时**只精准删掉脏值**，不会因为整段重写而丢掉同一字段里的正常内容。

顺带会清掉旧版本可能留下的**空演员节点**（在媒体服务器里会显示成一个空白人物）。
跑完让媒体服务器刷新一下元数据即可。

> 顺便澄清一点：MoviePilot **自己**的 NFO 生成代码是正确的
> （`app/modules/themoviedb/scraper.py` 里是 `company.get("name")` 取名字，且不写 `<network>`），
> 所以这些 dict 脏值确定来自本插件 v1.4.1 之前的版本，不是 MP 写坏的。

---

## 已知限制

- **banner / clearart / disc / thumb(landscape) 依赖 fanart.tv**：这几类 TMDB 没有，只有 fanart.tv 提供。
  插件会**自动沿用 MoviePilot 的 `FANART_API_KEY`**（MP 自带默认值），所以一般不用额外配置；
  但需要 TMDB API Key 走直连通道（复用宿主刮削通道时拿不到这几类）。**季 backdrop 不建议期待**：
  TMDB 的季图片接口只返回 `posters`，fanart 的季接口只有 `seasonposter/seasonbanner/seasonthumb`，
  没有数据源能提供季 backdrop，插件也已不列它。
- **剧集缩略图要求该集存在 NFO**：本插件以 NFO 为扫描入口，没有 NFO 的集不会被处理（电影/剧集/季同理）。
- **`HostProvider`（复用 MP 刮削通道）能力有限**：只有 MoviePilot 里也没配到可用 TMDB Key 时才会走它；
  字段映射在不同 MP 版本上未逐一验证，属「尽力而为」，且图片只能取到海报与背景图
  （`MediaInfo.poster_path` / `backdrop_path`），徽标 / 缩略图 / 季图片拿不到。
- **首轮图片有流量开销**：库里已有图片需要下载后才能判定是否一致；之后靠指纹清单零下载。
  库特别大时，可以先把「媒体库目录」填成某个子目录分批跑，或先设 `image_mode=missing` 只补空缺。
- **图片下载依赖 `image.tmdb.org`**：国内直连经常超时，甚至整段被拦（`SSL: UNEXPECTED_EOF_WHILE_READING`）。
  插件会自动沿用 MoviePilot 的 `PROXY_HOST`（代理）与 `TMDB_IMAGE_DOMAIN`（图片域名可换成镜像/反代）；
  官方域名连不上时还会**自动改试 TMDB 官方 CDN 裸域名**（同一份对象），每个地址各重试 3 次；
  仍失败的条目会列在详情页的失败清单里，下次运行自动重试。
  > 自定义了 `TMDB_IMAGE_DOMAIN` 时以你的镜像为准，插件不会再偷偷换源。
- **TMDB 接口域名也可覆盖**：接口地址默认 `api.themoviedb.org`，但它在部分地区会被网关整段拦掉
  （`Tunnel connection failed: 502`），而等价域名 `api.tmdb.org` 仍可达、返回内容一致。
  可在 MoviePilot 设置里加 `TMDB_API_DOMAIN=api.tmdb.org`，或给本插件进程设同名环境变量；
  只填域名会自动补 `/3`。**这是「图片能下、数据取不到」矛盾的根因。**
- **fanart.tv Key 三级回退**：横幅图 / 光盘图 / 透明艺术图 / 横版缩略图来自 fanart.tv，Key 按
  「宿主设置 `FANART_API_KEY` → 环境变量 `FANART_API_KEY` → MP 内置默认 Key」逐级取用。
  以前只读宿主设置，命令行 / docker 用环境变量传 Key 会失效。
- **写回后仍需让媒体服务器刷新**（MP 的「媒体库服务器刷新」插件，或在 Emby/Jellyfin 手动「刷新元数据」）。
- **硬链接做种库**请确认 `PUID/PGID/UMASK` 对媒体目录可写，否则会静默失败。
- 与官方「媒体库刮削」建议**二选一**：本插件已覆盖 NFO 与图片，同时开启两边可能互相覆盖。

---

<a id="specialsfixer"></a>

## SpecialsFixer — 整理记录季集修正

对**TMDB 查无该集**的整理记录，识别其是否为特别篇，确认后把该记录的季数与集数
修正到 `Season 00` 与正确集号，并**重新触发 MP 自身的整理流程**完成归位。

<img src="icons/specialsfixer.png" width="72" alt="icon">

### 职责边界（严格）

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

<a id="specialsrelocate"></a>

## SpecialsRelocate — 特别篇归位

自动比对本地剧集集数与 TMDB 官方季集数，识别**超出官方范围的剧集**，
判定其是否属于特别篇（SP / OVA / 总集篇 / 番外 / 特典），确认后按
Plex / TMDB 规范移入 `Season 00` 并重编号，**正片完全不受影响**。

<img src="icons/specialsrelocate.png" width="72" alt="icon">

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

## 目录结构

```
MoviePilot-Plugins/
├── package.v2.json                  # 插件市场索引（三个插件都在这里登记）
├── plugins.v2/
│   ├── nfogapfill/__init__.py
│   ├── specialsfixer/
│   │   ├── __init__.py              # 主类：事件钩子、巡检编排、修正与重整
│   │   ├── fixer_core.py# 纯逻辑：三态判定、证据加权、修正规则
│   │   └── tmdb_probe.py            # TMDB 客户端（区分 404 与网络失败）
│   └── specialsrelocate/
│       ├── __init__.py              # 主类：事件钩子、扫描编排、迁移执行
│       ├── core.py                  # 纯函数判定层：集号/季号解析、关键词、置信度
│       ├── fileops.py               # 文件层：安全移动、Season 00 推导、NFO
│       └── tmdb.py                  # TMDB 客户端：多域名回退 + 退避重试
├── icons/                           # 三个插件的图标（package.v2.json 里走 jsDelivr CDN）
├── scripts/
│   ├── make_specials_icons.py       # 本地绘制两个特别篇插件的图标（无第三方依赖）
│   ├── build_preview.py
│   └── fetch_real_samples.py
├── tests/
│   ├── _self_test.py / _self_test_plugin.py / _fixture/...
│   └── specials/
│       ├── test_specialsfixer.py        # 78 项离线测试
│       └── test_specialsrelocate.py     # 105 项离线测试
├── docs/DEPLOY.md
└── jellyfin/logo-title-fix.css
```

插件目录名 = 插件 ID = 主类名，三者必须一致（MoviePilot 按此约定加载）。
两个特别篇插件都做了分层：纯逻辑层不依赖宿主，可离线单测。

离线测试（不需要连 MoviePilot，伪造宿主 `app` 包）：

```bash
python tests/specials/test_specialsfixer.py       # 78 项
python tests/specials/test_specialsrelocate.py    # 105 项
```

---

## License

[MIT](LICENSE)
