# -*- coding: utf-8 -*-
"""
超集识别与特别篇归位核心逻辑（纯函数，无宿主依赖，可离线单测）。

判定链路：
    1. 扫描季目录 -> 提取本地集号集合
    2. 与 TMDB 该季官方集数比对 -> 得到超集集合
    3. 对每个超集做三重证据判定（关键词 / 时长 / TMDB Season 0 匹配）
    4. 给出建议动作：移入 Season 00 并重编号，或仅报告不动
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Tuple

# ---------------------------------------------------------------------------
# 正则
# ---------------------------------------------------------------------------

# S01E02 / S1.E2 / 1x02 —— 标准剧集编号
RE_SE_EP = re.compile(r"[Ss](?P<season>\d{1,2})[\s._-]*[Ee](?P<ep>\d{1,4})(?![\d])")
# 第 12 集 / 第十二集 —— 中文集号（阿拉伯数字）
RE_CN_EP = re.compile(r"第\s*(?P<ep>\d{1,4})\s*[集話话话期]")
# 1x02 —— 老式剧集编号
RE_X_EP = re.compile(r"(?<!\d)(?P<season>\d{1,2})[xX](?P<ep>\d{1,3})(?!\d)")
# 01 / 1x02 单独形式（目录内纯数字前缀）
RE_NUM_ONLY = re.compile(r"^(?P<ep>\d{1,4})(?=\D|$)")
# 无 S/E 标记的发布组命名： "- 24 [1080p]" / "_07_" / " - 07 - "
RE_DASH_EP = re.compile(r"[-–—]\s*(?P<ep>\d{1,3})\s*(?=[-–—\[\s.]|$)")
RE_UNDER_EP = re.compile(r"(?<=[\s_])(?P<ep>\d{1,3})(?=[\s_])")
# 裸集号：独立成词，且排除 1080p / 2160p / 年份这类数字
RE_LOOSE_EP = re.compile(r"(?<![\d.])(\d{1,3})(?![\d.pP]|\d*[pP]\b)")

# 季目录名：Season 01 / Season 1 / S01 / 第 1 季 / 特別篇(Specials)
RE_SEASON_DIR_EN = re.compile(r"^Season\s*(?P<season>\d{1,2})$", re.I)
RE_SEASON_DIR_SN = re.compile(r"^S(?P<season>\d{1,2})$", re.I)
RE_SEASON_DIR_CN = re.compile(r"^第\s*(?P<season>[0-9一二三四五六七八九十]+)\s*季$")

CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 剧集目录名里的 tmdbid：{tmdbid=94664}
RE_TMDBID_DIR = re.compile(r"\{tmdbid=(\d+)\}")
# tvshow.nfo 里的 tmdbid
RE_TMDBID_NFO = re.compile(r"<tmdbid>\s*(\d+)\s*</tmdbid>", re.I)

# 副标题 / 特别篇关键词（大小写不敏感）。命中即加权，不单独定罪。
SP_KEYWORDS = [
    "sp", "special", "specials", "ova", "oad", "ona", "extra", "extras",
    "bonus", "omake", "omakase", "番外", "番外篇", "总集篇", "总集", "合集",
    "特典", "特别篇", "特别版", "特别映像", "映像特典", "未放送", "先行版",
    "预告", "预览", "前传", "幕后", "花絮", "making", "recap", "summary",
    "总集編", "特別編", "映像特典", "ノベラ", "ドラマ指名", " corta",
]
# 用空格包裹才判定为独立词的短词，避免误伤（如 "Extraordinary" 里的 sp）
RE_SP_WORD = re.compile(r"(?<![A-Za-z])(" + "|".join(
    [re.escape(k) for k in SP_KEYWORDS if k.isascii() and len(k) <= 7]
) + r")(?![A-Za-z])", re.I)
# 中日文关键词直接子串匹配
RE_SP_CJK = re.compile(
    "|".join(re.escape(k) for k in SP_KEYWORDS if not k.isascii())
)

SUBTITLE_EXT = [".ass", ".ssa", ".srt", ".vtt", ".sub", ".idx", ".sup", ".smi"]


def is_special_keyword(name: str) -> List[str]:
    """返回文件名中命中的特别篇关键词列表。"""
    hits: List[str] = []
    if RE_SP_WORD.search(name or ""):
        hits += [m.group(1).lower() for m in RE_SP_WORD.finditer(name)]
    if RE_SP_CJK.search(name or ""):
        hits += [m.group(0) for m in RE_SP_CJK.finditer(name)]
    return sorted(set(hits))


def cn_number(text: str) -> Optional[int]:
    """中文数字转整数，支持 1-99（季号足够）。"""
    if not text:
        return None
    text = text.strip()
    if text.isdigit():
        return int(text)
    # 十X / X十 / X十X
    if "十" in text:
        head, _, tail = text.partition("十")
        h = CN_NUM.get(head, 1) if head else 1
        t = CN_NUM.get(tail, 0) if tail else 0
        return h * 10 + t
    return CN_NUM.get(text)


def season_from_dir(dir_name: str) -> Optional[int]:
    """
    从季目录名解析季号。识别不出返回 None —— 绝不返回 0 兜底。
    第 0 季（Specials / 特别篇）显式返回 0。
    """
    name = (dir_name or "").strip()
    if not name:
        return None
    low = name.lower()
    # 特别篇目录一律是第 0 季
    if low in ("specials", "special", "season 0", "season 00", "s00", "s0",
               "特别篇", "特典", "番外", "sp", "sp1", "specials season 0"):
        return 0
    for rx in (RE_SEASON_DIR_EN, RE_SEASON_DIR_SN):
        m = rx.match(name)
        if m:
            return int(m.group("season"))
    m = RE_SEASON_DIR_CN.match(name)
    if m:
        return cn_number(m.group("season"))
    return None


def extract_episode_number(file_name: str) -> Optional[int]:
    """
    从文件名提取集号。优先级（先精确后宽松，避免把 1080p / 年份当集号）：
      SxxEyy  >  第N集  >  1x02  >  纯数字前缀  >  -NN[-]  >  独立成词的 NN
    """
    name = (file_name or "").strip()
    if not name:
        return None
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", name)

    for rx in (RE_SE_EP, RE_CN_EP, RE_X_EP):
        m = rx.search(stem)
        if m:
            return int(m.group("ep"))

    m = RE_NUM_ONLY.match(stem)
    if m:
        return int(m.group("ep"))

    m = RE_DASH_EP.search(stem)
    if m:
        return int(m.group("ep"))

    m = RE_UNDER_EP.search(stem)
    if m:
        return int(m.group("ep"))

    # 兜底：独立成词的小数字，跳过分辨率/年份/编码组等常见噪声
    best = None
    for m in RE_LOOSE_EP.finditer(stem):
        val = int(m.group(1))
        if val == 0 or val > 999:
            continue
        # 排除紧邻 "p/P"（1080p）和 4 位年份形态（已由位数限制排除）
        tail = stem[m.end(1):m.end(1) + 2]
        if tail[:1] in ("p", "P"):
            continue
        # 取最靠后的合法数字（通常是集号，标题里的年份在前）
        best = val
    return best


@dataclass
class LocalEpisode:
    """季目录内的一个本地剧集文件及其附属文件。"""
    video: str
    ep: Optional[int]
    sidecars: List[str] = field(default_factory=list)   # 字幕/图片/nfo
    duration: Optional[int] = None                        # 秒，探测失败为 None
    sp_hits: List[str] = field(default_factory=list)      # 文件名里的特别篇关键词

    def display(self) -> str:
        return f"E{self.ep:02d}" if self.ep else "无集号"


@dataclass
class Verdict:
    """对单个超集文件的判定结果。"""
    episode: LocalEpisode
    season: int
    is_special: bool
    confidence: float
    reasons: List[str] = field(default_factory=list)
    target_season: Optional[int] = None        # 0 表示 Season 00
    target_ep: Optional[int] = None            # Season 00 内的新集号
    matched_s0_title: Optional[str] = None     # 匹配到的 TMDB Season 0 标题
    action: str = "report"                     # move / rename_only / report / skip

    def to_dict(self) -> dict:
        d = asdict(self)
        d["episode"] = {
            "video": self.episode.video,
            "ep": self.episode.ep,
            "sidecars": self.episode.sidecars,
            "duration": self.episode.duration,
        }
        return d


def group_episodes(files: List[str], durations: Dict[str, int] = None) -> List[LocalEpisode]:
    """
    把目录下的文件名归组成「视频 + 附属文件」的剧集列表。

    附属文件按**集号**匹配同集视频，而不是按 stem 前缀 ——
    因为字幕常被命名成 `xxx - S01E24.zh-CN.ass`，而视频是 `xxx - S01E24 SP.mkv`，
    两者 stem 前缀并不相同，只有集号一致。
    """
    durations = durations or {}
    videos: List[LocalEpisode] = []
    sidecar_map: Dict[str, List[str]] = {}
    for f in files:
        stem, ext = split_ext(f)
        low = ext.lower()
        if low in SUBTITLE_EXT or low in (".nfo", ".jpg", ".jpeg", ".png",
                                          ".tbn", ".webp", ".sup", ".idx"):
            sidecar_map.setdefault(stem, []).append(f)
            continue
        videos.append(LocalEpisode(
            video=f,
            ep=extract_episode_number(stem),
            duration=durations.get(f),
            sp_hits=is_special_keyword(stem),
        ))

    # 先按集号建索引
    by_ep: Dict[int, List[LocalEpisode]] = {}
    for v in videos:
        if v.ep is not None:
            by_ep.setdefault(v.ep, []).append(v)

    # 附属文件 -> 集号 -> 同集视频
    for sstem, items in sidecar_map.items():
        sep = extract_episode_number(sstem)
        targets = by_ep.get(sep) if sep is not None else None
        if not targets:
            continue
        for t in targets:
            t.sidecars.extend(items)

    # 集号匹配不上的（例如整季通用字幕），再退回 stem 全等匹配
    for v in videos:
        stem, _ = split_ext(v.video)
        for sstem, items in sidecar_map.items():
            sep = extract_episode_number(sstem)
            if sep is not None and sep in by_ep:
                continue                      # 已按集号归组过
            if sstem == stem:
                for it in items:
                    if it not in v.sidecars:
                        v.sidecars.append(it)

    videos.sort(key=lambda x: (x.ep is None, x.ep or 0))
    return videos


def split_ext(name: str) -> Tuple[str, str]:
    """拆 stem 与扩展名，支持双扩展 .tar.gz 这类（视频场景够用）。"""
    if "." not in name:
        return name, ""
    stem, _, ext = name.rpartition(".")
    return stem, f".{ext}"


def find_extras(local_eps: List[LocalEpisode], tmdb_count: int, tolerance: int = 0) -> List[LocalEpisode]:
    """
    找出超出 TMDB 官方集数的剧集。
    tolerance > 0 时额外容忍末尾若干集（用于官方未收录但确实是正片的场景）。
    无集号的文件不参与超集判定（信息不足，宁可不动）。
    """
    limit = (tmdb_count or 0) + max(0, tolerance)
    return [e for e in local_eps if e.ep is not None and e.ep > limit]


def judge_special(ep: LocalEpisode,
                  season: int,
                  s0_index: Dict[str, dict],
                  normal_duration: Optional[int],
                  s0_duration: Optional[int],
                  min_confidence: float = 0.5) -> Verdict:
    """
    判定单个超集文件是否属于特别篇。三路证据加权：

      A. 文件名关键词命中        权重 0.55（强证据，SP/OVA/特别篇 等）
      B. 时长显著偏离正片       权重 0.30（弱证据，仅作辅助）
      C. 标题命中 TMDB Season 0 权重 0.85（最强证据）

    置信度 >= min_confidence 才判定为特别篇。
    """
    reasons: List[str] = []
    score = 0.0

    if ep.sp_hits:
        score += 0.55
        reasons.append("文件名含特别篇关键词: " + ", ".join(ep.sp_hits))

    # 时长证据：明显短于正片中位数、或明显长于正片（总集篇反而更长）
    if normal_duration and ep.duration:
        ratio = ep.duration / normal_duration
        if ratio <= 0.75 or ratio >= 1.45:
            score += 0.30
            reasons.append(f"时长 {ep.duration}s 偏离正片中位数 {normal_duration}s（{ratio:.2f}x）")

    # TMDB Season 0 标题匹配：拿文件名里的标题片段去比对
    matched = None
    if s0_index:
        matched = match_s0(ep.video, s0_index)
    if matched:
        score += 0.85
        reasons.append(f"标题匹配 TMDB Season 0「{matched.get('name')}」")

    score = min(score, 1.0)
    is_sp = score >= min_confidence
    reasons.insert(0, f"置信度 {score:.2f}（阈值 {min_confidence:.2f}）")

    return Verdict(
        episode=ep,
        season=season,
        is_special=is_sp,
        confidence=score,
        reasons=reasons,
        target_season=0 if is_sp else None,
        matched_s0_title=(matched or {}).get("name"),
        action="move" if is_sp else "report",
    )


def match_s0(file_name: str, s0_index: Dict[str, dict]) -> Optional[dict]:
    """
    把本地文件名与 TMDB Season 0 条目做松散匹配。
    归一化后看是否互为子串（对中文标题足够可靠）。
    """
    import unicodedata

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s or "")
        s = re.sub(r"[^\w一-鿿]+", "", s.lower())
        return s

    fn = norm(split_ext(file_name)[0])
    if not fn:
        return None
    best = None
    for key, item in (s0_index or {}).items():
        t = norm(item.get("name") or "")
        if not t:
            continue
        if t in fn or (len(t) >= 4 and fn in t):
            if not best or len(t) > len(norm(best.get("name") or "")):
                best = item
    return best


def build_s0_index(season0: List[dict]) -> Dict[str, dict]:
    """把 TMDB Season 0 列表转成 {episode_number: item} 的索引。"""
    out = {}
    for it in season0 or []:
        num = it.get("episode_number")
        if num is not None:
            out[str(num)] = it
    return out


def median_duration(eps: List[LocalEpisode]) -> Optional[int]:
    """正片中位时长，用于识别明显偏短/偏长的超集。"""
    vals = sorted(e.duration for e in eps if e.duration)
    if len(vals) < 3:
        return vals[len(vals) // 2] if vals else None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return int((vals[mid - 1] + vals[mid]) / 2)


def target_special_ep(assigned: Dict[int, bool], prefer: Optional[int] = None) -> int:
    """
    为新的特别篇分配 Season 00 内的集号。
    优先沿用 TMDB Season 0 的官方集号；该号已被本地占用（或不存在）则顺延
    到当前最小空位，保证绝不与已有文件重号。
    """
    used = set(assigned.keys())
    if prefer is not None and prefer > 0 and prefer not in used:
        return prefer
    n = 1
    while n in used:
        n += 1
    return n