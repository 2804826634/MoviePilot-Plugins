# 部署与排错

## 一、三种部署方式怎么选

| 方式 | 持久性 | 能自动升级 | 适用场景 |
| --- | --- | --- | --- |
| A. 插件市场（自定义仓库） | 好 | ✅ | 长期使用，**推荐** |
| B. 本地插件仓库挂载 | 好 | 需 `git pull` | 内网、不想让 MP 联网拉 GitHub |
| C. 单文件丢进插件目录 | ❌ 升级镜像即丢 | ❌ | 临时试用、调试 |

---

## 二、方式 A：插件市场安装

MoviePilot 通过环境变量 `PLUGIN_MARKET`（逗号分隔的 `owner/repo` 列表）决定去哪些 GitHub 仓库拉取 `package.v2.json`。

```yaml
# docker-compose.yml
services:
  moviepilot:
    environment:
      - PLUGIN_MARKET=jxxghp/MoviePilot-Plugins,2804826634/moviepilot-nfo-gapfill
```

- **追加**而不是覆盖，官方市场依然可用。
- 也可以在 UI 里：`设定 → 插件 → 插件市场 → 自定义仓库` 直接填 `2804826634/moviepilot-nfo-gapfill`。
- MP 会请求 `https://raw.githubusercontent.com/2804826634/moviepilot-nfo-gapfill/main/package.v2.json`。
  如果容器访问 GitHub 困难，配置 `PROXY_HOST` 或将 `GITHUB_TOKEN` 填上（提高 API 限额）。
- 拉取成功后，市场里搜索「NFO」即可看到本插件，点击安装。

> 仓库必须是 **public**。私有仓库需要 MP 侧带 Token 访问，一般不建议。

---

## 三、方式 B：本地插件仓库

```bash
git clone https://github.com/2804826634/moviepilot-nfo-gapfill.git /path/to/mp_plugins
```

```yaml
volumes:
  - /path/to/mp_plugins:/mp_plugins:ro
environment:
  - PLUGIN_LOCAL_REPO_PATHS=/mp_plugins
```

要点：

- `PLUGIN_LOCAL_REPO_PATHS` 指向的是**仓库根目录**（即包含 `package.v2.json` 的那一层），不是 `plugins.v2`。
- 用 `:ro` 只读挂载即可；MP 只读不写。
- 多个本地仓库用英文逗号分隔。
- 重启容器后生效，市场来源里会出现「本地仓库」。

---

## 四、方式 C：单文件手动放入

```bash
# 1) 拷进容器
docker cp plugins.v2/nfogapfill/__init__.py moviepilot-v2:/config/NfoGapFill.py

# 2) 查真实插件目录（不同镜像/版本不一样）
docker exec -it moviepilot-v2 python -c \
  "import app.plugins,os;print(os.path.dirname(app.plugins.__file__))"

# 3) 移进插件目录（文件名必须是插件 ID = 类名）
docker exec -it moviepilot-v2 mv /config/NfoGapFill.py <上一步输出的目录>/

# 4) 重启
docker restart moviepilot-v2
```

⚠️ **文件名必须是 `NfoGapFill.py`**（等于类名）。改名会导致 MP 找不到插件类。
升级 MoviePilot 镜像后 `/app` 会被重置，需要重新执行一次。

---

## 五、首次运行建议流程

1. 安装后在插件配置里只填 **媒体库目录**，`mode` 选 **只报告差异**，打开 **演练模式**，
   图片先设 `image_mode = 只补缺失图片`，保存并「保存后立即运行一次」。
2. 打开插件详情页看报告，确认：
   - 扫描到的 NFO 数量对得上；
   - 「不一致」清单里确实是**你认为该改**的字段（如果里面有你的手工润色，把它加进「保护字段」）；
   - 图片那一节（`检查图片 N 张 / 图片判定 / 图片动作`）里，缺失与不一致的数量符合直觉。
3. 切 `mode = 不一致则替换`，关掉演练模式，直接「保存后立即运行一次」。
   图片此时建议仍保持 `missing`，先把 NFO 校准好。
   本插件已不提供「单轮最多处理文件数」上限 —— 想分批就把 `媒体库目录` 先填成某个子目录，
   跑顺了再换成整库根目录。
