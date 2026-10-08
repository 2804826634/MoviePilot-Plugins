# NfoGapFill v1.8.5 — 修「MP 识别不到插件图标」+ 设置页工厂化

## 一句话

**修好图标不显示**（根因在 MP 的取图路径），并把 313 行的 `get_form()` 压到 170 行 —— **界面零变化**。

## 一、图标为什么不显示（根因）

MP 取插件图标有**两条不同的路**（`app/core/plugin.py`）：

| 场景 | 取图标的位置 | 源码 |
|---|---|---|
| **已安装插件**的卡片 | 插件类的 **`plugin_icon` 属性** | 第 1427 行 `if hasattr(plugin_class, "plugin_icon")` |
| **插件市场**里的条目 | `package.v2.json` 的 **`icon` 字段** | 第 1688 行 `if plugin_info.get("icon")` |

而 `_merge_plugin_market_metadata()`（同一个文件第 235 行）把市场元数据合并到已安装插件时，合并了 `history` / `release` / `has_update` / `system_version`，**唯独没有 `icon`** —— 所以**已安装插件的图标永远取自类属性，市场里改图标对它无效**。

我们的类属性当时写的是：

```python
plugin_icon = "NfoGapFill.png"      # ← 裸文件名
```

问题在于 **MP 安装插件时只下载 `plugins.v2/{插件ID}/` 下的文件**（`__get_file_list`），仓库根目录的 `icons/` 根本不参与安装。所以这个文件在插件目录里**不存在**，图标必然 404；而且连大小写都对不上（真实文件是 `nfogapfill.png`）。

**这就解释了「市场里能看到图标、装完却没有」的现象** —— v1.7.1 那次只改了 `package.v2.json` 的市场图标，没动类属性。

### 修法

`plugin_icon` 指向与 `package.v2.json` **同一个 jsDelivr CDN 地址**，并抽成常量、在注释里写明两条取图路径：

```python
PLUGIN_ICON = ("https://cdn.jsdelivr.net/gh/2804826634/MoviePilot-Plugins@main/"
               "icons/nfogapfill.png")
...
plugin_icon = PLUGIN_ICON
```

> 官方仓库也是这个写法：`plugin_icon = "https://raw.githubusercontent.com/.../icons/xxx.png"`。
> 用 jsDelivr 而不用 raw.githubusercontent.com 是因为后者在国内常被挡。

顺带修了 `plugin_desc` —— 它还写着 v1.8.0 已删除的「支持字段保护」，现与 `package.v2.json` 对齐。

### 升级后仍看不到图标？

1. 插件页点「**刷新**」（重新拉取插件），或重启 MP；
2. 若 MP 服务器访问不了 `cdn.jsdelivr.net`，图标仍是加载不出来 ——
   这是网络问题而不是配置问题，可在浏览器里直接打开那个 URL 验证。

## 二、设置页工厂化（P2）

`get_form()` 原本是 **313 行手写的嵌套字典**：同样的 `VCol` 外壳抄了 19 遍、`VRow` 抄了 27 遍，加一个配置项要写 8 行、缩进到 12 层。

新增 8 个小工厂，**一个控件一行**：

```python
form_row(
    form_select("mode", "处理模式", {
        "sync": "不一致则替换（缺失补齐 + 不同替换 + 相同跳过）",
        "gapfill": "只补缺失（不动任何已有内容）",
        "report": "只报告差异（不写入任何文件）",
        "force": "强制全部覆盖（等同官方插件 force_all，慎用）",
    }),
    form_cron("cron", "执行周期", "留空 = 每周日凌晨 3 点跑一次；也可填 5 位 cron，如 0 3 * * *"),
),
```

下拉选项改用 `{值: 显示名}` 字典写，比原来的 `{"title":…, "value":…}` 列表**短一半**。

| 指标 | 改前 | 改后 |
|---|---|---|
| `get_form()` 行数 | 313 | **170** |
| 最深缩进 | 51 空格（约 12 层） | **34 空格** |
| 加一个配置项 | 8 行 | **1 行** |
| 脚本总行数 | 3792 | **3712（−80）** |

### 界面零变化（有据）

重构前后把表单 JSON 逐项对比：

- **表单结构完全一致** —— 归一化后 JSON 序列化长度都是 **8454 字符**，`a == b` 为真
- **默认配置完全一致** —— 默认值字典逐键相等
- 唯一差别：整行列补上了显式 `md: 12`，与原来的 `{"cols": 12}` 在 Vuetify 语义上等价

## 三、回归验证

- **离线断言 353 项全绿**：插件面 286 项 + 引擎面 67 项
  - 新增 12 项锁定本版：`plugin_icon` 必须是 https 绝对地址且**不是裸文件名**、
    与 `PLUGIN_ICON` 常量一致、`plugin_desc` 不含已删除功能、
    `get_form` 源码里不再有手写的 `VCol`/`VRow` 字典、
    篇幅 ≤200 行（回退即报警）、缩进 ≤40 空格、8 个工厂函数的行为
- **表单等价性**：重构前后 JSON 逐项对比，结构一致（见上）
- **跨文件一致性**：`plugin_icon` == `package.v2.json` 的 `icon`；
  `plugin_desc` == `description`

## 四、升级注意

- **配置无需改动**
- **设置页外观完全不变**（已用 JSON 对比验证），只是代码组织方式变了
- 图标若仍未显示，先刷新/重启 MP；仍不行就是 MP 服务器访问不了 CDN，可在浏览器打开图标 URL 验证
