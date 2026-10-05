#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NfoGapFill —— NFO 与图片元数据「差异比对 → 按需替换」工具（MoviePilot 插件 / 独立 CLI 双模式）

它解决什么问题
    MoviePilot 官方「媒体库刮削」插件对「已有文件」只有两档处理：
        · 不覆盖已有元数据   —— 只要字段非空 / 图片文件存在就一律不动，不管它是错的还是旧的
        · 覆盖所有元数据和图片 —— 连你手工润色的简介、自定义 tag、精挑的封面一起冲掉
    它的判定依据只有「文件在不在」（app/chain/media.py 的 _should_scrape），
    所以一张低清封面、错语言的 logo 会永远留在库里。
    本插件补上中间那一档，并且是默认行为：
        · 缺失            → 补齐
        · 与在线数据不一致 → 替换
        · 与在线数据一致   → 跳过（不产生任何写入，不改动文件 mtime）
    NFO 字段与图片共用这套判定；图片另外靠「指纹清单」在稳态下零下载地判定一致。
    三层保护：NFO 内 lockdata/lockedfields、插件配置的「保护字段」、只报告模式。

────────────────────────────────────────────────────────────────────────
一、作为 MoviePilot 插件部署（推荐：从插件市场装）

    docker-compose.yml 里把本仓库追加到插件市场（不要覆盖官方市场）：
        environment:
          - PLUGIN_MARKET=jxxghp/MoviePilot-Plugins,2804826634/moviepilot-nfo-gapfill
    重启容器后，插件市场搜「NFO」即可安装。

  也可以单文件手动放入（升级镜像会丢，需重做）：
        docker cp plugins.v2/nfogapfill/__init__.py moviepilot-v2:/config/NfoGapFill.py
        docker exec -it moviepilot-v2 python -c "import app.plugins,os;print(os.path.dirname(app.plugins.__file__))"
        docker exec -it moviepilot-v2 mv /config/NfoGapFill.py <上一步输出的目录>/
        docker restart moviepilot-v2
      注意文件名必须是插件 ID（类名）NfoGapFill.py。

────────────────────────────────────────────────────────────────────────
二、作为独立命令行工具（先在电脑上验证策略，再上 NAS）

    # 体检：只报告差异，不写盘
    python NfoGapFill.py --root /media/link --source tmdb --api-key XXX

    # 离线演练：用本地 JSON 模拟在线数据，不联网也能验证比对逻辑
    python NfoGapFill.py --root /media/link --source file --cache remote.json

    # 正式执行（先加 --dry-run 看一遍，再去掉）
    python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --mode sync --fix

    # 连图片一起处理（CLI 里图片默认关闭，插件里默认开启）
    python NfoGapFill.py --root /media/link --source tmdb --api-key XXX \
                         --mode sync --fix --image-mode sync

   CLI 与插件调用的是完全同一套引擎，CLI 上验证通过的行为就是插件的实际行为。

────────────────────────────────────────────────────────────────────────
三、四种运行模式（NFO 字段与图片共用）
    report   只报告差异，一个字节都不写
    gapfill  只补缺失（等价官方插件的「不覆盖已有元数据」）
    sync     缺失补齐 + 不一致替换 + 一致跳过   ← 默认，本插件的存在意义
    force    无条件用在线数据覆盖全部受管字段（等价官方插件的 force_all）

────────────────────────────────────────────────────────────────────────
四、图片处理（独立开关，与上面四种模式正交）
    image_mode = off      完全不处理图片（CLI 默认）
    image_mode = missing  只补缺失图片，不动已有图
    image_mode = sync     缺失补齐 + 不一致替换 + 一致跳过（插件默认）
    支持的图片类型（共 8 类，另含随「海报」一起处理的季海报）：
        海报 poster        电影、剧集目录 poster.jpg                ← TMDB
        背景图 backdrop    电影、剧集目录 backdrop.jpg + fanart.jpg  ← TMDB
        徽标 logo          电影、剧集目录 logo.png                  ← TMDB
        剧集缩略图 thumb   单集剧照，写成与该集视频同名的 .jpg        ← TMDB
        横幅图 banner      电影、剧集、季目录 banner.jpg             ← fanart.tv
        光盘图 disc        电影、剧集目录 disc.png                  ← fanart.tv
        透明艺术图 clearart 电影、剧集目录 clearart.png             ← fanart.tv
        横版缩略图 landscape 电影、剧集、季目录 landscape.jpg        ← fanart.tv
        季海报             跟随「海报」：**只写季目录 poster.jpg**（一季一图、各归其位）
                           不回退：该季在线没有海报就跳过并在报告里明确标注，
                           绝不用剧集海报或别的季的海报顶替
    fanart.tv 的 API Key 自动沿用 MoviePilot 的 FANART_API_KEY（MP 自带默认值），
    语言偏好跟随 MP 的 FANART_LANG（默认 zh,en）。键名映射与 MP 的 FanartModule 一致。
    一致的判定靠 image_manifest.json 指纹清单：记录「这张图来自哪个 URL、内容 sha256」，
    因此稳态下零下载即可判定「相同」。首次运行需要下载比对以建立指纹（有流量开销）。
    characterart（人物图）仍不支持 —— fanart.tv 有但 MP 的画集清单里没有它，需要时再说。

────────────────────────────────────────────────────────────────────────
五、与 MoviePilot 的配置联动（全部自动继承，不用手填）
    TMDB API Key 自动读取 MoviePilot 里配置的 TMDB_API_KEY；
    网络代理     自动读取 MoviePilot 里配置的 PROXY_HOST —— 插件里已不再提供代理输入框。
    两者都拿不到时才退回宿主刮削通道（该通道只有海报与背景图）。

    分级地区码 决定 NFO 里 <mpaa> 取哪个国家/地区的分级：
        US → PG-13 / R　　GB → 12 / 15 / 18　　JP → G / PG12 / R15+
        中国大陆没有官方影视分级体系，填 CN 通常取不到值；
        若所选地区恰好缺该片分级，会自动退回到任意有值的地区，不会留空。

    演员写入上限 可选 10 / 20 / 30 / 50 / 全部（全部 = 0，不限制）。

    保护字段（protect_fields）：照常参与比对、缺失也会补，但永不覆盖已有内容。
    （早期版本还有一个「字段白名单」用来收窄处理范围，按用户反馈已移除；
     该能力仍保留在引擎与 CLI 的 --only 里。）

    详情页展示的是「本次修改了哪些文件」表格（含演练/只报告模式下的待改动清单）；
    完整文本报告（含每一条跳过的原因）写在插件数据目录的 last_report.txt。

────────────────────────────────────────────────────────────────────────
六、媒体库目录可限定类型（每行一个目录，行尾加 #类型）
    /media/link/电影#电影      → 该目录只处理电影
    /media/link/剧集#电视剧    → 该目录只处理剧集（含季、单集）
    /media/link/纪录片         → 不加后缀则两种类型都处理
    后缀别名：movie / movies / 影片、tv / tvshow / series / 剧集。
    写法与官方「媒体库刮削」的 scraper_paths 一致，老配置可直接搬。
    路径本身含 # 时不受影响（认不出的后缀会当路径的一部分保留）。
    被跳过的数量会在报告的「按目录的『#类型』限定跳过 N 个 NFO」里体现。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Dict, List, Optional, Tuple

# ── MoviePilot 宿主环境探测：在 MP 里走宿主基类，在命令行里降级为普通类 ──
IN_MOVIEPILOT = False
_PluginBase: Any = object
CronTrigger: Any = None

try:
    from app.plugins import _PluginBase  # type: ignore # MP V2 入口（V3 兼容加载）

    IN_MOVIEPILOT = True
except Exception:
    try:
        from app.sdk.plugin import _PluginBase  # type: ignore # V3 原生入口

        IN_MOVIEPILOT = True
    except Exception:
        _PluginBase = object

try:
    from app.log import logger  # type: ignore
except Exception:
    class _CliLogger:
        """命令行模式下的极简日志，接口与宿主 logger 对齐。"""

        @staticmethod
        def _emit(level: str, msg: str) -> None:
            print(f"{datetime.now():%H:%M:%S} {level:<5} {msg}", flush=True)

        def info(self, msg: str) -> None:
            self._emit("INFO", msg)

        def warning(self, msg: str) -> None:
            self._emit("WARN", msg)

        def error(self, msg: str) -> None:
            self._emit("ERROR", msg)

        def debug(self, msg: str) -> None:
            pass

    logger = _CliLogger()

try:
    from apscheduler.triggers.cron import CronTrigger  # type: ignore
except Exception:
    CronTrigger = None


PLUGIN_VERSION = "1.7.0"
TIMEOUT = 25
WEEKLY_CRON = "0 3 * * 0"   # 「执行周期」留空时的默认值：每周日 03:00 跑一次
RATE_GAP = 0.25          # TMDB 限速基准：单线程下最快 4 请求/秒
RATE_GAP_MIN = 0.08      # 并发时的最快间隔（≈12 请求/秒，仍远低于 TMDB 的 50/秒）
TMDB_RETRIES = 3         # 网络类失败的重试次数（国内直连 TMDB 常 SSL 握手超时）
TMDB_RETRY_WAIT = 0.8    # 重试退避基数（秒），第 n 次等 n 倍
NUMBER_TOL = 0.05        # 评分/时长的数值容差，避免 8.4 与 8.40 被判为差异


class RateLimiter:
    """线程安全的全局限速器。

    多线程后不能再用「记一个 _last 时间戳」那套 —— 那样每个线程各自放行，
    实际速率会变成 N 倍。这里用「下一个可放行时刻」一次性推进，保证全局速率恒定。
    """

    def __init__(self, gap: float):
        self.gap = max(0.0, float(gap))
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.gap
        if delay > 0:
            time.sleep(delay)


def tmdb_gap(concurrency: int) -> float:
    """并发下的 TMDB 请求间隔。

    单线程（1）保持原来的 4 请求/秒不变；并发时按并发数等比放宽，
    但下限 RATE_GAP_MIN（≈12/秒），避免把 TMDB 打到限流。
    """
    workers = max(1, int(concurrency or 1))
    return max(RATE_GAP_MIN, RATE_GAP / workers)
# 图片地址前缀由 image_host() 动态给出（跟随宿主的 TMDB_IMAGE_DOMAIN 设置）

# 画质档位 → 各图片类型请求的 TMDB 尺寸。
# 必须按类型分别取：TMDB 不同图片类型支持的尺寸集合不一样（logo 最大只到 w500，
# 拿 backdrop 的 w1280 去请求 logo 会取不到图）。
IMG_SIZES: Dict[str, Dict[str, str]] = {
    "standard": {"poster": "w780", "backdrop": "w1280", "logo": "w500", "thumb": "w300"},
    "original": {"poster": "original", "backdrop": "original",
                 "logo": "original", "thumb": "original"},
}

# TMDB /images 接口响应里的数组名
IMG_API_KEYS: Dict[str, str] = {"poster": "posters", "backdrop": "backdrops",
                                "logo": "logos", "thumb": "stills"}

IMAGE_KINDS: Tuple[str, ...] = ("poster", "backdrop", "logo", "thumb",
                                "banner", "disc", "clearart", "landscape")
IMAGE_KIND_CN = {
    "poster": "海报", "backdrop": "背景图", "logo": "徽标", "thumb": "剧集缩略图",
    "banner": "横幅图", "disc": "光盘图", "clearart": "透明艺术图", "landscape": "横版缩略图",
}

IMG_OFF, IMG_MISSING, IMG_SYNC = "off", "missing", "sync"

UA = f"NfoGapFill/{PLUGIN_VERSION} (+MoviePilot plugin)"


def mp_setting(name: str, default: Any = None) -> Any:
    """读取 MoviePilot 宿主的配置项（如 TMDB_API_KEY / PROXY_HOST / TMDB_LOCALE）。

    宿主用的是 pydantic-settings 单例，用户在 UI 里改过之后是实时生效的，
    所以每次构建数据源时读一次即可拿到最新值。取不到（命令行环境、字段不存在、
    值为空串）时返回 default，绝不抛异常。
    """
    try:
        from app.core.config import settings  # type: ignore
    except Exception:
        return default
    value = getattr(settings, name, None)
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


# ══════════════════════════════════════════════════════════════════════
# 媒体库目录的「#类型」后缀
#   /media/link/电影#电影    → 这个目录只处理电影
#   /media/link/剧集#电视剧  → 这个目录只处理剧集（含季、单集）
#   不加后缀                 → 两种类型都处理
# 与官方「媒体库刮削」的 scraper_paths 写法保持一致，方便老用户迁移配置。
# ══════════════════════════════════════════════════════════════════════
TYPE_TAGS: Dict[str, str] = {
    "电影": "movie", "影片": "movie", "movie": "movie", "movies": "movie",
    "电视剧": "tv", "剧集": "tv", "电视": "tv", "tv": "tv",
    "tvshow": "tv", "series": "tv", "show": "tv",
}
TYPE_TAG_CN = {"movie": "电影", "tv": "电视剧"}


def normalize_type_tag(tag: str) -> Optional[str]:
    """把 `#电影` / `#电视剧` / `#movie` / `#tv` 这类后缀归一成 movie / tv。"""
    key = norm_text(tag).casefold().replace(" ", "")
    return TYPE_TAGS.get(key)


def parse_root_specs(specs: List[str], resolve: bool = False) -> Tuple[List[Path], Dict[str, str]]:
    """解析「路径[#类型]」形式的媒体库目录，返回 (目录列表, {目录: 强制类型})。

    识别不出类型时（例如路径里本来就带 #），`#...` 会当成路径的一部分保留，
    不会把用户真实的目录名吃掉。
    """
    roots: List[Path] = []
    types: Dict[str, str] = {}
    for spec in specs:
        text = str(spec or "").strip()
        if not text:
            continue
        forced: Optional[str] = None
        if "#" in text:
            head, _, tail = text.rpartition("#")
            tag = normalize_type_tag(tail)
            if tag and head.strip():
                forced, text = tag, head.strip()
        path = Path(text)
        if resolve:
            path = path.expanduser().resolve()
        roots.append(path)
        if forced:
            types[str(path)] = forced
    return roots, types


def type_allowed(forced: Optional[str], media_type: str) -> bool:
    """目录被限定为单一类型时，判断某个 NFO 是否该被处理。

    限电影 → 只收 movie；限电视剧 → 收 tvshow / season / episodedetails。
    """
    if forced == "movie":
        return media_type == "movie"
    if forced == "tv":
        return media_type in ("tvshow", "season", "episodedetails")
    return True


def image_host() -> str:
    """TMDB 图片地址前缀，跟随 MoviePilot 的 TMDB_IMAGE_DOMAIN。

    国内直连 image.tmdb.org 经常超时/被拦，MP 本身允许把域名换成镜像或反代
    （设置项 TMDB_IMAGE_DOMAIN）。插件这里跟着走，用户就不用再填一遍。

    两种写法都要兼容：只给域名（`image.tmdb.org`）→ 补上 `/t/p/`；
    已经带了路径（`mirror.example.com/t/p`）→ 不重复拼。
    """
    domain = str(mp_setting("TMDB_IMAGE_DOMAIN", "") or "").strip() or "image.tmdb.org"
    domain = re.sub(r"^https?://", "", domain).strip("/")
    if "/t/p" in domain:
        return f"https://{domain.rstrip('/')}/"
    return f"https://{domain}/t/p/"


def download_bytes(url: str, opener: Any = None, attempts: int = 3) -> Optional[bytes]:
    """下载二进制内容，失败自动重试。

    image.tmdb.org 在部分地区经常抽风，一次失败就把错误写到面板上会制造大量「假失败」。
    这里做多次尝试 + 递增退避，只有全部失败才返回 None 并记录一条告警。
    """
    last_error = "响应为空"
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            if opener is not None:
                with opener.open(request, timeout=TIMEOUT) as response:
                    data = response.read()
            else:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    data = response.read()
            if data:
                return data
        except Exception as exc:
            last_error = str(exc)
        if attempt < attempts:
            time.sleep(0.6 * attempt)
    logger.warning(f"图片下载失败（已重试 {attempts} 次）：{url}（{last_error}）")
    return None


# ══════════════════════════════════════════════════════════════════════
# fanart.tv：光盘图 / 横幅图 / 透明艺术图 / 横版缩略图只有这里有
# 映射关系照抄 MoviePilot 的 FanartModule._FANART_NAME_MAP，命名保持一致。
# ══════════════════════════════════════════════════════════════════════
FANART_KEYS: Dict[str, Tuple[str, ...]] = {
    "banner": ("moviebanner", "tvbanner"),
    "disc": ("moviedisc",),
    "clearart": ("hdmovieclearart", "movieart", "hdclearart"),
    "landscape": ("moviethumb", "tvthumb"),
}


