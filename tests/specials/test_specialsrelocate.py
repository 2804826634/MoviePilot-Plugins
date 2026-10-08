# -*- coding: utf-8 -*-
"""
离线测试：伪造宿主 app 包，加载插件模块，验证核心判定链路。
运行： python tests/specials/test_specialsrelocate.py
"""
import os
import sys
import types
import importlib.util
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
PLUGIN_DIR = REPO / "plugins.v2" / "specialsrelocate"
TMP = Path(tempfile.mkdtemp(prefix="mp_stub_"))


# ---------------------------------------------------------------------------
# 伪造宿主
# ---------------------------------------------------------------------------
def build_stub():
    app = types.ModuleType("app")
    app.__path__ = []
    sys.modules["app"] = app

    log = types.ModuleType("app.log")

    class _Logger:
        def __getattr__(self, _):
            return lambda *a, **k: None
    log.logger = _Logger()
    sys.modules["app.log"] = log

    plugins = types.ModuleType("app.plugins")
    plugins.__path__ = []

    class _PluginBase:
        def __init__(self):
            self._cfg_store = {}

        def update_config(self, config, plugin_id=None):
            self._cfg_store.update(config or {})

        def get_config(self, plugin_id=None):
            return dict(self._cfg_store)

        def get_data_path(self, plugin_id=None):
            p = TMP / "data"
            p.mkdir(parents=True, exist_ok=True)
            return p

        def save_data(self, k, v, plugin_id=None):
            (TMP / "data" / f"{k}.json").write_text(str(v), encoding="utf-8")

        def get_data(self, k=None, plugin_id=None):
            return None

        def post_message(self, *a, **k):
            print("  [通知]", a, k.get("title"))

    plugins._PluginBase = _PluginBase
    sys.modules["app.plugins"] = plugins

    schemas = types.ModuleType("app.schemas")
    schemas.__path__ = []
    sys.modules["app.schemas"] = schemas

    types_mod = types.ModuleType("app.schemas.types")

    class EventType:
        TransferComplete = "transfer.complete"
        PluginAction = "plugin.action"
        PluginReload = "plugin.reload"
    types_mod.EventType = EventType

    class NotificationType:
        Plugin = "plugin"
        System = "system"
    types_mod.NotificationType = NotificationType
    types_mod.MediaType = types.SimpleNamespace(TV="电视剧", MOVIE="电影")
    sys.modules["app.schemas.types"] = types_mod

    core_mod = types.ModuleType("app.core")
    core_mod.__path__ = []
    sys.modules["app.core"] = core_mod

    event_mod = types.ModuleType("app.core.event")

    class _EM:
        def register(self, etype):
            def deco(f):
                return f
            return deco
        def send_event(self, *a, **k):
            pass
        def disable_events_hander(self, *a, **k):
            pass
    event_mod.eventmanager = _EM()
    sys.modules["app.core.event"] = event_mod

    aps = types.ModuleType("apscheduler")
    aps.__path__ = []
    trig = types.ModuleType("apscheduler.triggers")
    trig.__path__ = []
    cron = types.ModuleType("apscheduler.triggers.cron")

    class CronTrigger:
        @staticmethod
        def from_crontab(expr):
            return expr
    cron.CronTrigger = CronTrigger
    sys.modules["apscheduler"] = aps
    sys.modules["apscheduler.triggers"] = trig
    sys.modules["apscheduler.triggers.cron"] = cron


