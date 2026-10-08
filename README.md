# MoviePilot-Plugins — 自用 MoviePilot 插件仓库

> 收录一个自用插件：**NFO 与图片差异比对**（NfoGapFill）。

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

点击插件名看详细文档。

### 文档

- [NfoGapFill — NFO 与图片差异比对](docs/NfoGapFill.md)：判定规则、四种运行模式、图片类型、三层保护、配置项详解、历史脏值修复
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
├── package.v2.json                  # 插件市场索引
├── plugins.v2/
│   └── nfogapfill/__init__.py       # 单文件插件
├── icons/nfogapfill.png             # 插件图标（package.v2.json 里走 jsDelivr CDN）
├── docs/                            # 文档
│   ├── NfoGapFill.md
│   └── DEPLOY.md
├── scripts/
│   ├── build_preview.py
│   └── fetch_real_samples.py
├── tests/                           # 离线测试（不连 MoviePilot，伪造宿主 app 包）
│   ├── _self_test.py / _self_test_plugin.py / _fixture/
├── jellyfin/logo-title-fix.css      # Jellyfin 详情页 logo/文字二选一
└── RELEASE_v1.7.8.md / RELEASE_v1.7.7.md / RELEASE_v1.7.6.md
```

约定：

- 插件目录名 = 插件 ID = 主类名 = 主类名小写（MoviePilot 按此约定加载）
- 插件入口固定为 `__init__.py`；若拆成多文件，MoviePilot 安装时会**递归下载整个插件目录**，
  同目录的辅助模块会一并安装，无需打包成单文件
- 图标走 jsDelivr CDN（`raw.githubusercontent.com` 在国内常被挡，CDN 一般可直连）

离线测试：

```bash
python tests/_self_test_plugin.py       # 269 项
```

---

## License

[MIT](LICENSE)
