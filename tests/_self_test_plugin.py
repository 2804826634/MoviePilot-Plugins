# -*- coding: utf-8 -*-
"""NfoGapFill 插件面自检：伪造一个 MoviePilot 宿主（app.plugins / app.log / apscheduler），
验证插件能被正常导入、实例化、init_plugin、get_form / get_page / get_service 返回结构正确，
并端到端跑通「插件 -> 引擎 -> 报告文件 -> 通知」这条链路。

    python _self_test_plugin.py
"""
import importlib.util
import inspect as _inspect
import json
import os
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

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
                 "image_mode", "tmdb_image_kinds", "fanart_image_kinds",
                 "image_quality", "image_sources"}
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
check("图片类型拆成两个多选下拉框（TMDB 一个 / fanart.tv 一个），不再用只能单选的复选框",
      all(f"'model': '{k}'" in form_json for k in ("tmdb_image_kinds", "fanart_image_kinds"))
      and "'model': 'image_kinds'" not in form_json
      and "'multiple': True" in form_json and "'chips': True" in form_json
      and "'component': 'VCheckbox'" not in form_json)
check("两个下拉框分别标注了所属数据源",
      "TMDB 提供的图片类型（可多选）" in form_json
      and "fanart.tv 提供的图片类型（可多选）" in form_json)
check("TMDB 下拉只列出 TMDB 真的会返回的类型（海报 / 背景图 / 徽标 / 单集剧照）",
      all(f"'title': '{title}'" in form_json for title in
          ("海报（poster.jpg）", "背景图（backdrop.jpg + fanart.jpg）",
           "徽标（logo.png）", "剧集缩略图（单集剧照 → 与视频同名的 .jpg）")))
check("fanart 下拉只列出 fanart 独有的类型（横版缩略图 / 横幅图 / 光盘图 / 透明艺术图 / 别名 landscape）",
      all(f"'title': '{title}'" in form_json for title in
          ("横版缩略图（thumb.jpg + landscape.jpg）", "横幅图（banner.jpg）",
           "光盘图（disc.png，仅电影）", "透明艺术图（clearart.png）",
           "横版缩略图别名（landscape.jpg）")))
check("图片说明里写全了落盘文件名，并写明季图两处都写（对齐 MP）",
      all(name in form_json for name in
          ("poster.jpg", "backdrop.jpg", "fanart.jpg", "logo.png"))
      and "seasonNN-poster.jpg" in form_json
      and "两处都写" in form_json)
check("两个下拉默认都全选（并集 = 全部 8 类）",
      sorted(defaults["tmdb_image_kinds"]) == sorted(module.TMDB_IMAGE_KINDS)
      and sorted(defaults["fanart_image_kinds"]) == sorted(module.FANART_IMAGE_KINDS)
      and sorted(module.merge_image_kinds(defaults["tmdb_image_kinds"],
                                          defaults["fanart_image_kinds"]))
      == sorted(module.IMAGE_KINDS))
check("图片来源优先级默认 TMDB 优先、fanart.tv 其次",
      defaults["image_sources"] == "tmdb,fanart"
      and module.image_source_order(defaults["image_sources"]) == ["tmdb", "fanart"])
check("图片来源优先级下拉列了四种组合",
      all(v in form_json for v in ("tmdb,fanart", "fanart,tmdb", "tmdb", "fanart"))
      and "'model': 'image_sources'" in form_json)
check("图片类型已扩到 8 类，且标注了数据来源（TMDB + fanart.tv）",
      len(module.IMAGE_KINDS) == 8
      and "fanart.tv" in form_json and "FANART_API_KEY" in form_json)
check("演员写入上限改为下拉选项，且含「全部」",
      "'model': 'cast_limit'" in form_json
      and "'title': '全部（按 TMDB 返回的全写，NFO 会明显变大）', 'value': '0'" in form_json)
check("分级地区码改为单选下拉，含常用地区",
      "'model': 'cert_country', 'label': '分级地区码（决定 mpaa 取哪个地区的分级）'" in form_json
      and all(f"'value': '{code}'" in form_json
              for code in ("US", "CN", "HK", "TW", "JP", "GB", "DE")))
check("全表单只有这两个图片类型下拉是多选（分级地区码 / 图片处理 / 画质 / 来源优先级都是单选）",
      form_json.count("'multiple': True") == 2
      and form_json.count("'multiple': True") == form_json.count("'chips': True"))
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
# 注意：两个新下拉一旦存在，就以它们为准（并集），旧的 image_kinds 布尔脏值被忽略。
repair_plugin = module.NfoGapFill()
repair_plugin.init_plugin({**defaults, "image_kinds": False})
check("两个下拉都在时，旧的布尔脏值不再影响处理集合（并集 = 全选）",
      sorted(repair_plugin._image_kinds) == sorted(module.IMAGE_KINDS))
check("旧键 image_kinds 被回写成干净列表（界面不再挂 false）",
      repair_plugin.get_config().get("image_kinds") == list(module.IMAGE_KINDS))
# 只给旧配置（无两个新下拉）时，布尔脏值仍按老规则收敛
legacy_plugin = module.NfoGapFill()
legacy_plugin.init_plugin({"paths": "/m/a", "image_kinds": False})
check("只给旧配置 image_kinds=False 时 = 不处理任何图片",
      legacy_plugin._image_kinds == [])
check("并把它回写成空列表（界面不再挂 false）",
      legacy_plugin.get_config().get("image_kinds") == [])

# 两个下拉的并集语义（v1.7.7 把单一下拉拆成 TMDB / fanart 各一个）
check("merge_image_kinds 取两个下拉的并集，且顺序按 IMAGE_KINDS 规范",
      module.merge_image_kinds(["poster"], ["banner"]) == ["poster", "banner"]
      and module.merge_image_kinds(["thumb"], ["thumb"]) == ["thumb"])
check("merge_image_kinds 只认各源允许的类型（TMDB 下拉里塞 banner 会被丢掉）",
      module.merge_image_kinds(["poster", "banner"], None) == ["poster"]
      and module.merge_image_kinds(None, ["banner", "poster"]) == ["banner"])
check("两个下拉都是 null（未配置）时回落到老配置 image_kinds",
      module.merge_image_kinds(None, None, ["poster", "logo"]) == ["poster", "logo"])
check("两个下拉都清空 = 空列表（不偷偷回退成全选）",
      module.merge_image_kinds([], []) == [])
check("两个下拉与老配置都缺失时返回 None（交给上层判定为全选）",
      module.merge_image_kinds(None, None) is None)
check("normalize_image_kinds 指定 allowed 池后只认池内值",
      module.normalize_image_kinds(["poster", "banner"], module.TMDB_IMAGE_KINDS,
                                   fallback_all=False) == ["poster"]
      and module.normalize_image_kinds(None, module.TMDB_IMAGE_KINDS,
                                       fallback_all=False) is None
      and module.normalize_image_kinds([], module.TMDB_IMAGE_KINDS,
                                       fallback_all=False) == [])

# 拆分后：两个下拉任一为脏值都要被回写修正，且并集 = 实际处理集合
repair2 = module.NfoGapFill()
repair2.init_plugin({**defaults,
                     "tmdb_image_kinds": ["poster", "bogus"],
                     "fanart_image_kinds": None})