def fanart_api_key() -> str:
    """fanart.tv 的 API Key，自动沿用 MoviePilot 的 FANART_API_KEY（MP 自带默认值）。"""
    return str(mp_setting("FANART_API_KEY", "") or "").strip()


def fanart_lang_order() -> List[str]:
    """语言偏好，跟随 MoviePilot 的 FANART_LANG（默认 zh,en）。"""
    raw = str(mp_setting("FANART_LANG", "") or "").strip() or "zh,en"
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def pick_fanart_image(entries: List[dict]) -> Optional[str]:
    """从 fanart.tv 的图片数组里挑一张：先按语言偏好（FANART_LANG），再按社区点赞数。"""
    valid = [item for item in entries or [] if item.get("url")]
    if not valid:
        return None
    order = fanart_lang_order()

    def rank(item: dict) -> Tuple[int, int]:
        lang = str(item.get("lang") or "").lower()
        try:
            likes = int(item.get("likes") or 0)
        except (TypeError, ValueError):
            likes = 0
        try:
            pos = order.index(lang)
        except ValueError:
            pos = len(order)
        return (pos, -likes)

    return min(valid, key=rank)["url"]


def fanart_image_urls(kinds: set, tmdb_id: str, tvdb_id: str,
                      api_key: str) -> Dict[str, str]:
    """从 fanart.tv 取 TMDB 拿不到的那几类图，返回 {图片类型: 地址}。

    电影按 tmdbid 查，剧集按 thetvdb id 查（fanart.tv 的剧集接口只认 tvdb id）。
    没有 Key、查不到、或这几类一个都不需要时返回空 dict，调用方自行兜底。
    """
    wanted = {kind for kind in kinds or () if kind in FANART_KEYS}
    if not wanted or not api_key:
        return {}
    if any(kind in FANART_KEYS for kind in wanted) and not (tmdb_id or tvdb_id):
        return {}
    # 剧集接口按 thetvdb id 查；电影按 tmdbid 查
    tv_mode = bool(tvdb_id) or not tmdb_id
    query = tvdb_id or tmdb_id
    segment = "tv" if tv_mode else "movies"
    url = f"https://webservice.fanart.tv/v3/{segment}/{query}?api_key={api_key}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception as exc:
        logger.warning(f"fanart.tv 查询失败（{segment}/{query}）：{exc}")
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    for kind in sorted(wanted):
        for key in FANART_KEYS[kind]:
            best = pick_fanart_image(data.get(key) or [])
            if best:
                out[kind] = best
                break
    return out


# ══════════════════════════════════════════════════════════════════════
# 字段规格与归一化
# ══════════════════════════════════════════════════════════════════════
FIELD_KINDS: Dict[str, str] = {
    # 文本
    "title": "text", "originaltitle": "text", "sorttitle": "text", "tagline": "text",
    "plot": "text", "outline": "text", "mpaa": "text", "status": "text", "set": "text",
    # 数值
    "year": "number", "runtime": "number", "rating": "number",
    "season": "number", "episode": "number", "votes": "number",
    # 日期
    "premiered": "date", "aired": "date", "release": "date", "enddate": "date",
    # 多值集合（顺序无关）
    "genre": "list", "country": "list", "director": "list", "credits": "list",
    "studio": "list", "tag": "list",
    # 结构化
    "actor": "actor",
}

# 每种 NFO 参与比对的字段（顺序即写入顺序）
MANAGED_FIELDS: Dict[str, List[str]] = {
    "movie": ["title", "originaltitle", "plot", "tagline", "year", "premiered", "runtime",
              "mpaa", "rating", "genre", "studio", "country", "director", "credits", "actor"],
    "tvshow": ["title", "plot", "tagline", "year", "premiered", "runtime", "mpaa", "rating",
               "genre", "studio", "country", "actor"],
    "episodedetails": ["title", "plot", "aired", "rating", "season", "episode",
                       "director", "credits", "actor"],
    "season": ["title", "plot", "premiered", "season"],
}

TAG2TYPE = {"movie": "movie", "tvshow": "tvshow",
            "episodedetails": "episodedetails", "season": "season"}

ACTOR_SEP = "|"          # 本地 actor 值的内部编码：name|role|thumb


def norm_text(value: Any) -> str:
    """仅供比较使用：NFKC（全角→半角）、反转义、压缩空白、去首尾。

    注意：绝不能用它来处理准备写回文件的内容 —— NFKC 会把中文全角标点改成半角，
    那是肉眼可见的破坏。写入路径一律使用 as_str_list 的原值。
    """
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = html.unescape(s)
    s = s.replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()


def to_number(value: Any) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", norm_text(value).replace(",", ""))
    return float(m.group()) if m else None


def norm_date(value: Any) -> str:
    s = norm_text(value)
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{4})$", s)
    return m.group(1) if m else s


def as_str_list(value: Any) -> List[str]:
    """把字段值规整成字符串列表，保留原样（只去首尾空白），供写入使用。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


# 兼容早期命名
to_str_list = as_str_list


# ── 宿主返回的结构化值 → 可直接写进 NFO 的文本 ──────────────────────
# 血泪教训：MoviePilot 的 MediaInfo 里 genres / production_companies / networks 都是
# List[dict]，directors / actors 是 List[MediaPerson]。若直接 str() 化，
# "{'id': 12, 'name': '冒险'}" 这种 Python 字面量就会被原样写进 NFO ——
# 媒体服务器会照原样显示成乱码，Jellyfin 还会把 <director> 按逗号拆成一堆假条目。
# 所以取值必须逐层剥到「名字」为止。
_NAME_KEYS = ("name", "title", "original_name", "character")
_CODE_KEYS = ("iso_3166_1", "english_name", "iso_639_1")
_IMAGE_KEYS = ("original", "medium", "thumb", "url", "image", "w500")


def item_text(value: Any) -> str:
    """从一个元素里取出可直接写入的文本：字符串原样、dict / 对象取 name 等。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in _NAME_KEYS + _CODE_KEYS:
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    for attr in _NAME_KEYS:
        text = str(getattr(value, attr, "") or "").strip()
        if text:
            return text
    return ""


def text_list(value: Any) -> List[str]:
    """把标量 / 字符串列表 / 字典列表 / 对象列表，统一变成文本列表。

    这是 HostProvider 的关键防线：宿主给的是结构化对象，必须剥成名字再写。
    """
    if value is None or value == "" or value == [] or value == {}:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return [text for text in (item_text(item) for item in items) if text]


def person_fields(person: Any) -> Tuple[str, str, str]:
    """从演员条目里取 (姓名, 角色, 头像)。

    兼容 MoviePilot 的 MediaPerson（角色字段叫 character、头像在 profile_path /
    images / avatar）与普通 dict；头像本身是 dict 时再往里找一层 url。
    """
    def pick(*names: str) -> str:
        for name in names:
            value = person.get(name) if isinstance(person, dict) else getattr(person, name, None)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, dict):
                for key in _IMAGE_KEYS:
                    nested = str(value.get(key) or "").strip()
                    if nested:
                        return nested
                continue
            return str(value).strip()
        return ""

    return (pick("name"),
            pick("character", "role"),
            pick("profile_path", "image", "thumb", "avatar"))


def looks_like_object_repr(text: str) -> bool:
    """判断一个值是不是「Python 对象字面量被 str() 出来」的产物。

    真实元数据几乎不可能长成这样。一旦命中，说明数据源把结构化对象当字符串吐了出来；
    这种内容写进 NFO 会让媒体服务器显示成乱码，所以宁可跳过并告警，也不写进去。
    """
    stripped = str(text or "").strip()
    if not stripped.startswith(("{", "[")):
        return False
    return ("': " in stripped or "\": " in stripped) and "{" in stripped


# 同义标签：同一个概念在 NFO 里可能落在不同标签下（例如出品方既可能是 <studio>
# 也可能是 <network>），媒体服务器往往把两者都算作同一栏。
# 替换某个字段时顺手清掉这些标签里的历史脏值 —— 但**只删脏值**，正常值一律不动，
# 也不把它们纳入比对（否则两边永远对不上，会陷入反复重写）。
SYNONYM_TAGS: Dict[str, Tuple[str, ...]] = {
    "studio": ("network",),
}


def purge_junk_elements(root: ET.Element, tags: Tuple[str, ...]) -> int:
    """删掉这些标签里「像对象字面量」的脏节点，返回删除数量。只删脏值，正常值不动。"""
    removed = 0
    for tag in tags:
        for el in list(root.findall(tag)):
            if looks_like_object_repr(el.text or ""):
                root.remove(el)
                removed += 1
    return removed


def count_junk_elements(root: ET.Element, tags: Tuple[str, ...]) -> int:
    """数一下这些标签里有多少「像对象字面量」的脏节点（不修改文档）。"""
    return sum(1 for tag in tags for el in root.findall(tag)
               if looks_like_object_repr(el.text or ""))


# ══════════════════════════════════════════════════════════════════════
# 差异比对
# ══════════════════════════════════════════════════════════════════════
SAME, DIFF, LOCAL_ONLY, REMOTE_ONLY = "相同", "不一致", "仅本地有", "仅在线有"

FILL = "补齐"      # 本地空、在线有  → 写
REPLACE = "替换"   # 两边都有但不同  → 写
SKIP = "跳过"      # 相同 / 本地独有 / 在线空


def compare(kind: str, local_vals: List[str], remote_vals: List[str]) -> Tuple[str, str]:
    """返回 (判定结果, 是否建议写入)。判定结果用于报告，写入与否还受模式和保护字段约束。"""
    L = [v for v in local_vals if norm_text(v)]
    R = [v for v in remote_vals if norm_text(v)]

    if not L and not R:
        return SAME, SKIP
    if not L:
        return REMOTE_ONLY, FILL
    if not R:
        return LOCAL_ONLY, SKIP

    if kind == "number":
        a, b = to_number(L[0]), to_number(R[0])
        if a is not None and b is not None:
            return (SAME, SKIP) if abs(a - b) <= NUMBER_TOL else (DIFF, REPLACE)
        return (SAME, SKIP) if norm_text(L[0]) == norm_text(R[0]) else (DIFF, REPLACE)

    if kind == "date":
        return (SAME, SKIP) if norm_date(L[0]) == norm_date(R[0]) else (DIFF, REPLACE)

    if kind == "list":
        ls = {norm_text(x).casefold() for x in L}
        rs = {norm_text(x).casefold() for x in R}
        return (SAME, SKIP) if ls == rs else (DIFF, REPLACE)

    if kind == "actor":
        # 只按演员姓名集合比较：role / 头像变化不足以触发整段重写
        ls = {norm_text(x.split(ACTOR_SEP)[0]).casefold() for x in L}
        rs = {norm_text(x.split(ACTOR_SEP)[0]).casefold() for x in R}
        return (SAME, SKIP) if ls == rs else (DIFF, REPLACE)

    return (SAME, SKIP) if norm_text(L[0]) == norm_text(R[0]) else (DIFF, REPLACE)


# ══════════════════════════════════════════════════════════════════════
# NFO 读写
# ══════════════════════════════════════════════════════════════════════
@dataclass
class NfoFile:
    path: Path
    media_type: str
    tree: ET.ElementTree

    @property
    def root(self) -> ET.Element:
        return self.tree.getroot()


def load_nfo(path: Path) -> Optional[NfoFile]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        logger.warning(f"NFO 解析失败，已跳过：{path}（{exc}）")
        return None
    mtype = TAG2TYPE.get(tree.getroot().tag)
    if not mtype:
        return None
    return NfoFile(path=path, media_type=mtype, tree=tree)


def read_local_values(nfo: NfoFile, name: str) -> List[str]:
    """读 NFO 里某字段的现值。返回原值（仅去首尾空白），空节点被过滤。"""
    root = nfo.root
    if name == "actor":
        out = []
        for el in root.findall("actor"):
            actor_name = (el.findtext("name") or "").strip()
            if not actor_name:
                continue
            out.append(ACTOR_SEP.join([actor_name,
                                       (el.findtext("role") or "").strip(),
                                       (el.findtext("thumb") or "").strip()]))
        return out
    out = []
    for el in root.findall(name):
        text = (el.text or "").strip()
        if text:
            out.append(text)
    return out


def get_locked_fields(root: ET.Element) -> Optional[bool]:
    """读取 Kodi 语义的字段锁。返回 None 表示未使用锁机制；True 表示 lockdata 全锁。"""
    lockdata = norm_text(root.findtext("lockdata")).lower()
    if lockdata in ("true", "yes", "1"):
        return True
    # <lockedfields>title|plot</lockedfields> 或逐个 <lockedfield>title</lockedfield>
    raw = [norm_text(root.findtext("lockedfields"))]
    raw += [norm_text(el.text) for el in root.findall("lockedfield")]
    fields = {f.strip().casefold() for chunk in raw if chunk for f in re.split(r"[|,;]", chunk)}
    fields.discard("")
    return fields if fields else None


def write_local_values(nfo: NfoFile, name: str, new_values: List[str], replace: bool) -> int:
    """写回字段。replace=True 时先清空该字段的全部旧节点再重建（保持元素顺序可接受）。

    返回「顺带清掉的历史脏值节点数」——替换时会把同义标签里的对象字面量垃圾一并扫掉。
    """
    root = nfo.root
    if name == "actor":
        if replace:
            for el in list(root.findall("actor")):
                root.remove(el)
        else:
            # 顺手清掉「只有空 name」的 actor 节点：它不含任何信息，却会在媒体服务器里
            # 显示成一个空白人物（历史版本把结构化对象当字符串处理时写出过这种垃圾节点）
            for el in list(root.findall("actor")):
                if not norm_text(el.findtext("name")):
                    root.remove(el)
            existing = {norm_text(el.findtext("name")).casefold() for el in root.findall("actor")}
            new_values = [v for v in new_values
                          if norm_text(v.split(ACTOR_SEP)[0]).casefold() not in existing]
        for item in new_values:
            parts = item.split(ACTOR_SEP)
            el = ET.SubElement(root, "actor")
            ET.SubElement(el, "name").text = parts[0]
            if len(parts) > 1 and parts[1]:
                ET.SubElement(el, "role").text = parts[1]
            if len(parts) > 2 and parts[2]:
                ET.SubElement(el, "thumb").text = parts[2]
        return 0

    if replace:
        for el in list(root.findall(name)):
            root.remove(el)
        for value in new_values:
            ET.SubElement(root, name).text = value
        # 同义标签（例如 studio 与 network）里的历史脏值也一并清掉，正常值不动
        return purge_junk_elements(root, SYNONYM_TAGS.get(name, ()))

    # 补齐模式：优先填已存在的空节点，多余的新值再追加，避免产生重复标签
    empties = [el for el in root.findall(name) if not norm_text(el.text)]
    for el in empties:
        if not new_values:
            break
        el.text = new_values.pop(0)
    for value in new_values:
        ET.SubElement(root, name).text = value
    return 0


