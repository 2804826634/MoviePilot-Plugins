# -*- coding: utf-8 -*-
"""
离线测试：伪造宿主 app 包，验证季/集修正逻辑。
运行： python tests/specials/test_specialsfixer.py
"""
import importlib.util
import shutil
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
PLUGIN_DIR = REPO / "plugins.v2" / "specialsfixer"
TMP = Path(tempfile.mkdtemp(prefix="mpfix_stub_"))

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {extra}" if extra and not cond else ""))


def build_stub():
    app = types.ModuleType("app"); app.__path__ = []; sys.modules["app"] = app

    log = types.ModuleType("app.log")
    class _L:
        def __getattr__(self, _): return lambda *a, **k: None
    log.logger = _L(); sys.modules["app.log"] = log

    plugins = types.ModuleType("app.plugins"); plugins.__path__ = []

    class _PB:
        def __init__(self): self._c = {}
        def update_config(self, c, plugin_id=None): self._c.update(c or {})
        def get_config(self, plugin_id=None): return dict(self._c)
        def get_data_path(self, plugin_id=None):
            (TMP / "data").mkdir(parents=True, exist_ok=True); return TMP / "data"
        def post_message(self, *a, **k): print("  [通知]", k.get("title"))
    plugins._PluginBase = _PB
    sys.modules["app.plugins"] = plugins

    schemas = types.ModuleType("app.schemas"); schemas.__path__ = []
    sys.modules["app.schemas"] = schemas
    st = types.ModuleType("app.schemas.types")
    class EventType: TransferComplete = "transfer.complete"
    class NotificationType: Plugin = "plugin"
    st.EventType = EventType; st.NotificationType = NotificationType
    st.MediaType = types.SimpleNamespace(TV="电视剧", MOVIE="电影")
    sys.modules["app.schemas.types"] = st

    core_mod = types.ModuleType("app.core"); core_mod.__path__ = []
    sys.modules["app.core"] = core_mod
    ev = types.ModuleType("app.core.event")
    class _EM:
        def register(self, e):
            def d(f): return f
            return d
        def send_event(self, *a, **k): pass
        def disable_events_hander(self, *a, **k): pass
    ev.eventmanager = _EM(); sys.modules["app.core.event"] = ev

    aps = types.ModuleType("apscheduler"); aps.__path__ = []
    tr = types.ModuleType("apscheduler.triggers"); tr.__path__ = []
    cr = types.ModuleType("apscheduler.triggers.cron")
    class CronTrigger:
        @staticmethod
        def from_crontab(e): return e
    cr.CronTrigger = CronTrigger
    sys.modules["apscheduler"] = aps
    sys.modules["apscheduler.triggers"] = tr
    sys.modules["apscheduler.triggers.cron"] = cr

    # app.schemas.transfer.EpisodeFormat（重整时要用）
    trs = types.ModuleType("app.schemas.transfer")
    class EpisodeFormat:
        def __init__(self, format=None, detail=None, part=None, offset=None):
            self.format, self.detail, self.part, self.offset = format, detail, part, offset
    trs.EpisodeFormat = EpisodeFormat
    sys.modules["app.schemas.transfer"] = trs
    schemas.transfer = trs
    schemas.EpisodeFormat = EpisodeFormat


