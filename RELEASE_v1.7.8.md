# NfoGapFill v1.7.8 — 海报语言回退：中文 → 无文字，绝不用外文

## 一句话

以前没有中文海报时会拿日文/英文海报顶上（同一个库里中、日文标题海报混着），
现在只走 **本语言 → 无文字海报 → 明确不写**，绝不写外文海报。

## 问题现场

用户的媒体库是中文元数据（`language=zh-CN`），但整理出来的海报语言不一致 ——
有的是中文标题，有的干脆是日文标题。

真实数据（TMDB id 312949 尼古喵喵，14 张海报）：

| 情况 | 在线分布 | 旧版结果 | 新版结果 |
|---|---|---|---|
| 有中文海报 | zh=3 / ja=3 / en=5 / null=3 | 视排序而定，可能选到 ja | **中文海报**（带中文标题「尼咕喵喵」） |
| 中文为0、无文字也很少 | zh=0 / ja=9 / null=1 / en=10 | **日文标题海报** | **无文字海报** |

关键在于第二种：很多老番 / 冷门片 TMDB 上**根本没人上传中文海报**，
所以「优先中文」对它无效 —— 旧代码的兜底逻辑把「其它语言」也算进候选，
于是挑了日文那张。新版在这种情况下退到无文字海报（纯画面），观感是干净的。

## 规则（最终确认版）

```
第1 优先级  本语言 =「元数据语言」配置（zh-CN → zh）
            ↓ 一张都没有
第 2 优先级  无文字海报（TMDB iso_639_1 为空）
            ↓ 也没有
第 3 步→ 返回 None，该图片类型记为缺失、不写文件、报告里说明原因
```

**明确不做的事**：不回退到英文、不回退到原始语言（日文）、不按票数/分辨率/评分排序、
不拿剧集海报顶替季海报。

## 改动清单

### 核心：`pick_best_image()` 改为严格语言匹配

```python
def lang_rank(item: dict):
    """0 = 本语言；1..N = 回退档位；**None = 不该选它**。"""
    code = (item.get("iso_639_1") or "").lower()
    if lang and code == lang:
        return 0
    for idx, key in enumerate(order, start=1):
        if key == "textless" and not code:
            return idx
        if key == "en" and code == "en":
            return idx
        if key == "original" and orig and code == orig:
            return idx
    return None                     # 其它语言一律不选
```

关键变化：旧代码对不匹配任何档位的候选返回 `len(order) + 1`，
等于把**所有其它语言都收进候选池**；现在返回 `None` 并在筛选时剔除：

```python
eligible = [(item, lang_rank(item)) for item in entries if item.get("file_path")]
eligible = [(item, rank) for item, rank in eligible if rank is not None]
if not eligible:
    return None                    # 明确表示「没有合适的图」
```

### 新增 `poster_fallbacks` 配置

- 默认 `("textless",)` —— 只有无文字一档。
- 设置页单选下拉，6 个选项：默认项 + 5 种放宽组合。
- CLI 新增 `--poster-fallbacks`。
- 非法值丢弃，全非法时回落 `textless`（**永不返回空，也永不自动放宽成外文**）。

### TMDB 请求按回退链动态构造

```python
order = self.poster_fallbacks
wanted = [lang, "null"]                      # 无文字版始终在候选里
if "en" in order and "en" not in wanted:
    wanted.append("en")
if "original" in order:
    original_lang = self._original_language(tmdb_id, media_type)
    ...
include = ",".join(part for part in wanted if part)
```

`include_image_language` 是**服务端**过滤：不列的语言 TMDB 根本不返回。
早期版本固定 `null,zh,en,ja`，既浪费配额又把日文混进候选。
新增 `_original_language()` 从电影/剧集主记录取 `original_language`
（季/单集接口没有这个字段），并按 `tmdb_id` 缓存。

### 逐类型独立判定

海报有中文版而徽标没有，是常态（TMDB 上传进度不均匀）。
每个图片类型**各自**跑一遍上面的语言链 ——
海报写中文版、徽标写无文字版，不会「因为徽标没中文图，连海报也一起放弃」。

### 报告里必须能说清「为什么不写」

「在线压根没上传这张图」和「在线有图但全是外文、按规则不放行」
是两回事。以前只有季海报会记录缺失原因，电影/剧集因为语言不匹配被跳过时
**完全静默** —— 用户只看到「没写海报」，根本不知道是有中文图之外的选择被主动放弃。

新增 `TmdbProvider.lang_rejected`，在有候选但选不中时记下人话说明：

```
在线这类型只有 日文/英文 的图，没有 中文 版、也没有无文字版；按「不拿外文海报凑数」的规则已跳过（未写入）
```

引擎层 `process_images()` 读到后，在变更明细里记为
`跳过（没有合适语言的图）`，并 `logger.info` 出来。
语言码经 `LANG_CN` 映射成中文（`ja`→日文、`en`→英文、`None`→无文字），
未知码原样显示，不编造名称。

### ★ 真实数据验证时发现并修掉的缺口：探测请求

上面那段逻辑有个前提：`entries` 非空。但 `include_image_language` 是
**服务端过滤** —— 严格模式只请求 `zh,null`，遇到「只有外文图」的条目时
TMDB 返回的是**空列表**，于是 `elif entries` 压根不成立，
恰恰是最需要解释的场景解释不出来。

实测（Friends，TMDB id 2420，poster 只有 1 张英文、无中文也无无文字）：