4. NFO 稳定后把 `image_mode` 切到 **缺失补齐 + 不一致替换**，跑一轮建立图片指纹
   （这一轮会下载比对，有流量开销；同样可以先只填子目录来控制规模）。
5. 确认无误后把 `媒体库目录` 换回整库根目录，设置 `cron` 周期任务。之后每轮图片几乎是零流量。

---

## 六、排错清单

| 现象 | 原因 / 处理 |
| --- | --- |
| 市场里看不到插件 | `PLUGIN_MARKET` 没生效（改完要重启容器）；仓库不是 public；容器访问不了 raw.githubusercontent.com，配 `PROXY_HOST` 或 `GITHUB_TOKEN` |
| **插件图标显示成默认的拼图块** | MP 是把 `package.v2.json` 里的 `icon` 字段**原样交给浏览器**加载的（服务端不代理图标），所以 raw.githubusercontent.com 在国内被挡时，市场列表能刷出来、图标却加载不出来。v1.7.1 起图标改用 **jsDelivr CDN**（一般可直连）。若仍不显示：① 插件市场点「刷新」让 MP 重新读取；② 浏览器硬刷新（Ctrl+F5）；③ 直接在浏览器打开那个图标链接确认能否访问，打不开说明该 CDN 也被挡，换成自己的图床地址即可 |
| 图标是破图 | 属于正常降级，不影响功能；确认 `package.v2.json` 里 `icon` 的 URL 可访问 |
| 扫描到 0 个 NFO | `paths` 填的是容器内路径（如 `/media/link/电影`），不是宿主机路径；确认该目录在容器里存在 |
| 某个目录下的 NFO 完全没被处理 | 检查「媒体库目录」是否给该目录加了 `#电影` / `#电视剧`，而它的类型不匹配；报告里的「按目录的『#类型』限定跳过 N 个 NFO」会体现出来。确认后把后缀去掉或改成正确类型即可 |
| 出现 **`season00-poster.jpg`** 这种文件 | v1.6.2 及更早的 bug：季号的「取名」与「取图」用了**两套解析** —— 取名那套解析不出就默认 0，于是给根本没有第 0 季的剧写出 `season00-poster.jpg`（用户遇到过）。v1.6.3 起两处统一走同一套解析；**解析不出季号就干脆不写季专用名**，绝不默认 0。另外中文季目录（`第一季` / `第十二季`）现在也能识别。已生成的 `season00-poster.jpg` 请手动删掉，之后不会再产生 |
| 日志大量 **`SSL handshake timed out`** / `取不到在线数据` | 国内直连 `api.themoviedb.org` 不稳定。v1.6.3 起 TMDB 请求**自动重试 3 次**（递增退避，404 不重试），报告里会写「网络抖动自动重试 N 次」。若仍大量失败，请在 MoviePilot 里配置 `PROXY_HOST` 代理 |
| 出现 **`season00-poster.jpg`** 这种文件 | v1.6.2 及更早的 bug：季号的「取名」与「取图」用了**两套解析** —— 取名那套解析不出就默认 0，于是给根本没有第 0 季的剧写出 `season00-poster.jpg`（用户遇到过）。v1.6.3 起两处统一走同一套解析；**解析不出季号就干脆不写季专用名**，绝不默认 0。另外中文季目录（`第一季` / `第十二季`）现在也能识别。已生成的 `season00-poster.jpg` 请手动删掉，之后不会再产生 |
| 日志大量 **`SSL handshake timed out`** / `取不到在线数据` | 国内直连 `api.themoviedb.org` 不稳定。v1.6.3 起 TMDB 请求**自动重试 3 次**（递增退避，404 不重试），报告里会写「网络抖动自动重试 N 次」。若仍大量失败，请在 MoviePilot 里配置 `PROXY_HOST` 代理 |
| 日志出现「**无法确定季号**」 | v1.6.1 及更早的 bug：`season.nfo` 这个**文件名里根本没有季号**，旧版只从文件名兜底 → 整季被跳过。v1.6.2 起会从**上级目录名**解析季号（`Season 01` / `S01` / `第 1 季` / `Season 1 - 1080p` 都认；`Specials` / `特别篇` 按惯例归第 0 季；`S01E01` 这类单集命名不会被误当季目录）。缺失的 `<season>` 会被一并补上 |
| **单集 NFO 全部提示「取不到在线数据，保持原样」** | v1.6.0 及更早的 bug：单集 NFO 里的 `<tmdbid>` 是**这一集自己的 id**，旧版拿它当「剧集 id」去查 TMDB 的 season/episode 接口 → 必然 404。v1.6.1 已改为**向上取剧集 id**（优先同剧 `tvshow.nfo`，其次剧集目录名里的 `{tmdbid=xxx}`，再退回按剧集名搜索）。升级后跑一轮即可自动修好 |
| 脏值（`{'id': 12, ...}`）清不掉 | v1.6.1 起，脏值清理不再被「只补缺失」模式、保护字段、`lockdata` 锁定或「取不到在线数据」挡住 —— 这些脏值本来就是本插件旧版写坏的，不该被保护（写盘前仍会备份）。另外 Jellyfin 的「工作室」只认 `<studio>` 标签，已核对过其源码 |
| 图片类型下拉框选了却像单选 | 请确认插件已升到 v1.3.0 以上 —— 早期版本用的是复选框，在 MP 里只能单选 |
| 开了 `notify` 但没收到通知 | 检查 MP 的「通知设置」是否配置了通知渠道 |
| 报告一直空 | 数据源没拿到数据：`tmdb_api_key` 无效 / 被墙；或 `HostProvider` 在该 MP 版本上字段映射不兼容 → 填 TMDB Key 走直连 |
| 写入报权限错误 | `PUID/PGID/UMASK` 要对媒体目录有写权限；硬链接做种库尤其注意 |
| 点了运行但没变化 | `mode` 是否为 `report`？`dry_run` 是否开着？字段是否命中 `protect_fields` 或 NFO 内 `lockedfields`？ |
| 报错 `429 Too Many Requests` | TMDB 限速，调小批次并错峰运行；内置限速为 4 req/s |
| 中文标点被改成半角 | 属于历史 bug，已在 v1.0.0 修复：比对走 NFKC 归一化，写入始终用原值 |
| 详情页出现「空表格」：只剩一条 `Items per page / 1-10 of 29` 分页条，表体一行都不显示 | v1.4.1 及更早版本的 bug：表格组件在插件详情页里渲染不出来（**数据是好的，只是没显示**）。v1.4.2 已改成只读文本清单 |
| 详情页提示「图片下载失败」 | 多数是 `image.tmdb.org` 在国内超时。v1.4.2 起会自动沿用 MP 的 `PROXY_HOST` 与 `TMDB_IMAGE_DOMAIN`，并**自动重试 3 次**；在 MP 设置里配好代理或图片镜像即可。失败条目下次运行会自动重试，不影响其它文件 |
| 日志出现「图片下载失败（已重试 3 次）」 | 三次都没成功，才会记一条。检查 MP 的代理设置与 `TMDB_IMAGE_DOMAIN`；只影响这一张图 |
| 类型/导演/工作室显示成 `{'id': 12, 'name': '冒险'}` 这种 Python 字面量 | v1.4.0 及更早版本的 bug：走宿主刮削通道时，宿主的 `genres`/`production_companies`/`directors` 是结构化对象，旧版直接 `str()` 写进了 NFO。**升级到 v1.4.3 后用 `sync` 模式跑一轮即可自动修好** |
| 干净名字与 dict 脏值**同时存在**（例如工作室一半正常一半是 `{'id': …}`） | 属于历史残留：旧版写下的脏值没被清掉。v1.4.3 起只要某字段存在「对象字面量」就强制整段重写，并**同时清理同义标签 `<network>`** 里的脏值；报告里会写「清理历史脏值 N 处」 |
| 修完后又冒出来了 | 说明还有第三方在改这些 NFO。本插件已确认不会写脏值，MoviePilot 自身的 NFO 生成也是正确的（`app/modules/themoviedb/scraper.py` 用 `company.get("name")`）；检查是否有其它刮削/整理工具在补写 NFO |
| 演职人员里多出几个叫 `{adult: False`、`'gender': 1` 的人 | 同一个 bug 的连带现象：Jellyfin 读 `<director>` 会按逗号拆分多值字段，一个坏值裂变成一堆「假导演」。同上，跑一轮 `sync` 即可清掉 |
| 日志出现「在线数据里的「xx」疑似把结构化对象直接转成了字符串」 | 这是 v1.4.1 新增的护栏在起作用：它拦下了疑似对象字面量的在线值，**保住了你已有的内容**。请把这条日志反馈上来（属于数据源 bug），不会影响其它字段 |

