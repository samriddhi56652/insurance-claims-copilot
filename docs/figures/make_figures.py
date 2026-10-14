"""Draw the three project figures (SVG + PNG) from one description.

    python docs/figures/make_figures.py

Figure 1  the traceability chain behind every draft
Figure 2  end-to-end claim workflow (the five lifecycle stages)
Figure 4  layered architecture, with the cross-cutting safeguards

The numbering (1, 2, 4) follows the report these were drawn for.
Needs only Pillow. Fonts are the Windows system Arial / Times New Roman; on
another machine change FONT_DIR. The same drawing calls write the SVG and the PNG,
so the two never drift apart.
"""

from __future__ import annotations

import math
import pathlib
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
FONT_DIR = pathlib.Path("C:/Windows/Fonts")
FONTS = {  # (bold, italic, serif) -> file
    (False, False, False): "arial.ttf",
    (True, False, False): "arialbd.ttf",
    (False, True, False): "ariali.ttf",
    (True, False, True): "timesbd.ttf",
}
SVG_FAMILY = {False: "Arial, Helvetica, sans-serif", True: "'Times New Roman', Times, serif"}
SEGOE = {(False, False): "segoeui.ttf", (True, False): "segoeuib.ttf", (False, True): "segoeuii.ttf",
         (True, True): "segoeuib.ttf"}
SEGOE_SVG = "'Segoe UI', -apple-system, 'Helvetica Neue', Arial, sans-serif"

NAVY = "#1E3A5F"
BOX_LINE = "#243B5E"
PANEL_FILL = "#EEF2F8"
PANEL_LINE = "#A9B8CE"
SHADE = "#E2EAF7"
ARROW = "#3A3F4B"
GREY = "#5A6475"
WHITE = "#FFFFFF"
SAFE_ITEM = "#2B4C78"

SS = 4  # supersampling for the PNG; the file is written at 2x the drawing units
OUT_SCALE = 2