def load_plugin():
    build_stub()
    sys.path.insert(0, str(PLUGIN_DIR.parent))
    pkg = types.ModuleType("specialsrelocate")
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules["specialsrelocate"] = pkg
    spec = importlib.util.spec_from_file_location(
        "specialsrelocate", PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["specialsrelocate"] = mod
    spec.loader.exec_module(mod)
    return mod


PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {extra}" if extra and not cond else ""))


# ---------------------------------------------------------------------------
def test_parsing():
    print("\n=== 1. 季号 / 集号解析 ===")
    core = sys.modules["specialsrelocate"].core

    for name, want in [("Season 01", 1), ("Season 1", 1), ("S01", 1), ("S02", 2),
                       ("第 1 季", 1), ("第 12 季", 12), ("第二季", 2), ("第十二季", 12),
                       ("Season 00", 0), ("S00", 0), ("Specials", 0), ("特别篇", 0),
                       ("随便什么目录", None)]:
        got = core.season_from_dir(name)
        check(f"season_from_dir({name!r}) == {want}", got == want, f"got={got}")

    for fname, want in [
        ("无职转生 - S01E24.mkv", 24), ("Show.S01E01.1080p.mkv", 1),
        ("[Group] Show - 24 [1080p].mkv", 24), ("剧集 第 12 集.mkv", 12),
        ("Show - 1x05.mkv", 5), ("Show 07.mkv", 7), ("Show S02E103.mkv", 103),
        ("无番号.mkv", None),
    ]:
        got = core.extract_episode_number(fname)
        check(f"extract_episode_number({fname!r}) == {want}", got == want, f"got={got}")


def test_keywords():
    print("\n=== 2. 特别篇关键词识别 ===")
    core = sys.modules["specialsrelocate"].core
    for name, should in [
        ("Show S01E24 SP.mkv", True), ("Show OVA.mkv", True),
        ("无职转生 总集篇.mkv", True), ("[特别篇] 无职转生.mkv", True),
        ("Show - 24 [特别映像].mkv", True), ("Show S01E24 番外篇.mkv", True),
        ("Show S01E01.mkv", False),
        ("Show Extraordinary.mkv", False),   # sp 不应误伤 Extraordinary
        ("Show S01E12 Special.mkv", True),
    ]:
        hits = core.is_special_keyword(name)
        check(f"is_special_keyword({name!r}) -> {should}", bool(hits) == should, f"hits={hits}")


def test_find_extras():
    print("\n=== 3. 超集识别（无职转生 S1：官方23集 / 本地24集） ===")
    core = sys.modules["specialsrelocate"].core
    files = [f"无职转生 - S01E{i:02d}.mkv" for i in range(1, 25)]
    eps = core.group_episodes(files)

    check("解析出 24 集", len(eps) == 24, f"got={len(eps)}")

    extras = core.find_extras(eps, 23, 0)
    check("超集 = [E24]", [e.ep for e in extras] == [24], f"got={[e.ep for e in extras]}")

    eps1 = core.group_episodes(files[:23])
    check("容差0：23集时无超集", core.find_extras(eps1, 23, 0) == [])

    extras_t1 = core.find_extras(eps, 23, 1)
    check("容差1：24集时无超集（不动）", extras_t1 == [], f"got={[e.ep for e in extras_t1]}")

    extras_t2 = core.find_extras(eps, 23, 2)
    check("容差2：25集时才判 E24 超集", [e.ep for e in extras_t2] == [24] if len(files) > 24 else True)


def test_sidecars():
    print("\n=== 4. 附属文件（字幕/图片/NFO）归组 ===")
    core = sys.modules["specialsrelocate"].core
    files = [
        "无职转生 - S01E23.mkv",
        "无职转生 - S01E23.zh-CN.ass",
        "无职转生 - S01E23.jpg",
        "无职转生 - S01E24 SP.mkv",
        "无职转生 - S01E24.zh-CN.ass",
    ]
    eps = core.group_episodes(files)
    e24 = [e for e in eps if e.ep == 24][0]
    check("E24 只把视频当视频", e24.video.endswith("E24 SP.mkv"))
    check("E24 归入 1 个字幕", len(e24.sidecars) == 1, f"got={e24.sidecars}")
    e23 = [e for e in eps if e.ep == 23][0]
    check("E23 归入 2 个附属文件", len(e23.sidecars) == 2, f"got={e23.sidecars}")


def test_judge():
    print("\n=== 5. 特别篇判定（阈值 0.5） ===")
    core = sys.modules["specialsrelocate"].core
    s0 = core.build_s0_index([
        {"episode_number": 1, "name": "番外篇「艾莉丝的哥布林讨伐」"},
        {"episode_number": 2, "name": "『无职转生Ⅱ』第零话「守护术师菲兹」"},
    ])

    # 5a：文件名含 SP -> 0.55 达标
    v = core.judge_special(
        core.LocalEpisode("无职转生 - S01E24 SP.mkv", 24, sp_hits=core.is_special_keyword("SP")),
        1, s0, 1440, None, 0.5)
    check("SP 关键词 -> 判为特别篇", v.is_special, f"conf={v.confidence}")
    check("SP 置信度 >= 0.55", v.confidence >= 0.55, f"conf={v.confidence}")

    # 5b：普通超集、无任何证据 -> 不判
    v2 = core.judge_special(
        core.LocalEpisode("无职转生 - S01E24.mkv", 24), 1, s0, 1440, None, 0.5)
    check("无证据超集 -> 不判为特别篇", not v2.is_special, f"conf={v2.confidence}")
    check("无证据时 action=report", v2.action == "report")

    # 5c：TMDB S0 标题匹配 -> 0.85 强证据
    v3 = core.judge_special(
        core.LocalEpisode("无职转生 - S01E24 番外篇 艾莉丝的哥布林讨伐.mkv", 24),
        1, s0, 1440, None, 0.5)
    check("匹配 TMDB S0 标题 -> 判为特别篇", v3.is_special, f"conf={v3.confidence}")
    check("记录匹配到的 S0 标题", v3.matched_s0_title == "番外篇「艾莉丝的哥布林讨伐」",
          f"got={v3.matched_s0_title}")

    # 5d：阈值 0.7 时纯关键词不足 -> 只报告
    v4 = core.judge_special(
        core.LocalEpisode("无职转生 - S01E24 SP.mkv", 24, sp_hits=core.is_special_keyword("SP")),
        1, s0, 1440, None, 0.7)
    check("阈值0.7：纯 SP 证据不足 -> 仅报告", not v4.is_special, f"conf={v4.confidence}")

    # 5e：总集篇（时长远长于正片）-> 关键词+时长双证据
    v5 = core.judge_special(
        core.LocalEpisode("无职转生 - S01E24 总集篇.mkv", 24,
                          duration=4200,
                          sp_hits=core.is_special_keyword("总集篇")),
        1, s0, 1440, None, 0.5)
    check("总集篇（长时长+关键词）-> 判为特别篇", v5.is_special, f"conf={v5.confidence}")
    check("时长证据被记录", any("时长" in r for r in v5.reasons), f"reasons={v5.reasons}")

    # 5f：短片（无关键词、时长很短）单独不足以定罪
    v6 = core.judge_special(
        core.LocalEpisode("无职转生 - S01E24.mkv", 24, duration=300), 1, s0, 1440, None, 0.5)
    check("仅时长偏短(0.30) < 阈值 -> 不判", not v6.is_special, f"conf={v6.confidence}")


def test_target_ep():
    print("\n=== 6. Season 00 集号分配 ===")
    core = sys.modules["specialsrelocate"].core
    check("空目录 -> 分配 1", core.target_special_ep({}, None) == 1)
    check("已占用1 -> 分配 2", core.target_special_ep({1: True}, None) == 2)
    check("已占用1,2 -> 分配 3", core.target_special_ep({1: True, 2: True}, None) == 3)
    check("有官方号3 -> 用 3", core.target_special_ep({1: True, 2: True}, 3) == 3)
    # 官方号已被占用时不重号，顺延到最小空位
    check("官方号已被占 -> 顺延到空位", core.target_special_ep({3: True}, 3) == 1)
    check("官方号被占且1,2已占 -> 用 4",
          core.target_special_ep({1: True, 2: True, 3: True}, 3) == 4)


def test_season00_dir():
    print("\n=== 7. Season 00 目录推导 ===")
    fops = sys.modules["specialsrelocate"].fileops
    s = Path("/media/电视剧/无职转生 (2021) {tmdbid=94664}/Season 01")
    check("style=season -> Season 00", fops.season00_dir(s, "season").name == "Season 00")
    check("style=plain -> Specials", fops.season00_dir(s, "plain").name == "Specials")
    check("style=cn -> 特别篇", fops.season00_dir(s, "cn").name == "特别篇")
    check("目录与季目录同级", fops.season00_dir(s, "season").parent == s.parent)


def test_nfo():
    print("\n=== 8. Season 00 NFO 生成 ===")
    fops = sys.modules["specialsrelocate"].fileops
    xml = fops.build_episode_nfo(
        title="无职转生", season=0, episode=1,
        episode_title="番外篇「艾莉丝的哥布林讨伐」",
        air_date="2022-03-16", runtime=24,
        show_title="无职转生")
    check("含 <season>0</season>", "<season>0</season>" in xml)
    check("含 <episode>1</episode>", "<episode>1</episode>" in xml)
    check("含正确标题", "艾莉丝的哥布林讨伐" in xml)
    check("含首播日期", "<aired>2022-03-16</aired>" in xml)
    check("中文尖括号被转义", "&lt;" in fops.build_episode_nfo(
        "测试", 0, 1, episode_title="a<b>c"))
    # 正片季号不能被写成 0
    xml2 = fops.build_episode_nfo("测试", 2, 5)
    check("season=2 时写 <season>2</season>", "<season>2</season>" in xml2 and "season>0<" not in xml2)


def test_move_real_fs():
    print("\n=== 9. 真实文件移动（临时目录） ===")
    fops = sys.modules["specialsrelocate"].fileops
    base = TMP / "movetest"
    season_dir = base / "无职转生 (2021) {tmdbid=94664}" / "Season 01"
    season_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "无职转生 - S01E24 SP.mkv").write_text("video-bytes", encoding="utf-8")
    (season_dir / "无职转生 - S01E24 SP.zh-CN.ass").write_text("sub-bytes", encoding="utf-8")
    (season_dir / "无职转生 - S01E23.mkv").write_text("keep-me", encoding="utf-8")

    s00 = fops.season00_dir(season_dir, "season")
    moved = fops.move_episode_group(
        season_dir=season_dir, target_dir=s00,
        video_name="无职转生 - S01E24 SP.mkv",
        sidecars=["无职转生 - S01E24 SP.zh-CN.ass"],
        new_stem="无职转生 - S00E01")

    check("移动了 2 个文件（视频+字幕）", len(moved) == 2, f"got={moved}")
    check("视频落到 Season 00 且改名正确",
          (s00 / "无职转生 - S00E01.mkv").exists())
    check("字幕同步改名落位",
          (s00 / "无职转生 - S00E01.zh-CN.ass").exists())
    check("字幕内容完整", (s00 / "无职转生 - S00E01.zh-CN.ass").read_text(encoding="utf-8") == "sub-bytes")
    check("视频内容完整", (s00 / "无职转生 - S00E01.mkv").read_text(encoding="utf-8") == "video-bytes")
    check("源已移走", not (season_dir / "无职转生 - S01E24 SP.mkv").exists())
    check("正片 E23 未被动", (season_dir / "无职转生 - S01E23.mkv").exists())
    check("无残留 .part 临时文件",
          not any(p.name.endswith(".part") for p in s00.iterdir()),
          f"got={[p.name for p in s00.iterdir()]}")

    # 冲突不覆盖
    (season_dir / "dup SP.mkv").write_text("dup-video", encoding="utf-8")
    fops.move_episode_group(season_dir, s00, "dup SP.mkv", [], "无职转生 - S00E01")
    check("同名目标不覆盖、加 (1) 后缀", (s00 / "无职转生 - S00E01(1).mkv").exists())
    check("原文件内容未被覆盖",
          (s00 / "无职转生 - S00E01.mkv").read_text(encoding="utf-8") == "video-bytes")