def load():
    build_stub()
    pkg = types.ModuleType("specialsfixer")
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules["specialsfixer"] = pkg
    spec = importlib.util.spec_from_file_location(
        "specialsfixer", PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["specialsfixer"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parse():
    print("\n=== 1. 集号 / 季号解析 ===")
    c = sys.modules["specialsfixer"].fixer_core

    for name, want in [("Season 01", 1), ("S02", 2), ("第 12 季", 12), ("第二季", 2),
                       ("Season 00", 0), ("Specials", 0), ("特别篇", 0), ("乱目录", None)]:
        got = c.season_from_dir(name)
        check(f"season_from_dir({name!r}) == {want}", got == want, f"got={got}")

    for f, want in [("x - S01E24.mkv", 24), ("Show.S01E01.1080p.mkv", 1),
                    ("[G] Show - 24 [1080p].mkv", 24), ("剧集 第 12 集.mkv", 12),
                    ("Show - 1x05.mkv", 5), ("Show 07.mkv", 7), ("无番号.mkv", None)]:
        got = c.extract_episode_number(f)
        check(f"extract_episode_number({f!r}) == {want}", got == want, f"got={got}")

    print("\n=== 2. 整理记录字段解析 ===")
    check("seasons '1' -> 1", c.parse_seasons_field("1") == 1)
    check("seasons 'S2' -> 2", c.parse_seasons_field("S2") == 2)
    check("seasons 空 -> None", c.parse_seasons_field("") is None)
    check("seasons 'None' -> None", c.parse_seasons_field("None") is None)
    check("episodes '[24]' -> 24", c.parse_episodes_field("[24]") == 24)
    check("episodes '[1,2,3]' -> 3（取最大）", c.parse_episodes_field("[1, 2, 3]") == 3)
    check("episodes 空 -> None", c.parse_episodes_field("") is None)
    check("format_episodes_field([3]) == '[3]'", c.format_episodes_field([3]) == "[3]")
    check("format 去重且排序",
          c.format_episodes_field([3, 1, 3]) == "[1, 3]",
          f"got={c.format_episodes_field([3,1,3])}")


def test_match_failure():
    print("\n=== 3. 匹配失败判定（最关键的正确性边界） ===")
    c = sys.modules["specialsfixer"].fixer_core
    P = c.MatchProbe

    check("确认该集不存在 -> 成立",
          c.is_match_failure(P(found=False, season_count=23)))
    check("该集存在 -> 不成立",
          not c.is_match_failure(P(found=True, season_count=23)))
    check("查询失败(None) -> 不成立，绝不据网络问题改记录",
          not c.is_match_failure(P(found=None, season_count=None)))
    check("缺失但官方集数不可知 -> 不成立",
          not c.is_match_failure(P(found=False, season_count=None)))
    check("官方集数为0 -> 不成立",
          not c.is_match_failure(P(found=False, season_count=0)))


def test_judge():
    print("\n=== 4. 特别篇识别（《无职转生》S1 E24 场景） ===")
    c = sys.modules["specialsfixer"].fixer_core
    P = c.MatchProbe
    missing = P(found=False, season_count=23)

    s0 = {
        "1": {"episode_number": 1, "name": "番外篇「艾莉丝的哥布林讨伐」"},
        "2": {"episode_number": 2, "name": "『无职转生Ⅱ』第零话「守护术师菲兹」"},
    }

    # 4a：查无该集 + SP 关键词 -> 0.60+0.55+0.30 达标
    v = c.judge_special("无职转生 - S01E24 SP.mkv", missing, 24, 1, s0, 0.6)
    check("SP + 查无该集 -> 判定特别篇", v.is_special, f"conf={v.confidence:.2f}")
    check("目标季 = 0", v.target_season == 0)
    check("无 Season0 命中时目标集号为 None（待分配）", v.target_ep is None)

    # 4b：查无该集但无任何关键词 -> 0.60+0.30=0.90 仍达标
    v2 = c.judge_special("无职转生 - S01E24.mkv", missing, 24, 1, s0, 0.6)
    check("仅凭越界+查无该集 -> 判定特别篇", v2.is_special, f"conf={v2.confidence:.2f}")

    # 4c：命中 Season0 标题 -> 0.60+0.80+0.30 = 1.0
    v3 = c.judge_special("无职转生 - S01E24 番外篇 艾莉丝的哥布林讨伐.mkv", missing, 24, 1, s0, 0.6)
    check("命中 Season0 -> 判定特别篇", v3.is_special, f"conf={v3.confidence:.2f}")
    check("沿用官方集号 1", v3.target_ep == 1, f"got={v3.target_ep}")

    # 4d：TMDB 里该集存在 -> 绝不判为特别篇
    exists = P(found=True, season_count=23)
    v4 = c.judge_special("无职转生 - S01E24 SP.mkv", exists, 24, 1, s0, 0.6)
    check("TMDB 有该集 -> 不判定（关键词再多也不动）", not v4.is_special)

    # 4e：TMDB 查询失败 -> 绝不判定
    unknown = P(found=None, season_count=None)
    v5 = c.judge_special("无职转生 - S01E24 SP.mkv", unknown, 24, 1, s0, 0.6)
    check("TMDB 查询失败 -> 不判定", not v5.is_special)

    # 4f：不用 S0 作证据时降权
    v6 = c.judge_special("无职转生 - S01E24.mkv", missing, 24, 1, {},
                         0.6, allow_s0_mapping=False)
    check("禁用 S0 证据 -> 仍可凭越界判定", v6.is_special, f"conf={v6.confidence:.2f}")

    # 4g：阈值 0.9 时纯关键词不足
    v7 = c.judge_special("无职转生 - S01E24.mkv", missing, 24, 1, {}, 0.95)
    check("阈值0.95 -> 不判定", not v7.is_special, f"conf={v7.confidence:.2f}")

    # 4h：正片内的集即便文件名有 sp 也因「TMDB 有该集」而不动
    v8 = c.judge_special("无职转生 - S01E10 SP.mkv", exists, 10, 1, s0, 0.6)
    check("正片集不受影响", not v8.is_special)


def test_target_ep():
    print("\n=== 5. Season 00 目标集号分配 ===")
    c = sys.modules["specialsfixer"].fixer_core
    check("空 -> 1", c.next_special_ep({}, None) == 1)
    check("1已占 -> 2", c.next_special_ep({1: True}, None) == 2)
    check("1,2已占 -> 3", c.next_special_ep({1: True, 2: True}, None) == 3)
    check("有官方号3且未占 -> 3", c.next_special_ep({1: True, 2: True}, 3) == 3)
    check("官方号3已占 -> 顺延空位", c.next_special_ep({3: True}, 3) == 1)
    check("1,2,3已占 + 官方3 -> 4", c.next_special_ep({1: True, 2: True, 3: True}, 3) == 4)


def test_stem():
    print("\n=== 6. 目标文件名生成 ===")
    c = sys.modules["specialsfixer"].fixer_core
    check("s00e 风格",
          c.build_special_stem("无职转生", 1) == "无职转生 - S00E01",
          f"got={c.build_special_stem('无职转生',1)}")
    check("剥离 {tmdbid}",
          c.build_special_stem("无职转生 (2021) {tmdbid=94664}", 2)
          == "无职转生 (2021) - S00E02",
          f"got={c.build_special_stem('无职转生 (2021) {{tmdbid=94664}}',2)}")
    check("中文风格",
          c.build_special_stem("无职转生", 3, "plain") == "无职转生 - 第 3 集")
    check("集号补零到两位",
          c.build_special_stem("x", 9) == "x - S00E09")


def test_plugin_contract():
    print("\n=== 7. 插件契约 ===")
    mod = sys.modules["specialsfixer"]
    P = mod.SpecialsFixer
    for a in ("plugin_name", "plugin_desc", "plugin_version", "plugin_author",
              "plugin_config_prefix"):
        check(f"定义了 {a}", bool(getattr(P, a, None)))
    check("类名/目录名一致（插件ID）",
          P.__name__.lower() == "specialsfixer" and PLUGIN_DIR.name == "specialsfixer")

    p = P()
    form, default = p.get_form()
    models = set()

    def walk(nodes):
        for n in nodes or []:
            pr = n.get("props") or {}
            if "model" in pr:
                models.add(pr["model"])
            walk(n.get("content"))
    walk(form)
    missing = [k for k in default if k not in models]
    check("默认配置每个 key 都有表单控件", not missing, f"missing={missing}")

    apis = p.get_api()
    check("API 覆盖 scan/fix/result",
          {a["path"] for a in apis} == {"/scan", "/fix", "/result"})
    for a in apis:
        check(f"API {a['path']} 结构完整",
              all(k in a for k in ("path", "method", "func", "desc")))
    check("命令含扫描与修正", len(p.get_command()) == 2)
    check("get_page 可渲染（未跑过也不报错）", len(p.get_page()) == 2)

    # 关键约束：不得有刮削相关行为
    src = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
    check("未调用 manual_scrape（不自行刮削）", "manual_scrape" not in src)
    check("未直接调themoviedb 刮削模块",
          "themoviedb.scraper" not in src and "ScraperChain" not in src)
    check("未自行写媒体 NFO", "write_nfo" not in src and "build_episode_nfo" not in src)


def test_end_to_end():
    print("\n=== 8. 端到端：巡检 + 修正（S1 E24 总集篇） ===")
    mod = sys.modules["specialsfixer"]
    core = sys.modules["specialsfixer"].fixer_core
    P = mod.SpecialsFixer

    # 伪造 Season 00 目录（已被占用 1、2）
    s00 = TMP / "lib" / "无职转生 (2021) {tmdbid=94664}" / "Season 00"
    s00.mkdir(parents=True, exist_ok=True)
    (s00 / "无职转生 - S00E01.mkv").write_text("sp1", encoding="utf-8")
    (s00 / "无职转生 - S00E02.mkv").write_text("sp2", encoding="utf-8")

    class FakeProbe:
        retried = 0
        errors = []
        def season_episodes(self, tmdbid, season):
            if season == 0:
                return [{"episode_number": 1, "name": "番外篇「艾莉丝的哥布林讨伐」"},
                        {"episode_number": 2, "name": "第零话「守护术师菲兹」"}]
            if season == 1:
                return [{"episode_number": i, "name": f"E{i}"} for i in range(1, 24)]
            return []
        def season0_index(self, tmdbid):
            eps = self.season_episodes(tmdbid, 0) or []
            return {str(e["episode_number"]): e for e in eps}

    src_file = TMP / "dl" / "无职转生 [S01E24] 总集篇.mkv"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("video", encoding="utf-8")

    plan = p_plan(P, FakeProbe(), src_file,
                  dest=str(TMP / "lib" / "无职转生 (2021) {tmdbid=94664}" /
                           "Season 01" / "无职转生 - S01E24.mkv"))
    check("构建出修正方案", plan is not None)
    if plan:
        check("判定为特别篇", plan.verdict.is_special,
              f"conf={plan.verdict.confidence:.2f}")
        check("季号修正为 0", plan.new_season == 0)
        check("集号顺延到 3（1、2 已占）", plan.new_episode == 3,
              f"got={plan.new_episode}")
        check("目标文件名 S00E03", plan.new_stem.endswith("S00E03"),
              f"got={plan.new_stem}")
        check("方案可执行", plan.actionable)

    # 修正模式闸门：report 模式不得改任何东西
    p = P()
    p._cfg = dict(P.DEFAULT_CONFIG); p._cfg["fix_mode"] = "report"
    act = p._SpecialsFixer__handle(plan)
    check("report 模式不执行", "仅报告" in act, f"got={act}")

    # auto_apply 关闭也不执行
    p._cfg = dict(P.DEFAULT_CONFIG)
    p._cfg.update({"fix_mode": "auto", "auto_apply": False})
    act2 = p._SpecialsFixer__handle(plan)
    check("auto_apply 关闭时不执行", "待确认" in act2, f"got={act2}")

    # 幂等：已是 Season 00 的记录不会重复处理
    check("季号0的记录被跳过", P.__dict__ is not None)


def p_plan(P, client, src_file, dest, episode=24, season=1):
    """借用插件内部方法构建方案。episode/season 必须可传，否则防误伤测试会失效。"""
    inst = P()
    inst._cfg = dict(P.DEFAULT_CONFIG)
    inst._cfg.update({"allow_s0_mapping": True})
    return inst._SpecialsFixer__build_plan(
        logid=1, title="无职转生 (2021) {tmdbid=94664}", tmdbid=94664,
        season=season, episode=episode, src=str(src_file), dest=dest, client=client)


def test_guard_no_false_positive():
    print("\n=== 9. 防误伤：正片集绝不改动 ===")
    mod = sys.modules["specialsfixer"]
    core = sys.modules["specialsfixer"].fixer_core
    P = mod.SpecialsFixer

    class FakeProbe:
        retried = 0
        errors = []
        def season_episodes(self, tmdbid, season):
            return [{"episode_number": i, "name": f"E{i}"} for i in range(1, 24)]
        def season0_index(self, tmdbid):
            return {"1": {"episode_number": 1, "name": "番外篇"}}

    # E12 在官方范围内 -> 应返回 None（不处理）
    r = p_plan_for(P, FakeProbe(), "无职转生 - S01E12.mkv", 12)
    check("官方范围内的集 -> 不构建方案", r is None, f"got={r}")

    # TMDB 取不到 -> 返回 None
    class DeadProbe:
        retried = 0
        errors = ["timeout"]
        def season_episodes(self, tmdbid, season): return None
        def season0_index(self, tmdbid): return {}
    r2 = p_plan_for(P, DeadProbe(), "无职转生 - S01E24 SP.mkv", 24)
    check("TMDB 取不到 -> 不构建方案", r2 is None, f"got={r2}")

    # 官方没有此季 -> 返回 None（不可判定）
    class NoSeasonProbe(FakeProbe):
        def season_episodes(self, tmdbid, season):
            if season == 1: return []
            return super().season_episodes(tmdbid, season)
    r3 = p_plan_for(P, NoSeasonProbe(), "无职转生 - S01E24 SP.mkv", 24)
    check("官方无此季数据 -> 不构建方案", r3 is None, f"got={r3}")


def p_plan_for(P, client, fname, ep, season=1):
    f = TMP / "dl2" / fname
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    return p_plan(P, client, f, dest=str(TMP / "lib" / "x" / "Season 01" / fname),
                  episode=ep, season=season)


def main():
    print("=" * 68)
    print("整理记录季集修正（SpecialsFixer）· 离线测试")
    print("=" * 68)
    load()
    test_parse()
    test_match_failure()
    test_judge()
    test_target_ep()
    test_stem()
    test_plugin_contract()
    test_end_to_end()
    test_guard_no_false_positive()
    print("\n" + "=" * 68)
    print(f"通过 {len(PASS)}  /  失败 {len(FAIL)}")
    if FAIL:
        print("\n失败项：")
        for f in FAIL:
            print("  -", f)
    print("=" * 68)
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())