class Canvas:
    """Records shapes once; renders them to SVG text and to a PIL image."""

    def __init__(self, w: int, h: int, face: str = "arial"):
        self.w, self.h = w, h
        self.face = face
        self.ops: list[tuple] = []

    # -- recording ---------------------------------------------------------
    def rect(self, x, y, w, h, fill=WHITE, line=BOX_LINE, lw=1.6, r=7, dash=False):
        self.ops.append(("rect", x, y, w, h, fill, line, lw, r, dash))

    def text(self, x, y, s, size=15, bold=False, italic=False, color=NAVY,
             anchor="middle", serif=False):
        self.ops.append(("text", x, y, s, size, bold, italic, color, anchor, serif))

    def lines(self, cx, cy, lines, size=15, lh=1.28, **kw):
        """Vertically centre a block of text lines on cy."""
        step = size * lh
        top = cy - (len(lines) - 1) * step / 2 + size * 0.35
        for i, s in enumerate(lines):
            self.text(cx, top + i * step, s, size=size, **kw)

    def path(self, pts, color=ARROW, lw=1.8, head=True, tail=False, dash=False):
        self.ops.append(("path", pts, color, lw, head, tail, dash))

    # -- svg -----------------------------------------------------------------
    def svg(self) -> str:
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
             f'viewBox="0 0 {self.w} {self.h}">',
             f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>']
        for op in self.ops:
            if op[0] == "rect":
                _, x, y, w, h, fill, line, lw, r, dash = op
                d = ' stroke-dasharray="6 5"' if dash else ""
                o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
                         f'fill="{fill}" stroke="{line}" stroke-width="{lw}"{d}/>')
            elif op[0] == "text":
                _, x, y, s, size, bold, italic, color, anchor, serif = op
                a = {"middle": "middle", "left": "start", "right": "end"}[anchor]
                o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SEGOE_SVG if (self.face == 'segoe' and not serif) else SVG_FAMILY[serif]}" '
                         f'font-size="{size}" font-weight="{700 if bold else 400}" '
                         f'font-style="{"italic" if italic else "normal"}" fill="{color}" '
                         f'text-anchor="{a}">{escape(s)}</text>')
            else:
                _, pts, color, lw, head, tail, dash = op
                body = list(pts)
                heads = []
                if head:
                    body[-1], tri = _shorten(pts[-2], pts[-1], 9)
                    heads.append(tri)
                if tail:
                    body[0], tri = _shorten(pts[1], pts[0], 9)
                    heads.append(tri)
                d = ' stroke-dasharray="6 5"' if dash else ""
                pstr = " ".join(f"{px:.1f},{py:.1f}" for px, py in body)
                o.append(f'<polyline points="{pstr}" fill="none" stroke="{color}" '
                         f'stroke-width="{lw}" stroke-linejoin="round"{d}/>')
                for tri in heads:
                    tstr = " ".join(f"{px:.1f},{py:.1f}" for px, py in tri)
                    o.append(f'<polygon points="{tstr}" fill="{color}"/>')
        o.append("</svg>")
        return "\n".join(o)

    # -- png -----------------------------------------------------------------
    def png(self) -> Image.Image:
        k = SS * OUT_SCALE
        img = Image.new("RGB", (self.w * k, self.h * k), WHITE)
        d = ImageDraw.Draw(img)

        def font(size, bold, italic, serif):
            if self.face == "segoe" and not serif:
                return ImageFont.truetype(str(FONT_DIR / SEGOE[(bold, italic)]), int(round(size * k)))
            key = (bold, italic, serif)
            if key not in FONTS:
                key = (bold, False, serif) if (bold, False, serif) in FONTS else (False, False, False)
            return ImageFont.truetype(str(FONT_DIR / FONTS[key]), int(round(size * k)))

        for op in self.ops:
            if op[0] == "rect":
                _, x, y, w, h, fill, line, lw, r, dash = op
                box = [x * k, y * k, (x + w) * k, (y + h) * k]
                if dash:
                    d.rounded_rectangle(box, radius=r * k, fill=fill)
                    _dashed_rect(d, box, line, lw * k, 6 * k, 5 * k)
                else:
                    d.rounded_rectangle(box, radius=r * k, fill=fill, outline=line,
                                        width=max(1, int(round(lw * k))))
            elif op[0] == "text":
                _, x, y, s, size, bold, italic, color, anchor, serif = op
                an = {"middle": "ms", "left": "ls", "right": "rs"}[anchor]
                d.text((x * k, y * k), s, font=font(size, bold, italic, serif), fill=color, anchor=an)
            else:
                _, pts, color, lw, head, tail, dash = op
                body = list(pts)
                heads = []
                if head:
                    body[-1], tri = _shorten(pts[-2], pts[-1], 9)
                    heads.append(tri)
                if tail:
                    body[0], tri = _shorten(pts[1], pts[0], 9)
                    heads.append(tri)
                kp = [(px * k, py * k) for px, py in body]
                for a, b in zip(kp, kp[1:]):
                    if dash:
                        _dashed_line(d, a, b, color, lw * k, 6 * k, 5 * k)
                    else:
                        d.line([a, b], fill=color, width=max(1, int(round(lw * k))))
                for tri in heads:
                    d.polygon([(px * k, py * k) for px, py in tri], fill=color)
        return img.resize((self.w * OUT_SCALE, self.h * OUT_SCALE), Image.LANCZOS)

    def save(self, stem: str) -> None:
        (HERE / f"{stem}.svg").write_text(self.svg(), encoding="utf-8")
        self.png().save(HERE / f"{stem}.png", optimize=True)


def _shorten(frm, to, size):
    """Pull the line end back by the arrowhead length; return (new_end, triangle)."""
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    base = (to[0] - ux * size, to[1] - uy * size)
    px, py = -uy, ux
    hw = size * 0.42
    tri = [to, (base[0] + px * hw, base[1] + py * hw), (base[0] - px * hw, base[1] - py * hw)]
    return base, tri


