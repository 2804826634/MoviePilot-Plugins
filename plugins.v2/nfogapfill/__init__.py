#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NfoGapFill —— NFO 元数据「差异比对 → 按需替换」工具（MoviePilot 插件 / 独立 CLI 双模式）

它解决什么问题
    MoviePilot 官方「媒体库刮削」插件的覆盖模式只有两档：
        · 不覆盖已有元数据   —— 只要字段非空就一律不动，不管它是不是错的/旧的
        · 覆盖所有元数据和图片 —— 连你手工润色的简介、自定义 tag 一起冲掉
    本插件补上中间那一档，并且是默认行为：
        · 缺失            → 补齐
        · 与在线数据不一致 → 替换
        · 与在线数据一致   → 跳过（不产生任何写入，不改动文件 mtime）
    另外支持三层保护：NFO 内 lockdata/lockedfields、插件配置的「保护字段」、只报告模式。

────────────────────────────────────────────────────────────────────────
一、作为 MoviePilot 插件部署（推荐：方式 A 最省事）

  方式 A：直接放入插件目录
      1) 把本文件拷进容器：
         docker cp NfoGapFill.py moviepilot-v2:/config/NfoGapFill.py
      2) 找到插件目录真实路径（不同镜像/版本可能是 /app/app/plugins 或 /app/plugins）：
         docker exec -it moviepilot-v2 python -c "import app.plugins,os;print(os.path.dirname(app.plugins.__file__))"
      3) 移进去并重启容器：
         docker exec -it moviepilot-v2 mv /config/NfoGapFill.py <上一步输出的目录>/
         docker restart moviepilot-v2
      4) 打开 MoviePilot → 设定 → 插件，在「已安装」里找到「NFO 差异比对与补齐」。

  方式 B：本地插件仓库（持久化，容器重建/升级不丢）
      1) 在宿主机建目录并放入本文件，文件名必须是插件 ID（类名）NfoGapFill.py：
         /your/appdata/mp_plugins/NfoGapFill.py
      2) docker-compose.yml 增加挂载与环境变量：
         volumes:
           - /your/appdata/mp_plugins:/mp_plugins
         environment:
           - PLUGIN_LOCAL_REPO_PATHS=/mp_plugins
      3) 重启容器，插件市场会多出「本地仓库」来源，可正常安装/卸载。

  注意：升级 MoviePilot 镜像后 /app 内的文件会被重置，方式 A 需要重新执行一次；
        长期使用建议方式 B，或把自己的仓库推到 GitHub 后用 PLUGIN_MARKET 安装。

────────────────────────────────────────────────────────────────────────
二、作为独立命令行工具（先在电脑上验证策略，再上 NAS）

    # 体检：只统计本地 NFO 有哪些字段缺失 / 与在线数据不一致（需要联网）
    python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --diff

    # 离线演练：用本地 JSON 模拟在线数据，不联网也能验证比对逻辑
    python NfoGapFill.py --root /media/link --source file --cache remote.json --diff

    # 正式执行（先加 --dry-run 看一遍，再去掉）
    python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --mode sync --fix

   CLI 与插件调用的是完全同一套引擎，CLI 上验证通过的行为就是插件的实际行为。

────────────────────────────────────────────────────────────────────────
三、四种运行模式
    report   只报告差异，一个字节都不写
    gapfill  只补缺失（等价官方插件的「不覆盖已有元数据」）
    sync     缺失补齐 + 不一致替换 + 一致跳过   ← 默认，本插件的存在意义
    force    无条件用在线数据覆盖全部受管字段（等价官方插件的 force_all）