check("init_plugin 收敛 TMDB 下拉的脏值并保留合法项",
      repair2._tmdb_image_kinds == ["poster"])
check("TMDB 下拉非空时，fanart 下拉的 null 视为「空」（并集只由有值的一边决定）",
      repair2._image_kinds == ["poster"])
check("两个下拉的并集就是最终处理集合",
      sorted(repair2._image_kinds)
      == sorted(module.merge_image_kinds(repair2._tmdb_image_kinds,
                                         repair2._fanart_image_kinds)))
check("修正后的两个下拉都被回写进配置库",
      repair2.get_config().get("tmdb_image_kinds") == ["poster"]
      and repair2.get_config().get("fanart_image_kinds") == [])

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

print()
print("=" * 70)
print("图片域名跟随宿主配置 + 下载失败自动重试")
print("=" * 70)
_orig_mp_setting = module.mp_setting
try:
    module.mp_setting = lambda name, default=None: (
        {"TMDB_IMAGE_DOMAIN": "mirror.example.com/t/p"}.get(name, default))
    check("image_host 跟随宿主的 TMDB_IMAGE_DOMAIN",
          module.image_host() == "https://mirror.example.com/t/p/", module.image_host())
    module.mp_setting = lambda name, default=None: (
        {"TMDB_IMAGE_DOMAIN": "https://img.cdn.cn"}.get(name, default))
    check("填了完整 URL 也能规整掉协议与多余斜杠",
          module.image_host() == "https://img.cdn.cn/t/p/", module.image_host())
    module.mp_setting = lambda name, default=None: (
        {"TMDB_IMAGE_DOMAIN": "  "}.get(name, default))
    check("宿主没配（空白值）时回落官方域名",
          module.image_host() == "https://image.tmdb.org/t/p/", module.image_host())
finally:
    module.mp_setting = _orig_mp_setting
check("恢复后默认仍是官方域名",
      module.image_host() == "https://image.tmdb.org/t/p/")

# TMDB 接口域名：默认官方，可被宿主设置覆盖（api.themoviedb.org 被整段拦掉时的逃生口）
try:
    module.mp_setting = lambda name, default=None: (
        {"TMDB_API_DOMAIN": "api.tmdb.org"}.get(name, default))
    check("tmdb_api_host 跟随宿主的 TMDB_API_DOMAIN（补 /3）",
          module.tmdb_api_host() == "https://api.tmdb.org/3", module.tmdb_api_host())
    module.mp_setting = lambda name, default=None: (
        {"TMDB_API_DOMAIN": "https://api.tmdb.org/3"}.get(name, default))
    check("填了完整 URL/已带 /3 时不重复拼接",
          module.tmdb_api_host() == "https://api.tmdb.org/3", module.tmdb_api_host())
    module.mp_setting = lambda name, default=None: (
        {"TMDB_API_DOMAIN": "  "}.get(name, default))
    check("宿主没配（空白值）时回落官方接口域名",
          module.tmdb_api_host() == "https://api.themoviedb.org/3", module.tmdb_api_host())
finally:
    module.mp_setting = _orig_mp_setting
check("恢复后默认仍是官方接口域名",
      module.tmdb_api_host() == "https://api.themoviedb.org/3")
check("TmdbProvider 实例真的用上了 api_host",
      "self.api_host" in _inspect.getsource(module.TmdbProvider._get),
      "fetch 里仍硬编码 api.themoviedb.org")


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FlakyOpener:
    """前 fail_times 次抛异常，之后返回数据 —— 模拟 image.tmdb.org 抽风。"""

    def __init__(self, fail_times, payload=b"image-bytes"):
        self.fail_times = fail_times
        self.payload = payload
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OSError("connection reset")
        return _FakeResponse(self.payload)


flaky = FlakyOpener(1)
check("下载失败会自动重试并最终成功",
      module.download_bytes("https://x/y.png", flaky, attempts=3) == b"image-bytes"
      and flaky.calls == 2, f"calls={flaky.calls}")
dead = FlakyOpener(99)
check("重试全部失败才返回 None，并且尝试了设定的次数",
      module.download_bytes("https://x/y.png", dead, attempts=2) is None and dead.calls == 2,
      f"calls={dead.calls}")
empty = FlakyOpener(0, payload=b"")
check("响应为空也算失败（不会写出 0 字节图片）",
      module.download_bytes("https://x/y.png", empty, attempts=1) is None)

# 官方图片域名被整段拦掉时，必须自动改走 CDN 备用源（否则「图选得出来、下不下来」）
check("官方图片地址会追加 CDN 备用源",
      module.image_url_candidates("https://image.tmdb.org/t/p/original/a.jpg")
      == ["https://image.tmdb.org/t/p/original/a.jpg",
          "https://tmdb-image-prod.b-cdn.net/t/p/original/a.jpg"],
      str(module.image_url_candidates("https://image.tmdb.org/t/p/original/a.jpg")))
check("非官方地址（fanart / 自定义镜像）不追加备用源",
      module.image_url_candidates("https://assets.fanart.tv/fanart/x.jpg")
      == ["https://assets.fanart.tv/fanart/x.jpg"])


class FirstHostDead:
    """第一个源全挂、备用源能通 —— 模拟 image.tmdb.org 被拦而 CDN 可用。"""

    def __init__(self):
        self.hosts = []

    def open(self, request, timeout=None):
        host = request.full_url.split("/")[2]
        self.hosts.append(host)
        if host == "image.tmdb.org":
            raise OSError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
        return _FakeResponse(b"cdn-bytes")


dead_host = FirstHostDead()
check("官方域名连不上时自动换 CDN 源并成功",
      module.download_bytes("https://image.tmdb.org/t/p/original/a.jpg",
                            dead_host, attempts=1) == b"cdn-bytes"
      and "tmdb-image-prod.b-cdn.net" in dead_host.hosts,
      f"hosts={dead_host.hosts}")

# fanart Key：宿主没配时应回落 MP 内置默认值 / 环境变量，而不是直接判「没 Key」
_orig_env = os.environ.get("FANART_API_KEY")
try:
    os.environ.pop("FANART_API_KEY", None)
    check("宿主没配 fanart key 时回落到 MP 内置默认值",
          module.fanart_api_key() == module.FANART_DEFAULT_KEY,
          module.fanart_api_key())
    os.environ["FANART_API_KEY"] = "env-key-123"
    check("宿主没配但环境变量有 fanart key 时用环境变量",
          module.fanart_api_key() == "env-key-123", module.fanart_api_key())
    module.mp_setting = lambda name, default=None: (
        {"FANART_API_KEY": "host-key-999"}.get(name, default))
    check("宿主配了 fanart key 时宿主优先",
          module.fanart_api_key() == "host-key-999", module.fanart_api_key())
finally:
    module.mp_setting = _orig_mp_setting
    if _orig_env is None:
        os.environ.pop("FANART_API_KEY", None)
    else:
        os.environ["FANART_API_KEY"] = _orig_env

