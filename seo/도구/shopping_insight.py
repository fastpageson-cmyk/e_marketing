"""네이버 데이터랩 쇼핑인사이트(API HUB): 식품 카테고리 안에서 키워드 클릭 추이를 비교하고, 키워드별 연령·성별 비중을 본다. 키는 출력하지 않는다.

  python3 shopping_insight.py 배추김치10kg 포기김치10kg 김치10kg       # 키워드 5개까지, 최근 3개월 월별 상대값
  python3 shopping_insight.py --audience 김치10kg                        # 연령·성별 비중(%)

키 파일: 이 폴더의 shopping_api_key.env (NAVER_CLIENT_ID, NAVER_CLIENT_SECRET = API HUB 쇼핑인사이트 키). 커밋 금지.
상대값은 같은 호출 안의 최댓값을 100으로 둔 값이라 호출끼리는 비교하지 않는다.
"""
import json, sys, urllib.request
from datetime import date, timedelta
from pathlib import Path

HOST = "https://naverapihub.apigw.ntruss.com"
FOOD = "50000006"  # 네이버쇼핑 식품 카테고리


def call(path, body):
    env = {}
    for line in (Path(__file__).resolve().parent / "shopping_api_key.env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    h = {"X-NCP-APIGW-API-KEY-ID": env["NAVER_CLIENT_ID"], "X-NCP-APIGW-API-KEY": env["NAVER_CLIENT_SECRET"],
         "Content-Type": "application/json"}
    req = urllib.request.Request(HOST + path, data=json.dumps(body, ensure_ascii=False).encode(), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def main():
    args = sys.argv[1:]
    end = date.today() - timedelta(days=1)
    base = {"startDate": (end - timedelta(days=90)).replace(day=1).isoformat(), "endDate": end.isoformat(),
            "timeUnit": "month", "category": FOOD}
    if args[0] == "--audience":
        for dim in ("age", "gender"):
            data = call(f"/shopping/v1/category/keyword/{dim}", dict(base, keyword=args[1]))["results"][0]["data"]
            agg = {}
            for d in data:
                agg[d["group"]] = agg.get(d["group"], 0) + d["ratio"]
            total = sum(agg.values())
            print(dim, {k: round(v / total * 100) for k, v in sorted(agg.items())})
        return
    body = dict(base, keyword=[{"name": k, "param": [k]} for k in args[:5]])
    for res in call("/shopping/v1/category/keywords", body)["results"]:
        print(res["title"], [(d["period"][:7], round(d["ratio"], 1)) for d in res["data"]])


main()