### 图片相关的现象

| 现象 | 原因 / 处理 |
| --- | --- |
| 图片一副都没动 | 依次确认：`image_mode` 不是 `off`；`mode` 不是 `report`；`dry_run` 没开；该条目没有 `<lockdata>true</lockdata>`；`image_kinds` 包含该类型 |
| 低清 / 放错的图没被换掉 | `image_mode` 若是 `missing` 就只补空缺，改 `sync` 才会比对替换；或该图已被 `lockdata` / `lockedfields` 锁住 |
| 首轮图片跑得很慢、流量很大 | **预期行为**：库里已有图必须先下载才能判定是否一致。把「媒体库目录」先填成子目录分批跑，或先设 `image_mode=missing` 只补空缺 |
| 四个图片类型都没勾选，图片一副没动 | 这是**刻意的**：全不勾 = 明确表示不处理图片（等同于 `image_mode=off`），不会再偷偷回退成「全部」 |
| 配置里找不到「单轮最多处理文件数」了 | v1.2.0 起已移除该配置。要分批就先把「媒体库目录」填成子目录，或临时调 `image_mode` |
| 详情页清单是空的 / 还是旧的长文本 | 清单只列**会写盘**的文件；本次没有任何改动就会是空。若是老版本遗留数据或 `last_changes.json` 写入失败，页面会自动退化为展示 `last_report.txt` |
| 剧集缩略图（单集图）没生成 | 该集必须有 NFO —— 本插件以 NFO 为扫描入口；另外它需要 TMDB API Key（宿主通道不提供剧照） |
| 徽标 logo 没生成 | 同上，TMDB 的 logo 要直连 API；且 `image_kinds` 要含 `logo` |
| 改了画质档后图片被整批重下 | **预期行为**：画质档位改变请求 URL，指纹随之失效。要么接受一次重下，要么先删掉 `image_manifest.json` 重新建立 |
| 季海报只出现在一个地方 | **v1.7.0 起只写 `<季目录>/poster.jpg`**（一季一图、各归其位），不再往剧集根目录写 `seasonNN-poster.jpg` |
| 剧集根目录残留一堆 `seasonNN-poster.jpg` | v1.7.0 起不再产生，但旧版写下的会留着。插件**只检测并提示、不擅自删除**（报告里显示「检测到 N 个旧版残留…」）。确认要清理可执行：`find <媒体库目录> -maxdepth 3 -name 'season*-poster.jpg' -delete` |
| 某季在线没有海报 | **明确标注缺失**（报告里「N 季在线没有海报，已跳过」+ 明细里一条「跳过（在线无此图）」），并且**绝不回退**用剧集海报或别的季的海报顶替 |
| 想知道某张图来自哪个 URL | 打开 `image_manifest.json`（插件数据目录内，或 CLI 的 `<root>/.nfo-backup/image_manifest.json`），按路径查 |

