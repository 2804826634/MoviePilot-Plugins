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
SEASON = FIX / "电视剧" / "怪奇物语 (2016)" / "Season 01" / "season.nfo"
EPISODE = FIX / "电视剧" / "怪奇物语 (2016)" / "Season 01" / "怪奇物语 - S01E01.nfo"
IMAGES = HERE / "_fixture" / "images"

# 图片落盘位置（与 MP / Kodi / Jellyfin 约定一致）
POSTER = FIX / "电影" / "星际穿越 (2014)" / "poster.jpg"
BACKDROP = FIX / "电影" / "星际穿越 (2014)" / "backdrop.jpg"
FANART = FIX / "电影" / "星际穿越 (2014)" / "fanart.jpg"
LOGO = FIX / "电影" / "星际穿越 (2014)" / "logo.png"
TV_POSTER = FIX / "电视剧" / "怪奇物语 (2016)" / "poster.jpg"
SEASON_POSTER = FIX / "电视剧" / "怪奇物语 (2016)" / "Season 01" / "poster.jpg"
SEASON_ROOT_POSTER = FIX / "电视剧" / "怪奇物语 (2016)" / "season01-poster.jpg"
EPISODE_THUMB = FIX / "电视剧" / "怪奇物语 (2016)" / "Season 01" / "怪奇物语 - S01E01.jpg"

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
    SEASON: """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<season>
  <title></title>
  <season>1</season>
</season>
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
    # 清掉上一轮写进样例库的图片，保证每轮起点一致（下面各轮会按需重新放置预置图）
    for pattern in ("*.jpg", "*.png", "*.nfgpart"):
        for stray in FIX.rglob(pattern):
            if stray.is_file():
                stray.unlink()
    shutil.rmtree(FIX / ".nfo-backup", ignore_errors=True)


def run(*extra, root=None):
    """root 可覆盖默认媒体库根目录，用于测试「#类型」后缀这类场景。"""
    cmd = [PY, str(TOOL), "--root", str(root if root is not None else FIX),
           "--source", "file", "--cache", str(CACHE), *extra]
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
print("第 6 轮：图片补全 —— 缺失补齐、别名、各类型落盘位置")
print("=" * 70)
reset_fixture()
out = run("--mode", "sync", "--fix", "--image-mode", "sync")
check("缺失海报被补齐（内容与在线图一致）",
      POSTER.exists() and POSTER.read_bytes() == (IMAGES / "poster_a.png").read_bytes())
check("缺失背景图被补齐", BACKDROP.exists() and BACKDROP.read_bytes() == (IMAGES / "backdrop_a.png").read_bytes())
check("fanart 别名与 backdrop 内容一致", FANART.exists() and FANART.read_bytes() == BACKDROP.read_bytes())
check("缺失徽标被补齐", LOGO.exists() and LOGO.read_bytes() == (IMAGES / "logo_a.png").read_bytes())
check("剧集海报被补齐", TV_POSTER.exists() and TV_POSTER.read_bytes() == (IMAGES / "poster_a.png").read_bytes())
check("季海报写入季目录", SEASON_POSTER.exists() and SEASON_POSTER.read_bytes() == (IMAGES / "season1.png").read_bytes())
check("季海报不再写剧集根目录（一季一图、各归其位）", not SEASON_ROOT_POSTER.exists(),
      f"不应存在 {SEASON_ROOT_POSTER}")
check("季目录里只有 poster.jpg 这一张季海报，没有 seasonNN-poster 之类的变体",
      SEASON_POSTER.exists()
      and not [x.name for x in SEASON_POSTER.parent.iterdir()
               if x.name.startswith("season") and "poster" in x.name.lower()],
      str(sorted(x.name for x in SEASON_POSTER.parent.iterdir())))
check("单集缩略图按 <视频名>.jpg 落盘",
      EPISODE_THUMB.exists() and EPISODE_THUMB.read_bytes() == (IMAGES / "still_a.png").read_bytes())
check("lockdata 条目连图片一起跳过", not (FIX / "电影" / "锁定测试 (2000)" / "poster.jpg").exists())
check("报告包含图片统计", "检查图片" in out)
check("报告包含图片判定与动作", "图片判定" in out and "图片动作" in out)

print()
print("=" * 70)
print("第 7 轮：图片幂等 —— 指纹清单让第二次运行零下载、零写入")
print("=" * 70)
before = {p: p.read_bytes() for p in (POSTER, BACKDROP, FANART, LOGO, TV_POSTER, EPISODE_THUMB)}
out = run("--mode", "sync", "--fix", "--image-mode", "sync")
check("第二次运行图片零写入", "写入 0 张" in out, out.strip().splitlines()[-1] if out else "")
check("第二次运行靠指纹判定一致（未重新下载比对）", "指纹匹配" in out)
check("第二次运行所有图片字节级不变",
      all(p.read_bytes() == before[p] for p in before))

