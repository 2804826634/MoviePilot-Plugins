# -*- coding: utf-8 -*-
"""NfoGapFill 插件面自检：伪造一个 MoviePilot 宿主（app.plugins / app.log / apscheduler），
验证插件能被正常导入、实例化、init_plugin、get_form / get_page / get_service 返回结构正确，
并端到端跑通「插件 -> 引擎 -> 报告文件 -> 通知」这条链路。

    python _self_test_plugin.py
"""
import importlib.util
import json
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
                 "tmdb_api_key", "language", "cert_country", "cast_limit",
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
check("图片类型改为多选下拉框（multiple + chips），不再用只能单选的复选框",
      "'model': 'image_kinds'" in form_json
      and "'multiple': True" in form_json and "'chips': True" in form_json
      and "'component': 'VCheckbox'" not in form_json)
check("图片类型选项为中文，并标注落盘文件名",
      all(f"'title': '{title}'" in form_json for title in
          ("海报（poster.jpg）", "背景图（backdrop.jpg + fanart.jpg）",
           "徽标（logo.png）", "剧集缩略图（单集剧照 → 与视频同名的 .jpg）")))
check("图片说明里写全了 4 类落盘文件名与季海报的连带行为",
      all(name in form_json for name in
          ("poster.jpg", "backdrop.jpg", "fanart.jpg", "logo.png", "seasonNN-poster.jpg")))
check("图片说明里写明了不支持的类型及原因（TMDB 没有，只有 fanart.tv 提供）",
      all(name in form_json for name in
          ("banner", "clearart", "discart", "landscape", "characterart", "fanart.tv")))
check("图片类型默认全选", sorted(defaults["image_kinds"]) == sorted(module.IMAGE_KINDS))
check("演员写入上限改为下拉选项，且含「全部」",
      "'model': 'cast_limit'" in form_json
      and "'title': '全部（按 TMDB 返回的全写，NFO 会明显变大）', 'value': '0'" in form_json)
check("分级地区码改为单选下拉，含常用地区",
      "'model': 'cert_country', 'label': '分级地区码（决定 mpaa 取哪个地区的分级）'" in form_json
      and all(f"'value': '{code}'" in form_json
              for code in ("US", "CN", "HK", "TW", "JP", "GB", "DE")))
check("全表单只有图片类型是多选（分级地区码保持单选）",
      form_json.count("'multiple': True") == 1)
check("分级地区码给了完整说明（mpaa 与各地区分级差异）",
      "分级地区码」怎么填" in form_json and "PG-13" in form_json)
check("「字段白名单」与「网络代理」已从配置项中移除",
      "only_fields" not in defaults and "proxy" not in defaults
      and "'model': 'only_fields'" not in form_json and "'model': 'proxy'" not in form_json)
check("保护字段的说明保留，并列出了各类型可用字段名",
      "「保护字段」= 照常参与比对" in form_json and "premiered" in form_json)
check("已写明 TMDB Key 留空会自动读取 MoviePilot 的配置、代理自动沿用 PROXY_HOST",
      "自动读取 MoviePilot 里已配置的 Key" in form_json and "PROXY_HOST" in form_json)

# 图片类型解析：列表（多选下拉）与字符串（老配置 / CLI）两种载体
def kinds_of(value):
    probe = module.NfoGapFill.__new__(module.NfoGapFill)
    probe._image_kinds = value
    return probe._NfoGapFill__image_kinds_set()

check("多选列表能正确解析（大小写不敏感）", kinds_of(["poster", "LOGO"]) == {"poster", "logo"})
check("多选被清空（[] / null / 空串）= 不处理任何图片（不会偷偷回退成全部）",
      kinds_of([]) == set() and kinds_of(None) == set() and kinds_of("") == set())
check("老配置的逗号字符串仍兼容", kinds_of("poster, backdrop") == {"poster", "backdrop"})
check("字符串写错时回退全部（避免手写错字导致静默不干活）",
      kinds_of("posterr") == set(module.IMAGE_KINDS))

# 回归：v1.2.0 的单选复选框把 image_kinds 存成了布尔，界面上冒出一个 `false` chip
check("旧版复选框存下的布尔值能被修好（true = 全选，false = 全不选）",
      kinds_of(True) == set(module.IMAGE_KINDS) and kinds_of(False) == set())