def _dashed_line(d, a, b, color, width, on, off):
    n = math.hypot(b[0] - a[0], b[1] - a[1])
    if n == 0:
        return
    ux, uy = (b[0] - a[0]) / n, (b[1] - a[1]) / n
    pos = 0.0
    while pos < n:
        end = min(pos + on, n)
        d.line([(a[0] + ux * pos, a[1] + uy * pos), (a[0] + ux * end, a[1] + uy * end)],
               fill=color, width=max(1, int(round(width))))
        pos += on + off


def _dashed_rect(d, box, color, width, on, off):
    x0, y0, x1, y1 = box
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        _dashed_line(d, a, b, color, width, on, off)


def caption(c: Canvas, text: str, y: int) -> None:
    c.text(c.w / 2, y, text, size=17, bold=True, serif=True, color="#111111")


# =============================================================================
# Figure 1 - traceability chain
# =============================================================================
def figure1() -> Canvas:
    c = Canvas(1330, 262)
    bw, bh, gap, pad = 118, 64, 34, 18
    groups = [
        ("What the claim says", ["Claim report", "Claim type and facts", "Document requirement"]),
        ("How the policy responds", ["Policy clause", "Coverage rule", "Evidence"]),
        ("What needs attention", ["Flag or open item", "Adjuster decision"]),
    ]
    x, top, ph = 30, 26, 158
    prev_right = None
    for title, items in groups:
        pw = len(items) * bw + (len(items) - 1) * gap + 2 * pad
        c.rect(x, top, pw, ph, fill=PANEL_FILL, line=PANEL_LINE, lw=1.4, r=8)
        by = top + 22
        for i, label in enumerate(items):
            bx = x + pad + i * (bw + gap)
            c.rect(bx, by, bw, bh, fill=WHITE, line=BOX_LINE, lw=1.8, r=5)
            parts = label.split(" and ") if len(label) > 14 else [label]
            if len(label) > 14 and " and " in label:
                parts = [parts[0] + " and", parts[1]]
            elif len(label) > 14:
                w = label.split(" ")
                parts = [" ".join(w[:-1]), w[-1]] if len(w) > 1 else [label]
            c.lines(bx + bw / 2, by + bh / 2, parts, size=15, color=NAVY)
            if i:
                c.path([(bx - gap + 2, by + bh / 2), (bx - 2, by + bh / 2)])
        if prev_right is not None:
            c.path([(prev_right - 6, by + bh / 2), (x + pad - 2, by + bh / 2)])
        c.text(x + pw / 2, top + ph - 16, title, size=15, bold=True, color=NAVY)
        prev_right = x + pw
        x += pw + 22
    caption(c, "Figure 1. The traceability chain behind every draft.", 236)
    return c


# =============================================================================
# Figure 2 - workflow
# =============================================================================
def figure2() -> Canvas:
    c = Canvas(1500, 420)
    bw, bh, gap = 250, 112, 50
    x0, y0 = 25, 108
    stages = [
        ("Stage 1", ["Intake: register the claim,", "screen for signals,", "draft the first request"],
         ["Adjuster approves", "the draft"], False),
        ("Stage 2", ["Awaiting documents: checklist", "built for the claim type;", "chase drafts as replies arrive"],
         ["Adjuster verifies", "each document"], True),
        ("Stage 3", ["Review ready: draft the", "preliminary coverage", "recommendation"],
         ["Adjuster approves or", "changes the recommendation"], True),
        ("Stage 4", ["Settlement: record the decision,", "repair authorised,", "payment arranged"],
         ["Human only: adjuster", "records every step"], True),
        ("Stage 5", ["Closed: draft the closure", "notice; save the real", "outcome to customer memory"],
         ["Adjuster approves", "the notice"], False),
    ]
    centers = []
    for i, (name, desc, gate, shaded) in enumerate(stages):
        x = x0 + i * (bw + gap)
        c.rect(x, y0, bw, bh, fill=SHADE if shaded else WHITE, line=BOX_LINE, lw=1.8, r=5)
        c.text(x + bw / 2, y0 + 28, name, size=15, bold=True, color=NAVY)
        c.lines(x + bw / 2, y0 + 70, desc, size=13.5, color=NAVY)
        c.lines(x + bw / 2, y0 + bh + 34, gate, size=13, italic=True, color=GREY)
        centers.append(x + bw / 2)
        if i:
            c.path([(x - gap + 3, y0 + bh / 2), (x - 3, y0 + bh / 2)])
    # the loop that makes the memory useful: a closed claim becomes history
    ly = 62
    c.path([(centers[4], y0 - 2), (centers[4], ly), (centers[0], ly), (centers[0], y0 - 2)],
           dash=True, lw=1.5)
    c.text((centers[0] + centers[4]) / 2, ly - 12,
           "A closed claim's outcome becomes the customer's history, and resurfaces at Stage 1 of their next claim",
           size=13, italic=True, color=GREY)
    # legend
    lx, lyy = 25, 300
    c.rect(lx, lyy, 30, 20, fill=SHADE, line=BOX_LINE, lw=1.4, r=3)
    c.text(lx + 42, lyy + 15, "Stage where the adjuster makes a decision on the claim itself, not only approving a draft",
           size=13.5, color=NAVY, anchor="left")
    caption(c, "Figure 2. End-to-end workflow of the copilot.", 372)
    return c


