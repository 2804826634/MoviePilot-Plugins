# NfoGapFill — MoviePilot 的 NFO 与图片差异比对插件

> 比对本地 NFO 与在线元数据、海报/背景图：**缺失补齐、不一致替换、一致跳过**。

![version](https://img.shields.io/badge/version-1.4.2-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![platform](https://img.shields.io/badge/MoviePilot-v2%20%7C%20v3-9cf)
![python](https://img.shields.io/badge/python-3.9%2B-yellow)

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

### 支持的全部类型（就这 4 类 + 季海报）

落盘命名遵循 **MP / Kodi / Jellyfin 三者共同认可**的约定（对照 MP `app/chain/media.py` 的 `IMAGE_ALIASES` 与季目录命名规则实现）：

| 配置里的选项 | 落盘文件 | 适用 | 数据来源 |
| --- | --- | --- | --- |
| 海报（poster） | `poster.jpg` | 电影、剧集目录 | TMDB `posters` |
| 背景图（backdrop） | `backdrop.jpg` **+** `fanart.jpg` | 电影、剧集目录 | TMDB `backdrops` |
| 徽标（logo） | `logo.png` | 电影、剧集目录 | TMDB `logos` |
| 剧集缩略图（thumb） | `<视频文件名>.jpg` | 单集（需该集有 NFO） | TMDB `stills` |
| 季海报 | `<季目录>/poster.jpg` **+** `<剧集根目录>/seasonNN-poster.jpg` | 季 | TMDB `posters`（**跟随「海报」一起处理，不单独成项**） |

### 不支持的类型（以及为什么）

`banner`、`clearart`、`discart`、`landscape`、`characterart` 这类画集 **TMDB 并不提供**——
它只有 海报 / 背景图 / 徽标 / 剧照 四种素材，上面那几类只有 **fanart.tv** 才有，需要另外申请该站 API Key。

所以本插件的定位是：**把你库里已有这几类补全并纠错**，不是「全画集刮削」。
需要完整画集的话，可以再叠加一个 fanart.tv 类工具，两者不冲突。

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
   2804826634/moviepilot-nfo-gapfill
   ```

   或通过环境变量固定（`docker-compose.yml`）：

   ```yaml
   environment:
     - PLUGIN_MARKET=2804826634/moviepilot-nfo-gapfill
   ```

3. 在市场里找到「**NFO 与图片差异比对**」→ 安装 → 启用。

> 也可把本仓库地址**追加**到已有的 `PLUGIN_MARKET`（多个仓库用英文逗号分隔），不会影响官方市场。

### 方式 B：本地插件仓库（离线、可版本管理）

```bash
git clone https://github.com/2804826634/moviepilot-nfo-gapfill.git /path/to/mp_plugins
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
| `cron` | `0 3 * * *` | 执行周期（5 位 cron） |
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
| `image_kinds` | 四种全选 | 处理的图片类型，**多选下拉**：海报 / 背景图 / 徽标 / 剧集缩略图（全不选 = 不处理图片） |
| `image_quality` | `standard` | 画质档：`standard`（海报 w780 / 背景图 w1280 / 徽标 w500）或 `original`（最清晰、体积大） |

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

## 自测

无需联网、无需 TMDB Key，纯标准库：

```bash
python tests/_self_test.py          # 引擎行为 57 项断言（含图片补齐/别名/指纹幂等/#类型限定）
python tests/_self_test_plugin.py   # 插件面 120 项断言（伪造 MP 宿主 + 表单/页面/选图/尺寸/指纹/目录类型/脏配置修复/结构化值剥离）
```

覆盖：相同字段不被触碰、缺失被补齐、不一致被替换、`lockdata` 阻止替换、写入前备份、
二次运行幂等（零写入）、保护字段生效、`gapfill` 模式不替换、表单控件与默认配置一一对应、端到端出报告并发通知；
图片部分另外覆盖：缺失补齐、`fanart` 别名同内容、季海报双落点、单集缩略图命名、
指纹匹配零下载幂等、错图被替换且原图入备份、`image_mode=missing/off` 行为、
`lockdata` 连图片一起锁、TMDB 选图策略（语言 → 分辨率 → 评分）、尺寸档位按类型区分。

---

## 支持的字段与图片

- **电影**（`movie.nfo` / 同名 NFO）：`title`、`originaltitle`、`plot`、`tagline`、`year`、`premiered`、`runtime`、`mpaa`、`rating`、`genre`、`studio`、`country`、`director`、`credits`、`actor`，以及 `uniqueid[tmdb]` / `tmdbid`
- **剧集**：`tvshow.nfo`、`season.nfo`、单集 NFO（`episodedetails`）
- **图片**：`poster`（海报）、`backdrop`（背景图，含 `fanart` 别名）、`logo`（徽标）、`thumb`（剧集缩略图）、季海报

---

## 目录结构

```
moviepilot-nfo-gapfill/
├── package.v2.json                 # 插件市场索引
├── plugins.v2/
│   └── nfogapfill/
│       └── __init__.py             # 插件本体（类名 NfoGapFill）
├── icons/
│   └── nfogapfill.png
├── docs/
│   └── DEPLOY.md                   # 部署与排错详解
└── tests/
    ├── _self_test.py
    ├── _self_test_plugin.py
    └── _fixture/
        ├── 媒体库/                  # 样例媒体库（NFO）
        ├── images/                 # 样例在线图片（离线测图片用）
        └── remote_cache.json       # 模拟在线元数据 + 图片地址
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

不用手工改。升级到 v1.4.1 后，用 `模式 = 不一致则替换`（`sync`，默认就是它）跑一轮即可：

本地是脏值、在线是干净名字 → 判定「不一致」→ 直接替换掉。

顺带会清掉旧版本可能留下的**空演员节点**（在媒体服务器里会显示成一个空白人物）。
跑完让媒体服务器刷新一下元数据即可。

---

## 已知限制

- **不提供 banner / clearart / discart / landscape**：这些画集 TMDB 没有，只有 fanart.tv 提供，需要额外申请其 API Key，不在本插件范围内。所以本插件是「补齐 + 纠错」，不是「全画集刮削」，可以和 fanart.tv 类工具并存。
- **剧集缩略图要求该集存在 NFO**：本插件以 NFO 为扫描入口，没有 NFO 的集不会被处理（电影/剧集/季同理）。
- **`HostProvider`（复用 MP 刮削通道）能力有限**：只有 MoviePilot 里也没配到可用 TMDB Key 时才会走它；
  字段映射在不同 MP 版本上未逐一验证，属「尽力而为」，且图片只能取到海报与背景图
  （`MediaInfo.poster_path` / `backdrop_path`），徽标 / 剧集缩略图 / 季海报拿不到。
- **首轮图片有流量开销**：库里已有图片需要下载后才能判定是否一致；之后靠指纹清单零下载。
  库特别大时，可以先把「媒体库目录」填成某个子目录分批跑，或先设 `image_mode=missing` 只补空缺。
- **图片下载依赖 `image.tmdb.org`**：国内直连经常超时。插件会自动沿用 MoviePilot 的
  `PROXY_HOST`（代理）与 `TMDB_IMAGE_DOMAIN`（图片域名可换成镜像/反代），
  下载失败还会**自动重试 3 次**；仍失败的条目会列在详情页的失败清单里，下次运行自动重试。
- **写回后仍需让媒体服务器刷新**（MP 的「媒体库服务器刷新」插件，或在 Emby/Jellyfin 手动「刷新元数据」）。
- **硬链接做种库**请确认 `PUID/PGID/UMASK` 对媒体目录可写，否则会静默失败。
- 与官方「媒体库刮削」建议**二选一**：本插件已覆盖 NFO 与图片，同时开启两边可能互相覆盖。

## License

[MIT](LICENSE)
