#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카타르·중동정세 언론 모니터링 (대사관/공관용, 무료·완전자동)
- 갱신 주기(직전 갱신 → 이번 갱신) '창(window)' 안에 보도된 기사만 수집
- 카타르 관련은 필수 별도 섹션 + 중동정세(해외/국내), 각 기사에 매체·링크 연결
- (무료) Google Gemini API 키가 있으면 매 갱신 시 '한국어 핵심 요약(핵심 수치 포함)'을 상단 자동 생성
- GitHub Actions가 하루 2회(카타르시간 07:00 / 15:30) 실행 → 커밋/게시 → 공개 URL 자동 갱신

환경변수 GEMINI_API_KEY 가 있으면 요약 생성, 없으면 요약 없이 헤드라인만(정상 동작).
"""

import os
import re
import json
import html
import calendar
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    import feedparser
except ImportError:
    raise SystemExit("feedparser가 필요합니다: pip install feedparser")

# ───────────────────────── CONFIG ─────────────────────────
TITLE = "🇶🇦 카타르·중동정세 언론 모니터링"
SUBTITLE = "갱신 주기 내 주요 뉴스 · 카타르 관련 필수 포함 · 공관 모니터링용"

Q_QATAR_EN = ["Qatar Iran", "Qatar Doha", "Al Udeid", "Ras Laffan Qatar", "Qatar security"]
Q_QATAR_KO = ["카타르 이란", "카타르 도하", "알우데이드", "카타르 미사일", "카타르 정세"]
Q_MIDEAST_EN = ["Middle East Iran Israel", "US Iran strikes", "Strait of Hormuz", "Gulf tensions", "Iran Israel war"]
Q_MIDEAST_KO = ["중동 정세", "이란 이스라엘", "호르무즈", "걸프 긴장", "이란 미국"]

QATAR_KW = ["qatar", "doha", "al udeid", "al-udeid", "udeid", "ras laffan", "hamad",
            "카타르", "도하", "알우데이드", "라스라판", "하마드"]
MIDEAST_KW = ["iran", "iranian", "israel", "israeli", "gulf", "hormuz", "houthi", "yemen",
              "saudi", "bahrain", "kuwait", "oman", "uae", "emirates", "tehran", "gaza",
              "lebanon", "hezbollah", "idf", "middle east", "egypt",
              "이란", "이스라엘", "걸프", "호르무즈", "후티", "예멘", "사우디", "바레인",
              "쿠웨이트", "오만", "중동", "테헤란", "가자", "헤즈볼라", "이집트"]

# 직접 RSS (본문 발췌 description 제공 → 요약 품질↑). Google News가 막힐 때 보강.
DIRECT_FEEDS = [
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC Middle East", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
]

QUICK_LINKS = {
    "카타르 현지 매체": [("Gulf Times", "https://www.gulf-times.com/"),
        ("The Peninsula", "https://thepeninsulaqatar.com/"),
        ("Qatar Tribune", "https://www.qatar-tribune.com/")],
    "미국·해외 주요 매체": [("Al Jazeera", "https://www.aljazeera.com/news/"),
        ("CNN", "https://www.cnn.com/world"),
        ("Reuters — Middle East", "https://www.reuters.com/world/middle-east/"),
        ("BBC — Middle East", "https://www.bbc.com/news/world/middle_east"),
        ("AP — Middle East", "https://apnews.com/hub/middle-east"),
        ("The New York Times — ME", "https://www.nytimes.com/section/world/middleeast")],
    "이란·역내 매체": [("Tehran Times", "https://www.tehrantimes.com/"),
        ("Press TV", "https://www.presstv.ir/"),
        ("IRNA (English)", "https://en.irna.ir/"),
        ("Iran International", "https://www.iranintl.com/en")],
    "국내(한국) 매체": [("연합뉴스 국제", "https://www.yna.co.kr/international/all"),
        ("YTN", "https://www.ytn.co.kr/"), ("한국경제", "https://www.hankyung.com/"),
        ("문화일보", "https://www.munhwa.com/"), ("파이낸셜뉴스", "https://www.fnnews.com/"),
        ("조선일보", "https://www.chosun.com/"), ("중앙일보", "https://www.joongang.co.kr/")],
    "정부·공식 공지": [("카타르 외무부(MOFA) 성명", "https://mofa.gov.qa/en/latest-articles/statements"),
        ("한국 외교부 해외안전여행(0404)", "https://www.0404.go.kr/"),
        ("외교부 이란 여행경보", "https://0404.go.kr/ntnSafetyInfo/176/detail")],
}

MAX_PER_SECTION = 50
BOUNDARY_AM = (7, 0)
BOUNDARY_PM = (15, 30)
TZ = timezone(timedelta(hours=3))          # Asia/Qatar (UTC+3)
GEMINI_MODEL = "gemini-2.0-flash"          # 무료 티어 모델
# ──────────────────────────────────────────────────────────

feedparser.USER_AGENT = "Mozilla/5.0 (compatible; MideastMediaMonitor/1.0)"
TAG_RE = re.compile(r"<[^>]+>")


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
            items.append({"title": title, "link": link, "source": source_of(e, label),
                          "dt": dt, "lang": lang, "qatar": is_qatar, "desc": desc})
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items


# ───────────────────── Gemini 무료 요약 ─────────────────────
def gemini_summary(items, win_label):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or not items:
        return None
    lines = []
    for x in items[:45]:
        tag = "[카타르] " if x["qatar"] else ""
        d = x["dt"].astimezone(TZ).strftime("%m/%d %H:%M")
        lines.append(f"- {tag}({x['source']}, {d}) {x['title']} :: {x['desc']}")
    articles = "\n".join(lines)
    prompt = (
        "당신은 주카타르대사관 상황실의 뉴스 요약 담당입니다. 아래는 커버기간 "
        f"'{win_label}' 동안 수집된 카타르·중동정세 기사 목록(제목/매체/발췌)입니다.\n"
        "이를 근거로 '한국어'로 간결하지만 밀도 높은 핵심 요약을 작성하세요. '최대한 요약'은 분량 축소가 "
        "아니라 중요한 내용과 핵심 수치를 빠짐없이 담는다는 뜻입니다. 형식은 아래를 정확히 따르세요.\n"
        "■ 핵심 요약: (3~6개 문장. 전반 정세와 함의)\n"
        "■ 핵심 수치: (기사에 나온 사상자 수, 미사일 발사/요격 수, 유가, 호르무즈 통과 비중, 연속 공습일수 등 "
        "구체 수치를 불릿으로. 없으면 '이번 기간 특이 수치 없음')\n"
        "■ 카타르 관련: (있으면 불릿 2~4개, 없으면 '해당 기간 카타르 직접 특이사항 없음')\n"
        "■ 중동정세 주요: (불릿 3~6개. 미국·이란·이스라엘·걸프 등)\n"
        "규칙: 제목·발췌에 없는 사실·수치는 절대 추정/창작하지 말 것. 지명·수치·날짜는 있는 그대로. "
        "각 불릿 끝에 근거 매체명을 (매체명) 형태로 표기. 불릿은 '- '로 시작. 마크다운 헤더(#) 금지.\n\n"
        f"[기사 목록]\n{articles}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1500},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as ex:
        print(f"[warn] gemini summary failed: {ex}")
        return None


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


def render(items, win_label, summary_text):
    now_utc = datetime.now(timezone.utc)
    now_q = now_utc.astimezone(TZ)
    qatar = [x for x in items if x["qatar"]][:MAX_PER_SECTION]
    me_en = [x for x in items if not x["qatar"] and x["lang"] == "en"][:MAX_PER_SECTION]
    me_ko = [x for x in items if not x["qatar"] and x["lang"] == "ko"][:MAX_PER_SECTION]

    def block(rows, empty):
        return "\n".join(li(x, now_utc) for x in rows) or f'<li class="empty">{empty}</li>'

    if summary_text:
        summary_html = ('<div class="card sum"><h2><span class="bar"></span>🧭 이번 갱신 핵심 요약 '
                        '<span class="ai">AI 자동요약</span></h2>'
                        f'<div class="sumbody">{summary_to_html(summary_text)}</div></div>')
    else:
        summary_html = ('<div class="card sum"><h2><span class="bar"></span>🧭 이번 갱신 핵심 요약</h2>'
                        '<div class="sumbody"><div class="pl" style="color:var(--muted)">요약 미생성 — '
                        'GEMINI_API_KEY 시크릿을 등록하면 매 갱신 시 한국어 요약(핵심 수치 포함)이 표시됩니다(무료).</div></div></div>')

    quick = ""
    for g, links in QUICK_LINKS.items():
        chips = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)}</a>' for n, u in links)
        quick += f'<div class="qgroup"><div class="qh">{esc(g)}</div><div class="qchips">{chips}</div></div>'

    return TEMPLATE.format(
        title=esc(TITLE), subtitle=esc(SUBTITLE),
        updated=now_q.strftime("%Y-%m-%d %H:%M"), window=esc(win_label),
        n_q=len(qatar), n_me=len(me_en) + len(me_ko), summary=summary_html,
        qatar=block(qatar, "이번 창(window)에 카타르 직접 관련 신규 기사 없음"),
        me_en=block(me_en, "이번 창에 해외 신규 기사 없음"),
        me_ko=block(me_ko, "이번 창에 국내 신규 기사 없음"),
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
  .wrap{{max-width:1060px;margin:0 auto;padding:18px 14px 60px}}
  header{{position:sticky;top:0;background:linear-gradient(180deg,var(--bg) 72%,transparent);
    padding:12px 0;border-bottom:1px solid var(--line);margin-bottom:16px;z-index:5}}
  .titrow{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}
  .dot{{width:10px;height:10px;border-radius:50%;background:var(--green);animation:p 2s infinite}}
  @keyframes p{{0%{{box-shadow:0 0 0 0 rgba(47,191,113,.5)}}70%{{box-shadow:0 0 0 8px rgba(47,191,113,0)}}100%{{box-shadow:0 0 0 0 rgba(47,191,113,0)}}}}
  h1{{font-size:19px;margin:0}}
  .sub{{color:var(--muted);font-size:12.5px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
  .sub b{{color:var(--txt)}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 15px;margin-bottom:14px}}
  .card h2{{font-size:14px;margin:0 0 10px;display:flex;align-items:center;gap:8px}}
  .card h2 .bar{{width:3px;height:15px;background:var(--accent);border-radius:2px}}
  .card.pin h2 .bar{{background:var(--gold)}}
  .card.sum{{background:linear-gradient(180deg,rgba(77,163,255,.08),transparent),var(--panel)}}
  .ai{{font-size:10.5px;font-weight:700;color:#111;background:var(--accent);padding:1px 7px;border-radius:6px}}
  .sumbody .sh{{font-weight:800;margin:11px 0 4px;font-size:13px;color:var(--accent)}}
  .sumbody .bl{{position:relative;padding-left:14px;margin:4px 0;font-size:13.5px}}
  .sumbody .bl:before{{content:"•";position:absolute;left:2px;color:var(--accent)}}
  .sumbody .pl{{font-size:13.5px;margin:3px 0}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  @media (max-width:720px){{.grid{{grid-template-columns:1fr}}}}
  ul{{list-style:none;margin:0;padding:0}}
  li{{padding:10px 0;border-bottom:1px solid var(--line)}} li:last-child{{border-bottom:none}}
  li a{{color:var(--txt);text-decoration:none;font-size:14px;font-weight:600}}
  li a:hover{{color:var(--accent);text-decoration:underline}}
  .qflag{{font-size:10.5px;font-weight:700;color:#111;background:var(--gold);padding:1px 6px;border-radius:6px;vertical-align:middle}}
  .dsc{{color:var(--muted);font-size:12.5px;margin-top:3px}}
  .meta{{color:var(--muted);font-size:11.5px;margin-top:3px;opacity:.85}}
  .empty{{color:var(--muted);font-size:13px}}
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

  <div class="card pin">
    <h2><span class="bar"></span>🇶🇦 카타르 관련 (필수 포함)</h2>
    <ul>{qatar}</ul>
  </div>

  <div class="grid">
    <div class="card"><h2><span class="bar"></span>중동정세 — 해외 언론</h2><ul>{me_en}</ul></div>
    <div class="card"><h2><span class="bar"></span>중동정세 — 국내(한국) 언론</h2><ul>{me_ko}</ul></div>
  </div>

  <div class="card">
    <h2><span class="bar"></span>관심 매체 · 정부 공지 바로가기</h2>
    {quick}
  </div>

  <footer>
    ※ 공관 모니터링용 · Google News RSS 및 주요 매체 피드 자동 집계 + (무료) Gemini 한국어 요약(핵심 수치 포함). <b>직전 갱신 → 이번 갱신</b> 창(window) 기사만 표시, 카타르 직접 관련은 상단 고정.
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
    summary = gemini_summary(items, label)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(render(items, label, summary))
    print(f"generated · window={label} · items={len(items)} · summary={'yes' if summary else 'no'}")


if __name__ == "__main__":
    main()
