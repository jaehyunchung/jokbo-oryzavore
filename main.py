# -*- coding: utf-8 -*-
"""
족보 오리자보어 족보 도구 — AI 운영 진입점 (zero-coding junior 전용).

AI가 이 파일을 통해 다음을 자동 수행한다:
  1. OS 감지 → 의존성 자동 설치
  2. PDF 추출 → 카운트 신호 표시 → 인간 확인 체크포인트
  3. questions_data.py 작성/검토 (사람 or AI) → validate.py 구조 검증
  4. DOCX 빌드 (jokbo_pipeline/build.py) + HTML 뷰어 빌드 (kd_library/build_viewer.py)

모든 의존성 설치·실행은 메인세션(나)이 담당한다.

importability guarantee:
  - module-level imports: stdlib only (no third-party; no side effects)
  - heavy deps (pypdf, python-docx, Pillow) imported lazily inside functions
  - `python -c 'import main'` exits 0 with no ImportError on a bare Python install
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

# ─── 버전 (단일 진실) ────────────────────────────────────────────────────────
__version__ = "1.2.0"   # 1.2.0: Phase2 --segmentation(LLM Segmenter 포인터맵 → 코드 절단, llm_segment) 이식. opt-in·fail-closed(구조/누출 검증 실패 시 blocker). 1.1.0: Phase1 --auto-format(제네릭 포맷추론: format_lab/format_probe) 이식. opt-in(기본 off·기존 추출경로 불변)

# ─── 패키지 루트 (이 파일 위치) ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
JOKBO_PIPELINE_DIR = ROOT / "jokbo_pipeline"
KD_LIBRARY_DIR = ROOT / "kd_library"

sys.path.insert(0, str(JOKBO_PIPELINE_DIR))
import parse_warnings  # noqa: E402  (추출 경고 taxonomy/blocker 단일 진실)

# ─── 파이썬 의존성: requirements.txt 가 단일 진실 ────────────────────────────
# 패키지 이름·버전 상한은 requirements.txt 한 곳에만 둔다. 아래 _PIP_FALLBACK 은
# 파일이 없을 때(부분 복사본 등)만 쓰는 안전망이며 버전을 고정하지 않는다.
REQUIREMENTS = ROOT / "requirements.txt"
_PIP_FALLBACK = ["pypdf", "python-docx", "Pillow", "pdfplumber"]


def pip_install_command() -> list:
    """pip 설치 명령 한 줄. requirements.txt 가 있으면 그걸 쓴다(버전 상한 적용)."""
    base = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if REQUIREMENTS.exists():
        return base + ["-r", str(REQUIREMENTS)]
    return base + list(_PIP_FALLBACK)

# ─── OS별 의존성 설치 명령 (AI가 순서대로 실행; 인스펙터블) ───────────────────
# 이 목록이 정확히 실행되는 명령이다. 변경 시 여기만 수정하라(중복 금지).
_INSTALL_COMMANDS = {
    "windows": [
        # Python (user scope, UAC 불필요) — 이미 있으면 자동 스킵.
        # 'Python.Python.3' 은 유효한 winget 패키지 ID 가 아니라 설치가 실패한다
        # (winget ID 는 버전 접미 필수).
        ["winget", "install", "--id", "Python.Python.3.12", "--source", "winget",
         "--scope", "user", "--silent", "--accept-package-agreements",
         "--accept-source-agreements"],
        # LibreOffice (DOCX→PDF 렌더 확인용; UAC 팝업 1회 클릭 필요)
        ["winget", "install", "--id", "TheDocumentFoundation.LibreOffice",
         "--source", "winget", "--silent", "--accept-package-agreements",
         "--accept-source-agreements"],
        # pip 패키지 (requirements.txt 단일 진실)
        # ※ poppler(pdftoppm·pdftotext)는 Windows 설치 목록에 없고 패키지에도 동봉돼
        #   있지 않다. 페이지 렌더 검수에 필요하면 에이전트가 런타임에 받아 poppler_win/
        #   에 풀고 PATH 에 넣는다(AGENTS.md 6.1). 코어 추출은 pypdf 라 없어도 돌아간다.
        pip_install_command(),
    ],
    "macos": [
        # Homebrew가 없으면 설치 (이미 있으면 자동 스킵)
        ["/bin/bash", "-c",
         'command -v brew >/dev/null 2>&1 || '
         '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'],
        # LibreOffice + poppler
        ["brew", "install", "--cask", "libreoffice"],
        ["brew", "install", "poppler"],
        # pip 패키지 (requirements.txt 단일 진실)
        pip_install_command(),
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API (import 가능 함수; side-effect 없음)
# ─────────────────────────────────────────────────────────────────────────────

def detect_os() -> str:
    """현재 OS 반환: 'windows' | 'macos' | 'other'"""
    s = platform.system().lower()
    if s == "windows":
        return "windows"
    if s == "darwin":
        return "macos"
    return "other"


def install_commands(os_name: str) -> list:
    """os_name 에 대응하는 설치 명령 목록 반환 (리스트의 리스트)."""
    return list(_INSTALL_COMMANDS.get(os_name, []))


def install_deps(os_name: str, dry_run: bool = False) -> None:
    """OS별 의존성 자동 설치.

    dry_run=True 이면 실제 실행 없이 명령만 출력 (테스트·검토용).
    """
    cmds = install_commands(os_name)
    if not cmds:
        print(f"[install_deps] OS '{os_name}' 에 대한 설치 명령이 없습니다.")
        return
    for cmd in cmds:
        readable = " ".join(str(c) for c in cmd)
        print(f"[install_deps] {'(dry-run) ' if dry_run else ''}실행: {readable}")
        if not dry_run:
            # brew/winget 자체가 PATH 에 없으면 subprocess.run 이 FileNotFoundError 를 던진다 —
            # 잡지 않으면 트레이스백으로 전체가 중단돼 '보조 도구 실패는 graceful' 계약이 깨진다.
            try:
                rc = subprocess.run(cmd, check=False).returncode
            except FileNotFoundError:
                rc = 127
                print(f"  ⚠ 명령을 찾을 수 없음: {cmd[0]} (미설치 또는 PATH 밖)")
            if rc != 0:
                print(f"  ⚠ 종료코드 {rc} — 계속 진행 (수동 확인 권장)")


def run_extraction(
    pdf_path: Path,
    work_dir: Path,
    header_regex: str = "",
    auto_format: bool = False,
    segmentation: str = "",
) -> dict:
    """PDF 추출 (jokbo_pipeline/extract.py 호출) → 카운트 신호 dict 반환.

    Returns:
        {'pages': int, 'n_images': int, 'n_headers': int, 'n_questions': int,
         'structure_json': Path, 'all_questions_json': Path,
         'stdout': str, 'returncode': int}
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    extract_py = JOKBO_PIPELINE_DIR / "extract.py"
    cmd = [sys.executable, str(extract_py),
           "--pdf", str(pdf_path),
           "--work", str(work_dir)]
    if header_regex:
        cmd += ["--header-regex", header_regex]
    if auto_format:
        # Phase1 포맷추론: 경고 추천 조치('--auto-format 재추출')를 원클릭 경로에서도 수행 가능하게.
        cmd += ["--auto-format"]
    if segmentation:
        # Phase2 에스컬레이션: LLM Segmenter 포인터맵으로 코드가 절단(--auto-format 보다 우선).
        cmd += ["--segmentation", segmentation]

    result = subprocess.run(cmd, capture_output=True, text=True)
    stdout = result.stdout + result.stderr

    counts = {"pages": 0, "n_images": 0, "n_headers": 0, "n_questions": 0,
              "returncode": result.returncode, "stdout": stdout}

    # extract.py 출력 예: "페이지 32 · 임베드 이미지 5 · 헤더 8 · 답마커(문항) 45"
    m = re.search(r"페이지\s+(\d+)\s*·\s*임베드 이미지\s+(\d+)\s*·\s*헤더\s+(\d+)\s*·\s*답마커\(문항\)\s+(\d+)", stdout)
    if m:
        counts["pages"] = int(m.group(1))
        counts["n_images"] = int(m.group(2))
        counts["n_headers"] = int(m.group(3))
        counts["n_questions"] = int(m.group(4))

    # 우선순위: 기계 판독용 counts.json 이 있으면 그걸로 덮어쓴다(stdout 정규식은 폴백) + 경고 taxonomy.
    cjson = work_dir / "counts.json"
    if cjson.exists():
        try:
            with open(cjson, encoding="utf-8") as f:
                man = json.load(f)
            counts["manifest"] = man
            counts["warnings"] = man.get("warnings", [])
            counts.update({"pages": man.get("pages", counts["pages"]),
                           "n_images": man.get("images", counts["n_images"]),
                           "n_headers": man.get("headers", counts["n_headers"]),
                           "n_questions": man.get("questions", counts["n_questions"]),
                           "n_questions_by_number": man.get("questions_by_number", 0),
                           "n_absorbed": man.get("absorbed_segments", 0),
                           "n_mapped": man.get("mapped", 0),
                           "n_unmerged": man.get("unmerged", 0)})
        except Exception as e:
            print(f"[run_extraction] counts.json 파싱 실패(폴백: stdout): {e}")

    counts["structure_json"] = work_dir / "structure.json"
    counts["all_questions_json"] = work_dir / "all_questions.json"
    return counts