| `include_image_language` 写法 | TMDB 返回 |
|---|---|
| `zh,null`（严格模式） | **0 张** |
| 省略该参数 | **0 张** |
| 传空串 | **0 张** |
| `en` | 1 张（英文） |

也就是说「不传参数」并不等于「全部语言」—— 必须**显式枚举**语言码。
于是对没选中的类型补一次探测请求：

```python
probe_langs = ",".join(("zh", "null", "en", "ja", "ko", "fr", "de", "es",
                        "it", "pt", "ru", "th", "vi", "hi", "ar",
                        "sv", "da", "nl", "pl", "tr"))
```

探测结果**只用于生成说明文案，绝不用于选图**（有专门断言守着这一点）。
一次请求覆盖 20 种常见语言，代价可接受；网络失败/限流时静默返回空，
不影响主流程。

修复后的真实输出：

```
【默认严格】回退链=['textless']
   poster  -> （不写）
           说明: 在线这类型只有 英文 的图，没有 中文 版、也没有无文字版；
                 按「不拿外文海报凑数」的规则已跳过（未写入）
【放宽：无文字→英文→原始语言】
   poster  -> d6DGaL0vv1NztWSImbGDwHQsDB5.jpg
```

## 顺手修掉的配置 bug

`poster_fallback_order()` 的合法值校验写成了：

```python
if part in POSTER_FALLBACKS and part not in order:   # ← 错
```

`POSTER_FALLBACKS` 是**默认档位**（收窄后只剩 `("textless",)`），
不是**可选档位全集**。于是 `en` / `original` 永远被当非法值丢弃 ——
界面上能选「英文 → 无文字海报」，实际配进去还是被收敛成 `["textless"]`，
宽松模式形同虚设。改用新增的 `POSTER_FALLBACK_CHOICES` 做白名单：

```python
POSTER_FALLBACK_CHOICES = ("textless", "en", "original")   # 全集
POSTER_FALLBACKS = ("textless",)                           # 默认值
```

这个 bug 是被单测断言「把 en 排在 textless 前，则选英文」抓出来的。

## 测试

`tests/_self_test_plugin.py` 新增/重写选图测试块：

- 尼古喵喵场景：有中文 → 选中文（`/zh.jpg`）
- 无中文 → 选无文字（`/textless.jpg`），**不**选日文
- 候选里只剩英文/日文 → 返回 `None`
- 元数据语言=英文 / 日文时，按对应语言优先（规则跟着「元数据语言」走）
- 显式加 `en` / `original` 后才允许外文，且**顺序决定优先级**
- `poster_fallback_order()` 对逗号串 / 列表 / 非法值 / 全非法值的收敛
- 白名单用 `POSTER_FALLBACK_CHOICES`（全集）而非 `POSTER_FALLBACKS`（默认值）
- `_describe_rejection()` 的语言名映射与未知码兜底
- `_probe_foreign_langs()`：会额外发一次探测、显式枚举语言码、
  **探测到的外文图绝不会被当成结果返回**
- 引擎级：只有外文图时不写盘 + 报告说清原因 + 不误计入 `images_missing`

**269 项断言全部通过，失败 0。**

## 升级影响

- 无需改配置：`poster_fallbacks` 缺失时按 `textless` 处理。
- 存量文件**不会被自动重刷** —— 图片判定依据是「文件在不在」。
  想让没中文海报的片子换成无文字版，需要对这类条目跑一次 `sync` + `force_all`，
  或手动删掉那几张 poster 再跑 `missing`。
- 想保持旧行为（宁可要日文也不要留空）：把「没有本语言海报时，回退到」
  改成 `无文字海报 → 原始语言（日文）→ 英文`。
- **多了探测请求**：某类型按规则没选到时会多发一次 TMDB 请求（仅用于生成说明）。
  条目极多且网络受限时，探测会跟着重试，但失败即静默跳过，不影响取图结果。

## 验证方式

```bash
python tests/_self_test_plugin.py
# 共 269 项断言，通过 269，失败 0
```

真实 API 抽查（`language=zh-CN`、默认回退链 `['textless']`）：

| 条目 | 类型 | 在线分布（zh,null 查询） | 结果 |
|---|---|---|---|
| 尼古喵喵 (312949) | poster | zh=3 / null=3 | **中文** `p5soa8DFv7PYxjOlTMY1ARHjT3a.jpg` |
| 尼古喵喵 (312949) | backdrop | null=6（**0 张中文**） | **无文字** `4ei68OmZr0XHnN82OjiV8GBqfyN.jpg` |
| 尼古喵喵 (312949) | logo | zh=3 | **中文** `v6dh19zxE4hEkd0ErseZt7AejSZ.png` |
| Friends (2420) | poster | **0 张**（只有 1 张英文） | **不写** + 说明「在线这类型只有 英文 的图…」 |

三条尼古喵喵的结果正是「**逐类型独立判定**」的实证：同一部剧，
poster 与 logo 命中中文，backdrop 因为一张中文都没有而退到无文字版，
三者互不牵连。

放宽模式的对照（验证回退链顺序真的生效）：

| 配置 | backdrop 结果 |
|---|---|
| `textless`（默认） | `4ei68O...`（无文字） |
| `textless,en,original` | `4ei68O...`（无文字优先） |
| `en,textless` | `zAMw1Nu5XzGW50eNjBkIxF3kfrx.jpg`（英文） |
| 元数据语言改成 `ja-JP` | `aTcxCPsjOE8YRKzM8yWThRmPd5x.jpg`（日文，规则跟着元数据语言走） |