def write_nfo_file(nfo: NfoFile, backup_root: Optional[Path], root_dir: Path) -> None:
    if backup_root:
        try:
            dst = backup_root / nfo.path.relative_to(root_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():          # 首次备份为准，反复运行不会覆盖最初版本
                shutil.copy2(nfo.path, dst)
        except Exception as exc:
            logger.warning(f"备份失败（继续写入）：{nfo.path}（{exc}）")
    try:
        ET.indent(nfo.tree, space="  ")
    except AttributeError:
        pass
    body = ET.tostring(nfo.root, encoding="unicode")
    nfo.path.write_text('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        + body + "\n", encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# 图片规格与落盘
#   命名遵循 MP / Kodi / Jellyfin 共同认可的约定（对照 MP 的
#   app/chain/media.py 里 IMAGE_ALIASES 与季目录 naming 规则），列在这里以免写错：
#     · 电影 / 剧集目录：poster.jpg、backdrop.jpg（+ fanart.jpg 别名）、logo.png
#     · 季目录：poster.jpg（只此一处；不再往剧集根目录写 seasonNN-poster.jpg）
#     · 单集：<视频文件名>.jpg，与 MP 的写法一致，放在视频同级目录
#   注意：TMDB 只提供 poster / backdrop / logo / still 四类；
#   banner、clearart、discart、landscape 需要 fanart.tv，不在本插件范围内。
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ImageSpec:
    kind: str                 # poster / backdrop / logo / thumb
    name: str                 # 目标文件名模板，可用 {stem} / {season}
    alias: bool = False       # 与同 kind 的主图内容相同，只是多写一份别名文件
    in_parent: bool = False   # 落到上级目录（当前没有图片类型使用，保留能力备用）


IMAGE_SPECS: Dict[str, List[ImageSpec]] = {
    "movie": [
        ImageSpec("poster", "poster.jpg"),
        ImageSpec("backdrop", "backdrop.jpg"),
        ImageSpec("backdrop", "fanart.jpg", alias=True),        # Kodi / Emby 认 fanart
        ImageSpec("logo", "logo.png"),
        ImageSpec("banner", "banner.jpg"),
        ImageSpec("disc", "disc.png"),
        ImageSpec("clearart", "clearart.png"),
        ImageSpec("landscape", "landscape.jpg"),
    ],
    "tvshow": [
        ImageSpec("poster", "poster.jpg"),
        ImageSpec("backdrop", "backdrop.jpg"),
        ImageSpec("backdrop", "fanart.jpg", alias=True),
        ImageSpec("logo", "logo.png"),
        ImageSpec("banner", "banner.jpg"),
        ImageSpec("disc", "disc.png"),
        ImageSpec("clearart", "clearart.png"),
        ImageSpec("landscape", "landscape.jpg"),
    ],
    "season": [
        # 季海报只放在**该季自己的目录**里，且统一命名为 poster.jpg。
        # 不再往剧集根目录写 seasonNN-poster.jpg —— 那会把各季海报堆到同一个目录下
        # （与「一季一图、各归其位」的约定相悖），用户明确要求去掉。
        ImageSpec("poster", "poster.jpg"),
        ImageSpec("banner", "banner.jpg"),
        ImageSpec("landscape", "landscape.jpg"),
    ],
    "episodedetails": [
        ImageSpec("thumb", "{stem}.jpg"),
    ],
}


def image_targets(nfo: NfoFile, kinds: set,
                  season: Optional[str] = None) -> List[Tuple[ImageSpec, Path]]:
    """算出这个 NFO 对应的全部图片落盘路径。

    `season` 由引擎用 `resolve_season_episode()`（三级兜底）解析后传进来。
    以前这里自己解析、失败就**默认 0** —— 于是「解析不出季号的季 NFO」会写出
    `season00-poster.jpg`（用户就遇到过：剧目根本没有第 0 季）。
    更糟的是取图 URL 用的是另一套解析、可能算成第 1 季 ——
    结果是「拿第 1 季的图、写成 season00 的名字」。

    因此：**解析不出季号时直接跳过季专用文件名**（宁可不写，也不写错季）。
    """
    specs = IMAGE_SPECS.get(nfo.media_type, [])
    if not specs:
        return []
    if season is None:
        season = norm_text(nfo.root.findtext("season"))
    season_num: Optional[int] = None
    if season is not None and str(season).strip():
        digits = re.sub(r"\D", "", str(season))
        if digits:
            season_num = int(digits)
    out: List[Tuple[ImageSpec, Path]] = []
    for spec in specs:
        if spec.kind not in kinds:
            continue
        if "{season" in spec.name and season_num is None:
            continue            # 季号未知 → 不写 seasonNN-xxx，避免写出 season00 这种错名
        name = spec.name.format(stem=nfo.path.stem,
                               season=season_num if season_num is not None else 0)
        base = nfo.path.parent.parent if spec.in_parent else nfo.path.parent
        out.append((spec, base / name))
    return out


def sha256_file(path: Path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


class ImageManifest:
    """记录「这张本地图片来自哪个在线地址、内容指纹是什么」。

    有了它，稳态下才能在不下载的前提下判定「相同」—— 这正是官方插件做不到的：
    它只看文件在不在（`_should_scrape` 里 `file_exists` 一票否决），
    所以一张错图、低清图会永远留在库里。
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self.data: Dict[str, Dict[str, Any]] = {}
        self.dirty = False
        self._lock = threading.Lock()          # 多线程下 record/matches 都要串行化
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data = loaded
            except Exception as exc:
                logger.warning(f"读取图片指纹清单失败，将重建：{exc}")

    @staticmethod
    def key(path: Path) -> str:
        return str(path).replace("\\", "/")

    def matches(self, path: Path, url: str) -> bool:
        """清单能否证明「本地这张图就是该在线图」——能则不下载。"""
        with self._lock:
            entry = self.data.get(self.key(path))
        if not entry or entry.get("url") != url:
            return False
        return bool(entry.get("sha256")) and entry["sha256"] == sha256_file(path)

    def record(self, path: Path, url: str, digest: str, size: int) -> None:
        with self._lock:
            self.data[self.key(path)] = {
                "url": url, "sha256": digest, "size": size,
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.dirty = True

    def save(self) -> None:
        if not (self.path and self.dirty):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        except Exception as exc:
            logger.warning(f"写入图片指纹清单失败（不影响本次结果）：{exc}")


def write_image_bytes(path: Path, data: bytes, backup_root: Optional[Path], root_dir: Path) -> None:
    """原子写入图片：先写 .nfgpart 再 replace，避免媒体服务器读到半截文件。"""
    if backup_root:
        try:
            dst = backup_root / path.relative_to(root_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not dst.exists():      # 首次备份为准
                shutil.copy2(path, dst)
        except Exception as exc:
            logger.warning(f"备份图片失败（继续写入）：{path}（{exc}）")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".nfgpart")
    tmp.write_bytes(data)
    tmp.replace(path)


def pick_best_image(entries: List[dict], language: str) -> Optional[dict]:
    """从 TMDB 的图片数组里挑一张。

    排序优先级：语言匹配 → 分辨率（越大越好）→ 社区评分 → 投票数。
    语言上先要本语言、再要无文字版（iso_639_1 为空）、其次英文、最后其他语言。
    """
    lang = (language or "").split("-")[0].lower()

    def rank(item: dict) -> Tuple[int, int, float, int]:
        code = (item.get("iso_639_1") or "").lower()
        if lang and code == lang:
            lang_rank = 0
        elif not code:
            lang_rank = 1
        elif code == "en":
            lang_rank = 2
        else:
            lang_rank = 3
        return (lang_rank,
                -int(item.get("width") or 0),
                -float(item.get("vote_average") or 0),
                -int(item.get("vote_count") or 0))

    candidates = [item for item in entries or [] if item.get("file_path")]
    return min(candidates, key=rank) if candidates else None


def image_size_for(quality: str, kind: str) -> str:
    return IMG_SIZES.get(quality, IMG_SIZES["standard"]).get(kind, "original")


def normalize_image_kinds(raw: Any) -> Optional[List[str]]:
    """把 image_kinds 的历史各种写法收敛成合法的类型列表。

    历史上这个配置项换过三种载体，必须都能吃下并修好：

    - **布尔值**：v1.2.0 用复选框渲染，而宿主当时把它当单值处理，于是存成了 true / false，
      界面上就会冒出一个写着 `false` 的怪 chip。这里把 true 视为全选、false 视为全不选。
    - **列表**：v1.3.0 起多选下拉的载体，直接取其中的合法值（空列表就是空，用户明确关掉）。
    - **逗号字符串**：最早期的写法，以及 CLI 传参。

    返回 None 表示「压根没配过」（键缺失），由调用方决定默认值。
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return list(IMAGE_KINDS) if raw else []
    if isinstance(raw, (list, tuple, set)):
        wanted = {str(item).strip().casefold() for item in raw if str(item).strip()}
        return [kind for kind in IMAGE_KINDS if kind in wanted]

    text = str(raw).strip()
    if not text:
        return []
    wanted = {part.strip().casefold() for part in re.split(r"[,\s]+", text) if part.strip()}
    picked = [kind for kind in IMAGE_KINDS if kind in wanted]
    return picked or list(IMAGE_KINDS)      # 整串都没写对时回退全部，避免静默不干活


# ══════════════════════════════════════════════════════════════════════
# 在线数据源：统一产出 {字段名: [字符串]} 与 {图片类型: URL}
# ══════════════════════════════════════════════════════════════════════
class TmdbProvider:
    """直连 TMDB。行为最可预测，建议优先使用（需要一个免费 API Key）。"""

    name = "TMDB 直连"

    def __init__(self, api_key: str, language: str = "zh-CN", proxy: Optional[str] = None,
                 cert_country: str = "US", cast_limit: int = 20,
                 image_quality: str = "standard", concurrency: int = 1):
        self.api_key = api_key
        self.language = language
        self.cert_country = (cert_country or "US").upper()
        self.cast_limit = cast_limit
        self.image_quality = image_quality if image_quality in IMG_SIZES else "standard"
        # 图片域名跟随宿主配置（国内直连 image.tmdb.org 经常超时，MP 允许换镜像）
        self.img_host = image_host()
        # 光盘图 / 横幅图 / 透明艺术图 / 横版缩略图来自 fanart.tv，Key 自动沿用宿主配置
        self.fanart_key = fanart_api_key()
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)
        # 多线程下用线程安全的全局限速器（旧的「记时间戳」会被每个线程各自放行）
        self.limiter = RateLimiter(tmdb_gap(concurrency))
        self._lock = threading.Lock()
        self.calls = 0
        self.retries = 0      # 自动重试次数（给运行报告用）

    def _get(self, path: str, **params) -> Optional[dict]:
        """请求 TMDB，**网络类失败会自动重试**。

        国内直连 api.themoviedb.org 很常见 `SSL handshake timed out` / 连接被重置 ——
        以前一次失败就放弃，于是条目被记成「取不到在线数据，保持原样」。
        现在对这类瞬时错误重试 TMDB_RETRIES 次（递增退避），
        但 404（资源不存在）不重试，401（Key 无效）直接抛错。
        """
        params.update({"api_key": self.api_key, "language": self.language})
        url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
        last_error = ""
        for attempt in range(1, TMDB_RETRIES + 1):
            self.limiter.wait()          # 每次尝试都走限速，重试不会突破速率上限
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with self._lock:
                self.calls += 1
            wait = 0.0
            try:
                with self.opener.open(req, timeout=TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    raise RuntimeError("TMDB 返回 401：API Key 无效或未激活")
                if exc.code in (404, 422):
                    return None                       # 资源不存在，重试没有意义
                last_error = f"HTTP {exc.code}"
                wait = (5.0 if exc.code == 429 else TMDB_RETRY_WAIT) * attempt
            except Exception as exc:
                last_error = str(exc)
                wait = TMDB_RETRY_WAIT * attempt
            if attempt < TMDB_RETRIES:
                with self._lock:
                    self.retries += 1
                logger.debug(f"TMDB 请求失败将重试（第 {attempt}/{TMDB_RETRIES - 1} 次）："
                             f"{path}（{last_error}）")
                time.sleep(wait)
        logger.warning(f"TMDB 请求失败（已自动重试 {TMDB_RETRIES - 1} 次）：{path}（{last_error}）")
        return None

    @staticmethod
    def _cert(data: dict, country: str) -> str:
        def pick(entries, key_a, key_b):
            for entry in entries or []:
                if entry.get("iso_3166_1") == country:
                    for sub in entry.get(key_a) or []:
                        val = str(sub.get(key_b) or "").strip()
                        if val:
                            return val
            for entry in entries or []:
                for sub in entry.get(key_a) or []:
                    val = str(sub.get(key_b) or "").strip()
                    if val:
                        return val
            return ""

        return (pick((data.get("release_dates") or {}).get("results"), "release_dates", "certification")
                or pick((data.get("content_ratings") or {}).get("results"), "ratings", "rating"))

    @staticmethod
    def _crew(credits: dict, jobs: set) -> List[str]:
        out, seen = [], set()
        for person in (credits or {}).get("crew") or []:
            pname = (person.get("name") or "").strip()
            if person.get("job") in jobs and pname and pname not in seen:
                seen.add(pname)
                out.append(pname)
        return out

    def _actors(self, credits: dict) -> List[str]:
        # cast_limit <= 0 表示不限制（全部写入）
        people = [
            ACTOR_SEP.join([(a.get("name") or "").strip(), (a.get("character") or "").strip(),
                            (self.img_host + "original" + a["profile_path"]) if a.get("profile_path") else ""])
            for a in (credits or {}).get("cast") or []
            if (a.get("name") or "").strip()
        ]
        return people if self.cast_limit <= 0 else people[: self.cast_limit]
    def fetch_movie(self, tmdb_id: str) -> Dict[str, List[str]]:
        data = self._get(f"/movie/{tmdb_id}", append_to_response="credits,release_dates")
        if not data:
            return {}
        credits = data.get("credits") or {}
        return {
            "title": to_str_list(data.get("title")),
            "originaltitle": to_str_list(data.get("original_title")),
            "plot": to_str_list(data.get("overview")),
            "tagline": to_str_list(data.get("tagline")),
            "year": to_str_list((data.get("release_date") or "")[:4]),
            "premiered": to_str_list(data.get("release_date")),
            "runtime": to_str_list(data.get("runtime")),
            "mpaa": to_str_list(self._cert(data, self.cert_country)),
            "rating": to_str_list(f"{data['vote_average']:.1f}" if data.get("vote_average") else ""),
            "genre": [str(g.get("name") or "").strip() for g in data.get("genres") or [] if g.get("name")],
            "studio": [str(c.get("name") or "").strip() for c in data.get("production_companies") or [] if c.get("name")],
            "country": [str(c.get("name") or c.get("iso_3166_1") or "").strip()
                        for c in data.get("production_countries") or []],
            "director": self._crew(credits, {"Director"}),
            "credits": self._crew(credits, {"Writer", "Screenplay", "Story"}),
            "actor": self._actors(credits),
        }

    def fetch_tvshow(self, tmdb_id: str) -> Dict[str, List[str]]:
        data = self._get(f"/tv/{tmdb_id}", append_to_response="credits,content_ratings")
        if not data:
            return {}
        credits = data.get("credits") or {}
        runtimes = data.get("episode_run_time") or []
        return {
            "title": to_str_list(data.get("name")),
            "plot": to_str_list(data.get("overview")),
            "tagline": to_str_list(data.get("tagline")),
            "year": to_str_list((data.get("first_air_date") or "")[:4]),
            "premiered": to_str_list(data.get("first_air_date")),
            "runtime": to_str_list(runtimes[0] if runtimes else ""),
            "mpaa": to_str_list(self._cert(data, self.cert_country)),
            "rating": to_str_list(f"{data['vote_average']:.1f}" if data.get("vote_average") else ""),
            "genre": [str(g.get("name") or "").strip() for g in data.get("genres") or [] if g.get("name")],
            "studio": [str(n.get("name") or "").strip() for n in data.get("networks") or [] if n.get("name")],
            "country": [str(c.get("name") or c.get("iso_3166_1") or "").strip()
                        for c in data.get("production_countries") or []],
            "director": self._crew(credits, {"Director"}),
            "credits": self._crew(credits, {"Writer", "Screenplay", "Story"}),
            "actor": self._actors(credits),
        }

    def fetch_episode(self, tmdb_id: str, season: str, episode: str) -> Dict[str, List[str]]:
        data = self._get(f"/tv/{tmdb_id}/season/{season}/episode/{episode}",
                         append_to_response="credits")
        if not data:
            return {}
        credits = data.get("credits") or {}
        return {
            "title": to_str_list(data.get("name")),
            "plot": to_str_list(data.get("overview")),
            "aired": to_str_list(data.get("air_date")),
            "rating": to_str_list(f"{data['vote_average']:.1f}" if data.get("vote_average") else ""),
            "season": to_str_list(data.get("season_number")),
            "episode": to_str_list(data.get("episode_number")),
            "director": self._crew(credits, {"Director"}),
            "credits": self._crew(credits, {"Writer", "Screenplay"}),
            "actor": self._actors(credits),
        }

    def fetch_season(self, tmdb_id: str, season: str) -> Dict[str, List[str]]:
        data = self._get(f"/tv/{tmdb_id}/season/{season}")
        if not data:
            return {}
        return {
            "title": to_str_list(data.get("name")),
            "plot": to_str_list(data.get("overview")),
            "premiered": to_str_list(data.get("air_date")),
            "season": to_str_list(data.get("season_number")),
        }

    def search(self, title: str, year: Optional[str] = None, is_tv: bool = False) -> Optional[str]:
        """按标题（+年份）搜索 TMDB 返回 id。让 NFO 里没有 tmdbid 的存量文件也能被识别。"""
        if not title:
            return None
        params: Dict[str, Any] = {"query": title}
        if year:
            params["first_air_date_year" if is_tv else "year"] = year
        data = self._get("/search/tv" if is_tv else "/search/movie", **params)
        results = (data or {}).get("results") or []
        if not results:
            return None
        if year:                      # 有年份时优先取年份一致的，避免命中重名新片
            for item in results:
                date = item.get("first_air_date") if is_tv else item.get("release_date")
                if str(date or "").startswith(str(year)) and item.get("id"):
                    return str(item["id"])
        first = results[0].get("id")
        return str(first) if first else None

    # ── 图片 ────────────────────────────────────────────────────────
    def image_size(self, kind: str) -> str:
        return image_size_for(self.image_quality, kind)

    def fetch_images(self, tmdb_id: str, media_type: str, season: Optional[str] = None,
                     episode: Optional[str] = None, kinds: Any = ()) -> Dict[str, str]:
        """返回 {图片类型: 在线地址}。拿不到的图片类型不会出现在结果里。"""
        lang = (self.language or "").split("-")[0].lower()
        include = ",".join([part for part in (lang, "en", "null") if part])
        if media_type == "movie":
            path = f"/movie/{tmdb_id}/images"
        elif media_type == "tvshow":
            path = f"/tv/{tmdb_id}/images"
        elif media_type == "season" and season:
            path = f"/tv/{tmdb_id}/season/{season}/images"
        elif media_type == "episodedetails" and season and episode:
            path = f"/tv/{tmdb_id}/season/{season}/episode/{episode}/images"
        else:
            return {}
        data = self._get(path, include_image_language=include)
        if not data:
            return {}
        out: Dict[str, str] = {}
        for kind in kinds:
            best = pick_best_image(data.get(IMG_API_KEYS.get(kind, "")) or [], self.language)
            if best:
                out[kind] = f"{self.img_host}{self.image_size(kind)}{best['file_path']}"
        # TMDB 只有海报 / 背景图 / 徽标 / 剧照；光盘图、横幅图、透明艺术图、横版缩略图
        # 只有 fanart.tv 提供，需要额外查一次（电影按 tmdbid，剧集按 thetvdb id）
        missing = {kind for kind in kinds if kind in FANART_KEYS and kind not in out}
        if missing and not self.fanart_key:
            if not getattr(self, "_warned_fanart_key", False):
                self._warned_fanart_key = True
                logger.warning("要处理 " + "、".join(
                    f"{k}（{IMAGE_KIND_CN.get(k, k)}）" for k in sorted(missing))
                    + "，但拿不到 fanart.tv 的 API Key（会自动沿用 MoviePilot 的"
                      " FANART_API_KEY，MP 自带默认值）—— 这几类本轮跳过")
            missing = set()
        if missing:
            tvdb_id = ""
            if media_type != "movie":
                external = self._get(f"/tv/{tmdb_id}/external_ids") or {}
                tvdb_id = str(external.get("tvdb_id") or "").strip()
            for kind, url in fanart_image_urls(missing, tmdb_id, tvdb_id,
                                               self.fanart_key).items():
                out.setdefault(kind, url)
        return out

    def read_image(self, url: str) -> Optional[bytes]:
        return download_bytes(url, self.opener)


class HostProvider:
    """借用 MoviePilot 自身的媒体识别链路，无需额外 API Key（尽力而为，失败会明确记日志）。"""

    name = "MoviePilot 宿主链路"

    def __init__(self, image_quality: str = "standard", cast_limit: int = 20) -> None:
        self._chain = None
        self._failed = False
        self._opener_obj = None
        self.image_quality = image_quality if image_quality in IMG_SIZES else "standard"
        self.cast_limit = cast_limit
        self.img_host = image_host()

    def _media_chain(self):
        if self._failed:
            return None
        if self._chain is None:
            try:
                from app.chain.media import MediaChain  # type: ignore
                self._chain = MediaChain()
            except Exception as exc:
                logger.warning(f"无法加载宿主 MediaChain，将只能依赖其它数据源：{exc}")
                self._failed = True
        return self._chain

    def _recognize(self, tmdb_id: str, is_tv: bool):
        chain = self._media_chain()
        if chain is None:
            return None
        try:
            from app.schemas.types import MediaSource, MediaType  # type: ignore
        except Exception:
            MediaSource = MediaType = None  # type: ignore
        attempts = []
        if MediaSource is not None:
            attempts.append(dict(media_source=MediaSource.TMDB, media_id=str(tmdb_id),
                                 mtype=MediaType.TV if is_tv else MediaType.MOVIE))
        # V2 旧签名兜底
        attempts.append(dict(tmdbid=str(tmdb_id), mtype="电视剧" if is_tv else "电影"))
        for kwargs in attempts:
            try:
                info = chain.recognize_media(**kwargs)
                if info:
                    return info
            except Exception:
                continue
        return None

    @staticmethod
    def _info_to_fields(info: Any, is_tv: bool, limit: int = 20) -> Dict[str, List[str]]:
        """把宿主的 MediaInfo 转成 {字段名: [文本]}。

        注意：MediaInfo 的 genre / studio / country / director / actor 拿到的是**结构化对象**
        （List[dict] 或 List[MediaPerson]），必须用 text_list / person_fields 剥成名字，
        **绝对不要对它们做 str()** —— 那会把 Python 字面量写进用户的 NFO。
        """
        def g(*names: str) -> Any:
            for name in names:
                value = getattr(info, name, None)
                if value not in (None, "", [], {}):
                    return value
            return None

        people = list(g("actors") or [])
        if limit > 0:
            people = people[:limit]
        actors = []
        for person in people:
            name, role, image = person_fields(person)
            if name:                       # 名字为空的条目没有意义，不写
                actors.append(ACTOR_SEP.join([name, role, image]))

        runtimes = g("episode_run_time")
        if isinstance(runtimes, (list, tuple)) and runtimes:
            runtimes = [runtimes[0]]       # 只取第一集时长，避免写出多个 <runtime>

        fields = {
            "title": text_list(g("title", "name")),
            "originaltitle": text_list(g("original_title", "original_name")),
            "plot": text_list(g("overview", "plot")),
            "tagline": text_list(g("tagline")),
            "rating": text_list(g("vote_average", "rating")),
            # 以下都是「名字列表」，宿主给的是对象，必须剥
            "genre": text_list(g("genres", "genre")),
            "country": text_list(g("production_countries", "country", "origin_country")),
            "director": text_list(g("directors", "director")),
            "actor": actors,
        }
        if is_tv:
            fields["premiered"] = text_list(g("first_air_date", "release_date"))
            fields["year"] = [str(g("first_air_date", "release_date") or "").strip()[:4]]
            fields["studio"] = text_list(g("networks", "production_companies", "studios"))
            fields["runtime"] = text_list(runtimes)
        else:
            fields["premiered"] = text_list(g("release_date"))
            fields["year"] = [str(g("release_date") or "").strip()[:4]]
            fields["runtime"] = text_list(g("runtime"))
            fields["studio"] = text_list(g("production_companies", "studios"))
        return {k: v for k, v in fields.items() if v}

    def fetch_movie(self, tmdb_id: str) -> Dict[str, List[str]]:
        info = self._recognize(tmdb_id, False)
        return self._info_to_fields(info, False, self.cast_limit) if info else {}

    def fetch_tvshow(self, tmdb_id: str) -> Dict[str, List[str]]:
        info = self._recognize(tmdb_id, True)
        return self._info_to_fields(info, True, self.cast_limit) if info else {}

    def fetch_episode(self, tmdb_id: str, season: str, episode: str) -> Dict[str, List[str]]:
        logger.warning("宿主链路暂不支持单集简介比对，建议为插件填写 TMDB API Key")
        return {}

    def fetch_season(self, tmdb_id: str, season: str) -> Dict[str, List[str]]:
        return {}

    # ── 图片 ────────────────────────────────────────────────────────
    def fetch_images(self, tmdb_id: str, media_type: str, season: Optional[str] = None,
                     episode: Optional[str] = None, kinds: Any = ()) -> Dict[str, str]:
        """宿主链路只能给到海报与背景图（MediaInfo 的 poster_path / backdrop_path）。

        剧集缩略图、季海报、徽标拿不到 —— 那几类需要 TMDB API Key 走直连。
        """
        if media_type not in ("movie", "tvshow"):
            return {}
        fanart_wanted = sorted(k for k in kinds or () if k in FANART_KEYS)
        if fanart_wanted and not getattr(self, "_warned_fanart", False):
            self._warned_fanart = True
            logger.warning("宿主刮削通道拿不到 " + "、".join(
                f"{k}（{IMAGE_KIND_CN.get(k, k)}）" for k in fanart_wanted)
                + " —— 这几类来自 fanart.tv，需要配置 TMDB API Key 走直连")
        info = self._recognize(tmdb_id, media_type == "tvshow")
        if info is None:
            return {}
        attrs = {"poster": ("poster_path", "poster"), "backdrop": ("backdrop_path", "backdrop")}
        out: Dict[str, str] = {}
        for kind in kinds:
            for attr in attrs.get(kind, ()):
                value = str(getattr(info, attr, "") or "").strip()
                if value:
                    out[kind] = (value if value.startswith("http")
                                 else self.img_host + image_size_for(self.image_quality, kind) + value)
                    break
        return out

    def _opener(self):
        """优先复用宿主配置的代理，否则直连。"""
        if self._opener_obj is None:
            handlers = []
            try:
                from app.core.config import settings  # type: ignore
                proxy = (getattr(settings, "PROXY_HOST", "") or "").strip()
                if proxy:
                    handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            except Exception:
                pass
            self._opener_obj = urllib.request.build_opener(*handlers)
        return self._opener_obj

    def read_image(self, url: str) -> Optional[bytes]:
        return download_bytes(url, self._opener())


class FileProvider:
    """从本地 JSON 读取「在线数据」，用于离线演练与回归测试。

    元数据 JSON 结构： {"movie:157336": {"plot": ["..."], "actor": ["名字|角色|https://..."]}, ...}
    键规则：movie:<tmdbid> / tv:<tmdbid> / season:<tmdbid>:<季> / episode:<tmdbid>:<季>:<集>

    图片 JSON 结构： {"images:movie:157336": {"poster": "images/poster_a.jpg", ...}, ...}
    键规则同上前缀 images:；值可以是 http(s) 地址，也可以是相对缓存文件所在目录的本地路径
    （本地路径让整条图片链路不联网也能测）。
    """

    name = "本地 JSON"

    def __init__(self, cache_path: str):
        self.data: Dict[str, Any] = {}
        self.base_dir = Path(cache_path).parent if cache_path else Path(".")
        if cache_path:
            try:
                self.data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"读取缓存 JSON 失败：{cache_path}（{exc}）")
        self.calls = 0
        self._lock = threading.Lock()

    def _lookup(self, key: str) -> Dict[str, List[str]]:
        with self._lock:
            self.calls += 1
        return self.data.get(key) or {}

    def fetch_movie(self, tmdb_id: str) -> Dict[str, List[str]]:
        return self._lookup(f"movie:{tmdb_id}")

    def fetch_tvshow(self, tmdb_id: str) -> Dict[str, List[str]]:
        return self._lookup(f"tv:{tmdb_id}")

    def fetch_season(self, tmdb_id: str, season: str) -> Dict[str, List[str]]:
        return self._lookup(f"season:{tmdb_id}:{season}")

    def fetch_episode(self, tmdb_id: str, season: str, episode: str) -> Dict[str, List[str]]:
        return self._lookup(f"episode:{tmdb_id}:{season}:{episode}")

    # ── 图片 ────────────────────────────────────────────────────────
    def fetch_images(self, tmdb_id: str, media_type: str, season: Optional[str] = None,
                     episode: Optional[str] = None, kinds: Any = ()) -> Dict[str, str]:
        if media_type == "movie":
            key = f"images:movie:{tmdb_id}"
        elif media_type == "tvshow":
            key = f"images:tv:{tmdb_id}"
        elif media_type == "season":
            key = f"images:season:{tmdb_id}:{season}"
        elif media_type == "episodedetails":
            key = f"images:episode:{tmdb_id}:{season}:{episode}"
        else:
            return {}
        entry = self.data.get(key) or {}
        return {kind: str(entry[kind]) for kind in kinds
                if isinstance(entry, dict) and entry.get(kind)}

    def read_image(self, url: str) -> Optional[bytes]:
        """http(s) 走网络；其余按本地文件路径读（相对路径按缓存 JSON 所在目录解析）。"""
        text = str(url or "").strip()
        if text.startswith(("http://", "https://")):
            request = urllib.request.Request(text, headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    return response.read()
            except Exception as exc:
                logger.warning(f"图片下载失败：{text}（{exc}）")
                return None
        raw = text[7:] if text.startswith("file://") else text
        path = Path(urllib.parse.unquote(raw))
        if not path.is_absolute():
            path = self.base_dir / path
        try:
            return path.read_bytes()
        except Exception as exc:
            logger.warning(f"读取本地图片失败：{path}（{exc}）")
            return None


# ══════════════════════════════════════════════════════════════════════
# 引擎配置与报告
# ══════════════════════════════════════════════════════════════════════
@dataclass
class EngineConfig:
    roots: List[Path]
    exclude_paths: List[str] = field(default_factory=list)
    root_types: Dict[str, str] = field(default_factory=dict)   # {目录路径: movie|tv} 限定该目录的类型
    mode: str = "sync"                     # report | gapfill | sync | force
    protect_fields: set = field(default_factory=set)
    only_fields: set = field(default_factory=set)
    respect_lock: bool = True
    dry_run: bool = False
    backup: bool = True
    backup_dir: Optional[Path] = None
    max_files: int = 0
    concurrency: int = 1        # 处理并发数（1 = 顺序执行）
    report_limit: int = 300
    # ── 图片 ──（引擎默认关闭，由插件/CLI 显式开启，避免意外的网络流量）
    image_mode: str = IMG_OFF              # off | missing | sync
    image_kinds: set = field(default_factory=lambda: set(IMAGE_KINDS))
    image_quality: str = "standard"        # standard | original
    manifest_path: Optional[Path] = None   # 图片指纹清单，稳态下靠它零下载判定「相同」


@dataclass
class Change:
    nfo: str
    media_type: str
    field: str
    verdict: str
    action: str
    local: str
    remote: str


@dataclass
class Report:
    started: str = ""
    finished: str = ""
    scanned: int = 0
    untouched: int = 0            # 无任何差异
    changed_files: int = 0        # 实际写入了几个文件
    skipped_locked: int = 0
    skipped_type: int = 0         # 所在目录被 #类型 限定时跳过的条数
    scrubbed: int = 0             # 清理掉的「对象字面量」历史脏值节点数
    retried: int = 0              # 网络失败后自动重试的次数
    images_missing: int = 0       # 在线没有对应图片、且拒绝回退的季海报数
    legacy_alias: int = 0         # 检测到的旧版 seasonNN-poster.jpg 残留数
    unresolved: int = 0           # 拿不到在线数据
    failed: int = 0
    counts: Dict[str, int] = field(default_factory=dict)    # 差异判定统计
    applied: Dict[str, int] = field(default_factory=dict)   # 实际动作统计
    changes: List[Change] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    mode: str = "sync"
    provider: str = ""
    calls: int = 0
    images_scanned: int = 0
    images_written: int = 0
    image_bytes: int = 0
    image_counts: Dict[str, int] = field(default_factory=dict)    # 图片差异判定统计
    image_applied: Dict[str, int] = field(default_factory=dict)   # 图片实际动作统计
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    # ── 并发安全的自增入口（多线程下必须走这里，否则会丢计数）──────
    def bump(self, name: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name, 0) + n)

    def tally(self, bucket: str, key: str, n: int = 1) -> None:
        with self._lock:
            target = getattr(self, bucket)
            target[key] = target.get(key, 0) + n

    def add_error(self, text: str) -> None:
        with self._lock:
            self.errors.append(text)

    def add_change(self, change: "Change", limit: int) -> None:
        with self._lock:
            if len(self.changes) < limit:
                self.changes.append(change)

    def to_text(self) -> str:
        lines = [
            f"运行模式：{self.mode}　数据源：{self.provider}　在线请求：{self.calls} 次",
            f"开始：{self.started}　结束：{self.finished}",
            "-" * 62,
            f"扫描 NFO {self.scanned} 个｜无差异 {self.untouched}｜已写入文件 {self.changed_files}"
            f"｜受锁保护 {self.skipped_locked}｜取不到在线数据 {self.unresolved}｜失败 {self.failed}",
        ]
        if self.skipped_type:
            lines.append(f"按目录的「#类型」限定跳过 {self.skipped_type} 个 NFO（类型不符）")
        if self.scrubbed:
            lines.append(f"清理历史脏值 {self.scrubbed} 处"
                         f"（早期版本把结构化对象写成 Python 字面量留下的）")
        if self.retried:
            lines.append(f"网络抖动自动重试 {self.retried} 次"
                         f"（重试后仍失败的条目会记在下方）")
        if self.images_missing:
            lines.append(f"{self.images_missing} 季在线没有海报，已跳过（不回退其它季或剧集海报）")
        if self.legacy_alias:
            lines.append(f"检测到 {self.legacy_alias} 个旧版残留的「剧集目录/seasonNN-poster.jpg」，"
                         f"新版只写「季目录/poster.jpg」，这些旧文件可自行删除")
        if self.counts:
            lines.append("差异判定：" + "｜".join(f"{k} {v}" for k, v in self.counts.items()))
        if self.applied:
            lines.append("实际动作：" + "｜".join(f"{k} {v}" for k, v in self.applied.items()))
        if self.images_scanned:
            lines.append(f"检查图片 {self.images_scanned} 张｜写入 {self.images_written} 张"
                         f"（{self.image_bytes / 1048576:.1f} MB）")
        if self.image_counts:
            lines.append("图片判定：" + "｜".join(f"{k} {v}" for k, v in self.image_counts.items()))
        if self.image_applied:
            lines.append("图片动作：" + "｜".join(f"{k} {v}" for k, v in self.image_applied.items()))
        if self.errors:
            lines.append("-" * 62)
            lines.append(f"无法比对/失败 {len(self.errors)} 条（最多列 15 条）：")
            lines.extend(f"  · {e}" for e in self.errors[:15])
        if self.changes:
            lines.append("-" * 62)
            lines.append(f"变更明细（本次共 {len(self.changes)} 条）")
            for c in self.changes:
                lines.append(f"[{c.action}] {c.nfo} :: {c.field}")
                lines.append(f"    本地：{(c.local or '（空）')[:140]}")
                lines.append(f"    在线：{(c.remote or '（空）')[:140]}")
        return "\n".join(lines)

    @staticmethod
    def _needs_write(action: str) -> bool:
        """这条记录是否代表「会写盘」（演练 / 只报告模式下的待执行也算）。"""
        return bool(action) and not any(token in action for token in ("跳过", "未比对"))

    def change_rows(self, limit: int = 200) -> List[Dict[str, Any]]:
        """按文件聚合「本次改了什么」，供插件详情页表格直接渲染。

        只收会写盘的条目：跳过（锁定 / 保护字段 / gapfill / 仅补缺失）与「未比对」都不算改动；
        演练与只报告模式下的「仅报告（应为补齐）」也算，这样首轮体检就能看清将要改哪些文件。
        """
        agg: Dict[str, Dict[str, Any]] = {}
        for c in self.changes:
            if not self._needs_write(c.action):
                continue
            row = agg.setdefault(c.nfo, {"file": c.nfo, "kind": "", "fields": [], "images": []})
            if c.media_type != "图片" and not row["kind"]:
                row["kind"] = c.media_type
            bucket = "images" if c.media_type == "图片" else "fields"
            name = c.field.replace("[图片] ", "") if bucket == "images" else c.field
            item = f"{name} · {c.action}"
            if item not in row[bucket]:
                row[bucket].append(item)
        return [{
            "file": row["file"],
            "kind": row["kind"] or "图片",
            "fields": "、".join(row["fields"])[:150] or "—",
            "images": "、".join(row["images"])[:150] or "—",
        } for row in agg.values()][:limit]


# ══════════════════════════════════════════════════════════════════════
# 引擎主流程
# ══════════════════════════════════════════════════════════════════════
def iter_nfo_files(root: Path) -> List[Path]:
    """递归收集 NFO，跳过本工具的备份目录。"""
    return [path for path in sorted(root.rglob("*.nfo")) if ".nfo-backup" not in path.parts]


def is_excluded(path: Path, excludes: List[str]) -> bool:
    text = str(path).replace("\\", "/").casefold()
    return any(ex.strip().casefold() in text for ex in excludes if ex.strip())


def find_tmdb_id(root: ET.Element, media_type: str) -> Tuple[Optional[str], str]:
    for uid in root.findall("uniqueid"):
        if (uid.get("type") or "").casefold() in ("tmdb", "tmdbid") and norm_text(uid.text):
            return norm_text(uid.text), "NFO 内 uniqueid"
    el = root.find("tmdbid")
    if el is not None and norm_text(el.text).isdigit():
        return norm_text(el.text), "NFO 内 tmdbid"
    return None, "NFO 内无 TMDB 标识"


def title_year_from_dir(name: str) -> Tuple[Optional[str], Optional[str]]:
    """从目录名里猜「标题 + 年份」：「藏海传 (2025)」→ ("藏海传", "2025")。"""
    match = re.search(r"[\(\[]((?:19|20)\d{2})[\)\]]", name or "")
    year = match.group(1) if match else None
    title = re.sub(r"[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]", "", name or "").strip(" -_·") or None
    return title, year


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(text: str) -> Optional[int]:
    """把常见中文数字转成整数（一~九十九）：「第一季」→ 1、「第十二季」→ 12。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw == "十":
        return 10
    if "十" in raw:
        head, _, tail = raw.partition("十")
        if head and head not in _CN_DIGITS:
            return None
        if tail and tail not in _CN_DIGITS:
            return None
        tens = _CN_DIGITS.get(head, 1) if head else 1
        return tens * 10 + _CN_DIGITS.get(tail, 0)
    return _CN_DIGITS.get(raw)


def season_from_dir(name: str) -> Optional[str]:
    """从目录名里取季号：「Season 01」/「S01」/「第 1 季」/「第一季」→ "1"。

    **season.nfo 这种文件名里根本没有季号** —— 季号只能从上级目录名取，
    只看文件名必然得到「无法确定季号」。
    """
    text = str(name or "").strip()
    # 「S01E01」「1x02」这种是单集命名，不是季目录 —— 宁可不猜，
    # 也不能把别的季的元数据写进 NFO
    if re.search(r"s\d{1,3}\s*e\d{1,3}", text, re.I) or re.search(r"(?:^|\D)\d{1,2}x\d", text):
        return None
    # 花絮/特典按惯例是第 0 季（Kodi / Jellyfin 都这么放）
    if re.search(r"specials?(?:$|[\s._-])", text, re.I) or "特别篇" in text or "特典" in text:
        return "0"
    patterns = (
        r"(?:season|s)\s*0*(\d{1,3})(?!\d)",       # Season 01 / S01 / season1
        r"第\s*0*(\d{1,3})\s*季",                   # 第 1 季 / 第01季
        r"(?:^|\D)(\d{1,3})\s*季(?![节])",           # 1 季
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            number = int(match.group(1))
            if 0 <= number <= 100:
                return str(number)
    # 中文季名：第一季 / 第十二季（国产剧目录里很常见）
    match = re.search(r"第\s*([零一二两三四五六七八九十]+)\s*季", text)
    if match:
        number = cn_number(match.group(1))
        if number is not None and 0 <= number <= 100:
            return str(number)
    return None


def tmdb_id_from_dir(name: str) -> Optional[str]:
    """从目录名里读 MP 整理后的 tmdbid，例如「藏海传 (2025) {tmdbid=252640}」。"""
    match = re.search(r"tmdbid\s*[=\-:]\s*(\d+)", name or "", re.I)
    return match.group(1) if match else None


def guess_title_year(nfo: NfoFile) -> Tuple[Optional[str], Optional[str]]:
    root = nfo.root
    title = norm_text(root.findtext("title"))
    year = norm_text(root.findtext("year") or root.findtext("premiered") or root.findtext("aired"))
    year = year[:4] if year else None
    if not title:
        name = nfo.path.parent.name
        if name.casefold().startswith("season"):
            name = nfo.path.parent.parent.name
        dir_title, dir_year = title_year_from_dir(name)
        year = year or dir_year
        title = dir_title
    return title, year


class Engine:
    def __init__(self, cfg: EngineConfig, provider: Any,
                 cancel: Optional[Event] = None, single_file: Optional[Path] = None):
        self.cfg = cfg
        self.provider = provider
        self.cancel = cancel or Event()
        self.single_file = single_file
        self.report = Report(mode=cfg.mode, provider=getattr(provider, "name", "?"))
        self.manifest = ImageManifest(cfg.manifest_path)
        self._warned_junk: set = set()      # 脏值告警去重，避免刷屏
        self._lock = threading.Lock()       # 保护 _warned_junk 等并发共享状态
        self._legacy_seen: set = set()      # 旧版季海报残留：按剧集目录去重告警

    def sanitize_remote(self, field: str, values: List[str]) -> List[str]:
        """护栏：拦掉「结构化对象被 str() 出来」的脏值。

        真实元数据不可能长成 {'id': 12, 'name': '冒险'} 这样。一旦出现，说明数据源有 bug；
        这种内容写进 NFO 会让媒体服务器显示成乱码（Jellyfin 还会把 <director> 按逗号
        拆成一堆假条目），所以宁可跳过并告警，也绝不能写进用户的媒体库。
        """
        clean, junk = [], []
        for value in values:
            (junk if looks_like_object_repr(value) else clean).append(value)
        if junk:
            with self._lock:
                first_time = field not in self._warned_junk
                self._warned_junk.add(field)
            if first_time:
                logger.warning(f"在线数据里的「{field}」疑似把结构化对象直接转成了字符串，"
                               f"已跳过该值（请把这条反馈给数据源）：{junk[0][:80]}")
        return clean

    # ── 在线数据获取 ────────────────────────────────────────────────
    def fetch_remote(self, nfo: NfoFile) -> Tuple[Dict[str, List[str]], str]:
        root = nfo.root
        mtype = nfo.media_type

        tmdb_id, source = self.resolve_tmdb_id(nfo)
        if not tmdb_id:
            return {}, source

        if mtype == "movie":
            return self.provider.fetch_movie(tmdb_id), f"tmdb:{tmdb_id}（{source}）"
        if mtype == "tvshow":
            return self.provider.fetch_tvshow(tmdb_id), f"tmdb:{tmdb_id}（{source}）"
        if mtype == "season":
            season, _ = self.resolve_season_episode(nfo, mtype)
            if not season:
                return {}, "无法确定季号（NFO 里没有 <season>，目录名里也没写「Season 01」这类信息）"
            return self.provider.fetch_season(tmdb_id, season), f"tmdb:{tmdb_id} 第 {season} 季"
        season, episode = self.resolve_season_episode(nfo, mtype)
        if not (season and episode):
            return {}, f"无法确定季/集号（季={season or '?'} 集={episode or '?'}）"
        return (self.provider.fetch_episode(tmdb_id, season, episode),
                f"tmdb:{tmdb_id} S{season}E{episode}")

    @staticmethod
    def _from_name(nfo: NfoFile, pattern: str) -> Optional[str]:
        match = re.search(pattern, nfo.path.name, re.I)
        return match.group(1) if match else None

    def resolve_season_episode(self, nfo: NfoFile,
                               mtype: str) -> Tuple[Optional[str], Optional[str]]:
        """确定季号 / 集号：NFO 标签 → **上级目录名** → 文件名。

        以前只从「文件名」兜底 —— 而 `season.nfo` 里没有任何季号信息（名字就叫 season.nfo），
        于是整季被判定为「无法确定季号」直接跳过。季号其实写在**上级目录名**里（Season 01）。
        """
        root = nfo.root
        season = norm_text(root.findtext("season"))
        episode = norm_text(root.findtext("episode"))
        if not season:
            season = (season_from_dir(nfo.path.parent.name)
                      or season_from_dir(nfo.path.parent.parent.name))
        if not season:
            # 文件名兜底：S01E02 / 1x02
            season = self._from_name(nfo, r"S(\d+)") or self._from_name(nfo, r"(\d+)x\d+")
        if mtype == "episodedetails" and not episode:
            episode = self._from_name(nfo, r"E(\d+)") or self._from_name(nfo, r"\dx(\d+)")
        return season, episode

    def resolve_tmdb_id(self, nfo: NfoFile) -> Tuple[Optional[str], str]:
        """确定「该用哪个 TMDB id」—— 这里有个极易踩、后果很严重的坑：

        - **电影**：NFO 里的 `<tmdbid>` 就是电影 id ✓
        - **剧集**：tvshow.nfo 里的 `<tmdbid>` 就是剧集 id ✓
        - **季 / 单集**：NFO 里的 `<tmdbid>` 是「这一季 / 这一集自己的 id」，
          而 TMDB 的 season / episode 接口要的是**剧集 id**。直接拿单集 id 去查必然 404 ——
          表现就是整个库的单集全部「取不到在线数据，保持原样」。这两类必须向上取剧集 id。
        """
        mtype = nfo.media_type
        if mtype in ("season", "episodedetails"):
            return self._find_show_id(nfo)
        found = find_tmdb_id(nfo.root, mtype)
        if found[0]:
            return found
        if mtype == "tvshow":
            return self._find_show_id(nfo)
        # 电影：NFO 没写 tmdbid 时，先看目录名里有没有 {tmdbid=xxx}，再退回按标题搜索
        from_dir = tmdb_id_from_dir(nfo.path.parent.name)
        if from_dir:
            return from_dir, "目录名里的 tmdbid"
        return self._search_id(nfo, is_tv=False)

    def _find_show_id(self, nfo: NfoFile) -> Tuple[Optional[str], str]:
        """单集/季 NFO 取「剧集 id」：先向上找 tvshow.nfo，再退到剧集目录名。

        **绝不能拿单集自己的 <tmdbid> 兜底** —— 那是单集 id，拿去查 season/episode 必然 404。
        """
        current = nfo.path.parent
        for _ in range(4):
            current = current.parent
            candidate = current / "tvshow.nfo"
            if candidate.exists():
                loaded = load_nfo(candidate)
                if loaded:
                    found = find_tmdb_id(loaded.root, "tvshow")
                    if found[0]:
                        return found[0], "同剧 tvshow.nfo"
            if current == current.parent:
                break

        # 没有可用的 tvshow.nfo：退到「剧集目录」
        show_dir = nfo.path.parent
        if show_dir.name.casefold().startswith("season"):
            show_dir = show_dir.parent
        # MP 整理后的目录名常带 {tmdbid=xxx}（例如「藏海传 (2025) {tmdbid=252640}」）
        from_dir = tmdb_id_from_dir(show_dir.name)
        if from_dir:
            return from_dir, "剧集目录名里的 tmdbid"
        title, year = title_year_from_dir(show_dir.name)
        if title and hasattr(self.provider, "search"):
            found = self.provider.search(title, year, True)
            if found:
                return found, f"按剧集目录名搜索「{title}」{year or ''}".strip()
        return None, "未找到剧集 TMDB 标识（建议给 tvshow.nfo 补上 tmdbid）"

    def _search_id(self, nfo: NfoFile, is_tv: bool) -> Tuple[Optional[str], str]:
        title, year = guess_title_year(nfo)
        if not title or not hasattr(self.provider, "search"):
            return None, "无法识别（建议为该 NFO 补上 tmdbid）"
        found = self.provider.search(title, year, is_tv)
        if found:
            return found, f"按标题搜索「{title}」{year or ''}".strip()
        return None, f"搜索「{title}」未命中"

    # ── 主循环 ──────────────────────────────────────────────────────
    def run(self) -> Report:
        self.report.started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        targets: List[Path] = []
        for root in self.cfg.roots:
            if not root.is_dir():
                logger.warning(f"目录不存在，已跳过：{root}")
                continue
            for path in iter_nfo_files(root):
                if is_excluded(path, self.cfg.exclude_paths):
                    continue
                targets.append(path)
        if self.single_file:
            targets = [self.single_file] if self.single_file in targets or self.single_file.exists() else targets
        if self.cfg.max_files:
            targets = targets[: self.cfg.max_files]

        workers = max(1, int(self.cfg.concurrency or 1))
        pairs = [(path, next((r for r in self.cfg.roots if str(path).startswith(str(r))), path.parent))
                 for path in targets]
        logger.info(f"NFO 差异比对开始：待检查 {len(pairs)} 个文件，模式 {self.cfg.mode}"
                    + (f"，并发 {workers}" if workers > 1 else ""))

        def work(item: Tuple[Path, Path]) -> None:
            if self.cancel.is_set():
                return
            path, root_dir = item
            try:
                self.process(path, root_dir)
            except Exception as exc:
                self.report.bump("failed")
                self.report.add_error(f"{path}：{exc}")
                logger.error(f"处理失败：{path}（{exc}）")

        if workers > 1 and len(pairs) > 1:
            # 主要收益在网络 I/O：图片下载、TMDB / fanart 查询、本地哈希都能并行起来。
            # 共享状态（Report / 指纹清单 / 限速器）都已加锁，见各自的 bump/tally/add_* 入口。
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nfogapfill") as pool:
                for index, _ in enumerate(pool.map(work, pairs), 1):
                    if index % 200 == 0:
                        logger.info(f"进度 {index}/{len(pairs)}")
        else:
            for index, item in enumerate(pairs, 1):
                if self.cancel.is_set():
                    logger.info("收到停止信号，提前结束本轮")
                    break
                work(item)
                if index % 200 == 0:
                    logger.info(f"进度 {index}/{len(pairs)}")

        self.manifest.save()
        self.report.finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.report.calls = getattr(self.provider, "calls", 0)
        self.report.retried = getattr(self.provider, "retries", 0)
        logger.info(f"NFO 差异比对结束：扫描 {self.report.scanned}，写入 {self.report.changed_files}，"
                    f"无差异 {self.report.untouched}；图片检查 {self.report.images_scanned}，"
                    f"写入 {self.report.images_written}"
                    + (f"；网络重试 {self.report.retried} 次" if self.report.retried else ""))
        if self.report.legacy_alias:
            logger.warning(
                f"发现 {self.report.legacy_alias} 个旧版残留的 seasonNN-poster.jpg（剧集目录下）。"
                f"新版只在季目录内写 poster.jpg，这些旧文件可自行删除 —— 例如："
                f"find <媒体库> -maxdepth 3 -name 'season*-poster.jpg' -delete")
        if self.report.unresolved >= 5:
            logger.warning(
                f"本轮有 {self.report.unresolved} 个条目取不到在线数据"
                f"（已自动重试 {self.report.retried} 次）。若日志多为 SSL 握手超时/连接重置，"
                f"建议在 MoviePilot 里配置 PROXY_HOST 代理 —— 国内直连 api.themoviedb.org 不稳定")
        return self.report

    def scrub_when_unresolved(self, nfo: NfoFile, rel: str, root_dir: Path,
                              fields: List[str], locked: Optional[bool],
                              locked_names: set) -> None:
        """拿不到在线数据时，也要把文件里的历史脏值清掉。

        以前这里直接 return —— 于是「在线取不到 + 本地有脏值」的条目会永远留着
        `{'id': 12, 'name': '冒险'}` 这种乱码，用户会觉得「升级了也修不好」。
        脏值不是内容，删它不会丢任何信息（同标签里的正常值一律保留）。
        """
        tags = [(name,) + SYNONYM_TAGS.get(name, ())
                for name in fields if name.casefold() not in locked_names]
        total = sum(count_junk_elements(nfo.root, group) for group in tags)
        if not total:
            return
        if self.cfg.mode == "report" or self.cfg.dry_run:
            logger.info(f"[预演] {rel}：将清理 {total} 处历史脏值（本次不写盘）")
            return
        if locked is True:
            logger.warning(f"{rel}：条目被 <lockdata> 锁定，但其中的历史脏值是本插件旧版写坏的，"
                           f"仍会清理（原文件已备份）")
        removed = sum(purge_junk_elements(nfo.root, group) for group in tags)
        if removed:
            self.report.bump("scrubbed", removed)
            self.report.bump("changed_files")
            logger.info(f"{rel}：清理历史脏值 {removed} 处（本条目取不到在线数据）")
            write_nfo_file(nfo, (self.cfg.backup_dir if self.cfg.backup else None), root_dir)

    def forced_type(self, root: Path) -> Optional[str]:
        """该目录是否被 #电影 / #电视剧 限定了类型；没限定返回 None。"""
        if not self.cfg.root_types:
            return None
        key = str(root)
        if key in self.cfg.root_types:
            return self.cfg.root_types[key]
        normalized = key.replace("\\", "/").casefold()      # 容错大小写与斜杠方向
        for candidate, forced in self.cfg.root_types.items():
            if candidate.replace("\\", "/").casefold() == normalized:
                return forced
        return None

    def process(self, path: Path, root_dir: Path) -> None:
        nfo = load_nfo(path)
        if not nfo:
            return
        rel = str(path)
        try:
            rel = str(path.relative_to(root_dir))
        except ValueError:
            pass

        # 目录被 #电影 / #电视剧 限定时，类型不符的 NFO 直接跳过
        forced = self.forced_type(root_dir)
        if not type_allowed(forced, nfo.media_type):
            self.report.bump("skipped_type")
            logger.debug(f"{rel}：所在目录被限定为「{TYPE_TAG_CN.get(forced or '', forced)}」，"
                         f"与 NFO 类型 {nfo.media_type} 不符，跳过")
            return

        self.report.bump("scanned")

        managed = MANAGED_FIELDS.get(nfo.media_type, [])
        if self.cfg.only_fields:
            managed = [f for f in managed if f in self.cfg.only_fields]

        locked = get_locked_fields(nfo.root) if self.cfg.respect_lock else None
        locked_names = {f.casefold() for f in locked} if isinstance(locked, set) else set()

        remote, source = self.fetch_remote(nfo)
        if not remote:
            self.report.bump("unresolved")
            self.report.add_error(f"{rel}：{source}")
            logger.warning(f"取不到在线数据，保持原样：{rel}（{source}）")
            # 字段本身没法比对，但历史脏值仍然要清 —— 否则这类条目会永远带着乱码
            self.scrub_when_unresolved(nfo, rel, root_dir, managed, locked, locked_names)
            return

        plan: List[Tuple[str, bool, List[str]]] = []   # (字段名, 是否整体替换, 要写入的值)
        for name in managed:
            kind = FIELD_KINDS.get(name, "text")
            local_raw = read_local_values(nfo, name)
            # 本地遗留的对象字面量脏值不能算「内容」—— 它们会被媒体服务器显示成乱码
            junk_local = [v for v in local_raw if looks_like_object_repr(v)]
            local_vals = [v for v in local_raw if not looks_like_object_repr(v)]
            remote_vals = self.sanitize_remote(name, to_str_list(remote.get(name)))

            junk_syn = count_junk_elements(nfo.root, SYNONYM_TAGS.get(name, ()))
            is_purge = bool(junk_local or junk_syn)
            if is_purge:
                # 即使去掉脏值后与在线一致，也必须整体重写一遍才能清掉它们（否则会永远留着）。
                # 在线没数据时就用本地剩下的正常值重写，避免把正常内容一起清空。
                verdict, action = DIFF, REPLACE
                write_vals = remote_vals or local_vals
                self.report.bump("scrubbed", len(junk_local))
                logger.info(f"{rel}：{name} 有 {len(junk_local) + junk_syn} 处历史脏值"
                            f"（同义标签 {junk_syn} 处），将整体重写清除")
            else:
                verdict, action = compare(kind, local_vals, remote_vals)
                write_vals = remote_vals

            self.report.tally("counts", verdict)
            if action == SKIP:
                continue

            is_locked = locked is True or name.casefold() in locked_names
            if is_locked and not is_purge:
                applied, do_write = "跳过（NFO 字段锁定）", False
            elif self.cfg.mode == "report":
                # 带上「应为……」是为了让详情页在只报告模式下也能显示「将要修改哪些文件」
                applied, do_write = f"仅报告（应为{action}）", False
            elif is_purge:
                # 脏值不是「内容」：gapfill（只补缺失）、「保护字段」、乃至 <lockdata> 锁
                # 都不该挡住清理 —— 这些脏值本来就是本插件旧版写坏的，
                # 锁保护的是用户/其它工具的内容，不该保护我们自己的 bug 产物。
                # 写盘前会照常备份。
                applied = "清理脏值（条目被锁定）" if is_locked else "清理脏值"
                do_write = True
                if is_locked:
                    logger.warning(f"{rel}：{name} 含历史脏值（本插件旧版写坏的），"
                                   f"即使条目被锁定也一并清理，原文件已备份")
            elif self.cfg.mode == "gapfill" and action == REPLACE:
                applied, do_write = "跳过（gapfill 只补缺失）", False
            elif self.cfg.mode != "force" and action == REPLACE and name in self.cfg.protect_fields:
                applied, do_write = "跳过（受保护字段）", False
            elif action == FILL:
                applied, do_write = FILL, True
            else:
                applied, do_write = REPLACE, True

            self.report.tally("applied", applied)
            if is_locked and not do_write:
                self.report.bump("skipped_locked")
            self.record(rel, nfo.media_type, name, verdict, applied, local_vals, remote_vals)
            if do_write:
                plan.append((name, action == REPLACE, write_vals))

        pending_images = self.process_images(nfo, rel, root_dir)

        if not plan and not pending_images:
            self.report.bump("untouched")
            return
        if self.cfg.dry_run:
            if plan:
                logger.info(f"[预演] {rel} 将更新 {len(plan)} 个字段：{', '.join(p[0] for p in plan)}")
            return
        if not plan:
            return

        # 注意：写入用比对/过滤之后的值，绝不能再去 remote 里取原始值 ——
        # 那样护栏就形同虚设（早期版本正是这里又把脏值写了回去）
        for name, replace, values in plan:
            scrubbed = write_local_values(nfo, name, values, replace=replace)
            if scrubbed:
                self.report.bump("scrubbed", scrubbed)
                logger.info(f"{rel}：{name} 顺带清掉 {scrubbed} 处同义标签里的历史脏值")
        write_nfo_file(nfo, (self.cfg.backup_dir if self.cfg.backup else None), root_dir)
        self.report.bump("changed_files")
        logger.info(f"已更新 {rel}：{', '.join(p[0] for p in plan)}")

    # ── 图片 ────────────────────────────────────────────────────────
    def fetch_remote_images(self, nfo: NfoFile, kinds: set) -> Dict[str, str]:
        if not kinds or not hasattr(self.provider, "fetch_images"):
            return {}
        root = nfo.root
        mtype = nfo.media_type
        tmdb_id, _ = self.resolve_tmdb_id(nfo)
        if not tmdb_id:
            return {}
        season = episode = None
        if mtype in ("season", "episodedetails"):
            season, episode = self.resolve_season_episode(nfo, mtype)
        try:
            return self.provider.fetch_images(tmdb_id, mtype, season=season,
                                              episode=episode, kinds=kinds) or {}
        except Exception as exc:
            logger.warning(f"获取在线图片列表失败：{nfo.path}（{exc}）")
            return {}

    def process_images(self, nfo: NfoFile, rel: str, root_dir: Path) -> int:
        """比对/补齐该 NFO 对应的图片，返回「需要写盘」的目标数（演练模式下也算）。"""
        if self.cfg.image_mode == IMG_OFF:
            return 0
        # 季号必须与「取图用的季号」用同一套解析，否则会写出 season00 这种错名
        season = None
        if nfo.media_type in ("season", "episodedetails"):
            season, _ = self.resolve_season_episode(nfo, nfo.media_type)
        targets = image_targets(nfo, self.cfg.image_kinds, season=season)
        if not targets:
            return 0
        # 旧版会把季海报在剧集根目录另存一份 seasonNN-poster.jpg；新版不再写，
        # 这里只做「检测 + 提示」，绝不擅自删除用户库里的文件
        if nfo.media_type == "season" and season is not None:
            try:
                legacy = nfo.path.parent.parent / f"season{int(season):02d}-poster.jpg"
            except (TypeError, ValueError):
                legacy = None
            if legacy is not None and legacy.exists():
                self.report.bump("legacy_alias")
                if legacy.parent not in self._legacy_seen:
                    self._legacy_seen.add(legacy.parent)
                    logger.warning(f"检测到旧版写法残留的季海报：{legacy} —— "
                                   f"新版只写「季目录/poster.jpg」，这个文件可自行删除")
        urls = self.fetch_remote_images(nfo, {spec.kind for spec, _ in targets})
        if not urls:
            # 一季可能在线什么素材都没有。以前这里直接返回什么都不记，
            # 于是「该季海报缺失」在输出里完全看不出来 —— 现在明确标注（且绝不回退）。
            if nfo.media_type == "season" and "poster" in self.cfg.image_kinds:
                self.report.bump("images_missing")
                logger.info(f"{rel}：该季在线没有任何图片素材，季目录内不会写 poster.jpg"
                            f"（不回退其它季或剧集海报）")
                self.__image_change(rel, "未比对", "跳过（在线无此图）",
                                    "[图片] poster → poster.jpg", "该季缺海报，且不允许回退", "")
            return 0

        actionable = 0
        locked = get_locked_fields(nfo.root) if self.cfg.respect_lock else None
        locked_names = {f.casefold() for f in locked} if isinstance(locked, set) else set()
        cache: Dict[str, Optional[bytes]] = {}     # 同一 URL 本轮只下载一次（别名文件共用）
        for spec, path in targets:
            label = f"[图片] {spec.kind} → {path.name}" + ("（别名）" if spec.alias else "")
            url = urls.get(spec.kind)
            if not url:
                # 在线没有这张图。**明确标记、绝不回退** ——
                # 不能用「剧集海报」或「别的季的海报」来顶替某一季的海报。
                if spec.kind == "poster" and nfo.media_type == "season":
                    self.report.bump("images_missing")
                    logger.info(f"{rel}：该季在线没有「海报」，未写入 {path}"
                                f"（不回退其它季或剧集海报）")
                    self.__image_change(rel, "未比对", "跳过（在线无此图）", label,
                                        "该季缺海报，且不允许回退", "")
                continue
            self.report.bump("images_scanned")

            # Kodi 的 lockdata 表示「整个条目不许改」，lockedfields 可按字段名锁单张图
            if locked is True or spec.kind.casefold() in locked_names:
                self.report.bump("skipped_locked")
                self.__image_change(rel, "未比对", "跳过（NFO 锁定）", label,
                                    "lockdata / lockedfields", url)
                continue

            # 指纹清单能证明「本地就是这张在线图」→ 零下载跳过（稳态下几乎不产生流量）
            if self.manifest.matches(path, url):
                self.__image_change(rel, SAME, SKIP, label, "与在线一致（指纹匹配）", url)
                continue

            exists = path.exists()
            local_digest = sha256_file(path) if exists else None

            if self.cfg.image_mode == IMG_MISSING and exists:
                self.__image_change(rel, "未比对", "跳过（仅补缺失）", label,
                                    f"已存在 {path.stat().st_size} 字节", url)
                continue

            if url not in cache:
                reader = getattr(self.provider, "read_image", None)
                cache[url] = reader(url) if callable(reader) else None
            data = cache[url]
            if not data:
                self.report.add_error(f"{rel}：图片下载失败（{spec.kind}）{url}")
                continue

            digest = hashlib.sha256(data).hexdigest()
            if local_digest == digest:
                self.manifest.record(path, url, digest, len(data))
                self.__image_change(rel, SAME, SKIP, label, "与在线一致", url)
                continue

            verdict = REMOTE_ONLY if not exists else DIFF
            action = FILL if not exists else REPLACE
            local_desc = "（缺失）" if not exists else f"{path.stat().st_size} 字节，与在线不同"
            actionable += 1

            if self.cfg.mode == "report":
                self.__image_change(rel, verdict, f"{action}（仅报告）", label, local_desc, url)
            elif self.cfg.mode == "gapfill" and action == REPLACE:
                self.__image_change(rel, verdict, "跳过（gapfill 只补缺失）", label, local_desc, url)
            elif self.cfg.dry_run:
                self.__image_change(rel, verdict, f"{action}（演练）", label, local_desc, url)
            else:
                write_image_bytes(path, data,
                                  self.cfg.backup_dir if self.cfg.backup else None, root_dir)
                self.manifest.record(path, url, digest, len(data))
                self.report.bump("images_written")
                self.report.bump("image_bytes", len(data))
                self.__image_change(rel, verdict, action, label, local_desc, url)
                logger.info(f"图片{action}：{path}")
        return actionable

    def __image_change(self, rel: str, verdict: str, action: str, field: str,
                       local: str, remote: str) -> None:
        self.report.tally("image_counts", verdict)
        self.report.tally("image_applied", action)
        if len(self.report.changes) >= self.cfg.report_limit:
            return
        self.report.add_change(Change(
            nfo=rel, media_type="图片", field=field, verdict=verdict, action=action,
            local=local[:200], remote=remote[:200]), self.cfg.report_limit)

    def record(self, rel: str, media_type: str, name: str, verdict: str,
               action: str, local_vals: List[str], remote_vals: List[str]) -> None:
        self.report.add_change(Change(
            nfo=rel, media_type=media_type, field=name, verdict=verdict, action=action,
            local=" ｜ ".join(local_vals)[:200], remote=" ｜ ".join(remote_vals)[:200],
        ), self.cfg.report_limit)


# ══════════════════════════════════════════════════════════════════════
# MoviePilot 插件
# ══════════════════════════════════════════════════════════════════════
class NfoGapFill(_PluginBase):  # type: ignore[misc]
    # 插件名称
    plugin_name = "NFO 与图片差异比对"
    # 插件描述
    plugin_desc = ("比对本地 NFO 与海报/背景图：缺失补齐、不一致替换、一致跳过；"
                   "支持字段保护与 NFO 锁定。")
    # 插件图标
    plugin_icon = "NfoGapFill.png"
    # 插件版本
    plugin_version = PLUGIN_VERSION
    # 插件作者
    plugin_author = "MC星云"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "nfogapfill_"
    # 加载顺序
    plugin_order = 21
    # 可使用的用户级别
    user_level = 1

    # 详情页表格里的类型显示名
    KIND_CN = {"movie": "电影", "tvshow": "剧集", "season": "季", "episodedetails": "单集"}

    # 运行态
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _concurrency: int = 4
    _mode: str = "sync"
    _paths: str = ""
    _exclude_paths: str = ""
    _protect_fields: str = ""
    _respect_lock: bool = True
    _dry_run: bool = False
    _backup: bool = True
    _tmdb_api_key: str = ""
    _language: str = "zh-CN"
    _cert_country: str = "US"
    _cast_limit: str = "20"
    _notify: bool = True
    _image_mode: str = IMG_SYNC
    _image_kinds: Any = IMAGE_KINDS          # 统一由 normalize_image_kinds 收敛成列表
    _image_quality: str = "standard"
    _event: Event = Event()
    _timer: Optional[threading.Timer] = None

    # ── 生命周期 ───────────────────────────────────────────────────
    def init_plugin(self, config: Optional[dict] = None) -> None:
        repair: Dict[str, Any] = {}

        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._cron = (config.get("cron") or "").strip()
            self._concurrency = max(1, min(16, self.__int(config.get("concurrency"), 4)))
            self._mode = config.get("mode") or "sync"
            self._paths = config.get("paths") or ""
            self._exclude_paths = config.get("exclude_paths") or ""
            self._protect_fields = config.get("protect_fields") or ""
            self._respect_lock = bool(config.get("respect_lock", True))
            self._dry_run = bool(config.get("dry_run"))
            self._backup = bool(config.get("backup", True))
            self._tmdb_api_key = (config.get("tmdb_api_key") or "").strip()
            self._language = config.get("language") or "zh-CN"
            self._cert_country = (config.get("cert_country") or "US").strip()
            self._cast_limit = str(config.get("cast_limit") or "20")
            self._notify = bool(config.get("notify", True))
            self._image_mode = config.get("image_mode") or IMG_SYNC
            # 图片类型：收敛成一个干净的列表；若与存下来的值不同就顺手修正回去，
            # 否则界面上会一直挂着历史遗留的怪值（例如旧版复选框存下的 false）
            kinds = normalize_image_kinds(config.get("image_kinds"))
            self._image_kinds = list(IMAGE_KINDS) if kinds is None else kinds
            if config.get("image_kinds") != self._image_kinds:
                repair["image_kinds"] = self._image_kinds
            self._image_quality = config.get("image_quality") or "standard"

        self.stop_service()

        # 把历史遗留的非法配置修正回宿主的配置库，避免界面一直显示脏值
        if repair:
            try:
                logger.info(f"已自动修正配置：{repair}")
                self.update_config(repair)
            except Exception as exc:
                logger.warning(f"回写修正后的配置失败（不影响本次运行）：{exc}")

        if self._onlyonce:
            logger.info("NFO 差异比对：立即运行一次")
            self._event.clear()
            self._timer = threading.Timer(3, self.__run)
            self._timer.daemon = True
            self._timer.start()
            self._onlyonce = False
            self.__save_config()

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self) -> None:
        """退出插件，取消未执行的即时任务与运行中的循环。"""
        try:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._event.set()
            self._event = Event()
        except Exception as exc:
            logger.warning(f"停止服务时出现异常：{exc}")

    # ── 界面 ───────────────────────────────────────────────────────
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "onlyonce", "label": "保存后立即运行一次"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify", "label": "完成后发送通知"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "mode",
                                    "label": "处理模式",
                                    "items": [
                                        {"title": "不一致则替换（缺失补齐 + 不同替换 + 相同跳过）", "value": "sync"},
                                        {"title": "只补缺失（不动任何已有内容）", "value": "gapfill"},
                                        {"title": "只报告差异（不写入任何文件）", "value": "report"},
                                        {"title": "强制全部覆盖（等同官方插件 force_all，慎用）", "value": "force"},
                                    ]}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VCronField", "props": {
                                    "model": "cron", "label": "执行周期（留空 = 每周日凌晨 3 点跑一次）",
                                    "placeholder": "留空 = 每周一次；也可填 5 位 cron，如 0 3 * * * 表示每天 03:00"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "concurrency",
                                    "label": "并发数（加快比对速度）",
                                    "items": [
                                        {"title": "1 — 顺序执行（最省资源）", "value": "1"},
                                        {"title": "4 — 推荐（默认）", "value": "4"},
                                        {"title": "6", "value": "6"},
                                        {"title": "8 — 网络很好时可以试", "value": "8"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "「并发数」决定同时处理多少个 NFO：主要收益在网络等待（图片下载、"
                                         "TMDB 与 fanart.tv 查询），对本地磁盘与 CPU 压力很小，"
                                         "所以开着基本只有好处。并发时 TMDB 的请求速率会按比例放宽"
                                         "（上限约 12 请求/秒，仍远低于其限制），单线程则维持原来的 4 请求/秒。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "dry_run", "label": "演练模式（只记录将要修改的内容，不写盘）"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "respect_lock", "label": "尊重 NFO 内的 lockdata / lockedfields"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {
                                    "model": "backup", "label": "写入前备份原 NFO / 图片到 .nfo-backup"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "cast_limit",
                                    "label": "演员写入上限",
                                    "items": [
                                        {"title": "10 位（文件更小）", "value": "10"},
                                        {"title": "20 位（默认）", "value": "20"},
                                        {"title": "30 位", "value": "30"},
                                        {"title": "50 位", "value": "50"},
                                        {"title": "全部（按 TMDB 返回的全写，NFO 会明显变大）", "value": "0"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "image_mode",
                                    "label": "图片处理",
                                    "items": [
                                        {"title": "缺失补齐 + 不一致替换（推荐）", "value": "sync"},
                                        {"title": "只补缺失图片（不比对、不替换已有图）", "value": "missing"},
                                        {"title": "完全不处理图片", "value": "off"},
                                    ]}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "image_quality",
                                    "label": "图片画质",
                                    "items": [
                                        {"title": "标准（海报 w780 / 背景 w1280，省空间）", "value": "standard"},
                                        {"title": "原始尺寸（最清晰，体积明显更大）", "value": "original"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "image_kinds",
                                    "label": "处理的图片类型（可多选）",
                                    "multiple": True,
                                    "chips": True,
                                    "items": [
                                        {"title": "海报（poster.jpg）", "value": "poster"},
                                        {"title": "背景图（backdrop.jpg + fanart.jpg）", "value": "backdrop"},
                                        {"title": "徽标（logo.png）", "value": "logo"},
                                        {"title": "剧集缩略图（单集剧照 → 与视频同名的 .jpg）", "value": "thumb"},
                                        {"title": "横幅图（banner.jpg）", "value": "banner"},
                                        {"title": "光盘图（disc.png）", "value": "disc"},
                                        {"title": "透明艺术图（clearart.png）", "value": "clearart"},
                                        {"title": "横版缩略图（landscape.jpg）", "value": "landscape"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "勾选的类型会写成什么（命名与 MP / Kodi / Jellyfin 约定一致）："
                                         "① 海报 → poster.jpg；"
                                         "② 背景图 → backdrop.jpg，并额外写一份 fanart.jpg（Kodi/Emby 认这个名）；"
                                         "③ 徽标 → logo.png；"
                                         "④ 剧集缩略图 → 单集剧照，写成与该集视频同名的 .jpg（要求该集存在 NFO）；"
                                         "⑤ 横幅图 → banner.jpg；⑥ 光盘图 → disc.png；"
                                         "⑦ 透明艺术图 → clearart.png；⑧ 横版缩略图 → landscape.jpg。"
                                         "季目录也会写 banner.jpg 与 landscape.jpg（与剧集根目录同图）。"
                                         "季海报不单独成项，跟随「海报」一起处理：**只写该季目录下的 poster.jpg**，"
                                         "不会写到剧集根目录、也不会把各季海报堆在一起；"
                                         "某一季在线没有海报时会明确标注缺失，绝不用其它季或剧集海报顶替。"
                                         "全部不选 = 不处理任何图片（等于关掉图片处理，不会偷偷回退成全选）。"
                                         "判定沿用与 NFO 相同的「一致才跳过」逻辑：先比对本地图与在线图，"
                                         "一致不动、不一致才替换 —— 官方「媒体库刮削」只判断文件在不在，"
                                         "所以低清图、错图永远不会被换掉。首次运行需要下载比对以建立指纹，"
                                         "之后靠指纹零下载判定。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "数据来源分两路：海报 / 背景图 / 徽标 / 剧照来自 TMDB；"
                                         "光盘图 / 横幅图 / 透明艺术图 / 横版缩略图 **只有 fanart.tv 有**，"
                                         "其 API Key 会自动沿用 MoviePilot 里配置的 FANART_API_KEY"
                                         "（MP 自带默认值，所以一般什么都不用填），"
                                         "语言偏好也跟随 MP 的 FANART_LANG。"
                                         "这几类需要 TMDB API Key 走直连（宿主刮削通道拿不到）。"
                                         "注意 fanart.tv 是社区共建，冷门影片这几类可能就是没有 —— 那不是故障。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "paths",
                                    "label": "媒体库目录（每行一个；行尾可加 #电影 / #电视剧 限定类型）",
                                    "rows": 5,
                                    "placeholder": "/media/link/电影#电影\n"
                                                   "/media/link/电视剧#电视剧\n"
                                                   "/media/link/其它    （不加 # 则电影和电视剧都处理）"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "「媒体库目录」的行尾可以加 #电影 或 #电视剧 来限定这个目录只处理对应类型，"
                                         "例如 /media/link/电影#电影 就只会处理电影，"
                                         "该目录下即使有剧集 NFO 也会被跳过（写入 #电视剧 同理，"
                                         "会处理剧集及其季、单集）。不加后缀则该目录下两种类型都处理。"
                                         "别名也认：movie / movies / 影片、tv / tvshow / series / 剧集。"
                                         "跳过数量会在运行报告的「按目录的『#类型』限定跳过」里体现。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "exclude_paths", "label": "排除路径", "rows": 2,
                                    "placeholder": "每行一个路径片段，命中即跳过"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "protect_fields", "label": "保护字段（只补不换）",
                                    "placeholder": "逗号分隔，例如 plot,tagline,actor"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "tmdb_api_key",
                                    "label": "TMDB API Key（留空 = 自动使用 MoviePilot 里配置的 Key）",
                                    "placeholder": "通常留空即可；只有在想用另一个 Key 时才填"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "language", "label": "元数据语言",
                                    "items": [
                                        {"title": "简体中文", "value": "zh-CN"},
                                        {"title": "繁體中文", "value": "zh-TW"},
                                        {"title": "English", "value": "en-US"},
                                        {"title": "日本語", "value": "ja-JP"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "「保护字段」= 照常参与比对、缺失也会补，但**永远不会覆盖你已有的内容**。"
                                         "想保住手工润色的简介、自己写的一句话宣传语，就把对应字段填进来。"
                                         "字段名写 NFO 的标签名（小写、逗号分隔）："
                                         "电影可用 title, originaltitle, plot, tagline, year, premiered, "
                                         "runtime, mpaa, rating, genre, studio, country, director, credits, actor；"
                                         "剧集 tvshow 可用 title, plot, tagline, year, premiered, runtime, mpaa, "
                                         "rating, genre, studio, country, actor；"
                                         "单集可用 title, plot, aired, rating, season, episode, director, credits, actor；"
                                         "季可用 title, plot, premiered, season。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "「TMDB API Key」留空时会自动读取 MoviePilot 里已配置的 Key，"
                                         "网络代理也会自动沿用 MoviePilot 的 PROXY_HOST —— "
                                         "所以这里通常什么都不用填。只有当 MoviePilot 里也没有可用的 Key 时，"
                                         "才会退回宿主的刮削通道（该通道拿不到徽标、剧集缩略图和季海报）。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "cert_country",
                                    "label": "分级地区码（决定 mpaa 取哪个地区的分级）",
                                    "items": [
                                        {"title": "美国 — PG-13 / R（默认）", "value": "US"},
                                        {"title": "中国大陆 — 无官方分级，通常取不到值", "value": "CN"},
                                        {"title": "中国香港 — IIA / IIB / III", "value": "HK"},
                                        {"title": "中国台湾 — 普遍级 / 保护级 / 辅15", "value": "TW"},
                                        {"title": "日本 — G / PG12 / R15+", "value": "JP"},
                                        {"title": "韩国 — ALL / 12 / 15 / 19", "value": "KR"},
                                        {"title": "英国 — 12 / 15 / 18", "value": "GB"},
                                        {"title": "德国 — FSK 12 / FSK 16", "value": "DE"},
                                        {"title": "法国 — Tous publics / -12 / -16", "value": "FR"},
                                        {"title": "意大利 — T / VM14 / VM18", "value": "IT"},
                                        {"title": "西班牙 — APTA / 12 / 16 / 18", "value": "ES"},
                                        {"title": "澳大利亚 — PG / M / MA15+", "value": "AU"},
                                        {"title": "加拿大 — PG / 14A / 18A", "value": "CA"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                                 "text": "「分级地区码」怎么填：NFO 里的 <mpaa> 存的是影视分级（PG-13、R 这类），"
                                         "而 TMDB 上同一部片在不同国家的分级并不一样，这个配置就决定取哪一份 —— "
                                         "填 US 得到 PG-13 / R，填 GB 得到 12 / 15 / 18，填 JP 得到 G / PG12 / R15+。"
                                         "注意中国大陆没有官方影视分级体系，填 CN 通常取不到值；"
                                         "若所选地区恰好缺该片的分级，会自动退回到任意有值的地区，不会留空。"
                                         "下拉里只列了常用地区；万一需要别的地区，"
                                         "可以把插件配置里的 cert_country 直接改成对应的两位 ISO 国家码。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {
                                    "type": "info", "variant": "tonal"},
                                 "text": "「不一致则替换」会修正与 TMDB 不同的字段（例如过时的简介、错误的年份）。"
                                         "想保住手工润色的内容，就把它填进「保护字段」。"}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VAlert", "props": {"type": "warning", "variant": "tonal"},
                                 "text": "建议先用「只报告差异 + 演练模式」跑一轮：运行结束后本页会列出«将要修改哪些文件»，"
                                         "对着清单确认无误，再切换为「不一致则替换」正式执行。"}]},
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "mode": "sync",
            "cron": "",              # 留空 = 每周日凌晨 3 点一次（见 WEEKLY_CRON）
            "concurrency": "4",
            "dry_run": False,
            "respect_lock": True,
            "backup": True,
            "paths": "",
            "exclude_paths": "",
            "protect_fields": "",
            "tmdb_api_key": "",
            "language": "zh-CN",
            "cert_country": "US",
            "cast_limit": "20",
            "image_mode": IMG_SYNC,
            "image_kinds": list(IMAGE_KINDS),
            "image_quality": "standard",
        }

    def get_page(self) -> List[dict]:
        """详情页主视图 =「本次修改了哪些文件」的表格。

        完整文本报告（含每条跳过的原因）仍然写进插件数据目录的 last_report.txt，
        需要深挖时去那里翻；页面上只保留最需要一眼看到的改动清单。
        """
        data = self.__load_changes()
        if not data:
            return self.__page_fallback()

        rows = data.get("rows") or []
        changed = int(data.get("changed_files") or 0)
        images_written = int(data.get("images_written") or 0)
        scanned = int(data.get("scanned") or 0)
        images_scanned = int(data.get("images_scanned") or 0)
        errors = [str(item) for item in (data.get("errors") or [])]
        dry = bool(data.get("dry_run"))
        preview = dry or data.get("mode") == "report"
        verb = "将要修改" if preview else "本次修改"

        # 明细用纯文本：VDataTable 在本环境实测只渲染出分页条、表体一行都不显示
        # （分页条能报出「1-10 of 29」，说明数据到了，是渲染问题），
        # 而只读文本域是验证过稳定可用的 —— 先保证「能读到内容」。
        lines: List[str] = []
        if rows:
            lines.append(f"{verb} {changed} 个 NFO、{images_written} 张图片"
                         f"（按文件列出，共 {len(rows)} 项）")
            for row in rows:
                kind = row.get("kind") or ""
                kind_cn = self.KIND_CN.get(kind, kind)
                lines.append("")
                lines.append(f"▍{row.get('file', '')}" + (f"　{kind_cn}" if kind_cn else ""))
                lines.append(f"    字段：{row.get('fields') or '—'}")
                images = row.get("images") or "—"
                if images != "—":
                    lines.append(f"    图片：{images}")
        else:
            lines.append(f"本次没有需要修改的内容"
                         f"（已扫描 {scanned} 个 NFO / {images_scanned} 张图片）。")
        if errors:
            lines.append("")
            lines.append(f"—— 另有 {len(errors)} 条无法比对 / 失败 ——")
            lines.extend(errors)

        blocks: List[dict] = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [
                    {"component": "VAlert", "props": {
                        "type": "info", "variant": "tonal",
                        "text": f"NFO 与图片差异比对 v{PLUGIN_VERSION}"
                                f"　模式：{data.get('mode', self._mode)}"
                                f"　图片：{self._image_mode}"
                                f"　上次运行：{data.get('finished', '未知')}"
                                + ("　（演练中，未写盘）" if dry else "")}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [
                    {"component": "VAlert", "props": {
                        "type": "success" if rows else "warning", "variant": "tonal",
                        "text": (f"{verb} {changed} 个 NFO、{images_written} 张图片"
                                 f"（本轮共扫描 {scanned} 个 NFO / {images_scanned} 张图片，"
                                 f"其余均与在线一致或被规则跳过）"
                                 + (f"，另有 {len(errors)} 条无法比对 / 失败"
                                    f"（明细见下方清单末尾）" if errors else "")
                                 if rows else
                                 f"本次没有需要修改的内容"
                                 f"（扫描 {scanned} 个 NFO / {images_scanned} 张图片，全部已是最新）")}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [
                    {"component": "VTextarea", "props": {
                        "model": "changes_text",
                        "modelValue": "\n".join(lines),
                        "rows": 20, "readonly": True, "no-resize": True,
                        "label": (f"{verb}的文件（共 {len(rows)} 项，可滚动查看）" if rows
                                  else "本次没有需要修改的内容")}}]},
            ]},
        ]

        # 失败明细已经附在上面清单的末尾，这里不再重复贴 ——
        # 之前在这里截断 90 个字符，会出现「图片下载失败（po」这种半句话
        blocks.append({"component": "VRow", "content": [
            {"component": "VCol", "props": {"cols": 12}, "content": [
                {"component": "VAlert", "props": {
                    "type": "info", "variant": "tonal",
                    "text": "清单只列「会写盘」的文件；被跳过的条目（NFO 锁定、保护字段、"
                            "gapfill 只补缺失、图片仅补缺失等）不在此列，"
                            "完整原因见插件数据目录下的 last_report.txt。"}}]},
        ]})
        return blocks

    def __page_fallback(self) -> List[dict]:
        """还没有结构化明细时（老版本遗留数据 / 明细写入失败）退回展示文本报告。"""
        text = self.__load_last_report() or "尚未运行过。保存配置时勾选「保存后立即运行一次」即可产生结果。"
        head = text.splitlines()
        return [
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VAlert", "props": {
                            "type": "info", "variant": "tonal",
                            "text": f"NFO 与图片差异比对 v{PLUGIN_VERSION}　模式：{self._mode}"
                                    f"　图片：{self._image_mode}"
                                    + ("　（演练中，不会写盘）" if self._dry_run else "")}}]},
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VAlert", "props": {
                            "type": "success" if head else "warning", "variant": "tonal",
                            "text": head[0] if head else "尚无运行记录"}}]},
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VTextarea", "props": {
                            "model": "report_text", "modelValue": text, "rows": 22, "readonly": True,
                            "label": "上次运行结果（完整报告同时保存在插件数据目录 last_report.txt）"}}]},
                ],
            },
        ]

    def get_command(self) -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if self._enabled and CronTrigger is not None:
            # 「执行周期」留空 = 每周执行一次（表单里默认就是空的，用户不需要懂 cron）
            cron = (self._cron or "").strip() or WEEKLY_CRON
            try:
                trigger = CronTrigger.from_crontab(cron)
            except Exception as exc:
                logger.error(f"cron 表达式无效（{cron}）：{exc}，已回退为每周一次（{WEEKLY_CRON}）")
                trigger = CronTrigger.from_crontab(WEEKLY_CRON)
            return [{
                "id": "NfoGapFill",
                "name": "NFO 差异比对与补齐",
                "trigger": trigger,
                "func": self.__run,
                "kwargs": {},
            }]
        return []

    def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        return None

    # ── 内部实现 ───────────────────────────────────────────────────
    def __save_config(self) -> None:
        try:
            self.update_config({
                "enabled": self._enabled,
                "onlyonce": False,
                "notify": self._notify,
                "mode": self._mode,
                "cron": self._cron,
                "concurrency": str(self._concurrency),
                "dry_run": self._dry_run,
                "respect_lock": self._respect_lock,
                "backup": self._backup,
                "paths": self._paths,
                "exclude_paths": self._exclude_paths,
                "protect_fields": self._protect_fields,
                "tmdb_api_key": self._tmdb_api_key,
                "language": self._language,
                "cert_country": self._cert_country,
                "cast_limit": self._cast_limit,
                "image_mode": self._image_mode,
                "image_kinds": self._image_kinds,
                "image_quality": self._image_quality,
            })
        except Exception as exc:
            logger.warning(f"保存插件配置失败：{exc}")

    def __report_file(self) -> Path:
        try:
            base = Path(self.get_data_path())
        except Exception:
            base = Path(__file__).parent
        base.mkdir(parents=True, exist_ok=True)
        return base / "last_report.txt"

    def __load_last_report(self) -> str:
        try:
            path = self.__report_file()
            return path.read_text(encoding="utf-8") if path.exists() else ""
        except Exception:
            return ""

    def __changes_file(self) -> Path:
        """结构化变更明细，供详情页表格渲染（与纯文本报告并列存放）。"""
        return self.__report_file().with_name("last_changes.json")

    def __load_changes(self) -> dict:
        try:
            path = self.__changes_file()
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def __manifest_file(self) -> Path:
        try:
            base = Path(self.get_data_path())
        except Exception:
            base = Path(__file__).parent
        base.mkdir(parents=True, exist_ok=True)
        return base / "image_manifest.json"

    def __build_provider(self):
        quality = self._image_quality if self._image_quality in IMG_SIZES else "standard"
        limit = self.__int(self._cast_limit, 20)
        # Key 与代理都自动沿用 MoviePilot 的配置（插件里已不再提供这两项的输入框）
        own_key = (self._tmdb_api_key or "").strip()
        key = own_key or str(mp_setting("TMDB_API_KEY", "") or "").strip()
        proxy = str(mp_setting("PROXY_HOST", "") or "").strip()
        if key:
            logger.info("TMDB 数据源：%s%s" % (
                "插件内单独配置的 API Key" if own_key else "自动读取 MoviePilot 中配置的 API Key",
                "，代理沿用宿主的" if proxy else ""))
            return TmdbProvider(key, self._language, proxy or None,
                                self._cert_country, limit, quality,
                                concurrency=self._concurrency)
        logger.warning("插件与 MoviePilot 都没有可用的 TMDB API Key，改用宿主刮削通道"
                       "（该通道只能取到海报与背景图，徽标 / 剧集缩略图 / 季海报将不可用）")
        return HostProvider(quality, limit)

    @staticmethod
    def __int(value: Any, default: int) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return default

    @staticmethod
    def __split_lines(text: str) -> List[str]:
        return [line.strip() for line in re.split(r"[\r\n]+", text or "") if line.strip()]

    @staticmethod
    def __split_set(text: str) -> set:
        return {item.strip().casefold() for item in re.split(r"[,\s]+", text or "") if item.strip()}

    def __image_kinds_set(self) -> set:
        """当前生效的图片类型集合（统一走 normalize_image_kinds 收敛）。"""
        return set(normalize_image_kinds(self._image_kinds) or [])

    def __run(self) -> None:
        try:
            roots, root_types = parse_root_specs(self.__split_lines(self._paths))
            if not roots:
                logger.warning("未配置任何媒体库目录，任务结束")
                return
            if root_types:
                logger.info("已限定目录类型：" + "，".join(
                    f"{item} → {TYPE_TAG_CN.get(forced, forced)}"
                    for item, forced in root_types.items()))
            cfg = EngineConfig(
                roots=roots,
                exclude_paths=self.__split_lines(self._exclude_paths),
                root_types=root_types,
                mode=self._mode if self._mode in ("report", "gapfill", "sync", "force") else "sync",
                protect_fields=self.__split_set(self._protect_fields),
                only_fields=set(),    # 插件已移除「字段白名单」（引擎与 CLI 的 --only 仍保留该能力）
                respect_lock=self._respect_lock,
                dry_run=self._dry_run,
                backup=self._backup,
                max_files=0,          # 插件不再提供单轮上限（引擎仍支持，CLI 用 --max-files）
                concurrency=self._concurrency,
                image_mode=(self._image_mode if self._image_mode in (IMG_OFF, IMG_MISSING, IMG_SYNC)
                            else IMG_SYNC),
                image_kinds=self.__image_kinds_set(),
                image_quality=(self._image_quality if self._image_quality in IMG_SIZES
                               else "standard"),
                manifest_path=self.__manifest_file(),
            )
            provider = self.__build_provider()
            self._event.clear()
            report = Engine(cfg, provider, cancel=self._event).run()

            text = report.to_text()
            try:
                self.__report_file().write_text(text, encoding="utf-8")
            except Exception as exc:
                logger.warning(f"写入报告失败：{exc}")
            try:
                self.save_data("nfogapfill_report", {
                    "scanned": report.scanned, "changed": report.changed_files,
                    "untouched": report.untouched, "unresolved": report.unresolved,
                    "finished": report.finished, "mode": report.mode,
                    "images_scanned": report.images_scanned,
                    "images_written": report.images_written,
                    "image_bytes": report.image_bytes,
                })
            except Exception:
                pass

            try:
                self.__changes_file().write_text(json.dumps({
                    "finished": report.finished, "mode": report.mode,
                    "dry_run": self._dry_run, "provider": report.provider,
                    "scanned": report.scanned, "changed_files": report.changed_files,
                    "unchanged": report.untouched,
                    "images_scanned": report.images_scanned,
                    "images_written": report.images_written,
                    "image_bytes": report.image_bytes,
                    "errors": report.errors[:15],
                    "rows": report.change_rows(),
                }, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception as exc:
                logger.warning(f"写入变更明细失败（详情页会退化为展示完整报告）：{exc}")

            if self._notify:
                self.__notify(report)
        except Exception as exc:
            logger.error(f"NFO 差异比对任务异常：{exc}")

    def __notify(self, report: Report) -> None:
        title = "【NFO 与图片差异比对】完成"
        text = (f"扫描 NFO {report.scanned}｜写入 {report.changed_files}｜无差异 {report.untouched}\n"
                f"字段：替换 {report.counts.get(REPLACE, 0)}｜补齐 {report.counts.get(FILL, 0)}"
                f"｜取不到在线数据 {report.unresolved}\n"
                f"图片：检查 {report.images_scanned}｜写入 {report.images_written}"
                f"（{report.image_bytes / 1048576:.1f} MB）"
                f"{'（演练，未写盘）' if self._dry_run else ''}")
        try:
            from app.schemas.types import NotificationType  # type: ignore
            self.post_message(mtype=NotificationType.Plugin, title=title, text=text)
        except Exception:
            try:
                self.post_message(title=title, text=text)
            except Exception as exc:
                logger.warning(f"发送通知失败：{exc}")


# ══════════════════════════════════════════════════════════════════════
# 命令行入口（与插件共用同一套引擎）
# ══════════════════════════════════════════════════════════════════════
def build_cli_provider(args) -> Any:
    if args.source == "file":
        if not args.cache:
            raise SystemExit("--source file 需要同时指定 --cache <json 路径>")
        return FileProvider(args.cache)
    if args.source == "host":
        return HostProvider(args.image_quality, args.cast_limit)
    if not args.api_key:
        raise SystemExit("--source tmdb 需要 --api-key，或设置环境变量 TMDB_API_KEY")
    return TmdbProvider(args.api_key, args.lang, args.proxy or None, args.cert_country,
                        args.cast_limit, args.image_quality)


def cli_main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="NfoGapFill",
        description="NFO 与图片元数据差异比对：缺失补齐、不一致替换、一致跳过",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  体检（只报告差异）  python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --mode report\n"
               "  离线演练            python NfoGapFill.py --root /media/link --source file --cache remote.json\n"
               "  正式执行            python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --mode sync --fix\n"
               "  含图片              ... --fix --image-mode sync\n"
               "\n注意：插件里图片处理默认开启（sync），CLI 里默认关闭（off），需显式指定。")
    parser.add_argument("--root", action="append", required=True,
                        help="媒体库目录，可重复指定；行尾可加 #电影 / #电视剧 限定该目录的类型")
    parser.add_argument("--source", choices=["tmdb", "host", "file"], default="tmdb",
                        help="在线数据来源：tmdb 直连 / host 宿主链路 / file 本地 JSON")
    parser.add_argument("--cache", default="", help="--source file 时的 JSON 路径")
    parser.add_argument("--mode", choices=["report", "gapfill", "sync", "force"], default="sync",
                        help="report 只报告 / gapfill 只补缺失 / sync 不同则替换（默认）/ force 全量覆盖")
    parser.add_argument("--fix", action="store_true", help="允许写入。不加则等价于 --mode report")
    parser.add_argument("--dry-run", action="store_true", help="打印将要修改的内容但不写盘")
    parser.add_argument("--protect", default="", help="保护字段（只补不换），逗号分隔，如 plot,tagline")
    parser.add_argument("--only", default="", help="只处理这些字段，逗号分隔")
    parser.add_argument("--exclude", default="", help="排除路径片段，逗号分隔")
    parser.add_argument("--api-key", default=None, help="TMDB API Key（默认读环境变量 TMDB_API_KEY）")
    parser.add_argument("--lang", default="zh-CN", help="元数据语言，默认 zh-CN")
    parser.add_argument("--proxy", default=None, help="代理，如 http://127.0.0.1:7890")
    parser.add_argument("--cert-country", default="US", help="分级地区码，默认 US")
    parser.add_argument("--cast-limit", type=int, default=20, help="演员写入上限，默认 20；0 = 全部写入")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="并发处理数（1 = 顺序；插件默认 4）")
    parser.add_argument("--max-files", type=int, default=0, help="单轮最多处理多少个 NFO")
    parser.add_argument("--no-backup", action="store_true", help="不备份原文件（不推荐）")
    parser.add_argument("--backup-dir", default="", help="备份目录，默认 <root>/.nfo-backup")
    parser.add_argument("--image-mode", choices=["off", "missing", "sync"], default="off",
                        help="图片处理：off 不处理（CLI 默认）/ missing 只补缺失 / sync 不一致则替换")
    parser.add_argument("--image-kinds", default="poster,backdrop,logo,thumb",
                        help="处理的图片类型，逗号分隔（默认四种全开）")
    parser.add_argument("--image-quality", choices=["standard", "original"], default="standard",
                        help="图片画质，默认 standard（海报 w780 / 背景图 w1280 / 徽标 w500）")
    parser.add_argument("--image-manifest", default="",
                        help="图片指纹清单路径，默认 <第一个媒体库目录>/.nfo-backup/image_manifest.json")
    parser.add_argument("--json", dest="json_out", default="", help="把完整报告写入 JSON")
    args = parser.parse_args(argv)

    import os
    args.api_key = args.api_key or os.environ.get("TMDB_API_KEY", "")
    roots, root_types = parse_root_specs(args.root, resolve=True)
    if not roots:
        raise SystemExit("--root 至少要给一个媒体库目录")
    for root in roots:
        if not root.is_dir():
            raise SystemExit(f"目录不存在：{root}")
    if root_types:
        print("目录类型限定：" + "，".join(
            f"{item} → {TYPE_TAG_CN.get(forced, forced)}" for item, forced in root_types.items()))
    if not args.fix:
        args.mode = "report"

    provider = build_cli_provider(args)
    image_kinds = {s.strip().casefold() for s in re.split(r"[,\s]+", args.image_kinds) if s.strip()}
    manifest_path = (Path(args.image_manifest).expanduser() if args.image_manifest
                     else roots[0] / ".nfo-backup" / "image_manifest.json")
    cfg = EngineConfig(
        roots=roots,
        exclude_paths=[s.strip() for s in re.split(r"[,\n]+", args.exclude) if s.strip()],
        root_types=root_types,
        mode=args.mode,
        protect_fields={s.strip().casefold() for s in re.split(r"[,\s]+", args.protect) if s.strip()},
        only_fields={s.strip().casefold() for s in re.split(r"[,\s]+", args.only) if s.strip()},
        dry_run=args.dry_run,
        backup=not args.no_backup,
        backup_dir=Path(args.backup_dir).expanduser() if args.backup_dir else roots[0] / ".nfo-backup",
        max_files=args.max_files,
        concurrency=max(1, args.concurrency),
        image_mode=args.image_mode,
        image_kinds=(image_kinds & set(IMAGE_KINDS)) or set(IMAGE_KINDS),
        image_quality=args.image_quality,
        manifest_path=manifest_path,
    )
    report = Engine(cfg, provider).run()
    print()
    print(report.to_text())
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "scanned": report.scanned, "untouched": report.untouched,
            "changed_files": report.changed_files, "skipped_locked": report.skipped_locked,
            "unresolved": report.unresolved, "failed": report.failed,
            "counts": report.counts, "errors": report.errors,
            "images_scanned": report.images_scanned,
            "images_written": report.images_written,
            "image_bytes": report.image_bytes,
            "image_counts": report.image_counts,
            "image_applied": report.image_applied,
            "changes": [c.__dict__ for c in report.changes],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入：{args.json_out}")
    return 0


if __name__ == "__main__":
    if IN_MOVIEPILOT:
        logger.info("检测到 MoviePilot 宿主环境，本文件应作为插件加载，而不是直接运行。")
    sys.exit(cli_main())
