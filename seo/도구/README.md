# SEO 도구

## keyword_volume.py: 월 검색수 조회

네이버 검색광고 API의 키워드도구로 월 검색수(PC+모바일)를 한 번에 받는다.

```bash
python3 keyword_volume.py 결과.csv "배추김치 10kg" 김치주문 썰은배추김치
python3 keyword_volume.py --related 연관.csv 포기김치10kg 썰은배추김치
```

- 키: 이 폴더에 `searchad_api_key.env`를 둔다. 형식은 `../세부키워드/find_keywords.py`와 같다(`CUSTOMER_ID`, `ACCESS_LICENSE`, `SECRET_KEY`). `*.env`는 `.gitignore`로 막혀 있으니 절대 커밋하지 않는다.
- 상품 수는 이 스크립트로 받을 수 없다. 아이템스카우트(itemscout.io/keyword)에서 띄어 쓴 키워드로 검색하고, 6~8초 뒤에 읽는다.

## 쇼핑 검색 API 키 진단 (2026-10-30)

`세부키워드/shopping_api_key.env`로 상품 수를 조회하면 401 오류가 난다.

**원인: 키 종류가 다르다.**
- 이 키는 NAVER API HUB(네이버 클라우드) 형식이다. ID가 10자, Secret이 40자다. `api_key.env`(검색어트렌드용)와 형식이 같다.
- 네이버 쇼핑 검색 API(`openapi.naver.com/v1/search/shop.json`)는 네이버 개발자센터 키만 받는다. 그래서 HUB 키를 넣으면 401(`NID AUTH Result Invalid`)이 난다.
- NAVER API HUB 쪽에는 쇼핑 상품 검색 API가 없다. `search/v1/shop`, `search/v1/shopping`, `shopping/v1/search`가 모두 404였다. HUB의 "쇼핑"은 쇼핑인사이트(클릭 트렌드)뿐이다.
- 같은 키로 `search/v1/blog`를 부르면 "이 Application에서 활성화되지 않은 API"(401)가 나온다. 블로그·카페 검색을 쓰려면 HUB 콘솔에서 해당 API를 켜야 한다.

**키를 다시 받아야 하나:** 받아도 쇼핑 검색은 안 된다.
- 공개 MCP 저장소 isnow890/naver-search-mcp의 README에 따르면, 네이버 개발자센터 키는 2026-07-31부터 새로 발급되지 않는다. 이미 발급된 키는 2027-06-30까지 동작한다.
- 팀원 중 예전에 받은 개발자센터 키(Client ID 약 20자, Secret 약 10자)가 있으면 그 키를 `shop.json`에 쓸 수 있다.
- 키가 없으면 상품 수는 지금처럼 아이템스카우트로 본다.

## 쓸 만한 외부 도구

| 도구 | 쓰는 곳 | 메모 |
|---|---|---|
| [isnow890/naver-search-mcp](https://github.com/isnow890/naver-search-mcp) (MIT, ★87) | 쇼핑인사이트: 카테고리·키워드 클릭 트렌드, 성별·연령·기기별 | NAVER API HUB 키로 동작한다. 김치 카테고리의 연령·성별 클릭 비중을 보고 타깃을 잡을 때 쓴다. 쇼핑 상품 검색은 개발자센터 키가 있을 때만 된다. |
| [packative/naver-searchad-mcp](https://github.com/packative/naver-searchad-mcp) (MIT) | 검색광고 키워드도구·성과 | `keyword_volume.py`와 같은 일을 MCP로 한다. 검색광고를 실제로 돌리면 성과 조회에도 쓴다. |
| [NomaDamas/k-skill](https://github.com/NomaDamas/k-skill) (MIT, ★8.2k)의 `naver-ad-performance` | 검색광고 성과 리포트 | 키워드광고를 집행할 때 노출·클릭·CPC·전환을 본다. |
| 같은 저장소의 `naver-blog-research` | 블로그 주제 조사 | 정보성 글(김장시기, 김치보관법) 상위 글을 조사할 때 쓴다. |
| 같은 저장소의 `naver-shopping-search` | 경쟁 상품 가격 비교 | 공개 프록시로 검색 결과를 가져온다. SEO보다는 가격 조사에 맞다. |
| 아이템스카우트 | 상품 수, 경쟁강도 | 로그인이 필요하다. 붙여 쓴 키워드는 집계가 안 되는 경우가 많다. |

- 설치: `npx skills add https://github.com/nomadamas/k-skill --skill naver-blog-research`. 다른 스킬도 `--skill` 뒤 이름만 바꾸면 된다.
- 위 외부 도구들은 README만 확인했고, 코드는 직접 돌려 보지 않았다.
