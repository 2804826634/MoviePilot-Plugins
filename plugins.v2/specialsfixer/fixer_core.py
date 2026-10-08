# -*- coding: utf-8 -*-
"""
整理记录季/集修正的纯逻辑层（无宿主依赖，可离线单测）。

职责边界（严格）：
  - 只做「识别特别篇」+「算出该改成什么季/集」；
  - **不调用 TMDB 刮削、不写媒体元数据**，那些全部交给 MP 自身机制；
  - 识别依据只用两类：TMDB 查无该集（失败判定）+ 本地特征（特别篇证据）。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 正则（沿用并强化上一版已实测的集号解析）
# ---------------------------------------------------------------------------
RE_SE_EP = re.compile(r"[Ss](?P<season>\d{1,2})[\s._-]*[Ee](?P<ep>\d{1,4})(?![\d])")
RE_CN_EP = re.compile(r"第\s*(?P<ep>\d{1,4})\s*[集話话期]")
RE_X_EP = re.compile(r"(?<!\d)(?P<season>\d{1,2})[xX](?P<ep>\d{1,3})(?!\d)")
RE_NUM_ONLY = re.compile(r"^(?P<ep>\d{1,4})(?=\D|$)")
RE_DASH_EP = re.compile(r"[-–—]\s*(?P<ep>\d{1,3})\s*(?=[-–—\[\s.]|$)")
RE_UNDER_EP = re.compile(r"(?<=[\s_])(?P<ep>\d{1,3})(?=[\s_])")
RE_LOOSE_EP = re.compile(r"(?<![\d.])(\d{1,3})(?![\d.pP]|\d*[pP]\b)")

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}

RE_SEASON_DIR_EN = re.compile(r"^Season\s*(?P<season>\d{1,2})$", re.I)
RE_SEASON_DIR_SN = re.compile(r"^S(?P<season>\d{1,2})$", re.I)
RE_SEASON_DIR_CN = re.compile(r"^第\s*(?P<season>[0-9一二三四五六七八九十]+)\s*季$")

# 特别篇关键词。ascii 短词要求独立成词，避免误伤（Extraordinary 里的 sp）
SP_KEYWORDS = [
    "sp", "special", "specials", "ova", "oad", "ona", "extra", "extras",
    "bonus", "omake", "omakase", "recap", "summary", "making",
    "番外", "番外篇", "总集篇", "总集", "合集", "特典", "特别篇", "特别版",
    "特别映像", "映像特典", "未放送", "先行版", "先行放送", "预告", "预览",
    "前传", "幕后", "花絮", "总集編", "特別編", "映像特典", "ノベラ",
]
RE_SP_WORD = re.compile(r"(?<![A-Za-z])(" + "|".join(
    [re.escape(k) for k in SP_KEYWORDS if k.isascii() and len(k) <= 7]
) + r")(?![A-Za-z])", re.I)
RE_SP_CJK = re.compile("|".join(re.escape(k) for k in SP_KEYWORDS if not k.isascii()))


def is_special_keyword(name: str) -> List[str]:
    """文件名中命中的特别篇关键词。"""
    hits = [m.group(1).lower() for m in RE_SP_WORD.finditer(name or "")]
    hits += [m.group(0) for m in RE_SP_CJK.finditer(name or "")]
    return sorted(set(hits))


def cn_number(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.strip()
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        return CN_NUM.get(head, 1) * 10 + (CN_NUM.get(tail, 0) if tail else 0)
    return CN_NUM.get(text)


def season_from_dir(dir_name: str) -> Optional[int]:
    """从季目录名解析季号；识别不出返回 None（绝不 0 兜底）。"""
    name = (dir_name or "").strip()
    if not name:
        return None
    low = name.lower()
    if low in ("specials", "special", "season 0", "season 00", "s00", "s0",
               "特别篇", "特典", "番外", "sp"):
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
    """提取集号：SxxEyy > 第N集 > 1x02 > 纯数字前缀 > -NN- > 独立成词 NN。"""
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
    best = None
    for m in RE_LOOSE_EP.finditer(stem):
        val = int(m.group(1))
        if val == 0 or val > 999:
            continue
        if stem[m.end(1):m.end(1) + 1] in ("p", "P"):
            continue
        best = val
    return best


def split_ext(name: str) -> Tuple[str, str]:
    if "." not in name:
        return name, ""
    stem, _, ext = name.rpartition(".")
    return stem, f".{ext}"


# ---------------------------------------------------------------------------
# 判定：TMDB 匹配失败
# ---------------------------------------------------------------------------
@dataclass
class MatchProbe:
    """
    一次「TMDB 该季该集是否存在」的查询结果。
      found        —— TMDB 是否存在该集
      season_count —— 该季官方集数（用于交叉校验）
    """
    found: Optional[bool] = None      # None = 查不到（网络/接口失败），与「确认不存在」区分
    season_count: Optional[int] = None
    note: str = ""


def is_match_failure(probe: MatchProbe) -> bool:
    """
    「TMDB 查无该集」的确判定条件：

      ✓ 确认成立：found is False 且 season_count 有值（接口通、该季有效，
        但这一集不在 episodes 列表里）—— 这是唯一允许修正的条件。
      ✗ 不可判定：found is None（接口失败）→ 网络问题不是数据问题，
        绝不能据此改记录。
      ✗ 不成立：found is True（该集本来就有）→ 说明不是超集问题。
    """
    if probe.found is None:
        return False
    if probe.season_count is None or probe.season_count <= 0:
        return False       # 官方集数拿不到，无法确认边界，不能动
    return probe.found is False


# ---------------------------------------------------------------------------
# 判定：特别篇识别
# ---------------------------------------------------------------------------
@dataclass
class SpecialVerdict:
    is_special: bool
    confidence: float
    reasons: List[str] = field(default_factory=list)
    target_season: Optional[int] = None
    target_ep: Optional[int] = None
    s0_title: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_special": self.is_special,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
            "target_season": self.target_season,
            "target_ep": self.target_ep,
            "s0_title": self.s0_title,
        }


def judge_special(file_name: str,
                  probe: MatchProbe,
                  ep: Optional[int],
                  season: int,
                  s0_index: Dict[str, dict],
                  threshold: float = 0.5,
                  allow_s0_mapping: bool = True) -> SpecialVerdict:
    """
    综合判定是否特别篇，并给出修正目标。

    证据与权重：
      A. TMDB 查无该集          0.60（必要前提：不对应任何正片集）
      B. 文件名关键词            0.55（SP / OVA / 总集篇 / 特典 …）
      C. 命中 TMDB Season 0 标题 0.80（最强：官方就把它登记为特别篇）
      D. 超集越界（ep > 官方集数）0.30（辅助）

    判定为特别篇需同时满足：
      - 匹配失败（is_match_failure 为真）；
      - 置信度 >= threshold。
    """
    reasons: List[str] = []
    score = 0.0

    # A. 匹配失败前提
    match_failed = is_match_failure(probe)
    if match_failed:
        score += 0.60
        reasons.append(f"TMDB 未收录该集（官方该季共 {probe.season_count} 集）")
    elif probe.found is None:
        reasons.append("TMDB 查询失败（非确认缺失），不予处理")
    else:
        reasons.append("TMDB 存在该集，属正常正片，不处理")

    # B. 关键词
    kw = is_special_keyword(file_name)
    if kw:
        score += 0.55
        reasons.append("文件名含特别篇关键词：" + ", ".join(kw))

    # C. TMDB Season 0 标题匹配
    s0_title = None
    if s0_index and allow_s0_mapping:
        s0_title = match_s0_title(file_name, s0_index)
        if s0_title:
            score += 0.80
            reasons.append(f"标题匹配 TMDB Season 0「{s0_title}」")

    # D. 越界程度
    if ep is not None and probe.season_count and ep > probe.season_count:
        score += 0.30
        reasons.append(f"集号 E{ep:02d} 超出官方范围 E01-E{probe.season_count:02d}")

    score = min(score, 1.0)
    reasons.insert(0, f"置信度 {score:.2f}（阈值 {threshold:.2f}）")

    is_sp = bool(match_failed and score >= threshold)
    # 季数一律归 0（TMDB/媒体服务器规范的 Specials 季）
    target_season = 0 if is_sp else None
    target_ep = None
    if is_sp and s0_title:
        for num, item in (s0_index or {}).items():
            if (item or {}).get("name") == s0_title:
                try:
                    target_ep = int(num)
                except (TypeError, ValueError):
                    target_ep = None
                break

    return SpecialVerdict(
        is_special=is_sp,
        confidence=score,
        reasons=reasons,
        target_season=target_season,
        target_ep=target_ep,
        s0_title=s0_title,
    )


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[^\w一-鿿]+", "", s.lower())


def match_s0_title(file_name: str, s0_index: Dict[str, dict]) -> Optional[str]:
    """文件名与 Season 0 条目标题做归一化互查，取最长命中（更具体）。"""
    fn = _norm(split_ext(file_name)[0])
    if not fn:
        return None
    best = None
    for item in (s0_index or {}).values():
        t = _norm((item or {}).get("name") or "")
        if not t:
            continue
        if t in fn or (len(t) >= 4 and fn in t):
            if not best or len(t) > len(_norm(best.get("name") or "")):
                best = item
    return (best or {}).get("name") if best else None


# ---------------------------------------------------------------------------
# 修正规则
# ---------------------------------------------------------------------------
@dataclass
class FixPlan:
    """对一条整理记录的修正方案。"""
    logid: Optional[int] = None
    src: str = ""
    dest: str = ""
    title: str = ""
    tmdbid: Optional[int] = None
    old_season: Optional[int] = None
    old_episode: Optional[int] = None
    new_season: Optional[int] = None
    new_episode: Optional[int] = None
    new_stem: str = ""              # 期望 MP 生成的目标文件名（不含扩展名）
    verdict: Optional[SpecialVerdict] = None
    skip_reason: str = ""

    @property
    def actionable(self) -> bool:
        return bool(self.verdict and self.verdict.is_special and self.new_season is not None)


def next_special_ep(used: Dict[int, bool], prefer: Optional[int] = None) -> int:
    """
    Season 00 内的目标集号：
      - 有 TMDB 官方号且未被占用 -> 用官方号（与媒体服务器对齐）
      - 否则顺延到最小空位，绝不重号
    """
    taken = set(used.keys())
    if prefer is not None and prefer > 0 and prefer not in taken:
        return prefer
    n = 1
    while n in taken:
        n += 1
    return n


def build_special_stem(title: str, target_ep: int,
                       naming: str = "s00e") -> str:
    """
    生成 Season 00 内的目标文件名（不含扩展名）。

    naming:
      s00e   -> <标题> - S00E01（对齐 MP 默认 TV_RENAME_FORMAT）
      plain  -> <标题> - 第 1 集
    """
    safe = re.sub(r"\{tmdbid=\d+\}", "", title or "").strip()
    if naming == "plain":
        return f"{safe} - 第 {target_ep} 集"
    return f"{safe} - S00E{target_ep:02d}"


def parse_seasons_field(raw: str) -> Optional[int]:
    """TransferHistory.seasons 形如 '1'；解析不了返回 None。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    m = re.match(r"^S?(\d{1,3})$", s, re.I)
    return int(m.group(1)) if m else None


def parse_episodes_field(raw: str) -> Optional[int]:
    """
    TransferHistory.episodes 实际存的是**列表字符串**，例如 '[24]' 或 '[1, 2, 3]'。
    取最大集号作为该记录的集号；解析不了返回 None。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    if s.startswith("[") or s.startswith("{"):
        inner = s.strip("[]{} ")
        nums = [int(x) for x in re.findall(r"\d{1,4}", inner)]
        return max(nums) if nums else None
    m = re.search(r"(\d{1,4})", s)
    return int(m.group(1)) if m else None


def format_episodes_field(eps: List[int]) -> str:
    """写回 episodes 字段，统一用 '[n]' 形式（与 MP 内部一致）。"""
    return str(sorted(set(int(e) for e in eps if e is not None)))