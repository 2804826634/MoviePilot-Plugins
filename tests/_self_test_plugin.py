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
                 "backup", "max_files", "paths", "exclude_paths", "protect_fields",
                 "only_fields", "tmdb_api_key", "language", "proxy", "cert_country", "cast_limit"}
check("默认配置包含全部配置项", expected_keys <= set(defaults),
      f"缺少 {expected_keys - set(defaults)}")
form_json = str(form[0])
missing_controls = [k for k in expected_keys if f"'model': '{k}'" not in form_json]
check("表单里每个配置项都有对应控件", not missing_controls, f"缺控件：{missing_controls}")
check("表单包含启用 / 立即运行 / 周期 三项关键控件",
      all(f"'model': '{k}'" in form_json for k in ("enabled", "onlyonce", "cron")))

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
      mock_host.MESSAGES and "NFO 差异比对" in mock_host.MESSAGES[0].get("title", ""))
check("save_data 被调用", "nfogapfill_report" in mock_host.DATA)

print()
print("=" * 70)
print("get_page / get_command / get_api / stop_service")
print("=" * 70)
page = plugin.get_page()
check("get_page 返回组件列表", isinstance(page, list) and len(page) >= 2)
check("get_page 能读到上次报告", "扫描 NFO" in str(page))
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
