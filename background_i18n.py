# -*- coding: utf-8 -*-
"""배경 페이지(background-ko.html) 라인 단위 자동 번역기.

- BG_BODY는 블록 요소가 한 줄씩 배치돼 있어, '한글이 포함된 라인'만 골라 번역한다.
- 번역은 국문 라인 해시를 키로 파일 캐시(background_i18n_cache.json)에 저장 → 국문이 바뀐
  라인만 다음 빌드에서 재번역(비용·시간 관리, 국문과 자동 동기화).
- HTML 안전장치: 번역 결과의 태그 목록이 원문과 정확히 같을 때만 채택하고, 아니면 국문 라인을
  그대로 둔다(캐시하지 않음 → 다음 빌드 재시도). LLM 미가동·오류 시 전체가 국문으로 폴백.
- gen_fn(prompt, json_mode) 은 generate.py의 gemini_generate 를 주입받는다.
"""
import json
import os
import re
import hashlib

CACHE_PATH = "background_i18n_cache.json"
_HANGUL = re.compile(r"[가-힣]")
_TAG = re.compile(r"<[^>]+>")
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(cache, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as ex:
        print(f"[warn] bg i18n cache save failed: {ex}")


def _extract_json(s):
    """코드펜스 등 잡음 제거 후 첫 '{'~마지막 '}' 구간."""
    s = _FENCE.sub("", (s or "").strip())
    i, j = s.find("{"), s.rfind("}")
    return s[i:j + 1] if 0 <= i < j else s


def _key(line, lang):
    return hashlib.sha1(line.encode("utf-8")).hexdigest()[:16] + ":" + lang


def _tags(s):
    return _TAG.findall(s or "")


_TARGET = {"en": "English", "ar": "Arabic (Modern Standard Arabic)"}


def make_translator(gen_fn, cache_path=CACHE_PATH, batch=24):
    """gen_fn(prompt, json_mode)->str 를 받아 translate(lines, lang)->list(길이 동일) 반환."""
    cache = _load(cache_path)

    def translate(lines, lang):
        lines = list(lines)
        target = _TARGET.get(lang)
        if not target:
            return lines
        out = list(lines)
        todo = []  # (idx, line) — 번역 필요(한글 포함 + 캐시 미스)
        for i, ln in enumerate(lines):
            if not _HANGUL.search(ln):
                continue
            c = cache.get(_key(ln, lang))
            if c is not None:
                out[i] = c
            else:
                todo.append((i, ln))
        dirty = False
        for s in range(0, len(todo), batch):
            chunk = todo[s:s + batch]
            texts = [ln for _i, ln in chunk]
            prompt = (
                f"Translate each HTML fragment in this JSON array into {target}. "
                "STRICT RULES: (1) Keep ALL HTML tags, attributes, class names, id, href/src and any __TOKEN__ "
                "placeholders EXACTLY as-is and in the same order. (2) Translate ONLY the human-visible Korean text. "
                "(3) Keep numbers, dates, %, currency symbols and Latin/Arabic proper nouns unchanged. "
                "(4) Do NOT add, remove, merge or reorder tags. "
                "Return ONLY a JSON object {\"t\":[...]} with exactly the same number and order of items.\n\n"
                + json.dumps({"t": texts}, ensure_ascii=False))
            res = None
            try:
                raw = gen_fn(prompt, True)
                if raw:
                    tr = json.loads(_extract_json(raw)).get("t")
                    if isinstance(tr, list) and len(tr) == len(texts):
                        res = tr
            except Exception as ex:
                print(f"[warn] bg i18n batch failed({lang}): {ex}")
            for j, (i, ln) in enumerate(chunk):
                t = res[j] if res and isinstance(res[j], str) and res[j].strip() else None
                if t and _tags(t) == _tags(ln):     # 태그 구조 동일할 때만 채택(HTML 안전)
                    out[i] = t
                    cache[_key(ln, lang)] = t
                    dirty = True
                else:
                    out[i] = ln                     # 국문 폴백(캐시 안 함 → 다음 빌드 재시도)
        if dirty:
            _save(cache, cache_path)
        return out

    return translate