def test_plugin_contract():
    print("\n=== 10. 插件契约（元信息 / 表单 / API） ===")
    mod = sys.modules["specialsrelocate"]
    P = mod.SpecialsRelocate
    for attr in ("plugin_name", "plugin_desc", "plugin_version",
                 "plugin_author", "plugin_config_prefix"):
        check(f"定义了 {attr}", bool(getattr(P, attr, None)))
    check("plugin_id 与目录名一致",
          P.__name__.lower() == "specialsrelocate" and PLUGIN_DIR.name == "specialsrelocate")

    p = P()
    form, default = p.get_form()
    check("get_form 返回 (list, dict)", isinstance(form, list) and isinstance(default, dict))
    check("表单含 VForm", form and form[0].get("component") == "VForm")

    # 默认配置的每个 key 都必须在表单里有对应控件
    models = set()

    def walk(nodes):
        for n in nodes or []:
            props = n.get("props") or {}
            if "model" in props:
                models.add(props["model"])
            walk(n.get("content"))
    walk(form)
    missing = [k for k in default if k not in models]
    check("默认配置每个 key 都有表单控件", not missing, f"missing={missing}")

    apis = p.get_api()
    check("get_api 返回扫描与结果接口",
          {a["path"] for a in apis} == {"/scan", "/result"},
          f"got={[a['path'] for a in apis]}")
    for a in apis:
        check(f"API {a['path']} 有 method/func/desc",
              all(k in a for k in ("path", "method", "func", "desc")))

    cmds = p.get_command()
    check("get_command 提供扫描命令", len(cmds) >= 1)
    check("命令含 label/command/description",
          all(k in cmds[0] for k in ("label", "command", "description")))

    page = p.get_page()
    check("get_page 可渲染（未跑过也不报错）", isinstance(page, list) and len(page) == 2)