def _checkpoint_warnings(counts: dict) -> list:
    if "warnings" in counts:
        warnings = counts.get("warnings")
        if isinstance(warnings, list):
            return parse_warnings.sort_parse_warnings(warnings)
        return []
    return parse_warnings.build_parse_warnings(counts, [])


def format_checkpoint_report(counts: dict) -> str:
    warnings = _checkpoint_warnings(counts)
    lines = [
        "",
        "=" * 64,
        "  [추출 확인 체크포인트] — 반드시 사람이 확인 후 진행하세요",
        "=" * 64,
        f"  페이지 수       : {counts.get('pages', '?')}",
        f"  임베드 이미지   : {counts.get('n_images', '?')}",
        f"  헤더 (범위)     : {counts.get('n_headers', '?')}",
        f"  답마커 (문항)   : {counts.get('n_questions', '?')}",
        f"  문제번호 기준    : {counts.get('n_questions_by_number', 0)}   (보조 — 답마커와 독립, 교차검증)",
        f"  흡수 의심 문항   : {counts.get('n_absorbed', 0)}건   (답 미표기로 합쳐졌을 가능성)",
        f"  후보이미지 문항 : {counts.get('n_mapped', 0)}   (v2 #4 이미지 매핑)",
        f"  병합 분리(unmerge): {counts.get('n_unmerged', 0)}건   (v2 #6)",
    ]

    # 정본은 개인 도구 — 한 줄/경고로 간결하게(친절한 설명문 생략).
    if warnings:
        lines.append("")
        for w in warnings:
            idx = w.get("question_indices") or []
            tail = f" idx={idx}" if idx else ""
            lines.append(f"  ⚠ {w.get('code')} ({w.get('severity', 'warning')}){tail}"
                         f" — {w.get('recommended_action', '')}")
    else:
        lines.append("\n  · 경고 없음.")

    lines.append("=" * 64)
    return "\n".join(lines)


