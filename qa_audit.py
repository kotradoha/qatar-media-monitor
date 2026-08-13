#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""과거 회차 일괄 감사(backtest) — 아카이브 전 회차의 정부 동향/주요 이슈를 독립 규칙으로 재점검.
AI 비평은 로컬에서 못 돌리므로 '결정론 규칙 + 알려진 패턴 휴리스틱'으로 근사한다.
(실제 배포 QA는 여기에 AI 비평이 더해져 더 많이 잡는다 — 이 수치는 '하한'으로 보면 됨.)
결과만 출력하고 파일은 수정하지 않는다."""
import re
import glob
import html as _html
import difflib
from collections import Counter

import generate as G

ACTOR = G._GOV_SANE_ACTOR
ACTION = G._GOV_SANE_ACTION
SPECUL = G._GOV_SANE_SPECUL

ORG_HEAD = re.compile(r"(아랍연맹|جامعة الدول|걸프협력회의|gcc|oic|이슬람협력기구|유엔|un\b).{0,20}(사무총장|secretary|أمين)", re.I)
ENERGY_MKT = re.compile(r"(생산능력|생산량|수출량|증산|감산|가격 전망|투자 계획|시황)", re.I)


def _txt(li):
    no = re.sub(r'<a class="govlink".*?</a>', "", li, flags=re.S)
    return re.sub(r"<[^>]+>", "", _html.unescape(no)).strip()


def gov_flags(h):
    m = re.search(r'<ul class="govul">(.*?)</ul>', h, re.S)
    if not m:
        return []
    flags = []
    for li in re.findall(r"<li>.*?</li>", m.group(1), re.S):
        t = _txt(li)
        low = t.lower()
        has_actor = any(k in low for k in ACTOR)
        has_action = any(v in low for v in ACTION)
        if not has_actor:
            flags.append(("주체없음", t))
        elif any(p in t for p in SPECUL) and not has_action:
            flags.append(("추측·전망뿐", t))
        elif ORG_HEAD.search(t) and "카타르" not in t[:12]:
            flags.append(("기구수장 성명 의심", t))
        elif ENERGY_MKT.search(t) and not has_action:
            flags.append(("에너지 시황 코멘트 의심", t))
    return flags


def issue_blocks(h):
    """(theme, 링크url집합) 리스트."""
    out = []
    parts = re.split(r'<div class="issue">', h)[1:]
    for p in parts:
        p = p.split('<div class="issue">')[0]
        hm = re.search(r"<h2>(.*?)</h2>", p, re.S)
        theme = re.sub(r"<[^>]+>", "", _html.unescape(hm.group(1))).strip() if hm else ""
        # 이슈 링크(우측 관련보도) — 본문 첫 </div></div></div> 전까지
        body = p.split("</div></div></div>")[0]
        urls = {u.split("?")[0] for u in re.findall(r'href="(https?://[^"]+)"', body)}
        out.append((theme, urls))
    return out


def issue_flags(h):
    blocks = issue_blocks(h)
    flags = []
    # 링크 없음
    for i, (th, us) in enumerate(blocks):
        if not us:
            flags.append(("링크 없음", th))
    # 중복(링크 교집합 ≥ 작은쪽 60% 또는 테마 유사도 ≥0.8)
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            ti, ui = blocks[i]
            tj, uj = blocks[j]
            ov = (len(ui & uj) / min(len(ui), len(uj))) if (ui and uj) else 0
            sim = difflib.SequenceMatcher(None, re.sub(r"\W", "", ti), re.sub(r"\W", "", tj)).ratio()
            # 이슈는 서로 다른 주제가 같은 원문을 공유하는 게 정상 → 링크겹침만으론 중복 아님.
            # 진짜 중복은 '주제 유사도'가 핵심. 제목 매우 유사하거나, (링크 다수겹침 + 제목도 어느정도 유사)일 때만.
            if sim >= 0.7 or (ov >= 0.8 and sim >= 0.5):
                flags.append(("중복 의심", f"#{i+1}«{ti[:24]}» ↔ #{j+1}«{tj[:24]}» (링크겹침 {ov:.0%}, 제목유사 {sim:.0%})"))
    return flags


def main():
    files = sorted(glob.glob("archive/d-*-ko.html"))
    gov_total = Counter()
    iss_total = Counter()
    editions_with_gov = 0
    editions_with_iss = 0
    detail = []
    for f in files:
        ed = re.search(r"d-(\d{8})-(\d{4})", f)
        label = f"{ed.group(1)[4:6]}/{ed.group(1)[6:]} {ed.group(2)[:2]}:{ed.group(2)[2:]}"
        h = open(f, encoding="utf-8").read()
        gf = gov_flags(h)
        iff = issue_flags(h)
        if gf:
            editions_with_gov += 1
        if iff:
            editions_with_iss += 1
        for k, _ in gf:
            gov_total[k] += 1
        for k, _ in iff:
            iss_total[k] += 1
        if gf or iff:
            detail.append((label, gf, iff))

    print("=" * 64)
    print(f"감사 대상: {len(files)}개 회차 (아카이브 ko)")
    print("=" * 64)
    for label, gf, iff in detail:
        print(f"\n▶ {label}")
        for k, t in gf:
            print(f"   [정부/{k}] {t[:78]}")
        for k, t in iff:
            print(f"   [이슈/{k}] {t[:88]}")

    print("\n" + "=" * 64)
    print("■ 정부 동향 이상 (회차 %d개에서 발견):" % editions_with_gov)
    for k, v in gov_total.most_common():
        print(f"   - {k}: {v}건")
    print("■ 주요 이슈 이상 (회차 %d개에서 발견):" % editions_with_iss)
    for k, v in iss_total.most_common():
        print(f"   - {k}: {v}건")
    print(f"\n총 이상: 정부 {sum(gov_total.values())}건 · 이슈 {sum(iss_total.values())}건 "
          f"(전 {len(files)}회차 중 문제회차 {len(detail)}개)")
    print("※ 로컬 감사는 결정론+휴리스틱만. 실제 배포 QA는 AI 비평이 더해져 더 잡음(이 수치는 하한).")


if __name__ == "__main__":
    main()
