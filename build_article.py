#!/usr/bin/env python3
"""記事LPビルダーの公開版（published/lp-02.html）を article/ に軽量化して書き出す。

  python3 build_article.py

- /uploads/… を相対パスにし、使っている素材だけ article/uploads/ に置く
- 画像は WebP（横幅最大1000px）、HTMLに埋め込まれた画像（data:）もファイルに出して WebP 化
- 動画は tools/vconv（Mac標準のAVFoundation）で短辺720px・1.6Mbps の H.264（すぐ再生できる fast-start・音声なし）mp4 に変換
- 2枚目以降の画像は遅延読み込み、動画は画面に入ったら再生
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


def convert_video(src, dst):
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    tmp = dst + '.tmp.mp4'
    subprocess.run([VCONV, src, tmp, '1600'], check=True, stdout=subprocess.DEVNULL)
    if os.path.getsize(tmp) > os.path.getsize(src) * 0.9:   # 元がすでに軽い動画は、元より重くしない
        kbps = max(300, int(1600 * os.path.getsize(src) / os.path.getsize(tmp) * 0.8))
        subprocess.run([VCONV, src, tmp, str(kbps)], check=True, stdout=subprocess.DEVNULL)
    os.replace(tmp, dst)


def main():
    html = open(SRC_HTML, encoding='utf-8').read()
    os.makedirs(OUT_UP, exist_ok=True)
    keep = set()

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
            name = base + '.mp4'
            convert_video(src, os.path.join(OUT_UP, name))
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

    # 画像は最初の2枚以外を遅延読み込み
    n = [0]
    def lazy(m):
        n[0] += 1
        tag = m.group(0)
        if n[0] <= 2 or 'loading=' in tag:
            return tag
        return tag[:4] + ' loading="lazy" decoding="async"' + tag[4:]
    html = re.sub(r'<img\b[^>]*>', lazy, html)

    # 動画は最初の1本だけ先読み、残りは画面に入ったら読む
    v = [0]
    def vid(m):
        v[0] += 1
        return m.group(0) if v[0] == 1 else m.group(0).replace('preload="auto"', 'preload="metadata"')
    html = re.sub(r'<video\b[^>]*>', vid, html)

    script = '''<script>
(function(){
  var vs=[].slice.call(document.querySelectorAll('video[autoplay]'));
  function play(v){ v.muted=true; var p=v.play(); if(p&&p.catch) p.catch(function(){}); }
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){ es.forEach(function(e){
      if(e.isIntersecting){ e.target.preload='auto'; play(e.target); } else e.target.pause();
    }); },{rootMargin:'200px 0px'});
    vs.forEach(function(v){ io.observe(v); });
  } else vs.forEach(play);
  /* 低電力モード等で自動再生が止められたときは、最初のタッチ・スクロールで再生 */
  function kick(){ vs.forEach(function(v){ var r=v.getBoundingClientRect();
    if(r.bottom>0&&r.top<innerHeight) play(v); }); }
  ['touchstart','scroll','click'].forEach(function(t){ addEventListener(t,kick,{passive:true}); });
})();
</script>'''
    html = html.replace('</body>', script + '</body>', 1) if '</body>' in html else html + script

    for fn in os.listdir(OUT_UP):
        if fn not in keep:
            os.remove(os.path.join(OUT_UP, fn))
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(html)
    tot = sum(os.path.getsize(os.path.join(OUT_UP, f)) for f in keep)
    print('html %dKB / 素材 %d点 %.1fMB' % (len(html.encode()) // 1024, len(keep), tot / 1048576))


if __name__ == '__main__':
    main()
