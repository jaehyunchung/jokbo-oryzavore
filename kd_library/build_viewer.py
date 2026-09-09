#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
족보 오리자보어 — 족보 뷰어 빌드 스크립트 (과목 무관).

questions_data.py(SCOPES) → 이미지 base64 인라인 → JSON 직렬화
→ viewer_template.html 의 플레이스홀더에 주입 → 단일 자기완결 HTML 출력.

사용:
  python3 build_viewer.py \
    --data questions_data.py --images images \
    --template viewer_template.html \
    --out 족보뷰어_○○_2차범위_v5.html \
    --title "○○ 족보 2차범위 v5" --subject "○○ 2차범위" \
    --storage-key ob2_v5

설계 원칙: 서버 0 · 외부 fetch 0 · 이미지 base64만 · 원본 보존 분리 ·
빈 optional 필드 미렌더 · 데이터 가공/날조 금지(파일 그대로 직렬화).
"""
import argparse, base64, json, mimetypes, re, sys
from pathlib import Path
from typing import Final

# 스키마 단일 정의(KEEP·clean_scope·load_scopes)는 sibling jokbo_pipeline/schema.py 에서 import.
# 두 폴더는 항상 나란히 두고 배포하므로 jokbo_pipeline 이 옆에 있다(복붙 금지).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jokbo_pipeline.schema import KEEP, clean_scope, load_scopes  # noqa: E402

JEONNAL_MARKERS: Final[tuple[tuple[str, str, str], ...]] = (
    ("HTML", "<!-- JEONNAL:START -->", "<!-- JEONNAL:END -->"),
    ("JS", "/* JEONNAL:START */", "/* JEONNAL:END */"),
)


def validate_jeonnal_markers(template: str) -> None:
    for kind, start_marker, end_marker in JEONNAL_MARKERS:
        start_count = template.count(start_marker)
        end_count = template.count(end_marker)
        if start_count != 1 or end_count != 1:
            raise SystemExit(
                "템플릿의 JEONNAL 마커가 손상되었습니다: "
                f"{kind} START={start_count}개, END={end_count}개"
            )
        if template.find(start_marker) > template.find(end_marker):
            raise SystemExit(
                f"템플릿의 JEONNAL 마커가 손상되었습니다: {kind} START가 END 뒤에 있습니다."
            )


def strip_jeonnal(template: str) -> str:
    for _kind, start_marker, end_marker in JEONNAL_MARKERS:
        start_index = template.find(start_marker)
        end_index = template.find(end_marker, start_index) + len(end_marker)
        template = template[:start_index] + template[end_index:]
    return template


def image_to_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_questions(scopes, images_dir: Path):
    out, missing_img = [], []
    for order, (header, qs) in enumerate(scopes):
        scope = clean_scope(header)
        for q in qs:
            item = {"scope": scope, "scope_order": order, "scope_header": header}
            for k in KEEP:
                if k in q and q[k] not in (None, "", [], {}):
                    item[k] = q[k]
            # ★주관식/무옵션 방어: options 키를 항상 보장 → 뷰어의 q.options.map 크래시 원천 차단.
            item.setdefault("options", [])
            # 이미지: 파일을 base64 data URI 로 인라인 (외부참조 금지)
            if q.get("image"):
                p = images_dir / q["image"]
                if p.exists():
                    item["image"] = image_to_data_uri(p)
                else:
                    missing_img.append(q["image"])
                    item["image_missing_file"] = q["image"]
            # 다중 이미지(v2 #4): images[] 를 base64 data URI 리스트로 인라인. 존재하는 파일만.
            if isinstance(q.get("images"), list) and q["images"]:
                uris = []
                for fn in q["images"]:
                    p = images_dir / fn
                    if p.exists():
                        uris.append(image_to_data_uri(p))
                    else:
                        missing_img.append(fn)
                if uris:
                    item["images"] = uris
            if q.get("image_missing"):
                item["image_missing"] = True
            out.append(item)
    return out, missing_img


def question_qid(item):
    return item["scope"] + "||" + (item.get("meta") or "") + "||" + str(item.get("stem", ""))[:60]


def find_duplicate_qids(questions):
    groups = {}
    for item in questions:
        groups.setdefault(question_qid(item), []).append(item)
    return [group for group in groups.values() if len(group) > 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="questions_data.py")
    ap.add_argument("--images", default="images")
    ap.add_argument("--template", default="viewer_template.html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--storage-key", default="jokbo_v5")
    ap.add_argument("--no-jeonnal", action="store_true",
                    help="전날 모드 구획을 제거한 경량 뷰어 빌드")
    args = ap.parse_args()

    scopes = load_scopes(args.data)
    images_dir = Path(args.images)
    questions, missing = build_questions(scopes, images_dir)
    duplicate_qids = find_duplicate_qids(questions)

    scope_order = [clean_scope(h) for h, _ in scopes]
    n_img = sum(1 for q in questions if isinstance(q.get("image"), str)
                and q["image"].startswith("data:"))

    payload = {
        "title": args.title,
        "subject": args.subject,
        "storageKey": args.storage_key,
        "scopeOrder": scope_order,
        "questions": questions,
    }
    # </script> 가 데이터 문자열에 들어가도 깨지지 않도록 이스케이프
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    template = Path(args.template).read_text(encoding="utf-8")
    validate_jeonnal_markers(template)
    if args.no_jeonnal:
        template = strip_jeonnal(template)
        if "JEONNAL" in template:
            raise SystemExit(
                "템플릿의 JEONNAL 구획 제거에 실패했습니다: JEONNAL 문자열이 남아 있습니다."
            )
    if "/*__DATA__*/" not in template:
        raise SystemExit("템플릿에 /*__DATA__*/ 플레이스홀더가 없습니다.")
    html = template.replace("/*__DATA__*/", "const APP_DATA=" + data_json + ";")
    Path(args.out).write_text(html, encoding="utf-8")

    # 채점 가능성 점검(비차단 경고): options 가 있는데 정답 마커를 못 잡으면 뷰어에서 자동 'sk'(미채점).
    ungradable = []
    for q in questions:
        opts = q.get("options") or []
        if not opts:
            continue                      # 주관식 — 자가채점(정상)
        has_ans = bool(q.get("answers")) or bool(re.match(r"\s*[①-⑳]", str(q.get("verified", ""))))
        if not has_ans:
            ungradable.append(q.get("meta", "?"))

    print(f"✅ {args.out}")
    print(f"   문항 {len(questions)}개 · 이미지 base64 {n_img}개 · 범위 {len(scope_order)}개")
    if missing:
        print(f"   ⚠ 이미지 파일 누락 {len(missing)}: {missing}")
    if ungradable:
        print(f"   ⚠ 채점 불가(options 有·정답 마커 없음) {len(ungradable)}문항 → 뷰어에서 미채점 처리: {ungradable}")
        print("     (의도된 '확정 불가'면 무시. 마커 표기 오류면 verified 를 ①–⑳ 로 시작하도록 정정.)")
    if duplicate_qids:
        print(f"   ⚠ 중복 qid 감지 {len(duplicate_qids)}건 (같은 scope+meta+stem 앞 60자 — 통계/체크 키 충돌 위험)")
        for group in duplicate_qids:
            verified = list(dict.fromkeys(str(item.get("verified", "")) for item in group))
            print(f"     - {question_qid(group[0])} · {len(group)}문항 · verified={verified}")


if __name__ == "__main__":
    main()
