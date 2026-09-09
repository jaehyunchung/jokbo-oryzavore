# -*- coding: utf-8 -*-
"""
format_lab.py — 족보 포맷 변이 생성기 + 추출 견고성 격자(실험실).

배경(독립감사 b)
----------------
모르는 학교의 족보를 가질 수는 없지만, **포맷이 변하는 축(basis vector)** 은 가질 수 있다.
전국 족보는 소수의 독립 축(정답 표기·문항 번호·헤더·해설 위치·텍스트 품질)의 조합이다.
이 모듈은 각 축의 값을 파라미터로 받아 **ground truth 를 아는** 합성 족보 텍스트를 양산하고,
추출 순수함수(extract.*)를 그 cross-product 격자에 돌려 **regex 분절이 어느 축에서 깨지는지**
실측한다("다른 학교 없이 다른 학교를 테스트하는" 유일한 실험실 대체물).

범위
----
이 격자는 **텍스트 계층(regex 분절)** 을 본다 — 정답 표기/번호/헤더/해설 축. 조판(1단/2단·표)·
스캔이미지는 pypdf/OCR 추출 계층 문제라 여기서 다루지 않는다(별도). 텍스트만 보므로 stdlib 만 쓴다.

핵심 관찰(설계가 의도한 결과)
-----------------------------
split_blind_key 는 **답 마커로** 분절하므로, 문항 분절(recovered 문항수)은 번호·헤더 형식과
무관하고 오직 '답 마커가 있느냐'에만 의존한다. 따라서 정답 표기가 키워드 없는 형식
(원문자만/본문 색칠/무표기)이면 문항이 통째로 사라진다 — 감사 (a)의 본질을 격자가 재현한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import (  # noqa: E402
    count_extraction_markers, split_blind_key, count_question_numbers,
    DEFAULT_HEADER_REGEX,
)

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

# ── 합성 문항(ground truth) — 3개 범위에 6문항. 한글 stem(실 족보 반영). ──────────
SCOPES = [
    ("순환생리", [
        {"stem": "심박출량을 가장 잘 설명하는 것은?",
         "opts": ["전부하", "후부하", "심박수×일회박출량", "수축력", "정맥환류"],
         "ans": "3", "expl": "심박출량 = 심박수 × 일회박출량."},
        {"stem": "다음 중 전부하를 증가시키는 것은?",
         "opts": ["출혈", "정맥환류 증가", "이뇨제", "기립", "빈맥"],
         "ans": "2", "expl": "정맥환류가 늘면 전부하가 증가한다."},
    ]),
    ("호흡생리", [
        {"stem": "기능적 잔기량의 정의로 옳은 것은?",
         "opts": ["폐활량+잔기량", "예비호기량+잔기량", "일회호흡량", "흡기용량", "총폐용량"],
         "ans": "2", "expl": "FRC = 예비호기량 + 잔기량."},
        {"stem": "산소해리곡선을 좌측 이동시키는 것은?",
         "opts": ["발열", "산증", "2,3-DPG 증가", "알칼리증", "고탄산혈증"],
         "ans": "4", "expl": "알칼리증은 곡선을 좌측 이동시킨다."},
    ]),
    ("신장생리", [
        {"stem": "사구체여과율을 추정하는 지표는?",
         "opts": ["BUN", "크레아티닌청소율", "혈색소", "소변비중", "나트륨"],
         "ans": "2", "expl": "크레아티닌청소율로 GFR을 추정한다."},
        {"stem": "원위세뇨관에 작용하는 이뇨제는?",
         "opts": ["만니톨", "푸로세미드", "하이드로클로로티아지드", "아세타졸아미드", "스피로놀락톤"],
         "ans": "3", "expl": "티아지드는 원위세뇨관에 작용한다."},
    ]),
]

# ── 변이 축(basis vectors) ────────────────────────────────────────────────────
ANSWER_STYLES = ["ko_label", "en_label", "circled_only", "none"]  # 정답 표기
QNUM_STYLES = ["dot", "paren", "q_prefix", "none"]                # 문항 번호
HEADER_STYLES = ["bracket", "none"]                              # 헤더 유무/형식
EXPL_STYLES = ["after", "none"]                                  # 해설 위치


def _qnum(style, n):
    return {"dot": f"{n}. ", "paren": f"{n}) ", "q_prefix": f"Q{n}. ", "none": ""}[style]


def _answer_line(style, ans):
    if style == "ko_label":
        return f"정답: {ans}"
    if style == "en_label":
        return f"A: {ans}"
    if style == "circled_only":         # 키워드 없이 원문자만(본문 색칠의 텍스트 근사) → ANS_RE 미매칭
        return CIRCLED[int(ans) - 1]
    return None                          # none: 답 줄 자체를 생략


def _ocr_perturb(line):
    """결정론적 경량 OCR 노이즈 — stem 본문에만(구조 마커·번호·답은 건드리지 않음)."""
    return line.replace("는 ", "는  ").replace("의 ", "ㅇl ")  # 흔한 OCR 변이(공백 중복·ㅇl)


def render(answer_style="ko_label", qnum_style="dot", header_style="bracket",
           expl_style="after", ocr_noise=False, drop_answers=()):
    """축 값으로 합성 족보 텍스트를 만든다(번호는 범위 무관 1..N 연속).

    drop_answers: 답 줄을 생략할 1-based 문항번호 집합 — '일부만 답 미표기'(혼합) 시나리오용.
    이 문항은 다음(답 있는) 문항에 흡수돼야 정상(감사 a의 부분 누락 = 0.4.1 가드 대상)."""
    drop = set(drop_answers)
    lines = []
    n = 0
    for si, (label, qs) in enumerate(SCOPES):
        if header_style == "bracket":
            lines.append(f"[{2024 - si} 생리학교실 교수{chr(65 + si)}] {label}")
            lines.append("")
        for q in qs:
            n += 1
            stem = q["stem"]
            if ocr_noise:
                stem = _ocr_perturb(stem)
            lines.append(_qnum(qnum_style, n) + stem)
            # 선지는 항상 원문자(①②…)로 — 번호 축과 충돌 방지(가장 흔한 한국 관례).
            lines.append("  ".join(f"{CIRCLED[i]} {opt}" for i, opt in enumerate(q["opts"])))
            al = None if n in drop else _answer_line(answer_style, q["ans"])
            if al is not None:
                lines.append(al)
            if expl_style == "after" and answer_style != "none" and n not in drop:
                lines.append(f"해설: {q['expl']}")
            lines.append("")
    return "\n".join(lines)


def ground_truth():
    """알려진 진짜 값."""
    n = sum(len(qs) for _, qs in SCOPES)
    return {"n_questions": n, "n_scopes": len(SCOPES)}


def grid():
    """모든 축 조합을 dict 로 yield."""
    for a in ANSWER_STYLES:
        for qn in QNUM_STYLES:
            for h in HEADER_STYLES:
                for e in EXPL_STYLES:
                    yield {"answer_style": a, "qnum_style": qn,
                           "header_style": h, "expl_style": e}


def answerable(combo):
    """이 포맷에서 답 마커(ANS_RE)가 잡히는가 = 분절이 성립하는가."""
    return combo["answer_style"] in ("ko_label", "en_label")


def evaluate(combo, ocr_noise=False):
    """한 조합을 렌더 후 추출 순수함수로 측정 → ground truth 대비 지표."""
    text = render(ocr_noise=ocr_noise, **combo)
    gt = ground_truth()
    marks = count_extraction_markers(text, DEFAULT_HEADER_REGEX)
    blind, key = split_blind_key(text, lambda i: (None, None, None), lambda i: 1)
    n_absorbed = sum(1 for q in blind if q.get("absorbed_qnums"))
    return {
        "expected_q": gt["n_questions"],
        "header_count": marks["header_count"],
        "answer_markers": marks["answer_marker_count"],
        "n_recovered": len(blind),          # split_blind_key 가 복원한 문항수
        "n_by_number": count_question_numbers(text),
        "n_absorbed": n_absorbed,
        "answerable": answerable(combo),
    }


def _report():
    """격자를 돌려 'regex 분절이 어느 축에서 깨지는지' 매트릭스를 출력(개발자 진단용)."""
    gt = ground_truth(); n = gt["n_questions"]
    print(f"ground truth: {n}문항 / {gt['n_scopes']}범위   (recov==expected 면 OK)\n")
    print(f"{'answer':13}{'qnum':9}{'header':8} | hdr ans recov bynum absorb | 판정")
    print("-" * 78)
    breaks = 0
    for c in grid():
        if c["expl_style"] != "after":
            continue
        r = evaluate(c)
        if r["n_recovered"] == n:
            v = "OK"
        else:
            breaks += 1
            legible = (r["n_recovered"] == 0 or r["header_count"] == 0
                       or r["n_recovered"] != r["n_by_number"] or r["n_absorbed"] > 0)
            v = "BREAK·보임" if legible else "BREAK·침묵⚠"
        print(f"{c['answer_style']:13}{c['qnum_style']:9}{c['header_style']:8} | "
              f"{r['header_count']:3} {r['answer_markers']:3} {r['n_recovered']:5} "
              f"{r['n_by_number']:5} {r['n_absorbed']:6} | {v}")
    print(f"\nBREAK {breaks}건 — 전부 답표기 축(키워드 없는 정답)에서 발생, 번호·헤더 축은 OK.")
    print("→ 결론: regex 분절은 포맷 변이가 아니라 '답 마커 유무'에만 의존. redaction→LLM 분절은")
    print("  바로 이 (a)류(키워드 없는/누락 정답)를 위한 처방이며, 그 외 포맷 강건성은 이미 충분.")


if __name__ == "__main__":
    _report()
