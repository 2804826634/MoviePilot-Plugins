# -*- coding: utf-8 -*-
"""
TMDB 查询客户端（**仅用于判定匹配失败与取 Season 0 取证，不做刮削**）。

与常规 TMDB 客户端的差别在于「不把异常当不存在」：
    网络失败 / Key 无效 时必须能区分于「确认该集不存在」，
    否则会因网络抖动误改整理记录 —— 这是本插件最危险的误判来源。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import List, Optional

DEFAULT_DOMAINS = ["https://api.themoviedb.org/3", "https://api.tmdb.org/3"]
BUILTIN_KEY = "db55323b8d3e4154498498a75642b381"


class TMDBProbe:
    def __init__(self, api_key: str = "", domain: str = "",
                 locale: str = "zh-CN", retries: int = 3, proxy: str = None):
        self.api_key = (api_key or "").strip() or BUILTIN_KEY
        dom = (domain or "").strip()
        if dom:
            d = dom.rstrip("/")
            self.domains = [d] if d.endswith("/3") else [d + "/3"]
        else:
            self.domains = list(DEFAULT_DOMAINS)
        self.locale = locale or "zh-CN"
        self.retries = max(1, retries)
        self.proxy = proxy
        self.errors: List[str] = []
        self.retried = 0

    def _get(self, path: str) -> Optional[dict]:
        """
        返回 dict / None。
        关键：**None 只表示「取不到」**，绝不表示「不存在」。
        404/422 返回一个空字典哨兵，让上层能区分「确实没有这个资源」
        与「网络/Key 出问题」—— 两者绝不能混同，否则会误改记录。
        """
        last_exc = None
        for attempt in range(1, self.retries + 1):
            for base in self.domains:
                url = f"{base}{path}?api_key={self.api_key}&language={self.locale}"
                try:
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "MoviePilot-SpecialsFixer/1.0",
                        "Accept": "application/json",
                    })
                    opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy})
                    ) if self.proxy else urllib.request.build_opener()
                    with opener.open(req, timeout=20) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    if e.code == 401:
                        self.errors.append(f"{path} TMDB Key 无效(401)")
                        return None                    # Key 问题：不可判定
                    if e.code in (404, 422):
                        return {"_not_found": True}     # 确认不存在：哨兵
                    last_exc = f"HTTP {e.code}"
                    if e.code == 429:
                        self.retried += 1
                        time.sleep(5.0 * attempt)
                        break
                except Exception as e:
                    last_exc = f"{type(e).__name__}: {e}"
                    self.retried += 1
            if attempt < self.retries:
                time.sleep(2.0 * attempt)
        self.errors.append(f"{path} 取数失败：{last_exc}")
        return None

    def season_episodes(self, tmdbid: int, season: int) -> Optional[List[dict]]:
        """
        该季集数列表。
        返回 []    -> 官方确实没有该季（不是网络问题）
        返回 None  -> 取不到（网络/Key 问题）→ 上层必须跳过
        """
        data = self._get(f"/tv/{tmdbid}/season/{season}")
        if data is None:
            return None
        if data.get("_not_found"):
            return []
        eps = data.get("episodes") or []
        return eps if eps else []

    def season0_index(self, tmdbid: int) -> dict:
        """Season 0 条目索引 {'1': {...}}；取不到返回空 dict。"""
        eps = self.season_episodes(tmdbid, 0)
        if not eps:
            return {}
        return {str(e["episode_number"]): e
                for e in eps if e.get("episode_number") is not None}