check("normalize_image_kinds 对各类脏数据都返回干净列表",
      module.normalize_image_kinds(False) == []
      and module.normalize_image_kinds(True) == list(module.IMAGE_KINDS)
      and module.normalize_image_kinds(None) is None
      and module.normalize_image_kinds(["poster", "bogus"]) == ["poster"]
      and module.normalize_image_kinds("logo,thumb") == ["logo", "thumb"])
check("修复结果只含合法值（界面不会再冒出 false 这种 chip）",
      all(k in module.IMAGE_KINDS for k in
          (module.normalize_image_kinds(False) or []) + module.normalize_image_kinds(True)))

# init_plugin 还会把修正结果回写配置库，否则界面会一直挂着脏值
repair_plugin = module.NfoGapFill()
repair_plugin.init_plugin({**defaults, "image_kinds": False})
check("init_plugin 把布尔脏值收敛成空列表", repair_plugin._image_kinds == [])
check("并把修正结果回写进配置库", repair_plugin.get_config().get("image_kinds") == [])

# 媒体库目录的 #类型 限定
roots, types = module.parse_root_specs(["/m/电影#电影", "/m/剧集#电视剧", "/m/其它"])
# Windows 上 str(Path) 是反斜杠，比较前统一成正斜杠
by_path = {k.replace("\\", "/"): v for k, v in types.items()}
check("目录 #电影 后缀被识别并归一为 movie", by_path.get("/m/电影") == "movie")
check("目录 #电视剧 后缀被识别", by_path.get("/m/剧集") == "tv")
check("没写后缀的目录不限定类型", "/m/其它" not in by_path)
check("三种后缀都产出目录，且顺序不变", [str(p).replace("\\", "/") for p in roots]
      == ["/m/电影", "/m/剧集", "/m/其它"])
check("别名后缀也认（movie / movies / tvshow / 剧集）",
      module.normalize_type_tag("movie") == "movie"
      and module.normalize_type_tag("movies") == "movie"
      and module.normalize_type_tag("tvshow") == "tv"
      and module.normalize_type_tag("剧集") == "tv")
check("认不出的后缀不会把真实路径吃掉",
      module.parse_root_specs(["/m/a#b/c"])[0][0] == Path("/m/a#b/c")
      and not module.parse_root_specs(["/m/a#b/c"])[1])
check("类型限定只放行对应类型（限电影只收 movie，限电视剧收剧集/季/单集）",
      module.type_allowed("movie", "movie") and not module.type_allowed("movie", "tvshow")
      and module.type_allowed("tv", "tvshow") and module.type_allowed("tv", "season")
      and module.type_allowed("tv", "episodedetails")
      and not module.type_allowed("tv", "movie")
      and module.type_allowed(None, "movie") and module.type_allowed(None, "tvshow"))
check("目录键必须与最终 roots 字符串一致（否则限定会失效）",
      all(k in [str(p) for p in roots] for k in types))

print()
print("=" * 70)
print("回归：宿主 MediaInfo 的结构化对象不能被 str() 写进 NFO")
print("=" * 70)


class FakePerson:
    """模拟 MoviePilot 的 MediaPerson（角色字段叫 character，头像在 profile_path）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeInfo:
    """模拟 MoviePilot 的 MediaInfo（genres / production_companies 是 List[dict]）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# 数据照抄用户截图里那部片（疯狂动物城2 / Pixar）
