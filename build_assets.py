# 素材の前処理（python3 build_assets.py で assets/ を再生成）
#  gacha.webp    : 白背景と接地影を除去、取手を消して下地を補間したガチャ本体
#  handle.webp   : 回転用に切り出した取手（回転中心 = 画像中央）
#  capsules.webp : （旧）カプセル層。現在は未使用
#  capsule-sprites.webp : カプセル単体6色（176px角×6コマ）。canvas で1個ずつ動かす
#  label.webp    : カプセル層の上に固定するロゴ楕円
#  bg.webp       : 背景
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
from collections import deque

im = Image.open('assets/gacha-src.png').convert('RGB')
W, H = im.size
a = np.asarray(im).astype(np.int16)

# --- 白背景：外周からフラッドフィル ---
mn = a.min(axis=2); mx = a.max(axis=2)
cand = (mn > 232) & ((mx - mn) < 14)
bg = np.zeros((H, W), bool)
q = deque()
for y in range(H):
    for x in range(W):
        if (x in (0, W-1) or y in (0, H-1)) and cand[y, x]:
            bg[y, x] = True; q.append((y, x))
while q:
    y, x = q.popleft()
    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
        ny, nx = y+dy, x+dx
        if 0 <= ny < H and 0 <= nx < W and not bg[ny, nx] and cand[ny, nx]:
            bg[ny, nx] = True; q.append((ny, nx))

# 接地影：脚の下は全部消し、縁付近はグレー（低彩度）だけ消す
bg[1424:, :] = True
band = np.zeros((H, W), bool); band[1396:1424, :] = True
bg |= band & ((mx - mn) < 22) & (mn > 140)

alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8))
alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.1))

# --- 取手 ---
HX, HY, HA, HB = 510.5, 1084.5, 27, 84          # 取手の中心と半径
yy, xx = np.mgrid[0:H, 0:W]
def ell(cx, cy, ra, rb):
    return ((xx - cx) / ra) ** 2 + ((yy - cy) / rb) ** 2

# 取手スプライト（周囲 1px をぼかす）
hmask = Image.fromarray((np.clip((1.0 - ell(HX, HY, HA, HB)) * 40, 0, 1) * 255).astype(np.uint8))
box = (int(HX - 90), int(HY - 90), int(HX + 90), int(HY + 90))   # 180x180、中心=回転中心
hs = im.copy(); hs.putalpha(hmask)
hs.crop(box).save('assets/handle.webp', quality=92)

# 本体側の取手を消す：行ごとに左右の画素から線形補間
base = a.copy().astype(np.float32)
ia, ib = HA + 5, HB + 5
for y in range(int(HY - ib), int(HY + ib) + 1):
    t = (y - HY) / ib
    if abs(t) >= 1: continue
    half = ia * np.sqrt(1 - t * t)
    x0 = int(np.floor(HX - half)) - 1
    x1 = int(np.ceil(HX + half)) + 1
    L = base[y, x0 - 2:x0 + 1].mean(axis=0); R = base[y, x1:x1 + 3].mean(axis=0)
    for x in range(x0 + 1, x1):
        f = (x - x0) / (x1 - x0)
        base[y, x] = L * (1 - f) + R * f
# --- ガラス球の中を空にする（カプセルは canvas で1個ずつ描く） ---
GX, GY, GR = 510, 565, 397                     # ガラス内側の円
d = np.sqrt((xx - GX) ** 2 + (yy - 520) ** 2) / GR
t = np.clip(d, 0, 1)[..., None]
glass = np.array([247, 243, 250], np.float32) * (1 - t) + np.array([234, 226, 240], np.float32) * t
rin = np.sqrt((xx - GX) ** 2 + (yy - GY) ** 2)
m = np.clip((GR - rin) / 4, 0, 1)                        # 円の縁をなじませる
m *= np.clip((yy - 300) / 24, 0, 1)                      # 上はガラスの色と同じなので徐々に
m *= (yy <= 891)                                         # 下は金のリングの手前まで
m = m[..., None]
base = base * (1 - m) + glass * m

baseim = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
g = baseim.copy(); g.putalpha(alpha)
g.save('assets/gacha.webp', quality=90)

