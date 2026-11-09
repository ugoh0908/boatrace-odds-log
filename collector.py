"""競艇オッズ記録プログラム（PC用・追加インストール不要）

全場・全レースについて、締切の10/5/3/2/1分前と締切後に
単勝オッズと3連単オッズを公式サイトから取得し、結果と一緒にCSVへ保存します。
起動しっぱなしにすると、毎日 8:00 から自動で記録します（終了は Ctrl+C）。

使い方:  python collector.py
保存先:  このファイルと同じフォルダの boatrace_data/odds_YYYYMMDD.csv
"""
import csv, datetime, json, os, re, threading, time, urllib.request

JST = datetime.timezone(datetime.timedelta(hours=9))
BASE = 'https://www.boatrace.jp/owpc/pc/race'
SNAPS = [('m10', -600), ('m5', -300), ('m3', -180), ('m2', -120), ('m1', -60), ('final', 180)]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boatrace_data')
os.makedirs(OUT, exist_ok=True)
lock = threading.Lock()
SUFFIX = ''

# 3連単オッズ表の並び順（列=1着艇、各列20行）
ORDER3 = []
_cols = [[(f, s, t) for s in range(1, 7) if s != f for t in range(1, 7) if t not in (f, s)] for f in range(1, 7)]
for k in range(20):
    for c in range(6): ORDER3.append(_cols[c][k])

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (personal odds logger)'})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception:
            time.sleep(2 + 3 * i)
    return ''

def num(x):
    return float(x) if re.match(r'^[\d.]+$', x or '') else None

def venues(hd):
    return sorted(set(re.findall(r'raceindex\?jcd=(\d+)&amp;hd=' + hd, get(f'{BASE}/index?hd={hd}'))))

def deadlines(jcd, hd):
    t = re.findall(r'>(\d{1,2}:\d{2})<', get(f'{BASE}/raceindex?jcd={jcd}&hd={hd}'))
    return t[:12] if len(t) >= 12 else []

def snapshot(jcd, rno, hd):
    w = re.findall(r'oddsPoint[^>]*>([^<]*)<', get(f'{BASE}/oddstf?rno={rno}&jcd={jcd}&hd={hd}'))[:6]
    o3 = re.findall(r'class="oddsPoint[^"]*">([^<]*)<', get(f'{BASE}/odds3t?rno={rno}&jcd={jcd}&hd={hd}'))[:120]
    tri = {'-'.join(map(str, c)): num(x) for c, x in zip(ORDER3, o3)}
    return [num(x) for x in w] + [None] * (6 - len(w)), tri

def result(jcd, rno, hd):
    t = re.sub(r'\s+', ' ', re.sub('<[^>]+>', ' ', get(f'{BASE}/raceresult?rno={rno}&jcd={jcd}&hd={hd}')))
    m = re.search(r'単勝 (\d) &yen;([\d,]+)', t); m3 = re.search(r'3連単 (\d) - (\d) - (\d) &yen;([\d,]+)', t)
    return (m.group(1) if m else '', m.group(2).replace(',', '') if m else '',
            '-'.join(m3.group(1, 2, 3)) if m3 else '', m3.group(4).replace(',', '') if m3 else '')

def save(hd, row):
    path = os.path.join(OUT, f'odds_{hd}{SUFFIX}.csv')
    with lock:
        new = not os.path.exists(path)
        with open(path, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if new: w.writerow(['date', 'jcd', 'rno', 'deadline', 'snap', 'fetched', 'win1', 'win2', 'win3', 'win4', 'win5', 'win6',
                                'tri_json', 'res_win', 'res_win_pay', 'res_tri', 'res_tri_pay'])
            w.writerow(row)

def job(hd, jcd, rno, dl, snap):
    try:
        win, tri = snapshot(jcd, rno, hd)
        res = result(jcd, rno, hd) if snap == 'final' else ('', '', '', '')
        now = datetime.datetime.now(JST).strftime('%H:%M:%S')
        save(hd, [hd, jcd, rno, dl, snap, now, *win, json.dumps(tri, separators=(',', ':')), *res])
        print(now, f'{jcd}場 {rno}R {snap}', flush=True)
    except Exception as e:
        print('エラー', jcd, rno, snap, e, flush=True)

def run_day(hd):
    tasks = []
    for jcd in venues(hd):
        for rno, dl in enumerate(deadlines(jcd, hd), 1):
            h, m = map(int, dl.split(':'))
            t0 = datetime.datetime(int(hd[:4]), int(hd[4:6]), int(hd[6:]), h, m, tzinfo=JST)
            for name, off in SNAPS:
                tasks.append((t0 + datetime.timedelta(seconds=off), jcd, rno, dl, name))
    tasks.sort()
    print(f'{hd}: {len(tasks) // len(SNAPS)} レースを記録します', flush=True)
    for t, jcd, rno, dl, name in tasks:
        wait = (t - datetime.datetime.now(JST)).total_seconds()
        if wait < -30: continue
        if wait > 0: time.sleep(wait)
        threading.Thread(target=job, args=(hd, jcd, rno, dl, name), daemon=True).start()
    time.sleep(120)

def run_window(hd, until):
    """Run today's snapshots whose time is before `until` (HH:MM JST), then return. For GitHub Actions."""
    h, m = map(int, until.split(':'))
    end = datetime.datetime.now(JST).replace(hour=h, minute=m, second=0, microsecond=0)
    tasks = []
    for jcd in venues(hd):
        for rno, dl in enumerate(deadlines(jcd, hd), 1):
            hh, mm = map(int, dl.split(':'))
            t0 = datetime.datetime(int(hd[:4]), int(hd[4:6]), int(hd[6:]), hh, mm, tzinfo=JST)
            for name, off in SNAPS:
                t = t0 + datetime.timedelta(seconds=off)
                if t < end: tasks.append((t, jcd, rno, dl, name))
    tasks.sort()
    print(f'{hd}: {len(tasks)} snapshots until {until}', flush=True)
    for t, jcd, rno, dl, name in tasks:
        wait = (t - datetime.datetime.now(JST)).total_seconds()
        if wait < -30: continue
        if wait > 0: time.sleep(wait)
        threading.Thread(target=job, args=(hd, jcd, rno, dl, name), daemon=True).start()
    time.sleep(90)

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == '--until':
        SUFFIX = '_' + sys.argv[2].replace(':', '')
        run_window(datetime.datetime.now(JST).strftime('%Y%m%d'), sys.argv[2]); sys.exit(0)
    while True:
        now = datetime.datetime.now(JST)
        run_day(now.strftime('%Y%m%d'))
        nxt = (now + datetime.timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        print('次の記録開始:', nxt.strftime('%m/%d %H:%M'), flush=True)
        time.sleep(max(0, (nxt - datetime.datetime.now(JST)).total_seconds()))