"""

from __future__ import annotations

import argparse
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


PLUGIN_VERSION = "1.0.0"
TIMEOUT = 25
RATE_GAP = 0.25          # TMDB 限速：最快 4 请求/秒
NUMBER_TOL = 0.05        # 评分/时长的数值容差，避免 8.4 与 8.40 被判为差异
IMG_BASE = "https://image.tmdb.org/t/p/original"


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


def write_local_values(nfo: NfoFile, name: str, new_values: List[str], replace: bool) -> None:
    """写回字段。replace=True 时先清空该字段的全部旧节点再重建（保持元素顺序可接受）。"""
    root = nfo.root
    if name == "actor":
        if replace:
            for el in list(root.findall("actor")):
                root.remove(el)
        else:
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
        return

    if replace:
        for el in list(root.findall(name)):
            root.remove(el)
        for value in new_values:
            ET.SubElement(root, name).text = value
        return

    # 补齐模式：优先填已存在的空节点，多余的新值再追加，避免产生重复标签
    empties = [el for el in root.findall(name) if not norm_text(el.text)]
    for el in empties:
        if not new_values:
            break
        el.text = new_values.pop(0)
    for value in new_values:
        ET.SubElement(root, name).text = value


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
# 在线数据源：统一产出 {字段名: [字符串]}
# ══════════════════════════════════════════════════════════════════════
class TmdbProvider:
    """直连 TMDB。行为最可预测，建议优先使用（需要一个免费 API Key）。"""

    name = "TMDB 直连"

    def __init__(self, api_key: str, language: str = "zh-CN", proxy: Optional[str] = None,
                 cert_country: str = "US", cast_limit: int = 20):
        self.api_key = api_key
        self.language = language
        self.cert_country = (cert_country or "US").upper()
        self.cast_limit = cast_limit
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)
        self._last = 0.0
        self.calls = 0

    def _get(self, path: str, **params) -> Optional[dict]:
        gap = time.time() - self._last
        if gap < RATE_GAP:
            time.sleep(RATE_GAP - gap)
        params.update({"api_key": self.api_key, "language": self.language})
        url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        self._last = time.time()
        self.calls += 1
        try:
            with self.opener.open(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("TMDB 返回 401：API Key 无效或未激活")
            if exc.code == 429:
                time.sleep(2)
            if exc.code != 404:
                logger.warning(f"TMDB HTTP {exc.code}：{path}")
            return None
        except Exception as exc:
            logger.warning(f"TMDB 请求失败：{path}（{exc}）")
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
        return [
            ACTOR_SEP.join([(a.get("name") or "").strip(), (a.get("character") or "").strip(),
                            (IMG_BASE + a["profile_path"]) if a.get("profile_path") else ""])
            for a in (credits or {}).get("cast") or []
            if (a.get("name") or "").strip()
        ][: self.cast_limit]

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


class HostProvider:
    """借用 MoviePilot 自身的媒体识别链路，无需额外 API Key（尽力而为，失败会明确记日志）。"""

    name = "MoviePilot 宿主链路"

    def __init__(self) -> None:
        self._chain = None
        self._failed = False

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
    def _info_to_fields(info: Any, is_tv: bool) -> Dict[str, List[str]]:
        def g(*names: str) -> Any:
            for name in names:
                value = getattr(info, name, None)
                if value not in (None, "", [], {}):
                    return value
            return None

        actors = []
        for person in (g("actors") or [])[:20]:
            actors.append(ACTOR_SEP.join([
                str(getattr(person, "name", "") or "").strip(),
                str(getattr(person, "role", "") or "").strip(),
                str(getattr(person, "image", "") or getattr(person, "thumb", "") or "").strip(),
            ]))
        fields = {
            "title": to_str_list(g("title", "name")),
            "originaltitle": to_str_list(g("original_title", "original_name")),
            "plot": to_str_list(g("overview", "plot")),
            "tagline": to_str_list(g("tagline")),
            "rating": to_str_list(g("vote_average", "rating")),
            "genre": to_str_list(g("genres", "genre")),
            "country": to_str_list(g("country", "production_countries")),
            "director": to_str_list(g("directors", "director")),
            "actor": actors,
        }
        if is_tv:
            fields["premiered"] = to_str_list(g("first_air_date", "release_date"))
            fields["year"] = to_str_list(str(g("first_air_date", "release_date") or "").strip()[:4])
            fields["studio"] = to_str_list(g("networks", "production_companies", "studios"))
            fields["runtime"] = to_str_list(g("episode_run_time"))
        else:
            fields["premiered"] = to_str_list(g("release_date"))
            fields["year"] = to_str_list(str(g("release_date") or "").strip()[:4])
            fields["runtime"] = to_str_list(g("runtime"))
            fields["studio"] = to_str_list(g("production_companies", "studios"))
        return {k: v for k, v in fields.items() if v}

    def fetch_movie(self, tmdb_id: str) -> Dict[str, List[str]]:
        info = self._recognize(tmdb_id, False)
        return self._info_to_fields(info, False) if info else {}

    def fetch_tvshow(self, tmdb_id: str) -> Dict[str, List[str]]:
        info = self._recognize(tmdb_id, True)
        return self._info_to_fields(info, True) if info else {}

    def fetch_episode(self, tmdb_id: str, season: str, episode: str) -> Dict[str, List[str]]:
        logger.warning("宿主链路暂不支持单集简介比对，建议为插件填写 TMDB API Key")
        return {}

    def fetch_season(self, tmdb_id: str, season: str) -> Dict[str, List[str]]:
        return {}


class FileProvider:
    """从本地 JSON 读取「在线数据」，用于离线演练与回归测试。

    JSON 结构： {"movie:157336": {"plot": ["..."], "actor": ["名字|角色|https://..."]}, ...}
    键规则：movie:<tmdbid> / tv:<tmdbid> / season:<tmdbid>:<季> / episode:<tmdbid>:<季>:<集>
    """

    name = "本地 JSON"

    def __init__(self, cache_path: str):
        self.data: Dict[str, Dict[str, List[str]]] = {}
        if cache_path:
            try:
                self.data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"读取缓存 JSON 失败：{cache_path}（{exc}）")
        self.calls = 0

    def _lookup(self, key: str) -> Dict[str, List[str]]:
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


# ══════════════════════════════════════════════════════════════════════
# 引擎配置与报告
# ══════════════════════════════════════════════════════════════════════
@dataclass
class EngineConfig:
    roots: List[Path]
    exclude_paths: List[str] = field(default_factory=list)
    mode: str = "sync"                     # report | gapfill | sync | force
    protect_fields: set = field(default_factory=set)
    only_fields: set = field(default_factory=set)
    respect_lock: bool = True
    dry_run: bool = False
    backup: bool = True
    backup_dir: Optional[Path] = None
    max_files: int = 0
    report_limit: int = 300


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
    unresolved: int = 0           # 拿不到在线数据
    failed: int = 0
    counts: Dict[str, int] = field(default_factory=dict)    # 差异判定统计
    applied: Dict[str, int] = field(default_factory=dict)   # 实际动作统计
    changes: List[Change] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    mode: str = "sync"
    provider: str = ""
    calls: int = 0

    def to_text(self) -> str:
        lines = [
            f"运行模式：{self.mode}　数据源：{self.provider}　在线请求：{self.calls} 次",
            f"开始：{self.started}　结束：{self.finished}",
            "-" * 62,
            f"扫描 NFO {self.scanned} 个｜无差异 {self.untouched}｜已写入文件 {self.changed_files}"
            f"｜受锁保护 {self.skipped_locked}｜取不到在线数据 {self.unresolved}｜失败 {self.failed}",
        ]
        if self.counts:
            lines.append("差异判定：" + "｜".join(f"{k} {v}" for k, v in self.counts.items()))
        if self.applied:
            lines.append("实际动作：" + "｜".join(f"{k} {v}" for k, v in self.applied.items()))
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


def guess_title_year(nfo: NfoFile) -> Tuple[Optional[str], Optional[str]]:
    root = nfo.root
    title = norm_text(root.findtext("title"))
    year = norm_text(root.findtext("year") or root.findtext("premiered") or root.findtext("aired"))
    year = year[:4] if year else None
    if not title:
        name = nfo.path.parent.name
        if name.casefold().startswith("season"):
            name = nfo.path.parent.parent.name
        match = re.search(r"[\(\[]((?:19|20)\d{2})[\)\]]", name)
        if match:
            year = year or match.group(1)
        title = re.sub(r"[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]", "", name).strip(" -_·") or None
    return title, year


class Engine:
    def __init__(self, cfg: EngineConfig, provider: Any,
                 cancel: Optional[Event] = None, single_file: Optional[Path] = None):
        self.cfg = cfg
        self.provider = provider
        self.cancel = cancel or Event()
        self.single_file = single_file
        self.report = Report(mode=cfg.mode, provider=getattr(provider, "name", "?"))

    # ── 在线数据获取 ────────────────────────────────────────────────
    def fetch_remote(self, nfo: NfoFile) -> Tuple[Dict[str, List[str]], str]:
        root = nfo.root
        mtype = nfo.media_type

        tmdb_id, source = find_tmdb_id(root, mtype)
        if mtype in ("tvshow", "season", "episodedetails") and not tmdb_id:
            tmdb_id, source = self._find_show_id(nfo)
        if mtype == "movie" and not tmdb_id:
            tmdb_id, source = self._search_id(nfo, is_tv=False)
        if not tmdb_id:
            return {}, source

        if mtype == "movie":
            return self.provider.fetch_movie(tmdb_id), f"tmdb:{tmdb_id}（{source}）"
        if mtype == "tvshow":
            return self.provider.fetch_tvshow(tmdb_id), f"tmdb:{tmdb_id}（{source}）"
        if mtype == "season":
            season = norm_text(root.findtext("season")) or self._from_name(nfo, r"S(\d+)")
            if not season:
                return {}, "无法确定季号"
            return self.provider.fetch_season(tmdb_id, season), f"tmdb:{tmdb_id} 第 {season} 季"
        season = norm_text(root.findtext("season")) or self._from_name(nfo, r"S(\d+)")
        episode = norm_text(root.findtext("episode")) or self._from_name(nfo, r"E(\d+)")
        if not (season and episode):
            return {}, "无法确定季/集号"
        return (self.provider.fetch_episode(tmdb_id, season, episode),
                f"tmdb:{tmdb_id} S{season}E{episode}")

    @staticmethod
    def _from_name(nfo: NfoFile, pattern: str) -> Optional[str]:
        match = re.search(pattern, nfo.path.name, re.I)
        return match.group(1) if match else None

    def _find_show_id(self, nfo: NfoFile) -> Tuple[Optional[str], str]:
        """单集/季 NFO 自己没有剧集 id 时，向上找同级 tvshow.nfo。"""
        current = nfo.path.parent
        for _ in range(4):
            current = current.parent
            candidate = current / "tvshow.nfo"
            if candidate.exists():
                loaded = load_nfo(candidate)
                if loaded:
                    found = find_tmdb_id(loaded.root, "tvshow")
                    if found[0]:
                        return found[0], f"同剧 tvshow.nfo"
            if current == current.parent:
                break
        return None, "未找到剧集 TMDB 标识"

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

        logger.info(f"NFO 差异比对开始：待检查 {len(targets)} 个文件，模式 {self.cfg.mode}")
        for index, path in enumerate(targets, 1):
            if self.cancel.is_set():
                logger.info("收到停止信号，提前结束本轮")
                break
            root_dir = next((r for r in self.cfg.roots if str(path).startswith(str(r))), path.parent)
            try:
                self.process(path, root_dir)
            except Exception as exc:
                self.report.failed += 1
                self.report.errors.append(f"{path}：{exc}")
                logger.error(f"处理失败：{path}（{exc}）")
            if index % 200 == 0:
                logger.info(f"进度 {index}/{len(targets)}")

        self.report.finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.report.calls = getattr(self.provider, "calls", 0)
        logger.info(f"NFO 差异比对结束：扫描 {self.report.scanned}，写入 {self.report.changed_files}，"
                    f"无差异 {self.report.untouched}")
        return self.report

    def process(self, path: Path, root_dir: Path) -> None:
        nfo = load_nfo(path)
        if not nfo:
            return
        rel = str(path)
        try:
            rel = str(path.relative_to(root_dir))
        except ValueError:
            pass
        self.report.scanned += 1

        managed = MANAGED_FIELDS.get(nfo.media_type, [])
        if self.cfg.only_fields:
            managed = [f for f in managed if f in self.cfg.only_fields]

        locked = get_locked_fields(nfo.root) if self.cfg.respect_lock else None
        locked_names = {f.casefold() for f in locked} if isinstance(locked, set) else set()

        remote, source = self.fetch_remote(nfo)
        if not remote:
            self.report.unresolved += 1
            self.report.errors.append(f"{rel}：{source}")
            logger.warning(f"取不到在线数据，保持原样：{rel}（{source}）")
            return

        plan: List[Tuple[str, bool]] = []      # (字段名, 是否整体替换)
        for name in managed:
            kind = FIELD_KINDS.get(name, "text")
            local_vals = read_local_values(nfo, name)
            remote_vals = to_str_list(remote.get(name))
            verdict, action = compare(kind, local_vals, remote_vals)
            self.report.counts[verdict] = self.report.counts.get(verdict, 0) + 1
            if action == SKIP:
                continue

            is_locked = locked is True or name.casefold() in locked_names
            if is_locked:
                applied, do_write = "跳过（NFO 字段锁定）", False
            elif self.cfg.mode == "report":
                applied, do_write = "仅报告", False
            elif self.cfg.mode == "gapfill" and action == REPLACE:
                applied, do_write = "跳过（gapfill 只补缺失）", False
            elif self.cfg.mode != "force" and action == REPLACE and name in self.cfg.protect_fields:
                applied, do_write = "跳过（受保护字段）", False
            elif action == FILL:
                applied, do_write = FILL, True
            else:
                applied, do_write = REPLACE, True

            self.report.applied[applied] = self.report.applied.get(applied, 0) + 1
            if is_locked:
                self.report.skipped_locked += 1
            self.record(rel, nfo.media_type, name, verdict, applied, local_vals, remote_vals)
            if do_write:
                plan.append((name, action == REPLACE))

        if not plan:
            self.report.untouched += 1
            return
        if self.cfg.dry_run:
            logger.info(f"[预演] {rel} 将更新 {len(plan)} 个字段：{', '.join(p[0] for p in plan)}")
            return

        for name, replace in plan:
            write_local_values(nfo, name, to_str_list(remote.get(name)), replace=replace)
        write_nfo_file(nfo, (self.cfg.backup_dir if self.cfg.backup else None), root_dir)
        self.report.changed_files += 1
        logger.info(f"已更新 {rel}：{', '.join(p[0] for p in plan)}")

    def record(self, rel: str, media_type: str, name: str, verdict: str,
               action: str, local_vals: List[str], remote_vals: List[str]) -> None:
        if len(self.report.changes) >= self.cfg.report_limit:
            return
        self.report.changes.append(Change(
            nfo=rel, media_type=media_type, field=name, verdict=verdict, action=action,
            local=" ｜ ".join(local_vals)[:200], remote=" ｜ ".join(remote_vals)[:200],
        ))


# ══════════════════════════════════════════════════════════════════════
# MoviePilot 插件
# ══════════════════════════════════════════════════════════════════════
class NfoGapFill(_PluginBase):  # type: ignore[misc]
    # 插件名称
    plugin_name = "NFO 差异比对与补齐"
    # 插件描述
    plugin_desc = "比对本地 NFO 与在线元数据：缺失补齐、不一致替换、一致跳过；支持字段保护与 NFO 锁定。"
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

    # 运行态
    _enabled: bool = False
    _onlyonce: bool = False
    _cron: str = ""
    _mode: str = "sync"
    _paths: str = ""
    _exclude_paths: str = ""
    _protect_fields: str = ""
    _only_fields: str = ""
    _respect_lock: bool = True
    _dry_run: bool = False
    _backup: bool = True
    _tmdb_api_key: str = ""
    _language: str = "zh-CN"
    _proxy: str = ""
    _cert_country: str = "US"
    _cast_limit: str = "20"
    _max_files: str = "0"
    _notify: bool = True
    _event: Event = Event()
    _timer: Optional[threading.Timer] = None

    # ── 生命周期 ───────────────────────────────────────────────────
    def init_plugin(self, config: Optional[dict] = None) -> None:
        if config:
            self._enabled = bool(config.get("enabled"))
            self._onlyonce = bool(config.get("onlyonce"))
            self._cron = (config.get("cron") or "").strip()
            self._mode = config.get("mode") or "sync"
            self._paths = config.get("paths") or ""
            self._exclude_paths = config.get("exclude_paths") or ""
            self._protect_fields = config.get("protect_fields") or ""
            self._only_fields = config.get("only_fields") or ""
            self._respect_lock = bool(config.get("respect_lock", True))
            self._dry_run = bool(config.get("dry_run"))
            self._backup = bool(config.get("backup", True))
            self._tmdb_api_key = (config.get("tmdb_api_key") or "").strip()
            self._language = config.get("language") or "zh-CN"
            self._proxy = (config.get("proxy") or "").strip()
            self._cert_country = (config.get("cert_country") or "US").strip()
            self._cast_limit = str(config.get("cast_limit") or "20")
            self._max_files = str(config.get("max_files") or "0")
            self._notify = bool(config.get("notify", True))

        self.stop_service()

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
                                    "model": "cron", "label": "执行周期",
                                    "placeholder": "5 位 cron，例如 0 3 * * * 表示每天 03:00"}}]},
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
                                {"component": "VSwitch", "props": {"model": "backup", "label": "写入前备份原 NFO"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "max_files", "label": "单轮最多处理文件数",
                                    "placeholder": "0 表示不限；首次全库建议填 50 试水"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextarea", "props": {
                                    "model": "paths", "label": "媒体库目录", "rows": 4,
                                    "placeholder": "每行一个目录，例如 /media/link/电影\n/media/link/电视剧"}}]},
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
                                    "model": "tmdb_api_key", "label": "TMDB API Key（留空则尝试使用 MP 自身通道）",
                                    "placeholder": "在 themoviedb.org 免费申请"}}]},
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
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "only_fields", "label": "只处理这些字段（留空=全部）",
                                    "placeholder": "逗号分隔，例如 plot,rating"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "proxy", "label": "代理（留空则用宿主网络）",
                                    "placeholder": "http://192.168.1.2:7890"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "cert_country", "label": "分级地区码",
                                    "placeholder": "US / CN / JP，决定 mpaa 字段取哪个地区的分级"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "cast_limit", "label": "演员写入上限",
                                    "placeholder": "默认 20"}}]},
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
                                 "text": "建议先用「只报告差异 + 演练模式」跑一轮，确认差异清单符合预期后再切换为「不一致则替换」。"}]},
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "mode": "sync",
            "cron": "0 3 * * *",
            "dry_run": False,
            "respect_lock": True,
            "backup": True,
            "max_files": "0",
            "paths": "",
            "exclude_paths": "",
            "protect_fields": "",
            "only_fields": "",
            "tmdb_api_key": "",
            "language": "zh-CN",
            "proxy": "",
            "cert_country": "US",
            "cast_limit": "20",
        }

    def get_page(self) -> List[dict]:
        text = self.__load_last_report() or "尚未运行过。保存配置时勾选「保存后立即运行一次」即可产生结果。"
        head = text.splitlines()
        return [
            {
                "component": "VRow",
                "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [
                        {"component": "VAlert", "props": {
                            "type": "info", "variant": "tonal",
                            "text": f"NFO 差异比对与补齐 v{PLUGIN_VERSION}　模式：{self._mode}"
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
            cron = self._cron or "0 3 * * *"
            try:
                trigger = CronTrigger.from_crontab(cron)
            except Exception as exc:
                logger.error(f"cron 表达式无效（{cron}）：{exc}，已回退为每天 03:00")
                trigger = CronTrigger.from_crontab("0 3 * * *")
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
                "dry_run": self._dry_run,
                "respect_lock": self._respect_lock,
                "backup": self._backup,
                "max_files": self._max_files,
                "paths": self._paths,
                "exclude_paths": self._exclude_paths,
                "protect_fields": self._protect_fields,
                "only_fields": self._only_fields,
                "tmdb_api_key": self._tmdb_api_key,
                "language": self._language,
                "proxy": self._proxy,
                "cert_country": self._cert_country,
                "cast_limit": self._cast_limit,
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

    def __build_provider(self):
        if self._tmdb_api_key:
            return TmdbProvider(self._tmdb_api_key, self._language, self._proxy or None,
                                self._cert_country, self.__int(self._cast_limit, 20))
        logger.info("未配置 TMDB API Key，尝试使用 MoviePilot 宿主链路")
        return HostProvider()

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

    def __run(self) -> None:
        try:
            roots = [Path(p) for p in self.__split_lines(self._paths)]
            if not roots:
                logger.warning("未配置任何媒体库目录，任务结束")
                return
            cfg = EngineConfig(
                roots=roots,
                exclude_paths=self.__split_lines(self._exclude_paths),
                mode=self._mode if self._mode in ("report", "gapfill", "sync", "force") else "sync",
                protect_fields=self.__split_set(self._protect_fields),
                only_fields=self.__split_set(self._only_fields),
                respect_lock=self._respect_lock,
                dry_run=self._dry_run,
                backup=self._backup,
                max_files=self.__int(self._max_files, 0),
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
                })
            except Exception:
                pass

            if self._notify:
                self.__notify(report)
        except Exception as exc:
            logger.error(f"NFO 差异比对任务异常：{exc}")

    def __notify(self, report: Report) -> None:
        title = "【NFO 差异比对】完成"
        text = (f"扫描 {report.scanned}｜写入 {report.changed_files}｜无差异 {report.untouched}\n"
                f"替换 {report.counts.get(REPLACE, 0)}｜补齐 {report.counts.get(FILL, 0)}"
                f"｜取不到在线数据 {report.unresolved}"
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
        return HostProvider()
    if not args.api_key:
        raise SystemExit("--source tmdb 需要 --api-key，或设置环境变量 TMDB_API_KEY")
    return TmdbProvider(args.api_key, args.lang, args.proxy or None, args.cert_country, args.cast_limit)


def cli_main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="NfoGapFill",
        description="NFO 元数据差异比对与补齐：缺失补齐、不一致替换、一致跳过",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  体检（只报告差异）  python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --mode report\n"
               "  离线演练            python NfoGapFill.py --root /media/link --source file --cache remote.json\n"
               "  正式执行            python NfoGapFill.py --root /media/link --source tmdb --api-key XXX --mode sync --fix")
    parser.add_argument("--root", action="append", required=True, help="媒体库目录，可重复指定")
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
    parser.add_argument("--cast-limit", type=int, default=20, help="演员数量上限，默认 20")
    parser.add_argument("--max-files", type=int, default=0, help="单轮最多处理多少个 NFO")
    parser.add_argument("--no-backup", action="store_true", help="不备份原文件（不推荐）")
    parser.add_argument("--backup-dir", default="", help="备份目录，默认 <root>/.nfo-backup")
    parser.add_argument("--json", dest="json_out", default="", help="把完整报告写入 JSON")
    args = parser.parse_args(argv)

    import os
    args.api_key = args.api_key or os.environ.get("TMDB_API_KEY", "")
    roots = [Path(p).expanduser().resolve() for p in args.root]
    for root in roots:
        if not root.is_dir():
            raise SystemExit(f"目录不存在：{root}")
    if not args.fix:
        args.mode = "report"

    provider = build_cli_provider(args)
    cfg = EngineConfig(
        roots=roots,
        exclude_paths=[s.strip() for s in re.split(r"[,\n]+", args.exclude) if s.strip()],
        mode=args.mode,
        protect_fields={s.strip().casefold() for s in re.split(r"[,\s]+", args.protect) if s.strip()},
        only_fields={s.strip().casefold() for s in re.split(r"[,\s]+", args.only) if s.strip()},
        dry_run=args.dry_run,
        backup=not args.no_backup,
        backup_dir=Path(args.backup_dir).expanduser() if args.backup_dir else roots[0] / ".nfo-backup",
        max_files=args.max_files,
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
            "changes": [c.__dict__ for c in report.changes],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入：{args.json_out}")
    return 0


if __name__ == "__main__":
    if IN_MOVIEPILOT:
        logger.info("检测到 MoviePilot 宿主环境，本文件应作为插件加载，而不是直接运行。")
    sys.exit(cli_main())
