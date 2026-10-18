"""계란·김치 세부키워드 발굴 (NAVER API HUB 검색어트렌드 + 블로그·카페 검색).

  python3 find_keywords.py test      # 키 확인용 1회씩 호출
  python3 find_keywords.py harvest   # 후보 생성 -> 후보키워드.csv (동료 목록과 겹치는 건 제외)
  python3 find_keywords.py mine      # 블로그·카페 글에서 후보 추출 -> 후보키워드.csv 에 사용=? 로 추가 (검토 후 Y/N)
  python3 find_keywords.py volume    # 검색광고 키워드도구로 실측 월 검색수 + 연관키워드 -> 세부키워드_실측.csv, 연관키워드_후보.csv
  python3 find_keywords.py expand N  # 연관키워드 눈덩이 확장 (키워드도구 최대 N회) -> 세부키워드_최종.csv
  python3 find_keywords.py trend     # 사용=Y 후보의 검색지수 -> 월 조회수 추정 -> 세부키워드_결과.csv

제1원칙: 과금 방지. HUB는 현재 한시 무료(종량제 플랫폼)라서
  - 이 프로젝트 자체 월 상한(USAGE_CAP)을 공식 월 한도의 1% 미만으로 두고, 넘으면 호출 전에 멈춘다.
  - 오류 응답(401/403/429 등)이 오면 재시도 없이 즉시 멈춘다.
  - 모든 응답은 cache/ 에 저장해 재실행 시 재호출하지 않는다.
키는 *.env 에서 읽고 출력하지 않는다.
"""
import base64
import csv
import hashlib
import hmac
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
EXCLUDE = HERE / "동료_키워드_제외목록.csv"
CANDIDATES = HERE / "후보키워드.csv"
RESULT = HERE / "세부키워드_결과.csv"
HOST = "https://naverapihub.apigw.ntruss.com"
SEARCHAD_HOST = "https://api.searchad.naver.com"
VOLUME = HERE / "세부키워드_실측.csv"
RELATED = HERE / "연관키워드_후보.csv"
FINAL = HERE / "세부키워드_최종.csv"
MANUAL_EXCLUDE = HERE / "제외_키워드.csv"  # 브랜드·무관 키워드 (직접 검토해 추가)
HINTS_USED = CACHE / "searchad_hints.json"
DETAIL_RANGE = (300, 10000)  # 세부키워드: 월 검색수 300 이상 1만 이하
KIMCHI_TERMS = ("김치", "묵은지", "깍두기", "겉절이", "동치미", "소박이", "섞박지", "석박지")
EGG_TERMS = ("계란", "달걀", "유정란", "무정란", "구운란", "반숙란", "훈제란", "감동란", "청란", "초란", "왕란", "특란",
             "대란", "중란", "백색란", "쌍란", "청계알", "오골계알", "난각", "난백", "난황", "흰자", "노른자", "액란")
NOT_EGG = ("메추리", "명란", "타조", "오리", "거위", "콜덕", "부화", "알바", "알레르기", "알약", "알로에", "알람")
INFO_TERMS = ("만들기", "만드는", "담그기", "담그는", "레시피", "끓이는", "효능", "칼로리", "보관", "삶는", "삶기",
              "하는법", "요리", "볶음밥", "찌개", "찜", "조림", "말이", "후라이", "토스트", "샌드위치", "양념", "황금레시피")

KEY_FILES = {"trend": "api_key.env", "search": "api_key.env"}
# 공식 월 한도: 검색어트렌드 50,000 / 검색 775,000 -> 프로젝트 상한은 그 1% 미만
# 검색광고 API는 키워드도구 조회(GET)만 쓴다. 조회는 무료이고, 광고 생성·수정 요청은 코드에 없다.
USAGE_CAP = {"trend": 200, "search": 300, "searchad": 200}

