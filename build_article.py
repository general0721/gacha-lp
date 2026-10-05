#!/usr/bin/env python3
"""記事LPビルダーの公開版（published/lp-02.html）を article/ に軽量化して書き出す。

  python3 build_article.py

- /uploads/… を相対パスにし、使っている素材だけ article/uploads/ に置く
- 画像は WebP（横幅最大1000px）、HTMLに埋め込まれた画像（data:）もファイルに出して WebP 化
- 動画は全部「コマ送り」に変換して <canvas> にページのJSで描く（横720px・30コマ/秒）。
  コマは数枚ずつ縦につないだ止め絵（uploads/<名前>.frames/s000.webp …）にして、画面に入ったものだけ読み込んで描く。
  経緯（2026-10-05）：<video> はiPhoneの低電力モード等で止められ再生ボタンが出る → アニメーションWebPにしたが
  iPhoneでは「動かない」（低電力モード／アニメーション画像の自動再生オフ／重くて読み込み待ち）→ JSで描く方式に。
  コマの書き出しは tools/vconv（Mac標準のAVFoundation。swiftc -O tools/vconv.swift -o tools/vconv）
- 2枚目以降の画像は遅延読み込み。動画の枠は読み込み中も最初のコマを背景に出しておく
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
SHEET_PX = 3_000_000   # 1枚の止め絵に入れるコマの合計画素数の上限（スマホのメモリ対策）


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


def video_to_sheets(src, dirname):
    """動画 → コマを縦につないだ止め絵の束（dirname/s000.webp…）と最初のコマ（dirname/poster.webp）。
    (幅, 高さ, コマ数, 1枚あたりのコマ数) を返す"""
    meta = os.path.join(dirname, 'meta.txt')
    if not (os.path.exists(meta) and os.path.getmtime(meta) >= os.path.getmtime(src)):
        shutil.rmtree(dirname, ignore_errors=True)
        d = dirname + '.tmp'
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        subprocess.run([VCONV, '--frames', src, d, str(ANIM_FPS), str(ANIM_W)], check=True)
        files = sorted(os.listdir(d))
        w, h = Image.open(os.path.join(d, files[0])).size
        per = max(1, min(SHEET_PX // (w * h), 16383 // h))
        os.makedirs(dirname)
        for k in range(0, len(files), per):
            chunk = files[k:k + per]
            sheet = Image.new('RGB', (w, h * len(chunk)))
            for j, f in enumerate(chunk):
                sheet.paste(Image.open(os.path.join(d, f)).convert('RGB'), (0, h * j))
            sheet.save(os.path.join(dirname, 's%03d.webp' % (k // per)), 'WEBP', quality=ANIM_Q, method=4)
        Image.open(os.path.join(d, files[0])).convert('RGB').save(os.path.join(dirname, 'poster.webp'), 'WEBP', quality=60, method=6)
        shutil.rmtree(d)
        open(meta, 'w').write('%d %d %d %d' % (w, h, len(files), per))
    return tuple(int(x) for x in open(meta).read().split())


# コマ送りの再生：画面の近くに来た枠だけ止め絵を読み込み、時間に合わせて1コマずつ canvas に描く。
# 読み込めていないコマは直前のコマのまま待つ（最初は poster が背景に出ている）。画面外の枠は描かず、古い止め絵は手放す。
PLAYER = """<script>
(function(){
  var cs=[].slice.call(document.querySelectorAll('canvas[data-frames]'));
  var live=[];
  cs.forEach(function(c){
    c._n=+c.dataset.n; c._per=+c.dataset.per; c._fps=+c.dataset.fps; c._sheets={}; c._drawn=-1;
    c._ctx=c.getContext('2d'); c._t0=null;
  });
  function sheet(c,k){
    var s=c._sheets[k]; if(s) return s;
    s=new Image(); s.decoding='async'; s.src=c.dataset.frames+'s'+('00'+k).slice(-3)+'.webp';
    s.onload=function(){ s._ok=true; }; c._sheets[k]=s; return s;
  }
  function tick(now){
    live.forEach(function(c){
      if(c._t0===null) c._t0=now;
      var i=Math.floor((now-c._t0)/1000*c._fps)%c._n, k=Math.floor(i/c._per), s=sheet(c,k);
      var nk=(k+1)*c._per<c._n?k+1:0; sheet(c,nk);
      for(var key in c._sheets){ if(+key!==k&&+key!==nk&&+key!==0){ delete c._sheets[key]; } }
      if(s._ok&&i!==c._drawn){
        var w=c.width,h=c.height; c._ctx.drawImage(s,0,(i-k*c._per)*h,w,h,0,0,w,h); c._drawn=i;
      }
    });
    requestAnimationFrame(tick);
  }
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){ es.forEach(function(e){
      var c=e.target, at=live.indexOf(c);
      if(e.isIntersecting){ if(at<0){ live.push(c); sheet(c,0); } }
      else if(at>=0){ live.splice(at,1); c._sheets={0:c._sheets[0]}; c._t0=null; }
    }); },{rootMargin:'400px 0px'});
    cs.forEach(function(c){ io.observe(c); });
  } else live=cs;
  requestAnimationFrame(tick);
})();
</script>"""


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
            name = base + '.frames'
            sizes[name] = video_to_sheets(src, os.path.join(OUT_UP, name))
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

    # <video …></video> → コマ送りの <canvas>。動画用の見た目（角丸・枠・影・切り抜き）は CSS の video を .vanim に読み替えて引き継ぐ
    def vid(m):
        attrs = m.group(1)
        sm = re.search(r'\ssrc="uploads/([^"]+)\.frames"', attrs)
        if not sm:
            return m.group(0)
        base = sm.group(1)
        w, h, nfr, per = sizes[base + '.frames']
        attrs = attrs.replace(sm.group(0), '')
        attrs = re.sub(r'\s(autoplay|muted|playsinline|loop|controls)(?=[\s>]|$)', '', attrs)
        attrs = re.sub(r'\s(preload|poster)="[^"]*"', '', attrs)
        bg = 'background-image:url(uploads/%s.frames/poster.webp);background-size:100%% 100%%' % base
        if re.search(r'\sstyle="', attrs):
            attrs = re.sub(r'\sstyle="([^"]*)"', lambda s2: ' style="%s;%s"' % (s2.group(1).rstrip(';'), bg), attrs, 1)
        else:
            attrs += ' style="%s"' % bg
        cm = re.search(r'\sclass="([^"]*)"', attrs)
        if cm:
            attrs = attrs.replace(cm.group(0), ' class="%s vanim"' % cm.group(1), 1)
        else:
            attrs += ' class="vanim"'
        return ('<canvas%s width="%d" height="%d" data-frames="uploads/%s.frames/" data-n="%d" data-per="%d" data-fps="%d"></canvas>'
                % (attrs, w, h, base, nfr, per, ANIM_FPS))
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

    html = html.replace('</body>', PLAYER + '</body>', 1) if '</body>' in html else html + PLAYER

    for fn in os.listdir(OUT_UP):
        if fn not in keep:
            fp = os.path.join(OUT_UP, fn)
            shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(html)
    tot = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(OUT_UP) for f in fs)
    print('html %dKB / 素材 %d点 %.1fMB' % (len(html.encode()) // 1024, len(keep), tot / 1048576))


if __name__ == '__main__':
    main()
