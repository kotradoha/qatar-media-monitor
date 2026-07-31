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
SUBTITLE = "갱신 주기 내 사안별 요약 · 카타르 관련 필수 포함 · 공관 모니터링용"

Q_QATAR_EN = ["Qatar Iran", "Qatar Doha", "Al Udeid", "Ras Laffan Qatar", "Qatar security"]
Q_QATAR_KO = ["카타르", "카타르 이란", "카타르 도하", "알우데이드", "카타르 미사일", "카타르 정세", "카타르 교민", "카타르 대사관"]
Q_MIDEAST_EN = ["Middle East Iran Israel", "US Iran strikes", "Strait of Hormuz", "Gulf tensions",
                "Iran Israel war", "Gaza ceasefire", "oil price Middle East", "Red Sea shipping"]
Q_MIDEAST_KO = ["중동 정세", "이란 이스라엘", "호르무즈", "걸프 긴장", "이란 미국", "가자 휴전", "국제유가 중동"]

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
KOREA_SOURCES = ["yonhap", "연합", "ytn", "kbs", "mbc", "sbs", "조선", "chosun", "중앙", "joongang",
                 "joins", "동아", "donga", "한국경제", "hankyung", "매일경제", "mk.co", "maeil",
                 "한겨레", "hani", "경향", "khan", "서울", "문화", "파이낸셜", "fnnews", "뉴시스", "newsis",
                 "이데일리", "edaily", "머니투데이", "news1", "뉴스1"]


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
    "카타르 현지 매체": [("Qatar News Agency (QNA)", "https://www.qna.org.qa/en"),
        ("Al Jazeera", "https://www.aljazeera.com/news/"),
        ("Gulf Times", "https://www.gulf-times.com/"),
        ("The Peninsula", "https://thepeninsulaqatar.com/"),
        ("Qatar Tribune", "https://www.qatar-tribune.com/"),
        ("Doha News", "https://dohanews.co/")],
    "미국·해외 주요 매체": [("CNN", "https://www.cnn.com/world"),
        ("Reuters — Middle East", "https://www.reuters.com/world/middle-east/"),
        ("BBC — Middle East", "https://www.bbc.com/news/world/middle_east"),
        ("AP — Middle East", "https://apnews.com/hub/middle-east"),
        ("The New York Times — ME", "https://www.nytimes.com/section/world/middleeast")],
    "이란·역내 매체": [("Tehran Times", "https://www.tehrantimes.com/"),
        ("Press TV", "https://www.presstv.ir/"),
        ("IRNA (English)", "https://en.irna.ir/"),
        ("Iran International", "https://www.iranintl.com/en")],
    "국내(한국) 매체": [("연합뉴스 국제", "https://www.yna.co.kr/international/all"),
        ("YTN", "https://www.ytn.co.kr/"), ("KBS", "https://news.kbs.co.kr/"),
        ("조선일보", "https://www.chosun.com/"), ("중앙일보", "https://www.joongang.co.kr/"),
        ("동아일보", "https://www.donga.com/"),
        ("한국경제", "https://www.hankyung.com/"), ("매일경제", "https://www.mk.co.kr/")],
    "정부·공식 공지": [("카타르 외무부(MOFA) 성명", "https://mofa.gov.qa/en/latest-articles/statements"),
        ("한국 외교부 해외안전여행(0404)", "https://www.0404.go.kr/"),
        ("외교부 이란 여행경보", "https://0404.go.kr/ntnSafetyInfo/176/detail")],
}

MAX_PER_SECTION = 60
POOL_FOR_ISSUES = 40          # 사안 분류에 넘길 기사 수(무료 LLM 입력 8K 토큰 한도 고려)
DESC_MAX = 160                # 각 기사 desc를 프롬프트에 넣을 때 최대 길이(토큰 절약)
BOUNDARY_AM = (7, 0)
BOUNDARY_PM = (15, 30)
TZ = timezone(timedelta(hours=3))          # Asia/Qatar (UTC+3)
# 요약 엔진 우선순위: GitHub Models → Groq → Gemini (되는 것 자동 사용)
# GitHub Models(무료·GitHub 계정·전세계·리전제한 없음). OpenAI 호환.
# GitHub Actions 내장 GITHUB_TOKEN(permissions: models:read)으로 호출 → 별도 키/PAT 불필요.
GH_ENDPOINT = "https://models.github.ai/inference/chat/completions"
GH_MODELS = ["openai/gpt-4o-mini", "openai/gpt-4.1-mini", "meta/Llama-3.3-70B-Instruct"]
GEMINI_MODELS = ["gemini-2.0-flash-lite", "gemini-2.0-flash"]  # 순서대로 폴백(무료 한도 넉넉한 lite 우선)
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]  # Groq(무료·카드불필요·전세계)
# ──────────────────────────────────────────────────────────

