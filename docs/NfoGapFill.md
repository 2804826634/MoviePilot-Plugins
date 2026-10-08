# NfoGapFill — NFO 与图片差异比对

> 比对本地 NFO 与在线元数据、海报/背景图：**缺失补齐、不一致替换、一致跳过**。

![version](https://img.shields.io/badge/version-1.7.7-blue)

<img src="../icons/nfogapfill.png" width="96" alt="icon">

仓库：<https://github.com/2804826634/MoviePilot-Plugins>
安装：MoviePilot → `设定` → `插件` → 插件市场 → 自定义仓库填 `2804826634/MoviePilot-Plugins`

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

> **选图策略**：**海报 / 徽标 / 单集剧照 / 季图** 走下面的「本语言优先」两档规则
> （中文再分**简体 / 繁体**优先，v1.10.0 起）；
> **背景图（backdrop）** 单独一套 —— **默认直接跟随 TMDB 官网顺序**（见本节末「背景图」）。
>
> **① 海报 / 徽标 / 剧照 / 季图 —— 本语言优先（两档）**
>
> 1. **本语言档** —— 取「元数据语言」对应的图（选「简体中文」就是中文图），
>    档内**按评分（`vote_average`）从高到低**取；
> 2. **不限语言档** —— 本语言**一张都没有**时，不再限定语言，
>    **从全部候选里按评分从高到低**取。
>
> 元数据语言是中文时，第 1 档再拆成「简体 / 繁体」两组优先（v1.10.0 起）：
> **简体中文（`zh-CN`）→ 先取简体图，没有简体才用繁体兜底；**
> **繁体中文（`zh-TW` / `zh-HK`）→ 先取繁体图，没有繁体才用简体兜底。**
> 之外仍然是「本语言 → 不限语言」的顺序。
>
> **为什么需要单独处理简体 / 繁体**：TMDB 的 `/images` **响应**里所有中文图
> 都标 `iso_639_1: "zh"`，光看响应分不出简繁；但**请求参数**支持 `zh-CN` / `zh-TW`，
> 而且实测两组**互不重叠**。实测《无职转生》（`tv 94664`）：
>
> | 请求 `include_image_language` | 中文海报 | 中文徽标 |
> |---|---|---|
> | `zh-CN,null`（简体） | **4** | **1** |
> | `zh-TW,null`（繁体） | **12** | **3** |
> | `zh,null`（并集，旧行为） | 16（= 4+12） | 4（= 1+3） |
>
> 4+12=16、1+3=4 完全吻合 → 两组各自独立。旧行为只请求并集再按评分挑，
> 结果《无职转生》的海报与徽标**都选中了繁体那张**（海报 `aWUX…`，10.0 分）；
> v1.10.0 起简体设置下改为**简体优先**（海报 `u7LW…`、徽标 `81Jc…`）。
> 代价是对中文条目**多一次 TMDB 请求**（并集里没有中文图时会自动跳过这次请求）。
>
> 排序键依次是：**评分降序 → 票数降序 → 分辨率降序 → TMDB 返回顺序**。
> 也就是「评分打平了比票数，票数也打平了比谁大，全都一样才轮到 TMDB 的推荐顺序」。
> 只有在某类型**在线一张图都没有**时才记为缺失、不写这一文件。
>
> **为什么以评分而不是票数为准（v1.8.2 的关键修正）**：票数只说明「有多少人投过票」，
> 不代表图好 —— 一张图可能因为曝光多而被大量投低分。实测《凡人修仙传》（`tv 106449`）
> 的 142 张中文海报里，**票数最高那张（18 票）平均分只有 3.14**，
> 而**评分最高那张是 7.54（8 票）**。v1.8.0 按票数排序，选中的恰恰是口碑最差的那张。
>
> **为什么票数只是兜底**：评分一样时，样本更多的图更可信，所以票数多的排前面。
>
> **为什么还要比分辨率（v1.8.3 新增）**：评分与票数都打平的「全并列」在冷门条目上很常见。
> 实测《轻音少女》（`tv 42253`）有 **3 张海报并列最高分 3.334、且票数都是 1**，
> 其中两张是 2000×3000、一张是 1000×1500 —— 这时应该给大图。
> 比较方式是**先比宽度、再比高度**（所以 2000×3000 优于 2000×2800，也优于 1000×1500）。
>
> **为什么不设最低票数门槛**：实测 TMDB 上只被投过 1 票的图评分上限很低
> （三部热门片的 1 票图最高评分都只有 3.334），且给「全局最高分图」分别加上
> ≥2 / ≥3 / ≥5 票的门槛后结果**完全相同** —— 纯按评分排序不会选到「1 票满分」的噪声图。
>
> 为什么第 2 档不限制语言：TMDB 上很多老番 / 冷门片根本没人上传中文图
> （例如《冰菓》的 24 张海报里**一张中文都没有**），留空只会让这一类型永久缺失。
>
> 实测样例（真实 TMDB 数据，均为中文候选池）：
>
> | 条目 | 「票数优先」（v1.8.0） | 「评分优先」（v1.8.2 起） |
> |---|---|---|
> | 凡人修仙传（106449） | 3.14（18 票，口碑最差） | **7.54**（8 票） |
> | 权力的游戏（1399） | 6.44（16 票） | **8.03**（5 票） |
> | 沙丘 2（693134） | 6.44（24 票） | 6.44（24 票）← 两者一致 |
> | 冰菓（65329） | 5.79（7 票） | 5.79（7 票）← 无中文，同走第 2 档 |
> | 尼古喵喵（312949） | 3.33（1 票） | 3.33（1 票）← 中文仅 3 张，同图 |
> | 轻音少女（42253） | 1.75（4 票） | **3.33**（1 票）← 最高分 3 张并列、票数也都 1 |
>
> **② 背景图（backdrop）—— 跟随 TMDB 官网顺序（v1.9.0 起）**
>
> 背景图是**语言无关**的装饰图（同一张图供所有语言共用），所以**默认不走语言优先**，
> 而是**直接取 TMDB `/images` 返回列表的第一张** —— 即官网
> `/tv/{id}/images/backdrops` 页面的**默认展示顺序第一张**，**不做语言过滤、也不重新排序**。
>
> 为什么：只要 TMDB 上有人传过本语言背景图，语言优先就会**只在少数本语言图里挑**，
> 把官网默认展示的头部大图滤掉。实测《无职转生》（`tv 94664`）：官网列表第 1 张是
> 「**无语言 · 3840×2160 · 8.034 分 · 15 票**」的官方头图；而旧规则只在 **7 张中文图**
> （评分与票数**全是 0**）里按分辨率挑出一张 1920×1080，与官网默认展示的完全不同。
>
> | 模式 | 选中的背景图 | 特征 |
> |---|---|---|
> | `web`（默认） | `j9fRIimor0…jpg` | 无语言 · 3840×2160 · 8.034 分 ← **官网列表第 1 张** |
> | `language` | `l8lwpvr1QA…jpg` | 中文 · 1920×1080 · 评分/票数全 0 |
>
> v1.9.1 起**固定为「跟随官网顺序」**（配置页不再提供切换项）。
> **只影响背景图** —— 海报 / 徽标 / 剧照仍按语言优先，实测两种模式下
> 海报与徽标选出的图**完全一致**。特殊场景仍可用 CLI `--backdrop-order language` 切回旧行为。
>
> ⚠️ **与 MP 的一处可解释差异**（不是故障）：MP 对根目录的 `poster` / `backdrop` / `logo`
> 直接取 TMDB **主记录里那一张**（`MediaInfo.poster_path` / `backdrop_path` / `logo_path`，
> 即 TMDB 钦定图），本插件则从 `images` 接口的候选里按上面两档规则挑 ——
> 本语言优先 + 评分择优，能保证拿到**中文**图且是社区评价最高的那张，
> 但与 MP 的钦定图不保证逐字节相同。
> （顺带一提：MP 给《凡人修仙传》的钦定图在图库里只有 1 票、评分 3.33、843×1264。）
>
> 根目录 / 季目录的 `thumb`、`landscape` 取自 **fanart.tv 的横版缩略图**
> （`moviethumb` / `tvthumb` / `seasonthumb`），而不是 TMDB 的 `stills`。
> TMDB 的 `stills` 是**剧照**（横竖构图都有、多为竖版人物特写），只用于**单集**缩略图。
> 早先版本把根目录的 thumb 也接到 `stills`，写出来的 `thumb.jpg` 经常是竖图 ——
> 这是与 MP 的一处偏离，已修正。
>
> ⚠️ **另一处可解释差异**：MP 的 `thumb` / `landscape` 靠 fanart 模块动态注入
> （`tvthumb` → `thumb_path`），**该剧 fanart 没有对应数据时就不写**；
> 本插件同样如此 —— 所以「MP 那边没有 `landscape.jpg`」通常是 fanart 缺数据的正常结果。

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
2. **只补缺失** —— `mode=gapfill` 时已有内容一律不动，只补空缺（想保住手工润色内容时用这个）。
3. **演练模式** —— `dry_run` 下只生成「将要修改」的清单，不落盘。

> v1.8.0 起配置页不再提供「保护字段」，常见诉求请用第 2 条。
> 引擎层的 `EngineConfig.protect_fields` 精细语义仍然保留（见上文）。
>
> ⚠️ **v1.9.2 起插件不再写备份**：不再生成 `<媒体库根目录>/.nfo-backup/`，
> 改写不可回滚 —— 修改前请先用第 3 条（演练模式）或 `mode=report` 确认清单。
> 引擎的 `backup` / `backup_dir` 能力仍保留（CLI 侧仍可用 `--backup-dir`，默认开启备份）。

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
| `paths` | 空 | 媒体库目录，每行一个；**行尾可加 `#电影` / `#电视剧` 限定该目录的类型**（见下） |
| `exclude_paths` | 空 | 排除路径片段，命中即跳过 |
| `language` | `zh-CN` | 元数据语言（`zh-CN` / `zh-TW` / `en-US` / `ja-JP`）。**同时是海报 / 徽标 / 剧照的第一优先语言**（见上；中文再分简体 / 繁体优先，背景图不按语言过滤） |
| `image_mode` | `sync` | 图片处理：`sync` / `missing` / `off`，见上节 |
| `tmdb_image_kinds` | 四项全选 | **TMDB 提供的图片类型**（多选下拉）：海报 / 背景图 / 徽标 / 剧集缩略图（单集剧照） |
| `fanart_image_kinds` | 五项全选 | **fanart.tv 提供的图片类型**（多选下拉）：横版缩略图 / 横幅图 / 光盘图 / 透明艺术图 / 别名 landscape |
| `image_sources` | `tmdb,fanart` | **图片来源优先级**：`tmdb,fanart`（TMDB 优先）/ `fanart,tmdb` / `tmdb`（只用 TMDB）/ `fanart`（只用 fanart） |

> **v1.9.1 / v1.9.2 起以下五项不再出现在配置页**（行为固定，无需配置）：
>
> | 原配置项 | 现行固定行为 |
> |---|---|
> | `tmdb_api_key` | **自动读取 MoviePilot「设置 → TMDB」里配置的 `TMDB_API_KEY`**，插件页不再提供输入框；想换 Key 直接改 MoviePilot 的设置 |
> | `cast_limit` | **全部写入**：按 TMDB 返回的演员全写，不再限制 10/20/30/50 位（NFO 会明显变大） |
> | `image_quality` | **始终原始尺寸**：海报 / 背景图 / 徽标都取原图（不再提供「标准画质」w780/w1280 档） |
> | `backdrop_order` | **始终跟随 TMDB 官网顺序**（`web`）：取官网 images 页列表第一张，不限语言、不重排 |
> | `backup`（v1.9.2） | **不做备份**：不再生成 `.nfo-backup`，改写不可回滚（引擎层 `backup` / `backup_dir` 仍保留，CLI 可用 `--backup-dir`） |
>
> 引擎层对应的参数（`cast_limit` / `image_quality` / `backdrop_order` / `backup` / 自定义 Key）仍然保留，
> CLI 也可用 `--cast-limit` / `--image-quality` / `--backdrop-order` / `--backup-dir` 临时调整，供特殊场景调用。

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

### 分级地区码固定为美国（`cert_country`）

NFO 里的 `<mpaa>` 标签存的其实是**影视分级**（`PG-13`、`R` 这类），
本插件**固定取美国（US）地区的分级**，配置页里已不再提供下拉框。

> 若某部片在 TMDB 上没有美国分级，会自动退回到任意有值的地区，**不会留空**。
> 引擎层仍保留 `cert_country` 参数（默认 `US`），需要改地区时可直接构造
> `TmdbProvider(..., cert_country="JP", ...)`。

### 保护字段已从配置页移除（`protect_fields`）

v1.8.0 起**配置页与 CLI 都不再暴露「保护字段」**（按用户反馈移除）。
常见诉求请改用**「只补缺失」**模式（`mode=gapfill`）：已有内容一律不动，只补空缺。

> 引擎层 `EngineConfig.protect_fields` 的能力仍保留，需要「照常比对、缺失补齐、
> 但永不覆盖已有内容」这种精细语义时，可直接在代码里构造引擎配置使用
> （`protect_fields={"plot", "tagline"}`）。

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

> 仓库内**不再附带测试代码**。v1.7.8 及之前版本曾提供 269 项离线断言
> （`tests/_self_test.py` + `tests/_self_test_plugin.py`，不联网、不需TMDB Key），
> 已随仓库精简一并移除。

改动插件后想验证行为，建议用插件自带的 **CLI 演练模式**（`--source file` 离线跑，
不写盘只出报告）：

```bash
python plugins.v2/nfogapfill/__init__.py --source file --root 你的媒体库 --report
```

先用 `report` 模式看判定结果，确认无误再用 `sync` 模式实际写入。

那套断言曾覆盖：相同字段不被触碰、缺失被补齐、不一致被替换、`lockdata` 阻止替换、写入前备份、
二次运行幂等（零写入）、保护字段生效、`gapfill` 模式不替换、表单控件与默认配置一一对应、端到端出报告并发通知；
图片部分另外覆盖：缺失补齐、`fanart` 别名同内容、季图两处都写（季目录通用名 + 剧集根目录 seasonNN 副本）、单集缩略图命名、
指纹匹配零下载幂等、错图被替换且原图入备份、`image_mode=missing/off` 行为、
`lockdata` 连图片一起锁、TMDB 选图策略（海报 / 徽标本语言优先 + 评分降序 + 票数/分辨率兜底；背景图默认跟随官网顺序）、尺寸档位按类型区分、
与 MP 官方的类型集合/文件名逐项对齐（剧集不写 disc、thumb 与 landscape 成对、季图双落点、特别篇 season-specials-poster）。
这些行为约定仍然有效，文档各处描述的就是它们。

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

仓库整体结构见 [README 的「目录结构」一节](../README.md#目录结构)。本插件自身涉及的文件：

```
plugins.v2/nfogapfill/__init__.py    # 插件本体（类名 NfoGapFill）—— MoviePilot 只下载这一个文件
icons/nfogapfill.png                 # 图标
docs/DEPLOY.md                       # 部署与排错详解
```

> MoviePilot 约定：**类名 = 插件 ID**（`NfoGapFill`），**目录名 = 类名小写**（`nfogapfill`），入口固定为 `__init__.py`。
> 安装时 MP 只会拉取 `plugins.v2/nfogapfill/` 目录下的文件，`docs/` 与 `icons/` 不参与安装
> （图标是 `package.v2.json` 里通过 CDN 链接引用的）。

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