> 图片写入采用「先写 `.nfgpart` 再原子替换」，所以不会出现媒体服务器读到半截图片的情况。
> 如果目录里看到 `.nfgpart` 残留，说明上次写入被强制中断，直接删掉即可。

### 图片指纹清单放在哪

- **插件模式**：`<MoviePilot 数据目录>/plugins/NfoGapFill/image_manifest.json`（即插件页 `get_data_path()`）。
- **CLI 模式**：`<第一个媒体库目录>/.nfo-backup/image_manifest.json`，可用 `--image-manifest` 指定别处。

删掉它不会损坏媒体库，只是下一轮需要重新下载比对来重建指纹。

### 回滚

- 若开了 `backup`，原文件在 `<媒体库根目录>/.nfo-backup/` 下，按相对路径可原样还原。
- 紧急情况下在插件页停用插件即可停止所有定时任务。

---

## 七、与媒体服务器的配合

本插件只负责把 NFO **写对**。写完要让 Emby / Jellyfin 重新读取：

- 装 MP 的「媒体库服务器刷新」插件；或
- 在 Emby / Jellyfin 里对该条目执行「刷新元数据」（不要勾「替换所有元数据」，否则会覆盖刚写好的内容）。

> 建议让 MP（或本插件）当**唯一的 NFO 写手**，媒体服务器只读：Jellyfin 里取消勾选 `Nfo saver`，
> 避免两边互相覆盖。