PRODUCTS = {
    "계란": {
        # 동료 목록의 실제 월간 조회수를 기준점으로 써서 검색지수를 조회수로 환산
        "anchor": ("동물복지계란", 1320),
        "check": ("반숙계란", 1690),
        "bases": ["계란", "달걀", "유정란"],
        "queries": ["계란 추천", "유정란 추천", "계란 구매 후기", "구운계란 후기", "유정란 택배 후기",
                    "달걀 고르는 법", "훈제란 후기", "계란 선물 후기"],
        "seeds": """유정란 방사유정란 자연방사유정란 동물복지유정란 무항생제유정란 구운계란 맥반석계란
            반숙란 훈제란 감동란 특란 왕란 대란 목초란 초란 오메가3계란 계란선물세트 계란택배 신선란 청란
            백색란 계란10구 계란15구 계란20구 계란60구 산란일계란 당일산란계란 농장직송계란 해썹계란
            유기농유정란 구운란 날계란 영양란 계란2판 계란3판 갈색계란 구운계란30구 맥반석구운계란
            계란대용량 계란한판가격 난각번호 유정란30구 유정란택배 무항생제계란30구 목초유정란 방목계란
            자유방목계란 케이지프리계란 산지직송계란 농장계란 시골계란 토종란 청계유정란 계란선물
            계란답례품 난각번호1번유정란 동물복지계란30구 계란특란 왕란30구 특란30구 반숙훈제란
            유정란15구 유정란60구 청란30구 초란30구 훈제란30구 구운란30구 반숙란30구 감동란30구
            맥반석계란30구 동물복지유정란30구 자연방사유정란30구 왕란60구 특란60구 대란30구 대란60구
            중란 중란30구 왕특란 계란90구 계란4판 구운계란60구 구운계란대용량 훈제계란30구 삶은계란
            삶은계란택배 삶은계란30구 계란장조림 수란 온천계란 반숙란택배 구운란택배 훈제란택배
            쌍란 쌍란계란 청계알 오골계란 오골계유정란 홍삼계란 황토계란 DHA계란 셀레늄계란 허브계란
            아기계란 이유식계란 다이어트계란 단백질계란 캠핑계란 명절계란선물 유정란선물세트
            추석계란선물 계란직거래 계란정기구독 계란새벽배송 유정란정기배송 유정란농장 계란도매가격
            계란한판택배 무항생제유정란30구 동물복지계란10구 유정란10구 청란10구 초란15구
            쌍란30구 청계알30구 오골계알 구운란60구 반숙란60구 훈제란60구 구운계란택배 맥반석계란택배
            반숙계란30구 유정란한판 유정란가격 청란가격 초란가격 왕란가격 특란가격 대란가격 계란30구가격
            동물복지계란가격 무항생제계란가격 쌍란가격 맥반석계란가격 구운계란가격 감동란가격 훈제란가격
            반숙란가격 구운란가격 구운계란추천 반숙란추천 유정란추천 계란추천 훈제란추천 감동란추천
            맥반석계란추천 초란추천 청란추천 청계란30구
            오골계알30구 청계알가격 오골계알가격 왕란15구 특란15구 대란15구 왕란10구 특란10구 중란가격
            소란30구 구운란15구 구운란10구 감동란10구 감동란60구 반숙란10구 훈제란10구 훈제란15구
            맥반석구운란 구운계란10구 구운계란15구 반숙훈제계란 촉촉란 반숙구운란 간장계란 마약계란
            계란장 아기달걀 이유식유정란 임산부계란 헬스계란 단백질달걀 무항생제달걀 동물복지달걀
            유기농달걀 달걀30구 달걀한판 달걀가격 달걀택배 달걀선물세트 생달걀 구운달걀 맥반석달걀
            훈제달걀 반숙달걀 삶은달걀 제주유정란 제주계란 강원도유정란 지리산유정란 산청유정란
            하동유정란 유정란선물 계란명절선물 설선물계란
            달걀10구 달걀60구 달걀장 간장달걀 마약달걀 달걀장조림 구운달걀30구 삶은달걀30구 구운달걀택배
            삶은계란가격 백봉오골계알 토종닭계란 토종닭달걀 재래닭계란 시골달걀 무정란 계란등급 1+계란
            1+등급계란 에어프라이어구운계란""".split(),
    },
    "김치": {
        "anchor": ("포기김치10KG", 2620),
        "check": ("맛김치", 3640),
        "bases": ["김치", "묵은지", "깍두기", "겉절이", "동치미", "소박이"],
        "queries": ["김치 추천", "김치 주문 후기", "포기김치 후기", "묵은지 추천", "갓김치 후기",
                    "총각김치 후기", "김치 택배 후기", "김장김치 주문"],
        "seeds": """포기김치 배추김치 총각김치 열무김치 깍두기 파김치 갓김치 묵은지 백김치 겉절이 동치미
            나박김치 오이소박이 김치10KG 생김치 저염김치 김장김치 김치택배 볶음김치 김치선물세트
            묵은지3년 국내산포기김치 열무물김치 알타리김치 석박지 섞박지 고들빼기김치 부추김치
            오이김치 백김치5KG 포기김치5KG 포기김치3KG 국산포기김치 수제김치 김치주문 소포장김치
            저염포기김치 국내산깍두기 국내산총각김치 국내산열무김치 국내산파김치 국내산갓김치
            국내산묵은지 숙성김치 숙성묵은지 전라도묵은지 해남묵은지 묵은지10KG 묵은지5KG 김치세트
            순한김치 안매운백김치 유아김치 갓김치추천 파김치추천 묵은지추천 백김치추천 열무김치추천
            포기김치추천 동치미추천 김장김치주문 김장김치예약 깍두기추천 생김치추천 국산묵은지
            국산깍두기 국산총각김치 국산열무김치 국산파김치 국산갓김치 국산백김치
            포기김치1KG 포기김치2KG 포기김치4KG 배추김치3KG 배추김치10KG 총각김치2KG 총각김치3KG
            열무김치2KG 열무김치5KG 파김치1KG 파김치2KG 갓김치2KG 갓김치3KG 깍두기3KG 깍두기5KG
            백김치2KG 백김치3KG 동치미2KG 묵은지2KG 묵은지3KG 겉절이2KG 겉절이1KG 섞박지2KG 석박지3KG
            전라도갓김치 전라도총각김치 전라도열무김치 전라도깍두기 돌산갓김치 경상도포기김치 충청도김치
            강원도묵은지 황태김치 개성보쌈김치 보쌈김치 통영굴김치 깻잎김치 고구마순김치 얼갈이김치
            쪽파김치 무말랭이김치 돌나물물김치 배추물김치 열무얼갈이김치 미나리김치 고추김치 더덕김치
            콩나물김치 양배추김치 부추겉절이 알배추겉절이 봄동겉절이 봄동김치 배추겉절이 상추겉절이
            자취김치 캠핑김치 도시락김치 라면김치 볶음밥김치 업소용포기김치 업소용깍두기 식당용김치
            해썹김치 저온숙성김치 무설탕김치 젓갈없는김치 새우젓김치 생새우김치 명태김치 낙지김치
            오징어김치 굴보쌈김치 김치선물 명절김치선물 김장김치택배 국산김치택배 김치소포장
            여수돌산갓김치 돌산갓김치2KG 돌산갓김치5KG 해남포기김치 해남배추김치 해남갓김치 해남총각김치
            담양김치 괴산김치 전라도백김치 전라도겉절이 전라도석박지 경상도총각김치 포기김치가격 김치가격
            김치10KG가격 묵은지가격 총각김치가격 갓김치가격 파김치가격 열무김치가격 백김치가격 깍두기가격
            겉절이추천 석박지추천 섞박지추천 나박김치추천 오이소박이추천 볶음김치추천 맛김치추천
            고들빼기김치추천 부추김치추천 오이김치추천 알타리김치추천 김장김치추천 고추김치추천
            배추물김치추천 돌산갓김치추천
            전라도고들빼기김치 순천고들빼기 여수고들빼기김치 여수갓김치 돌산갓김치1KG 돌산파김치 여수파김치
            해남김장김치 진도김치 강진김치 영광김치 나주김치 남도묵은지 지리산묵은지 순창묵은지
            강원도열무김치 평창김치 강릉김치 개성김치 이북식김치 황해도김치 충청도석박지 충청도겉절이
            풋고추김치 고추소박이 오이고추김치 무깍두기 굴깍두기 설렁탕깍두기 국밥깍두기 설렁탕김치
            설렁탕섞박지 얼갈이겉절이 열무겉절이 쪽파겉절이 돌산갓물김치 청갓김치 실파김치 묵은지1KG
            1년묵은지 2년묵은지 3년묵은지 김치찜용묵은지 찌개용묵은지 김치찌개용묵은지 볶음용김치
            동치미국물 동치미무 김장김치가격 김치1KG가격 포기김치10KG가격 유아백김치 저염백김치
            비건포기김치 오신채없는김치 사찰김치 채식김치
            고창김치 부안김치 정읍김치 보성김치 장흥김치 완도김치 고흥김치 함평김치 무안김치 강원도겉절이
            경상도깍두기 경상도묵은지 여수김장김치 여수총각김치 여수묵은지 여수갓김치2KG 여수갓김치3KG
            여수갓김치5KG 여수갓김치택배 오이겉절이 무겉절이 깻잎겉절이 미나리겉절이 참나물겉절이
            양배추겉절이 겉절이택배 겉절이주문 무청김치 배추백김치 무백김치 백김치국물 나박물김치 오이물김치
            오이깍두기 오이부추김치 가지김치 우엉김치 연근김치""".split(),
    },
}


