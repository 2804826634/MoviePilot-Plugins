# NfoGapFill v1.8.6 — 图标改用 raw.githubusercontent.com

## 一句话

登上你的 MP 实测后找到了真正根因：**MP 的图片代理有域名白名单，而 `cdn.jsdelivr.net` 不在里面**。改用 `raw.githubusercontent.com` 即可。

## 根因：不是网络，是白名单

上一版我把图标换成了 jsDelivr CDN（因为它在国内更好连），但你反馈还是加载不出来。进你的 MP 一层层查下来，发现机制和我原先设想的完全不同：

**前端对绝对 URL 的图标，走的是「服务端图片代理」，不是浏览器直接取：**

```js
// 前端 plugin-BeuSoDl3.js
plugin_icon?.startsWith("http")
  ? `api/v1/system/img/1?imgurl=${encodeURIComponent(plugin_icon)}&cache=true`
  : `./plugin_icon/${plugin_icon}`
```

而这个代理接口（后端 `app/api/endpoints/system.py` 的 `proxy_img`）有**域名白名单**：

```python
allowed_domains = set(settings.SECURITY_IMAGE_DOMAINS)
return await fetch_image(url=imgurl, ..., allowed_domains=allowed_domains)
```

读你 MP 里的 `SECURITY_IMAGE_DOMAINS`，得到：

| 域名 | 是否在白名单 |
|---|---|
| `raw.githubusercontent.com` | ✅ |
| `github.com` | ✅ |
| image.tmdb.org / doubanio.com / lain.bgm.tv / thetvdb.com … | ✅ |
| **`cdn.jsdelivr.net`** | **❌ 不在 → 代理直接拒绝抓取** |

## 对照证据（从你 MP 里统计的）

你 MP 已安装 **35 个插件**，图标来源分布：

| 图标形式 | 数量 | 结果 |
|---|---|---|
| `raw.githubusercontent.com` | **17** | ✅ 允许 |
| `github.com` | 1 | ✅ 允许 |
| 裸文件名（MP 自带插件，由 `/plugin_icon/{name}` 提供） | 16 | ✅ |
| **`cdn.jsdelivr.net`（本插件）** | **1** | **❌ 被拒** |

也就是说 —— **你的 MP 里只有这一个插件的图标被白名单挡住了**。改成和另外 17 个一样的 `raw.githubusercontent.com` 即可。

顺带澄清两个我上一版没查清的点：

- **裸文件名这条路对我们不可用**：前端的 `./plugin_icon/{name}` 只服务 MP **自带**插件。实测 `AutoSignIn/signin.png`、`TorrentTransfer/seed.png` 都能取到（200），而我们的 `nfogapfill.png` 是 404。我们是从市场安装的插件，走不了这条路。
- **MP 是能对外联网的**：那 440 个市场插件的数据就是它拉到的（走你配的 `PROXY_HOST = socks5h://…192.168.31.118:7893`）。所以问题不在网络，在白名单。

## 改动

```python
PLUGIN_ICON = ("https://raw.githubusercontent.com/2804826634/MoviePilot-Plugins/"
               "main/icons/nfogapfill.png")
```

- `package.v2.json` 的 `icon` 同步改成同一个地址（两处必须一致）
- 注释里把三条约束都写清楚了：**类属性是唯一来源 / 不能写裸文件名 / 域名必须在白名单内**，并注明"别改回去"
- 新增 3 条回归断言锁死：**域名必须在白名单内**、**不得再出现 jsdelivr**、**与 package.v2.json 同源**

## 验证

- **离线回归 355 项全绿**（插件面 288 + 引擎面 67）
- 从你的 MP 读取 `SECURITY_IMAGE_DOMAINS` 实测比对（上表）
- 统计你 MP 全部 35 个已安装插件的图标域名（上表）

## 升级注意

- 配置无需改动
- **`SECURITY_IMAGE_DOMAINS` 是你自己在 MP 里配的安全项**。如果你把它改窄（比如去掉 `raw.githubusercontent.com`），图标仍会不显示 —— 那时请在
  **设定 → 安全 → 图片域名白名单**里加上图标所在域名。
- 另一个可选的稳妥做法：直接在白名单里加上 `cdn.jsdelivr.net`（或任何你想用的图床），
  这样就不受插件里写死哪个域名的限制了。
