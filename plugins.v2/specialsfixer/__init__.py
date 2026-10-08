# -*- coding: utf-8 -*-
"""
整理记录季/集修正（SpecialsFixer）

对「TMDB 查无该集」的整理记录，识别其是否为特别篇（SP / OVA / 特典 / 总集篇），
确认后把该记录的季数与集数改到 Season 00 与正确集号，并重新触发 MP 自身的
整理流程完成归位。

职责边界（严格遵守）：
  ✓ 只识别特别篇、只修正整理记录的季/集字段
  ✗ 不调用 TMDB 刮削、不写 NFO/图片等媒体元数据 —— 全部由 MP 自身机制完成

作者：peter_chen
版本：1.0.0
"""
from __future__ import annotations

import re
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

from . import fixer_core as core

PLUGIN_ID = "SpecialsFixer"


class SpecialsFixer(_PluginBase):
    plugin_name = "整理记录季集修正"
    plugin_desc = "对TMDB 查无该集的整理记录识别特别篇，修正季/集为 Season 00 并重新整理（刮削仍由 MP 完成）"
    plugin_icon = "specialsfixer.png"
    plugin_version = "1.0.0"
    plugin_author = "peter_chen"
    author_url = ""
    plugin_config_prefix = "specialsfixer_"
    plugin_order = 23
    user_level = 1

    DEFAULT_CONFIG = {
        "enabled": False,
        # 触发时机
        "trigger_on_transfer": True,      # 整理完成后检查该条记录
        "trigger_scheduled": True,        # 定时巡检历史记录
        "cron": "30 4 * * *",
        # 判定
        "threshold": 0.5,                 # 特别篇判定阈值
        "require_match_failure": True,    # 仅处理「确认查无该集」的记录
        "allow_s0_mapping": True,         # 允许用 TMDB Season 0 标题做证据
        "tolerance": 0,                   # 容差：官方集数 + N 之内视为正片
        # 修正规则
        "fix_mode": "auto",               # auto=改记录并重整 / dry=只改记录不重整 / report=只报告
        "target_season": 0,               # 目标季（0 = Season 00，TMDB 规范）
        "use_s0_episode": True,           # 优先沿用 TMDB Season 0 官方集号
        "naming": "s00e",                 # 目标文件名风格
        "keep_old_file": False,           # 重整时保留旧的已整理文件
        # 安全
        "auto_apply": False,              # 是否自动执行（关闭则一律只出报告，人工确认）
        "dry_run": True,
        "skip_failed_history": True,      # 跳过 status=False 的失败记录
        "scan_limit": 200,                # 单次巡检最多处理多少条
        "history_days": 30,               # 只巡检最近 N 天的记录
        # 通知
        "notify": True,
        "notify_only_when_changed": True,
        # TMDB（仅用于「查无该集」判定与 Season 0 取证，不做刮削）
        "tmdb_api_key": "",
        "tmdb_api_domain": "",
        "tmdb_locale": "zh-CN",
    }

    def __init__(self):
        super().__init__()
        self._cfg: Dict = {}
        self._last_result: List[dict] = []
        self._last_summary: str = ""

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def init_plugin(self, config: dict = None) -> None:
        cfg = dict(self.DEFAULT_CONFIG)
        cfg.update(config or {})
        self._cfg = cfg
        logger.info(f"[{PLUGIN_ID}] 初始化完成，fix_mode={cfg.get('fix_mode')}，"
                    f"auto_apply={cfg.get('auto_apply')}")

    def get_state(self) -> bool:
        return bool(self._cfg.get("enabled"))

    def stop_service(self) -> None:
        try:
            eventmanager.disable_events_hander(self.__class__.__name__)
        except Exception:
            pass

    def get_service(self) -> List[dict]:
        if not self.get_state() or not self._cfg.get("trigger_scheduled") or CronTrigger is None:
            return []
        cron = self._cfg.get("cron") or "30 4 * * *"
        try:
            trigger = CronTrigger.from_crontab(cron)
        except Exception:
            trigger = CronTrigger.from_crontab("30 4 * * *")
        return [{"id": PLUGIN_ID, "name": "整理记录季集修正 - 定时巡检",
                 "trigger": trigger, "func": self.scan_history, "kwargs": {}}]

    def get_command(self) -> List[Dict[str, str]]:
        return [
            {"label": "巡检历史记录（只报告）",
             "command": f"{PLUGIN_ID}_scan",
             "description": "扫描最近的历史整理记录，找出 TMDB 查无该集的可疑项"},
            {"label": "巡检并修正（按当前修正模式）",
             "command": f"{PLUGIN_ID}_fix",
             "description": "扫描并按 fix_mode 执行修正"},
        ]

    def get_api(self) -> List[Dict[str, str]]:
        return [
            {"path": "/scan", "method": "get", "func": "api_scan", "desc": "巡检历史记录"},
            {"path": "/fix", "method": "post", "func": "api_fix", "desc": "执行修正"},
            {"path": "/result", "method": "get", "func": "api_result", "desc": "获取最近结果"},
        ]

    def api_scan(self, days: int = None):
        return self.scan_history(days=days, apply=False)

    def api_fix(self, days: int = None):
        return self.scan_history(days=days, apply=True)

    def api_result(self):
        return {"summary": self._last_summary, "items": self._last_result}

    def get_page(self) -> List[dict]:
        rows = [{
            "记录ID": r.get("logid"),
            "剧集": r.get("title"),
            "原季/集": f"S{r.get('old_season')}E{r.get('old_episode')}",
            "官方集数": r.get("tmdb_count"),
            "判定": "特别篇" if r.get("is_special") else "非特别篇",
            "置信度": r.get("confidence"),
            "修正为": r.get("fix_text") or "—",
            "处理": r.get("action_text"),
            "依据": r.get("reason_text"),
        } for r in (self._last_result or [])]
        return [
            {"component": "VDataTable", "props": {
                "headers": [{"title": k, "key": k} for k in
                            ["记录ID", "剧集", "原季/集", "官方集数", "判定", "置信度", "修正为", "处理", "依据"]],
                "items": rows, "density": "compact", "hover": True}},
            {"component": "VAlert", "props": {
                "type": "info", "text": self._last_summary or "尚未巡检"}},
        ]

    def get_form(self) -> Tuple[List[dict], Dict]:
        default = dict(self.DEFAULT_CONFIG)
        form = [
            {"component": "VForm", "content": [
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "require_match_failure",
                            "label": "仅处理「确认查无该集」的记录"}},
                    ]},
                ]},
                {"component": "VAlert", "props": {
                    "type": "warning",
                    "text": "本插件只修正整理记录的季/集字段并重新触发 MP 整理，"
                            "不调用 TMDB 刮削、不写媒体元数据 —— 元数据仍由 MP 自身机制生成。",
                }},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "trigger_on_transfer", "label": "整理完成时检查该条记录"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "trigger_scheduled", "label": "定时巡检历史记录"}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VCronField", "props": {
                            "model": "cron", "label": "巡检周期"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "history_days", "label": "巡检最近天数", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "scan_limit", "label": "单次最多处理条数", "type": "number"}}]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "fix_mode", "label": "修正模式",
                            "items": [
                                {"title": "仅报告（不动任何东西）", "value": "report"},
                                {"title": "只改记录，不重新整理", "value": "dry"},
                                {"title": "改记录并重新整理（交给 MP 归位）", "value": "auto"},
                            ]}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "auto_apply", "label": "自动执行（关闭则需手动触发）"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "dry_run", "label": "预演（只展示将做什么，不改记录不重整）"}}]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "threshold", "label": "特别篇判定阈值",
                            "items": [
                                {"title": "0.60 均衡（推荐）", "value": 0.6},
                                {"title": "0.80 保守（需多项证据）", "value": 0.8},
                                {"title": "0.90 极保守", "value": 0.9},
                            ]}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "allow_s0_mapping", "label": "用 Season 0 标题作证据"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "tolerance", "label": "集数容差", "type": "number"}}]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "target_season", "label": "目标季号",
                            "hint": "0 = Season 00（TMDB/Plex 规范）", "type": "number"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "use_s0_episode", "label": "沿用 Season 0 官方集号"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "naming", "label": "目标文件名风格",
                            "items": [
                                {"title": "S00E01（对齐 MP 默认格式）", "value": "s00e"},
                                {"title": "第 1 集（中文）", "value": "plain"},
                            ]}}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "keep_old_file", "label": "重整时保留旧的已整理文件"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "skip_failed_history", "label": "跳过转移失败的记录"}}]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                        {"component": "VSwitch", "props": {"model": "notify", "label": "发送通知"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                        {"component": "VSwitch", "props": {
                            "model": "notify_only_when_changed",
                            "label": "仅在有实际修正时通知"}}]},
                ]},

                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "tmdb_api_key", "label": "TMDB API Key",
                            "placeholder": "留空 = 沿用 MoviePilot 配置"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VTextField", "props": {
                            "model": "tmdb_api_domain", "label": "TMDB 接口域名",
                            "placeholder": "留空 = 依次尝试官方两个域名"}}]},
                    {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                        {"component": "VSelect", "props": {
                            "model": "tmdb_locale", "label": "TMDB 返回语言",
                            "items": [
                                {"title": "简体中文", "value": "zh-CN"},
                                {"title": "繁体中文", "value": "zh-TW"},
                                {"title": "English", "value": "en-US"},
                                {"title": "日本語", "value": "ja-JP"},
                            ]}}]},
                ]},
            ]}
        ]
        return form, default

    # ------------------------------------------------------------------
    # 事件钩子
    # ------------------------------------------------------------------
    def __on_transfer_complete(self, event_data: dict) -> None:
        """
        整理完成后检查刚产生的记录。
        只处理电视剧类型；电影直接返回。
        """
        if not self.get_state() or not self._cfg.get("trigger_on_transfer"):
            return
        try:
            mediainfo = event_data.get("mediainfo")
            meta = event_data.get("meta")
            if mediainfo is None:
                return
            tmdbid = getattr(mediainfo, "tmdb_id", None)
            if not tmdbid:
                return
            # 只处理剧集
            mtype = getattr(mediainfo, "type", None)
            type_val = getattr(mtype, "value", None) or str(mtype)
            if "电影" in str(type_val):
                return
            season = getattr(meta, "season", None)
            episode = getattr(meta, "episode", None)
            src = getattr(getattr(event_data.get("transferinfo"), "path", None), "__str__", lambda: None)()
            client = self.__build_client()
            plan = self.__build_plan(
                logid=None, title=getattr(mediainfo, "title", "") or "",
                tmdbid=int(tmdbid), season=season, episode=episode,
                src=str(src or ""), dest="", client=client,
            )
            if plan and plan.verdict and plan.verdict.is_special:
                self.__handle(plan)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 整理完成事件处理失败：{e}\n{traceback.format_exc()}")

    # ------------------------------------------------------------------
    # 巡检
    # ------------------------------------------------------------------
    def scan_history(self, days: int = None, apply: bool = False) -> dict:
        """
        扫描历史整理记录，找出 TMDB 查无该集的可疑项。

        apply=False 时无论 fix_mode 是什么都只报告（安全默认）。
        """
        days = int(days or self._cfg.get("history_days") or 30)
        limit = int(self._cfg.get("scan_limit") or 200)
        client = self.__build_client()

        try:
            histories = self.__list_recent(days, limit)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 读取历史记录失败：{e}")
            return {"success": False, "message": f"读取历史记录失败：{e}"}

        logger.info(f"[{PLUGIN_ID}] 巡检最近 {days} 天的 {len(histories)} 条记录，"
                    f"apply={apply}")

        results: List[dict] = []
        fixed = 0
        for h in histories:
            if h.type != "电视剧" and str(h.type) != "TV":
                continue
            if self._cfg.get("skip_failed_history") and not h.status:
                continue
            tmdbid = h.tmdbid
            if not tmdbid:
                continue
            season = core.parse_seasons_field(h.seasons)
            episode = core.parse_episodes_field(h.episodes)
            if season is None or season == 0:
                continue          # 已是 Season 00 的跳过
            if episode is None:
                continue
            plan = self.__build_plan(
                logid=h.id, title=h.title, tmdbid=int(tmdbid),
                season=season, episode=episode,
                src=h.src, dest=h.dest, client=client,
            )
            if plan is None:
                continue
            if plan.verdict and plan.verdict.is_special and apply:
                self.__handle(plan)
                fixed += 1
            results.append(self.__to_row(plan))

        self._last_result = results
        summary = (f"巡检 {len(results)} 条可判定记录，"
                   f"识别特别篇 {sum(1 for r in results if r['is_special'])} 条"
                   + (f"，执行修正 {fixed} 条" if fixed else "，未执行修正"))
        self._last_summary = summary
        logger.info(f"[{PLUGIN_ID}] {summary}")
        self.__maybe_notify(results, summary, fixed, apply)
        return {"success": True, "message": summary, "items": results}

    # ------------------------------------------------------------------
    # 核心：构建修正方案
    # ------------------------------------------------------------------
    def __build_plan(self, logid, title, tmdbid, season, episode,
                     src, dest, client) -> Optional[core.FixPlan]:
        """判断一条记录是否该改季/集，并算出目标值。"""
        # 取该季官方集数与该集是否存在
        probe = self.__probe(tmdbid, season, episode, client)
        if not core.is_match_failure(probe):
            # 不是「确认查无该集」—— 网络失败或该集正常存在，都不动
            if probe.found is None:
                logger.debug(f"[{PLUGIN_ID}] {title} S{season}E{episode} "
                             f"TMDB 查询失败，跳过（不据网络问题改记录）")
            return None

        # 匹配失败成立 -> 判定是否特别篇
        file_name = Path(src).name if src else ""
        if not file_name:
            return None
        s0_index = client.season0_index(tmdbid) if self._cfg.get("allow_s0_mapping") else {}
        verdict = core.judge_special(
            file_name=file_name,
            probe=probe,
            ep=episode,
            season=season,
            s0_index=s0_index,
            threshold=float(self._cfg.get("threshold") or 0.6),
            allow_s0_mapping=bool(self._cfg.get("allow_s0_mapping", True)),
        )

        target_season = int(self._cfg.get("target_season") or 0)
        prefer = verdict.target_ep if self._cfg.get("use_s0_episode") else None
        used = self.__used_s00_eps(dest, src)
        target_ep = core.next_special_ep(used, prefer)

        return core.FixPlan(
            logid=logid, src=src, dest=dest, title=title, tmdbid=tmdbid,
            old_season=season, old_episode=episode,
            new_season=target_season if verdict.is_special else None,
            new_episode=target_ep if verdict.is_special else None,
            new_stem=core.build_special_stem(title, target_ep,
                                             self._cfg.get("naming") or "s00e"),
            verdict=verdict,
        )

    def __probe(self, tmdbid: int, season: int, episode: int, client) -> core.MatchProbe:
        """
        向 TMDB 确认「该季该集是否存在」。
        只用于判定匹配失败，**不做任何刮削**。

        三种结果必须严格区分（这是本插件最关键的正确性边界）：
          found=False          -> 确认该集不存在，可继续判定
          found=True           -> 该集正常存在，不处理
          found=None           -> 查询失败/官方无此季，绝不据此改记录
        """
        eps = client.season_episodes(tmdbid, season)
        if eps is None:
            return core.MatchProbe(found=None, season_count=None, note="季详情取不到（网络或 Key）")
        if not eps:
            # 官方没有这一季（或 Season 编号方式不同）—— 属于「不可判定」，
            # 因为无法确认官方集数边界，贸然改记录风险太高
            return core.MatchProbe(found=None, season_count=None, note="官方无此季数据")
        season_count = len(eps)
        found = any(int(e.get("episode_number") or -1) == int(episode) for e in eps)
        return core.MatchProbe(found=found, season_count=season_count,
                               note="该集存在" if found else "该集缺失")

    def __used_s00_eps(self, dest: str, src: str) -> Dict[int, bool]:
        """目标 Season 00 目录里已占用的集号（避免重号）。"""
        used: Dict[int, bool] = {}
        # dest 形如 .../Season 01/xxx.mkv —— 换算 Season 00 目录
        base = None
        if dest:
            p = Path(dest).parent
            if core.season_from_dir(p.name) is not None:
                base = p.parent / "Season 00"
        if base is None or not base.exists():
            return used
        try:
            for f in base.iterdir():
                if not f.is_file():
                    continue
                if f.suffix.lower() not in (".mkv", ".mp4", ".ts", ".avi", ".mov"):
                    continue
                ep = core.extract_episode_number(f.name)
                if ep:
                    used[ep] = True
        except (OSError, PermissionError):
            pass
        return used

    # ------------------------------------------------------------------
    # 执行修正
    # ------------------------------------------------------------------
    def __handle(self, plan: core.FixPlan) -> str:
        """
        执行修正。返回处理动作描述。
        严格遵守 fix_mode / auto_apply，不擅自越权。
        """
        mode = self._cfg.get("fix_mode") or "report"
        if mode == "report":
            return "仅报告（fix_mode=report）"
        if not self._cfg.get("auto_apply"):
            return "待确认（auto_apply 关闭）"
        if self._cfg.get("dry_run", True) and mode == "auto":
            # dry_run 只在 auto 模式下生效：展示将做什么但不落盘
            return f"预演：将 S{plan.old_season:02d}E{plan.old_episode:02d} " \
                   f"改为 S{plan.new_season:02d}E{plan.new_episode:02d} 并重新整理"

        # 1) 改记录
        ok = self.__update_history(plan)
        if not ok:
            return "记录修正失败"
        # 2) 重新整理（交给 MP 自身流程）
        if mode == "auto":
            self.__retransfer(plan)
            return f"已修正并重新整理：S{plan.new_season:02d}E{plan.new_episode:02d}"
        return f"已修正记录：S{plan.new_season:02d}E{plan.new_episode:02d}"

    def __update_history(self, plan: core.FixPlan) -> bool:
        """
        更新 TransferHistory 的 seasons / episodes 字段。
        只改季/集两个字段，不动其它任何数据。
        用 MP 原生 db_update 装饰器，与宿主其它插件写法一致（自动 commit/rollback）。
        """
        from app.db import db_update
        from app.db.models.transferhistory import TransferHistory

        @db_update
        def _do_update(db, logid: int, season: str, episode: str):
            h = db.query(TransferHistory).filter(TransferHistory.id == logid).first()
            if not h:
                return False
            h.seasons = season
            h.episodes = episode
            return True

        try:
            ok = _do_update(
                logid=plan.logid,
                season=str(plan.new_season),
                episode=core.format_episodes_field([plan.new_episode]),
            )
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 更新记录失败 logid={plan.logid}：{e}\n{traceback.format_exc()}")
            return False
        if ok:
            logger.info(
                f"[{PLUGIN_ID}] 记录 {plan.logid} 已更新："
                f"S{plan.old_season}E{plan.old_episode} -> S{plan.new_season}E{plan.new_episode}"
            )
        else:
            logger.warning(f"[{PLUGIN_ID}] 记录不存在 logid={plan.logid}")
        return bool(ok)

    def __retransfer(self, plan: core.FixPlan) -> bool:
        """
        调用 MP 自身的 TransferChain().manual_transfer 重新整理。

        这是「重新触发整理流程」的**官方入口**：
          - season=0            -> 覆盖季号，文件落到 Season 00 目录
          - EpisodeFormat.detail=目标集号 -> 强制按 S00Exx 识别集数
          - force=True          -> 允许重整已入库文件
          - scrape=True         -> 刮削交给 MP 自身机制，插件不碰元数据
        """
        try:
            from app.chain.transfer import TransferChain
            from app.schemas import MediaType
            from app.schemas.transfer import EpisodeFormat
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 无法导入 TransferChain：{e}")
            return False

        # 已入库的（dest 存在）优先用 dest 作为输入，这样文件被重新归位而不是重新复制一份
        in_path = Path(plan.dest) if plan.dest and Path(plan.dest).exists() else Path(plan.src)
        if not in_path.exists():
            logger.warning(f"[{PLUGIN_ID}] 源与目标路径均不存在，无法重新整理：{plan.src}")
            return False

        epformat = EpisodeFormat(
            format=None,
            detail=str(plan.new_episode),
            part=None,
            offset=0,
        )
        try:
            state, msg = TransferChain().manual_transfer(
                storage="local",
                in_path=in_path,
                filetype="file" if in_path.is_file() else "dir",
                tmdbid=plan.tmdbid,
                mtype=MediaType.TV,
                season=plan.new_season,
                epformat=epformat,
                scrape=True,          # 刮削由 MP 自身完成
                force=True,
            )
            if state:
                logger.info(f"[{PLUGIN_ID}] 重新整理成功：{in_path} -> "
                            f"S{plan.new_season:02d}E{plan.new_episode:02d}")
            else:
                logger.warning(f"[{PLUGIN_ID}] 重新整理失败：{in_path}：{msg}")
            return bool(state)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 重新整理异常：{e}\n{traceback.format_exc()}")
            return False

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def __list_recent(self, days: int, limit: int) -> list:
        """读取最近 N 天的整理记录。"""
        from app.db.models.transferhistory import TransferHistory
        import time
        since = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(time.time() - days * 86400))
        return TransferHistory.list_by_date(since)[:limit]

    def __build_client(self):
        def mp_setting(name, default=None):
            try:
                from app.core.config import settings
            except Exception:
                return default
            v = getattr(settings, name, None)
            if v is None or (isinstance(v, str) and not v.strip()):
                return default
            return v
        from . import tmdb_probe
        return tmdb_probe.TMDBProbe(
            api_key=self._cfg.get("tmdb_api_key") or mp_setting("TMDB_API_KEY", ""),
            domain=self._cfg.get("tmdb_api_domain") or "",
            locale=self._cfg.get("tmdb_locale") or mp_setting("TMDB_LOCALE", "zh-CN"),
            proxy=mp_setting("PROXY_HOST", None),
        )

    def __to_row(self, plan: core.FixPlan) -> dict:
        v = plan.verdict or core.SpecialVerdict(False, 0, [])
        return {
            "logid": plan.logid,
            "title": plan.title,
            "old_season": plan.old_season,
            "old_episode": plan.old_episode,
            "new_season": plan.new_season,
            "new_episode": plan.new_episode,
            "tmdb_count": v.reasons[0] if v.reasons else None,
            "is_special": v.is_special,
            "confidence": round(v.confidence, 2),
            "fix_text": f"S{plan.new_season:02d}E{plan.new_episode:02d}"
                        if v.is_special and plan.new_season is not None else "—",
            "action_text": "已处理" if v.is_special else "跳过",
            "reason_text": " | ".join(v.reasons[1:]) if v.reasons else "",
        }

    def __maybe_notify(self, results, summary, fixed, apply):
        if not self._cfg.get("notify"):
            return
        if self._cfg.get("notify_only_when_changed") and not fixed:
            return
        try:
            from app.schemas.types import NotificationType as NT
            title = "整理记录季集修正"
            lines = [summary]
            for r in results:
                if r["is_special"]:
                    lines.append(f"· {r['title']} S{r['old_season']:02d}E{r['old_episode']:02d}"
                                 f" -> {r['fix_text']}（置信度 {r['confidence']}）")
            self.post_message(mtype=NT.Plugin, title=title, text="\n".join(lines))
        except Exception as e:
            logger.warning(f"[{PLUGIN_ID}] 通知失败：{e}")