def norm(s):
    return re.sub(r"\s+", "", s).lower()


def load_env(name):
    env = {}
    for line in (HERE / name).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def searchad_headers(path):
    env = load_env("searchad_api_key.env")
    ts = str(int(time.time() * 1000))
    sig = hmac.new(env["SECRET_KEY"].encode(), f"{ts}.GET.{path}".encode(), hashlib.sha256).digest()
    return {"X-Timestamp": ts, "X-API-KEY": env["ACCESS_LICENSE"], "X-Customer": env["CUSTOMER_ID"],
            "X-Signature": base64.b64encode(sig).decode()}


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
        self.usage = json.loads(self.usage_path.read_text()) if self.usage_path.exists() else {}
        for k in USAGE_CAP:
            self.usage.setdefault(k, 0)
        self.headers = {}

    def _call(self, kind, url, body=None):
        key = hashlib.sha1((url + json.dumps(body, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()
        path = CACHE / f"{kind}_{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.usage[kind] >= USAGE_CAP[kind]:
            sys.exit(f"[중단] {kind} 이번 달 프로젝트 상한 {USAGE_CAP[kind]}회 도달. 더 호출하지 않음.")
        if kind == "searchad":
            headers = searchad_headers(urllib.parse.urlparse(url).path)
        else:
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

    def search(self, source, query, display=100):
        q = urllib.parse.urlencode({"query": query, "display": display, "start": 1, "sort": "sim"})
        return self._call("search", f"{HOST}/search/v1/{source}?{q}")

    def keywordstool(self, keywords):
        # 힌트 키워드는 1회 최대 5개, 공백 없이
        q = urllib.parse.urlencode({"hintKeywords": ",".join(keywords), "showDetail": 1})
        return self._call("searchad", f"{SEARCHAD_HOST}/keywordstool?{q}")

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
    r = api.search("blog", "계란", display=1)
    print("search OK: total =", r["total"])
    api.report()


def extract(texts, bases, min_freq=3):
    """글 제목·요약에서 '수식어+기본어' 형태를 뽑는다 (예: '동물복지 계란' -> 동물복지계란, '무항생제유정란')."""
    counts = Counter()
    for t in texts:
        toks = re.findall(r"[0-9A-Za-z가-힣]+", re.sub(r"<[^>]+>|&\w+;", " ", t))
        for i, tok in enumerate(toks):
            for b in bases:
                if tok == b and i > 0 and not toks[i - 1].isdigit() and len(toks[i - 1]) <= 6:
                    counts[toks[i - 1] + b] += 1
                elif b in tok and tok != b and len(tok) <= len(b) + 6:
                    counts[tok] += 1
    return {norm(k): n for k, n in counts.items() if n >= min_freq}


def mine():
    api = Api()
    excluded = load_excluded()
    with CANDIDATES.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0]) + (["언급수"] if "언급수" not in rows[0] else [])
    seen = {(r["상품"], r["키워드"]) for r in rows}
    added = 0
    for product, cfg in PRODUCTS.items():
        texts = []
        for q in cfg["queries"]:
            for source in ("blog", "cafearticle"):
                texts += [it["title"] + " " + it["description"] for it in api.search(source, q)["items"]]
        for kw, n in sorted(extract(texts, cfg["bases"]).items(), key=lambda x: -x[1]):
            if (product, kw) in seen or kw in excluded:
                continue
            rows.append({"상품": product, "키워드": kw, "동료목록중복": "", "사용": "?", "언급수": n})
            added += 1
    with CANDIDATES.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"글에서 새 후보 {added}개 추가 (사용=? -> 검토 후 Y/N) -> {CANDIDATES.name}")
    api.report()


