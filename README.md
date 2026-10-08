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

| 插件 ID | 名称 | 说明 | 版本 |
| --- | --- | --- | --- |
| [`NfoGapFill`](docs/NfoGapFill.md) | NFO 与图片差异比对 | 本地 NFO / 海报 / 背景图与在线元数据的**内容比对**：缺失补齐、不一致替换、一致跳过 | 1.7.7 |
| [`SpecialsFixer`](docs/SpecialsFixer.md) | 整理记录季集修正 | 对 TMDB 查无该集的整理记录识别特别篇，修正季/集为 Season 00 并重新触发 MP 整理 | 1.0.0 |
| [`SpecialsRelocate`](docs/SpecialsRelocate.md) | 特别篇归位 | 比对本地集数与 TMDB 官方季集数，识别超范围剧集并移入 Season 00 重编号 | 1.0.0 |

三者互不依赖，可单独安装。点击插件名看详细文档。

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

**建议**：先用 [`SpecialsFixer`](docs/SpecialsFixer.md)（保守，交给 MP 走正常流程）。只有当 MP 整理链路本身处理不了、或你要脱离 MP 自行管理目录时，才用 [`SpecialsRelocate`](docs/SpecialsRelocate.md)。

### 文档

- [NfoGapFill — NFO 与图片差异比对](docs/NfoGapFill.md)：判定规则、四种运行模式、图片类型、三层保护、配置项详解、历史脏值修复
- [SpecialsFixer — 整理记录季集修正](docs/SpecialsFixer.md)：匹配失败的三态判定、四路证据加权、季/集修正规则、`manual_transfer` 调用入口、兜底处理
- [SpecialsRelocate — 特别篇归位](docs/SpecialsRelocate.md)：集数比对逻辑、三重证据判定、安全设计、触发时机、可配置项
- [部署与排错](docs/DEPLOY.md)：`PLUGIN_MARKET` 配置、镜像与代理设置、常见问题
- [Jellyfin 详情页 logo/文字二选一](jellyfin/logo-title-fix.css)：把 CSS 引入 Jellyfin 自定义 CSS 即可

### 版本历史

- [RELEASE v1.7.7](RELEASE_v1.7.7.md)
- [RELEASE v1.7.6](RELEASE_v1.7.6.md)

---

## 目录结构

```
MoviePilot-Plugins/
├── package.v2.json                  # 插件市场索引（三个插件都在这里登记）
├── plugins.v2/
│   ├── nfogapfill/__init__.py       # 单文件插件
│   ├── specialsfixer/
│   │   ├── __init__.py              # 主类：事件钩子、巡检编排、修正与重整
│   │   ├── fixer_core.py            # 纯逻辑：三态判定、证据加权、修正规则
│   │   └── tmdb_probe.py            # TMDB 客户端（区分 404 与网络失败）
│   └── specialsrelocate/
│       ├── __init__.py              # 主类：事件钩子、扫描编排、迁移执行
│       ├── core.py                  # 纯函数判定层：集号/季号解析、关键词、置信度
│       ├── fileops.py               # 文件层：安全移动、Season 00 推导、NFO
│       └── tmdb.py                  # TMDB 客户端：多域名回退 + 退避重试
├── icons/                           # 三个插件的图标（package.v2.json 里走 jsDelivr CDN）
├── docs/                            # 每个插件一篇文档，与 README 的清单对应
│   ├── NfoGapFill.md
│   ├── SpecialsFixer.md
│   ├── SpecialsRelocate.md
│   └── DEPLOY.md
├── scripts/
│   ├── make_specials_icons.py       # 本地绘制两个特别篇插件的图标（无第三方依赖）
│   ├── build_preview.py
│   └── fetch_real_samples.py
├── tests/                           # 离线测试（不连MoviePilot，伪造宿主 app 包）
│   ├── _self_test.py / _self_test_plugin.py / _fixture/
│   └── specials/
│       ├── test_specialsfixer.py       # 78 项
│       └── test_specialsrelocate.py# 105 项
├── jellyfin/logo-title-fix.css      # Jellyfin 详情页 logo/文字二选一
└── RELEASE_v1.7.7.md / RELEASE_v1.7.6.md
```

约定：

- 插件目录名 = 插件 ID = 主类名 = 主类名小写（MoviePilot 按此约定加载）
- 多文件插件的入口固定为 `__init__.py`；MoviePilot 安装时会**递归下载整个插件目录**，
  所以同目录的辅助模块会一并安装，无需打包成单文件
- 两个特别篇插件都做了分层：纯逻辑层不依赖宿主，可脱离 MoviePilot 离线单测

离线测试：

```bash
python tests/specials/test_specialsfixer.py       # 78 项
python tests/specials/test_specialsrelocate.py    # 105 项
```

---

## License

[MIT](LICENSE)
