#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카타르·중동정세 언론 모니터링 (대사관/공관용, 무료·완전자동)
- 갱신 주기(직전 갱신 → 이번 갱신) '창(window)' 안 기사만 수집
- (무료 Gemini) 창 내 기사를 '사안(issue)'별로 자동 묶어: 왼쪽=요약, 오른쪽=관련 기사(카타르/해외/국내)
  * 사안 묶기 실패 시 → '전체 요약 → 기사 나열' 자동 폴백
- 아래에 전체 기사 목록(카타르 필수 / 중동정세 해외·국내) + 관심 매체 링크
- GitHub Actions가 하루 2회(카타르시간 07:00 / 15:30) 실행 → 커밋/게시 → 공개 URL 자동 갱신

환경변수 GEMINI_API_KEY 필요(무료). 없거나 한도 초과(429) 시 요약만 빠지고 나머지는 정상.
"""

import os
import re
import json
import html
import time
import calendar
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    import feedparser
except ImportError:
    raise SystemExit("feedparser가 필요합니다: pip install feedparser")

# ───────────────────────── CONFIG ─────────────────────────
TITLE = "🇶🇦 카타르·중동정세 언론 모니터링"
SUBTITLE = ("매일 오전 7:00·오후 3:30(카타르 시간) 자동 갱신 · 카타르·한국·해외 언론 및 국내외 연구기관 보고서 모니터링 · "
            "AI 사안별 요약과 관련 기사 원문 링크 제공")

Q_QATAR_EN = ["Qatar Iran", "Qatar Doha", "Al Udeid", "Ras Laffan Qatar", "Qatar security"]
Q_QATAR_KO = ["카타르", "카타르 이란", "카타르 도하", "알우데이드", "카타르 미사일", "카타르 정세", "카타르 교민", "카타르 대사관"]
Q_MIDEAST_EN = ["Middle East Iran Israel", "US Iran strikes", "Strait of Hormuz", "Gulf tensions",
                "Iran Israel war", "Gaza ceasefire", "oil price Middle East", "Red Sea shipping"]
Q_MIDEAST_KO = ["중동 정세", "이란 이스라엘", "호르무즈", "걸프 긴장", "이란 미국", "가자 휴전", "국제유가 중동"]
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
    "대외경제정책연구원", "kiep", "한국개발연구원", "kdi", "에너지경제연구원", "keei",
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


def source_region(src, korean):
    low = (src or "").lower()
    if any(k in low for k in QATAR_SOURCES):
        return "qatar"
    if any(k in low for k in IRAN_SOURCES):
        return "iran"
    if korean or any(k in low for k in KOREA_SOURCES):
        return "korea"
    return "overseas"

DIRECT_FEEDS = [
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC Middle East", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
]

QUICK_LINKS = {
    "🇶🇦 카타르 현지 매체": [("Qatar News Agency (QNA)", "https://www.qna.org.qa/en"),
        ("Al Jazeera", "https://www.aljazeera.com/news/"),
        ("Gulf Times", "https://www.gulf-times.com/"),
        ("The Peninsula", "https://thepeninsulaqatar.com/"),
        ("Qatar Tribune", "https://www.qatar-tribune.com/"),
        ("Doha News", "https://dohanews.co/")],
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
        ("The New York Times — ME", "https://www.nytimes.com/section/world/middleeast")],
    "🇰🇷 국내 종합·방송": [("연합뉴스 국제", "https://www.yna.co.kr/international/all"),
        ("YTN", "https://www.ytn.co.kr/"), ("KBS", "https://news.kbs.co.kr/"),
        ("조선일보", "https://www.chosun.com/"), ("중앙일보", "https://www.joongang.co.kr/"),
        ("동아일보", "https://www.donga.com/"), ("한겨레", "https://www.hani.co.kr/"),
        ("경향신문", "https://www.khan.co.kr/")],
    "🇰🇷 국내 경제지": [("매일경제", "https://www.mk.co.kr/"),
        ("한국경제", "https://www.hankyung.com/"),
        ("파이낸셜뉴스", "https://www.fnnews.com/"),
        ("서울경제", "https://www.sedaily.com/"),
        ("이데일리", "https://www.edaily.co.kr/")],
    "🏛️ 카타르 정부 공식": [("외교부 (MOFA)", "https://mofa.gov.qa/en"),
        ("내무부 (MOI)", "https://www.moi.gov.qa/"),
        ("국방부 (MOD)", "https://www.mod.gov.qa/"),
        ("카타르에너지 (QatarEnergy)", "https://www.qatarenergy.qa/en"),
        ("민간항공청 (CAA)", "https://caa.gov.qa/en/"),
        ("정부 커뮤니케이션실 (GCO)", "https://www.gco.gov.qa/en/")],
    "🏛️ 우리 정부(한국) 공식": [("외교부", "https://www.mofa.go.kr/"),
        ("주카타르대사관", "https://overseas.mofa.go.kr/qa-ko/index.do"),
        ("해외안전여행(0404)", "https://www.0404.go.kr/"),
        ("대통령실", "https://www.president.go.kr/"),
        ("korea.net", "https://www.korea.net/"),
        ("산업통상부", "https://www.motie.go.kr/"),
        ("국토교통부", "https://www.molit.go.kr/"),
        ("해양수산부", "https://www.mof.go.kr/"),
        ("국방부", "https://www.mnd.go.kr/")],
    "📑 연구기관·에너지(국책)": [("대외경제정책연구원(KIEP)", "https://www.kiep.go.kr/"),
        ("KDI 한국개발연구원", "https://www.kdi.re.kr/"),
        ("에너지경제연구원(KEEI)", "https://www.keei.re.kr/"),
        ("국제금융센터(KCIF)", "https://www.kcif.or.kr/"),
        ("산업연구원(KIET)", "https://www.kiet.re.kr/"),
        ("한국가스공사(KOGAS)", "https://www.kogas.or.kr/"),
        ("한국석유공사 오피넷(유가)", "https://www.opinet.co.kr/"),
        ("KOTRA 해외시장뉴스", "https://dream.kotra.or.kr/")],
    "📑 민간·금융 연구소": [("현대경제연구원(HRI)", "http://www.hri.co.kr/"),
        ("삼성글로벌리서치(SGR)", "https://www.samsungsgr.com/"),
        ("LG경영연구원", "https://www.lgbr.co.kr/"),
        ("포스코경영연구원(POSRI)", "https://www.posri.re.kr/"),
        ("하나금융경영연구소", "https://www.hanaif.re.kr/"),
        ("한국무역협회(KITA)", "https://www.kita.net/"),
        ("무역협회 국제무역통상연구원", "https://iit.kita.net/"),
        ("자본시장연구원(KCMI)", "https://www.kcmi.re.kr/")],
    "📑 외교·안보 연구기관(국책)": [("국립외교원(IFANS)", "https://www.ifans.go.kr/"),
        ("아산정책연구원", "https://www.asaninst.org/"),
        ("세종연구소", "https://www.sejong.org/")],
    "🌐 해외 연구기관·국제기구": [("IEA 국제에너지기구", "https://www.iea.org/"),
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
        ("Eurasia Group", "https://www.eurasiagroup.net/")],
    "📰 해외 심층분석·경제전망": [("The Economist — ME·Africa", "https://www.economist.com/middle-east-and-africa"),
        ("Economist Intelligence(EIU)", "https://www.eiu.com/"),
        ("Foreign Affairs — ME", "https://www.foreignaffairs.com/middle-east"),
        ("Foreign Policy", "https://foreignpolicy.com/"),
        ("Oxford Economics", "https://www.oxfordeconomics.com/"),
        ("Peterson Institute(PIIE)", "https://www.piie.com/"),
        ("RUSI", "https://www.rusi.org/"),
        ("S&P Global Commodity Insights", "https://www.spglobal.com/commodityinsights/")],
}

# 바로가기 대분류: 관련 매체 / 정부 / 유관기관 (각 아래에 위 세부 그룹을 배치)
QUICK_SECTIONS = [
    ("📰 관련 매체", ["🇶🇦 카타르 현지 매체", "🇮🇷 이란·역내 매체", "🌐 해외(미국·유럽 등) 매체",
                   "🇰🇷 국내 종합·방송", "🇰🇷 국내 경제지"]),
    ("🏛️ 정부", ["🏛️ 카타르 정부 공식", "🏛️ 우리 정부(한국) 공식"]),
    ("📑 유관기관", ["📑 연구기관·에너지(국책)", "📑 민간·금융 연구소", "📑 외교·안보 연구기관(국책)",
                 "🌐 해외 연구기관·국제기구", "📰 해외 심층분석·경제전망"]),
]

MAX_PER_SECTION = 60
POOL_FOR_ISSUES = 40          # 사안 분류에 넘길 기사 수(무료 LLM 입력 8K 토큰 한도 고려)
DESC_MAX = 160                # 각 기사 desc를 프롬프트에 넣을 때 최대 길이(토큰 절약)
SITE_BASE = "/qatar-media-monitor/"   # GitHub Pages 프로젝트 경로(콤보박스 링크 기준)
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
ANTHROPIC_MODELS = ["claude-haiku-4-5", "claude-3-5-haiku-latest"]
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
    am = now_q.replace(hour=BOUNDARY_AM[0], minute=BOUNDARY_AM[1], second=0, microsecond=0)
    pm = now_q.replace(hour=BOUNDARY_PM[0], minute=BOUNDARY_PM[1], second=0, microsecond=0)
    start = am if now_q >= pm else pm - timedelta(days=1)
    label = f"{start.strftime('%m/%d %H:%M')} → {now_q.strftime('%m/%d %H:%M')} (카타르시간)"
    return start, label


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
    "kiep.go.kr", "kdi.re.kr", "keei.re.kr", "kcif.or.kr", "kiet.re.kr", "ifans.go.kr",
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
    "kiep.go.kr", "kdi.re.kr", "keei.re.kr", "kcif.or.kr", "kiet.re.kr", "ifans.go.kr",
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
    for q in Q_REPORTS_KO: feeds.append(("ko", q, gnews_url(q, "ko", REPORT_QUERY_DAYS)))
    for q in Q_REPORTS_EN: feeds.append(("en", q, gnews_url(q, "en", REPORT_QUERY_DAYS)))
    # 한국 기관 자체 발간물: 기관 도메인을 site: 로 직접 조준(중동·유가·카타르 주제만 통과)
    for dom in KO_REPORT_SITE_DOMAINS:
        feeds.append(("ko", f"[site]{dom}", gnews_url(f"site:{dom}", "ko", REPORT_QUERY_DAYS)))
    for name, url in DIRECT_FEEDS: feeds.append(("en", name, url))

    for lang, label, url in feeds:
        try:
            d = feedparser.parse(url)
        except Exception as ex:
            print(f"[warn] feed failed {url}: {ex}")
            continue
        for e in d.entries:
            title = clean_title(e.get("title", "").strip())
            link = e.get("link", "").strip()
            if not title or not link:
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


# 진단 메시지(요약 실패 시 사이트에 표시 → 원인 파악용)
LLM_DIAG = []
def _diag(msg):
    print(msg)
    if len(LLM_DIAG) < 8:
        LLM_DIAG.append(msg)


# ───────────────────── Claude API (Anthropic·최우선·최고 품질) ─────────────────────
def anthropic_call(model, prompt, json_mode):
    key = _anthropic_key()
    if not key:
        return None
    url = "https://api.anthropic.com/v1/messages"
    msgs = [{"role": "user", "content": prompt}]
    if json_mode:
        msgs.append({"role": "assistant", "content": "{"})   # JSON 출력 강제(프리필)
    payload = {"model": model, "max_tokens": 2048, "temperature": 0.3, "messages": msgs}
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            url, data=body,
            headers={"content-type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            txt = data["content"][0]["text"].strip()
            return ("{" + txt) if json_mode else txt          # 프리필한 '{' 복원
        except urllib.error.HTTPError as ex:
            try:
                eb = ex.read().decode("utf-8", "ignore")[:200]
            except Exception:
                eb = ""
            if ex.code == 429:
                _diag(f"[warn] claude {model} 429, retry {attempt+1}/3")
                time.sleep(5 * (attempt + 1)); continue
            _diag(f"[warn] claude {model} HTTP {ex.code} {eb}"); return None
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
            _diag(f"[warn] openrouter {model} HTTP {ex.code} {eb}"); return None
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
                _diag(f"[warn] ghmodels {mid}@{host} HTTP {ex.code} {errbody}")
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
    prompt = (
        "당신은 주카타르대사관 상황실 분석관입니다. " + scope +
        "【모니터링 주제 범위】 이 브리핑의 주제는 '카타르의 국익·안보·경제에 유의미한 중동 정세'입니다. "
        "즉 이스라엘·이란·걸프 무력충돌 및 공습·교전 동향, 외교·중재(특히 카타르의 중재 역할), "
        "호르무즈·홍해 등 해상안전·물류, 국제유가·LNG·에너지, 경제·통상·투자, 항공·교민 안전의 관점에서 "
        "의미 있는 사안만 다룹니다.\n"
        "【사안으로 만들지 말 것(주제 밖)】 정책·전략·안보·경제 함의가 없는 순수 인도적 사연·난민 개인사·미담/르포, "
        "날씨·기상, 스포츠, 연예·문화·생활, 단순 지역 사건사고, 종교 일반 등은 사안으로 뽑지 마세요. "
        "다만 이런 소재라도 카타르 국익·에너지·안보·물류·외교에 직접 연결되면 포함합니다"
        "(예: 가자 휴전 협상·카타르 중재는 '외교·중재' 사안으로 포함하되, 개별 난민의 생활고 미담은 제외).\n"
        "핵심 판별 기준: 가자·이스라엘·이란 등 소재라도 ①카타르가 실제로 역할·조치를 했거나(중재·성명·정상외교·지원·군사·에너지 등), "
        "②카타르가 공격·공습을 당하거나 카타르의 안보·영공·경제·에너지·항공·교민 안전이 직접 영향받거나, "
        "③사안이 중동 무력충돌·에너지·물류·경제 등 정세의 실질 전개일 때 포함하세요. "
        "'카타르 매체에 실렸다'는 사실만으로는 관련성이 생기지 않습니다 — 카타르의 역할도 없고 정세·에너지·경제 함의도 없는 기사는 제외하세요.\n"
        "관련성이 약한 기사는 억지로 사안으로 묶지 말고 제외하고, 애매하면 사안 수를 줄이세요 — 수량보다 정확도·논리성 우선.\n"
        "'사안(issue)'별로 묶으세요. 개수는 그날 내용에 맞게 유연하게(보통 3~7개, 많으면 8개 이상, 정말 조용하면 1~2개). "
        "카테고리 예시: 전쟁·군사(공습·교전 추이) / 외교·중재 / 에너지·유가·LNG / "
        "물류·해상안전(홍해·수에즈·호르무즈) / 경제·통상 / 항공·교민안전.\n"
        "사안은 카타르 국익 관련성이 높은 순서로 배열하세요.\n"
        "각 사안 필드: theme(사안명, 앞에 이모지 1개 권장), "
        "summary(한국어, 정부보고서식 '개조식·했음체'로 3~5개 핵심 포인트. "
        "각 포인트에는 **구체적 수치·일자·주체·규모**(예: 사상자 수, 미사일·드론 수, 국제유가 가격·변동폭, "
        "통항·피격 선박 수, 봉쇄·휴전·중단 기간, 계약·금액·물동량, 지명·기관명 등)를 **가능한 한 포함**해 "
        "이 요약만으로도 상황보고가 될 만큼 충실히 작성. "
        "각 포인트는 명사형 종결어미 '-함/-음/-됨/-임/-없음'으로 끝내고 서술체 '-했다/-이다/-된다'는 절대 쓰지 말 것. "
        "예: '7/31 이란 IRGC가 미군 호위 유조선 2척을 호르무즈 해협서 타격, 승조원 3명 사망 주장함. 브렌트유 배럴당 약 $1 상승함.'), "
        "figures(핵심 수치를 세미콜론(;)으로 2~5개 나열; 사상자·미사일/유가($·변동폭)/통항·물동량/휴전·봉쇄 기간/금액 등, 없으면 \"\"), "
        "ids(그 사안 관련 기사 id 정수 배열, 최대 16개).\n"
        "중요 규칙:\n"
        "- [카타르현지]는 '카타르 매체발'이라는 출처 표시일 뿐, 그 자체로 사안 가치를 부여하지 않습니다. "
        "카타르가 실제로 역할·조치를 한 사안(중재·성명·정상외교·지원·군사·에너지 계약 등)이나, 카타르가 공격·공습을 당하거나 "
        "카타르 국익·안보·영공·경제·에너지·교민 안전에 직접 영향을 주는 사안만 '카타르 관련'으로 최우선하세요. 그런 카타르 실질 관여 사안이 있으면 반드시 1개 이상 만들고 관련 [카타르현지] 기사를 ids에 우선 포함하세요. "
        "단, 카타르 매체에 실렸을 뿐 카타르의 역할이 없고 정세·에너지·경제 함의도 없는 연성기사(예: 난민 개인사 미담, 지역 생활기사)는 "
        "최우선은커녕 사안으로 만들지 마세요.\n"
        "- 각 사안의 ids에는 그 사안과 관련된 카타르·이란·해외·국내 4개 권역의 '주요(메이저) 기사를 가능한 한 빠짐없이' 넣으세요"
        "(권역별 최대 4~5개까지). 요약 옆에서 웬만한 주요 기사가 다 보이게 하는 것이 목표입니다.\n"
        "- 동일 내용이면 메이저·공신력 매체(연합/뉴시스/KBS/MBC/SBS/조선/중앙/동아/한겨레/경향/한국경제/매일경제/파이낸셜뉴스, Reuters/AP/AFP/Bloomberg/CNN/BBC/Guardian, QNA/Al Jazeera/Gulf Times/Peninsula/Doha News) 기사를 우선 선택하세요.\n"
        "- 제공된 기사에 없는 사실·수치는 절대 창작 금지. 한국어로. 반드시 아래 JSON만 출력:\n"
        "{\"issues\":[{\"theme\":\"\",\"summary\":\"\",\"figures\":\"\",\"ids\":[0,1]}]}\n\n"
        f"[커버기간] {win_label}\n[기사 목록]\n" + "\n".join(lines)
    )
    out = gemini_generate(prompt, json_mode=True)
    if not out:
        return None
    try:
        data = json.loads(out)
        issues = data.get("issues") if isinstance(data, dict) else None
        if issues and isinstance(issues, list):
            return issues
    except Exception as ex:
        print(f"[warn] issues json parse failed: {ex}")
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
        "■ 카타르 관련: (불릿 2~4개, 없으면 '해당 기간 카타르 직접 특이사항 없음')\n■ 중동정세 주요: (불릿 3~6개)\n"
        "모든 불릿은 정부보고서식 '개조식·했음체'로, 명사형 종결어미 '-함/-음/-됨/-임/-없음'으로 끝낼 것(서술체 '-했다/-이다' 금지). "
        "제목·발췌에 없는 사실은 창작 금지. 불릿 끝에 (매체명). '- '로 시작. 마크다운 헤더(#) 금지.\n\n"
        + "\n".join(lines)
    )
    return gemini_generate(prompt, json_mode=False)


# ───────────────────── 렌더링 ─────────────────────
def ago(dt, now):
    m = int((now - dt).total_seconds() // 60)
    if m < 60: return f"{m}분 전"
    if m < 1440: return f"{m//60}시간 전"
    return f"{m//1440}일 전"


def esc(s):
    return html.escape(s or "", quote=True)


def li(x, now_utc):
    d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
    meta = " · ".join([esc(x["source"]), d, ago(x["dt"], now_utc)])
    flag = '<span class="qflag">카타르</span> ' if x["qatar"] else ""
    desc = f'<div class="dsc">{esc(x["desc"])}</div>' if x["desc"] else ""
    return (f'<li>{flag}<a href="{esc(x["link"])}" target="_blank" rel="noopener">{esc(x["title"])}</a>'
            f'{desc}<div class="meta">{meta}</div></li>')


def link_row(x):
    d = x["dt"].astimezone(TZ).strftime("%m/%d")
    return (f'<a href="{esc(x["link"])}" target="_blank" rel="noopener">{esc(x["title"])}'
            f'<span class="src">{esc(x["source"])} · {d}</span></a>')


def render_issues(issues, pool, now_utc):
    out = []
    for n, iss in enumerate(issues, 1):
        theme = esc(str(iss.get("theme", f"사안 {n}")))
        summary = esc(str(iss.get("summary", "")))
        figures = esc(str(iss.get("figures", "")))
        ids = [j for j in iss.get("ids", []) if isinstance(j, int) and 0 <= j < len(pool)]
        arts = [pool[j] for j in ids]
        q = [a for a in arts if a["region"] == "qatar"]
        ir = [a for a in arts if a["region"] == "iran"]
        ov = [a for a in arts if a["region"] == "overseas"]
        kr = [a for a in arts if a["region"] == "korea"]
        groups = ""
        if q:  groups += '<div class="grp"><div class="gh">🇶🇦 카타르 현지</div>' + "".join(link_row(a) for a in q) + '</div>'
        if ir: groups += '<div class="grp"><div class="gh">🇮🇷 이란·역내</div>' + "".join(link_row(a) for a in ir) + '</div>'
        if ov: groups += '<div class="grp"><div class="gh">🌐 해외(미국·유럽 등)</div>' + "".join(link_row(a) for a in ov) + '</div>'
        if kr: groups += '<div class="grp"><div class="gh">🇰🇷 국내(한국)</div>' + "".join(link_row(a) for a in kr) + '</div>'
        if not groups:
            groups = '<div class="grp"><div class="gh" style="color:var(--muted)">관련 링크 매핑 없음</div></div>'
        fig = f'<div class="figs">핵심 수치: {figures}</div>' if figures else ""
        out.append(
            f'<div class="issue"><div class="ihead"><span class="num">사안 {n}</span><h2>{theme}</h2></div>'
            f'<div class="row"><div class="left"><div class="sh">핵심 요약</div><p>{summary}</p>{fig}</div>'
            f'<div class="right">{groups}</div></div></div>')
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


def render(items, win_label, issues, flat_text, issue_pool=None, archive_list=None,
           reports=None, issue_label=None, weekly_inline=None):
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    if issue_pool is None:
        issue_pool = items[:POOL_FOR_ISSUES]
    def is_pin(x): return x["qatar"] or x["region"] == "qatar"
    qatar = [x for x in items if is_pin(x)][:MAX_PER_SECTION]
    me_ov = [x for x in items if not is_pin(x) and x["region"] == "overseas"][:MAX_PER_SECTION]
    me_ir = [x for x in items if not is_pin(x) and x["region"] == "iran"][:MAX_PER_SECTION]
    me_kr = [x for x in items if not is_pin(x) and x["region"] == "korea"][:MAX_PER_SECTION]

    def block(rows, empty):
        return "\n".join(li(x, now_utc) for x in rows) or f'<li class="empty">{empty}</li>'

    if issues:
        summary_html = ('<div class="sumhead"><span class="bar"></span>🧭 이번 회차 사안별 요약 '
                        '<span class="ai">AI 자동요약</span></div>' + render_issues(issues, issue_pool, now_utc))
    elif flat_text:
        summary_html = ('<div class="card sum"><div class="sumhead"><span class="bar"></span>🧭 이번 회차 핵심 요약 '
                        '<span class="ai">AI 자동요약</span></div>'
                        f'<div class="sumbody">{summary_to_html(flat_text)}</div></div>')
    else:
        diag = " · ".join(LLM_DIAG[-3:]) if LLM_DIAG else ""
        diag_html = f'<div class="pl" style="color:var(--muted);font-size:11px;margin-top:6px">진단: {esc(diag)}</div>' if diag else ""
        summary_html = ('<div class="card sum"><div class="sumhead"><span class="bar"></span>🧭 이번 회차 핵심 요약</div>'
                        '<div class="sumbody"><div class="pl" style="color:var(--muted)">요약 일시 미생성 — '
                        '다음 갱신에 자동 재시도됩니다. 아래 기사 목록은 정상입니다.</div>'
                        f'{diag_html}</div></div>')

    quick = ""
    for sec_title, group_names in QUICK_SECTIONS:
        quick += f'<div class="qsec">{esc(sec_title)}</div>'
        for g in group_names:
            links = QUICK_LINKS.get(g, [])
            if not links:
                continue
            slinks = sorted(links, key=_ql_key)   # 그룹 내 가나다/ABC 정렬
            chips = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)}</a>' for n, u in slinks)
            quick += f'<div class="qgroup"><div class="qh">{esc(g)}</div><div class="qchips">{chips}</div></div>'

    # 분석·보고서 — main()에서 누적·정렬해 넘겨준 목록(최신순)을 표시. 없으면 이번 창의 report 항목으로 폴백.
    rep_list = reports if reports is not None else [x for x in items if x.get("report")]
    tagmap = {"qatar": "카타르", "iran": "이란", "overseas": "해외", "korea": "국내"}
    def rep_dt(x):
        d = x.get("dt")
        return d.astimezone(TZ).strftime("%m/%d") if hasattr(d, "astimezone") else str(d or "")[:10]
    rows = "".join(
        f'<a href="{esc(x["link"])}" target="_blank" rel="noopener">'
        f'<span class="tag">{esc(tagmap.get(x.get("region","overseas"),"해외"))}</span>{esc(x["title"])}'
        f'<span class="src">{esc(x["source"])} · {rep_dt(x)}</span></a>'
        for x in rep_list[:REPORT_SHOW_MAX])
    if rows:
        report_html = ('<div class="card report"><div class="sumhead">'
                       '<span class="bar" style="background:var(--gold)"></span>📑 중동정세 심층 분석·보고서'
                       '<span class="hnote">국내외 연구기관·국제기구·컨설팅펌 발간물만</span>'
                       '<span class="ai" style="background:var(--gold)">최신순</span></div>'
                       f'<div class="reprows">{rows}</div></div>')
    else:
        report_html = ""

    # 지난 회차 콤보박스 — 전 회차 보관(일간/주간 optgroup 구분, 최신순)
    opts_daily, opts_weekly = "", ""
    for kind, label, fname in (archive_list or []):
        o = f'<option value="{SITE_BASE}archive/{esc(fname)}">{esc(label)}</option>'
        if kind == "weekly":
            opts_weekly += o
        else:
            opts_daily += o
    groups = f'<option value="{SITE_BASE}">이번 회차 (최신)</option>'
    if opts_daily:
        groups += f'<optgroup label="일간">{opts_daily}</optgroup>'
    if opts_weekly:
        groups += f'<optgroup label="주간 종합">{opts_weekly}</optgroup>'
    archive_html = ('<div class="archsel">🗂️ 지난 회차 보기: '
                    f'<select onchange="if(this.value)location.href=this.value">{groups}</select></div>')

    issuelabel = f'<span class="issno">{esc(issue_label)}</span>' if issue_label else ""
    weekly_html = weekly_inline or ""

    return TEMPLATE.format(
        archive=archive_html, report=report_html, weekly=weekly_html, issuelabel=issuelabel,
        title=esc(TITLE), subtitle=esc(SUBTITLE),
        updated=now_q.strftime("%Y-%m-%d %H:%M"), window=esc(win_label),
        n_q=len(qatar), n_me=len(me_ov) + len(me_ir) + len(me_kr),
        n_all=len(qatar) + len(me_ov) + len(me_ir) + len(me_kr), summary=summary_html,
        qatar=block(qatar, "이번 창(window)에 카타르 직접 관련 신규 기사 없음"),
        me_en=block(me_ov, "이번 창에 해외 신규 기사 없음"),
        me_ir=block(me_ir, "이번 창에 이란·역내 매체 신규 기사 없음"),
        me_ko=block(me_kr, "이번 창에 국내 신규 기사 없음"),
        quick=quick,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root{{--bg:#0b1220;--panel:#131c2e;--panel2:#0f1729;--line:#243149;--txt:#e6edf7;--muted:#93a1b8;--accent:#4da3ff;--green:#2fbf71;--gold:#f2b134}}
  @media (prefers-color-scheme:light){{:root{{--bg:#f4f6fb;--panel:#fff;--panel2:#eef2f9;--line:#dbe2ee;--txt:#14213a;--muted:#5a6b85}}}}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);line-height:1.5;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
  .wrap{{max-width:1180px;margin:0 auto;padding:18px 14px 60px}}
  header{{position:sticky;top:0;background:linear-gradient(180deg,var(--bg) 72%,transparent);
    padding:12px 0;border-bottom:1px solid var(--line);margin-bottom:16px;z-index:5}}
  .titrow{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}
  .dot{{width:10px;height:10px;border-radius:50%;background:var(--green);animation:p 2s infinite}}
  @keyframes p{{0%{{box-shadow:0 0 0 0 rgba(47,191,113,.5)}}70%{{box-shadow:0 0 0 8px rgba(47,191,113,0)}}100%{{box-shadow:0 0 0 0 rgba(47,191,113,0)}}}}
  h1{{font-size:19px;margin:0}}
  .sub{{color:var(--muted);font-size:12.5px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
  .sub b{{color:var(--txt)}}
  .sumhead{{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;margin:6px 0 12px}}
  .sumhead .bar{{width:3px;height:16px;background:var(--accent);border-radius:2px}}
  .ai{{font-size:10.5px;font-weight:700;color:#111;background:var(--accent);padding:1px 7px;border-radius:6px}}
  .issue{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden}}
  .issue .ihead{{display:flex;align-items:center;gap:8px;padding:11px 15px;border-bottom:1px solid var(--line);background:var(--panel2)}}
  .issue .ihead .num{{font-size:11.5px;font-weight:800;color:#111;background:var(--gold);border-radius:6px;padding:1px 8px}}
  .issue .ihead h2{{font-size:14.5px;margin:0}}
  .row{{display:grid;grid-template-columns:0.78fr 1.22fr;gap:0}}
  @media (max-width:760px){{.row{{grid-template-columns:1fr}}}}
  .left{{padding:13px 16px;border-right:1px solid var(--line)}}
  @media (max-width:760px){{.left{{border-right:none;border-bottom:1px solid var(--line)}}}}
  .left .sh{{font-size:11px;color:var(--accent);font-weight:800;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}}
  .left p{{margin:0 0 8px;font-size:13.5px}}
  .left .figs{{font-size:12.5px;color:var(--muted)}}
  .right{{padding:13px 16px}}
  .grp{{margin-bottom:9px}} .grp .gh{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px}}
  .grp a{{display:block;color:var(--txt);text-decoration:none;font-size:13px;font-weight:600;margin:5px 0}}
  .grp a:hover{{color:var(--accent);text-decoration:underline}}
  .grp a .src{{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:1px}}
  .tq{{font-size:10px;font-weight:700;color:#111;background:var(--gold);border-radius:5px;padding:0 5px;margin-right:4px;vertical-align:middle}}
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
  details.fulllist{{margin-top:6px}}
  details.fulllist>summary{{cursor:pointer;list-style:none;user-select:none;
    font-size:13px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;
    padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}}
  details.fulllist>summary::-webkit-details-marker{{display:none}}
  details.fulllist>summary:hover{{color:var(--txt)}}
  details.fulllist[open]>summary{{margin-bottom:12px}}
  details.fulllist .chev{{display:inline-block;transition:transform .15s;margin-right:4px}}
  details.fulllist[open] .chev{{transform:rotate(90deg)}}
  ul{{list-style:none;margin:0;padding:0}}
  li{{padding:10px 0;border-bottom:1px solid var(--line)}} li:last-child{{border-bottom:none}}
  li a{{color:var(--txt);text-decoration:none;font-size:14px;font-weight:600}}
  li a:hover{{color:var(--accent);text-decoration:underline}}
  .qflag{{font-size:10.5px;font-weight:700;color:#111;background:var(--gold);padding:1px 6px;border-radius:6px;vertical-align:middle}}
  .dsc{{color:var(--muted);font-size:12.5px;margin-top:3px}}
  .meta{{color:var(--muted);font-size:11.5px;margin-top:3px;opacity:.85}}
  .empty{{color:var(--muted);font-size:13px}}
  .sechd{{font-size:13px;font-weight:800;color:var(--muted);margin:20px 0 8px;text-transform:uppercase;letter-spacing:.5px}}
  .qsec{{font-size:13.5px;font-weight:800;color:var(--txt);margin:18px 0 10px;padding-bottom:5px;border-bottom:1px solid var(--line)}}
  .qsec:first-child{{margin-top:2px}}
  .qgroup{{margin:2px 0 12px}} .qh{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}}
  .qchips{{display:flex;flex-wrap:wrap;gap:7px}}
  .qchips a{{font-size:12.5px;color:var(--accent);text-decoration:none;border:1px solid var(--line);background:var(--panel2);border-radius:8px;padding:5px 10px}}
  .qchips a:hover{{text-decoration:underline}}
  .archsel{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--muted);margin:2px 0 12px}}
  .archsel select{{font-size:12.5px;color:var(--txt);background:var(--panel2);border:1px solid var(--line);
    border-radius:8px;padding:5px 9px;max-width:60%}}
  .issno{{font-size:11.5px;font-weight:800;color:#111;background:var(--gold);border-radius:6px;padding:2px 9px}}
  .wsec{{margin:2px 0 18px;padding:12px 15px 14px;border:1px solid rgba(242,177,52,.5);border-radius:14px;
    background:linear-gradient(180deg,rgba(242,177,52,.08),transparent)}}
  .wsec .sumhead{{margin-top:2px}}
  .wsec .wmeta{{font-size:11.5px;color:var(--muted);font-weight:400;margin-left:auto}}
  .wsec .wlink{{margin-top:8px;font-size:12.5px}}
  .wsec .wlink a{{color:var(--accent);text-decoration:none}}
  .wsec .wlink a:hover{{text-decoration:underline}}
  .searchbox{{display:flex;align-items:center;gap:8px;margin:2px 0 6px;font-size:13px}}
  .searchhint{{font-size:11.5px;color:var(--muted);margin:0 0 16px;line-height:1.45}}
  .searchbox input{{flex:1;max-width:440px;font-size:13px;color:var(--txt);background:var(--panel2);
    border:1px solid var(--line);border-radius:9px;padding:8px 11px}}
  .searchbox input::placeholder{{color:var(--muted)}}
  .kwn{{color:var(--muted);font-size:12px;white-space:nowrap}}
  .card.report{{border-color:rgba(242,177,52,.5);background:linear-gradient(180deg,rgba(242,177,52,.08),transparent)}}
  .reprows a{{display:block;color:var(--txt);text-decoration:none;font-size:13.5px;font-weight:700;margin:7px 0}}
  .reprows a:hover{{color:var(--accent);text-decoration:underline}}
  .reprows a .src{{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:1px}}
  .reprows a .tag{{display:inline-block;font-size:10px;font-weight:800;color:#111;background:var(--gold);border-radius:5px;padding:0 6px;margin-right:6px;vertical-align:middle}}
  footer{{margin-top:6px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:12px}}
  footer .sign{{text-align:right;margin-top:10px;font-weight:300;color:var(--muted);font-size:12.5px;letter-spacing:.2px}}
  .hnote{{font-size:11px;font-weight:400;color:var(--muted);letter-spacing:0}}
  @media (max-width:520px){{h1{{font-size:16.5px}} .qchips a{{padding:6px 11px}} .archsel select{{max-width:100%}}}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="titrow"><span class="dot"></span><h1>{title}</h1>{issuelabel}</div>
    <div class="sub">
      <span>{subtitle}</span>
      <span>최종 갱신: <b>{updated} (카타르시간)</b></span>
      <span>커버 기간: <b>{window}</b></span>
      <span>카타르 <b>{n_q}</b>건 · 중동정세 <b>{n_me}</b>건</span>
    </div>
  </header>

  {archive}

  {weekly}

  <div class="searchbox">🔎 <input id="kw" type="search" autocomplete="off"
      placeholder="키워드로 요약·기사·매체 필터 (예: LNG, 호르무즈, 유가)"> <span id="kwn" class="kwn"></span></div>
  <div class="searchhint">※ 이 페이지에 표시된 <b>뉴스 제목·요약문·매체명</b>에서 검색어가 보이는 항목만 남기는 방식입니다(기사 원문 전체나 지난 회차는 검색 대상이 아니며, 지난 회차는 위 콤보박스로 열어 검색).</div>

  {summary}

  <details class="fulllist">
    <summary><span class="chev">▸</span> 전체 기사 목록 (총 {n_all}건) — 클릭해서 펼치기 · 카타르/이란/해외/국내</summary>
    <div class="grid4">
      <div class="card"><h2><span class="bar"></span>🇶🇦 카타르</h2><ul>{qatar}</ul></div>
      <div class="card"><h2><span class="bar"></span>🇮🇷 이란·역내</h2><ul>{me_ir}</ul></div>
      <div class="card"><h2><span class="bar"></span>🌐 해외(미국·유럽 등)</h2><ul>{me_en}</ul></div>
      <div class="card"><h2><span class="bar"></span>🇰🇷 국내(한국)</h2><ul>{me_ko}</ul></div>
    </div>
  </details>

  {report}

  <div class="card">
    <h2><span class="bar"></span>관련 매체 · 정부 · 유관기관 바로가기 <span class="hnote">(가나다·알파벳순 기재)</span></h2>
    {quick}
  </div>

  <footer>
    본 페이지는 카타르·한국·해외 주요 언론과 국내외 연구기관·국제기구·정부기관의 공개 자료를 자동으로 수집하여, 카타르와 관련된 중동 정세를 사안별로 정리한 것입니다. 직전 회차 이후 새로 보도·발간된 자료만 반영하며, 단순 취합·비정식 매체는 제외합니다.
    <br>갱신은 매일 카타르 시간 오전 7:00과 오후 3:30에 자동으로 이루어지며, 일요일 오전 회차에는 지난 한 주를 종합한 주간 리포트를 함께 제공합니다.
    <br>사안 요약은 AI가 자동 생성하므로 사실관계·수치에 오류가 있을 수 있으며, 자동 수집 특성상 일부 기사·보고서가 누락될 수 있습니다. 본 화면은 <b>참고용</b>이오니, 중요한 사안은 각 원문과 추가 검색을 통해 반드시 재확인하시기 바랍니다.
    <div class="sign">— 주카타르대사관 Commercial Section</div>
  </footer>
</div>
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
  // 키워드 검색 — 사안 요약·전체목록·보고서·관심매체 링크를 즉시 필터
  (function () {{
    var inp = document.getElementById('kw');
    if (!inp) return;
    var sels = ['.issue', 'details.fulllist li', '.reprows a', '.qchips a'];
    function apply() {{
      var q = inp.value.trim().toLowerCase();
      var fl = document.querySelector('details.fulllist');
      if (fl && q) fl.open = true;
      var shown = 0;
      sels.forEach(function (s) {{
        document.querySelectorAll(s).forEach(function (el) {{
          var hit = !q || (el.textContent || '').toLowerCase().indexOf(q) >= 0;
          el.style.display = hit ? '' : 'none';
          if (hit && q) shown++;
        }});
      }});
      var n = document.getElementById('kwn');
      if (n) n.textContent = q ? (shown + '건 표시') : '';
    }}
    inp.addEventListener('input', apply);
  }})();
</script>
</body>
</html>
"""