def should_block_checkpoint(counts: dict) -> bool:
    return any(warning.get("severity") == "blocker" for warning in _checkpoint_warnings(counts))


def print_checkpoint(counts: dict) -> None:
    """체크포인트 리포트 + 첫 3문항 미리보기를 출력한다(질문은 하지 않는다).

    사람에게 보여 줄 내용을 만드는 것과, 승인을 '받는' 것을 분리한다 —
    에이전트 경로(--extract-only)는 이 출력만 쓰고 승인은 대화창에서 받는다.
    """
    print(format_checkpoint_report(counts))
    if should_block_checkpoint(counts):
        return

    # 첫 3문항 미리보기 (블라인드 — 원본 답은 answer_key.json 봉인)
    aq_path = counts.get("all_questions_json")
    if aq_path and Path(aq_path).exists():
        try:
            with open(aq_path, encoding="utf-8") as f:
                qs = json.load(f)
            absorbed = [(i, q) for i, q in enumerate(qs) if q.get('absorbed_qnums')]
            if absorbed:
                print(f"\n  ⚠⚠ 흡수 의심 {len(absorbed)}건 — 답 미표기 문항이 다음 문항에 합쳐졌을 수 있습니다:")
                for i, q in absorbed:
                    print(f"     idx {i}: 문제번호 {q['absorbed_qnums']}개 합쳐짐 · 선지 {len(q.get('options') or [])}개 · {str(q.get('stem') or '')[:42]}…")
            print("\n  [첫 3문항 미리보기]  (블라인드 — 원본 답은 answer_key.json 에 봉인)")
            for i, q in enumerate(qs[:3]):
                bucket = q.get('bucket') or f"범위={q.get('scope','?')}"
                nopt = len(q.get('options') or [])
                print(f"  [{i+1}] {bucket}  · 선지 {nopt}개")
                print(f"       문항={str(q.get('stem') or q.get('stem_raw') or '')[:60]}…")
        except Exception as e:
            print(f"  (미리보기 실패: {e})")

    print("=" * 64)


