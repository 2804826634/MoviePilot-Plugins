# -*- coding: utf-8 -*-
"""
特别篇归位（SpecialsRelocate）

自动比对本地剧集集数与 TMDB 官方季集数，识别超出范围的剧集，
判定其是否属于特别篇（SP / OVA / 总集篇 / 番外），确认后按 Plex / TMDB
规范移入 Season 00 并重编号，正片不受影响。

作者：peter_chen
版本：1.0.0
"""
from __future__ import annotations

import os
import re
import threading
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.core.event import eventmanager

try:
    from apscheduler.triggers.cron import CronTrigger
except Exception:                                    # pragma: no cover
    CronTrigger = None

from . import core, fileops, tmdb as tmdb_mod

PLUGIN_ID = "SpecialsRelocate"


class SpecialsRelocate(_PluginBase):
    plugin_name = "特别篇归位"
    plugin_desc = "自动比对本地集数与 TMDB 官方季集数，识别超集剧集并判定特别篇，按 Plex 规范移入 Season 00"
    plugin_icon = "specialsrelocate.png"
    plugin_version = "1.0.0"
    plugin_author = "peter_chen"
    author_url = ""
    plugin_config_prefix = "specialsrelocate_"
    plugin_order = 22
    user_level = 1

    # 默认配置（每个 key 在 get_form 里都有对应控件）
    DEFAULT_CONFIG = {
        "enabled": False,
        "cron": "0 4 * * *",
        # 触发时机
        "trigger_on_transfer": True,      # 整理（转移）完成时自动检查
        "trigger_on_manually": True,      # 支持手动触发（命令）
        "auto_run_after_save": False,     # 保存配置后立即全量跑一次
        # 扫描范围
        "media_roots": "",                # 留空 = 自动用 MP 媒体库目录
        "exclude_paths": "",
        "min_confidence": 0.5,            # 特别篇判定置信度阈值
        "tolerance": 0,                   # 容差：官方集数 + N 以内都视为正片
        "detect_duration": True,          # 探测时长作为辅助证据
        "timeout_per_file": 20,
        # 动作开关
        "dry_run": True,                  # 预演：只出报告不落盘
        "do_move": True,                  # 移动文件到 Season 00
        "do_rename": True,                # 按 S00Exx 重命名
        "write_nfo": True,                # 写单集 NFO
        "s00_dir_style": "season",        # season=Season 00 / plain=Specials / cn=特别篇
        "cleanup_empty_season": False,    # 超集迁走后清理空的季目录
        # 通知
        "notify": True,
        "notify_only_when_changed": True,
        # TMDB
        "tmdb_api_key": "",               # 留空 = 沿用 MoviePilot 配置
        "tmdb_api_domain": "",
        "tmdb_locale": "zh-CN",
    }

    def __init__(self):
        super().__init__()
        self._cfg: Dict = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._last_result: List[dict] = []
        self._last_summary: str = ""

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def init_plugin(self, config: dict = None) -> None:
        cfg = dict(self.DEFAULT_CONFIG)
        cfg.update(config or {})
        self._cfg = cfg
        self._stop.clear()
        logger.info(f"[{PLUGIN_ID}] 初始化完成，dry_run={cfg.get('dry_run')}")
        if cfg.get("auto_run_after_save"):
            self._timer = threading.Timer(5, self.run_full_scan)
            self._timer.daemon = True
            self._timer.start()

    def get_state(self) -> bool:
        return bool(self._cfg.get("enabled"))

    def stop_service(self) -> None:
        self._stop.set()
        if self._timer:
            self._timer.cancel()
            self._timer = None
        try:
            from app.core.event import eventmanager as em
            em.disable_events_hander(self.__class__.__name__)
        except Exception:
            pass

    def get_service(self) -> List[dict]:
        if not self.get_state() or CronTrigger is None:
            return []
        cron = self._cfg.get("cron") or "0 4 * * *"
        try:
            trigger = CronTrigger.from_crontab(cron)
        except Exception:
            trigger = CronTrigger.from_crontab("0 4 * * *")
        return [{
            "id": PLUGIN_ID,
            "name": "特别篇归位 - 定时全量扫描",
            "trigger": trigger,
            "func": self.run_full_scan,
            "kwargs": {},
        }]

    # ------------------------------------------------------------------
    # 命令 / API / 页面
    # ------------------------------------------------------------------
    def get_command(self) -> List[Dict[str, str]]:
        return [
            {
                "label": "立即全量扫描媒体库",
                "command": f"{PLUGIN_ID}_scan",
                "description": "比对所有季目录的集数并识别超集",
            },
            {
                "label": "扫描并归位（忽略预演开关）",
                "command": f"{PLUGIN_ID}_apply",
                "description": "立刻执行移动与重命名",
            },
        ]

    def get_api(self) -> List[Dict[str, str]]:
        return [
            {
                "path": "/scan",
                "method": "get",
                "func": "api_scan",
                "desc": "触发一次全量扫描",
            },
            {
                "path": "/result",
                "method": "get",
                "func": "api_result",
                "desc": "获取最近一次扫描结果",
            },
        ]

    def api_scan(self, dry_run: bool = None, apply: bool = False):
        force_dry = self._cfg.get("dry_run", True) if dry_run is None else dry_run
        if apply:
            force_dry = False
        result = self.run_full_scan(dry_run=force_dry)
        return result

    def api_result(self):
        return {
            "summary": self._last_summary,
            "items": self._last_result,
        }

    def get_page(self) -> List[dict]:
        items = self._last_result or []
        rows = []
        for r in items:
            rows.append({
                "剧集": r.get("show", ""),
                "季": r.get("season", ""),
                "官方集数": r.get("tmdb_count", ""),
                "本地集数": r.get("local_count", ""),
                "超集": r.get("extras_text", ""),
                "判定": r.get("verdict_text", ""),
                "置信度": r.get("confidence", ""),
                "动作": r.get("action_text", ""),
                "原因": r.get("reason_text", ""),
            })
        return [
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": k, "key": k} for k in
                        ["剧集", "季", "官方集数", "本地集数", "超集", "判定", "置信度", "动作", "原因"]
                    ],
                    "items": rows,
                    "density": "compact",
                    "hover": True,
                },
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "text": self._last_summary or "尚未运行扫描",
                },
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict]:
        default = dict(self.DEFAULT_CONFIG)
        form = [
            {"component": "VForm", "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "enabled", "label": "启用插件"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "dry_run", "label": "预演模式（只出报告不落盘）"}},
                    ]},
                ]},
                {"component": "VAlert", "props": {
                    "type": "warning",
                    "text": "预演模式关闭后才会真正移动文件。建议先用预演跑一轮，"
                            "在下方「数据页面」确认判定结果无误后再关闭。",
                }},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "trigger_on_transfer",
                            "label": "整理完成时自动检查"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "trigger_on_manually",
                            "label": "允许手动触发"}},
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "auto_run_after_save",
                            "label": "保存后立即全量扫描一次"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VCronField", "props": {
                            "model": "cron", "label": "定时扫描（留空则每天凌晨4点）"}},
                    ]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "media_roots", "label": "媒体库根目录",
                            "placeholder": "留空 = 自动读取 MoviePilot 媒体库目录；多个用换行或逗号分隔"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "exclude_paths", "label": "排除路径",
                            "placeholder": "多个用逗号分隔，支持片段匹配"}},
                    ]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "min_confidence", "label": "特别篇判定阈值",
                            "items": [
                                {"title": "0.30 激进（多判为特别篇）", "value": 0.3},
                                {"title": "0.50 均衡（推荐）", "value": 0.5},
                                {"title": "0.70 保守（只动证据明确的）", "value": 0.7},
                                {"title": "0.85 极保守（仅文件名关键词命中）", "value": 0.85},
                            ]}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "tolerance", "label": "集数容差",
                            "type": "number",
                            "hint": "官方集数 + N 之内都当作正片。例：TMDB23集、本地24集，容差1则不动"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "detect_duration",
                            "label": "探测时长作为辅助证据（需 ffprobe，较慢）"}},
                    ]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "timeout_per_file", "label": "单文件探测超时（秒）",
                            "type": "number"}},
                    ]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "do_move", "label": "移动文件到 Season 00"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "do_rename", "label": "按 S00Exx 重命名"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "write_nfo", "label": "写入单集 NFO"}},
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "s00_dir_style", "label": "特别篇目录命名",
                            "items": [
                                {"title": "Season 00（Plex / TMDB 规范，推荐）", "value": "season"},
                                {"title": "Specials（Kodi 习惯）", "value": "plain"},
                                {"title": "特别篇（中文）", "value": "cn"},
                            ]}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "cleanup_empty_season",
                            "label": "超集迁走后删除空的季目录"}},
                    ]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "notify", "label": "发送通知"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "notify_only_when_changed",
                            "label": "仅在有实际变更时通知"}},
                    ]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "tmdb_api_key", "label": "TMDB API Key",
                            "placeholder": "留空 = 自动沿用 MoviePilot 的配置"}},
                    ]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "tmdb_api_domain", "label": "TMDB 接口域名",
                            "placeholder": "留空 = 自动依次尝试官方两个域名"}},
                    ]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "tmdb_locale", "label": "TMDB 返回语言",
                            "items": [
                                {"title": "简体中文", "value": "zh-CN"},
                                {"title": "繁体中文", "value": "zh-TW"},
                                {"title": "English", "value": "en-US"},
                                {"title": "日本語", "value": "ja-JP"},
                            ]}},
                    ]},
                ]},
            ]}
        ]
        return form, default

    # ------------------------------------------------------------------
    # 事件钩子：整理完成
    # ------------------------------------------------------------------
    def __on_transfer_complete(self, event_data: dict) -> None:
        """监听 TransferComplete：整理入库完成后触发一次针对该剧的检查。"""
        if not self.get_state():
            return
        if not self._cfg.get("trigger_on_transfer"):
            return
        try:
            mediainfo = event_data.get("mediainfo")
            transferinfo = event_data.get("transferinfo")
            meta = event_data.get("meta")
            if mediainfo is None:
                return
            tmdbid = getattr(mediainfo, "tmdb_id", None)
            season = getattr(meta, "season", None)
            path = getattr(transferinfo, "target_path", None)
            if not tmdbid or season is None or path is None:
                return
            self._stop.clear()
            self.check_one_season(
                show_title=getattr(mediainfo, "title", ""),
                tmdbid=int(tmdbid),
                season=int(season),
                season_dir=Path(path),
                dry_run=bool(self._cfg.get("dry_run", True)),
            )
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 整理完成事件处理失败：{e}\n{traceback.format_exc()}")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run_full_scan(self, dry_run: Optional[bool] = None) -> dict:
        """全量扫描配置的媒体库根目录。"""
        if dry_run is None:
            dry_run = bool(self._cfg.get("dry_run", True))
        with self._lock:
            self._stop.clear()
            roots = self._resolve_roots()
            if not roots:
                msg = "未配置媒体库目录，且未能自动读取 MoviePilot 媒体库目录"
                logger.warning(f"[{PLUGIN_ID}] {msg}")
                self._last_summary = msg
                return {"success": False, "message": msg}

            client = self._build_client()
            logger.info(f"[{PLUGIN_ID}] 开始全量扫描，根目录={roots}，dry_run={dry_run}")

            results: List[dict] = []
            moved_total = 0
            for root in roots:
                for show_dir in self.__iter_show_dirs(root):
                    if self._stop.is_set():
                        break
                    tmdbid = self.__tmdbid_of(show_dir)
                    if not tmdbid:
                        continue
                    show_title = show_dir.name
                    for season_dir in self.__iter_season_dirs(show_dir):
                        if self._stop.is_set():
                            break
                        r = self.check_one_season(
                            show_title=show_title,
                            tmdbid=tmdbid,
                            season=core.season_from_dir(season_dir.name),
                            season_dir=season_dir,
                            dry_run=dry_run,
                            client=client,
                        )
                        if r:
                            results.append(r)
                            moved_total += r.get("moved", 0)

            self._last_result = results
            summary = self.__summarize(results, client, moved_total, dry_run)
            self._last_summary = summary
            logger.info(f"[{PLUGIN_ID}] 扫描完成：{summary}")
            self.__maybe_notify(results, summary, moved_total, dry_run)
            return {"success": True, "message": summary, "items": results}

    def check_one_season(self, show_title: str, tmdbid: int,
                         season: Optional[int], season_dir: Path,
                         dry_run: bool = True,
                         client: tmdb_mod.TMDBClient = None) -> Optional[dict]:
        """
        检查单个季目录。season 解析不出来（或第0季）直接跳过 —— 绝不瞎猜。
        """
        if season is None or season_dir is None or not season_dir.exists():
            logger.debug(f"[{PLUGIN_ID}] 季号无法从目录名识别，跳过：{season_dir}")
            return None
        if season == 0:
            return None                          # 已经是特别篇目录，不处理
        if not season_dir.is_dir():
            return None

        client = client or self._build_client()

        files = fileops.list_media_files(season_dir)
        if not files:
            return None

        videos = [f for f in files if fileops.is_video(f)]
        if not videos:
            return None

        durations = {}
        if self._cfg.get("detect_duration"):
            durations = self.__probe_durations([season_dir / v for v in videos])

        local_eps = core.group_episodes(files, durations)
        real_eps = [e for e in local_eps if e.ep]
        if not real_eps:
            return None

        tmdb_count = client.season_episode_count(tmdbid, season)
        if tmdb_count is None:
            logger.warning(
                f"[{PLUGIN_ID}] {show_title} S{season:02d} 取不到 TMDB 官方集数，跳过"
            )
            return None

        tolerance = int(self._cfg.get("tolerance") or 0)
        extras = core.find_extras(real_eps, tmdb_count, tolerance)
        if not extras:
            return None

        # 正片中位时长（仅用正片算，排除超集自身）
        normal = [e for e in real_eps if e not in extras]
        normal_duration = core.median_duration(normal)

        # TMDB Season 0 索引 + 已占用的 S00 集号
        s0_index = client.season0_index(tmdbid)
        s00_dir = fileops.season00_dir(season_dir, self._cfg.get("s00_dir_style") or "season")
        assigned = self.__existing_s00(s00_dir)

        verdicts: List[core.Verdict] = []
        for ex in extras:
            v = core.judge_special(
                ep=ex,
                season=season,
                s0_index=s0_index,
                normal_duration=normal_duration,
                s0_duration=None,
                min_confidence=float(self._cfg.get("min_confidence") or 0.5),
            )
            # 优先沿用 TMDB Season 0 的官方集号
            if v.is_special and v.matched_s0_title:
                for num, item in s0_index.items():
                    if (item or {}).get("name") == v.matched_s0_title:
                        try:
                            v.target_ep = int(num)
                        except (TypeError, ValueError):
                            pass
                        break
            verdicts.append(v)

        # 执行移动
        moved = 0
        plans: List[str] = []
        do_move = bool(self._cfg.get("do_move", True))
        do_rename = bool(self._cfg.get("do_rename", True))
        for v in verdicts:
            if not v.is_special or v.action != "move":
                continue
            if not do_move:
                v.action = "report"
                plans.append(f"仅报告：{v.episode.display()} 判为特别篇（未开启移动）")
                continue
            ep_no = core.target_special_ep(assigned, v.target_ep)
            new_stem = self.__build_special_stem(show_title, season, ep_no, v, do_rename)
            if dry_run:
                v.action = "report"
                plans.append(
                    f"[预演] {v.episode.video} -> {s00_dir.name}/{new_stem}{Path(v.episode.video).suffix}"
                )
                continue
            try:
                moved_files = fileops.move_episode_group(
                    season_dir=season_dir,
                    target_dir=s00_dir,
                    video_name=v.episode.video,
                    sidecars=v.episode.sidecars,
                    new_stem=new_stem,
                )
                moved += len(moved_files)
                assigned[ep_no] = True
                v.action = "move"
                plans.append(
                    f"已移动 {v.episode.video} -> {s00_dir.name}/{new_stem}"
                    f"（{len(moved_files)} 个文件，含附属文件）"
                )
                if self._cfg.get("write_nfo"):
                    self.__write_s00_nfo(
                        s00_dir, new_stem, show_title, ep_no, v, s0_index
                    )
            except Exception as e:
                logger.error(f"[{PLUGIN_ID}] 移动失败 {v.episode.video}: {e}\n{traceback.format_exc()}")
                v.action = "skip"
                plans.append(f"移动失败：{v.episode.video} -> {e}")

        # 迁完后的空季目录
        if (moved and self._cfg.get("cleanup_empty_season")
                and not dry_run
                and fileops.clean_empty_season_dir(season_dir)):
            try:
                season_dir.rmdir()
                plans.append(f"季目录已空并被删除：{season_dir.name}")
            except OSError:
                pass

        sp_list = [v for v in verdicts if v.is_special]
        other_list = [v for v in verdicts if not v.is_special]
        result = {
            "show": show_title,
            "tmdb_id": tmdbid,
            "season": season,
            "season_dir": str(season_dir),
            "tmdb_count": tmdb_count,
            "local_count": len(real_eps),
            "moved": moved,
            "extras_text": ", ".join(v.episode.display() for v in verdicts),
            "verdict_text": (
                f"特别篇 {len(sp_list)} 集 / 未确认 {len(other_list)} 集"
                if sp_list or other_list else "无"
            ),
            "confidence": max([v.confidence for v in verdicts], default=0),
            "action_text": "已归位" if moved else ("预演" if dry_run else "仅报告"),
            "reason_text": " | ".join(
                f"{v.episode.display()}: {v.reasons[-1] if v.reasons else '-'}"
                for v in verdicts
            ),
            "plans": plans,
            "details": [v.to_dict() for v in verdicts],
        }
        logger.info(
            f"[{PLUGIN_ID}] {show_title} S{season:02d}："
            f"TMDB {tmdb_count} 集 / 本地 {len(real_eps)} 集 / "
            f"超集 {[v.episode.display() for v in verdicts]} / "
            f"判定特别篇 {[v.episode.display() for v in sp_list]}"
        )
        return result

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _build_client(self) -> tmdb_mod.TMDBClient:
        def mp_setting(name, default=None):
            try:
                from app.core.config import settings
            except Exception:
                return default
            v = getattr(settings, name, None)
            if v is None or (isinstance(v, str) and not v.strip()):
                return default
            return v

        return tmdb_mod.TMDBClient(
            api_key=self._cfg.get("tmdb_api_key") or mp_setting("TMDB_API_KEY", ""),
            domain=self._cfg.get("tmdb_api_domain") or "",
            locale=self._cfg.get("tmdb_locale") or mp_setting("TMDB_LOCALE", "zh-CN"),
            proxy=mp_setting("PROXY_HOST", None),
        )

    def _resolve_roots(self) -> List[Path]:
        raw = (self._cfg.get("media_roots") or "").strip()
        roots: List[Path] = []
        if raw:
            for line in re.split(r"[\n,;]+", raw):
                p = Path(line.strip())
                if p.is_dir():
                    roots.append(p.resolve())
                else:
                    logger.warning(f"[{PLUGIN_ID}] 媒体库路径不存在：{line.strip()}")
            return roots

        # 自动读取 MP 媒体库目录
        try:
            from app.chain.media import MediaChain
            for lib in MediaChain().library.list():  # type: ignore[attr-defined]
                p = Path(lib)
                if p.is_dir():
                    roots.append(p.resolve())
        except Exception as e:
            logger.debug(f"[{PLUGIN_ID}] 自动读取媒体库目录失败：{e}")
        if not roots:
            try:
                from app.core.config import settings
                lp = getattr(settings, "LIBRARY_PATHS", None)
                if lp:
                    for line in re.split(r"[\n,;]+", str(lp)):
                        p = Path(line.strip())
                        if p.is_dir():
                            roots.append(p.resolve())
            except Exception:
                pass
        # 去重
        seen, uniq = set(), []
        for p in roots:
            rp = os.path.realpath(p)
            if rp not in seen:
                seen.add(rp)
                uniq.append(p)
        return uniq

    def __excluded(self, path: Path) -> bool:
        raw = (self._cfg.get("exclude_paths") or "").strip()
        if not raw:
            return False
        sp = str(path)
        for frag in re.split(r"[\n,;]+", raw):
            f = frag.strip()
            if f and f in sp:
                return True
        return False

    def __iter_show_dirs(self, root: Path):
        """剧集根目录下一层为剧目录（第二层是季目录）。"""
        try:
            entries = sorted(p for p in root.iterdir() if p.is_dir())
        except (PermissionError, OSError):
            return
        for show_dir in entries:
            if self.__excluded(show_dir):
                continue
            # 剧目录应至少有一个季目录子项
            try:
                if any(c.is_dir() and core.season_from_dir(c.name) is not None
                       for c in show_dir.iterdir()):
                    yield show_dir
            except (PermissionError, OSError):
                continue

    def __iter_season_dirs(self, show_dir: Path):
        try:
            entries = sorted(p for p in show_dir.iterdir() if p.is_dir())
        except (PermissionError, OSError):
            return
        for season_dir in entries:
            if self.__excluded(season_dir):
                continue
            if core.season_from_dir(season_dir.name) is None:
                continue
            yield season_dir

    def __tmdbid_of(self, show_dir: Path) -> Optional[int]:
        """从剧目录名 {tmdbid=xxx} 或 tvshow.nfo 里取剧集 id。"""
        m = core.RE_TMDBID_DIR.search(show_dir.name)
        if m:
            return int(m.group(1))
        nfo = show_dir / "tvshow.nfo"
        if nfo.exists():
            try:
                m = core.RE_TMDBID_NFO.search(nfo.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    return int(m.group(1))
            except (OSError, UnicodeDecodeError):
                pass
        return None

    def __existing_s00(self, s00_dir: Path) -> Dict[int, bool]:
        """Season 00 目录里已占用的集号。"""
        used: Dict[int, bool] = {}
        if not s00_dir.exists():
            return used
        for f in fileops.list_media_files(s00_dir):
            if not fileops.is_video(f):
                continue
            ep = core.extract_episode_number(f)
            if ep:
                used[ep] = True
        return used

    def __build_special_stem(self, show_title: str, season: int, ep_no: int,
                             v: core.Verdict, do_rename: bool) -> str:
        """
        生成 Season 00 内的目标文件名（不含扩展名）。
        对齐 MP 的 TV_RENAME_FORMAT 风格：<标题> - S00E01 - 第 1 集
        """
        if not do_rename:
            return Path(v.episode.video).stem
        safe_title = re.sub(r"\{tmdbid=\d+\}", "", show_title).strip()
        return f"{safe_title} - S00E{ep_no:02d}"

    def __write_s00_nfo(self, s00_dir: Path, stem: str, show_title: str,
                        ep_no: int, v: core.Verdict, s0_index: dict) -> None:
        """为迁入 Season 00 的单集写 NFO，season 固定 0。"""
        item = {}
        if v.matched_s0_title:
            for it in s0_index.values():
                if (it or {}).get("name") == v.matched_s0_title:
                    item = it
                    break
        content = fileops.build_episode_nfo(
            title=show_title,
            season=0,
            episode=ep_no,
            episode_title=item.get("name") or v.episode.display(),
            overview=item.get("overview"),
            air_date=item.get("air_date"),
            runtime=item.get("runtime"),
            show_title=show_title,
        )
        suffix = "".join(Path(v.episode.video).suffixes)
        nfo_path = s00_dir / f"{stem}{suffix}.nfo"
        if fileops.write_nfo(nfo_path, content):
            logger.info(f"[{PLUGIN_ID}] 已写入 NFO：{nfo_path.name}")

    def __probe_durations(self, videos: List[Path]) -> Dict[str, int]:
        """用 ffprobe 探测时长（秒）。失败静默跳过，不影响主流程。"""
        import shutil as _sh
        import subprocess
        ffprobe = _sh.which("ffprobe")
        if not ffprobe:
            logger.info(f"[{PLUGIN_ID}] 未找到 ffprobe，跳过时长相证据")
            return {}
        out: Dict[str, int] = {}
        timeout = int(self._cfg.get("timeout_per_file") or 20)
        for p in videos:
            if self._stop.is_set():
                break
            try:
                r = subprocess.run(
                    [ffprobe, "-v", "quiet", "-print_format", "json",
                     "-show_format", str(p)],
                    capture_output=True, timeout=timeout,
                )
                if r.returncode == 0:
                    data = json.loads(r.stdout.decode("utf-8", errors="ignore"))
                    dur = float((data.get("format") or {}).get("duration") or 0)
                    if dur > 0:
                        out[p.name] = int(dur)
            except Exception:
                continue
        return out

    def __summarize(self, results: List[dict], client, moved_total: int,
                    dry_run: bool) -> str:
        sp_total = 0
        report_total = 0
        for r in results:
            for d in r.get("details", []):
                if d.get("is_special"):
                    sp_total += 1
                else:
                    report_total += 1
        parts = [
            f"检查 {len(results)} 个季目录",
            f"识别超集 {sp_total + report_total} 集",
            f"判定特别篇 {sp_total} 集",
        ]
        if report_total:
            parts.append(f"未确认 {report_total} 集（仅报告）")
        if moved_total:
            parts.append(f"移动 {moved_total} 个文件")
        elif dry_run and sp_total:
            parts.append("预演模式未落盘")
        if client.retried:
            parts.append(f"网络抖动重试 {client.retried} 次")
        if client.errors:
            parts.append(f"取数失败 {len(client.errors)} 项")
        return "；".join(parts)

    def __maybe_notify(self, results: List[dict], summary: str,
                       moved_total: int, dry_run: bool) -> None:
        if not self._cfg.get("notify"):
            return
        if self._cfg.get("notify_only_when_changed") and not results:
            return
        try:
            from app.schemas.types import NotificationType as NotifyType
            title = "特别篇归位 · 预演报告" if dry_run else "特别篇归位完成"
            lines = [summary]
            for r in results[:10]:
                lines.append(f"· {r['show']} S{r['season']:02d}：{r['verdict_text']}；{r['action_text']}")
                for p in (r.get("plans") or [])[:3]:
                    lines.append(f"    {p}")
            if len(results) > 10:
                lines.append(f"…另有 {len(results) - 10} 个季目录，详见插件数据页")
            self.post_message(mtype=NotifyType.Plugin, title=title, text="\n".join(lines))
        except Exception as e:
            logger.warning(f"[{PLUGIN_ID}] 通知发送失败：{e}")


import json      # noqa: E402  （__probe_durations 使用）