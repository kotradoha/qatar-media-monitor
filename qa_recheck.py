#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""배포 2차 검증(QA) — 생성된 '카타르 정부 동향'을 독립 재점검해 이상물을 자동 제거.

generate.py 실행 '직후'(같은 워크플로 단계 사이)에 실행한다. 생성 파이프라인 내부 필터를
통과했더라도, 결과물(index/en/ar + 이번 회차 아카이브)을 다시 한 번 '독립적으로' 검사한다.

검사 2겹:
  (1) 결정론 규칙(generate._GOV_SANE_* 재사용) — 카타르 정부 주체 없음 / 추측·전망뿐 배제.
  (2) 독립 AI 비평(generate.gemini_generate) — 기구 수장 성명·과거 재탕·에너지 시황·역할 서술 등
      판단이 필요한 이상물을 잡음.

이상 항목은 정부 동향 섹션에서만 제거하며(남은 게 없으면 '특이사항 없음'으로 정리),
무엇을 왜 제거했는지 로그와 GITHUB_STEP_SUMMARY, qa_last.json에 남긴다(알림).

설계 원칙: fail-open — 어떤 예외가 나도 발행은 그대로 두고 조용히 넘어간다(QA는 '추가 안전망'일 뿐).
과도 삭제 방지 — 애매하면 남긴다.
"""
import os
import re
import sys
import json
import glob
import html as _html

try:
    import generate as G   # generate.py는 main 가드가 있어 import는 안전(부작용 없음)
except Exception as ex:    # noqa
    print(f"[qa] generate import 실패 — QA 스킵(발행 그대로): {ex}")
    sys.exit(0)

LIVE_FILES = ["index.html", "en.html", "ar.html"]


def _lang_of(path):
    b = os.path.basename(path)
    if b == "en.html" or b.endswith("-en.html"):
        return "en"
    if b == "ar.html" or b.endswith("-ar.html"):
        return "ar"
    return "ko"


def _gov_none(lang):
    try:
        return G.LANG.get(lang, G.LANG["ko"])["gov_none"]
    except Exception:
        return "이번 모니터링 기간 중 특이사항 없음"


def _newest_archive_triplet():
    """이번 회차가 방금 쓴 아카이브 3종(d-YYYYMMDD-HHMM-{ko,en,ar}.html)."""
    kos = glob.glob("archive/d-*-ko.html")
    if not kos:
        return []

    def ts(p):
        m = re.search(r"d-(\d{8})-(\d{4})-ko\.html$", p)
        return (m.group(1) + m.group(2)) if m else "0"

    newest = max(kos, key=ts)
    base = newest[: -len("ko.html")]
    return [base + lang + ".html" for lang in ("ko", "en", "ar") if os.path.exists(base + lang + ".html")]


def _bullet_urls(li_html):
    """정부 동향 <li> 하나의 링크 URL 집합(쿼리 제거) — 언어판 간 동일하므로 식별키로 사용."""
    return {u.split("?")[0] for u in re.findall(r'href="([^"]+)"', li_html)}


def _bullet_text(li_html):
    no_links = re.sub(r'<a class="govlink".*?</a>', "", li_html, flags=re.S)
    return re.sub(r"<[^>]+>", "", _html.unescape(no_links)).strip()


def _extract_gov_bullets(htmltext):
    m = re.search(r'<ul class="govul">(.*?)</ul>', htmltext, re.S)
    if not m:
        return []
    out = []
    for li in re.findall(r"<li>.*?</li>", m.group(1), re.S):
        out.append({"text": _bullet_text(li), "urls": _bullet_urls(li)})
    return out


def _deterministic_reason(text):
    """generate.py의 위생 토큰 재사용 — 제거 사유 문자열 또는 None."""
    try:
        actors, actions, specul = G._GOV_SANE_ACTOR, G._GOV_SANE_ACTION, G._GOV_SANE_SPECUL
    except Exception:
        return None
    low = text.lower()
    if not any(k in low for k in actors):
        return "카타르 정부 주체 없음"
    if any(p in text for p in specul) and not any(v in low for v in actions):
        return "구체적 행위 없이 추측·전망뿐"
    return None


def _ai_flags(bullets):
    """독립 AI 비평 — 제거할 항목 [{id, reason}] 리스트. 호출 실패 시 None(결정론만 적용)."""
    if not bullets:
        return []
    lines = [f"{i}: {b['text']}" for i, b in enumerate(bullets)]
    prompt = (
        "당신은 공개 뉴스 사이트의 '🏛️ 정세 관련 카타르 정부 동향' 섹션 전담 QA 심사관입니다. "
        "이 섹션은 오직 '카타르 정부·지도부(에미르·총리·부총리·외교/내무/국방부·정부커뮤니케이션실(GCO)·"
        "카타르에너지의 공식 조치·QNA)'가 중동 정세(전쟁·역내 안보)에 대해 '이번 모니터링 기간에 새로 취한 "
        "구체적 행위(성명·규탄·촉구·중재·통화·회담·발표·서명·조치)'만 담아야 합니다.\n"
        "아래 [항목] 각각을 검사해, 다음 중 하나라도 해당하면 '제거' 대상으로 고르세요:\n"
        "1) 카타르 정부가 주어(주체)가 아님 — 출처 미상 '이 사태는…', 타국·타 기구만의 동향, 카타르는 배경으로만 언급.\n"
        "2) 구체적 행위가 아니라 추측·전망·해설 — '~할 수 있음/가능성/전망/여파/함의' 식으로 끝나는 문장.\n"
        "3) 수개월 전 과거 사건의 재보도·회고 — 이번 기간에 새로 일어난 동향이 아님.\n"
        "4) 국제·역내 기구 수장(아랍연맹/GCC/OIC/유엔 사무총장·대변인 등) 개인 성명 — 카타르는 단지 회원국.\n"
        "5) 에너지 시황·기업 경영성 코멘트(생산량·수출·가격·투자 전망 등) — 정세 관련 공식 조치가 아님.\n"
        "6) 카타르의 역할·입지에 대한 일반적 서술('중재국 역할을 지속함' 등) — 구체적 행위가 없음.\n"
        "정상(카타르 정부·지도부의 '구체적인 새 정세 행위')이면 남기세요. "
        "판단이 애매하면 남기세요(과도한 삭제 금지 — 확실한 이상만 제거).\n"
        '출력은 오직 JSON: {"remove":[{"id":정수,"reason":"짧은 한국어 사유"}]} (제거할 것이 없으면 {"remove":[]}).\n\n'
        "[항목]\n" + "\n".join(lines)
    )
    try:
        out = G.gemini_generate(prompt, json_mode=True)
    except Exception as ex:
        print(f"[qa] AI 비평 호출 예외 — 결정론 규칙만 적용: {ex}")
        return None
    if not out:
        return None
    try:
        data = json.loads(G._extract_json(out))
        rem = data.get("remove")
        return rem if isinstance(rem, list) else []
    except Exception as ex:
        print(f"[qa] AI 비평 파싱 실패 — 결정론 규칙만 적용: {ex}")
        return None


def _remove_from_file(path, remove_url_sets):
    """path의 정부 동향 섹션에서 remove_url_sets와 링크가 겹치는 <li>를 제거. 남은 게 없으면 govnone."""
    if not os.path.exists(path):
        return
    s = open(path, encoding="utf-8").read()
    m = re.search(r'(<ul class="govul">)(.*?)(</ul>)', s, re.S)
    if not m:
        return
    head, body, tail = m.groups()
    keep = []
    for li in re.findall(r"<li>.*?</li>", body, re.S):
        urls = _bullet_urls(li)
        if urls and any(urls & rs for rs in remove_url_sets):
            continue  # 제거 대상
        keep.append(li)
    if keep:
        new = head + "".join(keep) + tail
    else:
        new = f'<div class="govnone">{_html.escape(_gov_none(_lang_of(path)))}</div>'
    open(path, "w", encoding="utf-8").write(s[: m.start()] + new + s[m.end():])


def _summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        try:
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("\n### 🏛️ 정부 동향 배포 2차 검증(QA)\n" + text + "\n")
        except Exception:
            pass


def main():
    try:
        live = open("index.html", encoding="utf-8").read()
    except FileNotFoundError:
        print("[qa] index.html 없음 — 스킵")
        return
    bullets = _extract_gov_bullets(live)
    if not bullets:
        print("[qa] 정부 동향 항목 없음(특이사항 없음) — 점검 불필요")
        return

    flagged = {}  # idx -> reason
    for i, b in enumerate(bullets):
        r = _deterministic_reason(b["text"])
        if r:
            flagged[i] = f"[규칙] {r}"

    ai = _ai_flags(bullets)
    if ai is None:
        print("[qa] AI 비평 불가 — 결정론 규칙만 적용")
    else:
        for item in ai:
            if not isinstance(item, dict):
                continue
            idx = item.get("id")
            reason = (item.get("reason") or "AI 비평").strip()
            if isinstance(idx, int) and 0 <= idx < len(bullets):
                flagged.setdefault(idx, f"[AI] {reason}")

    if not flagged:
        print(f"[qa] 정부 동향 {len(bullets)}건 모두 정상 — 이상 없음")
        _summary(f"✅ 정부 동향 {len(bullets)}건 정상 (제거 없음)")
        return

    remove_url_sets = [bullets[i]["urls"] for i in flagged if bullets[i]["urls"]]
    report = [f"- {bullets[i]['text'][:80]}  ·  사유: {flagged[i]}" for i in sorted(flagged)]

    if not remove_url_sets:
        # 링크 없는 불릿이라 URL로 특정 불가 — 안전상 건드리지 않고 알림만.
        print("[qa] 이상 의심되나 링크가 없어 자동 제거 보류(수동 확인 권장):\n" + "\n".join(report))
        _summary("⚠️ 이상 의심(링크 없어 자동 제거 보류):\n" + "\n".join(report))
        return

    targets = LIVE_FILES + _newest_archive_triplet()
    for f in targets:
        _remove_from_file(f, remove_url_sets)

    msg = f"🧹 정부 동향 QA — {len(flagged)}/{len(bullets)}건 자동 제거:\n" + "\n".join(report)
    print("[qa] " + msg)
    _summary(msg)
    try:
        json.dump(
            {"removed": report, "run_id": os.environ.get("GITHUB_RUN_ID", "")},
            open("qa_last.json", "w", encoding="utf-8"),
            ensure_ascii=False,
            indent=1,
        )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:  # fail-open: QA 실패가 발행을 막지 않도록
        print(f"[qa] 재점검 중 예외 — 발행은 그대로 유지: {ex}")
