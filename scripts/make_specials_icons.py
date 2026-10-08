# -*- coding: utf-8 -*-
"""
生成两个特别篇插件的图标（512x512 RGBA PNG，无第三方依赖）。

风格沿用本仓库既有的 nfogapfill.png：蓝色->青色对角渐变的圆角方块 + 纯白符号。
之所以本地手绘而不走 AI 生图：图标是几何色块，本地绘制结果确定、可复现、
不消耗积分，且能保证两个插件与既有图标风格严格一致。

运行： python scripts/make_specials_icons.py
输出： icons/specialsfixer.png、icons/specialsrelocate.png
"""
import math
import struct
import zlib
from pathlib import Path

SIZE = 512
RADIUS = 96          # 圆角半径（对齐 nfogapfill 的观感）
SS = 4               # 超采样倍数（抗锯齿）

# 与 nfogapfill.png 同色系：左上 #3B6FE0 -> 右下 #17B4C8
C_TOP = (0x3B, 0x6F, 0xE0)
C_BOTTOM = (0x17, 0xB4, 0xC8)

HERE = Path(__file__).parent
OUT_DIR = HERE.parent / "icons"


# ---------------------------------------------------------------------------
# 极简绘图层：先在 SS 倍分辨率上算，再做盒式降采样得到抗锯齿
# ---------------------------------------------------------------------------
class Canvas:
    def __init__(self, size):
        self.n = size
        # RGBA，初始全透明
        self.px = [[0, 0, 0, 0] for _ in range(size * size)]

    def _idx(self, x, y):
        return y * self.n + x

    def set(self, x, y, rgba):
        self.px[self._idx(x, y)] = list(rgba)

    def fill_gradient_rounded(self, c0, c1, radius):
        """整幅画布铺对角线性渐变，并按圆角矩形裁剪（外部保持全透明）。"""
        n = self.n
        for y in range(n):
            # 归一化对角坐标 0..1
            ty = y / (n - 1)
            for x in range(n):
                tx = x / (n - 1)
                t = (tx + ty) / 2.0
                r = round(c0[0] + (c1[0] - c0[0]) * t)
                g = round(c0[1] + (c1[1] - c0[1]) * t)
                b = round(c0[2] + (c1[2] - c0[2]) * t)
                if _in_rounded(x, y, n, radius):
                    self.set(x, y, (r, g, b, 255))

    def downsample(self, factor):
        """盒式降采样：factor x factor -> 1 像素，alpha 按覆盖率折算。"""
        n = self.n // factor
        out = Canvas(n)
        f2 = factor * factor
        for y in range(n):
            for x in range(n):
                r = g = b = a = 0
                for dy in range(factor):
                    row = (y * factor + dy) * self.n
                    for dx in range(factor):
                        pr, pg, pb, pa = self.px[row + x * factor + dx]
                        # 预乘后再平均，避免边缘出现黑边
                        r += pr * pa
                        g += pg * pa
                        b += pb * pa
                        a += pa
                if a == 0:
                    out.set(x, y, (0, 0, 0, 0))
                    continue
                out.set(x, y, (round(r / a), round(g / a), round(b / a), round(a / f2)))
        return out

    def stroke_polyline(self, pts, width, color=(255, 255, 255, 255), caps=True):
        """按线段绘制带圆角端点的粗线（用于对勾、箭头等）。"""
        half = width / 2.0
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            self._seg(x1, y1, x2, y2, half, color, caps)

    def _seg(self, x1, y1, x2, y2, half, color, caps):
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
        lo_x = max(0, int(min(x1, x2) - half - 2))
        hi_x = min(self.n - 1, int(max(x1, x2) + half + 2))
        lo_y = max(0, int(min(y1, y2) - half - 2))
        hi_y = min(self.n - 1, int(max(y1, y2) + half + 2))
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        for y in range(lo_y, hi_y + 1):
            for x in range(lo_x, hi_x + 1):
                px, py = x + 0.5, y + 0.5
                if seg_len2 == 0:
                    d = math.hypot(px - x1, py - y1)
                else:
                    t = ((px - x1) * dx + (py - y1) * dy) / seg_len2
                    t = max(0.0, min(1.0, t))
                    d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
                if d <= half:
                    self.set(x, y, color)

    def stroke_rect(self, x0, y0, x1, y1, width, color=(255, 255, 255, 255), radius=0):
        """矩形描边（四边独立画，保证圆角处不被裁掉）。"""
        for a, b in [((x0 + radius, y0), (x1 - radius, y0)),
                     ((x0 + radius, y1), (x1 - radius, y1)),
                     ((x0, y0 + radius), (x0, y1 - radius)),
                     ((x1, y0 + radius), (x1, y1 - radius))]:
            self.stroke_polyline([a, b], width, color, caps=False)

    def fill_circle(self, cx, cy, r, color=(255, 255, 255, 255)):
        for y in range(max(0, int(cy - r - 2)), min(self.n - 1, int(cy + r + 2)) + 1):
            for x in range(max(0, int(cx - r - 2)), min(self.n - 1, int(cx + r + 2)) + 1):
                if math.hypot(x + 0.5 - cx, y + 0.5 - cy) <= r:
                    self.set(x, y, color)

    def save(self, path):
        write_png(path, self.n, self.n, self.px)