print()
print("=" * 70)
print("回归：本地残留的「对象字面量」脏值必须被清掉（工作室那栏的现象）")
print("=" * 70)
JUNK_A = "{'id': 3756, 'logo_path': '/x.png', 'name': 'CoMix Wave Films', 'origin_country': 'JP'}"
JUNK_B = "{'id': 128616, 'name': 'Story', 'origin_country': 'JP'}"

studio_root = DATA_PATH / "studiolib"
movie_dir = studio_root / "电影" / "某片 (2023)"
movie_dir.mkdir(parents=True, exist_ok=True)
studio_nfo = movie_dir / "movie.nfo"

strip_cache = DATA_PATH / "studio_cache.json"
strip_cache.write_text(json.dumps({"movie:997": {
    "title": ["某片"], "year": ["2023"],
    "studio": ["CoMix Wave Films", "Story", "KADOKAWA"],
}}, ensure_ascii=False), encoding="utf-8")
nostudio_cache = DATA_PATH / "studio_cache_none.json"
nostudio_cache.write_text(json.dumps({"movie:997": {
    "title": ["某片"], "year": ["2023"],
}}, ensure_ascii=False), encoding="utf-8")


def run_studio(body, tag, cache=None):
    studio_nfo.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>\n'
        '  <title>某片</title>\n  <year>2023</year>\n  <tmdbid>997</tmdbid>\n'
        + body + "</movie>\n", encoding="utf-8")
    report = module.Engine(
        module.EngineConfig(roots=[studio_root], mode="sync",
                            manifest_path=DATA_PATH / f"studio_{tag}.json"),
        module.FileProvider(str(cache or strip_cache))).run()
    return studio_nfo.read_text(encoding="utf-8"), report


# 场景 A：干净名字与脏字典并存 —— 正是用户截图里的样子
CLEAN3 = ("  <studio>CoMix Wave Films</studio>\n  <studio>Story</studio>\n"
          "  <studio>KADOKAWA</studio>\n")
after_a, rep_a = run_studio(CLEAN3 + f"  <studio>{JUNK_A}</studio>\n  <studio>{JUNK_B}</studio>\n", "a")
check("场景A：脏 studio 被清掉，只留干净名字",
      after_a.count("<studio>") == 3 and "{'id'" not in after_a
      and "CoMix Wave Films" in after_a, after_a)
check("场景A：清理数量记进了报告", rep_a.scrubbed >= 2, f"scrubbed={rep_a.scrubbed}")

# 场景 B：脏值藏在同义标签 <network> 里，studio 本身是干净的（会被判为「一致」而跳过）
after_b, rep_b = run_studio(CLEAN3 + f"  <network>{JUNK_A}</network>\n", "b")
check("场景B：同义标签 <network> 里的脏值也被清掉",
      "<network>" not in after_b and "{'id'" not in after_b, after_b)
check("场景B：干净的 studio 一个不多一个不少", after_b.count("<studio>") == 3, after_b)

# 场景 C：在线没有这个字段时，只清脏值，不能把正常内容一起清空
after_c, _ = run_studio(
    "  <studio>CoMix Wave Films</studio>\n  <studio>保留我</studio>\n"
    f"  <studio>{JUNK_B}</studio>\n", "c", cache=nostudio_cache)
check("场景C：脏值清掉、正常值保留（不会因为整体重写而丢内容）",
      "{'id'" not in after_c and "CoMix Wave Films" in after_c
      and "保留我" in after_c and after_c.count("<studio>") == 2, after_c)

check("清理脏值只认「对象字面量」，正常片名不受影响",
      not module.looks_like_object_repr("Knives Out")
      and not module.looks_like_object_repr("CG 工作室")
      and not module.looks_like_object_repr("第 3 季"))

print()
print("=" * 70)
print("回归：以前会漏掉脏值清理的四条路径（用户反馈「升级了也没修好」）")
print("=" * 70)
empty_cache = DATA_PATH / "empty_cache.json"
empty_cache.write_text("{}", encoding="utf-8")
DIRTY = CLEAN3 + f"  <studio>{JUNK_A}</studio>\n"


def run_case(body, mode="sync", cache=None, protect=(), tag="x"):
    studio_nfo.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>\n'
        '  <title>某片</title>\n  <year>2023</year>\n  <tmdbid>997</tmdbid>\n'
        + body + "</movie>\n", encoding="utf-8")
    report = module.Engine(
        module.EngineConfig(roots=[studio_root], mode=mode, protect_fields=set(protect),
                            manifest_path=DATA_PATH / f"case_{tag}.json"),
        module.FileProvider(str(cache or strip_cache))).run()
    return studio_nfo.read_text(encoding="utf-8"), report


# ① 拿不到在线数据：以前直接 return，脏值永远留着
after_u, rep_u = run_case(DIRTY, cache=empty_cache, tag="unresolved")
check("① 拿不到在线数据时也会清掉脏 studio（正常值保留）",
      after_u.count("<studio>") == 3 and "{'id'" not in after_u
      and "CoMix Wave Films" in after_u, after_u)
check("① 清理数量计入报告（详情页能看到）", rep_u.scrubbed >= 1, str(rep_u.scrubbed))

# ② 只补缺失模式：以前被判为 REPLACE 而整条跳过
after_g, _ = run_case(DIRTY, mode="gapfill", tag="gapfill")
check("②「只补缺失」模式不再挡住脏值清理",
      after_g.count("<studio>") == 3 and "{'id'" not in after_g, after_g)

# ③ 保护字段：以前也会挡住
after_p, _ = run_case(DIRTY, protect=("studio",), tag="protect")
check("③「保护字段」不再挡住脏值清理",
      after_p.count("<studio>") == 3 and "{'id'" not in after_p, after_p)

# ④ lockdata 锁定：脏值是本插件旧版写坏的，锁不该保护自己的 bug 产物
after_l, _ = run_case("  <lockdata>true</lockdata>\n" + DIRTY, tag="locked")
check("④ 被 lockdata 锁定的条目也会清掉脏值（原文件已备份）",
      after_l.count("<studio>") == 3 and "{'id'" not in after_l, after_l)

# ⑤ 只报告模式：按设计一个字节都不写
after_r, _ = run_case(DIRTY, mode="report", tag="report")
check("⑤「只报告」模式不写盘（脏值留给下次 sync 清）",
      "{'id'" in after_r and after_r.count("<studio>") == 4, after_r)

print()
print("=" * 70)
print("回归：单集 NFO 里的 tmdbid 是「单集 id」，不能当剧集 id 用")
print("=" * 70)
check("目录名工具：{tmdbid=xxx} / 标题年份 都能解析",
      module.tmdb_id_from_dir("藏海传 (2025) {tmdbid=252640}") == "252640"
      and module.title_year_from_dir("藏海传 (2025) {tmdbid=252640}")[0].startswith("藏海传")
      and module.title_year_from_dir("藏海传 (2025) {tmdbid=252640}")[1] == "2025"
      and module.tmdb_id_from_dir("怪奇物语 (2016)") is None)

# ① 有 tvshow.nfo：即使单集 NFO 写了自己的 tmdbid，也要用剧集 id
ep_nfo_path = FIX / "电视剧" / "怪奇物语 (2016)" / "Season 01" / "怪奇物语 - S01E01.nfo"
ep_loaded = module.load_nfo(ep_nfo_path)
ET.SubElement(ep_loaded.root, "tmdbid").text = "5301287"      # 单集自己的 id
ep_engine = module.Engine(module.EngineConfig(roots=[FIX]),
                          module.FileProvider(str(DATA_PATH / "empty_cache.json")))
