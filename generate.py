#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카타르·중동 정세 언론 모니터링 (대사관/공관용, 무료·완전자동)
- 갱신 주기(직전 갱신 → 이번 갱신) '창(window)' 안 기사만 수집
- (무료 Gemini) 창 내 기사를 '사안(issue)'별로 자동 묶어: 왼쪽=요약, 오른쪽=관련 기사(카타르/해외/국내)
  * 사안 묶기 실패 시 → '전체 요약 → 기사 나열' 자동 폴백
- 아래에 전체 기사 목록(카타르 필수 / 중동 정세 해외·국내) + 관심 매체 링크
- GitHub Actions가 하루 2회(카타르시간 07:00 / 15:30) 실행 → 커밋/게시 → 공개 URL 자동 갱신

환경변수 GEMINI_API_KEY 필요(무료). 없거나 한도 초과(429) 시 요약만 빠지고 나머지는 정상.
"""

import os
import re
import json
import html
import time
import socket
import calendar
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

# 네트워크 무한 대기 방지: 어떤 소켓 작업도 이 시간을 넘기면 예외 발생(피드/LLM 호출이 걸려도 빌드가 멈추지 않도록).
socket.setdefaulttimeout(90)
FEED_TIMEOUT = 20   # RSS 피드는 응답이 빠르므로 더 짧게 제한

try:
    import feedparser
except ImportError:
    raise SystemExit("feedparser가 필요합니다: pip install feedparser")

# ───────────────────────── CONFIG ─────────────────────────
TITLE = "🇶🇦 카타르·중동 정세 언론 모니터링"
SUBTITLE = ("매일 오전 7:00·오후 3:30(카타르 시간) 자동 갱신 · 카타르·한국·해외 언론 및 국내외 연구기관 보고서 모니터링 · "
            "AI 사안별 요약과 관련 기사 원문 링크 제공")

Q_QATAR_EN = ["Qatar Iran", "Qatar Doha", "Al Udeid", "Ras Laffan Qatar", "Qatar security",
              "QatarEnergy LNG", "Qatar mediation Gaza", "Qatar Airways", "Qatar Emir diplomacy",
              "Qatar attack strike", "Al Udeid base attack", "Qatar airspace missile drone",
              # 카타르 정부의 전쟁 관련 공식 발표·성명·지침 조준
              "Qatar foreign ministry statement Iran", "Qatar Amir statement war",
              "Qatar condemns Iran Israel", "Qatar cabinet Iran war", "QatarEnergy statement force majeure",
              "Qatar government advisory Iran", "Qatar MOFA Iran strike"]
Q_QATAR_KO = ["카타르", "카타르 이란", "카타르 도하", "알우데이드", "카타르 미사일", "카타르 정세", "카타르 교민", "카타르 대사관",
              "카타르 피격", "카타르 공격", "카타르 영공",
              # 카타르 정부 공식 동향(전쟁 관련) 조준
              "카타르 외교부 성명", "카타르 정부 성명 이란", "카타르 국왕 이란", "카타르에너지 성명", "카타르 규탄 이란"]
Q_MIDEAST_EN = ["Middle East Iran Israel", "US Iran strikes", "Strait of Hormuz", "Gulf tensions",
                "Iran Israel war", "Gaza ceasefire", "oil price Middle East", "Red Sea shipping",
                "Iran nuclear talks", "Houthi Red Sea attack", "OPEC oil output", "Israel Iran strike",
                "Hormuz tanker", "Hamas disarm Gaza", "Trump Truth Social Iran", "Trump Truth Social strike Middle East",
                # 아랍·GCC 국가 간 공동성명·정상회의·외교장관 회의 조준
                "GCC summit Iran war", "Gulf Cooperation Council statement Iran", "GCC foreign ministers meeting",
                "Arab League statement Iran Israel", "Arab summit Iran war", "GCC joint statement",
                # CNN이 site:/RSS로 잘 안 잡혀 토픽 쿼리로 보강
                "CNN Iran war", "CNN Israel Iran strike", "CNN Qatar Gulf Middle East", "CNN Hormuz oil Iran"]
Q_MIDEAST_KO = ["중동 정세", "이란 이스라엘", "호르무즈", "걸프 긴장", "이란 미국", "가자 휴전", "국제유가 중동", "트럼프 트루스소셜",
                # 아랍·GCC 공동성명·회의
                "걸프협력회의 성명", "GCC 정상회의", "아랍연맹 성명", "걸프 국가 공동성명", "아랍 정상회의 이란"]
# 네이버 뉴스에서 '카타르'·'중동' 검색 시 노출되는 기사 포함(구글뉴스 site:로 네이버 뉴스 도메인 조준)
Q_NAVER_KO = ["카타르", "중동"]
NAVER_NEWS_DOMAINS = ["n.news.naver.com", "news.naver.com"]
# ── 하단 '링크모음'의 전(全) 언론매체를 매 회차 site: 조준으로 직접 모니터링(내부보고: 링크의 모든 매체 상시 모니터링) ──
# 카타르 현지: Qatar/Middle East 주제와 무관하게도 현지 보도를 폭넓게 확보(관련성 필터가 비관련 제거) → 바로 site:
QATAR_LOCAL_SITES = ["gulf-times.com", "thepeninsulaqatar.com", "dohanews.co",
                     "qatar-tribune.com", "lusailnews.qa", "qna.org.qa", "aljazeera.com"]
# 이란·역내 + 해외(미국·유럽 등) 매체 — 전 세계 보도를 다루므로 '중동 주제'로 조준
FOREIGN_MEDIA_SITES = [
    # 이란·역내
    "tehrantimes.com", "presstv.ir", "irna.ir", "iranintl.com", "english.alarabiya.net",
    "tasnimnews.com", "en.mehrnews.com", "farsnews.ir",
    # 해외(미국·유럽 등)
    "cnn.com", "edition.cnn.com", "reuters.com", "bbc.com", "apnews.com", "theguardian.com", "nytimes.com",
    "bloomberg.com", "wsj.com", "ft.com", "washingtonpost.com", "economist.com",
    "axios.com", "politico.com", "cnbc.com", "al-monitor.com", "middleeasteye.net",
    "timesofisrael.com", "aa.com.tr",
]
# 국내(한국) 종합·방송·경제지 — 국문 '중동 주제'로 조준
KOREA_MEDIA_SITES = [
    "yna.co.kr", "ytn.co.kr", "kbs.co.kr", "imbc.com", "sbs.co.kr", "jtbc.co.kr", "nocutnews.co.kr",
    "chosun.com", "joongang.co.kr", "donga.com", "hani.co.kr", "khan.co.kr",
    "mk.co.kr", "hankyung.com", "fnnews.com", "sedaily.com", "edaily.co.kr",
]
MEDIA_TOPIC = "(Qatar OR Iran OR Israel OR Gaza OR Hormuz OR Gulf)"
MEDIA_TOPIC_KO = "(카타르 OR 중동 OR 이란 OR 이스라엘 OR 호르무즈 OR 걸프 OR 가자)"
# 연구기관·에너지 기관의 중동·유가·카타르 분석/보고서 수집용 쿼리(뜨면 최상단 강조)
Q_REPORTS_KO = ["대외경제정책연구원 중동", "에너지경제연구원 유가", "국제금융센터 중동", "KDI 중동",
                "가스공사 카타르 LNG", "중동 정세 보고서", "중동 리스크 이슈분석", "호르무즈 해협 분석",
                "현대경제연구원 중동", "삼성글로벌리서치 중동 유가", "산업연구원 중동", "중동 리스크 보고서",
                # 한국 기관 보고서 수집 강화(기관명+주제)
                "대외경제정책연구원 유가 전망", "에너지경제연구원 중동 정세", "KDI 국제유가",
                "국제금융센터 중동 리스크", "한국무역협회 중동", "KOTRA 카타르", "코트라 중동 에너지",
                "석유공사 국제유가 전망", "산업연구원 에너지 안보", "국립외교원 중동", "아산정책연구원 중동",
                "세종연구소 중동", "자본시장연구원 유가", "삼정KPMG 에너지", "딜로이트 중동 전망"]
# 해외 연구기관·국제기구 리포트 수집용(영문)
Q_REPORTS_EN = ["IISS Middle East report", "Chatham House Gulf Iran", "CSIS Middle East analysis",
                "Crisis Group Iran Gulf", "IEA oil market report Middle East", "OPEC monthly oil report",
                "Brookings Middle East Iran", "Carnegie Middle East analysis", "Eurasia Group Middle East risk",
                "Strait of Hormuz shipping analysis report", "World Bank Middle East economic outlook",
                "Economist Intelligence Iran Gulf", "Foreign Affairs Iran Middle East",
                "Oxford Economics oil Middle East outlook", "Middle East Council Qatar analysis",
                "한국무역협회 중동 수출", "Doha Institute Gulf study"]

QATAR_KW = ["qatar", "doha", "al udeid", "al-udeid", "udeid", "ras laffan", "hamad",
            "카타르", "도하", "알우데이드", "라스라판", "하마드"]
MIDEAST_KW = ["iran", "iranian", "israel", "israeli", "gulf", "hormuz", "houthi", "yemen",
              "saudi", "bahrain", "kuwait", "oman", "uae", "emirates", "tehran", "gaza",
              "lebanon", "hezbollah", "idf", "middle east", "egypt", "red sea", "suez",
              "이란", "이스라엘", "걸프", "호르무즈", "후티", "예멘", "사우디", "바레인",
              "쿠웨이트", "오만", "중동", "테헤란", "가자", "헤즈볼라", "이집트", "홍해", "수에즈"]

# 핵심(중요) 토픽 키워드 — 이 중 하나라도 걸리면 '중요 기사'로 보고 소형매체라도 무조건 유지.
# (넓게 잡아 '중요기사 누락' 위험을 피함. 매칭되면 유지되는 방향이라 오탐은 안전.)
CORE_KW = [
    "strike", "airstrike", "air strike", "missile", "drone", "attack", "clash", "warplane", "warship", "warfare",
    "killed", "casualt", "wounded", "bomb", "shelling", "explosion", "blast", "ceasefire", "cease-fire", "truce",
    "escalat", "retaliat", "offensive", "assault", "nuclear", "enrich", "uranium", "irgc", "revolutionary guard",
    "hormuz", "strait", "red sea", "suez", "blockade", "tanker", "vessel", "naval", "shipping",
    "crude", "brent", "opec", "lng", "oil price", "gas price", "pipeline", "energy security",
    "sanction", "evacuat", "airspace", "no-fly", "intercept", "patriot", "ballistic", "hostage",
    "al udeid", "al-udeid", "udeid", "doha", "qatar",
    "공습", "미사일", "드론", "공격", "타격", "교전", "전투기", "사망", "부상", "폭발", "폭격", "폭탄", "포격",
    "휴전", "확전", "보복", "공세", "급습", "핵시설", "핵협상", "핵프로그램", "우라늄", "농축", "혁명수비대",
    "호르무즈", "해협", "홍해", "수에즈", "봉쇄", "유조선", "선박", "군함", "함정",
    "원유", "브렌트", "유가", "천연가스", "가스전", "송유관", "엘엔지", "에너지 안보",
    "제재", "대피", "영공", "요격", "탄도", "알우데이드", "인질", "도하",
]

# 취합/비정식/해외발 소스 제외(정식 매체만) — 매체명 기준(구글뉴스 링크 자체는 유지)
BLOCK_SOURCES = ["vietnam", "nate", "네이트", "msn", "yahoo", "bing", "biztoc", "newsbreak",
                 "daum", "다음", "google news", "aggreg", "sina", "coincu", "opoyi", "the eastern herald"]

# 소스 '소재지' 분류 — 카타르 현지 매체(도하 소재/카타르 매체). 알자지라=도하 본사 → 카타르.
QATAR_SOURCES = ["qatar news agency", "qna", "gulf times", "gulf-times", "the peninsula",
                 "peninsula qatar", "peninsulaqatar", "qatar tribune", "qatar-tribune",
                 "doha news", "dohanews", "al jazeera", "aljazeera", "al-jazeera", "lusail"]
# 국내(한국) 매체
KOREA_SOURCES = [
    # 통신사·방송
    "yonhap", "연합", "뉴시스", "newsis", "뉴스1", "news1", "ytn", "kbs", "mbc", "sbs", "jtbc", "연합뉴스tv",
    "노컷", "nocut", "nocutnews",
    # 종합일간지
    "조선", "chosun", "중앙", "joongang", "joins", "동아", "donga",
    "한겨레", "hani", "경향", "khan", "kyunghyang",
    "서울신문", "seoul", "문화일보", "munhwa", "국민일보", "kmib", "세계일보", "segye", "한국일보", "hankookilbo",
    # 경제지
    "매일경제", "매경", "mk.co", "maeil", "한국경제", "hankyung",
    "파이낸셜뉴스", "파이낸셜", "fnnews", "이데일리", "edaily", "머니투데이", "mt.co", "moneytoday",
    "서울경제", "sedaily", "헤럴드경제", "heraldcorp", "아시아경제", "asiae",
]

# 분석·보고서(연구기관·에너지·국책연구원) — 출처가 이들이면 최상단 '분석·보고서' 섹션으로 강조
REPORT_HINTS = [
    # 국책·공공 연구기관
    "대외경제정책연구원", "kiep", "emerics", "이머릭스", "신흥지역정보", "한국개발연구원", "kdi", "에너지경제연구원", "keei",
    "국제금융센터", "kcif", "산업연구원", "kiet", "국립외교원", "ifans",
    "아산정책", "asan", "세종연구소", "sejong", "한국무역협회", "kita", "국제무역통상연구원",
    "가스공사", "kogas", "석유공사", "knoc", "오피넷", "opinet",
    "수출입은행", "koreaexim", "무역보험공사", "ksure", "kotra", "코트라",
    # 민간·금융 연구소
    "현대경제연구원", "hri", "삼성글로벌리서치", "삼성경제연구소", "seri",
    "lg경영연구원", "포스코경영연구원", "posri", "하나금융경영연구소", "하나금융연구소",
    "우리금융경영연구소", "국제금융", "자본시장연구원",
    # 해외 연구기관·국제기구·에너지
    "imf", "국제통화기금", "world bank", "세계은행", "oecd",
    "iea", "international energy agency", "국제에너지기구", "opec", "석유수출국기구",
    "eia", "energy information administration", "미 에너지정보청",
    "iiss", "chatham house", "채텀하우스", "csis", "전략국제문제연구소",
    "brookings", "브루킹스", "carnegie", "카네기", "atlantic council", "애틀랜틱카운슬",
    "rand", "랜드연구소", "crisis group", "국제위기그룹", "middle east institute",
    "council on foreign relations", "eurasia group", "유라시아그룹",
    "rystad", "wood mackenzie", "우드매켄지", "s&p global", "wilson center", "bruegel",
    # 해외 심층분석·경제전망 발간처
    "economist", "이코노미스트", "eiu", "economist intelligence",
    "foreign affairs", "foreign policy", "oxford economics", "capital economics",
    "peterson institute", "piie", "mckinsey global", "맥킨지",
    "rusi", "stratfor", "geopolitical futures", "ispi", "merics", "bruegel",
    # 글로벌 회계·컨설팅펌(심층 산업·에너지·지정학 보고서 발간)
    "kpmg", "삼정", "삼정회계", "pwc", "삼일회계", "삼일pwc", "pricewaterhouse",
    "deloitte", "딜로이트", "안진회계", "ernst & young", "ernst and young", "한영회계", "ey 한영",
    "bcg", "boston consulting", "bain & company", "베인앤컴퍼니", "accenture", "액센츄어",
    "oliver wyman", "올리버와이먼", "roland berger", "롤랜드버거",
    "middle east council", "mecouncil", "gulf research", "걸프연구",
    "al jazeera centre for studies", "aljazeera centre", "doha institute", "브루킹스 도하",
]


# 이란·역내 매체
IRAN_SOURCES = ["tehran times", "press tv", "presstv", "irna", "mehr", "fars", "isna",
                "al-alam", "alalam", "iran international", "iranintl", "tasnim", "kayhan"]

# 해외(미국·유럽·글로벌·역내 기타) 매체 — 제목이 한글이어도(한국어판·번역 제목) 국내가 아닌 '해외'로 분류.
# ※ 짧고 모호한 토큰(ap, rt, dw 단독 등)은 오탐 방지를 위해 쓰지 않고, 구별되는 문자열만 사용.
OVERSEAS_SOURCES = [
    "reuters", "associated press", "ap news", "apnews", "afp", "agence france",
    "bloomberg", "cnn", "bbc", "the guardian", "guardian", "washington post",
    "new york times", "nytimes", "wall street journal", "wsj", "financial times", "ft.com",
    "the economist", "economist", "cnbc", "npr", "politico", "axios", "forbes", "newsweek",
    "al arabiya", "al-arabiya", "alarabiya", "france 24", "france24", "deutsche welle", "dw.com",
    "미국의 소리", "voa korea", "voanews", "자유아시아방송", "rfa", "sputnik", "tass", "rt.com",
    "times of israel", "jerusalem post", "haaretz", "middle east eye", "middle east monitor",
    "the national", "gulf news", "khaleej times", "arab news", "anadolu", "aa.com",
    "news on air", "akashvani", "the hindu", "hindustan times", "times of india", "ndtv",
    "modern ghana", "indexbox", "south china morning post", "scmp", "nikkei", "the diplomat",
    "semafor", "cbs news", "cbsnews", "sbs news", "sbs world", "sbs.com.au", "abc news", "nbc news", "usa today", "al monitor",
    "al-monitor", "middle east institute", "amwaj", "the cradle", "responsible statecraft",
    # 인도·기타 해외 매체(한국 매체 'news1'과의 부분일치 오분류 방지 위해 명시)
    "news18", "network18", "cnn-news18", "firstpost", "wion", "the print", "theprint",
    "indian express", "indianexpress", "india today", "livemint", "moneycontrol", "opindia", "zee news",
]


def source_region(src, korean):
    low = (src or "").lower()
    if any(k in low for k in QATAR_SOURCES):
        return "qatar"
    if any(k in low for k in IRAN_SOURCES):
        return "iran"
    if any(k in low for k in OVERSEAS_SOURCES):   # 해외 매체는 한글 제목이어도 '해외'로(국내 오분류 방지)
        return "overseas"
    if any(k in low for k in KOREA_SOURCES):
        return "korea"
    if korean:                                    # 출처 미상 + 한글 제목이면 국내로 추정
        return "korea"
    return "overseas"

DIRECT_FEEDS = [
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC Middle East", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    # CNN: 전용 중동 피드(edition_meast)는 사실상 폐기 → World 피드로 확보(관련성 필터가 중동·카타르만 통과)
    ("CNN World", "http://rss.cnn.com/rss/cnn_world.rss"),
    ("CNN Middle East", "http://rss.cnn.com/rss/edition_meast.rss"),
    # Doha News: 인스타 중심이라 구글뉴스 색인이 약함 → 워드프레스 RSS로 직접 확보(누락 방지)
    ("Doha News", "https://dohanews.co/feed/"),
    ("Times of Israel", "https://www.timesofisrael.com/feed/"),
    # 이란·역내 1차 정보원 — 구글뉴스가 이란 국영매체를 잘 색인하지 않으므로 직접 RSS로 확보(누락 방지)
    ("Tehran Times", "https://www.tehrantimes.com/rss"),
    ("Press TV", "https://www.presstv.ir/rss.xml"),
    ("Mehr News", "https://en.mehrnews.com/rss"),
    ("IRNA", "https://en.irna.ir/rss"),
    ("Middle East Eye", "https://www.middleeasteye.net/rss"),
]

QUICK_LINKS = {
    "🇶🇦 카타르 현지 매체": [("Qatar News Agency (QNA)", "https://www.qna.org.qa/en"),
        ("Al Jazeera", "https://www.aljazeera.com/news/"),
        ("Gulf Times", "https://www.gulf-times.com/"),
        ("The Peninsula", "https://thepeninsulaqatar.com/"),
        ("Qatar Tribune", "https://www.qatar-tribune.com/"),
        ("Doha News", "https://dohanews.co/"),
        ("Doha News 인스타그램 (@dohanews)", "https://www.instagram.com/dohanews/")],
    "🇮🇷 이란·역내 매체": [("Tehran Times", "https://www.tehrantimes.com/"),
        ("Press TV", "https://www.presstv.ir/"),
        ("IRNA (English)", "https://en.irna.ir/"),
        ("Iran International", "https://www.iranintl.com/en"),
        ("Al Arabiya", "https://english.alarabiya.net/")],
    "🌐 해외(미국·유럽 등) 매체": [("CNN", "https://www.cnn.com/world"),
        ("Reuters — Middle East", "https://www.reuters.com/world/middle-east/"),
        ("BBC — Middle East", "https://www.bbc.com/news/world/middle_east"),
        ("AP — Middle East", "https://apnews.com/hub/middle-east"),
        ("The Guardian — ME", "https://www.theguardian.com/world/middleeast"),
        ("The New York Times — ME", "https://www.nytimes.com/section/world/middleeast"),
        ("Bloomberg", "https://www.bloomberg.com/middleeast"),
        ("The Wall Street Journal", "https://www.wsj.com/world/middle-east"),
        ("Financial Times", "https://www.ft.com/middle-east"),
        ("The Washington Post", "https://www.washingtonpost.com/world/middle-east/"),
        ("The Economist — ME·Africa", "https://www.economist.com/middle-east-and-africa"),
        ("Axios", "https://www.axios.com/world"),
        ("Politico", "https://www.politico.com/"),
        ("Al-Monitor", "https://www.al-monitor.com/"),
        ("Middle East Eye", "https://www.middleeasteye.net/"),
        ("The Times of Israel", "https://www.timesofisrael.com/"),
        ("Anadolu Agency", "https://www.aa.com.tr/en"),
        ("CNBC", "https://www.cnbc.com/world/")],
    "🇰🇷 국내 종합·방송": [("연합뉴스 국제", "https://www.yna.co.kr/international/all"),
        ("YTN", "https://www.ytn.co.kr/"), ("KBS", "https://news.kbs.co.kr/"),
        ("MBC", "https://imnews.imbc.com/"), ("SBS", "https://news.sbs.co.kr/"),
        ("JTBC", "https://news.jtbc.co.kr/"), ("CBS 노컷뉴스", "https://www.nocutnews.co.kr/"),
        ("조선일보", "https://www.chosun.com/"), ("중앙일보", "https://www.joongang.co.kr/"),
        ("동아일보", "https://www.donga.com/"), ("한겨레", "https://www.hani.co.kr/"),
        ("경향신문", "https://www.khan.co.kr/")],
    "🇰🇷 국내 경제지": [("매일경제", "https://www.mk.co.kr/"),
        ("한국경제", "https://www.hankyung.com/"),
        ("파이낸셜뉴스", "https://www.fnnews.com/"),
        ("서울경제", "https://www.sedaily.com/"),
        ("이데일리", "https://www.edaily.co.kr/")],
    "🏛️ 카타르 정부": [("외교부 (MOFA)", "https://mofa.gov.qa/en"),
        ("내무부 (MOI)", "https://www.moi.gov.qa/"),
        ("내무부 공식 X — 보안·긴급 공지", "https://x.com/MOI_QatarEn"),
        ("국방부 (MOD)", "https://www.mod.gov.qa/"),
        ("카타르에너지 (QatarEnergy)", "https://www.qatarenergy.qa/en"),
        ("민간항공청 (CAA)", "https://caa.gov.qa/en/"),
        ("정부 커뮤니케이션실 (GCO)", "https://www.gco.gov.qa/en/")],
    "🏛️ 우리 정부(한국)": [("외교부", "https://www.mofa.go.kr/"),
        ("주카타르대사관", "https://overseas.mofa.go.kr/qa-ko/index.do"),
        ("해외안전여행(0404)", "https://www.0404.go.kr/"),
        ("대통령실", "https://www.president.go.kr/"),
        ("Korea.net", "https://www.korea.net/"),
        ("산업통상부", "https://www.motie.go.kr/"),
        ("국토교통부", "https://www.molit.go.kr/"),
        ("해양수산부", "https://www.mof.go.kr/"),
        ("국방부", "https://www.mnd.go.kr/")],
    "🏛️ 주요국 정부(미·이스라엘·이란 등)": [
        ("美 백악관", "https://www.whitehouse.gov/"),
        ("트럼프 Truth Social (@realDonaldTrump)", "https://truthsocial.com/@realDonaldTrump"),
        ("美 국무부", "https://www.state.gov/"),
        ("美 국방부(펜타곤)", "https://www.defense.gov/"),
        ("美 에너지부(EIA)", "https://www.energy.gov/"),
        ("이스라엘 외교부", "https://www.gov.il/en/departments/ministry_of_foreign_affairs/govil-landing-page"),
        ("이스라엘 총리실(PMO)", "https://www.gov.il/en/departments/pmo/govil-landing-page"),
        ("이스라엘 국방부(IDF)", "https://www.idf.il/en/"),
        ("이란 외교부", "https://en.mfa.gov.ir/"),
        ("이란 대통령실", "https://president.ir/en"),
        ("사우디 외교부", "https://www.mofa.gov.sa/en/"),
        ("UAE 외교부", "https://www.mofa.gov.ae/en"),
        ("UN 안전보장이사회", "https://www.un.org/securitycouncil/")],
    "📑 국내 연구기관": [("대외경제정책연구원(KIEP)", "https://www.kiep.go.kr/"),
        ("신흥지역정보 종합지식포털(EMERiCs)", "https://www.emerics.org:446/index.do"),
        ("KDI 한국개발연구원", "https://www.kdi.re.kr/"),
        ("에너지경제연구원(KEEI)", "https://www.keei.re.kr/"),
        ("국제금융센터(KCIF)", "https://www.kcif.or.kr/"),
        ("산업연구원(KIET)", "https://www.kiet.re.kr/"),
        ("한국가스공사(KOGAS)", "https://www.kogas.or.kr/"),
        ("한국석유공사 오피넷(유가)", "https://www.opinet.co.kr/"),
        ("KOTRA 해외시장뉴스", "https://dream.kotra.or.kr/"),
        ("KOTRA 도하무역관", "https://www.kotra.or.kr/doha"),
        ("현대경제연구원(HRI)", "http://www.hri.co.kr/"),
        ("삼성글로벌리서치(SGR)", "https://www.samsungsgr.com/"),
        ("LG경영연구원", "https://www.lgbr.co.kr/"),
        ("포스코경영연구원(POSRI)", "https://www.posri.re.kr/"),
        ("하나금융경영연구소", "https://www.hanaif.re.kr/"),
        ("한국무역협회(KITA)", "https://www.kita.net/"),
        ("무역협회 국제무역통상연구원", "https://iit.kita.net/"),
        ("자본시장연구원(KCMI)", "https://www.kcmi.re.kr/"),
        ("국립외교원(IFANS)", "https://www.ifans.go.kr/"),
        ("아산정책연구원", "https://www.asaninst.org/"),
        ("세종연구소", "https://www.sejong.org/")],
    "🌐 해외 연구기관": [("IEA 국제에너지기구", "https://www.iea.org/"),
        ("OPEC", "https://www.opec.org/"),
        ("美 EIA 에너지정보청", "https://www.eia.gov/"),
        ("IMF", "https://www.imf.org/"),
        ("World Bank", "https://www.worldbank.org/"),
        ("IISS", "https://www.iiss.org/"),
        ("Chatham House", "https://www.chathamhouse.org/"),
        ("CSIS", "https://www.csis.org/"),
        ("Brookings", "https://www.brookings.edu/"),
        ("Carnegie", "https://carnegieendowment.org/"),
        ("Atlantic Council", "https://www.atlanticcouncil.org/"),
        ("Council on Foreign Relations (CFR)", "https://www.cfr.org/"),
        ("Int'l Crisis Group", "https://www.crisisgroup.org/"),
        ("Middle East Institute", "https://www.mei.edu/"),
        ("Middle East Council(도하)", "https://mecouncil.org/"),
        ("Al Jazeera Centre for Studies", "https://studies.aljazeera.net/en"),
        ("Eurasia Group", "https://www.eurasiagroup.net/"),
        ("The Economist — ME·Africa", "https://www.economist.com/middle-east-and-africa"),
        ("Economist Intelligence(EIU)", "https://www.eiu.com/"),
        ("Foreign Affairs — ME", "https://www.foreignaffairs.com/middle-east"),
        ("Foreign Policy", "https://foreignpolicy.com/"),
        ("Oxford Economics", "https://www.oxfordeconomics.com/"),
        ("Peterson Institute(PIIE)", "https://www.piie.com/"),
        ("RUSI", "https://www.rusi.org/"),
        ("S&P Global Commodity Insights", "https://www.spglobal.com/commodityinsights/")],
}

# 바로가기 대분류: 언론 매체 / 정부 / 유관기관·연구소 (각 아래에 세부 그룹 배치)
QUICK_SECTIONS = [
    ("📰 언론 매체", ["🇶🇦 카타르 현지 매체", "🇮🇷 이란·역내 매체", "🌐 해외(미국·유럽 등) 매체",
                   "🇰🇷 국내 종합·방송", "🇰🇷 국내 경제지"]),
    ("🏛️ 정부", ["🏛️ 카타르 정부", "🏛️ 우리 정부(한국)", "🏛️ 주요국 정부(미·이스라엘·이란 등)"]),
    ("📑 유관기관·연구소", ["📑 국내 연구기관", "🌐 해외 연구기관"]),
]

# ───────────── 다국어(i18n): 한국어(기본)·영어·아랍어 ─────────────
LANGS = ["ko", "en", "ar"]
LANG_NAME = {"ko": "한국어", "en": "English", "ar": "العربية"}

QSEC_I18N = {
    "📰 언론 매체": {"en": "📰 Media", "ar": "📰 وسائل الإعلام"},
    "🏛️ 정부": {"en": "🏛️ Government", "ar": "🏛️ الجهات الحكومية"},
    "📑 유관기관·연구소": {"en": "📑 Institutions & Research", "ar": "📑 المؤسسات ومراكز الأبحاث"},
}
QGROUP_I18N = {
    "🇶🇦 카타르 현지 매체": {"en": "🇶🇦 Qatar local media", "ar": "🇶🇦 وسائل إعلام قطرية"},
    "🇮🇷 이란·역내 매체": {"en": "🇮🇷 Iran & regional media", "ar": "🇮🇷 إعلام إيراني وإقليمي"},
    "🌐 해외(미국·유럽 등) 매체": {"en": "🌐 Global media (US·Europe)", "ar": "🌐 إعلام دولي (أمريكا·أوروبا)"},
    "🇰🇷 국내 종합·방송": {"en": "🇰🇷 Korea — general & broadcast", "ar": "🇰🇷 كوريا — عام وبث"},
    "🇰🇷 국내 경제지": {"en": "🇰🇷 Korea — business press", "ar": "🇰🇷 كوريا — صحافة اقتصادية"},
    "🏛️ 카타르 정부": {"en": "🏛️ Qatar government", "ar": "🏛️ حكومة قطر"},
    "🏛️ 우리 정부(한국)": {"en": "🏛️ Korean government", "ar": "🏛️ الحكومة الكورية"},
    "🏛️ 주요국 정부(미·이스라엘·이란 등)": {"en": "🏛️ Key governments (US·Israel·Iran, etc.)", "ar": "🏛️ حكومات رئيسية (الولايات المتحدة·إسرائيل·إيران، إلخ)"},
    "📑 국내 연구기관": {"en": "📑 Korean research institutes", "ar": "📑 معاهد بحثية كورية"},
    "🌐 해외 연구기관": {"en": "🌐 Global research institutes", "ar": "🌐 معاهد بحثية دولية"},
}

LANG = {
 "ko": {
  "dir": "ltr", "html": "ko",
  "title": "카타르·중동 정세 일간·주간 언론 모니터링", "title2": "Qatar & Middle East — Daily·Weekly Media Monitor",
  "subtitle": ("매일 두 차례(카타르 시각 07:00, 15:30), 카타르·이란·기타 주요 국가·한국 주요 언론 보도를 취합하여 "
               "이슈별 AI 요약과 원문 링크를 제공합니다. 유관기관 최신 보고서 목록도 하단에서 참고하실 수 있으며, "
               "매주 일요일에는 전 주를 종합한 주간 리포트가 함께 발행됩니다. [주카타르대사관 Commercial Section · 도하무역관]"),
  "updated": "모니터링 일시", "tz": "카타르시간", "coverage": "모니터링 기간",
  "two_wk": "(주간)", "two_dl": "(일간)", "wk_range": "지난주 일 07:00 ~ 당일 07:00",
  "win_am": "전일 15:30 ~ 당일 07:00", "win_pm": "당일 07:00 ~ 당일 15:30", "win_pre": "전일 07:00 ~ 전일 15:30",
  "counts": "카타르 <b>{q}</b>건 · 중동 정세 <b>{me}</b>건", "counts_label": "모니터링 건수",
  "scope": ("<b>모니터링 부문</b> — 카타르와 관련된 중동 정세를 전쟁·군사, 외교·중재, 에너지·유가·LNG, "
            "물류·해상안전(호르무즈·홍해), 경제·통상, 항공·교민 등 위주로 정리"),
  "arch_view": "🗂️ 지난 회차 보기:", "arch_latest": "이번 회차 (최신)", "arch_daily": "지난 회차", "arch_weekly": "주간 종합", "sel_d": "일간", "sel_w": "주간", "sister": "✈️ 항공 모니터링",
  "search_ph": "키워드로 요약·기사·매체 필터 (예: LNG, 호르무즈, 유가)",
  "search_hint": ("※ 이 페이지에 표시된 <b>뉴스 제목·요약문·매체명</b>에서 검색어가 보이는 항목만 남기는 방식입니다"
                  "(기사 원문 전체나 지난 회차는 검색 대상이 아니며, 지난 회차는 위 콤보박스로 열어 검색)."),
  "search_count": "건 표시",
  "sum_head": "🧭 이번 회차 이슈별 요약", "sum_head_today": "🧭 오늘 일일 이슈별 요약", "sum_head_flat": "🧭 이번 회차 핵심 요약", "ai": "AI 자동요약",
  "sum_none_body": "요약 일시 미생성 — 다음 갱신에 자동 재시도됩니다. 아래 기사 목록은 정상입니다.", "diag": "진단",
  "issue": "이슈", "key_sum": "핵심 요약", "key_fig": "핵심 수치", "nomap": "관련 링크 매핑 없음",
  "qbox": "카타르 영향·피해", "links_fold": "🔗 이 이슈 관련 보도·링크 펼쳐보기",
  "g_qatar": "🇶🇦 카타르 현지", "g_iran": "🇮🇷 이란·역내", "g_over": "🌐 해외(미국·유럽 등)", "g_korea": "🇰🇷 국내(한국)",
  "flag": "카타르",
  "full_summary": "전체 기사 목록 (총 {n}건)", "full_note": "(카타르·이란·해외·한국)", "expand": "펼쳐보기", "collapse": "접기",
  "col_qatar": "🇶🇦 카타르", "col_iran": "🇮🇷 이란·역내", "col_over": "🌐 해외(미국·유럽 등)", "col_korea": "🇰🇷 국내(한국)",
  "dl_label": "다운로드", "dl_xlsx": "⬇ 엑셀", "dl_docx": "⬇ 워드", "x_s1": "이슈별 요약", "x_s2": "기사 목록", "x_no": "번호", "x_issue": "이슈", "x_sum": "요약", "x_media": "매체", "x_art": "기사 제목", "x_dt": "보도일시", "w_media": "발췌 매체", "mon_fname": "언론모니터링", "w_sumhead": "이슈별 요약",
  "empty_q": "이번 창(window)에 카타르 직접 관련 신규 기사 없음", "empty_over": "이번 창에 해외 신규 기사 없음",
  "empty_iran": "이번 창에 이란·역내 매체 신규 기사 없음", "empty_korea": "이번 창에 국내 신규 기사 없음",
  "rep_head": "중동 정세 심층 분석·보고서", "rep_note": "(국내외 연구기관 등)", "rep_badge": "최신순", "rep_new": "이번 회차 신규",
  "t_qatar": "카타르", "t_iran": "이란", "t_over": "해외", "t_korea": "국내",
  "wk_head": "🗓️ 지난주 언론동향", "wk_open": "주간 리포트 단독 페이지로 열기 →", "wk_none": "주간 요약 미생성 — 다음 갱신에 재시도됩니다.",
  "quick_head": "언론매체·정부·기관 링크모음", "quick_note": "(가나다·알파벳순)",
  "tl_head": "중동 전쟁 타임라인 (2026)", "tl_note": "2026. 2. 28. 발발 이후 주요 사건 · 최신순 · 공신력 있는 공개 보도를 교차 확인해 정리, 새 사건마다 갱신", "tl_q": "카타르",
  "tl_tag": "참고", "tl_back": "← 모니터로 돌아가기", "tl_src_label": "출처", "tl_src_note": "2026. 2. 28. 발발 이후 주요 사건을 최신순으로 정리하며, 새 사건이 생길 때마다 갱신합니다. 위 공신력 있는 공개 출처를 교차 확인해 작성했으며, 세부 수치·표현은 각 매체·1차 발표 확인을 권장합니다.",
  "tl_all": "전체", "tl_qonly": "카타르만", "tl_qex": "카타르 제외", "tl_dl": "⬇ 엑셀 다운로드", "tl_c_date": "날짜", "tl_c_cat": "구분", "tl_c_event": "사건", "tl_c_detail": "상세", "tl_cat_gen": "일반", "tl_fname": "중동전쟁_타임라인", "tl_sheet": "타임라인",
  "gov_head": "🏛️ 전쟁 관련 카타르 정부 동향", "gov_none": "이번 모니터링 기간 중 특이사항 없음",
  "foot": ("본 페이지는 카타르·이란·기타 주요 국가 및 한국의 공개 언론 보도와 유관기관 자료를 자동으로 수집·요약합니다. "
           "뉴스는 Google 뉴스 RSS 피드와 네이버 뉴스 검색, 알자지라·BBC 등 매체 RSS를 카타르·중동·에너지 등 키워드로 조회해 모으고, "
           "심층 보고서는 국내외 연구기관·국제기구 등 발행처 도메인을 직접 조준해 수집합니다. "
           "수집·요약은 각 매체가 공개한 제목과 요약 발췌(스니펫)를 근거로 하며, 유료 구독·멤버십 매체의 기사 전문은 제공된 원문 링크를 통해 독자께서 해당 매체에 직접 로그인·구독하셔야 열람하실 수 있습니다. "
           "수집된 기사는 Anthropic Claude(Sonnet 5) AI가 이슈별로 자동 분류·요약하고 영어·아랍어로 번역하며, "
           "전 과정은 GitHub Actions로 하루 두 번(카타르 시각 07:00·15:30) 자동 실행·게시됩니다. "
           "자동 수집 특성상 일부 기사·보고서들이 누락될 수 있사오니, 중요한 이슈는 각 원문과 추가 검색을 통해 재확인하시기 바랍니다."),
  "sign": "- 주카타르대사관 Commercial Section · 도하무역관", "org": "주카타르대사관 Commercial Section · 도하무역관",
  "ago_min": "{n}분 전", "ago_hr": "{n}시간 전", "ago_day": "{n}일 전",
  "daily_no": "일간 제{n}호", "weekly_no": "주간 제{n}호", "daily_demo": "일간(시범)", "ed_daily": "일간", "ed_weekly": "주간",
  "no_only": "제{n}호", "wk_incl": " (주간)", "wdays": ["월","화","수","목","금","토","일"],
 },
 "en": {
  "dir": "ltr", "html": "en",
  "title": "Qatar & Middle East — Daily·Weekly Media Monitor", "title2": "",
  "subtitle": ("Twice a day (07:00 and 15:30 Qatar time), major coverage from Qatari, Iranian, other major countries' and Korean outlets "
               "is compiled into AI issue summaries with source links. A list of the latest reports from relevant institutions is also "
               "available for reference lower on the page, and every Sunday a weekly report recapping the past week is published. "
               "[Commercial Section, Embassy of the Republic of Korea in Qatar · KOTRA Doha]"),
  "updated": "Monitored at", "tz": "Qatar time", "coverage": "Monitoring period",
  "two_wk": "(Weekly)", "two_dl": "(Daily)", "wk_range": "Last Sunday 07:00 ~ today 07:00",
  "win_am": "Prev day 15:30 – same day 07:00", "win_pm": "Same day 07:00 – 15:30", "win_pre": "Prev day 07:00 – 15:30",
  "counts": "Qatar <b>{q}</b> · Middle East <b>{me}</b>", "counts_label": "Monitored items",
  "scope": ("<b>Coverage focus</b> — Qatar-related Middle East developments in war &amp; military, "
            "diplomacy &amp; mediation, energy·oil·LNG, logistics &amp; maritime security (Hormuz/Red Sea), "
            "economy &amp; trade, aviation·citizens, etc."),
  "arch_view": "🗂️ Past editions:", "arch_latest": "Current edition (latest)", "arch_daily": "Daily", "arch_weekly": "Weekly", "sel_d": "Daily", "sel_w": "Weekly", "sister": "✈️ Flight monitor",
  "search_ph": "Filter summaries · articles · outlets (e.g. LNG, Hormuz, oil)",
  "search_hint": ("※ Filters items on this page whose <b>headline, summary or outlet name</b> contains your keyword "
                  "(full article text and past editions are not searched; open a past edition from the selector above to search it)."),
  "search_count": " shown",
  "sum_head": "🧭 This edition — issue briefs", "sum_head_today": "🧭 Today — daily issue briefs", "sum_head_flat": "🧭 This edition — key summary", "ai": "AI summary",
  "sum_none_body": "Summary not generated this time — it will retry on the next update. The article lists below are fine.", "diag": "Diagnostics",
  "issue": "Issue", "key_sum": "Key summary", "key_fig": "Key figures", "nomap": "No linked articles mapped",
  "qbox": "Impact on Qatar", "links_fold": "🔗 Show related articles for this issue",
  "g_qatar": "🇶🇦 Qatar (local)", "g_iran": "🇮🇷 Iran & regional", "g_over": "🌐 Global (US·Europe)", "g_korea": "🇰🇷 Korea",
  "flag": "Qatar",
  "full_summary": "Full article list (total {n})", "full_note": "(Qatar·Iran·Global·Korea)", "expand": "Expand", "collapse": "Collapse",
  "col_qatar": "🇶🇦 Qatar", "col_iran": "🇮🇷 Iran & regional", "col_over": "🌐 Global (US·Europe)", "col_korea": "🇰🇷 Korea",
  "dl_label": "Download", "dl_xlsx": "⬇ Excel", "dl_docx": "⬇ Word", "x_s1": "Issue summaries", "x_s2": "Article list", "x_no": "No.", "x_issue": "Issue", "x_sum": "Summary", "x_media": "Outlet", "x_art": "Article", "x_dt": "Published", "w_media": "Cited outlets", "mon_fname": "media_monitor", "w_sumhead": "Issue summaries",
  "empty_q": "No new Qatar-related articles in this window", "empty_over": "No new global articles in this window",
  "empty_iran": "No new Iran/regional articles in this window", "empty_korea": "No new Korean articles in this window",
  "rep_head": "Middle East — in-depth analysis & reports", "rep_note": "(Research institutes, etc.)", "rep_badge": "Newest", "rep_new": "New this edition",
  "t_qatar": "Qatar", "t_iran": "Iran", "t_over": "Global", "t_korea": "Korea",
  "wk_head": "🗓️ Last week — media trends", "wk_open": "Open the weekly report as a standalone page →", "wk_none": "Weekly summary not generated — will retry next update.",
  "quick_head": "Media · Government · Institutions — links", "quick_note": "(sorted alphabetically)",
  "tl_head": "Middle East War Timeline (2026)", "tl_note": "Key events since the Feb 28, 2026 outbreak · newest first · cross-checked against credible public reporting, updated as events occur", "tl_q": "Qatar",
  "tl_tag": "Ref", "tl_back": "← Back to the monitor", "tl_src_label": "Sources", "tl_src_note": "Key events since the Feb 28, 2026 outbreak, newest first, updated as new events occur. Compiled by cross-checking the credible public sources above; please verify specific figures and wording against each outlet and primary announcements.",
  "tl_all": "All", "tl_qonly": "Qatar only", "tl_qex": "Exclude Qatar", "tl_dl": "⬇ Download Excel", "tl_c_date": "Date", "tl_c_cat": "Category", "tl_c_event": "Event", "tl_c_detail": "Details", "tl_cat_gen": "General", "tl_fname": "MiddleEast_War_Timeline", "tl_sheet": "Timeline",
  "gov_head": "🏛️ War-related Qatar government activity", "gov_none": "No notable developments during this monitoring window.",
  "foot": ("This page automatically collects and summarizes public news coverage and material from relevant institutions "
           "across Qatar, Iran, other major countries and Korea. News is gathered by querying Google News RSS feeds, Naver News search, "
           "and outlet RSS (Al Jazeera, BBC, etc.) with keywords such as Qatar, the Middle East and energy; in-depth reports "
           "are collected by directly targeting the publishing domains of domestic and international research institutes, "
           "international organizations, etc. Collection and summarization rely on each outlet's publicly available headline and snippet; "
           "for subscription or paywalled outlets, the full article can be opened through the provided source link only after the reader signs in or subscribes to that outlet directly. "
           "The collected articles are automatically clustered and summarized by issue, "
           "and translated into English and Arabic, by Anthropic Claude (Sonnet 5) AI. The whole process runs and publishes automatically "
           "twice a day (07:00 and 15:30 Qatar time) via GitHub Actions. Owing to automated collection some articles or reports may be missed, "
           "so please re-verify important issues against the original sources and further searches."),
  "sign": "- Embassy of the Republic of Korea in Qatar, Commercial Section · KOTRA Doha", "org": "Embassy of the Republic of Korea in Qatar, Commercial Section · KOTRA Doha",
  "ago_min": "{n}m ago", "ago_hr": "{n}h ago", "ago_day": "{n}d ago",
  "daily_no": "Daily No.{n}", "weekly_no": "Weekly No.{n}", "daily_demo": "Daily (preview)", "ed_daily": "Daily", "ed_weekly": "Weekly",
  "no_only": "No.{n}", "wk_incl": " (+wk)", "wdays": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
 },
 "ar": {
  "dir": "rtl", "html": "ar",
  "title": "رصد الإعلام اليومي والأسبوعي: قطر والشرق الأوسط", "title2": "",
  "subtitle": ("مرّتين يوميًا (07:00 و15:30 بتوقيت قطر) تُجمَّع أبرز تقارير الإعلام القطري والإيراني وسائر الدول الرئيسية والكوري في "
               "ملخصات بالذكاء الاصطناعي حسب القضية مع روابط المصادر. كما تتوفر قائمة بأحدث تقارير المؤسسات المعنية للاطلاع في أسفل الصفحة، "
               "ويصدر كل أحد تقرير أسبوعي يلخّص الأسبوع المنصرم. [القسم التجاري، سفارة جمهورية كوريا لدى قطر · كوترا الدوحة]"),
  "updated": "وقت الرصد", "tz": "بتوقيت قطر", "coverage": "فترة الرصد",
  "two_wk": "(أسبوعي)", "two_dl": "(يومي)", "wk_range": "الأحد الماضي 07:00 ~ اليوم 07:00",
  "win_am": "الأمس 15:30 – اليوم 07:00", "win_pm": "اليوم 07:00 – 15:30", "win_pre": "الأمس 07:00 – 15:30",
  "counts": "قطر <b>{q}</b> · الشرق الأوسط <b>{me}</b>", "counts_label": "عدد المرصود",
  "scope": ("<b>مجالات الرصد</b> — تطورات الشرق الأوسط المتعلقة بقطر في الحرب والعسكر، "
            "الدبلوماسية والوساطة، الطاقة والنفط وLNG، اللوجستيات والأمن البحري (هرمز/البحر الأحمر)، "
            "الاقتصاد والتجارة، والطيران والمواطنين، إلخ."),
  "arch_view": "🗂️ الإصدارات السابقة:", "arch_latest": "الإصدار الحالي (الأحدث)", "arch_daily": "يومي", "arch_weekly": "أسبوعي", "sel_d": "يومي", "sel_w": "أسبوعي", "sister": "✈️ رصد الطيران",
  "search_ph": "تصفية الملخصات · الأخبار · المصادر (مثال: LNG، هرمز، النفط)",
  "search_hint": ("※ تُظهر فقط العناصر التي تحتوي كلمتك في <b>العنوان أو الملخص أو اسم المصدر</b> على هذه الصفحة "
                  "(لا يشمل البحث النص الكامل للمقالات ولا الإصدارات السابقة؛ افتح إصدارًا سابقًا من القائمة أعلاه للبحث فيه)."),
  "search_count": " ظاهر",
  "sum_head": "🧭 هذا الإصدار — ملخص القضايا", "sum_head_today": "🧭 اليوم — ملخص القضايا اليومي", "sum_head_flat": "🧭 هذا الإصدار — الملخص الرئيسي", "ai": "ملخص آلي",
  "sum_none_body": "لم يُنشأ الملخص هذه المرة — ستُعاد المحاولة في التحديث التالي. قوائم الأخبار أدناه سليمة.", "diag": "تشخيص",
  "issue": "قضية", "key_sum": "الملخص الرئيسي", "key_fig": "أرقام رئيسية", "nomap": "لا مقالات مرتبطة",
  "qbox": "الأثر على قطر", "links_fold": "🔗 عرض الأخبار والروابط المتعلقة بهذه القضية",
  "g_qatar": "🇶🇦 قطر (محلي)", "g_iran": "🇮🇷 إيران والإقليم", "g_over": "🌐 دولي (أمريكا·أوروبا)", "g_korea": "🇰🇷 كوريا",
  "flag": "قطر",
  "full_summary": "قائمة الأخبار الكاملة (الإجمالي {n})", "full_note": "(قطر·إيران·دولي·كوريا)", "expand": "توسيع", "collapse": "طيّ",
  "col_qatar": "🇶🇦 قطر", "col_iran": "🇮🇷 إيران والإقليم", "col_over": "🌐 دولي (أمريكا·أوروبا)", "col_korea": "🇰🇷 كوريا",
  "dl_label": "تنزيل", "dl_xlsx": "⬇ Excel", "dl_docx": "⬇ Word", "x_s1": "ملخصات القضايا", "x_s2": "قائمة المقالات", "x_no": "الرقم", "x_issue": "القضية", "x_sum": "الملخص", "x_media": "الوسيلة", "x_art": "المقال", "x_dt": "تاريخ النشر", "w_media": "الوسائل", "mon_fname": "rasd_iaalam", "w_sumhead": "ملخصات القضايا",
  "empty_q": "لا مقالات جديدة متعلقة بقطر في هذه الفترة", "empty_over": "لا مقالات دولية جديدة في هذه الفترة",
  "empty_iran": "لا مقالات إيرانية/إقليمية جديدة في هذه الفترة", "empty_korea": "لا مقالات كورية جديدة في هذه الفترة",
  "rep_head": "الشرق الأوسط — تحليلات وتقارير معمّقة", "rep_note": "(مراكز الأبحاث وغيرها)", "rep_badge": "الأحدث", "rep_new": "جديد بهذا الإصدار",
  "t_qatar": "قطر", "t_iran": "إيران", "t_over": "دولي", "t_korea": "كوريا",
  "wk_head": "🗓️ الأسبوع الماضي — اتجاهات الإعلام", "wk_open": "افتح التقرير الأسبوعي كصفحة مستقلة →", "wk_none": "لم يُنشأ الموجز الأسبوعي — ستُعاد المحاولة في التحديث التالي.",
  "quick_head": "روابط الإعلام والحكومة والمؤسسات", "quick_note": "(مرتّبة أبجديًا)",
  "tl_head": "الجدول الزمني لحرب الشرق الأوسط (2026)", "tl_note": "أبرز الأحداث منذ اندلاع الحرب في 28 فبراير 2026 · الأحدث أولاً · جُمِعت بالتحقّق المتقاطع من تقارير عامة موثوقة، وتُحدَّث مع كل حدث جديد", "tl_q": "قطر",
  "tl_tag": "مرجع", "tl_back": "← العودة إلى الراصد", "tl_src_label": "المصادر", "tl_src_note": "أبرز الأحداث منذ اندلاع الحرب في 28 فبراير 2026، الأحدث أولاً، وتُحدَّث مع كل حدث جديد. جُمِعت بالتحقّق المتقاطع من المصادر العامة الموثوقة أعلاه؛ ويُرجى التحقّق من الأرقام والصياغة الدقيقة لدى كل مصدر والإعلانات الأولية.",
  "tl_all": "الكل", "tl_qonly": "قطر فقط", "tl_qex": "استثناء قطر", "tl_dl": "⬇ تنزيل Excel", "tl_c_date": "التاريخ", "tl_c_cat": "الفئة", "tl_c_event": "الحدث", "tl_c_detail": "التفاصيل", "tl_cat_gen": "عام", "tl_fname": "timeline_alsharq_alawsat", "tl_sheet": "الجدول الزمني",
  "gov_head": "🏛️ نشاط الحكومة القطرية المتعلق بالحرب", "gov_none": "لا توجد مستجدات تُذكر خلال فترة الرصد هذه.",
  "foot": ("تجمّع هذه الصفحة وتلخّص تلقائيًا التغطيات الإعلامية العامة ومواد الجهات المعنية في قطر وإيران وسائر الدول الرئيسية وكوريا. "
           "تُجمَع الأخبار عبر استعلام خلاصات Google News RSS وبحث أخبار Naver وخلاصات RSS لوسائل الإعلام (الجزيرة وBBC وغيرها) "
           "بكلمات مفتاحية مثل قطر والشرق الأوسط والطاقة؛ وتُجمَع التقارير المعمّقة باستهداف نطاقات ناشري مراكز الأبحاث المحلية والدولية "
           "والمنظمات الدولية وغيرها مباشرةً. ويعتمد الجمع والتلخيص على العنوان والمقتطف المتاحَين علنًا لكل وسيلة؛ "
           "أمّا النص الكامل لوسائل الاشتراك المدفوع فلا يُتاح الاطلاع عليه إلا عبر رابط المصدر المرفق وبعد أن يسجّل القارئ دخوله أو يشترك في تلك الوسيلة مباشرةً. "
           "وتُصنَّف المقالات المجمّعة وتُلخَّص تلقائيًا حسب القضية وتُترجَم إلى الإنجليزية والعربية "
           "بواسطة Anthropic Claude (Sonnet 5) للذكاء الاصطناعي. وتُنفَّذ العملية بأكملها وتُنشَر تلقائيًا مرّتين يوميًا (07:00 و15:30 بتوقيت قطر) عبر GitHub Actions. "
           "ونظرًا لطبيعة الجمع التلقائي قد تُغفل بعض المقالات أو التقارير، لذا يُرجى التحقق من القضايا المهمة عبر المصادر الأصلية وعمليات بحث إضافية."),
  "sign": "- سفارة جمهورية كوريا لدى قطر، القسم التجاري · كوترا الدوحة", "org": "سفارة جمهورية كوريا لدى قطر، القسم التجاري · كوترا الدوحة",
  "ago_min": "منذ {n} د", "ago_hr": "منذ {n} س", "ago_day": "منذ {n} ي",
  "daily_no": "يومي رقم {n}", "weekly_no": "أسبوعي رقم {n}", "daily_demo": "يومي (تجريبي)", "ed_daily": "يومي", "ed_weekly": "أسبوعي",
  "no_only": "رقم {n}", "wk_incl": " (أسبوعي)", "wdays": ["الإثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد"],
 },
}

MAX_PER_SECTION = 60
POOL_FOR_ISSUES = 72          # 사안 분류에 넘길 기사 수(Sonnet 5 대용량 컨텍스트 — 원산지 고루 반영·중요 기사 누락 방지)
DESC_MAX = 220                # 각 기사 desc를 프롬프트에 넣을 때 최대 길이
SITE_BASE = "/qatar-media-monitor/"   # GitHub Pages 프로젝트 경로(콤보박스 링크 기준)
FLIGHT_URL = "https://kotradoha.github.io/qatar-korea-flight-monitor/"   # 자매 사이트(항공 모니터링)
ISSUE_BASE = (2026, 8, 1)     # 제1호 기준일(오전 7시 회차 = 일간 제1호)
WEEKLY_WEEKDAY = 6            # 주간 종합 리포트 생성 요일(월=0…일=6 → 일요일 오전 회차)
WEEKLY_LOOKBACK_DAYS = 7      # 주간 리포트 커버 기간(일)
REPORT_PERSIST_DAYS = 120     # 좋은 보고서는 약 6월경부터 최근까지 누적 유지(일)
REPORT_QUERY_DAYS = 120       # 보고서 수집 쿼리 조회 기간(Google News when:Nd)
REPORT_SHOW_MAX = 15          # 보고서 섹션 표시 최대 개수(최신 순)
REPORT_STORE_MAX = 80         # reports.json 보관 최대 개수
BOUNDARY_AM = (7, 0)
BOUNDARY_PM = (15, 30)
TZ = timezone(timedelta(hours=3))          # Asia/Qatar (UTC+3)
# 요약 엔진 우선순위(키 접두어로 자동 판별, 되는 것 사용):
#   Claude API(sk-ant-) → OpenRouter(sk-or-) → Groq(gsk_) → Gemini(AQ/AIza) → GitHub Models(ghs_/PAT)
# Claude API(Anthropic·소액·카타르 지원·최고 품질). Haiku 저렴.
ANTHROPIC_MODELS = ["claude-sonnet-5", "claude-haiku-4-5"]
# OpenRouter(무료 모델·GitHub 로그인 가입·OpenAI 호환).
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OR_MODELS = ["openai/gpt-oss-20b:free", "google/gemma-4-31b-it:free",
             "meta-llama/llama-3.3-70b-instruct:free", "openrouter/free"]
# GitHub Models(현재 서비스 종료 진행 중 — 최후 폴백). OpenAI 호환.
GH_ENDPOINT = "https://models.github.ai/inference/chat/completions"
GH_MODELS = ["openai/gpt-4o-mini", "meta/Llama-3.3-70B-Instruct"]
GEMINI_MODELS = ["gemini-2.0-flash-lite", "gemini-2.0-flash"]
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
# ──────────────────────────────────────────────────────────

feedparser.USER_AGENT = "Mozilla/5.0 (compatible; MideastMediaMonitor/1.0)"
TAG_RE = re.compile(r"<[^>]+>")
HANGUL_RE = re.compile(r"[가-힣]")


def gnews_url(query, lang, when_days=2):
    q = query.replace(" ", "%20")
    w = f"%20when:{int(when_days)}d"
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={q}{w}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={q}{w}&hl=en-US&gl=US&ceid=US:en"


def window_bounds(now_q):
    # 이번 회차가 대표하는 '정기 모니터링 기간'(직전 경계 ~ 이번 경계). 실제 실행 시각이 아니라 07:00/15:30 경계로 고정.
    am = now_q.replace(hour=BOUNDARY_AM[0], minute=BOUNDARY_AM[1], second=0, microsecond=0)
    pm = now_q.replace(hour=BOUNDARY_PM[0], minute=BOUNDARY_PM[1], second=0, microsecond=0)
    if now_q >= pm:
        start, end, slot = am, pm, "pm"                                 # 오늘 07:00 ~ 오늘 15:30
    elif now_q >= am:
        start, end, slot = pm - timedelta(days=1), am, "am"             # 어제 15:30 ~ 오늘 07:00
    else:
        start, end, slot = am - timedelta(days=1), pm - timedelta(days=1), "pre"  # 어제 07:00 ~ 어제 15:30
    return start, end, slot


def entry_time(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def source_of(e, fallback):
    src = e.get("source")
    if isinstance(src, dict) and src.get("title"):
        return src["title"]
    if e.get("source") and getattr(e.get("source"), "title", None):
        return e.source.title
    title = e.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return fallback


def clean_title(t):
    if " - " in t:
        head = t.rsplit(" - ", 1)[0]
        if len(head) > 15:
            return head
    return t


def clean_desc(s):
    s = TAG_RE.sub(" ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:280]


def has(text, kws):
    low = text.lower()
    return any(k in low for k in kws)


def blocked_source(src):
    low = (src or "").lower()
    return any(b in low for b in BLOCK_SOURCES)


def _build_report_matchers():
    """짧은 영숫자 힌트(hri, kdi, eia…)는 단어경계로 매칭해 'christian⊃hri' 같은 오탐 방지.
    한글·공백·기호 포함 힌트는 부분문자열 매칭."""
    subs, regexes = [], []
    for h in REPORT_HINTS:
        hl = h.lower()
        if re.fullmatch(r"[a-z0-9]+", hl):
            regexes.append(re.compile(r"(?<![a-z0-9])" + re.escape(hl) + r"(?![a-z0-9])"))
        else:
            subs.append(hl)
    return subs, regexes

_REPORT_SUBS, _REPORT_REGEXES = _build_report_matchers()

# 발행처 도메인으로도 보고서 판별(구글뉴스 <source url>=원발행처 도메인). 특히 한국 기관 포착에 유효.
REPORT_DOMAINS = [
    # 한국 국책·공공·민간 연구기관
    "kiep.go.kr", "emerics.org", "kdi.re.kr", "keei.re.kr", "kcif.or.kr", "kiet.re.kr", "ifans.go.kr",
    "asaninst.org", "sejong.org", "kita.net", "kogas.or.kr", "knoc.or.kr", "opinet.co.kr",
    "koreaexim.go.kr", "ksure.or.kr", "kotra.or.kr", "hri.co.kr", "samsungsgr.com", "seri.org",
    "lgbr.co.kr", "posri.re.kr", "hanaif.re.kr", "kcmi.re.kr",
    # 해외 연구기관·국제기구·에너지
    "imf.org", "worldbank.org", "oecd.org", "iea.org", "opec.org", "eia.gov", "iiss.org",
    "chathamhouse.org", "csis.org", "brookings.edu", "carnegieendowment.org", "atlanticcouncil.org",
    "crisisgroup.org", "mei.edu", "cfr.org", "eurasiagroup.net", "rystadenergy.com", "woodmac.com",
    "spglobal.com", "economist.com", "eiu.com", "foreignaffairs.com", "foreignpolicy.com",
    "oxfordeconomics.com", "piie.com", "rusi.org", "mecouncil.org", "studies.aljazeera.net",
    "dohainstitute.org", "wilsoncenter.org", "bruegel.org",
    # 글로벌 회계·컨설팅펌
    "kpmg.com", "pwc.com", "deloitte.com", "ey.com", "bcg.com", "bain.com", "mckinsey.com",
    "accenture.com", "oliverwyman.com", "rolandberger.com",
]

def _domain_is_report(shref):
    s = (shref or "").lower()
    return any(dom in s for dom in REPORT_DOMAINS)

# 한국 기관 '자체 발간물' 직접 포착용 — 각 기관 도메인을 구글뉴스 site: 로 조준 수집.
# (기관 자체 RSS는 robots/비표준으로 확인이 어려워, 발행처 도메인을 직접 겨냥하는 방식으로 연결)
KO_REPORT_SITE_DOMAINS = [
    "kiep.go.kr", "emerics.org", "kdi.re.kr", "keei.re.kr", "kcif.or.kr", "kiet.re.kr", "ifans.go.kr",
    "asaninst.org", "sejong.org", "kita.net", "kogas.or.kr", "knoc.or.kr", "opinet.co.kr",
    "kotra.or.kr", "hri.co.kr", "samsungsgr.com", "posri.re.kr", "kcmi.re.kr",
]

def is_report_source(src):
    s = (src or "").lower()
    if any(h in s for h in _REPORT_SUBS):
        return True
    return any(rx.search(s) for rx in _REPORT_REGEXES)

# 심층 보고서 판별: '발행처(source 이름 또는 원발행처 도메인)가 실제 연구기관·국제기구·컨설팅펌'인 경우만 인정.
# 뉴스 매체가 보고서를 인용·소개한 기사(제목에 기관명이 들어가도)는 제외 → 뉴스성 나열 방지.
def looks_report(title, src, shref=""):
    # 1) 발행처(이름 또는 도메인)가 연구기관/국제기구/컨설팅펌이어야 함(뉴스 매체는 원천 배제)
    if not (is_report_source(src) or _domain_is_report(shref)):
        return False
    # 2) 중동·카타르 주제와 연관되어야 함
    if not (has(title + " ", QATAR_KW) or has(title + " ", MIDEAST_KW)):
        return False
    return True


def collect(win_start_utc, now_utc, when_days=2):
    items, seen = [], set()
    feeds = []
    for q in Q_QATAR_EN: feeds.append(("en", q, gnews_url(q, "en", when_days)))
    for q in Q_QATAR_KO: feeds.append(("ko", q, gnews_url(q, "ko", when_days)))
    for q in Q_MIDEAST_EN: feeds.append(("en", q, gnews_url(q, "en", when_days)))
    for q in Q_MIDEAST_KO: feeds.append(("ko", q, gnews_url(q, "ko", when_days)))
    # 링크모음의 전 언론매체를 매 회차 site: 조준으로 직접 모니터링(카타르 현지=폭넓게, 해외·역내=중동주제, 국내=국문 중동주제)
    for dom in QATAR_LOCAL_SITES:
        feeds.append(("en", f"[qa]{dom}", gnews_url(f"site:{dom}", "en", when_days)))
    for dom in FOREIGN_MEDIA_SITES:
        feeds.append(("en", f"[m]{dom}", gnews_url(f"site:{dom} {MEDIA_TOPIC}", "en", when_days)))
    for dom in KOREA_MEDIA_SITES:
        feeds.append(("ko", f"[kr]{dom}", gnews_url(f"site:{dom} {MEDIA_TOPIC_KO}", "ko", when_days)))
    # 네이버 뉴스 '카타르'/'중동' 검색 결과(네이버 도메인 조준)
    for q in Q_NAVER_KO:
        for dom in NAVER_NEWS_DOMAINS:
            feeds.append(("ko", f"[naver]{q}", gnews_url(f"{q} site:{dom}", "ko", when_days)))
    for q in Q_REPORTS_KO: feeds.append(("ko", q, gnews_url(q, "ko", REPORT_QUERY_DAYS)))
    for q in Q_REPORTS_EN: feeds.append(("en", q, gnews_url(q, "en", REPORT_QUERY_DAYS)))
    # 한국 기관 자체 발간물: 기관 도메인을 site: 로 직접 조준(중동·유가·카타르 주제만 통과)
    for dom in KO_REPORT_SITE_DOMAINS:
        feeds.append(("ko", f"[site]{dom}", gnews_url(f"site:{dom}", "ko", REPORT_QUERY_DAYS)))
    for name, url in DIRECT_FEEDS: feeds.append(("en", name, url))

    def _fetch(job):
        lang, label, url = job
        try:
            return (lang, label, feedparser.parse(url))
        except Exception as ex:
            print(f"[warn] feed failed {url}: {ex}")
            return (lang, label, None)

    socket.setdefaulttimeout(FEED_TIMEOUT)   # 피드 수집 동안엔 더 짧은 타임아웃 적용
    try:
        with ThreadPoolExecutor(max_workers=16) as _ex:   # 피드 병렬 수집(매체 수 많아도 빠르게)
            fetched = list(_ex.map(_fetch, feeds))
    finally:
        socket.setdefaulttimeout(90)   # 피드 수집 종료 후 기본 타임아웃 복원(LLM 호출 여유)
    # 결과 처리(단일 스레드 — dedup/append 안전)
    for lang, label, d in fetched:
        if d is None:
            continue
        for e in d.entries:
            title = clean_title(e.get("title", "").strip())
            link = e.get("link", "").strip()
            if not title or not link:
                continue
            if not link.lower().startswith(("http://", "https://")):   # 안전: http/https 링크만 허용(javascript:/data: 등 차단)
                continue
            src = source_of(e, label)
            if blocked_source(src):          # 취합/비정식/해외발 소스 제외
                continue
            sd = e.get("source")             # 구글뉴스 <source url="원발행처">
            shref = ""
            if isinstance(sd, dict):
                shref = sd.get("href", "") or sd.get("url", "") or ""
            elif sd is not None:
                shref = getattr(sd, "href", "") or ""
            desc = clean_desc(e.get("summary", ""))
            text = title + " " + desc
            is_qatar = has(text, QATAR_KW)
            report = looks_report(title, src, shref)
            if not is_qatar and not has(text, MIDEAST_KW) and not report:
                continue
            dt = entry_time(e)
            if dt is None or dt > now_utc + timedelta(minutes=5):
                continue
            # 일반 기사: 이번 창(window)만. 보고서: 창 밖이라도 최근 REPORT_PERSIST_DAYS(약 6월~)까지 허용.
            lo = win_start_utc
            if report:
                lo = min(win_start_utc, now_utc - timedelta(days=REPORT_PERSIST_DAYS))
            if dt < lo:
                continue
            key = link.split("?")[0].lower()
            tkey = "".join(title.lower().split())[:60]
            if key in seen or tkey in seen:
                continue
            seen.add(key); seen.add(tkey)
            kor = bool(HANGUL_RE.search(title))
            items.append({"title": title, "link": link, "source": src, "dt": dt,
                          "qatar": is_qatar, "desc": desc, "korean": kor, "shref": shref,
                          "report": report, "region": source_region(src, kor)})
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items


# ───────────────────── LLM 키 라우팅 ─────────────────────
# 키는 어느 시크릿 슬롯(GEMINI_API_KEY/GROQ_API_KEY/LLM_API_KEY/GH_MODELS_TOKEN)에 넣어도
# 접두어로 자동 판별해 알맞은 엔진에 사용.
#   Claude API: "sk-ant-..."  |  OpenRouter: "sk-or-..."  |  Groq: "gsk_..."
#   Gemini: "AQ..."/"AIza..."  |  GitHub 토큰: "ghs_/ghp_/github_pat_..."
def _all_keys():
    return [k for k in (os.environ.get("LLM_API_KEY", "").strip(),
                        os.environ.get("GH_MODELS_TOKEN", "").strip(),
                        os.environ.get("GROQ_API_KEY", "").strip(),
                        os.environ.get("GEMINI_API_KEY", "").strip()) if k]

def _anthropic_key():
    for k in _all_keys():
        if k.startswith("sk-ant-"):
            return k
    return ""

def _openrouter_key():
    for k in _all_keys():
        if k.startswith("sk-or-"):
            return k
    return ""

def _gh_token():
    # GH_MODELS_TOKEN 슬롯에 값이 있으면(예: Actions 내장 GITHUB_TOKEN=ghs_...) 그대로 사용.
    direct = os.environ.get("GH_MODELS_TOKEN", "").strip()
    if direct:
        return direct
    # 그 외 슬롯에 GitHub PAT가 들어있으면 접두어로 인식.
    for k in _all_keys():
        if k.startswith("github_pat_") or k.startswith("ghp_") or k.startswith("ghs_"):
            return k
    return ""

def _groq_key():
    for k in _all_keys():
        if k.startswith("gsk_"):
            return k
    return ""

def _gemini_key():
    for k in _all_keys():
        if k.startswith("AQ") or k.startswith("AIza"):
            return k
    return ""


# 진단 메시지(요약 실패 시 사이트에 표시 → 원인 파악용). msg=상세(로그·비공개), public=페이지 노출용(제공사 에러본문 등 미포함)
LLM_DIAG = []
def _diag(msg, public=None):
    print(msg)
    msg = public if public is not None else msg
    if len(LLM_DIAG) < 8:
        LLM_DIAG.append(msg)


def _extract_json(txt):
    """LLM 응답에서 JSON 객체만 추출(코드펜스 제거 + 최외곽 {..} 슬라이스). 프리필 미지원 모델 대응."""
    t = (txt or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1 and j > i:
        t = t[i:j + 1]
    t = re.sub(r",(\s*[}\]])", r"\1", t)   # 배열/객체 후행 콤마 제거(LLM JSON 오류 대비)
    return t


# ───────────────────── Claude API (Anthropic·최우선·최고 품질) ─────────────────────
def anthropic_call(model, prompt, json_mode):
    key = _anthropic_key()
    if not key:
        return None
    url = "https://api.anthropic.com/v1/messages"
    # 주의: 일부 최신 모델(예: Sonnet 5)은 temperature·assistant 프리필을 거부(400)하고, freeform JSON 신뢰도가 낮음.
    #  → JSON은 tool_use(구조화 출력)로 강제해 항상 유효한 JSON을 받고, 서술형은 text 블록을 추출. max_tokens는 여유 있게.
    msgs = [{"role": "user", "content": prompt}]
    payload = {"model": model, "max_tokens": 16000, "messages": msgs}
    if json_mode:
        payload["tools"] = [{
            "name": "emit_result",
            "description": "지시된 형식의 결과 JSON을 그대로 반환한다.",
            "input_schema": {"type": "object",
                             "properties": {"issues": {"type": "array", "items": {"type": "object"}}},
                             "required": ["issues"]},
        }]
        payload["tool_choice"] = {"type": "tool", "name": "emit_result"}
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            url, data=body,
            headers={"content-type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read().decode("utf-8"))
            blocks = data.get("content") or []
            if json_mode:
                # tool_use 블록의 input(검증된 JSON 객체)을 그대로 직렬화 반환 → 항상 유효한 JSON
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                        return json.dumps(b["input"], ensure_ascii=False)
                # 폴백: tool_use 없으면 text에서 추출 시도
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                        return _extract_json(b["text"])
                _diag(f"[warn] claude {model} no tool_use/text"); return None
            # 서술형: 첫 text 블록
            txt = ""
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                    txt = b["text"]; break
            if not txt:
                for b in blocks:
                    if isinstance(b, dict) and b.get("text"):
                        txt = b["text"]; break
            txt = (txt or "").strip()
            if not txt:
                _diag(f"[warn] claude {model} empty/nontext content"); return None
            return txt
        except urllib.error.HTTPError as ex:
            try:
                eb = ex.read().decode("utf-8", "ignore")[:200]
            except Exception:
                eb = ""
            if ex.code == 429:
                _diag(f"[warn] claude {model} 429, retry {attempt+1}/3")
                time.sleep(5 * (attempt + 1)); continue
            _diag(f"[warn] claude {model} HTTP {ex.code} {eb}", public=f"[warn] claude {model} HTTP {ex.code}"); return None
        except Exception as ex:
            _diag(f"[warn] claude {model} failed: {ex}"); return None
    return None


# ───────────────────── OpenRouter (무료 모델·OpenAI 호환) ─────────────────────
def openrouter_call(model, prompt, json_mode):
    key = _openrouter_key()
    if not key:
        return None
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            OR_ENDPOINT, data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                     "HTTP-Referer": "https://kotradoha.github.io/qatar-media-monitor/",
                     "X-Title": "Qatar Media Monitor"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as ex:
            try:
                eb = ex.read().decode("utf-8", "ignore")[:160]
            except Exception:
                eb = ""
            if ex.code == 429:
                _diag(f"[warn] openrouter {model} 429, retry {attempt+1}/3")
                time.sleep(4 * (attempt + 1)); continue
            _diag(f"[warn] openrouter {model} HTTP {ex.code} {eb}", public=f"[warn] openrouter {model} HTTP {ex.code}"); return None
        except Exception as ex:
            _diag(f"[warn] openrouter {model} failed: {ex}"); return None
    return None


# ───────────────────── GitHub Models (폴백·서비스 종료 진행중) ─────────────────────
# 엔드포인트/모델ID 포맷이 시점마다 달라 여러 조합을 순차 시도.
GH_ENDPOINTS = [
    "https://models.github.ai/inference/chat/completions",
    "https://models.inference.ai.azure.com/chat/completions",
]

def _gh_model_variants(model):
    # "openai/gpt-4o-mini" ↔ "gpt-4o-mini" 양쪽 포맷 모두 시도
    v = [model]
    if "/" in model:
        v.append(model.split("/", 1)[1])
    else:
        v.append("openai/" + model)
    return v

def github_models_call(model, prompt, json_mode):
    key = _gh_token()
    if not key:
        return None
    for endpoint in GH_ENDPOINTS:
        for mid in _gh_model_variants(model):
            payload = {
                "model": mid,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2048,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint, data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as ex:
                try:
                    errbody = ex.read().decode("utf-8", "ignore")[:200]
                except Exception:
                    errbody = ""
                host = endpoint.split("/")[2]
                _diag(f"[warn] ghmodels {mid}@{host} HTTP {ex.code} {errbody}", public=f"[warn] ghmodels {mid}@{host} HTTP {ex.code}")
                if ex.code == 429:
                    time.sleep(4);
            except Exception as ex:
                _diag(f"[warn] ghmodels {mid} failed: {ex}")
    return None


# ───────────────────── Gemini (사안별/폴백) ─────────────────────
def gemini_call(model, prompt, json_mode):
    key = _gemini_key()
    if not key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    cfg = {"temperature": 0.3, "maxOutputTokens": 2048}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as ex:
            if ex.code == 429:                     # 한도 초과 → 잠깐 쉬고 재시도
                print(f"[warn] {model} 429, retry {attempt+1}/3")
                time.sleep(6 * (attempt + 1)); continue
            _diag(f"[warn] gemini {model} HTTP {ex.code}"); return None
        except Exception as ex:
            _diag(f"[warn] gemini {model} failed: {ex}"); return None
    _diag(f"[warn] gemini {model} 429(한도)")
    return None


def groq_call(model, prompt, json_mode):
    key = _groq_key()
    if not key:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as ex:
            if ex.code == 429:
                print(f"[warn] groq {model} 429, retry {attempt+1}/3")
                time.sleep(4 * (attempt + 1)); continue
            _diag(f"[warn] groq {model} HTTP {ex.code}"); return None
        except Exception as ex:
            _diag(f"[warn] groq {model} failed: {ex}"); return None
    return None


def gemini_generate(prompt, json_mode):
    # 1순위: Claude API(최고 품질·카타르 지원·소액).
    for m in ANTHROPIC_MODELS:
        out = anthropic_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via claude:{m}")
            return out
    # 2순위: OpenRouter(무료).
    for m in OR_MODELS:
        out = openrouter_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via openrouter:{m}")
            return out
    # 3순위: Groq(무료).
    for m in GROQ_MODELS:
        out = groq_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via groq:{m}")
            return out
    # 4순위: Gemini(리전 무료 한도 잡히면).
    for m in GEMINI_MODELS:
        out = gemini_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via gemini:{m}")
            return out
    # 5순위: GitHub Models(서비스 종료 진행중 — 최후).
    for m in GH_MODELS:
        out = github_models_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via ghmodels:{m}")
            return out
    return None


def gemini_issues(pool, win_label, weekly=False):
    if not pool:
        return None
    lines = []
    for i, x in enumerate(pool):
        reg = {"qatar": "[카타르현지]", "iran": "[이란매체]", "korea": "[국내]", "overseas": "[해외]"}[x["region"]]
        qt = "(카타르관련)" if x["qatar"] else ""
        d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
        desc = (x["desc"] or "")[:DESC_MAX]
        lines.append(f"{i}: {reg}{qt} ({x['source']}, {d}) {x['title']} :: {desc}")
    scope = ("아래 [기사 목록]은 지난 한 주(약 7일)치입니다. 한 주간의 흐름을 종합해 "
             if weekly else "아래 [기사 목록]을 읽고 이 갱신 주기의 내용을 ")
    weekly_flow = (
        "【주간 종합·흐름 재구성 — 주간 보고 전용(가장 중요)】 이 보고는 특정 시점의 스냅숏(일일 보고)이 아니라 "
        "**지난 한 주 전체를 관통하는 큰 흐름을 재구성**하는 주간 종합입니다. 개별 기사·시점을 단순 나열·집계하지 말고, 한 주의 맥락과 인과를 엮으세요.\n"
        "① 먼저 한 주간 **반복적으로 등장하며 이번 주를 규정한 핵심 키워드·쟁점·행위자**(예: 특정 휴전·핵협상 국면, 공습·교전 라운드, 국제유가 추세, 호르무즈·홍해 긴장, 카타르의 중재 역할 등)를 추출하세요.\n"
        "② 이를 중심으로 사안을 묶어, 각 사안이 **주 초반→중반→후반으로 어떻게 시작되어 전개·전환·격화/완화·귀결됐는지 시간 순 '흐름'이 드러나게** 서술하세요. "
        "즉 각 summary 항목은 단발 사실이 아니라 그 사안이 한 주 동안 **어떻게 변화·진전됐는지의 경과**를 담되, 반드시 구체적 날짜·수치·전환점을 명시하세요"
        "(예: '주 초 ~로 시작 → 중반 ~로 확대·격화 → 주말 ~로 완화/봉합', '유가는 주 초 배럴당 ~달러에서 ~ 여파로 주중 ~달러까지 상승 후 주말 ~로 조정' 등). 원문에 없는 사실·수치는 창작 금지.\n"
        "③ 결과적으로 '이번 한 주 중동 정세가 카타르의 국익·안보·에너지·물류·외교 관점에서 어떻게 흘러갔는가'가 이 요약만으로 한눈에·조리 있게 읽혀야 합니다. "
        "흐름·경과를 담아야 하므로 summary 항목 수는 사안당 **3~5개까지 허용**하며, 각 항목은 (일일보다) 다소 길어도 좋으나 개조식·명사형 종결은 유지하세요.\n"
        if weekly else "")
    prompt = (
        "당신은 주카타르대사관 상황실 분석관입니다. " + scope + weekly_flow +
        "【모니터링 주제 범위】 이 브리핑의 주제는 '카타르의 국익·안보·경제에 유의미한 중동 정세'입니다. "
        "즉 이스라엘·이란·걸프 무력충돌 및 공습·교전 동향, 외교·중재(특히 카타르의 중재 역할), "
        "호르무즈·홍해 등 해상안전·물류, 국제유가·LNG·에너지, 경제·통상·투자, 항공·교민 안전의 관점에서 "
        "의미 있는 사안만 다룹니다.\n"
        "【사안으로 만들지 말 것(주제 밖)】 정책·전략·안보·경제 함의가 없는 순수 인도적 사연·난민 개인사·미담/르포, "
        "날씨·기상, 스포츠, 연예·문화·생활, 단순 지역 사건사고, 종교 일반 등은 사안으로 뽑지 마세요. "
        "다만 이런 소재라도 카타르 국익·에너지·안보·물류·외교에 직접 연결되면 포함합니다"
        "(예: 가자 휴전 협상·카타르 중재는 '외교·중재' 사안으로 포함하되, 개별 난민의 생활고 미담은 제외).\n"
        "【최우선 감지(반드시)】 카타르 본토·시설·기지(예: 알우데이드)·영공·해역·인원이 직접 공격·피격·미사일/드론 침범을 당했거나 "
        "카타르 내 피해(사상·시설 파손·폭발·정전·통신/항공 마비 등)가 발생한 정황이 기사에 조금이라도 있으면 **절대 누락하지 마세요.** "
        "무엇이·어디를·언제·피해규모(사상자·피해 정도)·현재 상태를 구체적으로 명시하되(정보가 단편적이면 '확인 중'으로라도 반드시 다룸), "
        "**표현 방식은 두 가지 중 택1**: ①카타르 피격·피해가 그 자체로 독립적 사안이면 **최상단 사안**으로 뽑고, "
        "②카타르 피격·피해가 더 큰 사안(예: 미·이란 확전, 호르무즈 위기)의 일부로 맥락상 그 안에 들어가는 것이 자연스러우면 **별도 사안으로 빼지 말고 그 사안의 `qatar_impact` 필드**에 카타르 피해 상세(무엇·어디·언제·피해규모·현재 상태)를 담으세요"
        "(이 필드는 화면에서 해당 이슈 안의 '※ 카타르 영향·피해' 별도 박스로 강조 표시됨). 카타르 직접 피해 정황이 없으면 qatar_impact는 비워 두세요.\n"
        "핵심 판별 기준: 가자·이스라엘·이란 등 소재라도 ①카타르가 실제로 역할·조치를 했거나(중재·성명·정상외교·지원·군사·에너지 등), "
        "②카타르가 공격·공습을 당하거나 카타르의 안보·영공·경제·에너지·항공·교민 안전이 직접 영향받거나, "
        "③사안이 중동 무력충돌·에너지·물류·경제 등 정세의 실질 전개일 때 포함하세요. "
        "'카타르 매체에 실렸다'는 사실만으로는 관련성이 생기지 않습니다 — 카타르의 역할도 없고 정세·에너지·경제 함의도 없는 기사는 제외하세요.\n"
        "관련성이 약한 기사는 억지로 사안으로 묶지 말고 제외하고, 애매하면 사안 수를 줄이세요 — 수량보다 정확도·논리성 우선.\n"
        "다만 카타르 국익·안보·에너지·물류·외교·정세에 유의미한 **중요 기사는 누락 없이 반드시 사안으로 포착**하고 그 핵심 내용을 요약에 충실히 반영하세요(사소·주변적 기사만 제외).\n"
        "'사안(issue)'별로 묶으세요. 개수는 그날 내용에 맞게 유연하게(보통 3~7개, 많으면 8개 이상, 정말 조용하면 1~2개). "
        "【유사 사안 통합】 같은 사건·동일 국면을 다룬 기사들은 출처·표현·보도 각도가 달라도 반드시 '하나의 사안'으로 통합하세요"
        "(예: '미·이스라엘의 이란 공습설'과 '이란의 보복 위협'이 같은 국면이면 한 사안으로 묶고, 각 전개는 그 사안의 summary 항목으로 정리). "
        "사실상 중복·인접한 국면을 여러 사안으로 쪼개지 말고, 반대로 본질이 다른 사안(예: 군사충돌 vs LNG 계약)은 분명히 분리하세요. "
        "묶을지 나눌지 애매하면, 카타르 국익 관점에서 '하나의 판단 단위'가 되는지를 기준으로 결정하세요.\n"
        "【교민·안전 소재 중복 금지】 미 대사관 출국·대피 권고, 여행경보, 교민 안전 우려 등 '안전·출국' 소재가 이미 상위 확전·위기 사안(예: 미·이란 확전) 안에 포함·서술돼 있으면 **별도의 '교민 안전 참고' 사안으로 또 만들지 마세요**(같은 사실 반복 금지 — 상위 사안에 흡수). "
        "'교민 안전·항공'을 **별도 사안으로 분리하는 것은 오직 한국 고유의 실행정보가 있을 때만** 허용합니다: 예) 한국 외교부·주카타르 대사관의 여행경보 발령·안전공지·대피 안내, 카타르 체류 교민 대상 조치, 카타르발/도하 경유 항공편 결항·변경 등. 이런 한국·카타르 특화 알맹이가 없으면 별도 사안화하지 말고 상위 사안 summary에 한 항목으로만 반영하세요.\n"
        "【다수 소스 종합】 카타르 현지·이란·역내·미국·유럽·글로벌·국내 등 다양한 매체가 대량 취합됩니다. 그만큼 "
        "**가장 중요·시급·파급력 큰 사안을 정확히 선별하고 우선순위를 매기는 것**과, **핵심 팩트·수치·구체 정황을 밀도 있게 담는 것**이 특히 중요합니다.\n"
        "【품질 기준】 요약은 반드시 **객관적·팩트 위주**로, 오직 **취합된 기사(제목·발췌) 내용에만 근거**해 작성하세요. "
        "확인된 사실과 수치만 사용하고 추측·과장·주관적 논평·창작은 금지하며(원문에 없는 내용·수치·전망을 지어내지 말 것), "
        "각 사안이 '무엇이 일어났고 카타르에 어떤 함의인지'가 요약만으로 드러나게 작성하세요.\n"
        "카테고리 예시: 전쟁·군사(공습·교전 추이) / 외교·중재 / 에너지·유가·LNG / "
        "물류·해상안전(홍해·수에즈·호르무즈) / 경제·통상 / 항공·교민안전.\n"
        "【사안 배열 순서】 기본적으로 위 모니터링 분야 순서, 즉 ①전쟁·군사 ②외교·중재 ③에너지·유가·LNG "
        "④물류·해상안전 ⑤경제·통상 ⑥항공·교민안전 의 순서를 가급적 따르되, 사안의 **시급성·중요성·파급효과**가 높은 사안을 "
        "그 순서보다 앞으로 유연하게 배치하세요. "
        "(예: 카타르항공 운항 차질 등 '항공·교민' 사안은 특별히 심각·시급하지 않는 한 뒤쪽에 배치.)\n"
        "【정보원 우선순위·편향 방지】 중동 정세는 **사건 당사국 매체(카타르 현지·이란·이스라엘·걸프)와 CNN·Reuters·AP·AFP·Bloomberg·BBC·Al Jazeera·이란 국영매체(Press TV/Tasnim/Mehr/IRNA) 등 국제 1차·속보 매체가 원(原)보도처**인 경우가 대부분입니다. "
        "**미국이 어떻다·이란이 어떻다·중동에서 무슨 일이 있었다 류의 국제 현안은 그 당사국·현지·국제 통신사가 가장 먼저·정확히 보도**하며, "
        "**한국 언론(연합뉴스·YTN·KBS·MBC·SBS·조선·중앙·동아 등)은 이들 외신을 전재·인용하는 2차(전달) 매체인 경우가 많습니다.** "
        "따라서 사안 선정·사실관계·요약 서술은 **1차 원보도처를 우선 근거**로 삼고, **한국 보도는 원출처가 없거나 한국 고유 관점(정부 대응·국내 산업·교민 영향)일 때만 보완적으로** 쓰세요. "
        "**동일한 사건·팩트를 다룰 때 목록에 현지·1차 원보도처가 있으면 그 원보도처를 먼저 근거·출처로** 쓰고, 한국 매체가 단순 전재이면 출처로 내세우지 마세요. "
        "**다만 한국 매체가 단순 전재가 아니라 독자적 시각·분석·논평(국내 영향 해석, 전문가 코멘트 등)을 담고 있으면 그 부분은 해당 매체를 명시해 인용해도 됩니다.** "
        "특히 **국내 언론이 같은 사안을 여러 건 전재하더라도 그 '기사 수량'을 사안의 중요도·상단 배치 근거로 삼지 말 것** "
        "— 중요도는 오직 사안의 실제 시급성·중요성·파급효과로 판단하세요.\n"
        "【한국 보도 내용 반드시 반영】 위 '1차·현지 우선'은 **출처·링크·매체명 표기**에 한한 원칙입니다. **이슈 선정과 요약 내용에는 한국 언론이 보도 중인 사안·정보도 반드시 포함**하세요 — 한국에서 활발히 다뤄지는 주제는 (전재라도) 누락하지 말고 이슈로 포착하고, **한국 정부·외교부 대응, 교민 안전·대피 안내, 국내 산업·에너지 안보 영향, 한국 관련 언급** 등 한국에서 중요한 관점·정보는 요약에 충실히 담으세요(관련 [국내] 기사를 ids에 포함). 대사관은 '현지에서 무슨 일이 일어나는가'와 함께 '한국에서 무엇이 어떻게 보도·논의되는가'를 모두 알아야 합니다.\n"
        "각 사안 필드: theme(사안명, 앞에 이모지 1개 권장. "
        "단, 사안이 '카타르 교민 안전' 또는 '항공 운영'을 다루되 교민이 직접 알아야 할 실질적·행동가능한 "
        "안전 경보·항공 운항 변동 정보가 아니라 배경·정황 참고 수준이면 사안명 맨 끝에 ' 참고'를 붙일 것"
        "(예: '카타르 내 교민 안전 및 항공 운영 참고')), "
        "summary(한국어 서술 항목의 **배열**. 항목 수는 2~4개로, 내용을 잘게 쪼개지 말 것. "
        "하나의 하위 사건·현상에 대한 원인·경과·결과·예상효과 등 서로 연관된 내용은 **한 항목으로 묶고**, 성격이 다른 내용은 항목을 나눠 구분. "
        "각 항목은 정부보고서식 개조식으로, 핵심 사실과 함께 **구체적 수치·규모·주체**(사상자·미사일/드론 수, 국제유가 가격·변동폭, 통항·피격 선박 수, 봉쇄·휴전 기간, 계약·금액·물동량, 지명·기관명 등)를 "
        "문장 안에 충실히 담아 **이 요약만으로 내부 보고가 될 수준**으로 작성. "
        "특히 원문(제목·발췌)에 등장하는 **날짜·기간·시각, 금액·비율·증감폭, 인원·수량, 지명·기관·인물명** 등 구체 팩트는 "
        "요약이라도 가능한 한 빠짐없이 반영해 최대한 상세하게 쓸 것(단, 원문에 없는 수치·사실은 절대 창작·추정하지 말 것). "
        "명사형 종결어미 '-함/-음/-됨/-임/-없음'으로 끝내고 서술체('-했다/-이다') 금지. "
        "**문두에 날짜(예: '7/31')를 붙이지 말 것**(커버 기간이 이미 명시됨). "
        "**'(현지시간)'·'(현지시각)'·'(한국시간)' 같은 막연한 시간대 표기를 불릿·문장 맨 앞에 단독으로 붙이지 말 것**"
        "(전쟁·공습·취소·합의 등 발표·결정의 시점이 중요하면 막연히 '현지시간'이라 쓰지 말고 **행위 주체(발표·결정한 인물·기관)가 있는 지역의 시간대와 구체적 날짜를 함께** 문장 안에 자연스럽게 녹일 것 — "
        "예: 트럼프·미국 정부 발표는 '미국시각 8월 1일 트럼프가 ~ 발표함', 이란 당국 발표는 '이란시각 8월 1일 새벽 ~'. "
        "원문(제목·발췌)에 있는 날짜만 쓰고, 원문에 없는 날짜·시각은 창작·추정 금지). "
        "'(기사 8·21)' 같은 기사 번호 표기, "
        "【매체명 표기 원칙 — 내용 우선】 **요약 본문에는 기본적으로 매체명을 넣지 말고 검증된 사실·수치만** 밀도 있게 서술하세요(보도 매체·원문은 우측 관련기사 목록에 이미 표시됨). "
        "여러 매체가 동일하게 보도한 사실일수록 매체명은 정보가치가 없으니 **절대 나열하지 마세요**(예: '(이스라엘타임스·KBS·경향신문 등)', '~라고 조선비즈가 보도함' 금지). "
        "특히 **'○○매체는/○○매체가 ~ 보도함/보도하는/보도했다'와 '○○ 등 국내 매체는 ~ 보도' 같은 '매체명+보도' 서술은 아래 4예외가 아니면 일체 금지**입니다"
        "(실제 금지 예: '뉴욕타임스는 쿠웨이트가 이란산 드론을 격추했다고 보도함', 'KBS 등 국내 매체는 ~ 계획 중이라고 보도함', 'news18 등은 ~ 표적 목록에 포함했다고 보도'). "
        "대신 **매체를 지우고 사실만 단정적으로** 서술하세요(예: '쿠웨이트가 이란산 드론을 격추한 것으로 확인됨', '미국이 ~ 공습을 계획 중인 것으로 알려짐'). 근거 매체는 우측 링크·↗칩에 이미 있으므로 본문에 다시 넣지 마세요. "
        "매체명은 **다음 네 경우에만** 밝힙니다: ①단독·독점 보도(누가·어떻게가 사실의 일부일 때, 예: '뉴욕타임스가 위성사진으로 ~ 확인함'), ②공식 입장·성명(매체가 아니라 발표 주체를 명시, 예: '이란 외무부', '카타르 국방부(QNA)', '쿠웨이트 국방부'), ③상반·미확인 주장(출처를 밝혀야 편향·진위가 드러날 때, 예: '이란 국영매체 주장'), ④신뢰도가 사안 판단에 결정적일 때. "
        "이 경우에도 반드시 **원(原)·현지·1차 매체**를 밝히고 한국 전재 매체는 쓰지 마세요. (사건의 주체·당사자인 기관·기업·정부·인물명은 매체명이 아니므로 당연히 그대로 서술.) "
        "예: ['이란 IRGC가 미군 호위 유조선 2척을 호르무즈서 타격해 승조원 3명 사망 주장, 이에 국제유가(브렌트)가 약 3% 올라 배럴당 90달러대에 진입함.', "
        "'튀르키예가 호르무즈 우회 육상 물류로를 3년 내 완공 목표로 검토 중이며, 한국 정부도 해협 안정 기여방안을 복수로 검토 중이나 미국의 구체 요청은 아직 없음.']), "
        "ids(그 사안 관련 기사 id 정수 배열, 최대 30개), "
        "qatar_impact(선택. 이 사안 안에 카타르 본토·시설·영공·해역·인원의 직접 피격·피해가 포함될 때만, 그 카타르 피해 상세를 담는 한국어 서술 배열 1~3개 — 명사형 종결어미, 무엇·어디·언제·피해규모·현재 상태 구체 명시. 카타르 직접 피해가 없으면 빈 배열 []. "
        "**qatar_impact 본문에는 매체명·기사번호를 넣지 말 것**(근거 출처는 아래 qatar_impact_ids로 제공되어 화면에 ↗ 링크로 표시됨). "
        "단, 그 피해·위협 주장이 **단일·비정통 매체(예: 지역 밖 2차 매체) 단독 보도이고 1차·현지 정통 소스가 없으면** 본문 끝에 '(단일 매체 보도, 교차확인 필요)'를 반드시 붙일 것), "
        "qatar_impact_ids(qatar_impact를 뒷받침하는 기사 id 정수 배열. 반드시 ids에도 포함. 카타르 피해가 없으면 빈 배열 []).\n"
        "qatar_impact의 내용은 반드시 [기사 목록]의 기사로 뒷받침돼야 하며 그 id를 ids와 qatar_impact_ids 양쪽에 포함하세요.\n"
        "【요약↔링크 일치(필수·양방향)】 summary의 모든 문장·사실·주장·수치는 반드시 [기사 목록]의 특정 기사에 근거해야 하며, 그 근거 기사의 id를 **빠짐없이 그 사안의 ids에 포함**하세요. "
        "즉 아래 '연관 보도내역·링크'만으로 요약의 모든 내용을 검증할 수 있어야 합니다. "
        "**역으로, [기사 목록]의 어떤 기사로도 뒷받침되지 않는 내용(특정 매체가 무엇을 보도·분석했다는 서술 포함)은 요약에 절대 쓰지 말고 제외하세요.** "
        "링크로 뒷받침 못 하는 주장은 아무리 중요해 보여도 넣지 않습니다(근거 없는 서술 금지 — 정확성 최우선). "
        "특정 매체의 분석·발언을 요약에 넣으려면 그 매체의 해당 기사가 [기사 목록]에 있어 id로 연결될 때만 서술하세요.\n"
        "중요 규칙:\n"
        "- [카타르현지]는 '카타르 매체발'이라는 출처 표시일 뿐, 그 자체로 사안 가치를 부여하지 않습니다. "
        "카타르가 실제로 역할·조치를 한 사안(중재·성명·정상외교·지원·군사·에너지 계약 등)이나, 카타르가 공격·공습을 당하거나 "
        "카타르 국익·안보·영공·경제·에너지·교민 안전에 직접 영향을 주는 사안만 '카타르 관련'으로 최우선하세요. 그런 카타르 실질 관여 사안이 있으면 반드시 1개 이상 만들고 관련 [카타르현지] 기사를 ids에 우선 포함하세요. "
        "단, 카타르 매체에 실렸을 뿐 카타르의 역할이 없고 정세·에너지·경제 함의도 없는 연성기사(예: 난민 개인사 미담, 지역 생활기사)는 "
        "최우선은커녕 사안으로 만들지 마세요.\n"
        "- 각 사안의 ids에는 그 사안과 관련된 카타르·이란·해외·국내 4개 권역의 '주요(메이저) 기사를 가능한 한 빠짐없이' 넣으세요"
        "(권역별 최대 4~5개까지). 요약 옆에서 웬만한 주요 기사가 다 보이게 하는 것이 목표입니다.\n"
        "- 동일 내용이면 **원(原)보도처·1차 매체를 우선**하세요. 우선순위: ①사건 당사국·현지매체(QNA/Al Jazeera/Gulf Times/Peninsula/Doha News, 이란 Press TV/Tasnim/Mehr/IRNA, 이스라엘 Times of Israel/Jerusalem Post) "
        "②국제 통신·속보 매체(Reuters/AP/AFP/Bloomberg/CNN/BBC/Guardian/NYT/WSJ/Al Arabiya/Anadolu/Middle East Eye) ③한국 매체(연합/뉴시스/KBS/MBC/SBS/조선/중앙/동아/한겨레/경향/한국경제/매일경제 — 대개 전재·2차이므로 보완용). "
        "국제 현안에서 ①②의 1차 기사가 목록에 있으면 반드시 그 id를 우선 포함하고, 한국 기사만으로 사안 링크를 채우지 마세요.\n"
        "- 제공된 기사에 없는 사실·수치는 절대 창작 금지. 한국어로. 반드시 아래 JSON만 출력:\n"
        "{\"issues\":[{\"theme\":\"\",\"summary\":[\"\",\"\"],\"qatar_impact\":[],\"qatar_impact_ids\":[],\"ids\":[0,1]}]}\n\n"
        f"[커버기간] {win_label}\n[기사 목록]\n" + "\n".join(lines)
    )
    # 이슈 생성은 품질 핵심이므로, 빈 결과/파싱 실패 시 flat 폴백 대신 최대 3회 재시도(간헐적 토큰초과·빈배열 방지)
    for attempt in range(3):
        out = gemini_generate(prompt, json_mode=True)
        if not out:
            _diag(f"[warn] issues empty response, retry {attempt+1}/3")
            continue
        try:
            data = json.loads(out)
            issues = data.get("issues") if isinstance(data, dict) else None
            if issues and isinstance(issues, list):
                # LLM이 문자열/비정상 원소를 섞어 반환해도 빌드가 죽지 않도록 dict 원소만 채택
                issues = [x for x in issues if isinstance(x, dict) and (x.get("theme") or x.get("summary"))]
                if issues:
                    return issues
            _diag(f"[warn] issues parsed but empty, retry {attempt+1}/3")
        except Exception as ex:
            _diag(f"[warn] issues json parse failed: {ex}, retry {attempt+1}/3")
    return None


def gemini_flat(pool, win_label):
    if not pool:
        return None
    lines = []
    for x in pool[:45]:
        tag = "[카타르] " if x["qatar"] else ""
        d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
        lines.append(f"- {tag}({x['source']}, {d}) {x['title']} :: {x['desc']}")
    prompt = (
        "당신은 주카타르대사관 상황실의 뉴스 요약 담당입니다. 아래 커버기간 "
        f"'{win_label}' 기사(제목/매체/발췌)를 근거로 한국어 핵심 요약을 작성하세요. 형식:\n"
        "■ 핵심 요약: (불릿 3~6개)\n■ 핵심 수치: (사상자·미사일·유가·호르무즈 비중 등 불릿; 없으면 '특이 수치 없음')\n"
        "■ 카타르 관련: (불릿 2~4개, 없으면 '해당 기간 카타르 직접 특이사항 없음')\n■ 중동 정세 주요: (불릿 3~6개)\n"
        "모든 불릿은 정부보고서식 '개조식·했음체'로, 명사형 종결어미 '-함/-음/-됨/-임/-없음'으로 끝낼 것(서술체 '-했다/-이다' 금지). "
        "제목·발췌에 없는 사실은 창작 금지. '- '로 시작. 마크다운 헤더(#) 금지. "
        "'(현지시간)'·'(한국시간)' 등 시간대 표기를 불릿 맨 앞에 단독으로 붙이지 말 것(필요하면 해당 시각 뒤 괄호로 녹일 것).\n"
        "【매체명 — 내용 우선】 불릿에는 **기본적으로 매체명을 넣지 말고 사실·수치만** 쓰세요. 여러 매체가 동일 보도한 사실은 매체명 나열 금지"
        "(예: '(이스라엘타임스·KBS·경향 등)' 금지). 단독·독점 보도, 공식 성명(발표 주체 명시), 상반·미확인 주장, 신뢰도가 결정적인 경우에만 출처를 밝히되 **원(原)·현지·1차 매체**를 쓰고 한국 전재 매체는 쓰지 마세요.\n\n"
        + "\n".join(lines)
    )
    return gemini_generate(prompt, json_mode=False)


def translate_issues(issues, lang):
    """사안 요약(theme/summary/figures)을 영어/아랍어로 번역. 실패 시 원문(한국어) 유지."""
    if not issues or lang == "ko":
        return issues
    target = {"en": "English", "ar": "Arabic (Modern Standard Arabic)"}.get(lang)
    if not target:
        return issues
    payload = [{"theme": i.get("theme", ""), "summary": i.get("summary", ""), "qatar_impact": i.get("qatar_impact", "")} for i in issues if isinstance(i, dict)]
    prompt = (
        f"Translate the 'theme', 'summary' and 'qatar_impact' fields of the following JSON into {target}. "
        "'summary' is an array of bullet strings — translate each element and return it as an array of the SAME length and order. "
        "'qatar_impact' may be a string or an array — translate it keeping the same type; if it is empty, return it empty. "
        "Keep all numbers, dates, currencies and proper nouns; keep any leading emoji in 'theme'. "
        "Return ONLY a JSON object of the exact form {\"issues\":[{\"theme\":\"\",\"summary\":[\"\"],\"qatar_impact\":\"\"}]} "
        "with the same number and order of items, no commentary.\n\n"
        + json.dumps({"issues": payload}, ensure_ascii=False))
    out = gemini_generate(prompt, json_mode=True)
    if not out:
        return issues
    try:
        tr = json.loads(out).get("issues")
        if isinstance(tr, list) and len(tr) == len(issues):
            merged = []
            for orig, t in zip(issues, tr):
                m = dict(orig)
                if isinstance(t, dict):
                    m["theme"] = t.get("theme") or orig.get("theme", "")
                    if t.get("summary"):
                        m["summary"] = t.get("summary")
                    if t.get("qatar_impact"):
                        m["qatar_impact"] = t.get("qatar_impact")
                merged.append(m)
            return merged
    except Exception as ex:
        print(f"[warn] translate_issues {lang} failed: {ex}")
    return issues


def gemini_qatar_gov(pool, win_label):
    """카타르 '정부' 공식 동향만 별도 경량 추출(코어 이슈 로직과 분리). 카타르 관련 기사만 대상.
    반환: [{"t": 한국어 불릿, "links": [(매체, url), ...]}] 리스트(없으면 [])."""
    qpool = [x for x in pool if x.get("qatar") or x.get("region") == "qatar"]
    if not qpool:
        return []
    lines = []
    for i, x in enumerate(qpool[:40]):
        d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
        desc = (x.get("desc") or "")[:DESC_MAX]
        lines.append(f"{i}: ({x['source']}, {d}) {x['title']} :: {desc}")
    prompt = (
        "당신은 주카타르대사관 상황실 분석관입니다. 아래 [기사 목록]에서 **전쟁(미·이스라엘-이란 전쟁)과 직접 관련된 카타르 '정부'의 공식 동향**만 뽑아 한국어로 정리하세요. "
        "대상: 카타르 국왕(에미르)·총리·외교부(MOFA)·국방부·내무부·정부커뮤니케이션실(GCO)·카타르에너지(QatarEnergy)·QNA(국영통신)의 "
        "**전쟁·이란 정세 관련** 공식 성명·발표·결정·조치 — 예: 전쟁 관련 중재·외교, 공습·정전·핵협상에 대한 지지/규탄/우려 성명, 자국민·교민 안전조치·여행/영공 공지, 에너지·LNG·불가항력 관련 공식 입장, 대이란 제재·추방 등. "
        "**카타르가 참여·서명한 GCC(걸프협력회의)·아랍연맹 공동성명이나 정상·외교장관 회의 결과도 카타르 정부의 공식 동향으로 포함**하세요(전쟁 관련일 때). "
        "【엄격】 반드시 [기사 목록]에 근거가 있는 것만. 원문에 없는 내용·추정 창작 절대 금지. "
        "**전쟁과 무관한 의례적 외교(축전·조전·일반 정상회담 등)·일반 정세·타국 발표·언론 논평은 제외**하고, **전쟁 관련으로 카타르 정부가 실제로 한 것**만. "
        "각 항목은 정부보고서식 개조식·명사형 종결('-함/-음/-됨/-임')로 쓰되, 내용이 있으면 **1~2문장으로 자세히**(누가·무엇을·언제·핵심 내용·수치·배경·함의) 담고 최대 4개. "
        "**아래 이슈별 언론동향과 내용이 겹쳐도 무방합니다 — 카타르 정부의 전쟁 관련 공식 발표·지침·성명·조치이면 반드시 포함**하세요(정부 공식 동향은 별도로 중요). "
        "각 항목에는 그 동향을 뒷받침하는 기사 번호(id)를 1~3개 담으세요. "
        "단, 전쟁과 무관한 의례적 외교나 카타르 정부 활동이 아닌 것은 넣지 말고, 뚜렷한 전쟁 관련 공식 동향이 없으면 반드시 빈 배열을 반환하세요. "
        "출력은 오직 JSON: {\"gov\":[{\"t\":\"불릿\",\"ids\":[0]}]} (없으면 {\"gov\":[]}).\n\n"
        f"[커버기간] {win_label}\n[기사 목록]\n" + "\n".join(lines))
    out = gemini_generate(prompt, json_mode=True)
    if not out:
        return []
    try:
        g = json.loads(out).get("gov")
        if not isinstance(g, list):
            return []
        res = []
        for item in g[:3]:
            if not isinstance(item, dict):
                continue
            t = (item.get("t") or "").strip()
            if not t:
                continue
            links, seen = [], set()
            for i in (item.get("ids") or [])[:6]:
                if isinstance(i, int) and 0 <= i < len(qpool):
                    x = qpool[i]
                    key = x.get("link")
                    if key and key not in seen:
                        seen.add(key)
                        links.append((x.get("source", ""), key))
                if len(links) >= 3:
                    break
            res.append({"t": t, "links": links})
        return res
    except Exception as ex:
        print(f"[warn] qatar_gov parse failed: {ex}")
    return []


def translate_gov(gov, lang):
    """정부 동향 불릿(dict 리스트)의 텍스트만 영어/아랍어로 번역. 링크는 유지. 실패 시 원문."""
    if not gov or lang == "ko":
        return gov
    target = {"en": "English", "ar": "Arabic (Modern Standard Arabic)"}.get(lang)
    if not target:
        return gov
    texts = [g["t"] for g in gov]
    prompt = (
        f"Translate each string in this JSON array into {target}, keeping numbers, dates and proper nouns. "
        "Return ONLY a JSON object {\"t\":[\"\"]} with the same number and order of items, no commentary.\n\n"
        + json.dumps({"t": texts}, ensure_ascii=False))
    out = gemini_generate(prompt, json_mode=True)
    if not out:
        return gov
    try:
        tr = json.loads(out).get("t")
        if isinstance(tr, list) and len(tr) == len(gov):
            return [{"t": (t if isinstance(t, str) and t.strip() else o["t"]), "links": o["links"]}
                    for o, t in zip(gov, tr)]
    except Exception as ex:
        print(f"[warn] translate_gov {lang} failed: {ex}")
    return gov


def render_qatar_gov(gov, lang="ko"):
    """카타르 정부 동향 섹션 — '오늘 일일 요약'과 동일한 섹션 제목(왼쪽 바) + 이슈 박스와 같은 모양의 흰색 박스.
    항상 표시, 동향 없으면 '금일 별도 동향 무'. 각 동향에 출처 링크(↗) 포함."""
    L = LANG.get(lang, LANG["ko"])
    head = f'<div class="sumhead"><span class="bar"></span>{esc(L["gov_head"])}</div>'
    if gov:
        lis = []
        for g in gov:
            chips = "".join(
                f'<a class="govlink" href="{esc(u)}" target="_blank" rel="noopener">↗ {esc(s)}</a>'
                for s, u in (g.get("links") or []) if u)
            lis.append(f'<li>{esc(g["t"])}{(" " + chips) if chips else ""}</li>')
        body = '<ul class="govul">' + "".join(lis) + "</ul>"
    else:
        body = f'<div class="govnone">{esc(L["gov_none"])}</div>'
    return head + f'<div class="govcard">{body}</div>'


# ───────────────────── 렌더링 ─────────────────────
def ago(dt, now, L=None):
    L = L or LANG["ko"]
    m = int((now - dt).total_seconds() // 60)
    if m < 60: return L["ago_min"].format(n=m)
    if m < 1440: return L["ago_hr"].format(n=m // 60)
    return L["ago_day"].format(n=m // 1440)


def esc(s):
    return html.escape(s or "", quote=True)


def li(x, now_utc, L=None):
    L = L or LANG["ko"]
    d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
    meta = " · ".join([esc(x["source"]), d, ago(x["dt"], now_utc, L)])
    desc = f'<div class="dsc">{esc(x["desc"])}</div>' if x["desc"] else ""
    return (f'<li><a href="{esc(x["link"])}" target="_blank" rel="noopener">{esc(x["title"])}</a>'
            f'{desc}<div class="meta">({meta})</div></li>')


def _clean_bullet(s):
    s = str(s or "")
    s = re.sub(r"\(\s*(?:기사|article|مقال)[^)]*\)", "", s, flags=re.I)   # (기사 8·21) 류 표기 제거
    s = re.sub(r"\s*[,，]?\s*(?:기사|article)\s*\d+(?:\s*[·,]\s*\d+)*", "", s, flags=re.I)  # '…, 기사 8' 같은 내부 잔여 표기 제거
    s = re.sub(r"\(\s*\)", "", s)  # 위 제거로 빈 괄호가 남으면 정리
    s = re.sub(r"^\s*\d{1,2}\s*[/·.\-]\s*\d{1,2}\.?\s*", "", s)            # 문두 날짜(7/31 등) 제거
    return re.sub(r"\s{2,}", " ", s).strip()


def _summary_bullets(summary):
    if isinstance(summary, list):
        items = summary
    else:
        s = str(summary or "")
        items = re.split(r"\n+", s) if "\n" in s else [s]
    return [c for c in (_clean_bullet(x) for x in items) if c]


def link_row(x):
    d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")   # 게재 시각까지 표기(모니터링 기간 내 최신순 확인용)
    return (f'<a href="{esc(x["link"])}" target="_blank" rel="noopener">{esc(x["title"])}'
            f'<span class="src">{esc(x["source"])} · {d}</span></a>')


def render_issues(issues, pool, now_utc, L=None, collapse_links=False):
    L = L or LANG["ko"]
    out = []
    for n, iss in enumerate((i for i in issues if isinstance(i, dict)), 1):
        theme = esc(str(iss.get("theme", f"{L['issue']} {n}")))
        bullets = _summary_bullets(iss.get("summary", ""))
        body = ('<ul class="sumbul">' + "".join(f'<li>{esc(b)}</li>' for b in bullets) + '</ul>') if bullets else ""
        # 이슈의 유효 ids 먼저 계산(※ 박스 근거 링크 폴백에 사용)
        raw_ids = iss.get("ids")
        ids = [j for j in (raw_ids if isinstance(raw_ids, list) else []) if isinstance(j, int) and 0 <= j < len(pool)]
        # 카타르 직접 피격·피해가 이 사안에 포함되면 별도 이슈로 빼지 않고 이슈 내부에 ※ 박스로 상세 표기
        qi_items = _summary_bullets(iss.get("qatar_impact", ""))
        # ※ 박스 근거 출처를 ↗ 외부링크 칩으로. 모델이 qatar_impact_ids를 주면 그걸 쓰고,
        #  안 주면 요약 텍스트에 언급된 출처명 → (없으면) 제목에 '카타르/Qatar' 포함 기사로 자동 매칭(폴백).
        _qraw = iss.get("qatar_impact_ids")
        qi_ids = [j for j in (_qraw if isinstance(_qraw, list) else []) if isinstance(j, int) and 0 <= j < len(pool)]
        if qi_items and not qi_ids:
            _qtxt = " ".join(str(x) for x in (iss.get("qatar_impact") if isinstance(iss.get("qatar_impact"), list) else [iss.get("qatar_impact") or ""])).lower()
            for j in ids:
                _k = (pool[j].get("source") or "").split()
                if _k and _k[0].lower() in _qtxt:
                    qi_ids.append(j)
            if not qi_ids:
                _cand = [j for j in ids if ("qatar" in (pool[j].get("title") or "").lower() or "카타르" in (pool[j].get("title") or ""))]
                _cand.sort(key=lambda j: 0 if pool[j]["region"] != "korea" else 1)
                qi_ids = _cand[:2]
            qi_ids = qi_ids[:4]
        _seen_q = set()
        qi_links = ""
        for j in qi_ids:
            if j in _seen_q:
                continue
            _seen_q.add(j)
            a = pool[j]
            qi_links += (f'<a class="qlink" href="{esc(a["link"])}" target="_blank" rel="noopener" '
                         f'title="{esc(a["title"])}"><span class="ic">↗</span>{esc(a["source"])}</a>')
        qbox = (f'<div class="qimpact"><div class="qh">※ {esc(L["qbox"])}</div>'
                + '<ul class="qbul">' + "".join(f'<li>{esc(b)}</li>' for b in qi_items) + '</ul>'
                + (f'<div class="qlinks">{qi_links}</div>' if qi_links else "")
                + '</div>') if qi_items else ""
        arts = [pool[j] for j in ids]
        _recent = lambda lst: sorted(lst, key=lambda a: a["dt"], reverse=True)   # 권역 그룹 내 최신 기사 순
        q = _recent([a for a in arts if a["region"] == "qatar"])
        ir = _recent([a for a in arts if a["region"] == "iran"])
        ov = _recent([a for a in arts if a["region"] == "overseas"])
        kr = _recent([a for a in arts if a["region"] == "korea"])
        groups = ""
        if q:  groups += f'<div class="grp"><div class="gh">{esc(L["g_qatar"])}</div>' + "".join(link_row(a) for a in q) + '</div>'
        if ir: groups += f'<div class="grp"><div class="gh">{esc(L["g_iran"])}</div>' + "".join(link_row(a) for a in ir) + '</div>'
        if ov: groups += f'<div class="grp"><div class="gh">{esc(L["g_over"])}</div>' + "".join(link_row(a) for a in ov) + '</div>'
        if kr: groups += f'<div class="grp"><div class="gh">{esc(L["g_korea"])}</div>' + "".join(link_row(a) for a in kr) + '</div>'
        if not groups:
            groups = f'<div class="grp"><div class="gh" style="color:var(--muted)">{esc(L["nomap"])}</div></div>'
        head = f'<div class="issue"><div class="ihead"><span class="num">{esc(L["issue"])} {n}</span><h2>{theme}</h2></div>'
        if collapse_links:
            # 주간: 요약을 전폭으로 보여 흐름을 직관적으로 읽게 하고, 이슈별 관련 링크는 접어두기(펼치면 표시)
            out.append(
                head
                + f'<div class="row solo"><div class="left" style="border-inline-end:none">{qbox}<div class="sh">{esc(L["key_sum"])}</div>{body}</div></div>'
                + f'<details class="linkfold"><summary>{esc(L["links_fold"])}</summary><div class="foldwrap">{groups}</div></details>'
                + '</div>')
        else:
            out.append(
                head
                + f'<div class="row"><div class="left">{qbox}<div class="sh">{esc(L["key_sum"])}</div>{body}</div>'
                + f'<div class="right">{groups}</div></div></div>')
    return "\n".join(out)


def summary_to_html(text):
    out = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        e = html.escape(line, quote=True)
        e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
        if line.lstrip().startswith("■"):
            out.append(f'<div class="sh">{e.replace("■", "").strip()}</div>')
        elif line.lstrip().startswith(("-", "•", "*")):
            out.append(f'<div class="bl">{e.lstrip("-•* ").strip()}</div>')
        else:
            out.append(f'<div class="pl">{e}</div>')
    return "\n".join(out)


def _ql_key(item):
    """관심 매체 정렬키: 한글명은 가나다 우선, 그다음 ABC(대소문자 무시)."""
    name = item[0] or ""
    first = name[0] if name else ""
    is_hangul = "가" <= first <= "힣"
    return (0 if is_hangul else 1, name.lower())


# ── 중동 전쟁 주요 일지(타임라인) — 공신력 있는 공개 출처(CFR·Wikipedia '2026 Iranian strikes on Qatar'·Stars and Stripes 등) 기반, 최신순.
# 새 사건이 생기면 이 리스트 맨 앞에 dict 하나만 추가하면 됨. q=True는 카타르 직접 관련.
TIMELINE = [
  {"d": "2026-08-01", "q": False, "note": {"ko": "미국시각", "en": "U.S. time", "ar": "بتوقيت أمريكا"},
   "ko": "트럼프, 이란 추가 대규모 공습 전격 취소 발표 — '합의의 윤곽' 마련·이란 등의 보류 요청 수용, 호르무즈 전면 개방과 '핵 위협' 종식을 조건으로 제시.",
   "en": "Trump abruptly cancels a planned large-scale strike on Iran, citing agreed 'parameters of a deal' and Tehran's request for a pause; sets full reopening of Hormuz and ending the 'nuclear threat' as conditions.",
   "ar": "ترامب يلغي فجأة ضربة واسعة مخطّطة على إيران، مشيراً إلى 'معالم اتفاق' وطلب طهران وقفاً؛ ويشترط إعادة فتح هرمز بالكامل وإنهاء 'التهديد النووي'."},
  {"d": "2026-07-30", "q": False,
   "ko": "이집트 최초 피격 — 드론이 지중해 다미에타 항의 선박 2척(가스선)을 타격, 이집트가 확전 경고. 전쟁이 에너지 인프라·역내로 확산되며 이집트가 처음으로 표적이 됨(후티는 관여 부인).",
   "en": "Egypt struck for the first time — a drone hits two (gas) ships at the Damietta Mediterranean port; Egypt warns of escalation. The war widens to energy infrastructure with Egypt targeted for the first time (Houthis deny involvement).",
   "ar": "استهداف مصر لأول مرة — مسيّرة تضرب سفينتين (للغاز) في ميناء دمياط المتوسطي، ومصر تحذّر من التصعيد. تتّسع الحرب لتطال البنية التحتية للطاقة مع استهداف مصر للمرة الأولى (والحوثيون ينفون الضلوع)."},
  {"d": "2026-07-28", "q": False,
   "ko": "사우디아라비아가 이라크 내 친이란 민병대를 겨냥한 미국의 공습에 가담 — 사우디의 참전.",
   "en": "Saudi Arabia joins U.S. strikes on Iran-backed militias in Iraq, marking Riyadh's entry into the war.",
   "ar": "السعودية تنضم إلى الضربات الأمريكية على الميليشيات المدعومة من إيران في العراق، إيذاناً بدخولها الحرب."},
  {"d": "2026-07-27", "q": False,
   "ko": "13일 연속 야간 공습 끝에 미국이 폭격을 중단하고, 이란도 조건부로 공격을 멈춤.",
   "en": "After 13 consecutive nights of strikes, the U.S. halts bombing and Iran conditionally suspends its attacks.",
   "ar": "بعد 13 ليلة متتالية من الضربات، توقف الولايات المتحدة قصفها وتعلّق إيران هجماتها بشروط."},
  {"d": "2026-07-13", "q": False,
   "ko": "트럼프, 호르무즈 해협 봉쇄와 통항 20% 통행료 부과 방침 발표 — 이란은 복수의 걸프국을 타격.",
   "en": "Trump announces a naval blockade of the Strait of Hormuz with a 20% transit toll; Iran strikes multiple Gulf states.",
   "ar": "ترامب يعلن حصاراً بحرياً لمضيق هرمز مع رسم عبور 20%؛ وإيران تضرب عدة دول خليجية."},
  {"d": "2026-07-08", "q": False,
   "ko": "이란이 바레인·쿠웨이트 주둔 미군 시설에 미사일·드론 공격 → 트럼프 '휴전 종료' 선언.",
   "en": "Iran fires missiles and drones at U.S. installations in Bahrain and Kuwait; Trump declares the ceasefire 'over.'",
   "ar": "إيران تطلق صواريخ ومسيّرات على منشآت أمريكية في البحرين والكويت؛ وترامب يعلن انتهاء وقف إطلاق النار."},
  {"d": "2026-07-01", "q": True,
   "ko": "미국·이란 협상단이 카타르에서 중재국과 각각 회동(직접 대화는 없음) — 카타르의 중재 무대 역할 부각.",
   "en": "U.S. and Iranian negotiators meet separately with mediators in Qatar (no direct talks), underscoring Doha's mediation role.",
   "ar": "مفاوضون أمريكيون وإيرانيون يجتمعون منفصلين مع وسطاء في قطر (دون محادثات مباشرة)، ما يؤكد دور الدوحة كوسيط."},
  {"d": "2026-07-01", "q": True,
   "ko": "카타르 LNG 불가항력이 4개월째 지속 — 이탈리아 에디슨 등 일부 계약은 9월까지 연장, 글로벌 LNG 공급 차질 장기화.",
   "en": "Qatar's LNG force majeure enters its fourth month — some contracts (e.g., Italy's Edison) extended into September, prolonging the disruption to global LNG supply.",
   "ar": "القوة القاهرة على الغاز المسال القطري تدخل شهرها الرابع — وتُمدَّد بعض العقود (مثل شركة إديسون الإيطالية) حتى سبتمبر، ما يُطيل اضطراب إمدادات الغاز المسال عالمياً."},
  {"d": "2026-06-28", "q": True,
   "ko": "군사작전 중 파편으로 카타르 국민 1명 사망, 이집트인 1명 부상 — 개전 이후 카타르 내 첫 사망자.",
   "en": "One Qatari national is killed and an Egyptian injured by shrapnel during military operations — the first death inside Qatar since the war began.",
   "ar": "مقتل مواطن قطري وإصابة مصري بشظايا أثناء العمليات العسكرية — أول وفاة داخل قطر منذ بدء الحرب."},
  {"d": "2026-06-25", "q": False,
   "ko": "이란 드론이 호르무즈에서 상선을 타격, 국제 대피 작전이 중단됨.",
   "en": "An Iranian drone strikes a commercial vessel in the Strait of Hormuz, halting international evacuation operations.",
   "ar": "مسيّرة إيرانية تضرب سفينة تجارية في مضيق هرمز، ما يوقف عمليات الإجلاء الدولية."},
  {"d": "2026-06-21", "q": True,
   "ko": "라스라판 바르잔 가스공장 시운전 중 폭발 — 2025년 12월 정비로 가동중단됐다가 이틀 전 재가동한 바르잔 가스처리시설에서 폭발해 13명 사망(인도인 12·파키스탄인 1)·66명 부상·초기 실종 18명. 에너지장관 알카비는 '사보타주·적대행위가 아닌 기술적 사고'로 규정하고 LNG 수출능력에는 영향이 없다고 밝힘.",
   "en": "Explosion during restart at Ras Laffan's Barzan gas plant — the Barzan gas-processing facility, halted since December 2025 for maintenance and restarted two days earlier, explodes, killing 13 (12 Indians, 1 Pakistani), injuring 66 and leaving 18 initially missing. Energy Minister Al Kaabi rules it a technical accident — not sabotage or a hostile act — and says LNG export capacity is unaffected.",
   "ar": "انفجار أثناء إعادة تشغيل مصنع برزان للغاز في رأس لفان — تعرّض مرفق معالجة الغاز في برزان، الذي كان متوقفاً منذ ديسمبر 2025 للصيانة وأُعيد تشغيله قبل يومين، لانفجار أودى بحياة 13 شخصاً (12 هندياً وباكستانياً واحداً) وأصاب 66 وترك 18 في عداد المفقودين مبدئياً. ووصفه وزير الطاقة الكعبي بأنه حادث تقني — لا تخريب ولا عمل عدائي — مؤكداً عدم تأثّر قدرة تصدير الغاز المسال."},
  {"d": "2026-06-20", "q": False,
   "ko": "이란이 레바논 휴전 위반을 주장하며 호르무즈 해협을 다시 봉쇄.",
   "en": "Iran again closes the Strait of Hormuz, alleging violations of the Lebanon ceasefire.",
   "ar": "إيران تغلق مضيق هرمز مجدداً، متّهمةً الطرف الآخر بانتهاك وقف إطلاق النار في لبنان."},
  {"d": "2026-06-17", "q": False,
   "ko": "트럼프와 이란 대통령이 3천억 달러 규모 투자기금을 포함한 프레임워크 합의에 서명.",
   "en": "Trump and Iran's president sign a framework agreement that includes a $300 billion investment fund.",
   "ar": "ترامب والرئيس الإيراني يوقّعان اتفاقاً إطارياً يتضمّن صندوق استثمار بقيمة 300 مليار دولار."},
  {"d": "2026-06-14", "q": False,
   "ko": "파키스탄 중재로 잠정 합의 — 호르무즈 재개방, 레바논 휴전, 60일 적대행위 중단 포함.",
   "en": "A Pakistan-mediated interim deal is signed: reopening Hormuz, a Lebanon ceasefire, and a 60-day halt to hostilities.",
   "ar": "توقيع اتفاق مؤقت بوساطة باكستانية يشمل إعادة فتح هرمز ووقف إطلاق النار في لبنان ووقف الأعمال العدائية 60 يوماً."},
  {"d": "2026-06-08", "q": False,
   "ko": "트럼프의 휴전 촉구에 이란과 이스라엘이 상호 군사작전 종료를 발표.",
   "en": "Following Trump's call for a ceasefire, Iran and Israel announce a mutual end to military operations.",
   "ar": "عقب دعوة ترامب لوقف إطلاق النار، تعلن إيران وإسرائيل إنهاءً متبادلاً للعمليات العسكرية."},
  {"d": "2026-05-03", "q": False,
   "ko": "트럼프가 호르무즈 통항 상선을 호위하는 '프로젝트 프리덤'을 발표(5/5 교전으로 일시 중단, 상선 2척 통항 성공).",
   "en": "Trump launches 'Project Freedom' to escort commercial vessels through Hormuz (paused May 5 amid clashes; two vessels transit successfully).",
   "ar": "ترامب يطلق 'مشروع الحرية' لمرافقة السفن التجارية عبر هرمز (عُلّق في 5 مايو بسبب اشتباكات، ونجح عبور سفينتين)."},
  {"d": "2026-04-07", "q": False,
   "ko": "초기 대규모 교전 국면이 끝나고 2주간의 휴전이 성립.",
   "en": "After the initial large-scale fighting phase, a two-week ceasefire takes hold.",
   "ar": "بعد مرحلة القتال الواسع الأولى، يبدأ سريان وقف إطلاق نار لمدة أسبوعين."},
  {"d": "2026-04-01", "q": True,
   "ko": "이란이 순항미사일 3발 발사, 2발 요격되고 1발이 카타르 인근 유조선에 명중 — 인명피해 없음.",
   "en": "Iran fires three cruise missiles; two are intercepted and one hits an oil tanker near Qatar, with no casualties.",
   "ar": "إيران تطلق ثلاثة صواريخ كروز؛ يُعترض اثنان ويصيب ثالث ناقلة نفط قرب قطر دون خسائر بشرية."},
  {"d": "2026-03-25", "q": False,
   "ko": "한국, 카타르 LNG 불가항력 영향 점검 — 산업부는 '카타르 비중이 2026년 약 14%로 낮고 대체 공급이 가능해 수급 문제는 없다'며 모니터링을 지속. 카타르는 한국의 3위 LNG 공급국(전년 716만t/총 4,777만t). 가스공사는 의무비축을 웃도는 재고를 확보했고, 정부는 석탄·원전 발전 확대와 가스발전 축소로 대응.",
   "en": "South Korea assesses the fallout from Qatar's LNG force majeure — the Industry Ministry says supply is secure ('Qatar's share is low at ~14% in 2026 and alternatives are available') while continuing to monitor. Qatar is Korea's third-largest LNG supplier (7.16 of 47.77 million tonnes the prior year). KOGAS holds inventories above mandatory reserves, and the government leans on more coal and nuclear generation while cutting gas-fired output.",
   "ar": "كوريا الجنوبية تقيّم تداعيات القوة القاهرة على الغاز القطري — وزارة الصناعة تقول إن الإمدادات آمنة ('حصة قطر منخفضة عند نحو 14% في 2026 وتتوفّر بدائل') مع مواصلة المراقبة. وقطر ثالث أكبر مورّد للغاز المسال لكوريا (7.16 من أصل 47.77 مليون طن في العام السابق). وتحتفظ كوغاز بمخزونات تفوق الاحتياطي الإلزامي، وتعتمد الحكومة على زيادة توليد الفحم والنووي مع خفض التوليد الغازي."},
  {"d": "2026-03-24", "q": True,
   "ko": "카타르에너지, 라스라판 피해로 LNG 장기계약에 '불가항력(force majeure)' 선언 — 14개 LNG 트레인 중 2개+GTL 1기 손상으로 수출능력 약 17%(연 1,280만t) 상실, 한국·이탈리아·벨기에·중국 4개국 수입에 영향, 연 200억 달러 손실 추정.",
   "en": "QatarEnergy declares force majeure on long-term LNG contracts after the Ras Laffan damage — with 2 of 14 LNG trains and one GTL plant hit, it loses ~17% of export capacity (12.8 mtpa) and affects buyers in South Korea, Italy, Belgium and China; estimated $20bn in lost annual revenue.",
   "ar": "قطر للطاقة تعلن 'القوة القاهرة' على عقود الغاز المسال طويلة الأجل بعد أضرار رأس لفان — مع تضرّر قطارين من أصل 14 ومنشأة GTL واحدة، تفقد نحو 17% من طاقة التصدير (12.8 مليون طن سنوياً) وتتأثّر مشتريات كوريا الجنوبية وإيطاليا وبلجيكا والصين؛ وخسائر سنوية تُقدَّر بـ20 مليار دولار."},
  {"d": "2026-03-23", "q": False,
   "ko": "트럼프가 이란 발전소 공습을 5일간 유예한다고 발표하며 '생산적 대화'를 주장(이란은 직접 대화 부인).",
   "en": "Trump announces a five-day pause on strikes against Iranian power plants, claiming 'productive' talks (Iran denies any direct negotiations).",
   "ar": "ترامب يعلن تعليقاً لخمسة أيام للضربات على محطات الطاقة الإيرانية مدّعياً محادثات 'مثمرة' (وإيران تنفي أي مفاوضات مباشرة)."},
  {"d": "2026-03-19", "q": True,
   "ko": "라스라판 가동중단이 헬륨 공급으로 확산 — 헬륨은 LNG 생산의 부산물이라 LNG가 멈추면 함께 끊겨 세계 헬륨 공급의 약 11%(카타르 물량의 약 30%)가 차질, 반도체 제조 리스크 부각(특히 한국·대만이 최대 노출).",
   "en": "The Ras Laffan shutdown spreads to helium — a byproduct of LNG, so no LNG means no helium — putting ~11% of global helium supply (about 30% of Qatar's 2026 volume) at risk and raising semiconductor-manufacturing risk, with South Korea and Taiwan most exposed.",
   "ar": "توقّف رأس لفان يمتدّ إلى الهيليوم — وهو منتج ثانوي للغاز المسال، فتوقُّف الغاز يوقفه أيضاً — ما يعرّض نحو 11% من الإمداد العالمي للهيليوم (نحو 30% من حجم قطر لعام 2026) للخطر ويرفع مخاطر تصنيع أشباه الموصلات، وكوريا الجنوبية وتايوان الأكثر تعرّضاً."},
  {"d": "2026-03-18", "q": True,
   "ko": "이란이 카타르 라스라판 가스시설을 타격 — LNG 수출 약 17% 차질(복구 3~5년 추정), 카타르는 이란 무관을 24시간 내 추방.",
   "en": "An Iranian strike hits Qatar's Ras Laffan gas facility, disrupting ~17% of LNG exports (repairs estimated at 3–5 years); Qatar expels Iranian attachés within 24 hours.",
   "ar": "ضربة إيرانية تصيب منشأة الغاز في رأس لفان بقطر، معطّلةً نحو 17% من صادرات الغاز المسال (تُقدَّر الإصلاحات بـ3–5 سنوات)؛ وقطر تطرد الملحقين الإيرانيين خلال 24 ساعة."},
  {"d": "2026-03-13", "q": False,
   "ko": "미국, 이란 최대 석유 수출 터미널 카르그섬 공습 — 이란 원유 수출의 대부분(약 90%)을 처리하는 카르그섬이 피격돼 이란 원유 수출·국제유가에 큰 충격(트럼프 '이란 석유경제 핵심 타격' 발표).",
   "en": "U.S. strikes Iran's main oil-export terminal, Kharg Island — the island handling about 90% of Iran's crude exports is hit, a major blow to Iranian oil exports and global oil prices (Trump says it struck the core of Iran's oil economy).",
   "ar": "الولايات المتحدة تضرب جزيرة خرج، المحطة الرئيسية لتصدير النفط الإيراني التي تعالج نحو 90% من صادرات الخام الإيرانية — ما وجّه ضربة كبيرة لصادرات النفط وأسعاره عالمياً (وترامب يقول إنها ضربت قلب الاقتصاد النفطي الإيراني)."},
  {"d": "2026-03-11", "q": True,
   "ko": "카타르가 밤사이 이란의 미사일·드론을 요격.",
   "en": "Qatar intercepts Iranian missiles and drones overnight.",
   "ar": "قطر تعترض صواريخ ومسيّرات إيرانية خلال الليل."},
  {"d": "2026-03-03", "q": True,
   "ko": "이란 미사일이 알우데이드 공군기지에 명중 — 인명피해는 보고되지 않음.",
   "en": "An Iranian missile hits Al Udeid Air Base; no casualties are reported.",
   "ar": "صاروخ إيراني يصيب قاعدة العديد الجوية دون تسجيل خسائر بشرية."},
  {"d": "2026-03-02", "q": True,
   "ko": "이란이 하마드국제공항을 재차 겨냥(요격), 카타르 F-15가 Su-24 폭격기 2대를 격추(첫 공대공 전과), 드론이 라스라판·메사이드 산업지구를 타격.",
   "en": "Iran again targets Hamad International Airport (intercepted); Qatari F-15s down two Su-24 bombers (first air-to-air kills), while drones hit the Ras Laffan and Mesaieed industrial areas.",
   "ar": "إيران تستهدف مطار حمد الدولي مجدداً (تم اعتراضه)؛ ومقاتلات F-15 القطرية تسقط قاذفتي Su-24 (أول إسقاط جوي)، بينما تضرب مسيّرات منطقتي رأس لفان ومسيعيد الصناعيتين."},
  {"d": "2026-02-28", "q": True,
   "ko": "이란 보복 개시 — 카타르에 미사일 66발(대부분 요격, 16명 부상)과 하마드공항 겨냥으로 영공 폐쇄; 알우데이드·바레인 5함대·쿠웨이트 미군기지와 이스라엘도 동시 타격.",
   "en": "Iran's retaliation begins — 66 missiles at Qatar (mostly intercepted, 16 injured) and a strike aimed at Hamad Airport close Qatari airspace; Al Udeid, the Fifth Fleet in Bahrain, U.S. bases in Kuwait, and Israel are hit simultaneously.",
   "ar": "بدء الرد الإيراني — 66 صاروخاً على قطر (اعتُرض معظمها وأُصيب 16) واستهداف مطار حمد يغلقان الأجواء القطرية؛ وتُضرب في الوقت نفسه العديد والأسطول الخامس في البحرين وقواعد أمريكية في الكويت وإسرائيل."},
  {"d": "2026-02-28", "q": False,
   "ko": "미국·이스라엘이 이란 핵·군사시설을 동시 기습 공습(하메네이 사망 보도) — 중동 전쟁 발발.",
   "en": "The U.S. and Israel launch simultaneous surprise strikes on Iran's nuclear and military sites (Khamenei reported killed) — the Middle East war breaks out.",
   "ar": "الولايات المتحدة وإسرائيل تشنّان ضربات مفاجئة متزامنة على مواقع إيران النووية والعسكرية (أنباء عن مقتل خامنئي) — اندلاع حرب الشرق الأوسط."},
]

_TL_MON = {"ko": ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"]}

# 타임라인 정리에 사용한 공신력 있는 공개 출처(하단에 작고 연하게 링크로 표기)
TL_SOURCES = [
    ("CFR Global Conflict Tracker", "https://www.cfr.org/global-conflict-tracker"),
    ("Al Jazeera", "https://www.aljazeera.com/"),
    ("CNN", "https://www.cnn.com/"),
    ("Reuters", "https://www.reuters.com/"),
    ("AP News", "https://apnews.com/"),
    ("CNBC", "https://www.cnbc.com/"),
    ("The Peninsula", "https://thepeninsulaqatar.com/"),
    ("Doha News", "https://dohanews.co/"),
    ("Fox Business", "https://www.foxbusiness.com/"),
    ("Gulf News", "https://gulfnews.com/"),
    ("AGBI (Arabian Gulf Business Insight)", "https://www.agbi.com/"),
    ("Stars and Stripes", "https://www.stripes.com/"),
    ("Wikipedia — 2026 Iran war / Iranian strikes on Qatar", "https://en.wikipedia.org/wiki/2026_Iranian_strikes_on_Qatar"),
]

def _timeline_rows(lang="ko"):
    L = LANG.get(lang, LANG["ko"])
    rows = []
    for e in TIMELINE:
        y, m, d = e["d"].split("-")
        mi = int(m)
        if lang == "ko":
            datestr = f'<span class="tly">{y}</span><span class="tlmd">{mi}월 {int(d)}일</span>'
        else:
            datestr = f'<span class="tly">{y}</span><span class="tlmd">{mi:02d}/{int(d):02d}</span>'
        note = e.get("note", {}).get(lang, "") if e.get("note") else ""
        note_html = f' <span class="tlnote">({esc(note)})</span>' if note else ""
        qcls = " q" if e.get("q") else ""
        qbadge = f'<span class="tlq">{esc(L["tl_q"])}</span>' if e.get("q") else ""
        rows.append(
            f'<div class="tlrow{qcls}"><div class="tldot"></div>'
            f'<div class="tldate">{datestr}</div>'
            f'<div class="tlbody">{qbadge}{esc(e.get(lang) or e.get("ko"))}{note_html}</div></div>')
    return '<div class="tlwrap">' + "".join(rows) + '</div>'

def _timeline_sources_html(lang="ko"):
    L = LANG.get(lang, LANG["ko"])
    items = " · ".join(
        f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)}</a>' for n, u in TL_SOURCES)
    return (f'<div class="tlsrc"><span class="tlsrc-l">{esc(L["tl_src_label"])}</span> {items}'
            f'<div class="tlsrc-n">{esc(L["tl_src_note"])}</div></div>')

def timeline_ref(lang="ko"):
    # 별도 버튼 대신 '모니터링 부문' 박스 안에 참고 링크로 삽입 (본문과 동일 크기, 언어버튼 색)
    L = LANG.get(lang, LANG["ko"])
    url = f"{SITE_BASE}timeline-{lang}.html"
    return (f'<span class="tldiv"></span>'
            f'<span class="tlref">📌 {esc(L["tl_tag"])}: '
            f'<a href="{esc(url)}" target="_blank" rel="noopener">🗓️ {esc(L["tl_head"])} →</a></span>')

def render_timeline_page(lang="ko"):
    L = LANG.get(lang, LANG["ko"])
    home = SITE_BASE if lang == "ko" else f"{SITE_BASE}{lang}.html"
    # 엑셀 내보내기용 데이터(사건 텍스트를 ' — ' 기준으로 제목/상세 분리)
    tldata = []
    for e in TIMELINE:
        txt = e.get(lang) or e.get("ko")
        parts = txt.split(" — ", 1)
        tldata.append({"iso": e["d"], "q": 1 if e.get("q") else 0,
                       "title": parts[0].strip(), "detail": (parts[1].strip() if len(parts) > 1 else "")})
    cfg = {
        "data": tldata,
        "c_date": L["tl_c_date"], "c_cat": L["tl_c_cat"], "c_event": L["tl_c_event"], "c_detail": L["tl_c_detail"],
        "catq": L["tl_q"], "catgen": L["tl_cat_gen"],
        "fname": L["tl_fname"], "sheet": L["tl_sheet"],
        "widths": [13, 9, 40, 60],
    }
    tlscript = _TL_SCRIPT.replace("__CFG__", json.dumps(cfg, ensure_ascii=False))
    return TIMELINE_PAGE.format(
        dir=L["dir"], htmllang=L["html"], title=esc(L["tl_head"]),
        tag=esc(L["tl_tag"]), head=esc(L["tl_head"]), note=esc(L["tl_note"]),
        rows=_timeline_rows(lang), sources=_timeline_sources_html(lang),
        back=esc(L["tl_back"]), home=esc(home),
        f_all=esc(L["tl_all"]), f_qonly=esc(L["tl_qonly"]), f_qex=esc(L["tl_qex"]), dl=esc(L["tl_dl"]),
        tlscript=tlscript)


# 타임라인 필터 + 인쇄 최적화 XLSX(순수 클라이언트, 라이브러리·서버 불필요) 생성 스크립트
_TL_SCRIPT = r"""(function(){
var CFG=__CFG__;var cur='all';
var rows=Array.prototype.slice.call(document.querySelectorAll('.tlwrap .tlrow'));
function applyFilter(f){cur=f;rows.forEach(function(r){var q=r.classList.contains('q');var show=(f==='all')||(f==='q'&&q)||(f==='ex'&&!q);r.style.display=show?'':'none';});
Array.prototype.forEach.call(document.querySelectorAll('.tlfbtn'),function(b){b.classList.toggle('on',b.getAttribute('data-f')===f);});}
Array.prototype.forEach.call(document.querySelectorAll('.tlfbtn'),function(b){b.addEventListener('click',function(){applyFilter(b.getAttribute('data-f'));});});
// ---- 순수 JS XLSX(무압축 ZIP) ----
var crcT=(function(){var t=[];for(var n=0;n<256;n++){var c=n;for(var k=0;k<8;k++){c=(c&1)?(0xEDB88320^(c>>>1)):(c>>>1);}t[n]=c>>>0;}return t;})();
function crc32(b){var c=0xFFFFFFFF;for(var i=0;i<b.length;i++){c=crcT[(c^b[i])&0xFF]^(c>>>8);}return (c^0xFFFFFFFF)>>>0;}
function SB(s){return new TextEncoder().encode(s);}
function u16(n){return [n&0xFF,(n>>8)&0xFF];}function u32(n){return [n&0xFF,(n>>8)&0xFF,(n>>16)&0xFF,(n>>24)&0xFF];}
function zip(files){var parts=[],cen=[],off=0;
files.forEach(function(f){var nm=SB(f.name),crc=crc32(f.data),sz=f.data.length;
var lh=new Uint8Array([].concat(u32(0x04034b50),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(sz),u32(sz),u16(nm.length),u16(0)));
parts.push(lh,nm,f.data);
cen.push(new Uint8Array([].concat(u32(0x02014b50),u16(20),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(sz),u32(sz),u16(nm.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(off))),nm);
off+=lh.length+nm.length+f.data.length;});
var cstart=off,csz=0;cen.forEach(function(x){csz+=x.length;});
var end=new Uint8Array([].concat(u32(0x06054b50),u16(0),u16(0),u16(files.length),u16(files.length),u32(csz),u32(cstart),u16(0)));
var all=parts.concat(cen,[end]),tot=all.reduce(function(a,x){return a+x.length;},0),out=new Uint8Array(tot),p=0;
all.forEach(function(x){out.set(x,p);p+=x.length;});return out;}
function X(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function col(c){var s='';c++;while(c>0){var m=(c-1)%26;s=String.fromCharCode(65+m)+s;c=Math.floor((c-1)/26);}return s;}
function cel(r,c,v,st){return '<c r="'+col(c)+r+'" t="inlineStr" s="'+st+'"><is><t xml:space="preserve">'+X(v)+'</t></is></c>';}
function buildXlsx(headers,body){
var sd='<row r="1">';headers.forEach(function(h,i){sd+=cel(1,i,h,'1');});sd+='</row>';
body.forEach(function(row,ri){var r=ri+2;sd+='<row r="'+r+'">';row.forEach(function(v,ci){sd+=cel(r,ci,v,'2');});sd+='</row>';});
var cols='<cols>';CFG.widths.forEach(function(w,i){cols+='<col min="'+(i+1)+'" max="'+(i+1)+'" width="'+w+'" customWidth="1"/>';});cols+='</cols>';
var lc=col(headers.length-1),lr=body.length+1;
var sheet='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr><dimension ref="A1:'+lc+lr+'"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'+cols+'<sheetData>'+sd+'</sheetData><pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/><pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="0"/></worksheet>';
var styles='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF2F4A6E"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf xfId="0"/><xf fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
var sn=X(CFG.sheet).slice(0,31);
var wb='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="'+sn+'" sheetId="1" r:id="rId1"/></sheets><definedNames><definedName name="_xlnm.Print_Titles" localSheetId="0">\''+sn+'\'!$1:$1</definedName></definedNames></workbook>';
var wbr='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>';
var ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>';
var rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>';
return zip([{name:'[Content_Types].xml',data:SB(ct)},{name:'_rels/.rels',data:SB(rels)},{name:'xl/workbook.xml',data:SB(wb)},{name:'xl/_rels/workbook.xml.rels',data:SB(wbr)},{name:'xl/styles.xml',data:SB(styles)},{name:'xl/worksheets/sheet1.xml',data:SB(sheet)}]);}
function dl(){var d=CFG.data.filter(function(e){return cur==='all'||(cur==='q'&&e.q)||(cur==='ex'&&!e.q);});
var headers=[CFG.c_date,CFG.c_cat,CFG.c_event,CFG.c_detail];
var body=d.map(function(e){return [e.iso,e.q?CFG.catq:CFG.catgen,e.title,e.detail];});
var bytes=buildXlsx(headers,body);
var blob=new Blob([bytes],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
var suf=cur==='q'?'_qatar':(cur==='ex'?'_ex-qatar':'');
var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=CFG.fname+suf+'.xlsx';document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},1500);}
var b=document.getElementById('tldl');if(b)b.addEventListener('click',dl);
})();"""


# 일간/주간 모니터 엑셀(2시트)·워드 내보내기 — 페이지 DOM을 읽어 본사 보고용 문서 생성(순수 클라이언트·무료)
_MON_SCRIPT = r"""(function(){
var URLBASE='https://kotradoha.github.io/qatar-media-monitor/';
var I18={
ko:{s1:'이슈별 요약',s2:'기사 목록',cNo:'번호',cIssue:'이슈',cSum:'요약',cMedia:'매체',cArt:'기사 제목',cDt:'보도일시',wMedia:'발췌 매체',edD:'일간 제{n}호',edW:'주간 종합',lPer:'모니터링 기간',lUpd:'모니터링 일시',org:'주카타르대사관 Commercial Section · KOTRA 도하무역관',note:'본 자료는 공개 언론 보도를 AI로 자동 요약·정리한 참고용 모니터링 결과입니다. 정확한 내용·수치는 각 매체 원문 링크를 확인하시기 바랍니다.',fname:'카타르_언론모니터링'},
en:{s1:'Issue summaries',s2:'Article list',cNo:'No.',cIssue:'Issue',cSum:'Summary',cMedia:'Outlet',cArt:'Article',cDt:'Published',wMedia:'Cited outlets',edD:'Daily No.{n}',edW:'Weekly review',lPer:'Coverage',lUpd:'Compiled',org:'Embassy of the ROK in Qatar, Commercial Section · KOTRA Doha',note:'An AI-assisted digest of public media reporting, for reference only. Please verify details and figures against the original articles.',fname:'Qatar_Media_Monitor'},
ar:{s1:'ملخصات القضايا',s2:'قائمة المقالات',cNo:'الرقم',cIssue:'القضية',cSum:'الملخص',cMedia:'الوسيلة',cArt:'المقال',cDt:'تاريخ النشر',wMedia:'الوسائل',edD:'العدد اليومي {n}',edW:'المراجعة الأسبوعية',lPer:'فترة الرصد',lUpd:'وقت الرصد',org:'سفارة جمهورية كوريا لدى قطر · القسم التجاري · كوترا الدوحة',note:'موجز بمساعدة الذكاء الاصطناعي لتقارير إعلامية عامة، للاطلاع فقط. يُرجى التحقّق من التفاصيل والأرقام من المقالات الأصلية.',fname:'rasd_iaalam_qatar'}};
var LANG=(document.documentElement.lang||'ko'); var T=I18[LANG]||I18.ko; var RTL=(LANG==='ar');
function txt(e){return e?(e.textContent||'').replace(/\s+/g,' ').trim():'';}
function scrape(){
  var title=txt(document.querySelector('h1'));
  var sm=document.querySelectorAll('.submeta > span');
  var updated=sm[0]?txt(sm[0]).replace(/^[^:：]*[:：]\s*/,''):'';
  var period=sm[1]?txt(sm[1]).replace(/^[^:：]*[:：]\s*/,''):'';
  // 회차번호(모니터링 일시에서 계산)
  var edn='';var m=updated.match(/(\d{4})\/(\d{1,2})\/(\d{1,2})[^0-9]*?(\d{1,2}):(\d{2})/);
  if(document.body.classList.contains('ed-weekly')){edn=T.edW;}
  else if(m){var y=+m[1],mo=+m[2],da=+m[3],hh=+m[4];var base=Date.UTC(2026,7,1);var cur=Date.UTC(y,mo-1,da);var days=Math.round((cur-base)/86400000);var no=days*2+(hh<12?1:2);if(no>=1)edn=T.edD.replace('{n}',no);}
  var issues=[];
  document.querySelectorAll('.issue').forEach(function(iss){
    var theme=txt(iss.querySelector('.ihead h2'))||txt(iss.querySelector('.ihead'));
    var sum=[];iss.querySelectorAll('.sumbul li').forEach(function(li){var t=txt(li);if(t)sum.push(t);});
    var arts=[],seen={};
    iss.querySelectorAll('a').forEach(function(a){var s=a.querySelector('.src');if(!s)return;
      var st=txt(s);var parts=st.split(' · ');var dt='',src=st;
      if(parts.length>=2 && /\d{1,2}\/\d{1,2}/.test(parts[parts.length-1])){dt=parts.pop().trim();src=parts.join(' · ').trim();}
      var at=txt(a).replace(st,'').trim();
      var key=src+'|'+at;if(seen[key])return;seen[key]=1;
      arts.push({src:src,art:at,dt:dt});});
    if(theme)issues.push({theme:theme,sum:sum,arts:arts});
  });
  return {title:title,updated:updated,period:period,edn:edn,issues:issues};
}
// ===== ZIP(무압축) =====
var crcT=(function(){var t=[];for(var n=0;n<256;n++){var c=n;for(var k=0;k<8;k++){c=(c&1)?(0xEDB88320^(c>>>1)):(c>>>1);}t[n]=c>>>0;}return t;})();
function crc32(b){var c=0xFFFFFFFF;for(var i=0;i<b.length;i++){c=crcT[(c^b[i])&0xFF]^(c>>>8);}return (c^0xFFFFFFFF)>>>0;}
function SB(s){return new TextEncoder().encode(s);}
function u16(n){return [n&0xFF,(n>>8)&0xFF];}function u32(n){return [n&0xFF,(n>>8)&0xFF,(n>>16)&0xFF,(n>>24)&0xFF];}
function zip(files){var parts=[],cen=[],off=0;
files.forEach(function(f){var nm=SB(f.name),crc=crc32(f.data),sz=f.data.length;
var lh=new Uint8Array([].concat(u32(0x04034b50),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(sz),u32(sz),u16(nm.length),u16(0)));
parts.push(lh,nm,f.data);
cen.push(new Uint8Array([].concat(u32(0x02014b50),u16(20),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(sz),u32(sz),u16(nm.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(off))),nm);
off+=lh.length+nm.length+f.data.length;});
var cstart=off,csz=0;cen.forEach(function(x){csz+=x.length;});
var end=new Uint8Array([].concat(u32(0x06054b50),u16(0),u16(0),u16(files.length),u16(files.length),u32(csz),u32(cstart),u16(0)));
var all=parts.concat(cen,[end]),tot=all.reduce(function(a,x){return a+x.length;},0),out=new Uint8Array(tot),p=0;
all.forEach(function(x){out.set(x,p);p+=x.length;});return out;}
function X(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function dl(bytes,mime,name){var blob=new Blob([bytes],{type:mime});var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},1500);}
// ===== XLSX(다중 시트) =====
function colL(c){var s='';c++;while(c>0){var m=(c-1)%26;s=String.fromCharCode(65+m)+s;c=Math.floor((c-1)/26);}return s;}
function cel(r,c,v,st){return '<c r="'+colL(c)+r+'" t="inlineStr" s="'+st+'"><is><t xml:space="preserve">'+X(v)+'</t></is></c>';}
function sheetXml(sh){
  var sd='',r=0;
  (sh.pre||[]).forEach(function(row){r++;sd+='<row r="'+r+'">';row.cells.forEach(function(cc,i){sd+=cel(r,i,cc.v,cc.s);});sd+='</row>';});
  var hr=r+1;sd+='<row r="'+hr+'">';sh.headers.forEach(function(h,i){sd+=cel(hr,i,h,'1');});sd+='</row>';
  sh.rows.forEach(function(row){r=++hr;sd+='<row r="'+hr+'">';row.forEach(function(v,i){sd+=cel(hr,i,v,'2');});sd+='</row>';hr=r;});
  (sh.post||[]).forEach(function(row){hr++;sd+='<row r="'+hr+'">';row.cells.forEach(function(cc,i){sd+=cel(hr,i,cc.v,cc.s);});sd+='</row>';});
  var cols='<cols>';sh.widths.forEach(function(w,i){cols+='<col min="'+(i+1)+'" max="'+(i+1)+'" width="'+w+'" customWidth="1"/>';});cols+='</cols>';
  var hrow=(sh.pre?sh.pre.length:0)+1;
  var af=sh.filter?('<autoFilter ref="A'+hrow+':'+colL(sh.headers.length-1)+hr+'"/>'):'';
  var frz='<pane ySplit="'+hrow+'" topLeftCell="A'+(hrow+1)+'" activePane="bottomLeft" state="frozen"/>';
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'+(RTL?' ':'')+'><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr><sheetViews><sheetView '+(RTL?'rightToLeft="1" ':'')+'workbookViewId="0">'+frz+'</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'+cols+'<sheetData>'+sd+'</sheetData>'+af+'<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/><pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="0"/></worksheet>';
}
function buildXlsx(sheets){
  var styles='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="4"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font><font><sz val="9"/><color rgb="FF7A7A7A"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF2F4A6E"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf xfId="0"/><xf fontId="1" fillId="2" borderId="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf fontId="0" borderId="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf fontId="2" applyFont="1"/><xf fontId="3" applyFont="1" applyAlignment="1"><alignment wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
  var sheetParts=[],wbSheets='',wbRels='',cts='',dn='';
  sheets.forEach(function(sh,i){var id=i+1;var nm=X(sh.name).slice(0,31);
    sheetParts.push({name:'xl/worksheets/sheet'+id+'.xml',data:SB(sheetXml(sh))});
    wbSheets+='<sheet name="'+nm+'" sheetId="'+id+'" r:id="rId'+id+'"/>';
    wbRels+='<Relationship Id="rId'+id+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet'+id+'.xml"/>';
    cts+='<Override PartName="/xl/worksheets/sheet'+id+'.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>';
    var hrow=(sh.pre?sh.pre.length:0)+1;dn+='<definedName name="_xlnm.Print_Titles" localSheetId="'+i+'">\''+nm+'\'!$'+hrow+':$'+hrow+'</definedName>';
  });
  var sid=sheets.length+1;
  var wb='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+wbSheets+'</sheets><definedNames>'+dn+'</definedNames></workbook>';
  var wbr='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+wbRels+'<Relationship Id="rId'+sid+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>';
  var ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'+cts+'<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>';
  var rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>';
  var files=[{name:'[Content_Types].xml',data:SB(ct)},{name:'_rels/.rels',data:SB(rels)},{name:'xl/workbook.xml',data:SB(wb)},{name:'xl/_rels/workbook.xml.rels',data:SB(wbr)},{name:'xl/styles.xml',data:SB(styles)}].concat(sheetParts);
  return zip(files);
}
function exportXlsx(){
  var D=scrape();
  var head=D.title+(D.edn?('  ['+D.edn+']'):'');
  var meta=T.lUpd+': '+D.updated+'    '+T.lPer+': '+D.period;
  // Sheet1: 이슈별 요약
  var s1rows=D.issues.map(function(e,i){return [String(i+1), e.theme, e.sum.map(function(b){return '• '+b;}).join('\n')];});
  var sheet1={name:T.s1,headers:[T.cNo,T.cIssue,T.cSum],rows:s1rows,widths:[6,42,80],
    pre:[{cells:[{v:head,s:'3'}]},{cells:[{v:meta,s:'4'}]},{cells:[{v:'',s:'0'}]}],
    post:[{cells:[{v:'',s:'0'}]},{cells:[{v:T.note,s:'4'}]},{cells:[{v:T.org+'   '+URLBASE,s:'4'}]}]};
  // Sheet2: 기사 목록(정렬용)
  var s2rows=[];D.issues.forEach(function(e){e.arts.forEach(function(a){s2rows.push([e.theme,a.src,a.art,a.dt]);});});
  var sheet2={name:T.s2,headers:[T.cIssue,T.cMedia,T.cArt,T.cDt],rows:s2rows,widths:[34,18,54,16],filter:true};
  dl(buildXlsx([sheet1,sheet2]),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',T.fname+'.xlsx');
}
// ===== DOCX =====
function wp(text,opt){opt=opt||{};var pPr='<w:pPr>'+(RTL?'<w:bidi/>':'')+(opt.align?'<w:jc w:val="'+opt.align+'"/>':'')+(opt.sb||opt.sa?'<w:spacing '+(opt.sb?'w:before="'+opt.sb+'" ':'')+(opt.sa?'w:after="'+opt.sa+'"':'')+'/>':'')+'</w:pPr>';
  var rPr='<w:rPr>'+(opt.b?'<w:b/>':'')+(opt.sz?'<w:sz w:val="'+opt.sz+'"/>':'')+(opt.color?'<w:color w:val="'+opt.color+'"/>':'')+(RTL?'<w:rtl/>':'')+'</w:rPr>';
  return '<w:p>'+pPr+'<w:r>'+rPr+'<w:t xml:space="preserve">'+X(text)+'</w:t></w:r></w:p>';}
function cellXml(w,paras){return '<w:tc><w:tcPr><w:tcW w:w="'+w+'" w:type="dxa"/><w:tcMar><w:top w:w="60" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tcMar></w:tcPr>'+(paras||'<w:p/>')+'</w:tc>';}
function exportDocx(){
  var D=scrape();var LW=7600,RW=2400;
  var body='';
  body+=wp(D.title,{b:true,sz:32,align:'center',sa:60});
  body+=wp((D.edn?D.edn+'   ':'')+T.lUpd+': '+D.updated+'   '+T.lPer+': '+D.period,{sz:18,color:'666666',align:'center',sa:160});
  D.issues.forEach(function(e,i){
    body+=wp((i+1)+'. '+e.theme,{b:true,sz:24,sb:160,sa:60});
    var left=e.sum.map(function(b){return wp('• '+b,{sz:19,sa:40});}).join('')||'<w:p/>';
    var mm=[];var seen={};e.arts.forEach(function(a){if(a.src&&!seen[a.src]){seen[a.src]=1;mm.push(a.src);}});
    var right=mm.map(function(s){return wp('· '+s,{sz:17,color:'444444',sa:20});}).join('')||'<w:p/>';
    body+='<w:tbl><w:tblPr><w:tblW w:w="10000" w:type="dxa"/>'+(RTL?'<w:bidiVisual/>':'')+'<w:tblBorders><w:top w:val="single" w:sz="4" w:color="D0D0D0"/><w:left w:val="single" w:sz="4" w:color="D0D0D0"/><w:bottom w:val="single" w:sz="4" w:color="D0D0D0"/><w:right w:val="single" w:sz="4" w:color="D0D0D0"/><w:insideH w:val="single" w:sz="4" w:color="D0D0D0"/><w:insideV w:val="single" w:sz="4" w:color="D0D0D0"/></w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="'+LW+'"/><w:gridCol w:w="'+RW+'"/></w:tblGrid><w:tr>'+cellXml(LW,left)+cellXml(RW,'<w:p><w:pPr>'+(RTL?'<w:bidi/>':'')+'</w:pPr><w:r><w:rPr><w:b/><w:sz w:val="16"/><w:color w:val="888888"/>'+(RTL?'<w:rtl/>':'')+'</w:rPr><w:t xml:space="preserve">'+X(T.wMedia)+'</w:t></w:r></w:p>'+right)+'</w:tr></w:tbl>';
    body+=wp('',{sz:8});
  });
  body+=wp('',{sz:10});
  body+=wp(T.note,{sz:16,color:'777777',sb:120});
  body+=wp(T.org+'   ·   '+URLBASE,{sz:16,color:'777777'});
  var sect='<w:sectPr>'+(RTL?'<w:bidi/>':'')+'<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>';
  var doc='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+sect+'</w:body></w:document>';
  var ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>';
  var rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>';
  dl(zip([{name:'[Content_Types].xml',data:SB(ct)},{name:'_rels/.rels',data:SB(rels)},{name:'word/document.xml',data:SB(doc)}]),'application/vnd.openxmlformats-officedocument.wordprocessingml.document',T.fname+'.docx');
}
var bx=document.getElementById('dlxlsx');if(bx)bx.addEventListener('click',exportXlsx);
var bd=document.getElementById('dldocx');if(bd)bd.addEventListener('click',exportDocx);
})();"""


def render(items, win_label, issues, flat_text, issue_pool=None, archive_list=None,
           reports=None, edition=None, weekly_inline=None, lang="ko", nav=None, home_url=None, new_since=None,
           weekly_from=None, qatar_gov=None):
    L = LANG.get(lang, LANG["ko"])
    # 모니터링 기간 표기: 주간+일일 동시 발행일(weekly_from 있음)은 두 줄로 (주간)/(일일) 구분
    if weekly_from:
        _wk = L["wk_range"]
        window_html = f'{esc(L["two_wk"])} {esc(_wk)}<br>{esc(L["two_dl"])} {esc(win_label)}'
    else:
        window_html = esc(win_label)
    home_url = home_url or SITE_BASE
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    _wd = {"ko": ["월", "화", "수", "목", "금", "토", "일"],
           "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
           "ar": ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
           }.get(lang, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    # 표시용 모니터링 일시. 특정 회차의 실제 실행이 늦어졌을 때 표기 시각만 정규 슬롯(예: 07:0X·15:3X)으로 보정하기 위한 1회성 override 지원.
    _ov = globals().get("UPDATED_TIME_OVERRIDE")
    _hhmm = _ov if _ov else now_q.strftime('%H:%M')
    updated_str = f"{now_q.strftime('%Y/%m/%d')}({_wd[now_q.weekday()]}) {_hhmm}"
    if issue_pool is None:
        issue_pool = items[:POOL_FOR_ISSUES]
    # 전체 기사 목록 컬럼은 '출처 매체의 권역' 기준으로 분류(한국 매체가 카타르 현지 칸에 섞이지 않도록)
    # 전체 목록은 권역별 상한 없이 전량 노출 → 목록 총계가 상단 '모니터링 건수' 합계와 정확히 일치(4개 권역이 items를 빠짐없이 분할).
    qatar = [x for x in items if x["region"] == "qatar"]
    me_ir = [x for x in items if x["region"] == "iran"]
    me_ov = [x for x in items if x["region"] == "overseas"]
    me_kr = [x for x in items if x["region"] == "korea"]
    # 모니터링 건수: 카타르 관련(현지매체+카타르 키워드) vs 그 외 중동 정세 — 관련성 기준, 미제한 집계
    n_qatar = sum(1 for x in items if x["qatar"] or x["region"] == "qatar")
    n_mideast = len(items) - n_qatar

    def block(rows, empty):
        return "\n".join(li(x, now_utc, L) for x in rows) or f'<li class="empty">{empty}</li>'

    # 주간+일일 동시 발행일(일일 페이지)에는 위 주간 섹션과 헷갈리지 않게 '오늘 일일' 파트를 구분선+전용 헤더로 분리
    _wkday = bool(weekly_inline)
    _dsep = '<div style="height:1px;background:var(--line);margin:22px 0 12px"></div>' if _wkday else ''
    _dhead = L.get("sum_head_today", L["sum_head"]) if _wkday else L["sum_head"]
    # 카타르 정부 동향 박스 — '오늘 일일' 요약 헤더 바로 아래(오늘 브리핑의 첫 항목)로 배치해 지난주 섹션과 분리
    _gov = render_qatar_gov(qatar_gov, lang)
    if issues:
        summary_html = (_dsep + _gov + f'<div class="sumhead"><span class="bar"></span>{esc(_dhead)} '
                        f'<span class="ai">{esc(L["ai"])}</span></div>' + render_issues(issues, issue_pool, now_utc, L, collapse_links=(edition == "weekly")))
    elif flat_text:
        summary_html = (_dsep + _gov + f'<div class="card sum"><div class="sumhead"><span class="bar"></span>{esc(_dhead if _wkday else L["sum_head_flat"])} '
                        f'<span class="ai">{esc(L["ai"])}</span></div>'
                        f'<div class="sumbody">{summary_to_html(flat_text)}</div></div>')
    else:
        diag = " · ".join(LLM_DIAG[-3:]) if LLM_DIAG else ""
        diag_html = f'<div class="pl" style="color:var(--muted);font-size:11px;margin-top:6px">{esc(L["diag"])}: {esc(diag)}</div>' if diag else ""
        summary_html = (_gov + f'<div class="card sum"><div class="sumhead"><span class="bar"></span>{esc(L["sum_head_flat"])}</div>'
                        f'<div class="sumbody"><div class="pl" style="color:var(--muted)">{esc(L["sum_none_body"])}</div>'
                        f'{diag_html}</div></div>')

    # 본사 보고용 엑셀·워드 다운로드 바(이슈가 있을 때만) — '이슈 요약'과 '전체 기사 목록' 사이
    if issues:
        dlbar = (f'<div class="dlbar"><span class="dll">{esc(L["dl_label"])}</span>'
                 f'<button class="dlbtn" id="dlxlsx">{esc(L["dl_xlsx"])}</button>'
                 f'<button class="dlbtn" id="dldocx">{esc(L["dl_docx"])}</button></div>')
        monscript = f'<script>{_MON_SCRIPT}</script>'
    else:
        dlbar = ""
        monscript = ""

    quick = ""
    for sec_title, group_names in QUICK_SECTIONS:
        sec_disp = sec_title if lang == "ko" else QSEC_I18N.get(sec_title, {}).get(lang, sec_title)
        quick += f'<div class="qsec">{esc(sec_disp)}</div>'
        for g in group_names:
            links = QUICK_LINKS.get(g, [])
            if not links:
                continue
            g_disp = g if lang == "ko" else QGROUP_I18N.get(g, {}).get(lang, g)
            slinks = sorted(links, key=_ql_key)   # 그룹 내 가나다/ABC 정렬(표기명은 고유명 유지)
            chips = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)}</a>' for n, u in slinks)
            quick += f'<div class="qgroup"><div class="qh">{esc(g_disp)}</div><div class="qchips">{chips}</div></div>'

    # 분석·보고서 — main()에서 누적·정렬해 넘겨준 목록(최신순). 없으면 이번 창의 report 항목으로 폴백.
    rep_list = reports if reports is not None else [x for x in items if x.get("report")]
    tagmap = {"qatar": L["t_qatar"], "iran": L["t_iran"], "overseas": L["t_over"], "korea": L["t_korea"]}
    def rep_dt(x):
        d = x.get("dt")
        return d.astimezone(TZ).strftime("%m/%d") if hasattr(d, "astimezone") else str(d or "")[:10]
    def rep_row(x):
        # '이번 회차 신규'는 발행일이 아니라 '이번 회차에 처음 목록에 들어온 시각(added)' 기준
        _a = x.get("added") or x.get("dt")
        is_new = bool(new_since and hasattr(_a, "astimezone") and _a >= new_since)
        newb = f'<span class="newtag">{esc(L["rep_new"])}</span>' if is_new else ""
        reg = x.get("region", "overseas")
        return (f'<a href="{esc(x["link"])}" target="_blank" rel="noopener">'
                f'<span class="tag tag-{reg}">{esc(tagmap.get(reg,L["t_over"]))}</span>{newb}{esc(x["title"])}'
                f'<span class="src">({esc(x["source"])} · {rep_dt(x)})</span></a>')
    rows = "".join(rep_row(x) for x in rep_list[:REPORT_SHOW_MAX])
    if rows:
        report_html = ('<details class="foldbox reportfold">'
                       '<summary><span class="chev">▸</span>'
                       f'{esc(L["rep_head"])}<span class="hnote">{esc(L["rep_note"])}</span>'
                       f'<span class="exp exp-c">{esc(L["expand"])} ▾</span>'
                       f'<span class="exp exp-o">{esc(L["collapse"])} ▴</span></summary>'
                       f'<div class="reprows">{rows}</div></details>')
    else:
        report_html = ""

    # 지난 회차 콤보박스 — 해당 언어 아카이브(일간/주간 optgroup 구분, 최신순)
    opts_daily, opts_weekly = "", ""
    for kind, label, fname in (archive_list or []):
        o = f'<option value="{SITE_BASE}archive/{esc(fname)}">{esc(label)}</option>'
        if kind == "weekly":
            opts_weekly += o
        else:
            opts_daily += o
    # 일간·주간을 좌우 두 개의 별도 드롭다운으로 분리 — 각각 쌓여도 서로 안 묻히고 짧게 유지
    # 서버측 옵션은 무JS 폴백. 아래 스크립트가 매니페스트로 '전체 회차'를 동적 재구성(현재 보는 회차 selected).
    _albl = json.dumps({"latest": L["arch_latest"], "daily": L["arch_daily"], "weekly": L["arch_weekly"], "seld": L["sel_d"], "selw": L["sel_w"]}, ensure_ascii=False)
    _archscript = """<script>(function(){var LB=__LB__;var B="__BASE__";
var lang=document.documentElement.lang||"ko";
var cur=(location.pathname.split("/").pop()||"index.html");
fetch(B+"archive/manifest.json",{cache:"no-store"}).then(function(r){return r.json();}).then(function(m){
var sd=document.getElementById("archsel-d"),sw=document.getElementById("archsel-w");if(!m)return;
var home=(m.home&&m.home[lang])||B;var ld=(m.latest_daily&&m.latest_daily[lang])||"";
var xs=(m.issues||[]).filter(function(x){return x.lang===lang;});
xs.sort(function(a,b){return a.dt<b.dt?1:(a.dt>b.dt?-1:0);});
function e(t){return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
var d='<option value="">'+e(LB.seld)+'</option><option value="'+e(home)+'">'+e(LB.latest)+'</option>';var w='<option value="">'+e(LB.selw)+'</option>';
xs.forEach(function(x){if(x.kind!=="weekly"&&x.file===ld)return;
var sel=(x.file===cur?" selected":"");
var o='<option value="'+e(B+"archive/"+x.file)+'"'+sel+'>'+e(x.label)+'</option>';
if(x.kind==="weekly")w+=o;else d+=o;});
if(sd){sd.innerHTML=d;if(cur===ld||cur==="index.html"||cur===lang+".html"||cur===""){sd.selectedIndex=0;}}
if(sw){sw.innerHTML=w;}
}).catch(function(){});})();</script>""".replace("__LB__", _albl).replace("__BASE__", SITE_BASE)
    _dsel = (f'<select id="archsel-d" aria-label="{esc(L["arch_daily"])}" onchange="if(this.value)location.href=this.value">'
             f'<option value="">{esc(L["sel_d"])}</option><option value="{esc(home_url)}">{esc(L["arch_latest"])}</option>{opts_daily}</select>')
    _wsel = (f'<select id="archsel-w" aria-label="{esc(L["arch_weekly"])}" onchange="if(this.value)location.href=this.value">'
             f'<option value="">{esc(L["sel_w"])}</option>{opts_weekly}</select>')
    archive_html = (f'<div class="archsel"><span class="archlbl">{esc(L["arch_view"])}</span>'
                    f'{_dsel}{_wsel}</div>' + _archscript)

    # 언어 전환 버튼
    nav = nav or {l: home_url for l in LANGS}
    navbtns = "".join(
        f'<a class="langbtn{" on" if l == lang else ""}" href="{esc(nav.get(l, home_url))}">{esc(LANG_NAME[l])}</a>'
        for l in LANGS)
    nav_html = (f'<div class="langrow">'
                f'<div class="lang">{navbtns}</div>'
                f'<a class="sitelink" href="{esc(FLIGHT_URL)}" target="_blank" rel="noopener">{esc(L["sister"])} →</a></div>')

    weekly_html = weekly_inline or ""

    return TEMPLATE.format(
        bodycls=("ed-weekly" if edition == "weekly" else ""),
        dir=L["dir"], htmllang=L["html"], nav=nav_html,
        archive=archive_html, report=report_html, weekly=weekly_html,
        title=esc(L["title"]), subtitle=esc(L["subtitle"]), scope=L["scope"],
        title2=(f'<div class="entitle">{esc(L["title2"])}</div>' if L.get("title2") else ""),
        updated_label=esc(L["updated"]), tz=esc(L["tz"]), coverage_label=esc(L["coverage"]),
        counts=L["counts"].format(q=n_qatar, me=n_mideast),
        counts_label=esc(L["counts_label"]),
        updated=updated_str, window=window_html,
        full_summary=esc(L["full_summary"].format(n=len(qatar) + len(me_ov) + len(me_ir) + len(me_kr))),
        full_note=esc(L["full_note"]),
        expand=esc(L["expand"]), collapse=esc(L["collapse"]),
        col_qatar=esc(L["col_qatar"]), col_iran=esc(L["col_iran"]), col_over=esc(L["col_over"]), col_korea=esc(L["col_korea"]),
        quick_head=esc(L["quick_head"]), quick_note=esc(L["quick_note"]),
        tlref=timeline_ref(lang),
        foot=esc(L["foot"]), sign=esc(L["sign"]),
        summary=summary_html,
        dlbar=dlbar, monscript=monscript,
        qatar=block(qatar, esc(L["empty_q"])),
        me_en=block(me_ov, esc(L["empty_over"])),
        me_ir=block(me_ir, esc(L["empty_iran"])),
        me_ko=block(me_kr, esc(L["empty_korea"])),
        quick=quick,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="{htmllang}" dir="{dir}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{--bg:#0b1220;--panel:#131c2e;--panel2:#0f1729;--line:#243149;--txt:#e6edf7;--muted:#93a1b8;--accent:#4da3ff;--green:#2fbf71;--gold:#f2b134;--note-bg:#2a1615;--crit-text:#ff6b6a}}
  @media (prefers-color-scheme:light){{:root{{--bg:#f4f6fb;--panel:#fff;--panel2:#eef2f9;--line:#dbe2ee;--txt:#14213a;--muted:#5a6b85;--note-bg:#fbeceb;--crit-text:#b4211f}}}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);line-height:1.5;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
  .wrap{{max-width:1180px;margin:0 auto;padding:6px 14px 60px}}
  header{{position:static;background:var(--bg);
    padding:4px 0 12px;border-bottom:1px solid var(--line);margin-bottom:16px;z-index:5}}
  .titrow{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;
    position:sticky;top:0;z-index:50;background:var(--bg);border-bottom:1px solid var(--line);padding:7px 0 8px;margin-bottom:4px}}
  .titcol{{display:flex;flex-direction:column;gap:1px}}
  .entitle{{font-size:14px;font-weight:600;color:var(--muted);letter-spacing:-.01em;margin-top:2px}}
  .orgline{{font-size:12px;font-weight:600;color:var(--txt);margin-top:2px;letter-spacing:.2px}}
  .langrow{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}}
  .sitelink{{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:700;color:var(--accent);
    text-decoration:none;border:1px solid var(--line);border-radius:8px;padding:4px 10px;background:var(--panel2);white-space:nowrap}}
  .sitelink:hover{{background:var(--panel);border-color:var(--accent)}}
  .lang{{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;border:1px solid var(--line);border-radius:8px;padding:2px}}
  .langbtn{{font-size:12.5px;font-weight:600;padding:5px 12px;border:none;border-radius:6px;background:transparent;color:var(--muted);text-decoration:none;white-space:nowrap;text-align:center;box-sizing:border-box}}
  .lang .langbtn:not(:first-child){{border-inline-start:1px solid var(--line)}}
  .langbtn.on{{background:var(--accent);color:#fff}}
  .langbtn:hover{{color:var(--txt)}}
  .langbtn.on:hover{{color:#fff}}
  .dot{{width:10px;height:10px;border-radius:50%;background:var(--green);animation:p 2s infinite}}
  @keyframes p{{0%{{box-shadow:0 0 0 0 rgba(47,191,113,.5)}}70%{{box-shadow:0 0 0 8px rgba(47,191,113,0)}}100%{{box-shadow:0 0 0 0 rgba(47,191,113,0)}}}}
  h1{{font-size:20px;font-weight:700;letter-spacing:-.01em;margin:0}}
  .sub{{color:var(--muted);font-size:13px;margin-top:4px;line-height:1.5}}
  .submeta{{color:var(--txt);font-size:14px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line);display:flex;gap:3px 14px;flex-wrap:wrap}}
  .submeta .tz{{font-weight:400;color:var(--muted)}}
  .submeta > span::before{{content:"• ";color:var(--accent);font-weight:700}}
  .submeta > span{{flex-basis:100%}}
  .sub b,.submeta b{{color:var(--txt)}}
  .sumhead{{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;margin:6px 0 12px;flex-wrap:wrap;word-break:keep-all}}
  .sumhead .bar{{width:3px;height:16px;background:var(--accent);border-radius:2px}}
  .ai{{font-size:10.5px;font-weight:700;color:var(--accent);background:transparent;border:1px solid var(--accent);padding:1px 7px;border-radius:6px;white-space:nowrap}}
  .issue{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden}}
  .issue .ihead{{display:flex;align-items:baseline;gap:8px;padding:11px 15px;border-bottom:1px solid var(--line);background:var(--panel2)}}
  .issue .ihead .num{{flex:0 0 auto;font-size:11.5px;font-weight:800;color:#111;background:var(--gold);border-radius:6px;padding:1px 8px}}
  .issue .ihead h2{{font-size:14.5px;margin:0;line-height:1.5}}
  .row{{display:grid;grid-template-columns:0.78fr 1.22fr;gap:0}}
  .row.solo{{grid-template-columns:1fr}}
  @media (max-width:760px){{.row{{grid-template-columns:1fr}}}}
  .left{{padding:13px 16px;border-inline-end:1px solid var(--line)}}
  @media (max-width:760px){{.left{{border-inline-end:none;border-bottom:1px solid var(--line)}}}}
  .left .sh{{font-size:11px;color:var(--accent);font-weight:800;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}}
  .left p{{margin:0 0 8px;font-size:13.5px}}
  .left .sumbul{{list-style:disc;margin:0;padding-inline-start:18px}}
  .left .sumbul li{{font-size:13.5px;line-height:1.55;margin:0 0 8px;padding:0;border:none}}
  .left .sumbul li:last-child{{margin-bottom:0}}
  .left .qimpact{{background:var(--note-bg);border:1px solid var(--gold);border-radius:10px;padding:9px 11px;margin:0 0 11px}}
  .left .qimpact .qh{{font-size:11.5px;font-weight:800;color:var(--crit-text);letter-spacing:.3px;margin-bottom:5px}}
  .left .qbul{{list-style:disc;margin:0;padding-inline-start:18px}}
  .left .qbul li{{font-size:13px;line-height:1.5;margin:0 0 6px;color:var(--txt)}}
  .left .qbul li:last-child{{margin-bottom:0}}
  .left .qimpact .qlinks{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
  .left .qimpact .qlink{{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:700;color:var(--crit-text);border:1px solid var(--gold);border-radius:6px;padding:2px 8px;text-decoration:none;background:transparent}}
  .left .qimpact .qlink .ic{{font-weight:800}}
  .left .qimpact .qlink:hover{{background:var(--gold);color:#1a1a1a}}
  .right{{padding:13px 16px}}
  .grp{{margin-bottom:9px}} .grp .gh{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px}}
  .grp a{{display:block;color:var(--txt);text-decoration:none;font-size:13px;font-weight:600;margin:5px 0}}
  .grp a:hover{{color:var(--accent);text-decoration:underline}}
  .grp a .src{{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:1px}}
  .linkfold{{border-top:1px solid var(--line)}}
  .linkfold>summary{{list-style:none;cursor:pointer;padding:9px 16px;font-size:12.5px;font-weight:700;color:var(--accent);user-select:none;display:flex;align-items:center;gap:6px}}
  .linkfold>summary::-webkit-details-marker{{display:none}}
  .linkfold>summary::before{{content:"▸";font-size:11px;transition:transform .15s}}
  .linkfold[open]>summary::before{{content:"▾"}}
  .linkfold>summary:hover{{text-decoration:underline}}
  .foldwrap{{padding:2px 16px 12px;display:flex;flex-wrap:wrap;gap:0 26px}}
  .foldwrap .grp{{flex:1 1 240px;min-width:220px}}
  .tq{{font-size:10px;font-weight:700;color:#111;background:var(--gold);border-radius:5px;padding:0 5px;margin-inline-end:4px;vertical-align:middle}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 15px;margin-bottom:14px}}
  .card.sum{{background:linear-gradient(180deg,rgba(77,163,255,.08),transparent),var(--panel)}}
  .sumbody .sh{{font-weight:800;margin:11px 0 4px;font-size:13px;color:var(--accent)}}
  .sumbody .bl{{position:relative;padding-left:14px;margin:4px 0;font-size:13.5px}}
  .sumbody .bl:before{{content:"•";position:absolute;left:2px;color:var(--accent)}}
  .sumbody .pl{{font-size:13.5px;margin:3px 0}}
  .card h2{{font-size:14px;margin:0 0 10px;display:flex;align-items:center;gap:8px}}
  .card h2 .bar{{width:3px;height:15px;background:var(--accent);border-radius:2px}}
  .card.pin h2 .bar{{background:var(--gold)}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  @media (max-width:720px){{.grid{{grid-template-columns:1fr}}}}
  .grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}}
  @media (max-width:820px){{.grid3{{grid-template-columns:1fr}}}}
  .grid4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px}}
  @media (max-width:980px){{.grid4{{grid-template-columns:1fr 1fr}}}}
  @media (max-width:560px){{.grid4{{grid-template-columns:1fr}}}}
  img.emoji{{height:1em;width:1em;margin:0 .06em 0 .05em;vertical-align:-0.12em}}
  /* 접이식 박스(전체목록·보고서·바로가기) — 동일한 회색 스타일·기본 접힘 */
  details.foldbox{{margin:14px 0}}
  details.reportfold{{margin-top:20px}}
  .foldbox>summary{{cursor:pointer;list-style:none;user-select:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap;
    font-size:14px;font-weight:800;color:var(--txt);letter-spacing:.2px;
    padding:13px 16px;border:1px solid var(--line);border-radius:12px;
    background:var(--panel2);transition:background .15s,box-shadow .15s}}
  .foldbox>summary::-webkit-details-marker{{display:none}}
  .foldbox>summary:hover{{background:var(--panel);box-shadow:0 0 0 3px rgba(127,127,127,.12)}}
  .foldbox[open]>summary{{margin-bottom:12px}}
  .foldbox .chev{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;
    border-radius:50%;background:var(--muted);color:#fff;font-size:12px;transition:transform .15s;flex:0 0 auto}}
  .foldbox[open] .chev{{transform:rotate(90deg)}}
  .foldbox .hnote{{font-weight:400}}
  summary .exp{{margin-inline-start:auto;font-size:11.5px;font-weight:700;color:#fff;
    background:var(--muted);border-radius:7px;padding:3px 10px;white-space:nowrap}}
  summary .exp-o{{display:none;background:var(--panel2);color:var(--muted);border:1px solid var(--line)}}
  details[open]>summary .exp-c{{display:none}}
  details[open]>summary .exp-o{{display:inline-block}}
  /* ── 중동 전쟁 타임라인 버튼(상단, 작게, 새 탭 링크) ── */
  .tlbtnrow{{display:flex;justify-content:center;margin:4px 0 2px}}
  .tlbtn{{display:inline-flex;align-items:center;gap:7px;max-width:100%;padding:7px 13px;
    border:1px solid var(--line);border-radius:999px;background:var(--panel2);
    text-decoration:none;color:var(--muted);font-weight:700;font-size:12px;
    transition:background .15s,box-shadow .15s,color .15s}}
  .tlbtn:hover{{background:var(--panel);color:var(--txt);box-shadow:0 0 0 3px rgba(127,127,127,.1)}}
  .tlbtn-tag{{font-size:10px;font-weight:800;color:#fff;background:var(--accent);border-radius:5px;padding:1px 6px;white-space:nowrap;flex:0 0 auto}}
  .tlbtn-t{{word-break:keep-all;line-height:1.3}}
  .tlbtn-arr{{flex:0 0 auto;font-weight:700}}
  /* ── 카타르 정부 동향 섹션(제목=sumhead, 내용=흰색 이슈형 박스) ── */
  .govcard{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 15px;margin:0 0 12px}}
  .govul{{margin:0;padding-inline-start:18px;list-style:disc}}
  .govul li{{font-size:13px;line-height:1.6;margin:3px 0;color:var(--txt)}}
  .govlink{{display:inline-block;font-size:10.5px;font-weight:700;color:var(--accent);text-decoration:none;
    border:1px solid var(--line);border-radius:6px;padding:0 6px;margin-inline-start:5px;white-space:nowrap;vertical-align:baseline}}
  .govlink:hover{{background:var(--panel2)}}
  .govnone{{font-size:12.5px;color:var(--muted)}}
  .foldbox>.reprows,.foldbox>.qbody{{padding:0 2px}}
  ul{{list-style:none;margin:0;padding:0}}
  li{{padding:10px 0;border-bottom:1px solid var(--line)}} li:last-child{{border-bottom:none}}
  li a{{color:var(--txt);text-decoration:none;font-size:14px;font-weight:600}}
  li a:hover{{color:var(--accent);text-decoration:underline}}
  .dsc{{color:var(--muted);font-size:12.5px;margin-top:3px}}
  .meta{{color:var(--muted);font-size:11px;margin-top:3px;opacity:.8}}
  .empty{{color:var(--muted);font-size:13px}}
  .sechd{{font-size:13px;font-weight:800;color:var(--muted);margin:20px 0 8px;text-transform:uppercase;letter-spacing:.5px}}
  .qsec{{font-size:13.5px;font-weight:800;color:var(--txt);margin:18px 0 10px;padding-bottom:5px;border-bottom:1px solid var(--line)}}
  .qsec:first-child{{margin-top:2px}}
  .qgroup{{margin:2px 0 12px}} .qh{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}}
  .qchips{{display:flex;flex-wrap:wrap;gap:7px}}
  .qchips a{{font-size:12.5px;color:var(--accent);text-decoration:none;border:1px solid var(--line);background:var(--panel2);border-radius:8px;padding:5px 10px}}
  .qchips a:hover{{text-decoration:underline}}
  .archsel{{display:flex;align-items:center;gap:6px 8px;font-size:12.5px;color:var(--muted);margin:2px 0 12px;flex-wrap:wrap}}
  .archlbl{{flex:0 0 auto;white-space:nowrap}}
  .archsel select{{font-size:12.5px;color:var(--txt);background:var(--panel2);border:1px solid var(--line);
    border-radius:8px;padding:5px 9px;flex:0 1 160px;min-width:0;max-width:none;
    text-overflow:ellipsis;white-space:nowrap;overflow:hidden}}
  .issno{{font-size:11.5px;font-weight:800;color:#111;background:var(--gold);border-radius:6px;padding:2px 9px}}
  h1 .edtag{{font-size:13px;font-weight:700;color:#111;background:var(--gold);border-radius:6px;padding:1px 8px;vertical-align:middle;letter-spacing:0}}
  .scopebar{{font-size:12.5px;color:var(--muted);background:linear-gradient(180deg,rgba(77,163,255,.07),transparent),var(--panel2);
    border:1px solid var(--line);border-radius:10px;padding:10px 13px;margin:2px 0 14px;line-height:1.55}}
  .scopebar b{{color:var(--txt);font-weight:700}}
  .tldiv{{display:block;border-top:1px dashed var(--line);margin:9px 0 8px}}
  .tlref{{display:block;font-size:12.5px;color:var(--muted)}}
  .tlref a{{color:var(--accent);font-weight:600;text-decoration:underline;text-underline-offset:3px;text-decoration-color:rgba(77,163,255,.45)}}
  .tlref a:hover{{text-decoration-color:var(--accent)}}
  .dlbar{{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:2px 0 20px}}
  .dll{{font-size:12px;font-weight:700;color:var(--muted)}}
  .dlbtn{{font:inherit;font-size:12.5px;font-weight:700;color:var(--accent);background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:7px 14px;cursor:pointer;white-space:nowrap}}
  .dlbtn:hover{{border-color:var(--accent)}}
  @media print{{.dlbar{{display:none}}}}
  .tlref img.emoji{{height:1em;width:1em;vertical-align:-0.12em}}
  .wsec{{margin:2px 0 18px;padding:12px 15px 14px;border:1px solid rgba(77,163,255,.5);border-radius:14px;
    background:linear-gradient(180deg,rgba(77,163,255,.08),transparent)}}
  .wsec .sumhead{{margin-top:2px}}
  .wsec .issue .ihead .num{{background:var(--accent);color:#fff}}
  body.ed-weekly .issue .ihead .num{{background:var(--accent);color:#fff}}
  .wsec .wmeta{{font-size:11.5px;color:var(--muted);font-weight:400;margin-inline-start:auto}}
  .wsec .wlink{{margin-top:8px;font-size:12.5px}}
  .wsec .wlink a{{color:var(--accent);text-decoration:none}}
  .wsec .wlink a:hover{{text-decoration:underline}}
  .card.report{{border-color:rgba(242,177,52,.5);background:linear-gradient(180deg,rgba(242,177,52,.08),transparent)}}
  .reprows a{{display:block;color:var(--txt);text-decoration:none;font-size:13.5px;font-weight:700;margin:7px 0}}
  .reprows a:hover{{color:var(--accent);text-decoration:underline}}
  .reprows a .src{{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:1px}}
  .reprows a .tag{{display:inline-block;font-size:10px;font-weight:800;color:#111;background:var(--gold);border:1px solid transparent;border-radius:5px;padding:0 6px;margin-inline-end:6px;vertical-align:middle}}
  .reprows a .tag.tag-overseas{{background:transparent;color:var(--txt);border-color:var(--gold)}}
  .reprows a .newtag{{display:inline-block;font-size:10px;font-weight:800;color:#fff;background:#e5484d;border-radius:5px;padding:0 6px;margin-inline-end:6px;vertical-align:middle}}
  footer{{margin-top:22px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;line-height:1.7}}
  footer .notice-emph{{margin-top:12px;padding:12px 14px;border-radius:10px;background:#e2eefb;border:1px solid rgba(42,120,214,0.35);color:#16305e;font-weight:600;font-size:12.5px;line-height:1.6}}
  footer .notice-sign{{text-align:end;margin-top:10px;font-weight:400;font-size:12px;color:#16305e;opacity:.9}}
  .hnote{{font-size:11px;font-weight:400;color:var(--muted);letter-spacing:0}}
  @media (max-width:520px){{h1{{font-size:16.5px}} .qchips a{{padding:6px 11px}}
    .archsel{{flex-wrap:nowrap;gap:6px}} .archlbl{{font-size:11.5px}}
    .archsel select{{flex:1 1 0;max-width:none;font-size:11.5px;padding:5px 7px}}
    .langrow{{justify-content:space-between;flex-wrap:wrap;gap:8px}} .lang{{flex:1 1 auto;gap:6px}} .langbtn{{flex:1;text-align:center;padding:10px 8px;font-size:14px}}}}
  /* 인쇄·PDF 저장(A4) — 밝은 배경·상호작용 요소 숨김·페이지 잘림 방지 */
  @media print {{
    :root{{--bg:#fff;--panel:#fff;--panel2:#fbfbfd;--line:#d0d0d0;--txt:#000;--muted:#555;--accent:#1e6bd6;--gold:#b8860b;--green:#2fbf71;--note-bg:#fbeceb;--crit-text:#b4211f}}
    @page{{size:A4;margin:12mm}}
    html,body{{background:#fff;color:#000}}
    .wrap{{max-width:none;margin:0;padding:0}}
    header{{position:static;border-bottom:1px solid #ccc}}
    .langbar,.archsel,.exp,.dot{{display:none !important}}
    a{{color:#000 !important;text-decoration:none}}
    .grid4{{grid-template-columns:1fr 1fr}}
    .issue,.card,details,.grp,.reprows a,li,.qgroup{{break-inside:avoid}}
    .issue,.card{{box-shadow:none}}
    h1{{font-size:16px}}
    .scopebar,.card.report{{background:#fff !important}}
  }}
</style>
</head>
<body class="{bodycls}">
<div class="wrap">
  {nav}
  <div class="titrow"><div class="titcol"><h1>{title}</h1>{title2}</div></div>
  <header>
    <div class="sub"><span>{subtitle}</span></div>
    <div class="scopebar">🎯 {scope}{tlref}</div>
    {archive}
    <div class="submeta">
      <span>{updated_label}: <b>{updated}</b> <span class="tz">({tz})</span></span>
      <span>{coverage_label}: <b>{window}</b></span>
      <span class="cnt">{counts_label}: {counts}</span>
    </div>
  </header>

  {weekly}

  {summary}

  {dlbar}

  <details class="fulllist foldbox">
    <summary><span class="chev">▸</span> {full_summary} <span class="hnote">{full_note}</span> <span class="exp exp-c">{expand} ▾</span><span class="exp exp-o">{collapse} ▴</span></summary>
    <div class="grid4">
      <div class="card"><h2><span class="bar"></span>{col_qatar}</h2><ul>{qatar}</ul></div>
      <div class="card"><h2><span class="bar"></span>{col_iran}</h2><ul>{me_ir}</ul></div>
      <div class="card"><h2><span class="bar"></span>{col_over}</h2><ul>{me_en}</ul></div>
      <div class="card"><h2><span class="bar"></span>{col_korea}</h2><ul>{me_ko}</ul></div>
    </div>
  </details>

  {report}

  <details class="foldbox">
    <summary><span class="chev">▸</span> {quick_head} <span class="hnote">{quick_note}</span> <span class="exp exp-c">{expand} ▾</span><span class="exp exp-o">{collapse} ▴</span></summary>
    <div class="qbody">{quick}</div>
  </details>

  <footer>
    <div class="notice-emph">{foot}<div class="notice-sign">{sign}</div></div>
  </footer>
</div>
{monscript}
<script src="https://cdn.jsdelivr.net/npm/twemoji@14.0.2/dist/twemoji.min.js" crossorigin="anonymous"></script>
<script>
  // 국기 이모지가 윈도우 등에서 'QA/IR/KR' 글자로 보이는 문제 방지 → 실제 국기 이미지로 렌더
  (function () {{
    function run() {{
      try {{
        if (window.twemoji) twemoji.parse(document.body, {{
          base: 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/',
          folder: 'svg', ext: '.svg'
        }});
      }} catch (e) {{}}
    }}
    run();
    window.addEventListener('DOMContentLoaded', run);
  }})();
  // 인쇄·PDF 저장 시 접힌 섹션(전체 목록·보고서)을 자동으로 펼쳐 전부 출력, 인쇄 후 원복
  (function () {{
    var saved = [];
    window.addEventListener('beforeprint', function () {{
      saved = [];
      document.querySelectorAll('details').forEach(function (d) {{ saved.push([d, d.open]); d.open = true; }});
    }});
    window.addEventListener('afterprint', function () {{
      saved.forEach(function (p) {{ p[0].open = p[1]; }});
      saved = [];
    }});
  }})();
</script>
<img src="https://hits.sh/kotradoha.github.io/qatar-media-monitor.svg" alt="" aria-hidden="true" loading="eager" referrerpolicy="no-referrer-when-downgrade" style="position:absolute;left:0;top:0;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);opacity:0;pointer-events:none">
</body>
</html>
"""

# 타임라인 독립 페이지(새 탭으로 열림) — 자체 완결형 스타일
TIMELINE_PAGE = """<!DOCTYPE html>
<html lang="{htmllang}" dir="{dir}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{--bg:#0b1220;--panel:#131c2e;--panel2:#0f1729;--line:#243149;--txt:#e6edf7;--muted:#93a1b8;--accent:#4da3ff;--gold:#f2b134}}
  @media (prefers-color-scheme:light){{:root{{--bg:#f4f6fb;--panel:#fff;--panel2:#eef2f9;--line:#dbe2ee;--txt:#14213a;--muted:#5a6b85}}}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR","Malgun Gothic",sans-serif;
    -webkit-text-size-adjust:100%}}
  img.emoji{{height:1em;width:1em;margin:0 .05em;vertical-align:-0.12em}}
  .wrap{{max-width:920px;margin:0 auto;padding:18px 16px 60px}}
  .tlback{{display:inline-block;font-size:12.5px;font-weight:700;color:var(--accent);text-decoration:none;margin-bottom:8px}}
  .tlback:hover{{text-decoration:underline}}
  .tlpage-div{{border:0;border-top:2px solid var(--line);margin:6px 0 14px}}
  .tlpage-h{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:0 0 8px;font-size:20px;font-weight:800;line-height:1.3;word-break:keep-all}}
  .tlpage-tag{{font-size:12px;font-weight:800;color:#fff;background:var(--accent);border-radius:7px;padding:2px 9px;white-space:nowrap}}
  .tlnotehead{{font-size:12px;color:var(--muted);line-height:1.55;margin:0 2px 20px}}
  .tlwrap{{position:relative}}
  .tlwrap::before{{content:"";position:absolute;inset-inline-start:99px;top:6px;bottom:8px;width:2px;background:var(--line)}}
  .tlrow{{position:relative;display:grid;grid-template-columns:88px 1fr;gap:0 22px;padding:0 0 18px}}
  .tlrow:last-child{{padding-bottom:2px}}
  .tldate{{text-align:end;line-height:1.25}}
  .tldate .tly{{display:block;font-size:11px;color:var(--muted);font-weight:700}}
  .tldate .tlmd{{display:block;font-size:13px;font-weight:800;color:var(--txt);white-space:nowrap}}
  .tldot{{position:absolute;inset-inline-start:94px;top:4px;width:11px;height:11px;border-radius:50%;
    background:var(--accent);border:2px solid var(--bg);z-index:1}}
  .tlbody{{font-size:13.5px;line-height:1.6;color:var(--txt);word-break:keep-all}}
  .tlnote{{color:var(--muted);font-weight:400}}
  .tlrow.q .tldot{{background:var(--gold);width:13px;height:13px;inset-inline-start:93px;top:3px}}
  .tlrow.q .tlbody{{font-weight:600}}
  .tlq{{display:inline-block;font-size:10px;font-weight:800;color:#111;background:var(--gold);
    border-radius:5px;padding:0 6px;margin-inline-end:6px;vertical-align:middle;white-space:nowrap}}
  .tlsrc{{margin-top:22px;padding-top:12px;border-top:1px solid var(--line);
    font-size:10.5px;color:var(--muted);line-height:1.7}}
  .tlsrc-l{{font-weight:800}}
  .tlsrc a{{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--line)}}
  .tlsrc a:hover{{color:var(--accent)}}
  .tlsrc-n{{margin-top:5px;font-size:10px;opacity:.85}}
  .tlbar{{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:2px 0 16px}}
  .tlfilters{{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}}
  .tlfbtn{{font:inherit;font-size:12px;font-weight:700;padding:6px 12px;border:0;background:transparent;color:var(--muted);cursor:pointer;border-inline-start:1px solid var(--line)}}
  .tlfbtn:first-child{{border-inline-start:0}}
  .tlfbtn.on{{background:var(--accent);color:#fff}}
  .tldlbtn{{font:inherit;font-size:12px;font-weight:700;color:var(--accent);background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:6px 12px;cursor:pointer;margin-inline-start:auto;white-space:nowrap}}
  .tldlbtn:hover{{border-color:var(--accent)}}
  @media (max-width:560px){{
    .tlwrap::before{{inset-inline-start:64px}}
    .tlrow{{grid-template-columns:54px 1fr;gap:0 16px}}
    .tldate .tlmd{{font-size:12px}}
    .tldot{{inset-inline-start:59px}}
    .tlrow.q .tldot{{inset-inline-start:58px}}
    .tlpage-h{{font-size:17px}}
  }}
  /* A4 인쇄 최적화 */
  @media print{{
    :root{{--bg:#fff;--panel:#fff;--panel2:#f5f5f5;--line:#c9c9c9;--txt:#111;--muted:#555;--accent:#1668c4;--gold:#a9791a}}
    @page{{size:A4;margin:14mm}}
    html,body{{background:#fff}}
    .wrap{{max-width:none;margin:0;padding:0}}
    .tlback{{display:none}}
    .tlpage-div{{border-top-color:#111}}
    .tlbar{{display:none}}
    .tlrow{{break-inside:avoid;page-break-inside:avoid;padding-bottom:12px}}
    .tlbody{{font-size:11.5pt;line-height:1.5}}
    .tldate .tlmd{{font-size:11pt}}
    .tldate .tly{{font-size:9pt}}
    .tldot{{border-color:#fff}}
    .tlsrc a{{color:#555;border:none}}
    .tlsrc{{break-inside:avoid}}
  }}
</style>
</head>
<body>
<div class="wrap">
  <a class="tlback" href="{home}">{back}</a>
  <hr class="tlpage-div">
  <h1 class="tlpage-h"><span class="tlpage-tag">{tag}</span>{head}</h1>
  <div class="tlbar">
    <div class="tlfilters">
      <button class="tlfbtn on" data-f="all">{f_all}</button>
      <button class="tlfbtn" data-f="q">{f_qonly}</button>
      <button class="tlfbtn" data-f="ex">{f_qex}</button>
    </div>
    <button class="tldlbtn" id="tldl">{dl}</button>
  </div>
  {rows}
  {sources}
</div>
<script src="https://cdn.jsdelivr.net/npm/twemoji@14.0.2/dist/twemoji.min.js" crossorigin="anonymous"></script>
<script>if(window.twemoji)twemoji.parse(document.body,{{folder:'svg',ext:'.svg'}});</script>
<script>{tlscript}</script>
</body>
</html>
"""


# 요약 풀에 우선 넣을 '메이저/공신력' 매체 힌트(카타르 현지는 별도로 최우선 고정)
MAJOR_HINTS = [
    "qatar news agency", "qna", "gulf times", "peninsula", "qatar tribune", "doha news",
    "al jazeera", "aljazeera", "lusail",
    "yonhap", "연합", "뉴시스", "newsis", "뉴스1", "news1", "ytn", "kbs", "mbc", "sbs", "jtbc",
    "노컷", "nocut", "nocutnews",
    "조선", "chosun", "중앙", "joongang", "joins", "동아", "donga",
    "한겨레", "hani", "경향", "khan", "kyunghyang", "서울신문", "seoul", "문화일보", "munhwa",
    "매일경제", "매경", "mk.co", "maeil", "한국경제", "hankyung",
    "파이낸셜뉴스", "fnnews", "이데일리", "edaily", "머니투데이", "moneytoday", "서울경제", "sedaily",
    "reuters", "ap news", "apnews", "associated press", "afp", "bloomberg", "cnn", "bbc",
    "the guardian", "washington post", "new york times", "nytimes", "wall street journal", "wsj",
    "financial times", "ft.com", "economist", "이코노미스트", "cnbc", "npr", "politico", "axios", "semafor",
    "al arabiya", "al-arabiya", "middle east eye", "middle east institute", "al monitor", "al-monitor",
    "times of israel", "jerusalem post", "the national", "anadolu", "amwaj",
    "irna", "press tv", "presstv", "tehran times", "mehr", "al-alam", "tasnim",
]

def _is_major(x):
    s = (x.get("source") or "").lower()
    return any(m in s for m in MAJOR_HINTS)

def _build_quicklink_hints():
    """관련 링크(QUICK_LINKS)에 등록된 매체·기관명을 소스 매칭용 힌트로 추출 — 이 목록 매체 기사는 무조건 유지."""
    hints = set()
    _skip = {"news", "www", "en", "english", "world", "section", "hub", "com", "co", "kr", "org", "x", "the"}
    for _cat, links in QUICK_LINKS.items():
        for name, url in links:
            base = re.split(r"[—\(\|·]", name)[0].strip().lower()
            if len(base) >= 4:                      # 짧은 약칭(ap·cnn·kbs 등)은 오탐 위험 → 제외(이미 MAJOR_HINTS로 유지됨)
                hints.add(base)
            m = re.search(r"https?://([^/]+)", url or "")
            if m:
                core = m.group(1).lower().replace("www.", "").split(".")[0]
                if len(core) >= 4 and core not in _skip:
                    hints.add(core)
    return hints

QUICKLINK_HINTS = _build_quicklink_hints()

def _in_quicklinks(x):
    s = (x.get("source") or "").lower()
    return any(h in s for h in QUICKLINK_HINTS)

def _is_core(x):
    return has((x.get("title") or "") + " " + (x.get("desc") or ""), CORE_KW)

_STORY_STOP = {"the","a","an","of","to","in","on","for","and","or","is","are","was","were","with",
               "as","at","by","from","that","this","its","his","her","after","over","amid","says","say",
               "및","the","속보","단독","종합","영상","포토","사진"}

def _story_toks(title):
    ws = re.findall(r"[a-z0-9]+|[가-힣]{2,}", (title or "").lower())
    return set(w for w in ws if len(w) >= 2 and w not in _STORY_STOP)

def _dedupe_stories(items):
    """near-duplicate(사실상 같은 기사) 정리 — 메이저 매체 버전을 대표로 우선 유지, 원래 순서 보존."""
    order = sorted(range(len(items)), key=lambda i: 0 if _is_major(items[i]) else 1)
    reps, keep = [], set()
    for i in order:
        ts = _story_toks(items[i].get("title", ""))
        if _is_major(items[i]):    # 메이저 매체는 이슈 중복이라도 무조건 유지
            keep.add(i)
            if len(ts) >= 5:
                reps.append(ts)    # 단, 소형매체 중복은 계속 억제하도록 대표로는 등록
            continue
        if len(ts) < 5:            # 너무 짧은 제목은 과합침 위험 → 그대로 유지
            keep.add(i); continue
        dup = False
        for kts in reps:
            uni = len(ts | kts)
            if uni and len(ts & kts) / uni >= 0.7:   # 70% 이상 겹치면 동일 기사로 간주(보수적)
                dup = True; break
        if not dup:
            reps.append(ts); keep.add(i)
    return [x for j, x in enumerate(items) if j in keep]

def filter_minor(items):
    """① 유지보장: 메이저 매체·관련링크 등록매체·카타르 관련·핵심 토픽·보고서는 무조건 유지.
       ② 그 외 소형매체 주변부 단발기사는 제외. ③ near-duplicate 정리. (목록=모니터링 건수 동시 감소 → 일치 유지)"""
    kept = [x for x in items
            if _is_major(x) or _in_quicklinks(x) or x.get("qatar") or x.get("region") == "qatar"
            or x.get("report") or _is_core(x)]
    return _dedupe_stories(kept)

def build_issue_pool(items):
    """사안 요약용 풀: 원산지·속보성 우선(카타르 현지 → 해외 글로벌·미국·유럽 → 이란·역내 → 국내 한국·보완).
    국내 언론이 같은 사안을 다수 전재해 풀이 국내 위주로 쏠리지 않도록 권역별 상한을 두고 1차 정보원을 앞세움."""
    maj = lambda lst: [x for x in lst if _is_major(x)] + [x for x in lst if not _is_major(x)]
    qatar = [x for x in items if x["qatar"] or x["region"] == "qatar"]
    rest = [x for x in items if not (x["qatar"] or x["region"] == "qatar")]
    overseas = [x for x in rest if x["region"] == "overseas"]   # 글로벌·미국·유럽 등 1차/속보 정보원
    iran = [x for x in rest if x["region"] == "iran"]           # 이란·역내 1차 정보원
    korea = [x for x in rest if x["region"] == "korea"]         # 국내(한국) — 보완적
    pool = maj(qatar)[:22] + maj(overseas)[:28] + maj(iran)[:10] + maj(korea)[:14]
    return pool[:POOL_FOR_ISSUES]


def _issue_base_dt():
    return datetime(ISSUE_BASE[0], ISSUE_BASE[1], ISSUE_BASE[2], 7, 0, tzinfo=TZ)

def _slot_of(now_q):
    """이번 회차가 대표하는 브리핑 슬롯(직전 07:00/15:30 경계)과 라벨(0700/1530)."""
    am = now_q.replace(hour=7, minute=0, second=0, microsecond=0)
    pm = now_q.replace(hour=15, minute=30, second=0, microsecond=0)
    if now_q >= pm:
        return pm, "1530"
    if now_q >= am:
        return am, "0700"
    prev = (now_q - timedelta(days=1)).replace(hour=15, minute=30, second=0, microsecond=0)
    return prev, "1530"

def _daily_no(slot_dt):
    base = _issue_base_dt()
    if slot_dt < base:
        return None
    d = (slot_dt.date() - base.date()).days
    return d * 2 + (1 if slot_dt.hour == 7 else 2)

def _first_weekly_sunday():
    b = _issue_base_dt().date()
    return b + timedelta(days=(WEEKLY_WEEKDAY - b.weekday()) % 7)

def _weekly_no(sun_date):
    first = _first_weekly_sunday()
    if sun_date < first:
        return None
    return (sun_date - first).days // 7 + 1

def _archive_meta(fname):
    """아카이브 파일명 → dict(kind, dt, lang, no, m, d[, hh, mm]). 언어접미사 없으면 ko로 간주."""
    n = fname[:-5] if fname.endswith(".html") else fname
    parts = n.split("-")
    try:
        if parts[0] == "d" and len(parts) >= 3:
            ymd, hhmm = parts[1], parts[2]
            lang = parts[3] if len(parts) >= 4 and parts[3] in LANGS else "ko"
            y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
            hh, mm = (7, 0) if hhmm == "0700" else (15, 30)
            slot = datetime(y, m, d, hh, mm, tzinfo=TZ)
            return {"kind": "daily", "dt": slot, "lang": lang, "no": _daily_no(slot),
                    "m": m, "d": d, "hh": hh, "mm": mm}
        if parts[0] == "w" and len(parts) >= 2:
            ymd = parts[1]
            lang = parts[2] if len(parts) >= 3 and parts[2] in LANGS else "ko"
            y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
            sd = datetime(y, m, d, 7, 0, tzinfo=TZ)
            return {"kind": "weekly", "dt": sd, "lang": lang, "no": _weekly_no(sd.date()), "m": m, "d": d}
    except Exception:
        return None
    return None


def _archive_label_text(meta, L):
    if meta["kind"] == "daily":
        _wd = L.get("wdays", ["","","","","","",""])[meta["dt"].weekday()]
        tail = f"{meta['m']:02d}/{meta['d']:02d}({_wd}) {meta['hh']:02d}:{meta['mm']:02d}"
        if not meta["no"]:
            return L["daily_demo"] + " · " + tail
        label = L["no_only"].format(n=meta["no"]) + " " + tail
        # 주간은 별도 드롭다운에서 검색하므로 일간 라벨에 '(주간 포함)' 표기하지 않음
        return label
    tail = f"~{meta['m']:02d}/{meta['d']:02d}"
    return (L["weekly_no"].format(n=meta["no"]) + " · " + tail) if meta["no"] else (L["arch_weekly"] + " " + tail)


def main():
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    # 크론 조기 실행 보정: 07:00/15:30 경계 20분 전 이내에 실행되면 해당 경계 회차로 스냅(회차 번호·기간 선택 일관성 확보)
    _am = now_q.replace(hour=BOUNDARY_AM[0], minute=BOUNDARY_AM[1], second=0, microsecond=0)
    _pm = now_q.replace(hour=BOUNDARY_PM[0], minute=BOUNDARY_PM[1], second=0, microsecond=0)
    _grace = timedelta(minutes=20)
    if _am - _grace <= now_q < _am:
        now_q = _am
    elif _pm - _grace <= now_q < _pm:
        now_q = _pm
    # 멱등성: 정기 트리거(schedule·외부 dispatch)가 '이미 발행된 슬롯'을 다시 실행하지 않도록 스킵.
    #  → 늦게 발화한 GitHub 크론이 정시(외부 cron) 결과를 늦은 시각으로 덮어쓰거나 API를 낭비하는 것을 방지.
    #    push·수동(workflow_dispatch)은 항상 재생성(코드 반영·강제 발행용).
    _sd0, _ap0 = _slot_of(now_q)
    if os.environ.get("GITHUB_EVENT_NAME", "") in ("schedule", "repository_dispatch") \
            and os.path.exists(f"archive/d-{_sd0.strftime('%Y%m%d')}-{_ap0}-ko.html"):
        print(f"[skip] slot {_sd0.strftime('%Y%m%d')}-{_ap0} already published (event={os.environ.get('GITHUB_EVENT_NAME')})")
        return
    start_q, end_q, win_slot = window_bounds(now_q)
    label_ko = f"{LANG['ko']['win_' + win_slot]} (카타르시간)"   # LLM 프롬프트·로그용(한국어)
    items = collect(start_q.astimezone(timezone.utc), now_utc)
    _n0 = len(items); items = filter_minor(items)               # 소형매체 주변부·중복 정리(메이저·관련링크·카타르·핵심토픽·보고서는 유지)
    print(f"[info] filter_minor: {_n0} → {len(items)} (dropped {_n0 - len(items)})")
    new_since_daily = start_q.astimezone(timezone.utc)          # 이번 회차 창(window) 시작 — 이후 발간 보고서는 '신규' 표기
    end_utc = end_q.astimezone(timezone.utc)                    # 모니터링 기간 끝(경계 시각) — 실행 시각이 아니라 07:00/15:30 경계로 고정
    new_since_weekly = now_utc - timedelta(days=WEEKLY_LOOKBACK_DAYS)
    # 전체 기사 목록/사안 풀에는 '모니터링 기간(경계~경계)' 내 기사만 사용(누적 보고서는 별도 섹션에서만 노출)
    items_win = [x for x in items if new_since_daily <= x["dt"] <= end_utc]
    pool = build_issue_pool(items_win)
    issues = gemini_issues(pool, label_ko)
    gov_ko = gemini_qatar_gov(pool, label_ko)
    flat = None if issues else gemini_flat(pool, label_ko)
    reports = _merge_reports(items, now_utc)
    os.makedirs("archive", exist_ok=True)
    slot_dt, ampm = _slot_of(now_q)
    dno = _daily_no(slot_dt)
    ymd = slot_dt.strftime('%Y%m%d')
    is_weekly = (ampm == "0700" and slot_dt.weekday() == WEEKLY_WEEKDAY and dno is not None)
    wno = _weekly_no(slot_dt.date()) if is_weekly else None

    # 모니터링 일시는 실제 실행 분이 아니라 정규 슬롯 시각(07:00/15:30)으로 표기(늦게 실행돼도 일관).
    globals()["UPDATED_TIME_OVERRIDE"] = "07:00" if ampm == "0700" else "15:30"

    def daily_fname(lang): return f"d-{ymd}-{ampm}-{lang}.html"
    def weekly_fname(lang): return f"w-{ymd}-{lang}.html"
    def home_url(lang): return SITE_BASE if lang == "ko" else f"{SITE_BASE}{lang}.html"
    def main_out(lang): return "index.html" if lang == "ko" else f"{lang}.html"

    # 주간 데이터(1회 수집·요약 후 언어별 번역)
    if is_weekly:
        wk_from = (now_q - timedelta(days=WEEKLY_LOOKBACK_DAYS)).strftime("%m/%d")
        wlabel_ko = f"지난주 종합 · {wk_from} ~ {now_q.strftime('%m/%d')} (카타르시간)"
        witems = collect(now_utc - timedelta(days=WEEKLY_LOOKBACK_DAYS), now_utc, when_days=WEEKLY_LOOKBACK_DAYS + 1)
        witems = filter_minor(witems)
        wpool = build_issue_pool(witems)
        wissues = gemini_issues(wpool, wlabel_ko, weekly=True)
        gov_wk_ko = gemini_qatar_gov(wpool, wlabel_ko)
        wflat = None if wissues else gemini_flat(wpool, wlabel_ko)
        wreports = _merge_reports(witems, now_utc)
        witems_win = [x for x in witems if x["dt"] >= new_since_weekly]

    # 아카이브 파일 목록(기존 전부 보관 + 이번 생성분 3개 언어)
    files = {f for f in os.listdir("archive") if f.endswith(".html")}
    for lang in LANGS:
        files.add(daily_fname(lang))
        if is_weekly:
            files.add(weekly_fname(lang))
    # 정식 호수(제N호)가 매겨진 회차만 콤보박스에 노출 — 정식 발행(제1호) 이전의 '시범' 스냅샷은 목록에서 제외
    metas = [(m, f) for f in files for m in [_archive_meta(f)] if m and m.get("no") is not None]

    # 회차 이동 콤보박스용 매니페스트 — 모든 페이지가 이 파일을 불러와 '전체 회차'를 동적 구성(어느 페이지·어느 날짜로든 자유 이동)
    _manifest = {
        "home": {l: home_url(l) for l in LANGS},
        "latest_daily": {l: daily_fname(l) for l in LANGS},
        "issues": [
            {"lang": m["lang"], "kind": m["kind"], "no": m["no"],
             "dt": m["dt"].isoformat(), "label": _archive_label_text(m, LANG[m["lang"]]), "file": f}
            for (m, f) in metas
        ],
    }
    with open("archive/manifest.json", "w", encoding="utf-8") as _mf:
        json.dump(_manifest, _mf, ensure_ascii=False)

    nav = {l: home_url(l) for l in LANGS}
    for lang in LANGS:
        L = LANG[lang]
        win_label = f"{L['win_' + win_slot]} ({L['tz']})"
        issue_label = L["daily_no"].format(n=dno) if dno else L["daily_demo"]
        iss_l = translate_issues(issues, lang) if issues else None
        gov_l = translate_gov(gov_ko, lang)

        cur = daily_fname(lang)
        lm = [(m, f) for (m, f) in metas if m["lang"] == lang and f != cur]
        lm.sort(key=lambda mf: mf[0]["dt"], reverse=True)
        archive_list = [(m["kind"], _archive_label_text(m, L), f) for (m, f) in lm]

        weekly_inline = None
        if is_weekly:
            wfn = weekly_fname(lang)
            wiss_l = translate_issues(wissues, lang) if wissues else None
            wwin = wlabel_ko.replace("(카타르시간)", "(" + L["tz"] + ")")
            whtml = render(witems_win, wwin, wiss_l, wflat, issue_pool=wpool,
                           archive_list=archive_list, reports=wreports,
                           edition="weekly", lang=lang, nav=nav,
                           home_url=home_url(lang), new_since=new_since_weekly,
                           qatar_gov=translate_gov(gov_wk_ko, lang))
            with open(os.path.join("archive", wfn), "w", encoding="utf-8") as fh:
                fh.write(whtml)
            if wiss_l:
                wbody = render_issues(wiss_l, wpool, now_utc, L, collapse_links=True)
            elif wflat:
                wbody = f'<div class="card sum"><div class="sumbody">{summary_to_html(wflat)}</div></div>'
            else:
                wbody = f'<div class="empty" style="padding:8px 2px">{esc(L["wk_none"])}</div>'
            weekly_inline = (
                '<div class="wsec">'
                '<div class="sumhead"><span class="bar" style="background:var(--accent)"></span>'
                f'{esc(L["wk_head"])} <span class="ai">{esc(L["weekly_no"].format(n=wno))}</span>'
                f'<span class="wmeta">{esc(wwin)}</span></div>'
                + wbody +
                f'<div class="wlink"><a href="{SITE_BASE}archive/{esc(wfn)}">{esc(L["wk_open"])}</a></div>'
                '</div>')

        html = render(items_win, win_label, iss_l, flat, issue_pool=pool,
                      archive_list=archive_list, reports=reports,
                      edition="daily", weekly_inline=weekly_inline,
                      lang=lang, nav=nav, home_url=home_url(lang), new_since=new_since_daily,
                      weekly_from=(wk_from if is_weekly else None), qatar_gov=gov_l)
        with open(main_out(lang), "w", encoding="utf-8") as fh:
            fh.write(html)
        with open(os.path.join("archive", cur), "w", encoding="utf-8") as fh:
            fh.write(html)
        # 중동 전쟁 타임라인 독립 페이지(새 탭으로 열림)
        with open(f"timeline-{lang}.html", "w", encoding="utf-8") as fh:
            fh.write(render_timeline_page(lang))

    mode = "issues" if issues else ("flat" if flat else "none")
    print(f"generated ko/en/ar · dno={dno} · window={label_ko} · items={len(items)} · summary={mode} · "
          f"weekly={'Y' if is_weekly else 'N'} · reports_total={len(reports)}")
    rep_srcs = {}
    for r in reports:
        rep_srcs[r.get("source", "?")] = rep_srcs.get(r.get("source", "?"), 0) + 1
    print("report sources:", sorted(rep_srcs.items(), key=lambda kv: -kv[1]))


def _merge_reports(items, now_utc):
    """이번 수집의 report 항목을 reports.json에 누적(dedupe·기간 정리·최신순)하고 목록 반환."""
    path = "reports.json"
    store = {}
    try:
        with open(path, encoding="utf-8") as f:
            for r in json.load(f):
                # 과거 느슨한 기준으로 저장된 뉴스성 항목은 재검증해 정리(발행처가 연구기관/컨설팅펌인 것만 유지)
                if not looks_report(r.get("title", ""), r.get("source", ""), r.get("shref", "")):
                    continue
                k = (r.get("link", "").split("?")[0]).lower()
                if k:
                    r.setdefault("added", r.get("dt"))   # 과거 항목엔 최초수집시각이 없으므로 발행일로 보정
                    store[k] = r
    except Exception:
        pass
    for x in items:
        if not x.get("report"):
            continue
        k = x["link"].split("?")[0].lower()
        if k in store:
            continue
        store[k] = {"title": x["title"], "link": x["link"], "source": x["source"],
                    "shref": x.get("shref", ""),
                    "dt": x["dt"].astimezone(timezone.utc).isoformat(),
                    "added": now_utc.astimezone(timezone.utc).isoformat(),   # 이번 회차에 처음 수집됨
                    "region": x.get("region", "overseas")}
    # 기간 정리(REPORT_PERSIST_DAYS 이내) + 최신순 정렬 + 보관 상한
    floor = now_utc - timedelta(days=REPORT_PERSIST_DAYS)
    out = []
    for r in store.values():
        try:
            d = datetime.fromisoformat(r["dt"])
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if d < floor:
            continue
        r2 = dict(r); r2["_dt"] = d
        out.append(r2)
    out.sort(key=lambda r: r["_dt"], reverse=True)
    out = out[:REPORT_STORE_MAX]
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if k != "_dt"} for r in out], f, ensure_ascii=False, indent=1)
    # render용: dt·added를 datetime으로
    for r in out:
        r["dt"] = r.pop("_dt")
        _a = r.get("added")
        if isinstance(_a, str):
            try:
                _ad = datetime.fromisoformat(_a)
                if _ad.tzinfo is None:
                    _ad = _ad.replace(tzinfo=timezone.utc)
                r["added"] = _ad
            except Exception:
                r["added"] = r["dt"]
        else:
            r["added"] = r.get("dt")
    return out


if __name__ == "__main__":
    main()