# =============================================================================
# Figure 2, README edition - GitHub-neutral styling, two lanes (copilot / adjuster)
# =============================================================================
def figure2_readme() -> Canvas:
    TXT, MUTED, BORDER, FILL = "#1F2328", "#656D76", "#D0D7DE", "#F6F8FA"
    ACC_FILL, ACC_LINE, ACC_TXT = "#DDF4FF", "#54AEFF", "#0550AE"
    c = Canvas(900, 292, face="segoe")
    x0, cw, gap = 96, 144, 18
    heads = ["1 Intake", "2 Awaiting documents", "3 Review ready", "4 Settlement", "5 Closed"]
    copilot = [["Screens the claim and", "drafts the first request"],
               ["Builds the checklist;", "drafts chasers as", "replies arrive"],
               ["Drafts the", "preliminary coverage", "recommendation"],
               ["No AI step:", "human only"],
               ["Drafts the closure", "notice; saves the outcome", "to customer memory"]]
    adjuster = [["Reviews, edits and", "approves the draft"],
                ["Verifies each", "document"],
                ["Approves or changes", "the recommendation"],
                ["Records the decision,", "repair and payment"],
                ["Approves the notice"]]
    decision = [False, True, True, True, False]
    hy, hh = 52, 34
    cy_, ch = 100, 64
    ay, ah = 176, 64
    centers = []
    for i in range(5):
        x = x0 + i * (cw + gap)
        centers.append(x + cw / 2)
        c.rect(x, hy, cw, hh, fill=WHITE, line=BORDER, lw=1.2, r=6)
        c.text(x + cw / 2, hy + 22, heads[i], size=12, bold=True, color=TXT)
        c.rect(x, cy_, cw, ch, fill=FILL, line=BORDER, lw=1.2, r=6)
        muted = i == 3
        c.lines(x + cw / 2, cy_ + ch / 2, copilot[i], size=12, color=MUTED if muted else TXT,
                italic=muted)
        c.rect(x, ay, cw, ah, fill=ACC_FILL if decision[i] else FILL,
               line=ACC_LINE if decision[i] else BORDER, lw=1.2, r=6)
        c.lines(x + cw / 2, ay + ah / 2, adjuster[i], size=12,
                color=ACC_TXT if decision[i] else TXT, bold=decision[i])
        if i:
            c.path([(x - gap + 2, hy + hh / 2), (x - 2, hy + hh / 2)], color="#8C959F", lw=1.4)
    c.text(8, cy_ + ch / 2 + 4, "Copilot", size=12.5, bold=True, color=MUTED, anchor="left")
    c.text(8, ay + ah / 2 + 4, "Adjuster", size=12.5, bold=True, color=MUTED, anchor="left")
    # the loop: a closed claim becomes the customer's history for the next one
    ly = 30
    c.path([(centers[4], hy - 2), (centers[4], ly), (centers[0], ly), (centers[0], hy - 2)],
           color="#8C959F", lw=1.3, dash=True)
    c.text((centers[0] + centers[4]) / 2, ly - 9,
           "A closed claim's outcome becomes the customer's history for their next claim",
           size=12, italic=True, color=MUTED)
    c.rect(x0, 264, 22, 14, fill=ACC_FILL, line=ACC_LINE, lw=1.2, r=3)
    c.text(x0 + 32, 275, "The adjuster makes a decision on the claim itself, not only approving a draft",
           size=12, color=MUTED, anchor="left")
    return c