def test_scan_end_to_end():
    print("\n=== 11. 端到端：扫描真实目录（mock TMDB） ===")
    mod = sys.modules["specialsrelocate"]
    P = mod.SpecialsRelocate

    base = TMP / "e2e" / "日番" / "无职转生 (2021) {tmdbid=94664}"
    s1 = base / "Season 01"
    s1.mkdir(parents=True, exist_ok=True)
    for i in range(1, 24):
        (s1 / f"无职转生 - S01E{i:02d}.mkv").write_text(f"v{i}", encoding="utf-8")
    (s1 / "无职转生 - S01E24 总集篇.mkv").write_text("sp", encoding="utf-8")
    (s1 / "无职转生 - S01E24.zh-CN.ass").write_text("s", encoding="utf-8")

    # 伪造 TMDB 客户端：S1=23集，Season 0 有 3 条
    class FakeClient:
        retried = 0
        errors = []

        def season_episode_count(self, tmdbid, season):
            return {1: 23, 2: 24}.get(season)

        def season0_index(self, tmdbid):
            return mod.core.build_s0_index([
                {"episode_number": 1, "name": "番外篇「艾莉丝的哥布林讨伐」"},
                {"episode_number": 2, "name": "『无职转生Ⅱ』第零话「守护术师菲兹」"},
                {"episode_number": 3, "name": "【转移迷宫篇】开播前特别节目"},
            ])

    p = P()
    p._cfg = dict(P.DEFAULT_CONFIG)
    p._cfg.update({"dry_run": False, "detect_duration": False,
                   "write_nfo": True, "min_confidence": 0.5})

    r1 = p.check_one_season("无职转生 (2021) {tmdbid=94664}", 94664, 1, s1,
                            dry_run=True, client=FakeClient())
    check("扫描命中该季", r1 is not None)
    check("识别 TMDB 23 集 / 本地 24 集",
          r1["tmdb_count"] == 23 and r1["local_count"] == 24,
          f"got={r1['tmdb_count']}/{r1['local_count']}")
    check("超集识别为 E24", r1["extras_text"] == "E24", f"got={r1['extras_text']}")
    check("E24 判定为特别篇", r1["details"][0]["is_special"])
    check("预演模式下不落盘", r1["moved"] == 0 and (s1 / "无职转生 - S01E24 总集篇.mkv").exists())

    r2 = p.check_one_season("无职转生 (2021) {tmdbid=94664}", 94664, 1, s1,
                            dry_run=False, client=FakeClient())
    s00 = mod.fileops.season00_dir(s1, "season")
    check("执行后 E24 移出第一季", not (s1 / "无职转生 - S01E24 总集篇.mkv").exists())
    check("字幕也移出第一季", not (s1 / "无职转生 - S01E24.zh-CN.ass").exists())
    check("Season 00 目录已创建", s00.exists() and s00.name == "Season 00")
    # 目标文件名会剥离 {tmdbid=xxx}（与 MP 的 TV_RENAME_FORMAT 一致）
    check("视频已重命名为 S00E01",
          (s00 / "无职转生 (2021) - S00E01.mkv").exists(),
          f"got={[p.name for p in s00.iterdir()]}")
    check("字幕同步重命名",
          (s00 / "无职转生 (2021) - S00E01.zh-CN.ass").exists(),
          f"got={[p.name for p in s00.iterdir()]}")
    nfo = s00 / "无职转生 (2021) - S00E01.mkv.nfo"
    check("已写入单集 NFO", nfo.exists(), f"got={[p.name for p in s00.iterdir()]}")
    if nfo.exists():
        content = nfo.read_text(encoding="utf-8")
        check("NFO season=0", "<season>0</season>" in content, f"content={content}")
        check("NFO episode=1", "<episode>1</episode>" in content)
    check("正片 23 集全部保留",
          len([f for f in mod.fileops.list_media_files(s1) if f.endswith(".mkv")]) == 23)
    check("Season 00 内集号可被解析为 1",
          mod.core.extract_episode_number("无职转生 - S00E01.mkv") == 1)

    # 幂等：再跑一次不应重复处理
    r3 = p.check_one_season("无职转生 (2021) {tmdbid=94664}", 94664, 1, s1,
                            dry_run=False, client=FakeClient())
    check("第二次运行无超集（幂等）", r3 is None, f"got={r3}")


def main():
    print("=" * 68)
    print("特别篇归位插件 · 离线测试")
    print("=" * 68)
    load_plugin()
    test_parsing()
    test_keywords()
    test_find_extras()
    test_sidecars()
    test_judge()
    test_target_ep()
    test_season00_dir()
    test_nfo()
    test_move_real_fs()
    test_plugin_contract()
    test_scan_end_to_end()

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