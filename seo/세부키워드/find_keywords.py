"""계란·김치 세부키워드 발굴 (NAVER API HUB 검색어트렌드).

  python3 find_keywords.py test      # 키 확인용 1회 호출
  python3 find_keywords.py harvest   # 후보 생성 -> 후보키워드.csv (동료 목록과 겹치는 건 제외)
  python3 find_keywords.py trend     # 사용=Y 후보의 검색지수 -> 월 조회수 추정 -> 세부키워드_결과.csv

제1원칙: 과금 방지. HUB는 현재 한시 무료(종량제 플랫폼)라서
  - 이 프로젝트 자체 월 상한(USAGE_CAP)을 공식 월 한도의 1% 미만으로 두고, 넘으면 호출 전에 멈춘다.
  - 오류 응답(401/403/429 등)이 오면 재시도 없이 즉시 멈춘다.
  - 모든 응답은 cache/ 에 저장해 재실행 시 재호출하지 않는다.
키는 *.env 에서 읽고 출력하지 않는다.
"""
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
EXCLUDE = HERE / "동료_키워드_제외목록.csv"
CANDIDATES = HERE / "후보키워드.csv"
RESULT = HERE / "세부키워드_결과.csv"
HOST = "https://naverapihub.apigw.ntruss.com"

KEY_FILES = {"trend": "api_key.env"}
# 공식 월 한도: 검색어트렌드 50,000 -> 프로젝트 상한은 그 1% 미만
USAGE_CAP = {"trend": 200}

PRODUCTS = {
    "계란": {
        # 동료 목록의 실제 월간 조회수를 기준점으로 써서 검색지수를 조회수로 환산
        "anchor": ("동물복지계란", 1320),
        "check": ("반숙계란", 1690),
        "seeds": """유정란 방사유정란 자연방사유정란 동물복지유정란 무항생제유정란 구운계란 맥반석계란
            반숙란 훈제란 감동란 특란 왕란 대란 목초란 초란 오메가3계란 계란선물세트 계란택배 신선란 청란
            백색란 계란10구 계란15구 계란20구 계란60구 산란일계란 당일산란계란 농장직송계란 해썹계란
            유기농유정란 구운란 날계란 영양란 계란2판 계란3판 갈색계란 구운계란30구 맥반석구운계란
            계란대용량 계란한판가격 난각번호 유정란30구 유정란택배 무항생제계란30구 목초유정란 방목계란
            자유방목계란 케이지프리계란 산지직송계란 농장계란 시골계란 토종란 청계유정란 계란선물
            계란답례품 난각번호1번유정란 동물복지계란30구 계란특란 왕란30구 특란30구 반숙훈제란""".split(),
    },
    "김치": {
        "anchor": ("포기김치10KG", 2620),
        "check": ("맛김치", 3640),
        "seeds": """포기김치 배추김치 총각김치 열무김치 깍두기 파김치 갓김치 묵은지 백김치 겉절이 동치미
            나박김치 오이소박이 김치10KG 생김치 저염김치 김장김치 김치택배 볶음김치 김치선물세트
            묵은지3년 국내산포기김치 열무물김치 알타리김치 석박지 섞박지 고들빼기김치 부추김치
            오이김치 백김치5KG 포기김치5KG 포기김치3KG 국산포기김치 수제김치 김치주문 소포장김치
            저염포기김치 국내산깍두기 국내산총각김치 국내산열무김치 국내산파김치 국내산갓김치
            국내산묵은지 숙성김치 숙성묵은지 전라도묵은지 해남묵은지 묵은지10KG 묵은지5KG 김치세트
            순한김치 안매운백김치 유아김치 갓김치추천 파김치추천 묵은지추천 백김치추천 열무김치추천
            포기김치추천 동치미추천 김장김치주문 김장김치예약 깍두기추천 생김치추천 국산묵은지
            국산깍두기 국산총각김치 국산열무김치 국산파김치 국산갓김치 국산백김치""".split(),
    },
}


def norm(s):
    return re.sub(r"\s+", "", s).lower()


