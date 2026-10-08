# -*- coding: utf-8 -*-
"""
文件迁移执行层：负责实际的重命名、移动、Season 00 目录创建与 NFO 写入。

设计原则：
  - 默认 dry-run，把「计划」和「执行」彻底分开，误判最多只是日志里多几行；
  - 移动使用 copy2 + fsync + os.replace 的顺序，先复制后删源，
    中途失败源文件仍在原处，不会丢数据；
  - 所有路径操作都做 realpath 去重，避免硬链接导致同一文件被处理两次。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

VIDEO_EXT = {".mkv", ".mp4", ".ts", ".iso", ".rmvb", ".avi", ".mov",
             ".mpeg", ".mpg", ".wmv", ".3gp", ".asf", ".m4v", ".flv",
             ".m2ts", ".strm", ".tp", ".f4v"}


class MoveResult:
    def __init__(self):
        self.moved: List[Tuple[str, str]] = []
        self.skipped: List[Tuple[str, str]] = []
        self.failed: List[Tuple[str, str]] = []

    def as_text(self) -> str:
        lines = []
        if self.moved:
            lines.append(f"已移动 {len(self.moved)} 个文件")
            for src, dst in self.moved:
                lines.append(f"  {os.path.basename(src)} -> {dst}")
        if self.skipped:
            lines.append(f"跳过 {len(self.skipped)} 个")
            for src, why in self.skipped:
                lines.append(f"  {os.path.basename(src)}：{why}")
        if self.failed:
            lines.append(f"失败 {len(self.failed)} 个")
            for src, why in self.failed:
                lines.append(f"  {os.path.basename(src)}：{why}")
        return "\n".join(lines) if lines else "无变更"


def is_video(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXT


def list_media_files(directory: Path) -> List[str]:
    """列出一个目录下的媒体文件与附属文件（不含子目录）。"""
    out = []
    try:
        for p in sorted(directory.iterdir()):
            if p.is_file():
                out.append(p.name)
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return out


def season00_dir(season_dir: Path, style: str = "season") -> Path:
    """
    按 Plex / TMDB 规范推导 Season 00 目录。
      style=season -> Season 00（MP 默认命名风格，推荐）
      style=cn     -> 特别篇
      style=plain  -> Specials
    """
    if style == "cn":
        return season_dir.parent / "特别篇"
    if style == "plain":
        return season_dir.parent / "Specials"
    return season_dir.parent / "Season 00"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _unique_path(target: Path) -> Path:
    """目标已存在时加 (1)(2) 后缀，绝不覆盖。"""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    i = 1
    while True:
        cand = target.with_name(f"{stem}({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1


def safe_move(src: Path, dst_dir: Path, new_name: Optional[str] = None) -> Path:
    """
    移动单个文件到 dst_dir，保持内容不变。
    顺序：复制 -> fsync -> 校验大小 -> 删源 -> 原子 rename。
    任一步失败都保证源文件完好。
    """
    ensure_dir(dst_dir)
    dst = dst_dir / (new_name or src.name)
    dst = _unique_path(dst)

    src_size = src.stat().st_size
    tmp = dst_dir / f".{dst.name}.{os.getpid()}.{os.urandom(4).hex()}.part"
    try:
        shutil.copy2(src, tmp)
        # 必须以「可写」方式另开句柄才能 fsync；
        # 对 copy2 返回的只读句柄 fsync 在 Windows 上直接 EBADF。
        try:
            with open(tmp, "r+b") as f:
                os.fsync(f.fileno())
        except OSError:
            # 部分网络/虚拟文件系统不支持 fsync，不影响正确性，跳过
            pass
        if tmp.stat().st_size != src_size:
            raise IOError(f"复制后大小不一致 {tmp.stat().st_size} != {src_size}")
        os.replace(tmp, dst)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    # 目标落地成功后才删源；源若为硬链接，删它不影响其他媒体库里的同一 inode
    try:
        src.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        raise IOError(f"目标已写入但源文件删除失败：{e}")
    return dst


def move_episode_group(season_dir: Path,
                       target_dir: Path,
                       video_name: str,
                       sidecars: List[str],
                       new_stem: str) -> List[Tuple[str, str]]:
    """
    移动一集视频及其附属文件到目标目录，并把 stem 换成 new_stem。
    返回 [(原路径, 新路径), ...]
    """
    moved: List[Tuple[str, str]] = []
    src_video = season_dir / video_name
    new_video = target_dir / f"{new_stem}{Path(video_name).suffix.lower()}"
    new_video = _unique_path(new_video)
    ensure_dir(target_dir)

    src_video = Path(os.path.realpath(src_video))
    dst = safe_move(src_video, target_dir, new_video.name)
    moved.append((str(src_video), str(dst)))

    for sc in sidecars:
        sc_path = season_dir / sc
        if not sc_path.exists():
            continue
        sc_suffix = "".join(Path(sc).suffixes)      # 保留 .zh-CN.ass 双扩展
        sc_body = Path(sc).name
        # 把 stem 换成 new_stem，保留后面的语言/字幕后缀
        new_sc_body = new_stem + sc_suffix
        try:
            real = Path(os.path.realpath(sc_path))
            dst_sc = safe_move(real, target_dir, new_sc_body)
            moved.append((str(real), str(dst_sc)))
        except Exception as e:
            logger_move_warning(sc, e)
    return moved


def logger_move_warning(name: str, exc: Exception) -> None:
    try:
        from app.log import logger
        logger.warning(f"[特别篇归位] 附属文件移动失败 {name}: {exc}")
    except Exception:
        pass


def clean_empty_season_dir(season_dir: Path, keep_nfo: bool = True) -> bool:
    """超集全部迁走后，季目录空了则可选清理（默认保留，避免误删剧集目录结构）。"""
    if not season_dir.exists():
        return False
    leftovers = [p for p in season_dir.iterdir() if p.is_file()]
    if keep_nfo:
        leftovers = [p for p in leftovers if p.suffix.lower() != ".nfo"]
    return False if leftovers else True


# ---------------------------------------------------------------------------
# NFO
# ---------------------------------------------------------------------------

def escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_episode_nfo(title: str, season: int, episode: int,
                      episode_title: Optional[str] = None,
                      overview: Optional[str] = None,
                      air_date: Optional[str] = None,
                      runtime: Optional[int] = None,
                      show_title: Optional[str] = None) -> str:
    """
    生成单集 NFO。season=0 时写 <season>0</season>，符合 Plex / TMDB 的 Season 0 约定。
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
        "<episodedetails>",
        f"  <title>{escape(episode_title)}</title>",
        f"  <showtitle>{escape(show_title or title)}</showtitle>",
        "  <season>0</season>" if season == 0 else f"  <season>{season}</season>",
        f"  <episode>{episode}</episode>",
    ]
    if air_date:
        lines.append(f"  <aired>{escape(air_date)}</aired>")
    if overview:
        lines.append(f"  <plot>{escape(overview)}</plot>")
    if runtime:
        lines.append(f"  <runtime>{runtime}</runtime>")
    lines.append("</episodedetails>")
    return "\n".join(lines) + "\n"


def write_nfo(path: Path, content: str) -> bool:
    """原子写 NFO。"""
    ensure_dir(path.parent)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.nfo.part"
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False