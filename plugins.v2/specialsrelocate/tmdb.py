# -*- coding: utf-8 -*-
"""
TMDB 查询客户端。

要点（来自国内实测踩坑）：
  - 域名可配：api.themoviedb.org 常被拦，api.tmdb.org 一般仍可达；
    只给域名时自动补 /3。
  - 401 直接抛错（Key 无效，重试无意义）；404/422 不重试；429 多等；
    SSL 超时等网络异常退避重试。
  - 集数取季详情接口 episodes 数组的**实际长度**，不信任 TMDB 的
    number_of_episodes 汇总字段（部分条目该字段缺失或不准）。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import List, Optional

DEFAULT_DOMAINS = ["https://api.themoviedb.org/3", "https://api.tmdb.org/3"]
BUILTIN_KEY = "db55323b8d3e4154498498a75642b381"   # MP 内置默认 Key


class TMDBClient:
    def __init__(self, api_key: str = "", domain: str = "",
                 locale: str = "zh-CN", retries: int = 3, proxy: str = None):
        self.api_key = (api_key or "").strip() or BUILTIN_KEY
        dom = (domain or "").strip()
        if dom:
            if dom.rstrip("/").endswith("/3"):
                self.domains = [dom.rstrip("/")]
            else:
                self.domains = [dom.rstrip("/") + "/3"]
        else:
            self.domains = list(DEFAULT_DOMAINS)
        self.locale = locale or "zh-CN"
        self.retries = max(1, retries)
        self.proxy = proxy
        self.errors: List[str] = []
        self.retried = 0

    # -- 底层请求 ---------------------------------------------------------
    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        last_exc = None
        for attempt in range(1, self.retries + 1):
            for base in self.domains:
                url = f"{base}{path}"
                if params:
                    q = "&".join(f"{k}={v}" for k, v in params.items())
                    url = f"{url}?{q}"
                try:
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "MoviePilot-SpecialsRelocate/1.0",
                        "Accept": "application/json",
                    })
                    opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy})
                    ) if self.proxy else urllib.request.build_opener()
                    with opener.open(req, timeout=20) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    if e.code == 401:
                        raise RuntimeError("TMDB API Key 无效（401）")
                    if e.code in (404, 422):
                        return None          # 资源不存在，不重试
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

    # -- 业务方法 ---------------------------------------------------------
    def season_detail(self, tmdbid: int, season: int) -> Optional[dict]:
        """季详情：含 episodes 全量列表。"""
        return self._get(f"/tv/{tmdbid}/season/{season}",
                         {"api_key": self.api_key, "language": self.locale})

    def season_episode_count(self, tmdbid: int, season: int) -> Optional[int]:
        """
        该季官方集数 = episodes 数组长度。
        拿不到返回 None（调用方必须跳过，不能当 0 用）。
        """
        data = self.season_detail(tmdbid, season)
        if not data:
            return None
        eps = data.get("episodes") or []
        return len(eps) if eps else None

    def season_episodes(self, tmdbid: int, season: int) -> List[dict]:
        data = self.season_detail(tmdbid, season)
        if not data:
            return []
        return data.get("episodes") or []

    def season0_index(self, tmdbid: int) -> dict:
        """Season 0（特别篇）条目索引：{'1': {...}, '2': {...}}。"""
        out = {}
        for it in self.season_episodes(tmdbid, 0):
            n = it.get("episode_number")
            if n is not None:
                out[str(n)] = it
        return out

    def tv_detail(self, tmdbid: int) -> Optional[dict]:
        return self._get(f"/tv/{tmdbid}",
                         {"api_key": self.api_key, "language": self.locale})