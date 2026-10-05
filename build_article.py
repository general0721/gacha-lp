#!/usr/bin/env python3
"""記事LPビルダーの公開版（published/lp-02.html）を article/ に軽量化して書き出す。

  python3 build_article.py

- /uploads/… を相対パスにし、使っている素材だけ article/uploads/ に置く
- 画像は WebP（横幅最大1000px）、HTMLに埋め込まれた画像（data:）もファイルに出して WebP 化
- 動画は全部「動く画像」（アニメーションWebP・横720px・30コマ/秒（元動画と同じなめらかさ。2026-10-05 ユーザー指定で15→30））に変換して <img> に置き換える。
  動画だとiPhoneの低電力モード等で自動再生が止められ再生ボタンが出るため（2026-10-05 ユーザー指定）。
  コマの書き出しは tools/vconv（Mac標準のAVFoundation。swiftc -O tools/vconv.swift -o tools/vconv）
- 2枚目以降の画像は遅延読み込み。動く画像は読み込み中も最初のコマを背景に出しておく
"""
import base64, hashlib, io, os, re, shutil, subprocess, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.expanduser('~/kiji-lp-builder')
SRC_HTML = os.path.join(BUILDER, 'published', 'lp-02.html')
SRC_UP = os.path.join(BUILDER, 'public', 'uploads')
OUT = os.path.join(HERE, 'article')
OUT_UP = os.path.join(OUT, 'uploads')
MAX_W = 1000
VIDEO_EXT = ('.mp4', '.mov', '.m4v', '.webm')
VCONV = os.path.join(HERE, 'tools', 'vconv')   # swiftc -O tools/vconv.swift -o tools/vconv
ANIM_W, ANIM_FPS, ANIM_Q = 720, 30, 70


def to_webp(im, dst):
    if getattr(im, 'n_frames', 1) > 1:   # アニメGIF
        im.save(dst, 'WEBP', save_all=True, quality=75, method=6)
        return
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA' if 'A' in im.getbands() or 'transparency' in im.info else 'RGB')
    if im.mode == 'RGBA' and im.getchannel('A').getextrema()[0] == 255:
        im = im.convert('RGB')
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    im.save(dst, 'WEBP', quality=80, method=6)


def video_to_anim(src, dst, poster):
    """動画 → 動く画像（アニメーションWebP）と最初のコマ（poster）。大きさは (幅, 高さ) を返す"""
    if not (os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src) and os.path.exists(poster)):
        d = dst + '.frames'
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        subprocess.run([VCONV, '--frames', src, d, str(ANIM_FPS), str(ANIM_W)], check=True)
        frames = [Image.open(os.path.join(d, f)).convert('RGB') for f in sorted(os.listdir(d))]
        frames[0].save(dst, 'WEBP', save_all=True, append_images=frames[1:],
                       duration=round(1000 / ANIM_FPS), loop=0, quality=ANIM_Q, method=4)
        frames[0].save(poster, 'WEBP', quality=60, method=6)
        shutil.rmtree(d)
    return Image.open(poster).size


def main():
    html = open(SRC_HTML, encoding='utf-8').read()
    os.makedirs(OUT_UP, exist_ok=True)
    keep = set()
    sizes = {}

    # 埋め込み画像（data:）→ ファイル
    def inline(m):
        raw = base64.b64decode(m.group(2))
        name = 'inline_' + hashlib.sha1(raw).hexdigest()[:10] + '.webp'
        dst = os.path.join(OUT_UP, name)
        if not os.path.exists(dst):
            to_webp(Image.open(io.BytesIO(raw)), dst)
        keep.add(name)
        return 'uploads/' + name
    html = re.sub(r'data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=]+)', inline, html)

    # /uploads/… → 変換して相対パスに
    def upload(m):
        fn = m.group(2)
        src = os.path.join(SRC_UP, fn)
        base, ext = os.path.splitext(fn)
        ext = ext.lower()
        if ext in VIDEO_EXT:
            name = base + '.anim.webp'
            poster = base + '.poster.webp'
            sizes[name] = video_to_anim(src, os.path.join(OUT_UP, name), os.path.join(OUT_UP, poster))
            keep.add(poster)
        elif ext in ('.png', '.jpg', '.jpeg', '.gif'):
            name = base + '.webp'
            dst = os.path.join(OUT_UP, name)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                to_webp(Image.open(src), dst)
        else:
            name = fn
            shutil.copy2(src, os.path.join(OUT_UP, name))
        keep.add(name)
        return m.group(1) + 'uploads/' + name
    html = re.sub(r'(^|[^A-Za-z0-9_.-])/uploads/([^"\')\s&\\]+)', upload, html)

    # <video …></video> → 動く画像の <img>。動画用の見た目（角丸・枠・影・切り抜き）は CSS の video を .vanim に読み替えて引き継ぐ
    def vid(m):
        attrs = m.group(1)
        sm = re.search(r'src="uploads/([^"]+)\.anim\.webp"', attrs)
        if not sm:
            return m.group(0)
        base = sm.group(1)
        w, h = sizes[base + '.anim.webp']
        attrs = re.sub(r'\s(autoplay|muted|playsinline|loop|controls)(?=[\s>]|$)', '', attrs)
        attrs = re.sub(r'\s(preload|poster)="[^"]*"', '', attrs)
        bg = 'background-image:url(uploads/%s.poster.webp);background-size:cover;background-position:center' % base
        if re.search(r'\sstyle="', attrs):
            attrs = re.sub(r'\sstyle="([^"]*)"', lambda s2: ' style="%s;%s"' % (s2.group(1).rstrip(';'), bg), attrs, 1)
        else:
            attrs += ' style="%s"' % bg
        cm = re.search(r'\sclass="([^"]*)"', attrs)
        if cm:
            attrs = attrs.replace(cm.group(0), ' class="%s vanim"' % cm.group(1), 1)
        else:
            attrs += ' class="vanim"'
        return '<img%s width="%d" height="%d" alt="">' % (attrs, w, h)
    html = re.sub(r'<video\b([^>]*)>\s*</video>', vid, html)
    html = re.sub(r'<style\b[^>]*>.*?</style>',
                  lambda m: re.sub(r'(?<![-\w.#])video(?=[\s,.>:{\[)+~]|$)', '.vanim', m.group(0)), html, flags=re.S)

    # 画像は最初の2枚以外を遅延読み込み
    n = [0]
    def lazy(m):
        n[0] += 1
        tag = m.group(0)
        # 縦横を書いておくと、遅れて読み込む画像でもページがガタつかない
        sm = re.search(r'src="uploads/([^"]+)"', tag)
        if sm and ' width=' not in tag and os.path.exists(os.path.join(OUT_UP, sm.group(1))):
            w, h = Image.open(os.path.join(OUT_UP, sm.group(1))).size
            tag = tag[:-1].rstrip('/').rstrip() + ' width="%d" height="%d">' % (w, h)
        if n[0] <= 2 or 'loading=' in tag:
            return tag
        return tag[:4] + ' loading="lazy" decoding="async"' + tag[4:]
    html = re.sub(r'<img\b[^>]*>', lazy, html)

    for fn in os.listdir(OUT_UP):
        if fn not in keep:
            os.remove(os.path.join(OUT_UP, fn))
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(html)
    tot = sum(os.path.getsize(os.path.join(OUT_UP, f)) for f in keep)
    print('html %dKB / 素材 %d点 %.1fMB' % (len(html.encode()) // 1024, len(keep), tot / 1048576))


if __name__ == '__main__':
    main()
