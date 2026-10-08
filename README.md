# MoviePilot-Plugins — 自用 MoviePilot 插件仓库

> 收录两个自用插件：**NFO 与图片差异比对**、**整理记录季集修正**。

![version](https://img.shields.io/badge/version-1.7.8-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![platform](https://img.shields.io/badge/MoviePilot-v2%20%7C%20v3-9cf)
![python](https://img.shields.io/badge/python-3.9%2B-yellow)

在 MoviePilot → `设定` → `插件` → **插件市场** → **自定义仓库** 填入：

```
2804826634/MoviePilot-Plugins
```

---

## 本仓库收录的插件

| 插件 ID | 名称 | 说明 | 版本 |
| --- | --- | --- | --- |
| [`NfoGapFill`](docs/NfoGapFill.md) | NFO 与图片差异比对 | 本地 NFO / 海报 / 背景图与在线元数据的**内容比对**：缺失补齐、不一致替换、一致跳过 | 1.7.8 |
| [`SpecialsFixer`](docs/SpecialsFixer.md) | 整理记录季集修正 | 对 TMDB 查无该集的整理记录识别特别篇，修正季/集为 Season 00 并重新触发 MP 整理 | 1.0.0 |

两者互不依赖，可单独安装。点击插件名看详细文档。

### SpecialsFixer 解决什么问题

番剧的官方季集数与本地资源常常对不上 —— 比如《无职转生》第一季 TMDB 只登记 23 集，
但下载到的资源有 24 集，多出的那集其实是特别篇（SP / OVA / 特典），却被并进了正片季。

本插件在整理**已完成**后发现「这集在 TMDB 查不到」，判定它是否属特别篇，
确认后只改整理记录里的季/集两个字段，再交回 MoviePilot 自身的流程重新整理 ——
**不自行刮削、不写媒体元数据**，元数据仍然只由 MP 自己的机制生成。

三道闸门默认全关，逐级放开：先 `report` 模式巡检确认判定 → 再 `dry_run` 看修正预览
→ 最后才开 `auto_apply`。详见 [文档](docs/SpecialsFixer.md)。

### 文档

- [NfoGapFill — NFO 与图片差异比对](docs/NfoGapFill.md)：判定规则、四种运行模式、图片类型、三层保护、配置项详解、历史脏值修复
- [SpecialsFixer — 整理记录季集修正](docs/SpecialsFixer.md)：匹配失败的三态判定、四路证据加权、季/集修正规则、`manual_transfer` 调用入口、兜底处理
- [部署与排错](docs/DEPLOY.md)：`PLUGIN_MARKET` 配置、镜像与代理设置、常见问题
- [Jellyfin 详情页 logo/文字二选一](jellyfin/logo-title-fix.css)：把 CSS 引入 Jellyfin 自定义 CSS 即可

### 版本历史

- [RELEASE v1.7.8](RELEASE_v1.7.8.md) —— 海报语言回退改为「本语言 → 无文字海报」，**绝不用外文海报凑数**
- [RELEASE v1.7.7](RELEASE_v1.7.7.md)
- [RELEASE v1.7.6](RELEASE_v1.7.6.md)

---

## 目录结构

```
MoviePilot-Plugins/
├── package.v2.json                  # 插件市场索引（两个插件都在这里登记）
├── plugins.v2/
│   ├── nfogapfill/__init__.py       # 单文件插件
│   └── specialsfixer/
│       ├── __init__.py              # 主类：事件钩子、巡检编排、修正与重整
│       ├── fixer_core.py            # 纯逻辑：三态判定、证据加权、修正规则
│       └── tmdb_probe.py            # TMDB 客户端（区分 404 与网络失败）
├── icons/                           # 两个插件的图标（package.v2.json 里走 jsDelivr CDN）
├── docs/                            # 每个插件一篇文档，与 README 的清单对应
│   ├── NfoGapFill.md
│   ├── SpecialsFixer.md
│   └── DEPLOY.md
├── scripts/
│   ├── make_plugin_icons.py       # 本地绘制插件图标（无第三方依赖）
│   ├── build_preview.py
│   └── fetch_real_samples.py
├── tests/                           # 离线测试（不连 MoviePilot，伪造宿主 app 包）
│   ├── _self_test.py / _self_test_plugin.py / _fixture/
│   └── specials/test_specialsfixer.py       # 78 项
├── jellyfin/logo-title-fix.css      # Jellyfin 详情页 logo/文字二选一
└── RELEASE_v1.7.8.md / RELEASE_v1.7.7.md / RELEASE_v1.7.6.md
```

约定：

- 插件目录名 = 插件 ID = 主类名 = 主类名小写（MoviePilot 按此约定加载）
- 多文件插件的入口固定为 `__init__.py`；MoviePilot 安装时会**递归下载整个插件目录**，
  所以同目录的辅助模块会一并安装，无需打包成单文件
- SpecialsFixer 做了分层：纯逻辑层（`fixer_core.py`）不依赖宿主，可脱离 MoviePilot离线单测

离线测试：

```bash
python tests/specials/test_specialsfixer.py       # 78 项
```

---

## License

[MIT](LICENSE)