print()
print("=" * 70)
print("第 8 轮：图片不一致则替换（并备份原图）")
print("=" * 70)
wrong = (IMAGES / "poster_wrong.png").read_bytes()
POSTER.write_bytes(wrong)
out = run("--mode", "sync", "--fix", "--image-mode", "sync")
check("放错的本地海报被替换回在线图", POSTER.read_bytes() == (IMAGES / "poster_a.png").read_bytes())
check("替换写入被记入报告", "图片动作" in out and "替换" in out)
check("被替换的原图已备份",
      (FIX / ".nfo-backup" / "电影" / "星际穿越 (2014)" / "poster.jpg").read_bytes() == wrong)

print()
print("=" * 70)
print("第 9 轮：image-mode=missing —— 只补缺失，不动已有图")
print("=" * 70)
reset_fixture()
POSTER.parent.mkdir(parents=True, exist_ok=True)
POSTER.write_bytes(wrong)          # 预置一张「错的」海报
out = run("--mode", "sync", "--fix", "--image-mode", "missing")
check("已存在的错图不被替换", POSTER.read_bytes() == wrong)
check("缺失的图仍然被补齐", BACKDROP.exists())
check("报告标注了「仅补缺失」", "仅补缺失" in out)

print()
print("=" * 70)
print("第 10 轮：演练模式下不写图片")
print("=" * 70)
reset_fixture()
out = run("--mode", "sync", "--dry-run", "--fix", "--image-mode", "sync")
check("演练模式不落任何图片", not POSTER.exists() and not BACKDROP.exists() and not LOGO.exists())
check("演练模式仍报告将要执行的图片动作", "演练" in out and "检查图片" in out)

print()
print("=" * 70)
print("第 11 轮：image-mode=off 完全不碰图片")
print("=" * 70)
reset_fixture()
out = run("--mode", "sync", "--fix", "--image-mode", "off")
check("关闭图片时不写图片", not POSTER.exists() and not BACKDROP.exists())
check("关闭图片时报告里没有图片统计", "检查图片" not in out)

print()
print("=" * 70)
print("第 12 轮：媒体库目录的「#类型」限定（只识别电影 / 只识别电视剧）")
print("=" * 70)
reset_fixture()
# 样例库共 6 个 NFO：电影 3 个、剧集相关 3 个（tvshow + season + 单集）
out = run("--mode", "report", root=f"{FIX}#电视剧")
check("限定 #电视剧：跳过 3 个电影 NFO", "按目录的「#类型」限定跳过 3 个 NFO" in out)
check("限定 #电视剧：只扫描剧集相关的 3 个 NFO", "扫描 NFO 3 个" in out)

out = run("--mode", "report", root=f"{FIX}#电影")
check("限定 #电影：跳过 3 个剧集 NFO", "按目录的「#类型」限定跳过 3 个 NFO" in out)
check("限定 #电影：只扫描 3 个电影 NFO", "扫描 NFO 3 个" in out)

out = run("--mode", "report", root=f"{FIX}/电影#电影")
check("限定子目录 /电影#电影 时也只处理电影", "扫描 NFO 3 个" in out
      and "按目录的「#类型」限定跳过" not in out)

out = run("--mode", "report", root=str(FIX))
check("不加 # 后缀时两种类型都处理（回归）", "扫描 NFO 6 个" in out
      and "按目录的「#类型」限定跳过" not in out)

print()
print("=" * 70)
print("第 13 轮：并发处理（--concurrency）结果必须与顺序执行完全一致")
print("=" * 70)
reset_fixture()
seq_out = run("--mode", "report")
reset_fixture()
par_out = run("--mode", "report", "--concurrency", "4")


def _summary(text):
    return next((line for line in text.splitlines() if line.startswith("扫描 NFO")), "")


def _details(text):
    return sorted(line for line in text.splitlines() if line.startswith("["))


seq_sum, par_sum = _summary(seq_out), _summary(par_out)
check("并发 4 与顺序执行的统计完全一致（没有丢计数）", seq_sum == par_sum,
      f"\n    顺序: {seq_sum}\n    并发: {par_sum}")
check("两者的变更明细条数与内容一致（没有串行化错误）",
      _details(seq_out) == _details(par_out),
      f"顺序 {len(_details(seq_out))} 条 / 并发 {len(_details(par_out))} 条")
check("日志里明确写出了并发数", "并发 4" in par_out)
check("顺序执行时不打印并发字样", "并发" not in seq_out)

print()
print("=" * 70)
reset_fixture()   # 复原样例库：保证可重复运行，并清掉 .nfo-backup 残留
failed = [r for r in results if not r[1]]
print(f"共 {len(results)} 项断言，通过 {len(results) - len(failed)}，失败 {len(failed)}")
for name, _ok, detail in failed:
    print(f"  FAIL {name} {detail}")
print("=" * 70)
sys.exit(1 if failed else 0)