def load_headers(kind):
    env = {}
    for line in (HERE / KEY_FILES[kind]).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    cid, secret = env.get("NAVER_CLIENT_ID"), env.get("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit(f"{KEY_FILES[kind]} 에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 없습니다.")
    return {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}


class Api:
    def __init__(self):
        CACHE.mkdir(exist_ok=True)
        self.usage_path = CACHE / f"usage_{date.today():%Y%m}.json"
        self.usage = json.loads(self.usage_path.read_text()) if self.usage_path.exists() else {"trend": 0}
        self.headers = {}

    def _call(self, kind, url, body=None):
        key = hashlib.sha1((url + json.dumps(body, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()
        path = CACHE / f"{kind}_{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.usage[kind] >= USAGE_CAP[kind]:
            sys.exit(f"[중단] {kind} 이번 달 프로젝트 상한 {USAGE_CAP[kind]}회 도달. 더 호출하지 않음.")
        if kind not in self.headers:
            self.headers[kind] = load_headers(kind)
        headers = dict(self.headers[kind])
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode()
        # 호출 전에 사용량을 먼저 기록 (실패한 호출도 1회로 센다)
        self.usage[kind] += 1
        self.usage_path.write_text(json.dumps(self.usage))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=20) as r:
                res = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            sys.exit(f"[중단] {kind} HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        time.sleep(0.2)
        return res

    def trend(self, keywords, start, end):
        body = {
            "startDate": start, "endDate": end, "timeUnit": "month",
            "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
        }
        return self._call("trend", f"{HOST}/search-trend/v1/search", body)

    def report(self):
        print(f"이번 달 누적 호출 {self.usage} / 프로젝트 상한 {USAGE_CAP}")


def last_12_months():
    end = date.today().replace(day=1) - timedelta(days=1)
    start = (end + timedelta(days=1)).replace(year=end.year - 1)
    return start.isoformat(), end.isoformat()


def grade(v):
    # 강의 기준: 대표 5,000+ / 세부(시작~성장) 1,000~5,000 / 그 아래는 틈새·저조회
    return "대표" if v >= 5000 else "세부" if v >= 1000 else "틈새" if v >= 300 else "저조회"


def load_excluded():
    with EXCLUDE.open(encoding="utf-8-sig") as f:
        return {norm(r["키워드"]) for r in csv.DictReader(f)}


def test():
    api = Api()
    s, e = last_12_months()
    r = api.trend(["계란"], e[:8] + "01", e)
    print("trend OK:", [g["title"] for g in r["results"]])
    api.report()


def harvest():
    excluded = load_excluded()
    rows = []
    for product, cfg in PRODUCTS.items():
        for kw in sorted({norm(s) for s in cfg["seeds"]}):
            dup = kw in excluded
            rows.append({"상품": product, "키워드": kw, "동료목록중복": "Y" if dup else "", "사용": "" if dup else "Y"})
    with CANDIDATES.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}개 후보 (동료 중복 {sum(r['동료목록중복'] == 'Y' for r in rows)}개 제외) -> {CANDIDATES.name}")


def trend():
    api = Api()
    excluded = load_excluded()
    with CANDIDATES.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["사용"].strip().upper() == "Y"]
    start, end = last_12_months()
    last = end[:7]
    out = []
    for product, cfg in PRODUCTS.items():
        anchor, anchor_vol = cfg["anchor"]
        cands = [r["키워드"] for r in rows if r["상품"] == product and norm(r["키워드"]) not in excluded]
        # 검증용: 동료 목록에 조회수가 있는 키워드 1개를 같이 환산해 오차를 본다
        cands = [cfg["check"][0]] + cands
        # 요청마다 비율이 따로 정규화되므로, 기준어를 매번 넣고 기준어 대비로 환산한다
        for i in range(0, len(cands), 4):
            chunk = cands[i:i + 4]
            res = api.trend([anchor] + chunk, start, end)["results"]
            series = {g["title"]: {d["period"][:7]: d["ratio"] for d in g["data"]} for g in res}
            a = series[anchor]
            if not a.get(last):
                sys.exit(f"[중단] 기준어 {anchor} 의 {last} 데이터 없음")
            for kw in chunk:
                s = series.get(kw, {})
                est = anchor_vol * s.get(last, 0) / a[last]
                avg = anchor_vol * (sum(s.values()) / 12) / a[last]
                out.append({
                    "상품": product, "키워드": kw, "구분": grade(est),
                    "추정월조회수(최근월)": round(est), "추정월평균(12개월)": round(avg),
                    "최고검색월": max(s, key=s.get) if s else "",
                    "비고": f"검증용(동료 실측 {cfg['check'][1]})" if kw == cfg["check"][0] else "",
                })
    out.sort(key=lambda r: (r["상품"], r["추정월조회수(최근월)"]))
    with RESULT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)}개 -> {RESULT.name}  (기간 {start} ~ {end}, 기준월 {last})")
    for r in out:
        if r["비고"]:
            print("검증:", r["키워드"], "추정", r["추정월조회수(최근월)"], "/", r["비고"])
    api.report()


if __name__ == "__main__":
    {"test": test, "harvest": harvest, "trend": trend}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