def _in_rounded(x, y, n, radius):
    """点是否落在圆角矩形内（圆角为四分之一圆弧）。"""
    r = radius
    cx = min(max(x, r), n - 1 - r)
    cy = min(max(y, r), n - 1 - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


def write_png(path, w, h, pixels):
    """写 8bit RGBA PNG（color type 6）。"""
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0 (None)
        row = pixels[y * w:(y + 1) * w]
        for p in row:
            raw += bytes((p[0] & 255, p[1] & 255, p[2] & 255, p[3] & 255))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    Path(path).write_bytes(png)


# ---------------------------------------------------------------------------
# 两个图标的具体画法（坐标按 SS 放大前的设计尺寸给出）
# ---------------------------------------------------------------------------
def draw_specialsfixer():
    """整理记录季集修正：文档 + 铅笔（表示「改这条记录的季/集」）。"""
    c = Canvas(SIZE * SS)
    c.fill_gradient_rounded(C_TOP, C_BOTTOM, RADIUS * SS)

    def s(v):
        return v * SS

    white = (255, 255, 255, 255)
    W = 34 * SS  # 线宽

    # 左侧文档：圆角矩形描边 + 两条文本行 + 右上角折角
    doc_x0, doc_y0, doc_x1, doc_y1 = s(150), s(120), s(316), s(392)
    c.stroke_rect(doc_x0, doc_y0, doc_x1, doc_y1, W, white, radius=18 * SS)
    # 折角：从右上角斜切
    c.stroke_polyline([(s(262), doc_y0), (s(316), doc_y0 + s(54))], W, white, caps=False)
    # 文本行（短的在上、长的在下，模拟记录条目）
    c.stroke_polyline([(s(186), s(224)), (s(280), s(224))], W * 0.62, white, caps=True)
    c.stroke_polyline([(s(186), s(282)), (s(280), s(282))], W * 0.62, white, caps=True)
    c.stroke_polyline([(s(186), s(340)), (s(246), s(340))], W * 0.62, white, caps=True)

    # 右下角铅笔：斜向主体 + 笔尖三角
    c.stroke_polyline([(s(300), s(300)), (s(392), s(208))], W * 1.05, white, caps=True)
    # 笔尖（两条短线交于一点）
    c.stroke_polyline([(s(300), s(300)), (s(268), s(324))], W * 0.8, white, caps=True)
    c.stroke_polyline([(s(300), s(300)), (s(324), s(272))], W * 0.8, white, caps=True)

    return c.downsample(SS)


def draw_specialsrelocate():
    """特别篇归位：Season 01 目录 → 箭头 → Season 00 目录。"""
    c = Canvas(SIZE * SS)
    c.fill_gradient_rounded(C_TOP, C_BOTTOM, RADIUS * SS)

    def s(v):
        return v * SS

    white = (255, 255, 255, 255)
    W = 30 * SS

    # 上层目录：Season 01（实线框）
    top_y0, top_y1 = s(122), s(226)
    c.stroke_rect(s(140), top_y0, s(372), top_y1, W, white, radius=16 * SS)
    # 目录内的「集号条」：三条短横
    for i, yy in enumerate((s(152), s(174), s(196))):
        c.stroke_polyline([(s(176), yy), (s(336 - i * 18), yy)], W * 0.5, white, caps=True)

    # 中间向下箭头：竖干 + 两个斜羽
    c.stroke_polyline([(s(256), s(250)), (s(256), s(322))], W, white, caps=True)
    c.stroke_polyline([(s(214), s(288)), (s(256), s(330))], W * 0.9, white, caps=True)
    c.stroke_polyline([(s(298), s(288)), (s(256), s(330))], W * 0.9, white, caps=True)

    # 下层目录：Season 00（双线框，强调「归位目标」）
    bot_y0, bot_y1 = s(344), s(430)
    c.stroke_rect(s(140), bot_y0, s(372), bot_y1, W, white, radius=16 * SS)
    c.stroke_polyline([(s(176), s(387)), (s(336), s(387))], W * 0.62, white, caps=True)

    return c.downsample(SS)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, fn in (("specialsfixer", draw_specialsfixer),
                     ("specialsrelocate", draw_specialsrelocate)):
        canvas = fn()
        path = OUT_DIR / ("%s.png" % name)
        canvas.save(path)
        print("written %s (%d bytes)" % (path, path.stat().st_size))


if __name__ == "__main__":
    main()