# --- カプセル層：ガラス球の内側 ---
CX, CY, CR = 510, 565, 392
cm = ((xx - CX) ** 2 + (yy - CY) ** 2 < CR ** 2) & (yy > 330) & (yy < 888)
cmask = Image.fromarray((cm * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))
cbox = (CX - CR, 330, CX + CR, 888)
c = im.copy(); c.putalpha(cmask)
c.crop(cbox).save('assets/capsules.webp', quality=88)

# --- カプセル単体のスプライト（前列のきれいに見えている2個＋色違い） ---
SP = 176                                        # 1コマの大きさ（半径84 + 余白）
def cut(cx, cy, r):
    box = (cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3)
    c = im.crop(tuple(int(round(v)) for v in box)).convert('RGBA')
    w = c.size[0]
    my, mx_ = np.mgrid[0:w, 0:w]
    rr = np.sqrt((mx_ - w / 2 + .5) ** 2 + (my - w / 2 + .5) ** 2)
    c.putalpha(Image.fromarray((np.clip(r - 1 - rr, 0, 1) * 255).astype(np.uint8)))
    return c.resize((SP - 8, SP - 8), Image.LANCZOS)
def hue(img, deg, sat=1.0, light=0.0):
    rgb, al = img.convert('RGB'), img.getchannel('A')
    h, s_, v = [np.asarray(ch).astype(np.float32) for ch in rgb.convert('HSV').split()]
    h = (h + deg / 360 * 255) % 255
    s_ = np.clip(s_ * sat, 0, 255)
    out = Image.merge('HSV', [Image.fromarray(x.astype(np.uint8)) for x in (h, s_, v)]).convert('RGB')
    if light:
        out = Image.blend(out, Image.new('RGB', out.size, (255, 255, 255)), light)
    out.putalpha(al)
    return out
A = cut(320.5, 796, 81)        # 濃いピンク（上半分クリア）
B = cut(485, 807.5, 84)        # 淡いピンク（上半分クリア）
variants = [A, B, hue(A, -58, .85), hue(B, -58, .9), hue(A, 0, .7, .22), hue(B, -30, .9)]
sheet = Image.new('RGBA', (SP * len(variants), SP), (0, 0, 0, 0))
for i, v in enumerate(variants):
    sheet.alpha_composite(v, (i * SP + 4, 4))
sheet.save('assets/capsule-sprites.webp', quality=90)

# --- ロゴ楕円 ---
LX, LY, LA, LB = 512, 570, 234, 142
lm = Image.fromarray((np.clip((1.0 - ell(LX, LY, LA, LB)) * 60, 0, 1) * 255).astype(np.uint8))
lbox = (LX - LA - 2, LY - LB - 2, LX + LA + 2, LY + LB + 2)
l = im.copy(); l.putalpha(lm)
l.crop(lbox).save('assets/label.webp', quality=90)

Image.open('assets/bg-src.png').convert('RGB').save('assets/bg.webp', quality=88)

print('handle box', box, 'capsule box', cbox, 'label box', lbox)

# --- 出てくるカプセル（ユーザー支給素材）を上下に分割 ---
#  capsule-top.webp / capsule-bottom.webp : 同じ正方形キャンバス。重ねると1個のカプセル
cap = Image.open('assets/capsule-src.png').convert('RGBA')
CCX, CCY, CRR = 603.5, 641, 440                  # 球の中心と半径
ca = np.asarray(cap).astype(np.float32)
cy_, cx_ = np.mgrid[0:cap.size[1], 0:cap.size[0]]
rr = np.sqrt((cx_ - CCX) ** 2 + (cy_ - CCY) ** 2)
ca[..., 3] *= np.clip(CRR + 2 - rr, 0, 1)        # 球の外（下の映り込み）を消す
# フタの下端は手前に膨らむ楕円：端 y=650、中央 y=702
seam = 650 + 52 * np.sqrt(np.clip(1 - ((cx_ - CCX) / CRR) ** 2, 0, 1))
top_m = np.clip(seam - cy_ + .5, 0, 1)
box = (int(CCX - 450), int(CCY - 450), int(CCX + 450), int(CCY + 450))
for name, m in (('top', top_m), ('bottom', 1 - top_m)):
    part = ca.copy(); part[..., 3] *= m
    Image.fromarray(part.astype(np.uint8)).crop(box).resize((512, 512), Image.LANCZOS) \
        .save(f'assets/capsule-{name}.webp', quality=92)

