# -*- coding: utf-8 -*-
"""NfoGapFill 插件面自检：伪造一个 MoviePilot 宿主（app.plugins / app.log / apscheduler），
验证插件能被正常导入、实例化、init_plugin、get_form / get_page / get_service 返回结构正确，
并端到端跑通「插件 -> 引擎 -> 报告文件 -> 通知」这条链路。

    python _self_test_plugin.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
FIX = HERE / "_fixture" / "媒体库"
CACHE = HERE / "_fixture" / "remote_cache.json"

TMP = Path(tempfile.mkdtemp(prefix="mp_mock_"))
DATA_PATH = TMP / "plugin_data"
DATA_PATH.mkdir(parents=True, exist_ok=True)
os.environ["MP_DATA_PATH"] = str(DATA_PATH)

SENT_MESSAGES = []
SAVED_DATA = {}

# ── 伪造宿主包 ────────────────────────────────────────────────────
(TMP / "app" / "schemas").mkdir(parents=True, exist_ok=True)
(TMP / "apscheduler" / "triggers").mkdir(parents=True, exist_ok=True)
(TMP / "app" / "__init__.py").write_text("", encoding="utf-8")
(TMP / "app" / "schemas" / "__init__.py").write_text("", encoding="utf-8")
(TMP / "app" / "schemas" / "types.py").write_text(
    "class NotificationType:\n    Plugin = 'Plugin'\n", encoding="utf-8")
(TMP / "app" / "log.py").write_text(
    "class _L:\n"
    "    def info(self, m): pass\n"
    "    def warning(self, m): pass\n"
    "    def error(self, m): pass\n"
    "    def debug(self, m): pass\n"
    "logger = _L()\n", encoding="utf-8")
(TMP / "app" / "plugins" / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
(TMP / "app" / "plugins" / "__init__.py").write_text(
    "import os\n"
    "from pathlib import Path\n"
    "from app.schemas.types import NotificationType\n"
    "\n"
    "MESSAGES = []\n"
    "DATA = {}\n"
    "\n"
    "class _PluginBase:\n"
    "    def __init__(self):\n"
    "        self._saved_config = {}\n"
    "    def update_config(self, config):\n"
    "        self._saved_config.update(config)\n"
    "        return True\n"
    "    def get_config(self):\n"
    "        return dict(self._saved_config)\n"
    "    def save_data(self, key, value):\n"
    "        DATA[key] = value\n"
    "        return True\n"
    "    def get_data(self, key=None):\n"
    "        return DATA.get(key) if key else dict(DATA)\n"
    "    def del_data(self, key):\n"
    "        DATA.pop(key, None)\n"
    "    def get_data_path(self):\n"
    "        return Path(os.environ.get('MP_DATA_PATH', '.'))\n"
    "    def post_message(self, **kwargs):\n"
    "        MESSAGES.append(kwargs)\n"
    "        return True\n", encoding="utf-8")
(TMP / "apscheduler" / "__init__.py").write_text("", encoding="utf-8")
(TMP / "apscheduler" / "triggers" / "__init__.py").write_text("", encoding="utf-8")
(TMP / "apscheduler" / "triggers" / "cron.py").write_text(
    "class CronTrigger:\n"
    "    def __init__(self, expr):\n"
    "        self.expr = expr\n"
    "    @classmethod\n"
    "    def from_crontab(cls, expr):\n"
    "        return cls(expr)\n", encoding="utf-8")

sys.path.insert(0, str(TMP))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail and not ok else ""))


# ── 以插件方式导入 ────────────────────────────────────────────────
spec = importlib.util.spec_from_file_location(
    "NfoGapFill", HERE.parent / "plugins.v2" / "nfogapfill" / "__init__.py")
module = importlib.util.module_from_spec(spec)
sys.modules["NfoGapFill"] = module      # dataclass 解析字符串注解时需要模块已注册
spec.loader.exec_module(module)

check("插件模块能被宿主方式导入", module.IN_MOVIEPILOT is True,
      "应识别为 MoviePilot 环境")
check("基类来自 app.plugins._PluginBase",
      module.NfoGapFill.__mro__[1].__name__ == "_PluginBase")
check("cron 触发器可用", module.CronTrigger is not None)

plugin = module.NfoGapFill()

print()
print("=" * 70)
print("插件元信息与配置表单")
print("=" * 70)
for attr in ("plugin_name", "plugin_desc", "plugin_icon", "plugin_version",
             "plugin_author", "plugin_config_prefix", "plugin_order", "user_level"):
    check(f"元信息 {attr} 已定义", getattr(plugin, attr, None) not in (None, ""),
          f"{attr} 缺失")

form = plugin.get_form()
check("get_form 返回 (页面JSON, 默认配置) 二元组",
      isinstance(form, tuple) and len(form) == 2
      and isinstance(form[0], list) and isinstance(form[1], dict))
defaults = form[1]
expected_keys = {"enabled", "onlyonce", "notify", "mode", "cron", "dry_run", "respect_lock",
                 "backup", "paths", "exclude_paths", "protect_fields",
                 "only_fields", "tmdb_api_key", "language", "proxy", "cert_country", "cast_limit",
                 "image_mode", "image_kinds", "image_quality"}
check("默认配置包含全部配置项", expected_keys <= set(defaults),
      f"缺少 {expected_keys - set(defaults)}")
form_json = str(form[0])
missing_controls = [k for k in expected_keys if f"'model': '{k}'" not in form_json]
check("表单里每个配置项都有对应控件", not missing_controls, f"缺控件：{missing_controls}")
check("表单包含启用 / 立即运行 / 周期 三项关键控件",
      all(f"'model': '{k}'" in form_json for k in ("enabled", "onlyonce", "cron")))
check("lockdata 开关没有被重复渲染", form_json.count("'model': 'respect_lock'") == 1)

print()
print("=" * 70)
print("本次针对反馈调整的配置项")
print("=" * 70)
check("「单轮最多处理文件数」已移除",
      "max_files" not in defaults and "'model': 'max_files'" not in form_json)
check("图片类型改为复选框组（4 个 VCheckbox 共享 image_kinds）",
      form_json.count("'component': 'VCheckbox'") == 4
      and form_json.count("'model': 'image_kinds'") == 4)
check("图片类型复选框显示中文名",
      all(f"'label': '{name}'" in form_json
          for name in ("海报", "背景图", "徽标", "剧集缩略图")))
check("图片类型默认全选", sorted(defaults["image_kinds"]) == sorted(module.IMAGE_KINDS))
check("演员写入上限改为下拉选项，且含「全部」",
      "'model': 'cast_limit'" in form_json
      and "'title': '全部（按 TMDB 返回的全写，NFO 会明显变大）', 'value': '0'" in form_json)
check("分级地区码给了完整说明（mpaa 与各地区分级差异）",
      "分级地区码」怎么填" in form_json and "PG-13" in form_json)
check("字段白名单给了说明，并讲清了与保护字段的区别",
      "字段白名单」和「保护字段」是两件不同的事" in form_json)
check("已写明 TMDB Key / 代理留空会自动沿用 MoviePilot 的配置",
      "自动读取 MoviePilot 里已配置的值" in form_json)

# 图片类型解析：列表（复选框）与字符串（老配置 / CLI）两种载体
def kinds_of(value):
    probe = module.NfoGapFill.__new__(module.NfoGapFill)
    probe._image_kinds = value
    return probe._NfoGapFill__image_kinds_set()

check("复选框列表能正确解析（大小写不敏感）", kinds_of(["poster", "LOGO"]) == {"poster", "logo"})
check("四个框全不勾 = 不处理任何图片（不会偷偷回退成全部）", kinds_of([]) == set())
check("老配置的逗号字符串仍兼容", kinds_of("poster, backdrop") == {"poster", "backdrop"})
check("字符串为空 = 没配过，默认全部类型", kinds_of("") == set(module.IMAGE_KINDS))
check("字符串写错时回退全部（避免手写错字导致静默不干活）",
      kinds_of("posterr") == set(module.IMAGE_KINDS))

# 演员上限：0 表示不限制
cast30 = {"cast": [{"name": f"演员{i}", "character": "路人"} for i in range(30)]}
check("演员上限 0 = 全部写入", len(module.TmdbProvider("dummy", cast_limit=0)._actors(cast30)) == 30)
check("演员上限 10 = 只取前 10 位", len(module.TmdbProvider("dummy", cast_limit=10)._actors(cast30)) == 10)
check("演员上限 20 = 默认取 20 位", len(module.TmdbProvider("dummy")._actors(cast30)) == 20)

# 读宿主配置：命令行 / 测试环境没有 app.core.config 时必须安全降级
check("没有宿主时读 MP 配置安全返回默认值",
      module.mp_setting("TMDB_API_KEY", "fallback") == "fallback"
      and module.mp_setting("NOT_EXIST_SETTING", None) is None)

print()
print("=" * 70)
print("init_plugin / get_state / get_service")
print("=" * 70)
config = dict(defaults)
config.update({"enabled": True, "onlyonce": False, "mode": "report",
               "cron": "0 4 * * *", "paths": str(FIX), "notify": False})
plugin.init_plugin(config)
check("get_state 随 enabled 变化", plugin.get_state() is True)

services = plugin.get_service()
check("get_service 返回一个定时服务", isinstance(services, list) and len(services) == 1)
if services:
    svc = services[0]
    check("服务结构正确（id/name/trigger/func/kwargs）",
          {"id", "name", "trigger", "func", "kwargs"} <= set(svc)
          and callable(svc["func"]) and svc["kwargs"] == {})
    check("cron 表达式被正确解析", getattr(svc["trigger"], "expr", "") == "0 4 * * *")

plugin.init_plugin({**config, "enabled": False})
check("停用后不注册服务", plugin.get_service() == [])

print()
print("=" * 70)
print("端到端：插件 -> 引擎 -> 报告文件 -> 通知")
print("=" * 70)
# 用本地 JSON 冒充在线数据，避免测试依赖网络
provider = module.FileProvider(str(CACHE))
plugin._NfoGapFill__build_provider = lambda: provider   # noqa: SLF001
config.update({"enabled": True, "notify": True, "mode": "sync", "dry_run": True})
plugin.init_plugin(config)
plugin._NfoGapFill__run()                                # noqa: SLF001
report_file = DATA_PATH / "last_report.txt"
check("报告文件已生成", report_file.exists())
text = report_file.read_text(encoding="utf-8") if report_file.exists() else ""
check("报告包含扫描与动作统计", "扫描 NFO" in text and "实际动作" in text)
check("报告里出现差异明细", "不一致" in text)
check("演练模式未写盘（沙丘 year 仍为 2022）",
      "<year>2022</year>" in (FIX / "电影" / "沙丘 (2021)" / "沙丘 (2021).nfo").read_text(encoding="utf-8"))

import app.plugins as mock_host   # noqa: E402
check("已发送通知", len(mock_host.MESSAGES) == 1,
      f"收到 {len(mock_host.MESSAGES)} 条")
check("通知标题符合预期",
      mock_host.MESSAGES and "NFO 与图片差异比对" in mock_host.MESSAGES[0].get("title", ""))
check("save_data 被调用", "nfogapfill_report" in mock_host.DATA)

print()
print("=" * 70)
print("图片能力：单元 + 端到端")
print("=" * 70)
check("端到端报告包含图片统计", "检查图片" in text)
check("端到端报告包含图片判定与动作", "图片判定" in text and "图片动作" in text)
check("演练模式下没有把图片写进样例库",
      not (FIX / "电影" / "星际穿越 (2014)" / "poster.jpg").exists())
check("save_data 记录了图片统计",
      (mock_host.DATA.get("nfogapfill_report") or {}).get("images_scanned", 0) > 0)
check("报告文件指明模式与数据源", "数据源" in text)

# pick_best_image：语言优先 → 分辨率 → 评分
candidates = [
    {"file_path": "/en_hi.jpg", "iso_639_1": "en", "width": 2000, "height": 3000,
     "vote_average": 9.0, "vote_count": 50},
    {"file_path": "/zh_small.jpg", "iso_639_1": "zh", "width": 1200, "height": 1800,
     "vote_average": 5.0, "vote_count": 3},
    {"file_path": "/textless.jpg", "iso_639_1": None, "width": 1800, "height": 2700,
     "vote_average": 6.0, "vote_count": 10},
]
best = module.pick_best_image(candidates, "zh-CN")
check("同语言优先（选到 zh 那张，而不是票数最高的 en）",
      best is not None and best["file_path"] == "/zh_small.jpg")
best_other = module.pick_best_image([c for c in candidates if c["iso_639_1"] != "zh"], "ja-JP")
check("无本语言时：无文字版优先于英文版",
      best_other is not None and best_other["file_path"] == "/textless.jpg")
best_res = module.pick_best_image(
    [{"file_path": "/small.jpg", "iso_639_1": None, "width": 500,
      "vote_average": 9.0, "vote_count": 99},
     {"file_path": "/big.jpg", "iso_639_1": None, "width": 2000,
      "vote_average": 5.0, "vote_count": 1}], "zh")
check("同语言档位内按分辨率优先（本地图库要清晰度）",
      best_res is not None and best_res["file_path"] == "/big.jpg")
check("候选为空时返回 None", module.pick_best_image([], "zh") is None)
check("没有 file_path 的候选被忽略",
      module.pick_best_image([{"iso_639_1": "zh", "width": 9999}], "zh") is None)

# 尺寸档位必须按图片类型区分：TMDB 的 logo 最大只到 w500
check("standard 档各类型尺寸分别取对",
      module.image_size_for("standard", "poster") == "w780"
      and module.image_size_for("standard", "backdrop") == "w1280"
      and module.image_size_for("standard", "logo") == "w500"
      and module.image_size_for("standard", "thumb") == "w300")
check("original 档一律返回 original", module.image_size_for("original", "logo") == "original")
check("未知画质档回退 standard", module.image_size_for("bogus", "poster") == "w780")

# image_targets：文件名与目录落点
movie_nfo = module.load_nfo(FIX / "电影" / "星际穿越 (2014)" / "movie.nfo")
movie_targets = {(spec.kind, spec.name) for spec, _ in
                 module.image_targets(movie_nfo, set(module.IMAGE_KINDS))}
check("电影图片目标 = poster / backdrop / fanart / logo",
      movie_targets == {("poster", "poster.jpg"), ("backdrop", "backdrop.jpg"),
                        ("backdrop", "fanart.jpg"), ("logo", "logo.png")})
season_tree = ET.ElementTree(ET.fromstring("<season><season>1</season></season>"))
season_nfo = module.NfoFile(path=Path("电视剧") / "怪奇物语 (2016)" / "Season 01" / "season.nfo",
                            media_type="season", tree=season_tree)
season_targets = module.image_targets(season_nfo, {"poster"})
check("季海报同时落季目录 poster.jpg 与剧集根目录 season01-poster.jpg",
      len(season_targets) == 2
      and season_targets[0][1].name == "poster.jpg"
      and season_targets[0][1].parent.name == "Season 01"
      and season_targets[1][1].name == "season01-poster.jpg"
      and season_targets[1][1].parent.name == "怪奇物语 (2016)")
check("按 kinds 过滤生效（只要 poster 时不产出 backdrop）",
      all(spec.kind == "poster" for spec, _ in season_targets))
episode_tree = ET.ElementTree(ET.fromstring("<episodedetails><season>2</season></episodedetails>"))
episode_nfo = module.NfoFile(path=Path("剧") / "Season 02" / "剧 - S02E03.nfo",
                             media_type="episodedetails", tree=episode_tree)
episode_targets = module.image_targets(episode_nfo, {"thumb"})
check("单集缩略图 = 视频同名 .jpg（与 MP 的写法一致）",
      len(episode_targets) == 1 and episode_targets[0][1].name == "剧 - S02E03.jpg")

# 指纹清单：内容与 URL 都一致才算「相同」
manifest_probe = module.ImageManifest(None)
probe = DATA_PATH / "probe.jpg"
probe.write_bytes(b"hello-image")
digest = module.sha256_file(probe)
manifest_probe.record(probe, "https://example.com/a.jpg", digest or "", 11)
check("指纹匹配：URL 与内容都一致 → 判定相同", manifest_probe.matches(probe, "https://example.com/a.jpg"))
check("URL 变了 → 不算相同（图片源更新了）",
      not manifest_probe.matches(probe, "https://example.com/b.jpg"))
probe.write_bytes(b"changed-image")
check("内容变了 → 不算相同（本地图被换过）",
      not manifest_probe.matches(probe, "https://example.com/a.jpg"))

print()
print("=" * 70)
print("get_page / get_command / get_api / stop_service")
print("=" * 70)
page = plugin.get_page()
check("get_page 返回组件列表", isinstance(page, list) and len(page) >= 2)
page_text = str(page)
check("详情页主视图改成「本次修改了哪些文件」表格", "VDataTable" in page_text)
check("表格列头为 文件 / 类型 / 字段变更 / 图片变更",
      all(f"'title': '{h}'" in page_text for h in ("文件", "类型", "字段变更", "图片变更")))
check("表格里给出了真实的媒体文件相对路径", "星际穿越" in page_text)
check("详情页标出上次运行时间", "上次运行" in page_text)
check("演练模式下措辞为「将要修改」", "将要修改" in page_text)
check("详情页不再直接堆整篇文本报告", "report_text" not in page_text)
check("结构化变更明细已落盘 last_changes.json", (DATA_PATH / "last_changes.json").exists())
check("完整文本报告仍然保留（供深挖跳过原因）", (DATA_PATH / "last_report.txt").exists())
check("get_command 返回空列表（不注册远程命令）", plugin.get_command() == [])
check("get_api 返回空列表", plugin.get_api() == [])
plugin.stop_service()
check("stop_service 不抛异常", True)

print()
print("=" * 70)
failed = [r for r in results if not r[1]]
print(f"共 {len(results)} 项断言，通过 {len(results) - len(failed)}，失败 {len(failed)}")
for name, _ok, detail in failed:
    print(f"  FAIL {name} {detail}")
print("=" * 70)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