feedparser.USER_AGENT = "Mozilla/5.0 (compatible; MideastMediaMonitor/1.0)"
TAG_RE = re.compile(r"<[^>]+>")
HANGUL_RE = re.compile(r"[가-힣]")


def gnews_url(query, lang):
    q = query.replace(" ", "%20")
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={q}%20when:2d&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={q}%20when:2d&hl=en-US&gl=US&ceid=US:en"


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


def collect(win_start_utc, now_utc):
    items, seen = [], set()
    feeds = []
    for q in Q_QATAR_EN: feeds.append(("en", q, gnews_url(q, "en")))
    for q in Q_QATAR_KO: feeds.append(("ko", q, gnews_url(q, "ko")))
    for q in Q_MIDEAST_EN: feeds.append(("en", q, gnews_url(q, "en")))
    for q in Q_MIDEAST_KO: feeds.append(("ko", q, gnews_url(q, "ko")))
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
            desc = clean_desc(e.get("summary", ""))
            text = title + " " + desc
            is_qatar = has(text, QATAR_KW)
            if not is_qatar and not has(text, MIDEAST_KW):
                continue
            dt = entry_time(e)
            if dt is None or dt < win_start_utc or dt > now_utc + timedelta(minutes=5):
                continue
            key = link.split("?")[0].lower()
            tkey = "".join(title.lower().split())[:60]
            if key in seen or tkey in seen:
                continue
            seen.add(key); seen.add(tkey)
            kor = bool(HANGUL_RE.search(title))
            items.append({"title": title, "link": link, "source": src, "dt": dt,
                          "qatar": is_qatar, "desc": desc, "korean": kor,
                          "region": source_region(src, kor)})
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items


# ───────────────────── LLM 키 라우팅 ─────────────────────
# 키는 GROQ_API_KEY / GEMINI_API_KEY 어느 슬롯에 넣어도, 접두어로 자동 판별해 알맞은 엔진에 사용.
#   GitHub Models 토큰: "github_pat_..." 또는 "ghp_..."
#   Groq 키: "gsk_..."  |  Gemini 키: "AQ..." 또는 "AIza..."
def _all_keys():
    return [k for k in (os.environ.get("GH_MODELS_TOKEN", "").strip(),
                        os.environ.get("GROQ_API_KEY", "").strip(),
                        os.environ.get("GEMINI_API_KEY", "").strip()) if k]

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


# ───────────────────── GitHub Models (1순위·무료·전세계) ─────────────────────
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
    # 1순위: GitHub Models(무료·GitHub 계정·리전제한 없음).
    for m in GH_MODELS:
        out = github_models_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via ghmodels:{m}")
            return out
    # 2순위: Groq(무료·전세계).
    for m in GROQ_MODELS:
        out = groq_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via groq:{m}")
            return out
    # 3순위: Gemini(무료 한도가 리전별로 잡히면 사용).
    for m in GEMINI_MODELS:
        out = gemini_call(m, prompt, json_mode)
        if out:
            print(f"[info] summary ok via gemini:{m}")
            return out
    return None