# --- チケット入りカプセル（ユーザー支給・白背景）---
#  capsule-whole.webp  : 割れる前の見た目。capsule-top/bottom と同じ大きさ・位置になる箱で切り出す
#  capsule-ticket.webp : 中のチケットだけ（割れた瞬間に取り出して本物のチケットへつなぐ）
tk = Image.open('assets/capsule-ticket-src.png').convert('RGB')
ta = np.asarray(tk).astype(np.float32)
TX, TY, TR = 606, 632, 447                       # 球（継ぎ目のフチは少し外に出る）
ty_, tx_ = np.mgrid[0:tk.size[1], 0:tk.size[0]]
r2 = np.sqrt((tx_ - TX) ** 2 + (ty_ - TY) ** 2)
m = np.clip(TR + .5 - r2, 0, 1)
lip = (np.abs(ty_ - 662) < 42) & (np.abs(tx_ - TX) < 454) & (ta.min(axis=2) < 240)
m = np.maximum(m, lip.astype(np.float32))
rgba = np.dstack([ta, m * 255]).astype(np.uint8)
half = TR * 450 / CRR                             # 旧カプセルと同じ比率の箱
wbox = tuple(int(round(v)) for v in (TX - half, TY - half, TX + half, TY + half))
Image.fromarray(rgba).crop(wbox).resize((512, 512), Image.LANCZOS).save('assets/capsule-whole.webp', quality=92)

# チケット：角丸の長方形から左右の切り欠きを抜く
KX0, KY0, KX1, KY1, KR = 278, 368, 928, 684, 14
kw, kh = KX1 - KX0, KY1 - KY0
ky, kx = np.mgrid[0:kh, 0:kw].astype(np.float32)
dx = np.maximum(np.maximum(KR - kx, kx - (kw - 1 - KR)), 0)
dy = np.maximum(np.maximum(KR - ky, ky - (kh - 1 - KR)), 0)
km = np.clip(KR + .5 - np.sqrt(dx ** 2 + dy ** 2), 0, 1)
for nx in (285 - KX0, 921 - KX0):
    km *= np.clip(np.sqrt((kx - nx) ** 2 + (ky - (535 - KY0)) ** 2) - 40, 0, 1)
kimg = np.dstack([ta[KY0:KY1, KX0:KX1], km * 255]).astype(np.uint8)
Image.fromarray(kimg).save('assets/capsule-ticket.webp', quality=92)
print('whole box', wbox, 'ticket in box: left %.2f%% top %.2f%% w %.2f%% h %.2f%%' % (
    (KX0 - wbox[0]) / (wbox[2] - wbox[0]) * 100, (KY0 - wbox[1]) / (wbox[3] - wbox[1]) * 100,
    kw / (wbox[2] - wbox[0]) * 100, kh / (wbox[3] - wbox[1]) * 100))

# --- ファーストビューのタイトル（ユーザー支給・透過PNG）：余白を詰める ---
tt = Image.open('assets/title-src.png').convert('RGBA')
tb = tt.getchannel('A').point(lambda v: 255 if v > 10 else 0).getbbox()
tt.crop((max(tb[0] - 6, 0), max(tb[1] - 6, 0), min(tb[2] + 6, tt.width), min(tb[3] + 6, tt.height))) \
  .save('assets/title.webp', quality=92)
print('title size', tt.crop(tb).size)

# --- 当選チケット（ユーザー支給・透過PNG）：余白を詰める ---
tkt = Image.open('assets/ticket-src.png').convert('RGBA')
kb = tkt.getchannel('A').point(lambda v: 255 if v > 10 else 0).getbbox()
tkt = tkt.crop((max(kb[0] - 4, 0), max(kb[1] - 4, 0), min(kb[2] + 4, tkt.width), min(kb[3] + 4, tkt.height)))
tkt.save('assets/ticket.webp', quality=92)
print('ticket size', tkt.size, 'aspect %.4f' % (tkt.width / tkt.height))