# =============================================================================
# Figure 4 - architecture
# =============================================================================
def figure4() -> Canvas:
    c = Canvas(1250, 700)
    lx, lw_, top = 30, 900, 24
    lh_, gap = 120, 36
    layers = [
        ("1. PRESENTATION LAYER (FRONTEND: STREAMLIT)",
         ["Claim intake form", "Stage-aware workbench", "Documents checklist and correspondence log", "Context-used panel"]),
        ("2. APPLICATION AND WORKFLOW LAYER (BACKEND: FASTAPI)",
         ["API routes", "Dependency wiring", "Claim lifecycle and stage rules", "Draft orchestration and storage"]),
        ("3. INTELLIGENCE LAYER (BACKEND)",
         ["Intake gate", "Policy retrieval (RAG)", "Customer memory", "Signal checks: SLA, priority, load", "Draft generation (one LLM call)"]),
        ("4. DATA LAYER",
         ["SQLite system of record: claims, drafts, checklist, correspondence",
          "Policy and procedure documents", "Vector index of the policies", "Customer history, rebuilt from SQLite on restart"]),
    ]
    def wrap(s, n):
        words, out, cur = s.split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > n:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        out.append(cur)
        return out

    for li, (title, items) in enumerate(layers):
        y = top + li * (lh_ + gap)
        c.rect(lx, y, lw_, lh_, fill=PANEL_FILL, line=PANEL_LINE, lw=1.4, r=8)
        c.text(lx + 16, y + 26, title, size=13, bold=True, color=NAVY, anchor="left")
        n, pad, ig = len(items), 16, 14
        bw = (lw_ - 2 * pad - (n - 1) * ig) / n
        chars = 20 if n == 4 else 16
        for i, label in enumerate(items):
            bx = lx + pad + i * (bw + ig)
            c.rect(bx, y + 42, bw, 64, fill=WHITE, line=BOX_LINE, lw=1.6, r=5)
            c.lines(bx + bw / 2, y + 74, wrap(label, chars + (6 if li == 3 and i == 0 else 0)),
                    size=13.5, color=NAVY)
        if li < len(layers) - 1:
            cx = lx + lw_ / 2
            c.path([(cx, y + lh_ + 3), (cx, y + lh_ + gap - 3)], head=True, tail=True)

    # cross-cutting safeguards
    px, pw = 960, 260
    ph = len(layers) * lh_ + (len(layers) - 1) * gap
    c.rect(px, top, pw, ph, fill=NAVY, line=NAVY, lw=1, r=8)
    c.lines(px + pw / 2, top + 34, ["CROSS-CUTTING", "SAFEGUARDS"], size=13.5, bold=True, color=WHITE)
    items = ["Human approval", "Context trace", "Template fallback", "Neutral-language flags", "Offline evaluation"]
    iy, ih, ig = top + 84, 62, 42
    for i, s in enumerate(items):
        yy = iy + i * (ih + ig)
        c.rect(px + 20, yy, pw - 40, ih, fill=SAFE_ITEM, line="#4A6C9B", lw=1.2, r=6)
        c.text(px + pw / 2, yy + ih / 2 + 5, s, size=14.5, color=WHITE)
    caption(c, "Figure 4. Architecture of the claims copilot.", top + ph + 44)
    return c


if __name__ == "__main__":
    for stem, fn in (("fig1_traceability_chain", figure1),
                     ("fig2_claim_workflow", figure2),
                     ("fig2_claim_workflow_readme", figure2_readme),
                     ("fig4_architecture", figure4)):
        fn().save(stem)
        print("wrote", stem)
