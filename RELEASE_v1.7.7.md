## NfoGapFill v1.7.7 — 图片来源优先级 + 三处网络环境适配修复

本版新增一个**图片来源优先级**设置，并修了三处**真实网络环境下端到端刮削时暴露的环境适配问题**。
功能行为与 v1.7.6 的图片口径一致，只是把「优先用哪个源」变成可配、并让它在被拦的网络里也能真正跑通。

### ① 新增：图片来源优先级（默认 TMDB 优先，fanart.tv 其次）

同一类图若两个源都能提供，按设定顺序取**第一个命中**的；没给的留给下一个源兜底。
设置项 `image_sources` 支持四种选择（CLI 对应 `--image-sources`）：

| 取值 | 含义 |
| --- | --- |
| `tmdb,fanart` | **默认**：TMDB 优先，fanart.tv 兜底 |
| `fanart,tmdb` | fanart.tv 优先，TMDB 兜底 |
| `tmdb` | 只用 TMDB（不做 fanart 兜底） |
| `fanart` | 只用 fanart.tv（不做 TMDB 兜底） |

> **要注意数据源本身的能力差异**，否则会以为「换了顺序怎么没变」：
> TMDB 只有 `posters` / `backdrops` / `logos`（单集另有 `stills` 剧照）；
> 而**横幅图、光盘图、透明艺术图、横版缩略图（thumb / landscape）只有 fanart.tv 有**
> （`moviebanner` / `moviedisc` / `hdclearart` / `moviethumb` / `tvthumb`）。
> 所以这几类**无论顺序如何都只能取到 fanart 的** —— 优先级只对「两边都有」的类型起作用。

实测（沙丘 438631，默认 `tmdb,fanart`）：`poster` 取自 `image.tmdb.org`（TMDB），
`thumb` 取自 `assets.fanart.tv`（TMDB 没有横版缩略图，自然落到 fanart）。

### ② TMDB 接口域名可覆盖（`TMDB_API_DOMAIN`）

**根因**：接口地址此前是硬编码的 `https://api.themoviedb.org/3`。而 `api.themoviedb.org`
在部分地区会被 DNS / 网关整段拦掉，日志里表现为：

```
TMDB 请求失败（已自动重试 2 次）：/movie/438631（<urlopen error Tunnel connection failed: 502 Bad Gateway>）
```

同一服务的等价域名 `api.tmdb.org` 往往仍然可达，返回内容与官方**逐字节一致**。
此前图片域名早就跟着宿主的 `TMDB_IMAGE_DOMAIN` 走了，接口域名却换不了 —— 于是会出现
「图片能下、数据取不到」这种自相矛盾的状态。

**修法**：新增覆盖开关，优先级为 `宿主设置 TMDB_API_DOMAIN` > `环境变量 TMDB_API_DOMAIN` > 官方默认值。
两种写法都兼容：只给域名（`api.tmdb.org`）→ 自动补 `/3`；已带 `/3` 或完整 URL → 不重复拼接。

```bash
# 方式一：MoviePilot 设置里加
TMDB_API_DOMAIN=api.tmdb.org
# 方式二：给插件进程设环境变量（命令行 / docker）
export TMDB_API_DOMAIN=api.tmdb.org
```

### ③ 图片下载自动换备用源

TMDB 的图片域名 `image.tmdb.org` 被整段拦掉时，报错是：

```
图片下载失败（已重试 3 次）：https://image.tmdb.org/t/p/original/xxx.jpg
  （<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol>）
```

**修法**：`image.tmdb.org` 连不上时，自动改试 TMDB **官方 CDN 的裸域名**
`tmdb-image-prod.b-cdn.net`（同一份对象、路径完全一致）。每个候选地址各重试 3 次，
只有全部候选都失败才记一条告警。

> **不会乱换源**：用户自定义了 `TMDB_IMAGE_DOMAIN`（镜像/反代）时以用户为准，
> 插件不会再偷偷替换成别的域名；fanart.tv 的地址也不受影响。

### ④ fanart.tv Key 三级回退

**根因**：横幅图 / 光盘图 / 透明艺术图 / 横版缩略图都来自 fanart.tv，而 Key 此前**只读宿主设置**
（`mp_setting("FANART_API_KEY")`）。于是两种情况下会被误判成「没 Key」而**静默跳过**这几类图：

1. 命令行 / docker 里用环境变量 `FANART_API_KEY` 传 Key —— 插件读不到；
2. 用户压根没配 —— 但 MoviePilot 本身**自带一个可用的默认 Key**，插件却没沿用。

日志表现为：

```
要处理 banner（横幅图）、clearart（透明艺术图）、thumb（缩略图），
但拿不到 fanart.tv 的 API Key —— 这几类本轮跳过
```

**修法**：按「宿主设置 `FANART_API_KEY` → 环境变量 `FANART_API_KEY` → MP 内置默认 Key」逐级回退。

### 验证（v1.7.7 修完后的真实环境复跑）

在真实网络环境（`api.themoviedb.org` 被拦、`image.tmdb.org` 被拦）对
《沙丘 (2021)》(tmdbid 438631) 与《怪奇物语》(tvdb 转 tmdbid 66732) 第 1 季
执行一次完整刮削，**24 个图片目标全部落盘，零失败**：

| 媒体 | 根目录图片 | 季/单集 |
| --- | --- | --- |
| 电影 沙丘 (2021) | poster / backdrop (+fanart 别名) / logo / **disc** / banner / clearart / thumb (+landscape 别名) | —— |
| 电视剧 怪奇物语 (2016) | poster / backdrop (+fanart 别名) / logo / banner / clearart / thumb (+landscape 别名) | Season 01 内 poster/banner/thumb/landscape **＋根目录 season01-poster/banner/thumb**（双落点）；S01E01 同名 .jpg |

分辨率抽样：`poster 1400×2100`、`backdrop 3840×2160`、`logo 4316×1214`、
`thumb/landscape 1000×562`（**横版**，来自 fanart `moviethumb`）、`disc 1000×1000`、
`单集缩略图 1920×1080`。

### 兼容性

- **纯增量修复**，不改变 v1.7.6 的图片类型、命名与取图口径；不设 `TMDB_API_DOMAIN` 时行为与 v1.7.6 完全一致。
- 升级后若你此前因「没 Key」缺了横幅图 / 光盘图 / 横版缩略图，下一轮运行会自动补上。
- 自检：引擎 65 项 + 插件面 224 项断言全绿（新增 11 项图片来源优先级断言）。