def product_of(kw):
    if any(t in kw for t in KIMCHI_TERMS):
        return "김치"
    if not any(t in kw for t in NOT_EGG) and (any(t in kw for t in EGG_TERMS) or kw.endswith(("란", "알"))):
        return "계란"
    return ""


def nature(kw):
    return "정보성" if any(t in kw for t in INFO_TERMS) else "상업성"


def cached_pool():
    pool = {}
    for path in sorted(CACHE.glob("searchad_*.json")):
        if path == HINTS_USED:
            continue
        for k in json.loads(path.read_text(encoding="utf-8")).get("keywordList", []):
            pool.setdefault(norm(k["relKeyword"]), k)
    return pool


def expand(max_calls):
    api = Api()
    excluded = load_excluded()
    manual = set()
    if MANUAL_EXCLUDE.exists():
        with MANUAL_EXCLUDE.open(encoding="utf-8-sig") as f:
            manual = {norm(r["키워드"]) for r in csv.DictReader(f)}
    used = set(json.loads(HINTS_USED.read_text())) if HINTS_USED.exists() else set()
    pool = cached_pool()

    def total(k):
        return count(k["monthlyPcQcCnt"]) + count(k["monthlyMobileQcCnt"])

    def picks():
        out = {"계란": [], "김치": []}
        for kw, k in pool.items():
            p = product_of(kw)
            if p and kw not in excluded and kw not in manual and DETAIL_RANGE[0] <= total(k) <= DETAIL_RANGE[1]:
                out[p].append(kw)
        return out

    for _ in range(max_calls):
        found = picks()
        # 200개에 덜 찬 상품부터, 아직 힌트로 안 쓴 키워드를 조회수 높은 순으로 5개씩
        # 힌트는 구간 밖(대표어 등)·동료 목록 키워드도 쓴다 (결과에서만 제외)
        hints = {p: sorted((kw for kw, k in pool.items() if product_of(kw) == p and kw not in used
                            and kw not in manual and total(k) >= 100), key=lambda kw: -total(pool[kw]))[:5]
                 for p in found}
        todo = [p for p in found if len(found[p]) < 200 and hints[p]]
        if not todo:
            break
        hints = hints[min(todo, key=lambda p: len(found[p]))]
        used.update(hints)
        HINTS_USED.write_text(json.dumps(sorted(used), ensure_ascii=False))
        for k in api.keywordstool(hints)["keywordList"]:
            pool.setdefault(norm(k["relKeyword"]), k)

    found = picks()
    rows = []
    for p, kws in found.items():
        for kw in kws:
            k = pool[kw]
            rows.append({"상품": p, "키워드": kw, "월검색수": total(k), "PC": count(k["monthlyPcQcCnt"]),
                         "모바일": count(k["monthlyMobileQcCnt"]), "경쟁정도": k["compIdx"], "성격": nature(kw)})
    rows.sort(key=lambda r: (r["상품"], -r["월검색수"]))
    with FINAL.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print({p: len(v) for p, v in found.items()}, "->", FINAL.name)
    api.report()


