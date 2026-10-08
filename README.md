# MoviePilot-Plugins — 自用 MoviePilot 插件仓库

> 收录一个自用插件：**NFO 与图片差异比对**（NfoGapFill）。

![version](https://img.shields.io/badge/version-1.8.7-blue)
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
| [`NfoGapFill`](docs/NfoGapFill.md) | NFO 与图片差异比对 | 本地 NFO / 海报 / 背景图与在线元数据的**内容比对**：缺失补齐、不一致替换、一致跳过 | 1.8.7 |

点击插件名看详细文档。

### 文档

- [NfoGapFill — NFO 与图片差异比对](docs/NfoGapFill.md)：判定规则、四种运行模式、图片类型、三层保护、配置项详解、历史脏值修复
- [部署与排错](docs/DEPLOY.md)：`PLUGIN_MARKET` 配置、镜像与代理设置、常见问题

### 版本历史

- [RELEASE v1.8.7](RELEASE_v1.8.7.md) —— 「在线没有这类图片」改 debug 并修正措辞（日志不再刷屏）
- [RELEASE v1.8.6](RELEASE_v1.8.6.md) —— 图标改用 raw.githubusercontent.com（MP 图片代理的域名白名单不含 jsDelivr）
- [RELEASE v1.8.5](RELEASE_v1.8.5.md) —— 修「MP 显示不了插件图标」+ 设置页工厂化（界面零变化）
- [RELEASE v1.8.4](RELEASE_v1.8.4.md) —— 修报告文案矛盾 + 消除四处结构性重复（不改判定行为）
- [RELEASE v1.8.3](RELEASE_v1.8.3.md) —— 选图补上「分辨率兜底」：评分与票数都并列时取更大的那张
- [RELEASE v1.8.2](RELEASE_v1.8.2.md) —— 选图改为「以评分为准」：按 vote_average 降序，票数降为并列兜底
- [RELEASE v1.8.1](RELEASE_v1.8.1.md) —— 设置页排版重排 + 说明文案精简（仅界面，行为同 v1.8.0）
- [RELEASE v1.8.0](RELEASE_v1.8.0.md) —— 图片获取逻辑统一：所有类型共用「本语言 → 按投票数降序」两档规则
- [RELEASE v1.7.8](RELEASE_v1.7.8.md) —— 海报语言回退改为「本语言 → 无文字海报」，**绝不用外文海报凑数**
- [RELEASE v1.7.7](RELEASE_v1.7.7.md)
- [RELEASE v1.7.6](RELEASE_v1.7.6.md)

---

## 目录结构

```
MoviePilot-Plugins/
├── package.v2.json                  # 插件市场索引
├── plugins.v2/
│   └── nfogapfill/__init__.py       # 插件本体（MoviePilot 只下载这一个文件）
├── icons/nfogapfill.png             # 插件图标（package.v2.json 里走 jsDelivr CDN）
├── docs/                            # 文档
│   ├── NfoGapFill.md
│   └── DEPLOY.md
├── create_release.sh                  # 发版脚本（打 zip + 建 Release + 上传附件）
└── RELEASE_v1.8.7.md / RELEASE_v1.8.6.md / RELEASE_v1.8.5.md / RELEASE_v1.8.4.md / RELEASE_v1.8.3.md / RELEASE_v1.8.2.md / RELEASE_v1.8.1.md / RELEASE_v1.8.0.md / RELEASE_v1.7.8.md / RELEASE_v1.7.7.md / RELEASE_v1.7.6.md
```

约定：

- 插件目录名 = 插件 ID = 主类名 = 主类名小写（MoviePilot 按此约定加载）
- 插件入口固定为 `__init__.py`；若拆成多文件，MoviePilot 安装时会**递归下载整个插件目录**，
  同目录的辅助模块会一并安装，无需打包成单文件
- 图标走 jsDelivr CDN（`raw.githubusercontent.com` 在国内常被挡，CDN 一般可直连）
- MoviePilot 安装插件时只拉取 `plugins.v2/{插件ID}/` 下的文件，
  仓库里的 `docs/` `icons/` 都不参与安装

发版：

```bash
GH_TOKEN=你的PAT bash create_release.sh          # 自动取 PLUGIN_VERSION
```

---

## License

[MIT](LICENSE)