# 요약 풀에 우선 넣을 '메이저/공신력' 매체 힌트(카타르 현지는 별도로 최우선 고정)
MAJOR_HINTS = [
    "qatar news agency", "qna", "gulf times", "peninsula", "qatar tribune", "doha news",
    "al jazeera", "aljazeera", "lusail",
    "yonhap", "연합", "뉴시스", "newsis", "뉴스1", "news1", "ytn", "kbs", "mbc", "sbs", "jtbc",
    "조선", "chosun", "중앙", "joongang", "joins", "동아", "donga",
    "한겨레", "hani", "경향", "khan", "kyunghyang", "서울신문", "seoul", "문화일보", "munhwa",
    "매일경제", "매경", "mk.co", "maeil", "한국경제", "hankyung",
    "파이낸셜뉴스", "fnnews", "이데일리", "edaily", "머니투데이", "moneytoday", "서울경제", "sedaily",
    "reuters", "ap ", "associated press", "afp", "bloomberg", "cnn", "bbc",
    "the guardian", "washington post", "new york times", "wall street journal", "financial times",
    "irna", "press tv", "tehran times", "mehr", "al-alam",
]

def _is_major(x):
    s = (x.get("source") or "").lower()
    return any(m in s for m in MAJOR_HINTS)

def build_issue_pool(items):
    """사안 요약용 풀: 카타르 관련 최우선 + 국내/해외 메이저 우선, 나머지 최신순."""
    qatar = [x for x in items if x["qatar"] or x["region"] == "qatar"]
    others = [x for x in items if not (x["qatar"] or x["region"] == "qatar")]
    others_major = [x for x in others if _is_major(x)]
    others_rest = [x for x in others if not _is_major(x)]
    n_qatar = min(len(qatar), 14)                      # 카타르 현지 최소 확보
    pool = qatar[:n_qatar] + others_major + others_rest
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