def human_checkpoint(counts: dict, approved: bool = False) -> bool:
    """추출 결과를 보여 주고 진행 여부를 확인한다.

    approved=False (기본): 터미널에서 사람의 응답을 직접 기다린다.
    approved=True  (--approve-extraction): **에이전트가 대화창에서 이미 사람의 승인을
        받았다**는 선언. 프롬프트를 건너뛴다. 코딩 에이전트의 셸 실행은 비대화형인
        경우가 많아 stdin 으로 사람을 붙잡을 수 없기 때문에, 승인 자체를 agent layer
        로 올린 것이다(사람 확인은 여전히 필수 — 건너뛰는 건 '입력 방법'뿐이다).

    ⚠ 어느 경로든 blocker 경고(헤더 0·분절 누출 등)는 승인으로 뚫을 수 없다.
      fail-closed 계약이라 --approve-extraction 도 blocker 앞에서는 False 를 낸다.

    Returns:
        True  → 진행 승인
        False → 중단
    """
    print_checkpoint(counts)
    if should_block_checkpoint(counts):
        return False

    if approved:
        print("\n  ✓ 사람 승인 확인됨(--approve-extraction) — 진행합니다.")
        return True

    try:
        ans = input("\n  위 신호가 정상입니까? 진행하려면 'yes' 를 입력하세요: ").strip().lower()
    except EOFError:
        # 비대화형(stdin 닫힘) 환경 — 트레이스백 대신 한국어 안내 후 미승인 처리.
        print("\n  ✗ 입력을 받을 수 없는 환경입니다(비대화형 실행).")
        print("    · 사람이 직접 쓴다면: 터미널에서 그냥 다시 실행하세요.")
        print("    · AI 에이전트라면: --extract-only 로 결과를 받아 사용자에게 보여 주고,")
        print("      승인을 받은 뒤 --skip-extract --approve-extraction 으로 재실행하세요.")
        return False
    return ans in ("yes", "y", "예", "네")


def build_docx(
    data_py: Path,
    out_path: Path,
    title: str,
    subtitle: str,
    img_dir: Path = None,
    raw_json: Path = None,
    strict: bool = False,
) -> int:
    """validate.py → build.py 순으로 DOCX 빌드.

    strict=True (--final): validate 를 --strict-detail --strict-meta 로 돌린다.
        authoring 충실도(imp·오답선지 해설)와 교수명 '이름만' 규약을 빌드 게이트로
        강제한다 — 에이전트가 별도 검증 단계를 건너뛰어도 최종본은 통과해야만 나온다.
        --strict-scope 는 범위 헤더의 희귀 토큰 때문에 오탐이 있어 넣지 않는다
        (필요하면 validate.py 를 직접 그 플래그로 돌릴 것).

    Returns: build.py 의 returncode (0 = 성공).
    """
    build_py = JOKBO_PIPELINE_DIR / "build.py"
    validate_py = JOKBO_PIPELINE_DIR / "validate.py"

    # ── 1. validate (구조 검증 게이트) ───────────────────────────────────────
    val_cmd = [sys.executable, str(validate_py), "--data", str(data_py)]
    if raw_json and Path(raw_json).exists():
        val_cmd += ["--raw", str(raw_json)]
    if strict:
        val_cmd += ["--strict-detail", "--strict-meta"]
        print("[build_docx] --final: strict 검증(authoring 충실도·교수명)으로 게이트합니다.")
    val_result = subprocess.run(val_cmd, cwd=str(JOKBO_PIPELINE_DIR))
    if val_result.returncode != 0:
        print("✗ validate.py 실패 → DOCX 빌드 중단. questions_data.py 를 수정 후 재실행하세요.")
        return val_result.returncode

    # ── 2. build DOCX ─────────────────────────────────────────────────────────
    build_cmd = [sys.executable, str(build_py),
                 "--data", str(data_py),
                 "--out", str(out_path),
                 "--title", title,
                 "--subtitle", subtitle]
    if img_dir and Path(img_dir).exists():
        build_cmd += ["--img", str(img_dir)]
    build_result = subprocess.run(build_cmd, cwd=str(JOKBO_PIPELINE_DIR))
    return build_result.returncode


