# -*- coding: utf-8 -*-
"""도판 재배치 — 페이지 렌더를 정본으로 삼아 도판을 다시 자른다 (과목 무관).

`extract.py` 가 `pdfimages` 로 뽑아 주는 도판은 **PDF 안에 박힌 이미지 객체 그대로**라
다음 사고가 난다. 실제로 한 과목에서 전부 나왔다.

  · 투명도 마스크가 따로 뽑히며 깨진 도판
  · 한 변이 200px 도 안 되는 조각(원래 그림의 일부만)
  · y좌표 추정으로 붙어 엉뚱한 문항에 달린 도판
  · 여러 장 문항에서 순서가 뒤바뀜 — 추출 순서는 PDF 내부 객체 순서이지 사람이 보는 순서가 아니다
    (2단 조판에서 오른쪽 단 위쪽 그림이 왼쪽 단 그림보다 먼저 나오는 일이 흔하다)

그래서 이 도구는 **페이지를 렌더해 사람(또는 멀티모달 에이전트)이 눈으로 판정**하게 하고,
판정에 적힌 비율 좌표로 **고해상도 렌더에서 다시 자른다.** 추출본은 쓰지 않는다.

    python3 imgwork.py render --work W --src jokbo --pdf 족보.pdf [--hires-dir DIR]
    python3 imgwork.py find   --data questions_data.py --query "문항의 특징적인 문구"
    python3 imgwork.py apply  --work W --data questions_data.py --out-images DIR

판정 파일 — `<work>/pages/<src>_p<NNN>.json` (사람/에이전트가 작성)

    {"src": "jokbo", "page": 72, "figures": [
      {"fig": 1, "box": [0.07,0.11,0.47,0.33], "verdict": "attach",
       "qid": "S02Q014", "slot": 1, "note": "하지직거상 검사 삽화 1)"},
      {"fig": 2, "verdict": "spoiler", "note": "진단명이 인쇄된 해설 슬라이드"}]}

  verdict : attach | spoiler | duplicate | no_question | junk
  box     : 페이지 대비 비율 [x0,y0,x1,y1]. attach 일 때 필수
  qid     : `find` 가 돌려주는 짧은 ID. **여러 문항이 한 도판을 쓰면 배열로 준다**
            (주제별 단위와 원본 시험지 부록에 같은 문항이 함께 실리는 경우)
  slot    : 한 문항에 여러 장일 때의 순서. **인쇄된 라벨 번호**를 쓴다(추출 순서 금지)

`apply` 산출: 크롭 이미지 + `<work>/image_map.json`(qid → 파일들) + `<work>/도판색인.md`.
**문항 데이터에 써 넣는 일은 하지 않는다** — 과목마다 데이터 구성이 달라서, 매핑만 주고
반영은 과목 쪽 스크립트가 한다.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict

import schema

VIEW_DPI = 150          # 눈으로 판정할 렌더. 한글 디지털 PDF 는 이 정도면 충분하다
CROP_DPI = 400          # 실제로 자를 때 쓰는 렌더 — 판정은 저해상도로 해도 손실이 없다
MAX_PIXELS = 750_000    # 뷰어가 base64 로 인라인해 용량이 +34% 된다. 긴 변이 아니라 화소수로 제한
MAX_SIDE = 1400
JPEG_Q = 80
VERDICTS = {"attach", "spoiler", "duplicate", "no_question", "junk"}


def _sources(work):
    p = work / "sources.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _qid(si, qi):
    return "S%02dQ%03d" % (si, qi)


def _load_questions(data):
    out = []
    for si, (head, qs) in enumerate(schema.load_scopes(data), 1):
        for qi, q in enumerate(qs, 1):
            out.append((_qid(si, qi), schema.clean_scope(head), q))
    return out


# ─── render ──────────────────────────────────────────────────────────────────
def cmd_render(a):
    work = pathlib.Path(a.work)
    (work / "renders").mkdir(parents=True, exist_ok=True)
    (work / "pages").mkdir(exist_ok=True)
    n = int(subprocess.run(["pdfinfo", a.pdf], capture_output=True, text=True,
                           check=True).stdout.split("Pages:")[1].split()[0])
    for p in range(1, n + 1):
        out = work / "renders" / f"{a.src}_p{p:03d}"
        if not out.with_suffix(".png").exists():
            subprocess.run(["pdftoppm", "-png", "-r", str(a.dpi), "-f", str(p), "-l", str(p),
                            "-singlefile", a.pdf, str(out)], check=True, capture_output=True)
    src = _sources(work)
    src[a.src] = {"pdf": str(pathlib.Path(a.pdf).resolve()), "pages": n,
                  "hires_dir": str(pathlib.Path(a.hires_dir).resolve()) if a.hires_dir else ""}
    (work / "sources.json").write_text(json.dumps(src, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print(f"✓ {a.src}: {n}쪽 렌더 → {work/'renders'}")
    print(f"  판정 파일을 {work/'pages'}/{a.src}_pNNN.json 로 쓰세요.")


# ─── find ────────────────────────────────────────────────────────────────────
def cmd_find(a):
    key = re.sub(r"\s+", "", a.query)
    hits = 0
    for qid, sc, q in _load_questions(a.data):
        blob = re.sub(r"\s+", "", (q.get("stem") or "") + " ".join(q.get("options") or []))
        if key and key in blob:
            hits += 1
            cur = q.get("images") or ([q["image"]] if q.get("image") else [])
            print(f"{qid}  [{sc}]")
            print(f"   {q.get('meta')}   {(q.get('stem') or '')[:96]}")
            print(f"   현재 도판 {cur or '없음'}")
            if hits >= a.limit:
                break
    if not hits:
        print("검색 결과 없음 — 더 짧고 특징적인 문구로 다시 시도하세요.")


# ─── apply ───────────────────────────────────────────────────────────────────
def _hires(work, src, page, cfg):
    if cfg.get("hires_dir"):
        for pat in (f"page-{page:02d}.png", f"page-{page:03d}.png", f"{src}_p{page:03d}.png"):
            c = pathlib.Path(cfg["hires_dir"]) / pat
            if c.exists():
                return c
    d = work / "hires"
    d.mkdir(exist_ok=True)
    out = d / f"{src}_p{page:03d}"
    if not out.with_suffix(".png").exists():
        subprocess.run(["pdftoppm", "-png", "-r", str(CROP_DPI), "-f", str(page), "-l", str(page),
                        "-singlefile", cfg["pdf"], str(out)], check=True, capture_output=True)
    return out.with_suffix(".png")


def _qids(fig):
    q = fig.get("qid")
    return [] if not q else ([q] if isinstance(q, str) else list(q))


def _dedup(recs):
    """같은 (문항, slot) 을 두 페이지가 주장하면 한쪽만 남긴다.

    한 문항의 도판이 페이지 경계를 넘어 이어지는 것(slot 1 은 앞 페이지, 2~4 는 다음 페이지)은
    정상이므로 충돌 단위는 페이지가 아니라 (문항, slot) 이다. 도판 하나가 여러 문항을 물고
    있을 수 있으므로 verdict 를 바꾸지 않고 **그 문항만 떼어 낸다.**
    """
    by_slot, npage = defaultdict(list), defaultdict(int)
    for rec in recs:
        k = (rec["src"], int(rec["page"]))
        for f in rec.get("figures", []):
            if f.get("verdict") != "attach":
                continue
            npage[k] += 1
            for q in _qids(f):
                by_slot[(q, int(f.get("slot", 1)))].append((k, f))
    dropped = []
    for (qid, slot), ents in by_slot.items():
        if len(ents) < 2:
            continue
        keep = max(ents, key=lambda e: (npage[e[0]], -e[0][1]))[0]
        for k, f in ents:
            if k == keep:
                continue
            rest = [q for q in _qids(f) if q != qid]
            f["qid"] = rest
            if not rest:
                f["verdict"] = "duplicate"
            dropped.append((qid, slot, k, keep))
    return dropped


def cmd_apply(a):
    from PIL import Image
    work, out_dir = pathlib.Path(a.work), pathlib.Path(a.out_images)
    sources = _sources(work)
    if not sources:
        raise SystemExit(f"✗ {work/'sources.json'} 가 없습니다 — 먼저 render 를 실행하세요.")
    out_dir.mkdir(parents=True, exist_ok=True)
    known = {qid: (sc, q) for qid, sc, q in _load_questions(a.data)}

    recs = []
    for jf in sorted((work / "pages").glob("*.json")):
        r = json.loads(jf.read_text(encoding="utf-8"))
        r["_file"] = jf.name
        recs.append(r)
    for qid, slot, k, keep in _dedup(recs):
        print(f"↔ {qid} slot{slot}: {k[0]} p{k[1]} 대신 {keep[0]} p{keep[1]} 채택")

    assign, index, errors, made = defaultdict(list), [], [], 0
    for rec in recs:
        src, page = rec.get("src"), int(rec.get("page", 0))
        if src not in sources:
            errors.append(f"{rec['_file']} — sources.json 에 없는 src '{src}'")
            continue
        hi = None
        for f in rec.get("figures", []):
            v, fig = f.get("verdict"), f.get("fig")
            tag = f"{src} p{page} fig{fig}"
            if v not in VERDICTS:
                errors.append(f"{tag} — 알 수 없는 verdict '{v}'")
                continue
            if v != "attach":
                index.append((src, page, fig, v, "", f.get("note", "")))
                continue
            qids = _qids(f)
            bad = [q for q in qids if q not in known]
            if not qids or bad:
                errors.append(f"{tag} — 존재하지 않는 qid {bad or '(비어 있음)'}")
                continue
            box = f.get("box")
            if not (isinstance(box, list) and len(box) == 4
                    and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                errors.append(f"{tag} — box 가 [x0,y0,x1,y1] 비율이 아님: {box}")
                continue
            if hi is None:
                hi = Image.open(_hires(work, src, page, sources[src])).convert("RGB")
            W, H = hi.size
            crop = hi.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
            k = min(1.0, (MAX_PIXELS / (crop.width * crop.height)) ** 0.5,
                    MAX_SIDE / max(crop.size))
            if k < 1.0:
                crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))),
                                   Image.LANCZOS)
            name = f"{src}_p{page:03d}_f{fig:02d}.jpg"
            crop.save(out_dir / name, "JPEG", quality=JPEG_Q, optimize=True)
            made += 1
            for q in qids:
                assign[q].append((int(f.get("slot", 1)), name))
            index.append((src, page, fig, "attach", " · ".join(qids), f.get("note", "")))

    for qid, got in assign.items():
        slots = sorted(s for s, _n in got)
        if slots != list(range(1, len(slots) + 1)):
            errors.append(f"{qid} — slot 이 {slots} 로 1..{len(slots)} 연속이 아님. "
                          f"'① 사진 1 … ⑤ 사진 5' 대응이 어긋난다")
    if errors:
        print(f"✗ 판정 파일 오류 {len(errors)}건 — 적용 중단")
        for e in errors[:40]:
            print("  ✗", e)
        sys.exit(1)

    mapping = {q: [n for _s, n in sorted(v)] for q, v in assign.items()}
    (work / "image_map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    LABEL = {"attach": "✅ 연결", "spoiler": "⛔ 정답 노출", "duplicate": "↔ 동일본",
             "no_question": "— 대응 문항 없음", "junk": "— 표지·빈 이미지"}
    lines = ["# 도판 색인 — 페이지 렌더 기준 재배치", "",
             f"- 생성 {made}장 → `{out_dir}`", f"- 연결 문항 {len(assign)}개", "",
             "| 원본 | p | fig | 판정 | 문항 | 비고 |", "|---|---:|---:|---|---|---|"]
    for src, page, fig, v, qid, note in index:
        first = qid.split(" · ")[0]
        stem = (known[first][1].get("stem") or "")[:44].replace("\n", " ") if first in known else ""
        lines.append(f"| {src} | {page} | {fig} | {LABEL[v]} | "
                     f"{qid + ' · ' + stem if qid else ''} | {note} |")
    (work / "도판색인.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✓ 도판 {made}장 → {out_dir}")
    print(f"✓ 매핑 {len(assign)}문항 → {work/'image_map.json'}")
    print(f"✓ 색인 → {work/'도판색인.md'}")
    print("→ image_map.json 을 문항 데이터의 image/images 로 반영하는 일은 과목 쪽 스크립트가 합니다.")


def main():
    ap = argparse.ArgumentParser(description="페이지 렌더 기준 도판 재배치")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="판정용 페이지 렌더 생성")
    r.add_argument("--work", required=True)
    r.add_argument("--src", required=True, help="출처 이름(족보/원본시험지 등 여러 개 가능)")
    r.add_argument("--pdf", required=True)
    r.add_argument("--dpi", type=int, default=VIEW_DPI)
    r.add_argument("--hires-dir", default="", help="이미 있는 고해상도 렌더 폴더(있으면 크롭에 재사용)")

    f = sub.add_parser("find", help="문구로 문항 qid 찾기")
    f.add_argument("--data", required=True)
    f.add_argument("--query", required=True)
    f.add_argument("--limit", type=int, default=8)

    p = sub.add_parser("apply", help="판정 → 크롭·재압축·매핑")
    p.add_argument("--work", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--out-images", required=True)

    a = ap.parse_args()
    {"render": cmd_render, "find": cmd_find, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    main()