def count(v):
    # 월 검색수가 10 미만이면 "< 10" 문자열로 온다
    return 5 if isinstance(v, str) else int(v)


def volume():
    api = Api()
    excluded = load_excluded()
    with RESULT.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    targets = [r for r in rows if r["비고"] or 300 <= int(r["추정월조회수(최근월)"]) < 5000]
    known = {norm(r["키워드"]) for r in rows}
    stats = {}
    for i in range(0, len(targets), 5):
        res = api.keywordstool([r["키워드"] for r in targets[i:i + 5]])
        for k in res["keywordList"]:
            stats.setdefault(norm(k["relKeyword"]), k)
    # 연관키워드 발굴용 대표어 힌트
    for hints in (["계란"], ["달걀", "유정란", "구운계란", "감동란", "반숙란"], ["김치", "포기김치", "묵은지", "갓김치", "총각김치"]):
        for k in api.keywordstool(hints)["keywordList"]:
            stats.setdefault(norm(k["relKeyword"]), k)
    out = []
    for r in targets:
        k = stats.get(norm(r["키워드"]))
        pc, mo = (count(k["monthlyPcQcCnt"]), count(k["monthlyMobileQcCnt"])) if k else ("", "")
        real = pc + mo if k else ""
        est = int(r["추정월조회수(최근월)"])
        out.append({"상품": r["상품"], "키워드": r["키워드"], "실측PC": pc, "실측모바일": mo, "실측합계": real,
                    "구분(실측)": grade(real) if k else "", "추정(데이터랩)": est,
                    "추정오차%": round((est - real) / real * 100) if real else "",
                    "경쟁정도": k["compIdx"] if k else "", "비고": r["비고"]})
    with VOLUME.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    # 연관키워드: 계란·김치 관련이고 300~5,000, 기존 후보·동료 목록과 겹치지 않는 것
    kimchi = ("김치", "묵은지", "깍두기", "겉절이", "동치미", "소박이", "섞박지", "석박지")
    rel = []
    for kw, k in stats.items():
        total = count(k["monthlyPcQcCnt"]) + count(k["monthlyMobileQcCnt"])
        if kw in known or kw in excluded or not 300 <= total < 5000:
            continue
        product = ("김치" if any(t in kw for t in kimchi)
                   else "계란" if "계란" in kw or "달걀" in kw or kw.endswith(("란", "알")) else "")
        if product:
            rel.append({"상품": product, "키워드": kw, "실측합계": total, "경쟁정도": k["compIdx"]})
    rel.sort(key=lambda r: (r["상품"], -r["실측합계"]))
    with RELATED.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["상품", "키워드", "실측합계", "경쟁정도"])
        w.writeheader()
        w.writerows(rel)
    print(f"실측 {sum(1 for o in out if o['실측합계'] != '')}/{len(out)}개 -> {VOLUME.name}, 연관 신규 {len(rel)}개 -> {RELATED.name}")
    api.report()


def harvest():
    excluded = load_excluded()
    rows = []
    if CANDIDATES.exists():
        with CANDIDATES.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    seen = {(r["상품"], r["키워드"]) for r in rows}
    for product, cfg in PRODUCTS.items():
        for kw in sorted({norm(s) for s in cfg["seeds"]} - {k for p, k in seen if p == product}):
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
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "expand":
        sys.exit(expand(int(sys.argv[2]) if len(sys.argv) > 2 else 0))
    {"test": test, "harvest": harvest, "mine": mine, "volume": volume, "trend": trend}.get(cmd, lambda: sys.exit(__doc__))()