fake_info = FakeInfo(
    title="疯狂动物城2", original_title="Zootopia 2",
    overview="兔子朱迪与狐狸尼克再度联手。", tagline="",
    vote_average=7.2, release_date="2025-11-26", runtime=108,
    genres=[{"id": 12, "name": "冒险"}, {"id": 16, "name": "动画"},
            {"id": 35, "name": "喜剧"}, {"id": 10751, "name": "家庭"},
            {"id": 878, "name": "科幻"}],
    directors=[{"adult": False, "gender": 1, "id": 1485788, "department": "Production",
                "job": "Producer", "name": "Nicole Paradis Grindle"},
               {"id": 1491592, "department": "Directing", "job": "Director",
                "name": "丹尼尔·钟"}],
    production_companies=[{"id": 3, "logo_path": "/x.png", "name": "Pixar",
                           "origin_country": "US"}],
    production_countries=[{"iso_3166_1": "US", "name": "United States of America"}],
    actors=[FakePerson(name="Ginnifer Goodwin", character="Judy Hopps",
                       profile_path="/abc.jpg", images={"thumb": "/abc_thumb.jpg"}),
            {"name": "Jason Bateman", "character": "Nick Wilde", "profile_path": "/def.jpg"},
            {"name": "", "character": "无名氏"}],          # 没名字的条目应被丢弃
)
host_fields = module.HostProvider._info_to_fields(fake_info, False, 20)

check("genre 被剥成纯名字（不再是 {'id': 12, 'name': '冒险'}）",
      host_fields.get("genre") == ["冒险", "动画", "喜剧", "家庭", "科幻"],
      str(host_fields.get("genre")))
check("director 被剥成纯名字", host_fields.get("director") == ["Nicole Paradis Grindle", "丹尼尔·钟"],
      str(host_fields.get("director")))
check("studio 取到 Pixar（而不是公司对象）", host_fields.get("studio") == ["Pixar"],
      str(host_fields.get("studio")))
check("country 取到国家名（而不是国家对象）",
      host_fields.get("country") == ["United States of America"])
check("runtime / year 正常", host_fields.get("runtime") == ["108"]
      and host_fields.get("year") == ["2025"])
check("演员：对象与 dict 两种形态都能取到 姓名/角色/头像",
      [a.split(module.ACTOR_SEP) for a in host_fields.get("actor", [])]
      == [["Ginnifer Goodwin", "Judy Hopps", "/abc.jpg"],
          ["Jason Bateman", "Nick Wilde", "/def.jpg"]],
      str(host_fields.get("actor")))
check("没名字的演员条目被丢弃", len(host_fields.get("actor", [])) == 2)
check("整份输出里不含任何 Python 对象字面量",
      not any(module.looks_like_object_repr(v)
              for vals in host_fields.values() for v in vals),
      str(host_fields))

# 剧集：episode_run_time 是 list，不能被写成多个 <runtime>
tv_info = FakeInfo(title="某剧", first_air_date="2016-07-15", episode_run_time=[50, 60],
                   networks=[{"id": 213, "name": "Netflix"}],
                   origin_country=["US"], genres=[{"id": 18, "name": "剧情"}])
tv_fields = module.HostProvider._info_to_fields(tv_info, True, 20)
check("剧集时长只取第一个（不会写出多个 runtime）", tv_fields.get("runtime") == ["50"])
check("剧集 studio 取网络方名字", tv_fields.get("studio") == ["Netflix"])
check("只有 ISO 代码时 country 也能取到值", tv_fields.get("country") == ["US"])
check("剧集 year 由首播日期截出", tv_fields.get("year") == ["2016"])

# 基础工具函数
check("item_text 覆盖 字符串 / 数字 / dict / 对象 四种输入",
      module.item_text(" 冒险 ") == "冒险" and module.item_text(12) == "12"
      and module.item_text({"id": 12, "name": "冒险"}) == "冒险"
      and module.item_text(FakePerson(name="Pixar")) == "Pixar"
      and module.item_text({"id": 1}) == "" and module.item_text(None) == "")
check("text_list 覆盖标量 / 字符串列表 / dict 列表 / 对象列表",
      module.text_list("科幻") == ["科幻"]
      and module.text_list(["科幻", "冒险"]) == ["科幻", "冒险"]
      and module.text_list([{"name": "科幻"}, {"name": "冒险"}]) == ["科幻", "冒险"]
      and module.text_list(None) == [] and module.text_list([]) == [])
check("looks_like_object_repr 能识别截图里那种脏值",
      module.looks_like_object_repr("{'id': 12, 'name': '冒险'}")
      and module.looks_like_object_repr("[{'a': 1}]")
      and not module.looks_like_object_repr("冒险")
      and not module.looks_like_object_repr("标题：{大冒险}")     # 正常文本不受影响
      and not module.looks_like_object_repr("2016-07-15"))

