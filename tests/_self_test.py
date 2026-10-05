# -*- coding: utf-8 -*-
"""NfoGapFill 自检：用本地 JSON 模拟在线数据，逐条验证「相同不动 / 缺失补齐 / 不同替换 / 锁定保护」。

不需要联网、不需要 TMDB Key。直接运行：
    python _self_test.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
FIX = HERE / "_fixture" / "媒体库"
CACHE = HERE / "_fixture" / "remote_cache.json"
PY = sys.executable
# 插件在仓库中的真实路径（与 MoviePilot 插件市场布局一致）
TOOL = REPO / "plugins.v2" / "nfogapfill" / "__init__.py"

MOVIE_A = FIX / "电影" / "星际穿越 (2014)" / "movie.nfo"
MOVIE_B = FIX / "电影" / "沙丘 (2021)" / "沙丘 (2021).nfo"
MOVIE_LOCKED = FIX / "电影" / "锁定测试 (2000)" / "movie.nfo"
TVSHOW = FIX / "电视剧" / "怪奇物语 (2016)" / "tvshow.nfo"
EPISODE = FIX / "电视剧" / "怪奇物语 (2016)" / "Season 01" / "怪奇物语 - S01E01.nfo"

FIXTURES = {
    MOVIE_A: """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>星际穿越</title>
  <originaltitle>Interstellar</originaltitle>
  <plot></plot>
  <year>2014</year>
  <uniqueid type="tmdb" default="true">157336</uniqueid>
  <tmdbid>157336</tmdbid>
  <genre>科幻</genre>
  <director>Christopher Nolan</director>
</movie>
""",
    MOVIE_B: """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>沙丘</title>
  <year>2022</year>
  <tmdbid>438631</tmdbid>
  <plot>这是本地手工写的一段简介，内容与在线不同。</plot>
</movie>
""",
    MOVIE_LOCKED: """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>锁定测试</title>
  <year>1900</year>
  <tmdbid>1</tmdbid>
  <lockdata>true</lockdata>
</movie>
""",
    TVSHOW: """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<tvshow>
  <title>怪奇物语</title>
  <plot>1983年的印第安纳州，一个小男孩离奇失踪。</plot>
  <tmdbid>66732</tmdbid>
</tvshow>
""",
    EPISODE: """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<episodedetails>
  <plot></plot>
  <season>1</season>
  <episode>1</episode>