def build_viewer(
    data_py: Path,
    template: Path,
    out_path: Path,
    title: str,
    subject: str,
    img_dir: Path = None,
    storage_key: str = "jokbo_v1",
    no_jeonnal: bool = False,
) -> int:
    """kd_library/build_viewer.py を呼んで単一HTML を생성.

    Returns: returncode (0 = 성공).
    """
    build_viewer_py = KD_LIBRARY_DIR / "build_viewer.py"
    cmd = [sys.executable, str(build_viewer_py),
           "--data", str(data_py),
           "--template", str(template),
           "--out", str(out_path),
           "--title", title,
           "--subject", subject,
           "--storage-key", storage_key]
    if img_dir and Path(img_dir).exists():
        cmd += ["--images", str(img_dir)]
    if no_jeonnal:
        cmd.append("--no-jeonnal")
    result = subprocess.run(cmd, cwd=str(KD_LIBRARY_DIR))
    return result.returncode


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    """AI 운영 족보 파이프라인 메인 플로우."""
    ap = argparse.ArgumentParser(
        description="족보 AI 파이프라인 — OS 감지·의존성 설치·추출·재검증·빌드 (AI 운영)"
    )
    ap.add_argument(
        "--version", action="version",
        version=f"jokbo-tools {__version__}",
        help="버전 정보 출력 후 종료",
    )
    ap.add_argument("--pdf", required=True, help="입력 족보 PDF 경로")
    ap.add_argument("--subject", required=True, help="과목명 (예: ○○과)")
    ap.add_argument("--work-dir", default="",
                    help="작업 폴더 (기본: output/<subject>_work)")
    ap.add_argument("--out-dir", default="output",
                    help="최종 출력 폴더 (기본: output/)")
    ap.add_argument("--header-regex", default="",
                    help="헤더 정규식 (빈칸=extract.py 기본값 사용)")
    ap.add_argument("--auto-format", action="store_true",
                    help="Phase1 제네릭 포맷 추론으로 추출: 답·해설 블록 구분자/러닝헤더/컬럼을 "
                         "입력에서 도출해 인라인 해설 침범·유령 문항을 구조적으로 제거. 체크포인트 "
                         "경고의 추천 조치('--auto-format 재추출')를 따를 때 사용.")
    ap.add_argument("--segmentation", default="",
                    help="Phase2 포맷추론 에스컬레이션: LLM Segmenter 가 만든 포인터맵(JSON, "
                         "라인ID→역할) 경로. --auto-format 으로도 추출이 지저분할 때 사용하며, "
                         "검증(파티션·블라인드 불변식·no-leak) 실패 시 체크포인트가 막힌다.")
    ap.add_argument("--extract-only", action="store_true",
                    help="추출까지만 하고 체크포인트 결과를 출력한 뒤 종료. 사람에게 묻지 않는다. "
                         "AI 에이전트용 — 이 출력을 사용자에게 한국어로 설명하고 승인을 받은 뒤 "
                         "--skip-extract --approve-extraction 으로 재실행하라.")
    ap.add_argument("--approve-extraction", action="store_true",
                    help="추출 체크포인트를 사람이 이미 승인했다고 보고 프롬프트를 건너뛴다. "
                         "AI 에이전트가 사용자 승인을 실제로 받은 뒤에만 쓸 것. "
                         "blocker 경고는 이 플래그로도 뚫리지 않는다.")
    ap.add_argument("--final", action="store_true",
                    help="최종본 프로필 — 빌드 전 validate 를 --strict-detail --strict-meta 로 "
                         "돌려 authoring 충실도·교수명 규약을 강제한다.")
    ap.add_argument("--viewer-no-jeonnal", action="store_true",
                    help="HTML 뷰어에서 전날 모드 구획 제거(경량 빌드)")
    ap.add_argument("--dry-run", action="store_true",
                    help="설치 명령만 출력하고 실행하지 않음 (검토용)")
    ap.add_argument("--skip-install", action="store_true",
                    help="의존성 설치 단계 건너뜀 (이미 설치된 경우)")
    ap.add_argument("--skip-extract", action="store_true",
                    help="추출 단계 건너뜀 (이미 추출된 경우; --work-dir 지정 필요)")
    args = ap.parse_args(argv)

    # ── 0. 경로 설정 ──────────────────────────────────────────────────────────
    # ★ 사용자 경로는 전부 절대경로로 굳힌다. build_docx()/build_viewer() 가 하위
    #   스크립트를 cwd=jokbo_pipeline 에서 돌리기 때문에, 상대경로를 그대로 넘기면
    #   그 cwd 기준으로 해석돼 파일을 못 찾는다. --out-dir 기본값이 'output'(상대)
    #   이라 아무 옵션 없이 실행하는 기본 경로가 정확히 여기서 깨졌다.
    pdf_path = Path(args.pdf).resolve()
    subject_safe = re.sub(r"[^\w가-힣]", "_", args.subject)
    out_dir = Path(args.out_dir).resolve()
    work_dir = (Path(args.work_dir).resolve() if args.work_dir
                else out_dir / f"{subject_safe}_work")
    out_dir.mkdir(parents=True, exist_ok=True)

    docx_out = out_dir / f"{subject_safe}_재검증본.docx"
    html_out = out_dir / f"{subject_safe}_뷰어.html"
    data_py = work_dir / "questions_data.py"
    template = KD_LIBRARY_DIR / "viewer_template.html"
    img_dir = work_dir / "images"
    raw_json = work_dir / "all_questions.json"

    print(f"[main] OS={detect_os()}  Python={sys.version.split()[0]}")

    # ── 1. 의존성 설치 ────────────────────────────────────────────────────────
    if not args.skip_install:
        os_name = detect_os()
        install_deps(os_name, dry_run=args.dry_run)
    if args.dry_run:
        # --skip-install 과 함께 줘도 dry-run 은 '검토만' 계약을 지킨다(실제 파이프라인 미실행).
        print("[main] --dry-run 모드: 이후 단계 실행 안 함.")
        return 0

    # ── 2. PDF 추출 ───────────────────────────────────────────────────────────
    if not args.skip_extract:
        if not pdf_path.exists():
            print(f"✗ PDF 파일을 찾을 수 없습니다: {pdf_path}")
            return 1
        counts = run_extraction(pdf_path, work_dir, header_regex=args.header_regex,
                                auto_format=args.auto_format,
                                segmentation=args.segmentation)
        print(counts.get("stdout", ""))
        if counts["returncode"] != 0:
            print("✗ PDF 추출 실패. extract.py 출력을 확인하세요.")
            return 1
    else:
        # 추출 건너뜀(재개 경로): 이전 추출의 기계판독 매니페스트(counts.json)가 있으면 그대로
        # 재사용해 '실제' 경고로 체크포인트를 재평가한다. 없으면 경고 없는 더미 — "warnings" 키를
        # 명시하지 않으면 build_parse_warnings 가 플레이스홀더 "?" 를 0 으로 강제 변환해
        # HEADER_MISSING(blocker) 을 날조하고, 문서가 안내하는 재개 흐름(questions_data.py
        # 작성 후 --skip-extract 재실행)이 영구히 막힌다.
        counts = {"pages": "?", "n_images": "?", "n_headers": "?",
                  "n_questions": "?", "warnings": [],
                  "all_questions_json": work_dir / "all_questions.json"}
        cjson = work_dir / "counts.json"
        if cjson.exists():
            try:
                with open(cjson, encoding="utf-8") as f:
                    man = json.load(f)
                counts.update({"manifest": man,
                               "warnings": man.get("warnings", []),
                               "pages": man.get("pages", "?"),
                               "n_images": man.get("images", "?"),
                               "n_headers": man.get("headers", "?"),
                               "n_questions": man.get("questions", "?"),
                               "n_questions_by_number": man.get("questions_by_number", 0),
                               "n_absorbed": man.get("absorbed_segments", 0),
                               "n_mapped": man.get("mapped", 0),
                               "n_unmerged": man.get("unmerged", 0)})
            except Exception as e:
                print(f"[main] counts.json 파싱 실패(이전 경고 없이 진행): {e}")

    # ── 3. 인간 확인 체크포인트 (필수 — 자동 진행 불가) ─────────────────────
    if args.extract_only:
        # 에이전트 경로: 보여 줄 것만 출력하고 종료한다. 승인은 대화창에서 받는다.
        print_checkpoint(counts)
        if should_block_checkpoint(counts):
            print("\n[main] blocker 경고가 있습니다 — 위 추천 조치를 먼저 처리하세요.")
            print("  (blocker 는 --approve-extraction 으로 뚫리지 않습니다.)")
            return 1
        print("\n[main] --extract-only 완료. 추출물은 아래에 있습니다:")
        print(f"  {work_dir}")
        print("  ➜ 이 결과를 사용자에게 한국어로 설명하고 '맞나요?' 를 물어보세요.")
        print("  ➜ 승인받으면: --skip-extract --approve-extraction 을 붙여 재실행하세요.")
        return 0

    approved = human_checkpoint(counts, approved=args.approve_extraction)
    if not approved:
        print("[main] 체크포인트 미승인 또는 비정상 신호 → 중단.")
        # 분절 blocker 는 위에서 이미 제 recommended_action 을 출력했다 — 거기에 대고
        # '--header-regex 조정/OCR' 을 덧붙이면 엉뚱한 조치를 안내하게 되므로 갈라 준다.
        seg_codes = {"SEGMENTATION_INVALID", "SEGMENTATION_LEAK"}
        if seg_codes & {w.get("code") for w in counts.get("warnings", [])}:
            print("  ➜ 위 안내대로 segmentation.json 의 라인 역할을 다시 분류해 재실행하세요.")
        else:
            print("  ➜ --header-regex 를 조정하거나 PDF OCR 후 재실행하세요.")
        return 1

    # ── 4. questions_data.py 검토 대기 (AI/사람 작성) ────────────────────────
    if not data_py.exists():
        print(f"\n[main] questions_data.py 가 없습니다: {data_py}")
        print("  ➜ 추출 결과(all_questions.json)를 바탕으로 questions_data.py 를 작성하세요.")
        print("  ➜ 작성 완료 후 다시 --skip-extract 를 붙여 재실행하면 빌드 단계로 진행합니다.")
        return 1

    # ── 5. DOCX 빌드 ─────────────────────────────────────────────────────────
    print(f"\n[main] DOCX 빌드 → {docx_out}")
    rc = build_docx(
        data_py=data_py,
        strict=args.final,
        out_path=docx_out,
        title=f"{args.subject} 족보 — 재편집·재검증본",
        subtitle=f"AI 재검증 · {args.subject}",
        img_dir=img_dir,
        raw_json=raw_json,
    )
    if rc != 0:
        print("✗ DOCX 빌드 실패.")
        return rc

    # ── 6. HTML 뷰어 빌드 ─────────────────────────────────────────────────────
    print(f"[main] HTML 뷰어 빌드 → {html_out}")
    rc = build_viewer(
        data_py=data_py,
        template=template,
        out_path=html_out,
        title=f"{args.subject} 족보 뷰어",
        subject=args.subject,
        img_dir=img_dir,
        storage_key=f"{subject_safe}_v1",
        no_jeonnal=args.viewer_no_jeonnal,
    )
    if rc != 0:
        print("✗ HTML 뷰어 빌드 실패.")
        return rc

    # ── 7. 완료 ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("  ✅ 완료")
    print(f"  DOCX : {docx_out}")
    print(f"  HTML : {html_out}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