ep_id, ep_src = ep_engine.resolve_tmdb_id(ep_loaded)
check("① 单集 NFO 里的 tmdbid 不会被当作剧集 id（取 tvshow.nfo 的）",
      ep_id == "66732", f"得到 {ep_id}（{ep_src}）")

# ② 没有 tvshow.nfo：退到剧集目录名里的 {tmdbid=xxx}（用户库的真实目录结构）
user_show = DATA_PATH / "dirid" / "国产剧" / "藏海传 (2025) {tmdbid=252640}" / "Season 01"
user_show.mkdir(parents=True, exist_ok=True)
user_ep = user_show / "藏海传 S01E07 2160p.WEB-DL.H265.DTS 5.1-CHDWEB.nfo"
user_ep.write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<episodedetails>\n'
    '  <title>第 7 集</title>\n  <season>1</season>\n  <episode>7</episode>\n'
    '  <tmdbid>5301287</tmdbid>\n</episodedetails>\n', encoding="utf-8")
user_loaded = module.load_nfo(user_ep)
user_engine = module.Engine(module.EngineConfig(roots=[DATA_PATH]),
                            module.FileProvider(str(DATA_PATH / "empty_cache.json")))
user_id, user_src = user_engine.resolve_tmdb_id(user_loaded)
check("② 没有 tvshow.nfo 时用剧集目录名里的 tmdbid（复现用户那两条日志）",
      user_id == "252640", f"得到 {user_id}（{user_src}）")
check("② 全程不会退回到单集自己的 id", user_id != "5301287")
check("② 来源标注可读", "目录名" in user_src, user_src)

print()
print("=" * 70)
print("回归：season.nfo 的季号只能从目录名取（用户日志「无法确定季号」）")
print("=" * 70)
check("目录名解析季号：Season 01 / S01 / 第 1 季 等写法都认",
      module.season_from_dir("Season 01") == "1"
      and module.season_from_dir("S01") == "1"
      and module.season_from_dir("season 3") == "3"
      and module.season_from_dir("第 1 季") == "1"
      and module.season_from_dir("第01季") == "1"
      and module.season_from_dir("1 季") == "1", str(module.season_from_dir("Season 01")))
check("认不出季号的目录名不会瞎猜",
      module.season_from_dir("电影") is None
      and module.season_from_dir("Specials") in (None, "0")
      and module.season_from_dir("Se7en") is None
      and module.season_from_dir("") is None
      and module.season_from_dir("S01E01") is None)   # 文件名的形态不该被当目录名
check("花絮/特典目录按惯例归到第 0 季",
      module.season_from_dir("Specials") == "0"
      and module.season_from_dir("特别篇") == "0"
      and module.season_from_dir("特典") == "0")
check("带后缀的季目录也能认（Season 1 - 1080p）",
      module.season_from_dir("Season 1 - 1080p") == "1")

# 复现用户结构：国产剧/潜伏 (2009) {tmdbid=21712}/Season 01/season.nfo，且 NFO 里没有 <season>
latent = DATA_PATH / "dirid" / "国产剧" / "潜伏 (2009) {tmdbid=21712}" / "Season 01"
latent.mkdir(parents=True, exist_ok=True)
latent_nfo = latent / "season.nfo"
latent_nfo.write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<season>\n'
    '  <title>第 1 季</title>\n</season>\n', encoding="utf-8")
latent_cache = DATA_PATH / "latent_cache.json"
latent_cache.write_text(json.dumps({"season:21712:1": {
    "title": ["第 1 季"], "plot": ["剧情简介"], "premiered": ["2009-04-01"], "season": ["1"],
}}, ensure_ascii=False), encoding="utf-8")
latent_rep = module.Engine(
    module.EngineConfig(roots=[DATA_PATH / "dirid"], mode="sync",
                        manifest_path=DATA_PATH / "latent_manifest.json"),
    module.FileProvider(str(latent_cache))).run()
after_latent = latent_nfo.read_text(encoding="utf-8")
check("① season.nfo 没写 <season> 时，从上级目录「Season 01」取到季号并补齐",
      "<season>1</season>" in after_latent.replace(" ", ""), after_latent)
check("① 不再报「无法确定季号」", "无法确定季号" not in latent_rep.to_text())
check("① 剧集 id 也来自目录名（tmdb:21712）",
      latent_rep.provider is not None and latent_rep.calls >= 1, str(latent_rep.calls))

print()
print("=" * 70)
print("网络抖动自动重试（用户日志里的 SSL handshake timed out）")
print("=" * 70)