def gemini_issues(pool, win_label):
    if not pool:
        return None
    lines = []
    for i, x in enumerate(pool):
        reg = {"qatar": "[카타르현지]", "iran": "[이란매체]", "korea": "[국내]", "overseas": "[해외]"}[x["region"]]
        qt = "(카타르관련)" if x["qatar"] else ""
        d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
        desc = (x["desc"] or "")[:DESC_MAX]
        lines.append(f"{i}: {reg}{qt} ({x['source']}, {d}) {x['title']} :: {desc}")
    prompt = (
        "당신은 주카타르대사관 상황실 분석관입니다. 아래 [기사 목록]을 읽고 이 갱신 주기의 내용을 "
        "'사안(issue)'별로 3~6개로 묶으세요. 카테고리 예시: 전쟁·군사 / 외교·중재 / 에너지·유가 / "
        "물류·해상안전(홍해·수에즈·호르무즈) / 항공·교민안전 / 경제. 카타르 직접 관련 사안은 우선 포함.\n"
        "각 사안 필드: theme(사안명, 앞에 이모지 1개 권장), summary(한국어 2~4문장, 핵심), "
        "figures(핵심 수치 한 줄; 사상자/미사일/유가/호르무즈 비중/휴전기간 등, 없으면 \"\"), "
        "ids(그 사안 관련 기사 id 정수 배열, 중요 기사 위주 최대 8개).\n"
        "규칙: 제공된 기사에 없는 사실·수치는 절대 창작 금지. 한국어로. 반드시 아래 JSON만 출력:\n"
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
        "■ 핵심 요약: (3~6문장)\n■ 핵심 수치: (사상자·미사일·유가·호르무즈 비중 등 불릿; 없으면 '특이 수치 없음')\n"
        "■ 카타르 관련: (불릿 2~4개, 없으면 '해당 기간 카타르 직접 특이사항 없음')\n■ 중동정세 주요: (불릿 3~6개)\n"
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
        if ov: groups += '<div class="grp"><div class="gh">🌐 해외</div>' + "".join(link_row(a) for a in ov) + '</div>'
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


def render(items, win_label, issues, flat_text):
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    def is_pin(x): return x["qatar"] or x["region"] == "qatar"
    qatar = [x for x in items if is_pin(x)][:MAX_PER_SECTION]
    me_ov = [x for x in items if not is_pin(x) and x["region"] == "overseas"][:MAX_PER_SECTION]
    me_ir = [x for x in items if not is_pin(x) and x["region"] == "iran"][:MAX_PER_SECTION]
    me_kr = [x for x in items if not is_pin(x) and x["region"] == "korea"][:MAX_PER_SECTION]

    def block(rows, empty):
        return "\n".join(li(x, now_utc) for x in rows) or f'<li class="empty">{empty}</li>'

    if issues:
        summary_html = ('<div class="sumhead"><span class="bar"></span>🧭 이번 갱신 사안별 요약 '
                        '<span class="ai">AI 자동요약</span></div>' + render_issues(issues, items[:POOL_FOR_ISSUES], now_utc))
    elif flat_text:
        summary_html = ('<div class="card sum"><div class="sumhead"><span class="bar"></span>🧭 이번 갱신 핵심 요약 '
                        '<span class="ai">AI 자동요약</span></div>'
                        f'<div class="sumbody">{summary_to_html(flat_text)}</div></div>')
    else:
        diag = " · ".join(LLM_DIAG[-3:]) if LLM_DIAG else ""
        diag_html = f'<div class="pl" style="color:var(--muted);font-size:11px;margin-top:6px">진단: {esc(diag)}</div>' if diag else ""
        summary_html = ('<div class="card sum"><div class="sumhead"><span class="bar"></span>🧭 이번 갱신 핵심 요약</div>'
                        '<div class="sumbody"><div class="pl" style="color:var(--muted)">요약 일시 미생성 — '
                        '다음 갱신에 자동 재시도됩니다. 아래 기사 목록은 정상입니다.</div>'
                        f'{diag_html}</div></div>')

    quick = ""
    for g, links in QUICK_LINKS.items():
        chips = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)}</a>' for n, u in links)
        quick += f'<div class="qgroup"><div class="qh">{esc(g)}</div><div class="qchips">{chips}</div></div>'

    return TEMPLATE.format(
        title=esc(TITLE), subtitle=esc(SUBTITLE),
        updated=now_q.strftime("%Y-%m-%d %H:%M"), window=esc(win_label),
        n_q=len(qatar), n_me=len(me_ov) + len(me_ir) + len(me_kr), summary=summary_html,
        qatar=block(qatar, "이번 창(window)에 카타르 직접 관련 신규 기사 없음"),
        me_en=block(me_ov, "이번 창에 해외 신규 기사 없음"),
        me_ir=block(me_ir, "이번 창에 이란·역내 매체 신규 기사 없음"),
        me_ko=block(me_kr, "이번 창에 국내 신규 기사 없음"),
        quick=quick, year=now_q.year,
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
  .wrap{{max-width:1100px;margin:0 auto;padding:18px 14px 60px}}
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
  .row{{display:grid;grid-template-columns:1.05fr 1fr;gap:0}}
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
  ul{{list-style:none;margin:0;padding:0}}
  li{{padding:10px 0;border-bottom:1px solid var(--line)}} li:last-child{{border-bottom:none}}
  li a{{color:var(--txt);text-decoration:none;font-size:14px;font-weight:600}}
  li a:hover{{color:var(--accent);text-decoration:underline}}
  .qflag{{font-size:10.5px;font-weight:700;color:#111;background:var(--gold);padding:1px 6px;border-radius:6px;vertical-align:middle}}
  .dsc{{color:var(--muted);font-size:12.5px;margin-top:3px}}
  .meta{{color:var(--muted);font-size:11.5px;margin-top:3px;opacity:.85}}
  .empty{{color:var(--muted);font-size:13px}}
  .sechd{{font-size:13px;font-weight:800;color:var(--muted);margin:20px 0 8px;text-transform:uppercase;letter-spacing:.5px}}
  .qgroup{{margin:2px 0 12px}} .qh{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}}
  .qchips{{display:flex;flex-wrap:wrap;gap:7px}}
  .qchips a{{font-size:12.5px;color:var(--accent);text-decoration:none;border:1px solid var(--line);background:var(--panel2);border-radius:8px;padding:5px 10px}}
  .qchips a:hover{{text-decoration:underline}}
  footer{{margin-top:6px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:12px}}
  @media (max-width:520px){{h1{{font-size:16.5px}} .qchips a{{padding:6px 11px}}}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="titrow"><span class="dot"></span><h1>{title}</h1></div>
    <div class="sub">
      <span>{subtitle}</span>
      <span>최종 갱신: <b>{updated} (카타르시간)</b></span>
      <span>커버 기간: <b>{window}</b></span>
      <span>카타르 <b>{n_q}</b>건 · 중동정세 <b>{n_me}</b>건</span>
    </div>
  </header>

  {summary}

  <div class="sechd">— 전체 기사 목록 —</div>

  <div class="card pin">
    <h2><span class="bar"></span>🇶🇦 카타르 관련 (필수 포함)</h2>
    <ul>{qatar}</ul>
  </div>

  <div class="grid3">
    <div class="card"><h2><span class="bar"></span>🇮🇷 이란·역내 매체</h2><ul>{me_ir}</ul></div>
    <div class="card"><h2><span class="bar"></span>🌐 해외 언론</h2><ul>{me_en}</ul></div>
    <div class="card"><h2><span class="bar"></span>🇰🇷 국내(한국) 언론</h2><ul>{me_ko}</ul></div>
  </div>

  <div class="card">
    <h2><span class="bar"></span>관심 매체 · 정부 공지 바로가기</h2>
    {quick}
  </div>

  <footer>
    ※ 공관 모니터링용 · Google News RSS 및 주요 매체 피드 자동 집계 + (무료) Gemini 사안별 한국어 요약. <b>직전 갱신 → 이번 갱신</b> 창(window) 기사만 표시, 취합/비정식 소스는 제외, 카타르 직접 관련은 상단 고정.
    <br>GitHub Actions가 매일 카타르시간 오전 7:00·오후 3:30에 자동 갱신합니다. © {year}
  </footer>
</div>
</body>
</html>
"""


def main():
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    start_q, label = window_bounds(now_q)
    items = collect(start_q.astimezone(timezone.utc), now_utc)
    pool = items[:POOL_FOR_ISSUES]
    issues = gemini_issues(pool, label)
    flat = None if issues else gemini_flat(pool, label)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(render(items, label, issues, flat))
    mode = "issues" if issues else ("flat" if flat else "none")
    print(f"generated · window={label} · items={len(items)} · summary={mode}")


if __name__ == "__main__":
    main()
