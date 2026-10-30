"""키워드별 월 검색수(네이버 검색광고 키워드도구). 상품 수는 아이템스카우트에서 따로 채운다. 키는 출력하지 않는다.

  python3 keyword_volume.py out.csv kw1 kw2 ...             # 키워드별 월 검색수 ("김치 2kg"처럼 띄어 써도 됨)
  python3 keyword_volume.py --related out.csv hint1 ...     # 연관키워드 전체를 검색수 순으로

키 파일: 이 폴더의 searchad_api_key.env (CUSTOMER_ID, ACCESS_LICENSE, SECRET_KEY). 커밋 금지(.gitignore).
월 검색수 5는 "10 미만"이라는 뜻이다.
"""
import base64, csv, hashlib, hmac, json, sys, time, urllib.parse, urllib.request
from pathlib import Path

KEYDIR = Path(__file__).resolve().parent


def env(name):
    d = {}
    for line in (KEYDIR / name).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def searchad(hints):
    e = env("searchad_api_key.env")
    path = "/keywordstool"
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(e["SECRET_KEY"].encode(), f"{ts}.GET.{path}".encode(), hashlib.sha256).digest()).decode()
    h = {"X-Timestamp": ts, "X-API-KEY": e["ACCESS_LICENSE"], "X-Customer": e["CUSTOMER_ID"], "X-Signature": sig}
    q = urllib.parse.urlencode({"hintKeywords": ",".join(hints), "showDetail": 1})
    return get(f"https://api.searchad.naver.com{path}?{q}", h)["keywordList"]


def num(v):
    return 5 if v == "< 10" else int(v)



def main():
    args = sys.argv[1:]
    related = args[0] == "--related"
    if related:
        args = args[1:]
    out, kws = args[0], args[1:]
    rows = {}
    for i in range(0, len(kws), 5):
        batch = [k.replace(" ", "") for k in kws[i:i + 5]]
        for r in searchad(batch):
            rows[r["relKeyword"].upper()] = r
        time.sleep(0.3)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["키워드", "월검색_PC", "월검색_모바일", "월검색_합", "광고경쟁", "상품수", "상품수/검색"])
        if related:
            for r in sorted(rows.values(), key=lambda r: -(num(r["monthlyPcQcCnt"]) + num(r["monthlyMobileQcCnt"]))):
                pc, mo = num(r["monthlyPcQcCnt"]), num(r["monthlyMobileQcCnt"])
                w.writerow([r["relKeyword"], pc, mo, pc + mo, r["compIdx"], "", ""])
            return
        for k in kws:
            r = rows.get(k.replace(" ", "").upper())
            pc = num(r["monthlyPcQcCnt"]) if r else ""
            mo = num(r["monthlyMobileQcCnt"]) if r else ""
            tot = pc + mo if r else ""
            w.writerow([k, pc, mo, tot, r["compIdx"] if r else "", "", ""])


main()