class _FakeHttpResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FlakyOpener:
    """前 fail_times 次抛网络异常，之后返回数据。"""

    def __init__(self, fail_times, payload=None, error=None):
        self.fail_times = fail_times
        self.calls = 0
        self.payload = payload if payload is not None else {"title": "ok"}
        self.error = error or OSError(
            "<urlopen error _ssl.c:993: The handshake operation timed out>")

    def open(self, request, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return _FakeHttpResponse(self.payload)


def _provider_with(opener):
    prov = module.TmdbProvider("KEY", "zh-CN", None, "US", 20, "standard")
    prov.limiter = module.RateLimiter(0)      # 测试里不限速
    prov.opener = opener
    return prov


_orig_wait = module.TMDB_RETRY_WAIT
module.TMDB_RETRY_WAIT = 0.01                 # 测试里别真等
try:
    flaky = _FlakyOpener(2)
    prov = _provider_with(flaky)
    check("SSL 握手超时会被自动重试，最终成功拿到数据",
          prov._get("/movie/137") == {"title": "ok"} and flaky.calls == 3, f"calls={flaky.calls}")
    check("重试次数记在 provider.retries（报告里会显示）", prov.retries == 2, str(prov.retries))
    check("「在线请求」按实际尝试次数计", prov.calls == 3, str(prov.calls))

    dead = _FlakyOpener(99)
    prov2 = _provider_with(dead)
    check("重试用尽才放弃并返回 None", prov2._get("/movie/1") is None and dead.calls == 3,
          f"calls={dead.calls}")

    class _NotFoundOpener:
        def __init__(self):
            self.calls = 0

        def open(self, request, timeout=None):
            self.calls += 1
            raise module.urllib.error.HTTPError("u", 404, "Not Found", None, None)

    nf = _NotFoundOpener()
    prov3 = _provider_with(nf)
    check("404 不重试（资源不存在，重试没意义）",
          prov3._get("/movie/1") is None and nf.calls == 1 and prov3.retries == 0,
          f"calls={nf.calls} retries={prov3.retries}")

    class _LimitedOpener:
        def __init__(self):
            self.calls = 0

        def open(self, request, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise module.urllib.error.HTTPError("u", 429, "Too Many", None, None)
            return _FakeHttpResponse({"title": "ok"})

    lim = _LimitedOpener()
    prov4 = _provider_with(lim)
    check("被限流（429）也会重试", prov4._get("/movie/1") == {"title": "ok"} and lim.calls == 2,
          f"calls={lim.calls}")

    check("报告里有「网络抖动自动重试」这一行",
          "网络抖动自动重试" in module.Report(retried=7).to_text())
finally:
    module.TMDB_RETRY_WAIT = _orig_wait

print()
print("=" * 70)
print("回归：没有第 0 季的剧不该被写出 season00-poster.jpg")
print("=" * 70)
check("中文数字转换：一/十/十二/二十/二十一",
      module.cn_number("一") == 1 and module.cn_number("十") == 10
      and module.cn_number("十二") == 12 and module.cn_number("二十") == 20
      and module.cn_number("二十一") == 21 and module.cn_number("九十九") == 99
      and module.cn_number("") is None and module.cn_number("abc") is None)
check("中文季目录名也能认：第一季 / 第十二季",
      module.season_from_dir("第一季") == "1"
      and module.season_from_dir("第十二季") == "12"
      and module.season_from_dir("第二季") == "2", str(module.season_from_dir("第一季")))

# 复现用户日志：走向共和 (2003) {tmdbid=66498}/第一季/season.nfo，且 NFO 里没有 <season>
# 旧版：取名用「默认 0」→ 写出 season00-poster.jpg；取图用另一套解析 → 拿到第 1 季的图
xiang = DATA_PATH / "dirid" / "电视剧" / "国产剧" / "走向共和 (2003) {tmdbid=66498}" / "第一季"
xiang.mkdir(parents=True, exist_ok=True)
xiang_nfo_path = xiang / "season.nfo"
xiang_nfo_path.write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<season>\n'
    '  <title>第一季</title>\n</season>\n', encoding="utf-8")
xiang_loaded = module.load_nfo(xiang_nfo_path)
xiang_engine = module.Engine(module.EngineConfig(roots=[DATA_PATH]),
                             module.FileProvider(str(DATA_PATH / "empty_cache.json")))
xiang_season, _ = xiang_engine.resolve_season_episode(xiang_loaded, "season")
check("① 中文目录「第一季」解析为第 1 季（不再是未知 → 0）", xiang_season == "1", str(xiang_season))
xiang_names = {path.name for _, path in
               module.image_targets(xiang_loaded, {"poster"}, season=xiang_season)}
check("② 季图两处都写：季目录 poster.jpg + 剧集根目录 season01-poster.jpg（对齐 MP）",
      xiang_names == {"poster.jpg", "season01-poster.jpg"},
      str(sorted(xiang_names)))

# 季号确实解析不出来时：宁可不写季专用名，也不写 season00
unknown = module.NfoFile(path=DATA_PATH / "dirid" / "未知季" / "season.nfo", media_type="season",
                         tree=ET.ElementTree(ET.fromstring("<season><title>x</title></season>")))
unknown_names = {path.name for _, path in module.image_targets(unknown, {"poster"})}
check("③ 季号未知时跳过季专用文件名（只留季目录里的 poster.jpg）",
      unknown_names == {"poster.jpg"}, str(sorted(unknown_names)))

print()
print("=" * 70)
print("季图落盘规则：与 MP 一致 —— 季目录通用名 + 剧集根目录 seasonNN 副本")
print("=" * 70)
season_root = DATA_PATH / "seasonlib"
show_dir = season_root / "电视剧" / "某剧 (2016) {tmdbid=66732}"
season_dir = show_dir / "Season 01"
season_dir.mkdir(parents=True, exist_ok=True)
(show_dir / "tvshow.nfo").write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<tvshow>\n'
    '  <title>某剧</title>\n  <tmdbid>66732</tmdbid>\n</tvshow>\n', encoding="utf-8")
(season_dir / "season.nfo").write_text(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<season>\n'
    '  <title>第 1 季</title>\n  <season>1</season>\n</season>\n', encoding="utf-8")

img_dir = DATA_PATH / "season_images"
img_dir.mkdir(parents=True, exist_ok=True)
shutil.copy(FIX.parent / "images" / "season1.png", img_dir / "season1.png")

season_cache = DATA_PATH / "season_cache.json"
season_cache.write_text(json.dumps({
    "season:66732:1": {"title": ["第 1 季"], "season": ["1"]},
    "images:season:66732:1": {"poster": str(img_dir / "season1.png")},
}, ensure_ascii=False), encoding="utf-8")

# 同一条目，但在线没有任何图片素材（用来验证「明确标注缺失、不回退」）
season_cache_none = DATA_PATH / "season_cache_none.json"
season_cache_none.write_text(json.dumps({
    "season:66732:1": {"title": ["第 1 季"], "season": ["1"]},
}, ensure_ascii=False), encoding="utf-8")


def run_season(tag, cache=None):
    cfg = module.EngineConfig(roots=[season_root], mode="sync", image_mode="sync",
                              image_kinds={"poster"},
                              manifest_path=DATA_PATH / f"season_{tag}.json")
    return module.Engine(cfg, module.FileProvider(str(cache or season_cache))).run()


def root_season_posters():
    return sorted(p.name for p in show_dir.iterdir()
                  if p.name.startswith("season") and p.name.endswith("-poster.jpg"))


# 正常匹配到在线季海报 → 两处都写（与 MP 的 _get_target_fileitems_and_paths 一致）
report_a = run_season("a")
check("① 季图写入季目录：Season 01/poster.jpg",
      (season_dir / "poster.jpg").exists(), str(sorted(p.name for p in season_dir.iterdir())))
check("② 同时写入剧集根目录：season01-poster.jpg（对齐 MP 的双落点）",
      root_season_posters() == ["season01-poster.jpg"], str(root_season_posters()))
check("② 两份内容一致（同一张在线图，只下载一次）",
      (season_dir / "poster.jpg").read_bytes() == (show_dir / "season01-poster.jpg").read_bytes())

# 幂等：再跑一次不该重复写（指纹清单命中）
report_a2 = run_season("a")
check("② 二次运行幂等：两处都已存在且与在线一致 → 零写入",
      (show_dir / "season01-poster.jpg").exists()
      and report_a2.images_written == 0, f"written={report_a2.images_written}")

# 重置：清掉两处，让后续用例从干净状态开始
(season_dir / "poster.jpg").unlink(missing_ok=True)
(show_dir / "season01-poster.jpg").unlink(missing_ok=True)

# 季 0（特别篇）：根目录副本按 MP 的写法用 season-specials-poster
special_dir = show_dir / "Specials"
special_dir.mkdir(parents=True, exist_ok=True)
special_nfo = module.NfoFile(path=special_dir / "season.nfo", media_type="season",
                             tree=ET.ElementTree(ET.fromstring(
                                 "<season><title>特别篇</title><season>0</season></season>")))
special_names = {path.name for _, path in module.image_targets(special_nfo, {"poster"}, season="0")}
check("⑤ 特别篇（季 0）根目录副本写成 season-specials-poster.jpg（与 MP 一致）",
      "season-specials-poster.jpg" in special_names and "season00-poster.jpg" not in special_names,
      str(sorted(special_names)))
shutil.rmtree(special_dir, ignore_errors=True)

# 该季在线没有任何图片素材 → 明确标注缺失，且绝不回退用剧集/别季海报
report_c = run_season("c", cache=season_cache_none)
check("④ 该季在线无海报时明确标注缺失（不是静默跳过）",
      report_c.images_missing >= 1, f"images_missing={report_c.images_missing}")
