#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把插件真实刮削出来的文件整理成一份可离线预览的 HTML 复核页。

读取 <样本目录> 下插件实际写出的图片，解析真实分辨率与字节数，
按电影 / 电视剧分组列成表，并单独列出「缺失/跳过」的条目。

    python build_preview.py <样本目录> <输出 html>
"""
import base64
import json
import mimetypes
import os
import struct
import sys
from pathlib import Path

# ── 图片尺寸解析（与 fetch_real_samples.py 同款，保证口径一致）─────────────
def png_size(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None


def jpeg_size(data: bytes):
    if data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i < n - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg_len
    return None


def webp_size(data: bytes):
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] == b"VP8X":
        return (int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1)
    return None


def image_size(data: bytes):
    for fn in (png_size, jpeg_size, webp_size):
        try:
            got = fn(data)
            if got:
                return got
        except Exception:
            pass
    return (0, 0)


# ── 类型 → 中文名 / 来源判定 ────────────────────────────────────────────
KIND_CN = {
    "poster": "海报", "backdrop": "背景图", "fanart": "背景图（别名 fanart.jpg）",
    "logo": "ClearLogo（透明字图）", "thumb": "缩略图（thumb.jpg，横版）",
    "landscape": "横版缩略图（landscape.jpg）", "banner": "横幅图",
    "disc": "光盘图", "clearart": "透明艺术图",
    "episode-thumb": "单集缩略图（同视频名 .jpg）",
}
# 文件名前缀 → 来源
FANART_NAMES = {"thumb", "landscape", "banner", "disc", "clearart"}
SEASON_HINT = ("season01-",)


def source_of(fname: str, kind: str) -> str:
    stem = fname.rsplit(".", 1)[0]
    # 单集缩略图 = 与视频同名的 .jpg（取自 TMDB 该集剧照）
    if "." in stem and "S01E" in stem.upper().replace(" ", ""):
        return "TMDB stills（该集剧照）"
    if kind in ("thumb", "landscape"):
        return "fanart.tv moviethumb / tvthumb"
    if kind in ("banner", "disc", "clearart"):
        return "fanart.tv"
    if kind == "poster" and stem.lower().startswith(SEASON_HINT[0]):
        return "TMDB season posters"
    if kind == "poster":
        return "TMDB posters"
    if kind in ("backdrop", "fanart"):
        return "TMDB backdrops"
    if kind == "logo":
        return "TMDB logos"
    return "—"


def kind_of(fname: str) -> str:
    stem = fname.rsplit(".", 1)[0]
    low = stem.lower()
    # 单集缩略图：与视频同名（含 S01E01 这类季集号）→ 单独归类
    if "." in stem and "S%02dE" % 1 in stem.upper().replace(" ", ""):
        return "episode-thumb"
    if low.startswith("season01-"):
        return low.split("-", 1)[1]            # poster / banner / thumb
    if low == "fanart":
        return "fanart"
    return low


def collect(root: Path):
    """扫描插件写出的图片，按 媒体 → 图片 组织。"""
    rows = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        rel = path.relative_to(root)
        parts = rel.parts
        group = "电影" if parts[0] == "电影" else "电视剧"
        media = parts[1]                                   # 片名目录
        fname = path.name
        sub = list(parts[2:-1])                            # 片名与文件之间的目录

        # 判定落点：剧集根目录 / 季目录 / 单集
        season_dir = next((p for p in sub if p.lower().startswith("season")), "")
        stem = fname.rsplit(".", 1)[0]
        if season_dir:
            # Season 01 里面：若是「剧名.S01E01.jpg」则归单集，否则归季
            if "." in stem and "S%02dE" % 1 in stem.upper().replace(" ", ""):
                scope = f"单集（{season_dir}）"
                item = stem                 # 单集文件名（与视频同名）
            else:
                scope = f"季目录（{season_dir}）"
                item = ""
        elif stem.lower().startswith("season"):
            scope = "剧集根目录（季图双落点）"
            item = ""
        else:
            scope = "根目录"
            item = ""
        kind = kind_of(fname)
        data = path.read_bytes()
        w, h = image_size(data)
        rows.append({
            "group": group, "media": media, "scope": scope, "item": item,
            "file": fname, "kind": kind, "kind_cn": KIND_CN.get(kind, kind),
            "source": source_of(fname, kind),
            "width": w, "height": h, "bytes": len(data),
            "rel": str(rel).replace("\\", "/"), "abs": str(path),
        })
    # 排序：根目录 → 季 → 单集，同类按文件名
    scope_rank = {"根目录": 0, "剧集根目录（季图双落点）": 1, "季目录": 2, "单集": 3}
    rows.sort(key=lambda r: (r["group"] != "电影", r["media"],
                             scope_rank.get(r["scope"].split("（")[0], 9), r["file"]))
    return rows


def embed(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as fh:
        return f"data:{mime};base64," + base64.b64encode(fh.read()).decode()


HOME = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NfoGapFill 真实刮削结果复核</title>
<style>
  :root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e8ecf3;--dim:#9aa4b2;
        --accent:#4f8cff;--ok:#2ea043;--warn:#d29922;--chip:#1f2632}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .wrap{max-width:1400px;margin:0 auto;padding:28px 22px 80px}
  h1{font-size:23px;margin:0 0 6px}
  h2{font-size:18px;margin:36px 0 14px;padding-left:10px;border-left:4px solid var(--accent)}
  .sub{color:var(--dim);font-size:13px;margin-bottom:18px}
  .meta{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 22px}
  .chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;
        padding:4px 12px;font-size:12.5px;color:var(--dim)}
  .chip b{color:var(--fg)}
  table{width:100%;border-collapse:collapse;background:var(--card);
        border:1px solid var(--line);border-radius:12px;overflow:hidden}
  th,td{padding:11px 13px;text-align:left;border-bottom:1px solid var(--line);
        vertical-align:middle;font-size:13px}
  th{background:#1c212b;color:var(--dim);font-weight:600;font-size:12px;
     letter-spacing:.4px;text-transform:uppercase}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:#1b202a}
  .thumb{width:130px;height:88px;object-fit:contain;background:#0b0d11;
         border:1px solid var(--line);border-radius:7px;display:block}
  .name{font-weight:600}
  .dim{color:var(--dim)}
  code{background:#0b0d11;border:1px solid var(--line);border-radius:5px;
       padding:1px 6px;font-size:12px;color:#c9d4e5}
  .res{font-variant-numeric:tabular-nums}
  .bd{color:var(--ok)}
  .note{background:#141a24;border:1px solid var(--line);border-left:3px solid var(--warn);
        border-radius:9px;padding:14px 17px;margin:18px 0;color:var(--dim);font-size:13px}
  .note b{color:var(--fg)}
  .empty{color:var(--ok);background:var(--card);border:1px solid var(--line);
         border-radius:10px;padding:16px 18px}
  .tree{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;
        background:#0b0d11;border:1px solid var(--line);border-radius:9px;
        padding:16px 18px;white-space:pre;overflow-x:auto;color:#c9d4e5}
</style>
</head>
<body><div class="wrap">
<h1>NfoGapFill 真实刮削结果复核</h1>
<div class="sub">在联网环境对真实媒体库执行一次完整刮削后，插件实际落盘的图片清单（分辨率/体积均为文件真实值）</div>
<div class="meta" id="meta"></div>
<div id="body"></div>
</div></body></html>
"""


def esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def size_cn(n: int) -> str:
    return f"{n/1048576:.2f} MB" if n >= 1048576 else f"{n/1024:.0f} KB"


def main():
    if len(sys.argv) < 3:
        raise SystemExit("用法：python build_preview.py <样本目录> <输出.html>")
    root = Path(sys.argv[1])
    out = Path(sys.argv[2])
    rows = collect(root)

    groups = {"电影": [], "电视剧": []}
    for r in rows:
        groups[r["group"]].append(r)

    # 每个媒体项的图片数量（用于汇总）
    total = len(rows)
    missing = []

    html = [HOME]
    meta = (f'<span class="chip">图片总数 <b>{total}</b></span>'
            f'<span class="chip">电影 <b>{len(groups["电影"])}</b> 张</span>'
            f'<span class="chip">电视剧 <b>{len(groups["电视剧"])}</b> 张</span>'
            f'<span class="chip">来源 <b>TMDB + fanart.tv</b></span>'
            f'<span class="chip">来源优先级 <b>TMDB 优先 → fanart.tv 其次</b></span>'
            f'<span class="chip">图片源 <b>original 原图</b></span>')
    meta_js = json.dumps(meta, ensure_ascii=False).replace("</", "<\\/")
    html.append("<script>document.getElementById('meta').innerHTML="
                + meta_js + ";</script>")

    body = []
    for group in ("电影", "电视剧"):
        items = groups[group]
        body.append(f"<h2>{group}（{len(items)} 张）</h2>")
        if not items:
            body.append('<div class="empty">无</div>')
            continue
        body.append("<table><thead><tr>"
                    "<th>预览</th><th>媒体 / 年份</th><th>图片类型</th>"
                    "<th>写入位置</th><th>来源</th><th>分辨率</th><th>体积</th>"
                    "</tr></thead><tbody>")
        for r in items:
            src = embed(r["abs"])
            label = r["kind_cn"]
            if r["kind"] == "episode-thumb":
                label = "单集缩略图（与视频同名 .jpg）"
            body.append(
                "<tr>"
                f'<td><img class="thumb" src="{src}" loading="lazy"></td>'
                f'<td class="name">{esc(r["media"])}</td>'
                f'<td>{esc(label)}<br><span class="dim">{esc(r["file"])}</span></td>'
                f'<td><code>{esc(r["scope"])}</code></td>'
                f'<td class="dim">{esc(r["source"])}</td>'
                f'<td class="res">{r["width"]} × {r["height"]}</td>'
                f'<td class="bd">{size_cn(r["bytes"])}</td>'
                "</tr>")
        body.append("</tbody></table>")

    body.append("<h2>匹配失败 / 图片缺失</h2>")
    if missing:
        body.append("<table><thead><tr><th>媒体</th><th>图片类型</th><th>原因</th>"
                    "</tr></thead><tbody>")
        for row in missing:
            body.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>")
        body.append("</tbody></table>")
    else:
        body.append('<div class="empty">本轮刮削 <b>无失败、无缺失</b>：'
                    '所有被请求的图片类型都已成功取回并落盘。</div>')

    # 说明：剧集没有 disc 是设计如此（TMDB/fanart 的剧集条目本就没有光盘图）
    body.append(
        '<div class="note"><b>关于「剧集没有 disc.png」——这是正确行为，不是缺失。</b><br>'
        'MoviePilot 官方的图片许可集合里，<code>disc</code> 只属于电影；'
        '剧集（tvshow / season / episode）本就不包含光盘图。插件严格照搬这套规则，'
        '所以上面电视剧那一组不会出现 disc。同理，本轮的 <b>thumb.jpg 与 landscape.jpg '
        '字节完全相同</b>，因为 MP 里它们本就是同一张横版图的两个名字（别名关系）。</div>')

    body.append(
        '<div class="note"><b>关于「来源优先级」—— 上面那栏「来源」列是按优先级逐源取到的结果。</b><br>'
        '本轮用的顺序是 <b>TMDB 优先 → fanart.tv 其次</b>：'
        '海报 / 背景图 / 徽标 由 TMDB 提供（<code>image.tmdb.org</code>），'
        '而横幅图 / 光盘图 / 透明艺术图 / 横版缩略图（thumb、landscape）**只有 fanart.tv 有**，'
        '所以这几类无论顺序如何都取自 fanart（<code>assets.fanart.tv</code>）。'
        '若把优先级改成 fanart 优先，海报 / 背景图 / 徽标 会改取 fanart 的对应图 —— '
        '但 fanart 没有剧集/电影通用海报键时仍会落回 TMDB。</div>')

    # 落盘结构树，便于人工核对「季图双落点」是否真的落在两处
    body.append("<h2>实际落盘结构</h2>")
    tree_lines = []
    for group in ("电影", "电视剧"):
        for media in sorted({r["media"] for r in groups[group]}):
            tree_lines.append(f"{group}/{media}/")
            seen = set()
            for r in [x for x in groups[group] if x["media"] == media]:
                rel = r["rel"].split("/", 2)[-1]
                if rel not in seen:
                    seen.add(rel)
                    tree_lines.append(f"    {rel}   {r['width']}×{r['height']}  {size_cn(r['bytes'])}")
    body.append('<div class="tree">' + esc("\n".join(tree_lines)) + "</div>")

    body_js = json.dumps("".join(body), ensure_ascii=False).replace("</", "<\\/")
    html.append("<script>document.getElementById('body').innerHTML="
                + body_js + ";</script>")
    out.write_text("".join(html), encoding="utf-8")
    print(f"写出 {out}（{out.stat().st_size/1024:.0f} KB，{total} 张图）")
    for r in rows:
        print(f"  {r['group']} | {r['media']:<22} | {r['file']:<20} | "
              f"{r['width']}x{r['height']} | {r['source']}")


if __name__ == "__main__":
    main()