def _archive_label(fname):
    """아카이브 파일명 → (kind, 정렬키(datetime), 라벨). 알 수 없으면 None."""
    n = fname[:-5] if fname.endswith(".html") else fname
    try:
        if n.startswith("d-"):
            y, m, d = int(n[2:6]), int(n[6:8]), int(n[8:10])
            ampm = n[11:15]
            hh, mm = (7, 0) if ampm == "0700" else (15, 30)
            slot = datetime(y, m, d, hh, mm, tzinfo=TZ)
            no = _daily_no(slot)
            tail = f"{m:02d}/{d:02d} {hh:02d}:{mm:02d}"
            return ("daily", slot, (f"제{no}호 · {tail}" if no else f"(시범) {tail}"))
        if n.startswith("w-"):
            y, m, d = int(n[2:6]), int(n[6:8]), int(n[8:10])
            sd = datetime(y, m, d, 7, 0, tzinfo=TZ)
            no = _weekly_no(sd.date())
            return ("weekly", sd, (f"주간 제{no}호 · ~{m:02d}/{d:02d}" if no else f"주간 ~{m:02d}/{d:02d}"))
    except Exception:
        return None
    return None


def main():
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    start_q, label = window_bounds(now_q)
    items = collect(start_q.astimezone(timezone.utc), now_utc)
    pool = build_issue_pool(items)
    issues = gemini_issues(pool, label)
    flat = None if issues else gemini_flat(pool, label)
    reports = _merge_reports(items, now_utc)

    os.makedirs("archive", exist_ok=True)
    slot_dt, ampm = _slot_of(now_q)
    dno = _daily_no(slot_dt)
    daily_fname = f"d-{slot_dt.strftime('%Y%m%d')}-{ampm}.html"
    issue_label = (f"일간 제{dno}호" if dno else "일간(시범)")

    # 일요일 오전 회차 → 지난 7일 주간 종합 리포트도 생성(일간과 같은 페이지에 동시 노출)
    is_weekly = (ampm == "0700" and slot_dt.weekday() == WEEKLY_WEEKDAY and dno is not None)
    weekly_fname = f"w-{slot_dt.strftime('%Y%m%d')}.html" if is_weekly else None
    weekly_inline = None

    # 콤보박스 목록: 기존 아카이브 전부 보관(삭제 없음) + 이번 생성분 포함, 최신순
    files = {f for f in os.listdir("archive") if f.endswith(".html")}
    files.add(daily_fname)
    if weekly_fname:
        files.add(weekly_fname)
    entries = []
    for f in files:
        info = _archive_label(f)
        if info:
            entries.append((info[0], info[1], info[2], f))
    entries.sort(key=lambda e: e[1], reverse=True)
    archive_list = [(k, lab, f) for (k, sk, lab, f) in entries if f != daily_fname]

    # 주간 리포트 생성
    if is_weekly:
        wk_from = (now_q - timedelta(days=WEEKLY_LOOKBACK_DAYS)).strftime("%m/%d")
        wlabel = f"지난주 종합 · {wk_from} → {now_q.strftime('%m/%d')} (카타르시간)"
        witems = collect(now_utc - timedelta(days=WEEKLY_LOOKBACK_DAYS), now_utc,
                         when_days=WEEKLY_LOOKBACK_DAYS + 1)
        wpool = build_issue_pool(witems)
        wissues = gemini_issues(wpool, wlabel, weekly=True)
        wflat = None if wissues else gemini_flat(wpool, wlabel)
        wreports = _merge_reports(witems, now_utc)
        wno = _weekly_no(slot_dt.date())
        # (1) 주간 단독 아카이브 페이지(콤보박스·영구 보관용)
        whtml = render(witems, wlabel, wissues, wflat, issue_pool=wpool,
                       archive_list=archive_list, reports=wreports,
                       issue_label=f"주간 제{wno}호")
        with open(os.path.join("archive", weekly_fname), "w", encoding="utf-8") as f:
            f.write(whtml)
        # (2) 일간 페이지 상단에 함께 노출할 주간 요약 인라인 블록
        if wissues:
            wbody = render_issues(wissues, wpool, now_utc)
        elif wflat:
            wbody = f'<div class="card sum"><div class="sumbody">{summary_to_html(wflat)}</div></div>'
        else:
            wbody = '<div class="empty" style="padding:8px 2px">주간 요약 미생성 — 다음 갱신에 재시도됩니다.</div>'
        weekly_inline = (
            '<div class="wsec">'
            '<div class="sumhead"><span class="bar" style="background:var(--gold)"></span>'
            f'📅 지난주 주간 종합 리포트 <span class="ai" style="background:var(--gold)">주간 제{wno}호</span>'
            f'<span class="wmeta">{esc(wlabel)}</span></div>'
            + wbody +
            f'<div class="wlink"><a href="{SITE_BASE}archive/{esc(weekly_fname)}">주간 리포트 단독 페이지로 열기 →</a></div>'
            '</div>')

    html = render(items, label, issues, flat, issue_pool=pool,
                  archive_list=archive_list, reports=reports,
                  issue_label=issue_label, weekly_inline=weekly_inline)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join("archive", daily_fname), "w", encoding="utf-8") as f:
        f.write(html)

    mode = "issues" if issues else ("flat" if flat else "none")
    print(f"generated · {issue_label} · window={label} · items={len(items)} · summary={mode} · "
          f"weekly={'Y' if is_weekly else 'N'} · reports_total={len(reports)} · archive={len(archive_list)}")
    # 진단: 보고서 발행처 분포(한국 기관이 실제 잡히는지 확인용)
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
                    "dt": x["dt"].astimezone(timezone.utc).isoformat(), "region": x.get("region", "overseas")}
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
    # render용: dt를 datetime으로
    for r in out:
        r["dt"] = r.pop("_dt")
    return out


if __name__ == "__main__":
    main()