check("④ 也不会回退：季目录里不会凭空出现 poster.jpg",
      sorted(p.name for p in season_dir.iterdir()) == ["season.nfo"],
      str(sorted(p.name for p in season_dir.iterdir())))
check("④ 报告里能读到这条缺失说明",
      "在线没有海报" in report_c.to_text(), report_c.to_text()[-300:])

print()
print("=" * 70)
print("fanart.tv：光盘图 / 横幅图 / 透明艺术图 / 横版缩略图")
print("=" * 70)
_orig_urlopen = module.urllib.request.urlopen
_orig_mp = module.mp_setting
try:
    module.mp_setting = lambda name, default=None: (
        {"FANART_LANG": "zh,en"}.get(name, default))

    check("选图优先语言偏好（zh > en），再按点赞数",
          module.pick_fanart_image([
              {"url": "b_en.jpg", "lang": "en", "likes": "9"},
              {"url": "b_zh.jpg", "lang": "zh", "likes": "1"},
              {"url": "b_jp.jpg", "lang": "jp", "likes": "99"},
          ]) == "b_zh.jpg"
          and module.pick_fanart_image([
              {"url": "b_en.jpg", "lang": "en", "likes": "2"},
              {"url": "b_pl.jpg", "lang": "pl", "likes": "99"},
          ]) == "b_en.jpg")

    payload = {
        "moviebanner": [{"url": "http://a/b_en.jpg", "lang": "en", "likes": "5"},
                        {"url": "http://a/b_zh.jpg", "lang": "zh", "likes": "1"}],
        "moviedisc": [{"url": "http://a/d1.png", "lang": "00", "likes": "9"}],
        "moviethumb": [{"url": "http://a/mt_zh.jpg", "lang": "zh", "likes": "7"}],
        "tvthumb": [{"url": "http://a/tt_zh.jpg", "lang": "zh", "likes": "7"}],
        "seasonposter": [
            {"url": "http://a/s1p.jpg", "lang": "zh", "likes": "3", "season": "1"},
            {"url": "http://a/s2p.jpg", "lang": "zh", "likes": "9", "season": "2"},
        ],
        "seasonthumb": [
            {"url": "http://a/s1t.jpg", "lang": "zh", "likes": "4", "season": "1"},
            {"url": "http://a/s1t_en.jpg", "lang": "en", "likes": "40", "season": "1"},
            {"url": "http://a/s2t.jpg", "lang": "zh", "likes": "8", "season": "2"},
        ],
        "seasonbanner": [
            {"url": "http://a/s1b.jpg", "lang": "zh", "likes": "2", "season": "1"},
        ],
    }

    class _FakeFanart:
        def __init__(self, data):
            self._data = data

        def read(self):
            return json.dumps(self._data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = getattr(request, "full_url", "")
        return _FakeFanart(payload)

    module.urllib.request.urlopen = fake_urlopen
    try:
        urls = module.fanart_image_urls({"banner", "disc", "clearart"}, "812", "", "KEY")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("电影按 tmdbid 查询，横幅优先中文、光盘取唯一一张",
          urls.get("banner") == "http://a/b_zh.jpg" and urls.get("disc") == "http://a/d1.png"
          and "clearart" not in urls, str(urls))
    check("请求地址指向 fanart.tv 的电影接口并带上 Key",
          "/v3/movies/812?api_key=KEY" in captured.get("url", ""), captured.get("url", ""))

    module.urllib.request.urlopen = fake_urlopen
    try:
        urls_tv = module.fanart_image_urls({"banner"}, "", "355730", "KEY")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("剧集按 thetvdb id 查询", "/v3/tv/355730?api_key=KEY" in captured.get("url", "")
          and urls_tv.get("banner") == "http://a/b_zh.jpg", captured.get("url", ""))

    # thumb / landscape 走 fanart 的横版缩略图，且按媒体类型选对键
    module.urllib.request.urlopen = fake_urlopen
    try:
        thumb_movie = module.fanart_image_urls({"thumb", "landscape"}, "812", "", "KEY",
                                               "movie")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("电影 thumb/landscape 取 fanart 的 moviethumb（横版缩略图）",
          thumb_movie.get("thumb") == "http://a/mt_zh.jpg"
          and thumb_movie.get("landscape") == "http://a/mt_zh.jpg", str(thumb_movie))

    module.urllib.request.urlopen = fake_urlopen
    try:
        thumb_tv = module.fanart_image_urls({"thumb", "landscape"}, "", "355730", "KEY",
                                            "tvshow")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("剧集 thumb/landscape 取 fanart 的 tvthumb",
          thumb_tv.get("thumb") == "http://a/tt_zh.jpg"
          and thumb_tv.get("landscape") == "http://a/tt_zh.jpg", str(thumb_tv))

    check("没有 Key 时不发请求、返回空",
          module.fanart_image_urls({"banner", "disc"}, "812", "", "") == {})
    check("剧集既没有 tvdbid 也没有 tmdbid 时不发请求",
          module.fanart_image_urls({"banner"}, "", "", "KEY") == {})
    check("不需要 fanart 的类型（如海报）不会触发查询",
          module.fanart_image_urls({"poster"}, "812", "", "KEY") == {})

    # 季级别：seasonposter / seasonbanner / seasonthumb 是带 season 字段的数组，必须按季筛选
    module.urllib.request.urlopen = fake_urlopen
    try:
        s1 = module.fanart_season_image_urls({"poster", "banner", "thumb"}, "1", "355730", "KEY")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("季图片按季号筛选：第 1 季取到 s1 的图，不串到第 2 季",
          s1.get("poster") == "http://a/s1p.jpg"
          and s1.get("banner") == "http://a/s1b.jpg"
          and s1.get("thumb") == "http://a/s1t.jpg", str(s1))

    check("季图片语言偏好同样生效（zh 优先于票数更高的 en）",
          s1.get("thumb") == "http://a/s1t.jpg", str(s1))

    module.urllib.request.urlopen = fake_urlopen
    try:
        s2 = module.fanart_season_image_urls({"poster", "thumb"}, "2", "355730", "KEY")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("第 2 季只取 s2 的图（s1 的不会被当成 s2 的）",
          s2.get("poster") == "http://a/s2p.jpg" and s2.get("thumb") == "http://a/s2t.jpg",
          str(s2))
    module.urllib.request.urlopen = fake_urlopen
    try:
        s1_padded = module.fanart_season_image_urls({"poster"}, "01", "355730", "KEY")
    finally:
        module.urllib.request.urlopen = _orig_urlopen
    check("季号写法兼容：'01' 与 '1' 等价",
          s1_padded.get("poster") == "http://a/s1p.jpg", str(s1_padded))
    check("季图没有 tvdbid 时不发请求",
          module.fanart_season_image_urls({"thumb"}, "1", "", "KEY") == {})
    check("季图请求指向 fanart.tv 的剧集接口",
          "/v3/tv/355730?api_key=KEY" in captured.get("url", ""), captured.get("url", ""))
finally:
    module.mp_setting = _orig_mp
check("恢复后语言偏好回到默认 zh,en", module.fanart_lang_order() == ["zh", "en"])

print()
print("=" * 70)
print("图片来源优先级：默认 TMDB 优先、fanart.tv 其次（可配置）")
print("=" * 70)
check("image_source_order 默认 TMDB -> fanart",
      module.image_source_order(None) == ["tmdb", "fanart"])
check("逗号字符串能解析成有序列表",
      module.image_source_order("fanart,tmdb") == ["fanart", "tmdb"])
check("列表也能解析（去重且保序）",
      module.image_source_order(["fanart", "tmdb", "fanart"]) == ["fanart", "tmdb"])
check("单个来源也接受（只用 tmdb）",
      module.image_source_order("tmdb") == ["tmdb"])
check("认不出的值直接丢掉；全认不出时回退默认（绝不返回空）",
      module.image_source_order(["weird", "  "]) == ["tmdb", "fanart"])
check("IMAGE_SOURCES 常量就是两者",
      set(module.IMAGE_SOURCES) == {"tmdb", "fanart"})

# 构造一个能同时从 TMDB 与 fanart 拿到 poster 的 provider，验证「先到先得」
class _PriorityProvider(module.TmdbProvider):
    """把两个源的取图结果都拦下来，只验证顺序（不发真实请求）。"""

    def __init__(self, order):
        self.api_key = "K"
        self.language = "zh-CN"
        self.fanart_key = "FANART"
        self.source_order = module.image_source_order(order)
        self.img_host = "https://image.tmdb.org/t/p/"
        self.calls = []

    def image_size(self, kind):
        return "w500"

    def _get(self, path, **params):
        return {"posters": [{"file_path": "/tmdb.jpg", "iso_639_1": "zh"}]}

    def _tvdb_id(self, tmdb_id):
        return "999"

    def _fetch_fanart_images(self, tmdb_id, media_type, season, kinds, out):
        self.calls.append("fanart")
        out.setdefault("poster", "https://assets.fanart.tv/poster.jpg")

    def _fetch_tmdb_images(self, tmdb_id, media_type, season, episode, kinds, out):
        self.calls.append("tmdb")
        out.setdefault("poster", "https://image.tmdb.org/t/p/w500/tmdb.jpg")


p_tmdb_first = _PriorityProvider("tmdb,fanart")
res_tmdb = p_tmdb_first.fetch_images("812", "movie", kinds=["poster"])
check("TMDB 优先时 poster 取 TMDB 的图",
      res_tmdb.get("poster") == "https://image.tmdb.org/t/p/w500/tmdb.jpg", str(res_tmdb))
check("TMDB 优先时先问 TMDB 再问 fanart",
      p_tmdb_first.calls == ["tmdb", "fanart"], str(p_tmdb_first.calls))

p_fanart_first = _PriorityProvider("fanart,tmdb")
res_fa = p_fanart_first.fetch_images("812", "movie", kinds=["poster"])
check("改成 fanart 优先后 poster 取 fanart 的图（TMDB 不再覆盖）",
      res_fa.get("poster") == "https://assets.fanart.tv/poster.jpg", str(res_fa))
check("fanart 优先时先问 fanart 再问 TMDB",
      p_fanart_first.calls == ["fanart", "tmdb"], str(p_fanart_first.calls))

p_tmdb_only = _PriorityProvider("tmdb")
p_tmdb_only.fetch_images("812", "movie", kinds=["poster"])
check("只配 tmdb 时不会再问 fanart",
      p_tmdb_only.calls == ["tmdb"], str(p_tmdb_only.calls))

print()
print("=" * 70)
print("并发（多线程）与「执行周期」留空 = 每周一次")
print("=" * 70)
check("并发下的 TMDB 间隔：单线程保持 4/秒，并发时放宽但设下限",
      module.tmdb_gap(1) == module.RATE_GAP
      and abs(module.tmdb_gap(2) - 0.125) < 1e-9
      and module.tmdb_gap(4) == module.RATE_GAP_MIN
      and module.tmdb_gap(64) == module.RATE_GAP_MIN)

# 限速器必须是「全局」的：多线程一起抢，总速率也不能翻倍
limiter = module.RateLimiter(0.02)
_start = time.monotonic()
with module.ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(lambda _: limiter.wait(), range(8)))
_elapsed = time.monotonic() - _start
check("RateLimiter 在多线程下仍保持全局速率（8 次 × 20ms 至少 120ms）",
      _elapsed >= 0.12, f"实际 {_elapsed:.3f}s")

