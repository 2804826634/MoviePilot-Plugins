#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在**能联网**的机器上抓取 TMDB / fanart.tv 的真实 API 响应，供离线复核插件刮削结果。

用法（在能连网的机器上跑）：
    TMDB_API_KEY=你的key FANART_API_KEY=你的key python fetch_real_samples.py 输出目录

不传 fanart key 也能跑（跳过 fanart 那几个接口）。

产出：
    <输出目录>/cache.json        插件 FileProvider 用的 cache（键：movie:438631 等）
    <输出目录>/raw/*.json        原始 API 响应（人工核对用）
    <输出目录>/images/<名>.jpg   真实图片文件（已下载，供预览）
    <输出目录>/manifest.json     每张图的来源 / URL / 真实分辨率 / 字节数

把整个输出目录打包发回即可。
"""
import json
import os
import struct
import sys
import urllib.request

MOVIE_ID = "438631"      # 沙丘 (2021)
TV_ID = "66732"          # 怪奇物语
SEASON = "1"
EPISODE = "1"
LANG = "zh-CN"
# 注意：某些网络环境会封 api.themoviedb.org（返回 502/000），
# 而 api.tmdb.org 是同一服务的等价域名、常可直连 —— 默认用它。
TMDB = os.environ.get("TMDB_BASE", "https://api.tmdb.org/3")
UA = {"User-Agent": "nfg-sample/1.0"}


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 401:
            raise SystemExit(
                f"\n[TMDB/fanart 拒绝了请求：401]\n{body}\n\n"
                "这通常表示 API Key 无效。请到 https://www.themoviedb.org/settings/api\n"
                "核对「API Key (v3 auth)」是否为最新值（32 位十六进制）。\n"
                f"（当前请求域名：{url.split('/3/')[0]}，如被网络封锁可设 TMDB_BASE 换域名）")
        raise SystemExit(f"\n[请求失败 {exc.code}] {url}\n{body}")


def get_bytes(url: str):
    """下载图片。某些网络环境封 image.tmdb.org，但官方 CDN 源可用，故按序回退。"""
    candidates = [url]
    for bad, good in (("https://image.tmdb.org", "https://tmdb-image-prod.b-cdn.net"),
                      ("http://image.tmdb.org", "https://tmdb-image-prod.b-cdn.net")):
        if url.startswith(bad):
            candidates.append(good + url[len(bad):])
    last = None
    for u in candidates:
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:
            last = exc
    raise last if last else RuntimeError("no url")


def png_size(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    return None


def jpeg_size(data: bytes):
    """扫 JPEG 的 SOFn 段拿宽高。"""
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
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
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X":
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return w, h
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


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("  ->", path, os.path.getsize(path), "bytes")


def pick(entries, want_lang):
    """和插件同款：只按语言优先级，同级取第一条。"""
    best, best_rank = None, 99
    for item in entries or []:
        if not item.get("file_path"):
            continue
        code = (item.get("iso_639_1") or "").lower()
        rank = 0 if code == want_lang else (1 if not code else (2 if code == "en" else 3))
        if rank < best_rank:
            best, best_rank = item, rank
        if best_rank == 0:
            break
    return best


def fanart_pick(entries):
    """和插件同款：先语言偏好（zh,en），再点赞数。"""
    if not entries:
        return None
    order = ["zh", "en"]

    def rank(it):
        lg = str(it.get("lang") or "").lower()
        try:
            pos = order.index(lg)
        except ValueError:
            pos = len(order)
        try:
            likes = int(it.get("likes") or 0)
        except (TypeError, ValueError):
            likes = 0
        return (pos, -likes)

    return min(entries, key=rank)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法：TMDB_API_KEY=xxx python fetch_real_samples.py <输出目录>")
    out = sys.argv[1]
    tmdb_key = os.environ.get("TMDB_API_KEY", "").strip()
    fanart_key = os.environ.get("FANART_API_KEY", "").strip()
    if not tmdb_key:
        raise SystemExit("缺少环境变量 TMDB_API_KEY")
    raw = os.path.join(out, "raw")
    imgdir = os.path.join(out, "images")
    os.makedirs(imgdir, exist_ok=True)

    print("[1/5] TMDB 主记录")
    movie = get_json(f"{TMDB}/movie/{MOVIE_ID}?api_key={tmdb_key}&language={LANG}")
    tv = get_json(f"{TMDB}/tv/{TV_ID}?api_key={tmdb_key}&language={LANG}")
    season = get_json(f"{TMDB}/tv/{TV_ID}/season/{SEASON}?api_key={tmdb_key}&language={LANG}")
    ext = get_json(f"{TMDB}/tv/{TV_ID}/external_ids?api_key={tmdb_key}")
    save_json(os.path.join(raw, "movie.json"), movie)
    save_json(os.path.join(raw, "tv.json"), tv)
    save_json(os.path.join(raw, "season.json"), season)
    save_json(os.path.join(raw, "external_ids.json"), ext)

    print("[2/5] TMDB images 接口")
    inc = "zh,en,null"
    m_img = get_json(f"{TMDB}/movie/{MOVIE_ID}/images?api_key={tmdb_key}&include_image_language={inc}")
    t_img = get_json(f"{TMDB}/tv/{TV_ID}/images?api_key={tmdb_key}&include_image_language={inc}")
    s_img = get_json(f"{TMDB}/tv/{TV_ID}/season/{SEASON}/images?api_key={tmdb_key}&include_image_language={inc}")
    e_img = get_json(f"{TMDB}/tv/{TV_ID}/season/{SEASON}/episode/{EPISODE}/images?api_key={tmdb_key}&include_image_language={inc}")
    save_json(os.path.join(raw, "movie_images.json"), m_img)
    save_json(os.path.join(raw, "tv_images.json"), t_img)
    save_json(os.path.join(raw, "season_images.json"), s_img)
    save_json(os.path.join(raw, "episode_images.json"), e_img)

    print("[3/5] fanart.tv")
    fanart_tv = fanart_movie = None
    if fanart_key:
        tvdb_id = str(ext.get("tvdb_id") or "").strip()
        if tvdb_id:
            fanart_tv = get_json(f"https://webservice.fanart.tv/v3/tv/{tvdb_id}?api_key={fanart_key}")
            save_json(os.path.join(raw, "fanart_tv.json"), fanart_tv)
        fanart_movie = get_json(f"https://webservice.fanart.tv/v3/movies/{MOVIE_ID}?api_key={fanart_key}")
        save_json(os.path.join(raw, "fanart_movie.json"), fanart_movie)
    else:
        print("  （未提供 FANART_API_KEY，跳过 fanart）")

    print("[4/5] 按插件算法选图 + 组装 cache")
    host = "https://image.tmdb.org/t/p/original"
    mt = "zh"

    def tmdb_url(entries):
        best = pick(entries, mt)
        return (host + best["file_path"]) if best else ""

    def fanart_url(data, *keys):
        for k in keys:
            best = fanart_pick((data or {}).get(k))
            if best and best.get("url"):
                return best["url"], k
        return "", ""

    # 每项：(分组, 媒体名, 年份, 类型, 来源, URL)
    plan = []

    def add(group, title, year, kind, source, url, note=""):
        if url:
            plan.append((group, title, year, kind, source, url, note))

    mname = movie.get("title") or "沙丘"
    myear = (movie.get("release_date") or "")[:4]
    add("电影", mname, myear, "poster", "TMDB posters", tmdb_url(m_img.get("posters")))
    add("电影", mname, myear, "backdrop", "TMDB backdrops", tmdb_url(m_img.get("backdrops")))
    add("电影", mname, myear, "logo", "TMDB logos", tmdb_url(m_img.get("logos")))
    if fanart_movie:
        for kind, keys in (("thumb", ("moviethumb",)), ("landscape", ("moviethumb",)),
                           ("banner", ("moviebanner",)), ("disc", ("moviedisc",)),
                           ("clearart", ("hdmovieclearart", "movieart"))):
            u, k = fanart_url(fanart_movie, *keys)
            add("电影", mname, myear, kind, f"fanart {k}", u)

    tname = tv.get("name") or "怪奇物语"
    tyear = (tv.get("first_air_date") or "")[:4]
    add("电视剧", tname, tyear, "poster", "TMDB posters", tmdb_url(t_img.get("posters")))
    add("电视剧", tname, tyear, "backdrop", "TMDB backdrops", tmdb_url(t_img.get("backdrops")))
    add("电视剧", tname, tyear, "logo", "TMDB logos", tmdb_url(t_img.get("logos")))
    if fanart_tv:
        for kind, keys in (("thumb", ("tvthumb",)), ("landscape", ("tvthumb",)),
                           ("banner", ("tvbanner",)), ("clearart", ("hdclearart",))):
            u, k = fanart_url(fanart_tv, *keys)
            add("电视剧", tname, tyear, kind, f"fanart {k}", u)
    add("电视剧", f"{tname} 第{SEASON}季", (season.get("air_date") or "")[:4],
        "season-poster", "TMDB season posters", tmdb_url(s_img.get("posters")))
    if fanart_tv:
        for kind, keys in (("season-banner", ("seasonbanner",)), ("season-thumb", ("seasonthumb",))):
            entries = [it for it in (fanart_tv.get(keys[0]) or [])
                       if str(it.get("season", "")).strip() in (SEASON, str(int(SEASON)))]
            best = fanart_pick(entries)
            add("电视剧", f"{tname} 第{SEASON}季", "", kind, f"fanart {keys[0]}",
                best.get("url") if best else "")
    add("电视剧", f"{tname} S{int(SEASON):02d}E{int(EPISODE):02d}", "",
        "episode-thumb", "TMDB stills", tmdb_url(e_img.get("stills")))

    print("[5/5] 下载图片 + 解析真实分辨率")
    manifest = []
    for idx, (group, title, year, kind, source, url, note) in enumerate(plan, 1):
        ext_part = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        fname = f"{idx:02d}_{kind}{ext_part}"
        entry = {"group": group, "title": title, "year": year, "kind": kind,
                 "source": source, "url": url, "file": fname, "bytes": 0,
                 "width": 0, "height": 0, "ok": False}
        try:
            data = get_bytes(url)
            with open(os.path.join(imgdir, fname), "wb") as fh:
                fh.write(data)
            w, h = image_size(data)
            entry.update(bytes=len(data), width=w, height=h, ok=True)
            print(f"  {fname:28s} {w}x{h}  {len(data)} bytes")
        except Exception as exc:
            entry["error"] = str(exc)[:120]
            print(f"  {fname:28s} 下载失败：{str(exc)[:80]}")
        manifest.append(entry)

    save_json(os.path.join(out, "manifest.json"), manifest)

    # 完整选图计划（含被跳过的项/缺失项）—— 供离线复核「哪些图没取到、为什么」
    save_json(os.path.join(out, "plan.json"), [
        {"group": g, "title": t, "year": y, "kind": k, "source": s,
         "url": u, "note": n} for (g, t, y, k, s, u, n) in plan])

    # 插件 FileProvider 的 cache（图片网址，供离线再跑一次插件）
    cache = {
        f"movie:{MOVIE_ID}": {
            "poster": [tmdb_url(m_img.get("posters"))],
            "backdrop": [tmdb_url(m_img.get("backdrops"))],
            "logo": [tmdb_url(m_img.get("logos"))],
        },
        f"tv:{TV_ID}": {
            "poster": [tmdb_url(t_img.get("posters"))],
            "backdrop": [tmdb_url(t_img.get("backdrops"))],
            "logo": [tmdb_url(t_img.get("logos"))],
        },
        f"season:{TV_ID}:{SEASON}": {"poster": [tmdb_url(s_img.get("posters"))]},
        f"episode:{TV_ID}:{SEASON}:{EPISODE}": {"thumb": [tmdb_url(e_img.get("stills"))]},
    }
    save_json(os.path.join(out, "cache.json"), cache)

    ok = sum(1 for m in manifest if m["ok"])
    print(f"\n完成：{ok}/{len(manifest)} 张图已下载。")
    print("把整个输出目录打包发回：", os.path.abspath(out))


if __name__ == "__main__":
    main()