# 引擎护栏：即便数据源真的吐出对象字面量，也不能写进用户的 NFO
guard_root = DATA_PATH / "guardlib"
guard_movie = guard_root / "电影" / "测试 (2020)"
guard_movie.mkdir(parents=True, exist_ok=True)
guard_nfo = guard_movie / "movie.nfo"
guard_nfo.write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>\n'
    '  <title>测试</title>\n  <year>2020</year>\n  <tmdbid>999</tmdbid>\n'
    '  <genre>科幻</genre>\n</movie>\n', encoding="utf-8")
guard_cache = DATA_PATH / "guard_cache.json"
guard_cache.write_text(json.dumps({"movie:999": {
    "title": ["测试"], "year": ["2020"],
    "genre": ["{'id': 12, 'name': '冒险'}"],          # 数据源出 bug，吐了对象字面量
}}, ensure_ascii=False), encoding="utf-8")
guard_cfg = module.EngineConfig(roots=[guard_root], mode="sync",
                                manifest_path=DATA_PATH / "guard_manifest.json")
guard_report = module.Engine(guard_cfg, module.FileProvider(str(guard_cache))).run()
guard_after = guard_nfo.read_text(encoding="utf-8")
check("护栏生效：脏值没有被写进 NFO（本地原值保持不动）",
      "科幻" in guard_after and "{'id'" not in guard_after, guard_after)
check("该字段被判定为「仅本地有」而不是「替换」（说明值确实被拦下了）",
      guard_report.counts.get(module.LOCAL_ONLY, 0) >= 1, str(guard_report.counts))

# 历史版本可能写出「只有空 name」的 actor 节点，会在媒体服务器里显示成空白人物
actor_root = DATA_PATH / "actorlib"
actor_movie = actor_root / "电影" / "空演员 (2021)"
actor_movie.mkdir(parents=True, exist_ok=True)
actor_cache = DATA_PATH / "actor_cache.json"
actor_cache.write_text(json.dumps({"movie:998": {
    "title": ["空演员"], "year": ["2021"],
    "actor": ["真实演员|主角|", "新增演员|配角|"],
}}, ensure_ascii=False), encoding="utf-8")

# 场景 A：本地只剩空 actor 节点（历史脏数据的典型形态）→ 本地读出来是空，
#         于是判定为「补齐」，会走 replace=False 的补写路径，正好验证清理逻辑
actor_nfo = actor_movie / "movie.nfo"
actor_nfo.write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>\n'
    '  <title>空演员</title>\n  <year>2021</year>\n  <tmdbid>998</tmdbid>\n'
    '  <actor><name></name><role>导演</role></actor>\n'
    '  <actor><name>   </name></actor>\n'
    '</movie>\n', encoding="utf-8")
module.Engine(module.EngineConfig(roots=[actor_root], mode="sync",
                                  manifest_path=DATA_PATH / "actor_m1.json"),
              module.FileProvider(str(actor_cache))).run()
after_a = actor_nfo.read_text(encoding="utf-8")
check("补齐时清掉空的 actor 节点（不再留下空白人物 / 假导演）",
      after_a.count("<actor>") == 2 and "<role>导演</role>" not in after_a
      and "真实演员" in after_a and "新增演员" in after_a, after_a)

# 场景 B：本地有旧演员（与在线不一致）→ 走整体替换，同样不该残留空节点
actor_nfo.write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>\n'
    '  <title>空演员</title>\n  <year>2021</year>\n  <tmdbid>998</tmdbid>\n'
    '  <actor><name></name><role>导演</role></actor>\n'
    '  <actor><name>旧演员</name><role>配角</role></actor>\n'
    '</movie>\n', encoding="utf-8")
module.Engine(module.EngineConfig(roots=[actor_root], mode="sync",
                                  manifest_path=DATA_PATH / "actor_m2.json"),
              module.FileProvider(str(actor_cache))).run()
after_b = actor_nfo.read_text(encoding="utf-8")
check("替换时旧演员与空节点一起被清掉，只留在线值",
      after_b.count("<actor>") == 2 and "旧演员" not in after_b
      and "<role>导演</role>" not in after_b, after_b)

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
