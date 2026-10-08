## NfoGapFill v1.7.6 — 严格对齐 MP 官方的图片类型与命名

本版逐项核对了 MoviePilot 官方的刮削实现（`app/chain/media.py` 的 `IMAGE_ALIASES`、各媒体类型的允许集合、
季图的落盘逻辑 `_get_target_fileitems_and_paths` 与别名扩展 `_expand_with_aliases`），
并对照官方测试 `tests/test_mediascrape.py` 的命名断言，把图片类型与命名改到与 MP **完全一致**。

### 四处修正

**① 补上缩略图 `thumb.jpg`（之前完全缺失）**

MP 的电影、剧集、季目录都写缩略图，旧版只在单集写过。
现在电影 / 剧集 / 季目录都会写 `thumb.jpg`，并按 MP 的 `IMAGE_ALIASES`（`thumb ⇄ landscape`）
**同时写一份 `landscape.jpg`** —— 两者本就是同一张图的两套文件名，兼容 Kodi / Emby / Jellyfin。

**② 剧集目录不再写 `disc.png`**

MP 的 `tv`（剧集）允许集合里**没有 disc**，只有电影有。旧版给剧集也写，属于与官方不一致，现已去掉。

**③ 季目录补上缩略图**

MP 的季允许集合是 `nfo / poster / backdrop / banner / thumb / landscape`，旧版少了 `thumb`，现已补上。

**④ 季图改为与 MP 完全一致的双落点（撤销 v1.7.0 的偏离）**

v1.7.0 曾按当时的要求「只写季目录、不写剧集根目录」。核对 MP 源码后确认官方是**两个落点都写**：

```
该季目录：  poster.jpg / banner.jpg / thumb.jpg / landscape.jpg（别名）
剧集根目录：season01-poster.jpg / season01-banner.jpg / season01-thumb.jpg
季 0：      season-specials-poster.jpg（与 MP 的 get_season_poster 写法一致）
```

- 触发起因与 MP 一致：`item_type == SEASON` + 文件名以 `season` 开头 + 类型属于 `POSTER / BANNER / THUMB / BACKDROP / LANDSCAPE`。
- **根目录副本不带别名**：MP 的 `_expand_with_aliases` 遇到 `season` 前缀会直接 `continue`，
  所以根目录只有 `seasonNN-poster/-banner/-thumb`，不会出现 `season01-fanart.jpg` 或 `season01-landscape.jpg`。
- 两个落点是**同一份下载**写入两处（引擎按 URL 去重），不会重复走网络。

### 一处刻意不做：季 `backdrop`

MP 的季允许集合里列了 `backdrop`，但**没有任何数据源能提供季 backdrop** ——
TMDB 的 `/tv/{id}/season/{n}/images` 只返回 `posters`；fanart 的季级键只有
`seasonposter / seasonbanner / seasonthumb`（且是数组、需按季号过滤）。
写上去只是个永远取不到图的空操作，因此不列。

### 兼容性说明

- 本版**不删除**任何历史残留文件。v1.7.0 时期按老规则没有写出的 `seasonNN-poster.jpg`，
  本次刮削会自动补上；已经存在的 `disc.png`（剧集目录）**不会**被主动删除，如需清理请手动处理。
- 单集缩略图命名 `S01E01.jpg` 与 MP 一致，未改动。
- 引擎与配置项无破坏性变更，直接升级即可。

### 提示

由于 `package.v2.json` 里 `release: true`，请确保本版本对应的 GitHub Release（含 `nfogapfill_v1.7.6.zip` 附件）
已创建，否则 MoviePilot 安装时会先失败再回退。

---

**测试**：引擎行为 65 项断言 + 插件面 195 项断言，共 **260 项全部通过**。