</episodedetails>
""",
}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail and not ok else ""))


def reset_fixture():
    for path, text in FIXTURES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    shutil.rmtree(FIX / ".nfo-backup", ignore_errors=True)


def run(*extra):
    cmd = [PY, str(TOOL), "--root", str(FIX), "--source", "file", "--cache", str(CACHE), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    return proc.stdout


if "--reset-only" in sys.argv:
    reset_fixture()
    print(f"样例库已重置为「待修复」状态：{FIX}")
    sys.exit(0)


print("=" * 70)
print("第 1 轮：只报告，验证不写盘")
print("=" * 70)
reset_fixture()
before_locked = MOVIE_LOCKED.read_text(encoding="utf-8")
out = run("--mode", "report")
check("report 模式不写盘（沙丘 year 仍为 2022）", "<year>2022</year>" in MOVIE_B.read_text(encoding="utf-8"))
check("report 输出包含差异统计", "差异判定" in out)
check("锁定 NFO 未被触碰", MOVIE_LOCKED.read_text(encoding="utf-8") == before_locked)

print()
print("=" * 70)
print("第 2 轮：预演 + 正式同步")
print("=" * 70)
out = run("--mode", "sync", "--dry-run", "--fix")
check("dry-run 不写盘", "<year>2022</year>" in MOVIE_B.read_text(encoding="utf-8"))

out = run("--mode", "sync", "--fix")
text_a = MOVIE_A.read_text(encoding="utf-8")
text_b = MOVIE_B.read_text(encoding="utf-8")
text_ep = EPISODE.read_text(encoding="utf-8")
text_tv = TVSHOW.read_text(encoding="utf-8")

check("缺失字段被补齐（星际穿越 plot）",
      "一支探险队利用虫洞穿越星际，为人类寻找新的家园。" in text_a,
      "全角逗号必须原样保留，不能被 NFKC 规范化")
check("本地空 plot 只有一个节点", text_a.count("<plot>") == 1)
check("相同字段未被改动（title / director 原样）",
      "<title>星际穿越</title>" in text_a and "<director>Christopher Nolan</director>" in text_a)
check("不一致字段被替换（genre 1 项 → 3 项）", text_a.count("<genre>") == 3)
check("不重复追加同名标签", text_a.count("<title>") == 1 and text_a.count("<year>") == 1)
check("数值型不一致被替换（沙丘 year 2022 → 2021）", "<year>2021</year>" in text_b)
check("文本型不一致被替换（沙丘 plot 换成在线值）",
      "保罗·厄崔迪前往厄拉科斯星球" in text_b and "这是本地手工写的一段简介" not in text_b)
check("沙丘 plot 未被重复创建", text_b.count("<plot>") == 1)
check("TV 相同 plot 未动", "1983年的印第安纳州，一个小男孩离奇失踪。" in text_tv)
check("TV 缺失字段被补齐（premiered）", "<premiered>2016-07-15</premiered>" in text_tv)
check("单集缺失字段被补齐（title / plot / director）",
      "第一章：威尔·拜尔斯失踪" in text_ep and "威尔在骑车回家的路上神秘失踪" in text_ep
      and "<director>The Duffer Brothers</director>" in text_ep)
check("lockdata=true 的 NFO 完全未改动", MOVIE_LOCKED.read_text(encoding="utf-8") == before_locked)
check("已生成备份", (FIX / ".nfo-backup" / "电影" / "沙丘 (2021)" / "沙丘 (2021).nfo").exists())
check("备份保留的是最初版本", "<year>2022</year>" in
      (FIX / ".nfo-backup" / "电影" / "沙丘 (2021)" / "沙丘 (2021).nfo").read_text(encoding="utf-8"))

print()
print("=" * 70)
print("第 3 轮：幂等 —— 再跑一次不应该有任何写入")
print("=" * 70)
snapshot = {p: p.read_text(encoding="utf-8") for p in FIXTURES}
out = run("--mode", "sync", "--fix")
check("第二次运行零写入", "已写入文件 0" in out, out.strip().splitlines()[-1] if out else "")
check("第二次运行全部文件字节级不变",
      all(p.read_text(encoding="utf-8") == snapshot[p] for p in FIXTURES))

print()
print("=" * 70)
print("第 4 轮：保护字段 —— 只补不换")
print("=" * 70)
reset_fixture()
out = run("--mode", "sync", "--fix", "--protect", "plot,year")
text_b = MOVIE_B.read_text(encoding="utf-8")
check("受保护字段 plot 未被替换", "这是本地手工写的一段简介" in text_b)
check("受保护字段 year 未被替换", "<year>2022</year>" in text_b)
check("未受保护的字段照常补齐（tagline）", "<tagline>恐惧是思维的杀手。</tagline>" in text_b)
check("报告标注了跳过原因", "受保护字段" in out)

print()
print("=" * 70)
print("第 5 轮：gapfill 模式（等价官方插件的「不覆盖已有元数据」）")
print("=" * 70)
reset_fixture()
run("--mode", "gapfill", "--fix")
text_a = MOVIE_A.read_text(encoding="utf-8")
text_b = MOVIE_B.read_text(encoding="utf-8")
check("gapfill 补缺失（星际穿越 plot）", "一支探险队利用虫洞穿越星际" in text_a)
check("gapfill 不替换不一致（genre 仍为 1 项）", text_a.count("<genre>") == 1)
check("gapfill 不替换不一致（沙丘 year 仍为 2022）", "<year>2022</year>" in text_b)

print()
print("=" * 70)
reset_fixture()   # 复原样例库：保证可重复运行，并清掉 .nfo-backup 残留
failed = [r for r in results if not r[1]]
print(f"共 {len(results)} 项断言，通过 {len(results) - len(failed)}，失败 {len(failed)}")
for name, _ok, detail in failed:
    print(f"  FAIL {name} {detail}")
print("=" * 70)
sys.exit(1 if failed else 0)