# 「执行周期」留空 → 每周日凌晨 3 点
check("执行周期默认值是空的（用户不用懂 cron）", defaults["cron"] == "")
check("留空时的默认周期 = 每周日 03:00", module.WEEKLY_CRON == "0 3 * * 0")


class _FakeCronTrigger:
    """模拟 apscheduler 的 CronTrigger：字段数不对就抛错。"""

    captured = []

    @classmethod
    def from_crontab(cls, expr):
        cls.captured.append(expr)
        if len(str(expr or "").split()) != 5:
            raise ValueError("Wrong number of fields; got 1, expected 5")
        return ("cron-trigger", expr)


_real_cron = module.CronTrigger
module.CronTrigger = _FakeCronTrigger
try:
    cron_plugin = module.NfoGapFill()
    cron_plugin.init_plugin({**defaults, "enabled": True, "cron": ""})
    cron_plugin.get_service()
    check("get_service 在留空时用每周周期注册", _FakeCronTrigger.captured[-1] == module.WEEKLY_CRON,
          str(_FakeCronTrigger.captured))

    cron_plugin.init_plugin({**defaults, "enabled": True, "cron": "0 */6 * * *"})
    cron_plugin.get_service()
    check("填了 cron 就按填的来", _FakeCronTrigger.captured[-1] == "0 */6 * * *")

    cron_plugin.init_plugin({**defaults, "enabled": True, "cron": "not-a-cron"})
    cron_plugin.get_service()
    check("cron 写错时回退到每周一次", _FakeCronTrigger.captured[-1] == module.WEEKLY_CRON)
finally:
    module.CronTrigger = _real_cron

def _concurrency_of(base, value):
    probe = module.NfoGapFill()
    probe.init_plugin({**base, "concurrency": value})
    return probe._concurrency


check("并发数可从配置读入并会被限幅（1..16）",
      _concurrency_of(defaults, "4") == 4
      and _concurrency_of(defaults, "999") == 16
      and _concurrency_of(defaults, "0") == 1
      and _concurrency_of(defaults, "abc") == 4)
check("并发数也进了默认配置（表单有这一项）",
      "concurrency" in defaults and "'model': 'concurrency'" in form_json)

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

# pick_best_image：**只**按语言优先级挑，同级取 TMDB 原始顺序第一条
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

# 同级不再比分辨率/评分/票数 —— 取原始顺序第一条（对齐 MP 的"钦定图"行为）
best_res = module.pick_best_image(
    [{"file_path": "/small.jpg", "iso_639_1": None, "width": 500,
      "vote_average": 9.0, "vote_count": 99},
     {"file_path": "/big.jpg", "iso_639_1": None, "width": 2000,
      "vote_average": 5.0, "vote_count": 1}], "zh")
