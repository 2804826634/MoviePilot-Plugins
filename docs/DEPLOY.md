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

1. 安装后在插件配置里只填 **媒体库目录**，`mode` 选 **只报告差异**，打开 **演练模式**，保存并「保存后立即运行一次」。
2. 打开插件详情页看报告，确认：
   - 扫描到的 NFO 数量对得上；
   - 「不一致」清单里确实是**你认为该改**的字段（如果里面有你的手工润色，把它加进「保护字段」）。
3. 切 `mode = 不一致则替换`，关掉演练模式，先设 `max_files = 50` 跑一轮。
4. 确认无误后把 `max_files` 设为 `0`（不限），设置 `cron` 周期任务。

---

## 六、排错清单

| 现象 | 原因 / 处理 |
| --- | --- |
| 市场里看不到插件 | `PLUGIN_MARKET` 没生效（改完要重启容器）；仓库不是 public；容器访问不了 raw.githubusercontent.com，配 `PROXY_HOST` 或 `GITHUB_TOKEN` |
| 图标是破图 | 属于正常降级，不影响功能；确认 `package.v2.json` 里 `icon` 的 URL 可访问 |
| 扫描到 0 个 NFO | `paths` 填的是容器内路径（如 `/media/link/电影`），不是宿主机路径；确认该目录在容器里存在 |
| 开了 `notify` 但没收到通知 | 检查 MP 的「通知设置」是否配置了通知渠道 |
| 报告一直空 | 数据源没拿到数据：`tmdb_api_key` 无效 / 被墙；或 `HostProvider` 在该 MP 版本上字段映射不兼容 → 填 TMDB Key 走直连 |
| 写入报权限错误 | `PUID/PGID/UMASK` 要对媒体目录有写权限；硬链接做种库尤其注意 |
| 点了运行但没变化 | `mode` 是否为 `report`？`dry_run` 是否开着？字段是否命中 `protect_fields` 或 NFO 内 `lockedfields`？ |
| 报错 `429 Too Many Requests` | TMDB 限速，调小批次并错峰运行；内置限速为 4 req/s |
| 中文标点被改成半角 | 属于历史 bug，已在 v1.0.0 修复：比对走 NFKC 归一化，写入始终用原值 |

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
