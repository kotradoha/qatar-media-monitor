# -*- coding: utf-8 -*-
"""과거 아카이브의 정부 동향 en/ar '한국어 잔존'(번역 fail-open)분을 소급 번역.

핵심: 손번역이 아니라 사이트가 쓰는 그 함수 generate.translate_gov(=Claude/자동 파이프라인)를
그대로 호출해 채운다 → 정규 회차와 품질·방식 동일, 사람 개입에 의한 오류 위험 없음.

- 대상: archive/d-*-{en,ar}.html, archive/w-*-{en,ar}.html 중 govul에 한글이 남은 파일.
- 텍스트 원본은 같은 슬롯의 -ko.html 불릿(순서 1:1). 링크(↗ chip)는 원본 그대로 보존.
- 번역이 또 실패(한글 반환)하면 그 파일은 건드리지 않고 [unchanged]로 보고(안전).
- 기본은 DRY-RUN(무엇을 바꿀지 목록만). 실제 반영은  --apply.

실행(키가 있는 환경에서):
    # 로컬: 사이트 secrets와 같은 키 하나만 셸에 넣고
    GEMINI_API_KEY=...  python backfill_gov_i18n.py --apply
    # 또는 GitHub Actions에서 이 스크립트를 한 번 돌림(권장 — 키가 이미 secrets에 있음)
"""
import re, sys, glob, os
import generate as g

APPLY = "--apply" in sys.argv
HANGUL = re.compile(r"[가-힣]")


def gov_block(path):
    html = open(path, encoding="utf-8").read()
    m = re.search(r'<ul class="govul">.*?</ul>', html, re.S)
    if not m:
        return html, None, None
    lis = re.findall(r"<li>.*?</li>", m.group(0), re.S)
    return html, m.group(0), lis


def bullet_text(li):
    head = re.split(r"<a\b", li, maxsplit=1)[0]  # 첫 링크 chip 이전이 본문
    t = re.sub(r"^<li>", "", head)
    return re.sub(r"<[^>]+>", "", t).strip()


def set_bullet_text(li, new_plain):
    esc = g.esc(new_plain)
    if "<a" in li:
        return re.sub(r"^<li>.*?(?=<a\b)", "<li>" + esc + " ", li, flags=re.S)
    return "<li>" + esc + "</li>"


changed = skipped = 0
for kf in sorted(glob.glob("archive/d-*-ko.html")) + sorted(glob.glob("archive/w-*-ko.html")):
    _, _, kolis = gov_block(kf)
    if not kolis:
        continue
    ko_texts = [bullet_text(li) for li in kolis]
    for lang in ("en", "ar"):
        ef = kf.replace("-ko.html", f"-{lang}.html")
        if not os.path.exists(ef):
            continue
        ehtml, eblock, elis = gov_block(ef)
        if not elis:
            continue
        if not any(HANGUL.search(bullet_text(li)) for li in elis):
            continue                              # 이미 번역됨 → 스킵
        if len(elis) != len(ko_texts):
            print(f"[SKIP 불릿수 불일치] {ef}: {lang} {len(elis)} vs ko {len(ko_texts)}")
            continue
        if not APPLY:
            print(f"[would translate] {ef}  ({len(elis)} bullets)")
            skipped += 1
            continue
        gov = [{"t": t, "links": []} for t in ko_texts]
        tr = g.translate_gov(gov, lang)
        if len(tr) != len(elis) or all(HANGUL.search(x.get("t", "")) for x in tr):
            print(f"[unchanged] {ef} — 번역 실패(한글 반환), 원본 유지")
            continue
        newlis = []
        for li, x in zip(elis, tr):
            nt = x.get("t", "")
            newlis.append(li if HANGUL.search(nt) else set_bullet_text(li, nt))
        newblock = '<ul class="govul">' + "".join(newlis) + "</ul>"
        open(ef, "w", encoding="utf-8").write(ehtml.replace(eblock, newblock))
        print(f"[translated] {ef}")
        changed += 1

print(f"\n{'APPLIED' if APPLY else 'DRY-RUN'}: 번역 {changed}건, 대기/스킵 {skipped}건")