check("同语言档位内取 TMDB 原始顺序第一条（不再按分辨率挑）",
      best_res is not None and best_res["file_path"] == "/small.jpg")
best_order = module.pick_best_image(
    [{"file_path": "/zh_first.jpg", "iso_639_1": "zh", "width": 300,
      "vote_average": 1.0, "vote_count": 0},
     {"file_path": "/zh_second.jpg", "iso_639_1": "zh", "width": 9999,
      "vote_average": 9.9, "vote_count": 999}], "zh")
check("多条本语言时保留第一条（不被票数/分辨率带偏）",
      best_order is not None and best_order["file_path"] == "/zh_first.jpg")
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
check("电影图片目标 = poster / backdrop / fanart / logo / disc / banner / clearart / thumb / landscape",
      movie_targets == {("poster", "poster.jpg"), ("backdrop", "backdrop.jpg"),
                        ("backdrop", "fanart.jpg"), ("logo", "logo.png"),
                        ("disc", "disc.png"), ("banner", "banner.jpg"),
                        ("clearart", "clearart.png"),
                        ("thumb", "thumb.jpg"), ("thumb", "landscape.jpg")})
check("新增类型默认全选（8 类都在 IMAGE_KINDS 里）",
      len(module.IMAGE_KINDS) == 8
      and set(module.IMAGE_KINDS) == {"poster", "backdrop", "logo", "thumb",
                                      "banner", "disc", "clearart", "landscape"})
check("fanart 键名映射与 MoviePilot 的 FanartModule 一致",
      module.FANART_KEYS["banner"] == ("moviebanner", "tvbanner")
      and module.FANART_KEYS["disc"] == ("moviedisc",)
      and "hdmovieclearart" in module.FANART_KEYS["clearart"]
      and "moviethumb" in module.FANART_KEYS["landscape"])
check("根目录的 thumb 也走 fanart 的横版缩略图（不再用 TMDB 的 stills 剧照）",
      module.FANART_KEYS["thumb"] == ("moviethumb", "tvthumb")
      and "thumb" not in module.IMG_API_KEYS)
check("按媒体类型精确指定 fanart 键：电影 movie*、剧集 tv*",
      module.FANART_KEYS_BY_TYPE["movie"]["thumb"] == ("moviethumb",)
      and module.FANART_KEYS_BY_TYPE["tvshow"]["thumb"] == ("tvthumb",)
      and module.FANART_KEYS_BY_TYPE["tvshow"]["banner"] == ("tvbanner",))
check("剧集没有 disc（按类型精确表里不含）",
      "disc" not in module.FANART_KEYS_BY_TYPE["tvshow"])
check("季专用 fanart 键与 MP 的 seasonposter/seasonbanner/seasonthumb 对齐",
      module.FANART_SEASON_KEYS["poster"] == ("seasonposter",)
      and module.FANART_SEASON_KEYS["banner"] == ("seasonbanner",)
      and module.FANART_SEASON_KEYS["thumb"] == ("seasonthumb",))

# 单集的缩略图必须是「这一集的剧照」(TMDB stills)，不能被根目录那套 fanart 逻辑顶掉
_tmdb_src = _inspect.getsource(module.TmdbProvider._fetch_tmdb_images)
check("单集缩略图仍取 TMDB 的 stills（该集剧照）",
      'stills' in _tmdb_src and 'episodedetails' in _tmdb_src,
      "_fetch_tmdb_images 里应有 episode_thumb_key = 'stills'")

# 剧集：MP 的 tv 允许集合里**没有 disc**，所以 image_targets 不该产出 disc.png
tvshow_nfo = module.load_nfo(FIX / "电视剧" / "怪奇物语 (2016)" / "tvshow.nfo")
tvshow_specs = {(spec.kind, spec.name) for spec, _ in
                module.image_targets(tvshow_nfo, set(module.IMAGE_KINDS))}
check("剧集根目录不写 disc.png（与 MP 的 tv 允许集合一致）",
      ("disc", "disc.png") not in tvshow_specs
      and ("thumb", "thumb.jpg") in tvshow_specs
      and ("thumb", "landscape.jpg") in tvshow_specs,
      str(sorted(tvshow_specs)))
check("剧集根目录其余类型齐全",
      tvshow_specs == {("poster", "poster.jpg"), ("backdrop", "backdrop.jpg"),
                       ("backdrop", "fanart.jpg"), ("logo", "logo.png"),
                       ("banner", "banner.jpg"), ("clearart", "clearart.png"),
                       ("thumb", "thumb.jpg"), ("thumb", "landscape.jpg")})

season_tree = ET.ElementTree(ET.fromstring("<season><season>1</season></season>"))
season_nfo = module.NfoFile(path=Path("电视剧") / "怪奇物语 (2016)" / "Season 01" / "season.nfo",
                            media_type="season", tree=season_tree)
season_targets = module.image_targets(season_nfo, set(module.IMAGE_KINDS))

# 每个非别名季图类型都产出两个落点：剧集根目录 seasonNN-xxx + 季目录通用名
season_by_loc: Dict[str, list] = {"root": [], "season": []}
for spec, path in season_targets:
    where = "root" if path.parent.name == "怪奇物语 (2016)" else "season"
    season_by_loc[where].append((spec.kind, spec.name))
check("季图两处都写：剧集根目录 + 季目录（对齐 MP）",
      len(season_by_loc["season"]) == 4 and len(season_by_loc["root"]) == 3,
      f"season={season_by_loc['season']} root={season_by_loc['root']}")
check("季目录内的通用名 = poster / banner / thumb / landscape（对齐 MP 的 season）",
      {(k, n) for k, n in season_by_loc["season"]}
      == {("poster", "poster.jpg"), ("banner", "banner.jpg"),
          ("thumb", "thumb.jpg"), ("thumb", "landscape.jpg")},
      str(sorted(season_by_loc["season"])))
check("剧集根目录的副本 = season01-poster / -banner / -thumb（不带别名，与 MP 一致）",
      {(k, n) for k, n in season_by_loc["root"]}
      == {("poster", "poster.jpg"), ("banner", "banner.jpg"), ("thumb", "thumb.jpg")},
      str(sorted(season_by_loc["root"])))
check("根目录副本的文件名确实是 seasonNN- 形式",
      sorted(p.name for _, p in season_targets if p.parent.name == "怪奇物语 (2016)")
      == ["season01-banner.jpg", "season01-poster.jpg", "season01-thumb.jpg"],
      str(sorted(p.name for _, p in season_targets if p.parent.name == "怪奇物语 (2016)")))
season_poster_only = module.image_targets(season_nfo, {"poster"})
check("按 kinds 过滤生效（只要 poster 时不产出 backdrop）",
      {(s.kind, p.name) for s, p in season_poster_only}
      == {("poster", "poster.jpg"), ("poster", "season01-poster.jpg")},
      str(sorted((s.kind, p.name) for s, p in season_poster_only)))
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
check("详情页主视图改成「本次修改了哪些文件」清单，且不再用渲染不出来的 VDataTable",
      "VTextarea" in page_text and "VDataTable" not in page_text)
check("清单按文件列出字段/图片改动", "▍" in page_text and "字段：" in page_text
      and "星际穿越" in page_text)
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
