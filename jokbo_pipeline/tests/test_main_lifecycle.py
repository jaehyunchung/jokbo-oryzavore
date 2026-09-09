# -*- coding: utf-8 -*-
"""
test_main_lifecycle.py — main.py 전체 lifecycle 통합 회귀.

다른 테스트들이 모듈 단위(추출 헬퍼·스키마·빌더)를 보는 반면, 이 파일은 **오케스트레이터가
단계를 옳게 이어 붙이는지**를 본다. 후배에게 배포한 뒤에는 개발자가 옆에서 디버깅해 줄 수
없으므로, 첫 실행부터 재개까지의 경로를 여기서 잠근다.

검사:
  1) 의존성 — requirements.txt 단일 진실, 파일 없을 때 폴백, OS별 명령, 실행파일 부재 graceful
  2) 추출 호출 — 플래그 조합(--header-regex/--auto-format/--segmentation)이 extract.py 로 전달
  3) 카운트 — counts.json 우선, 없으면 stdout 정규식 폴백
  4) 체크포인트 — blocker 차단, --approve-extraction 승인, 비대화형 EOF 거부,
                  **blocker 는 승인으로 뚫리지 않음(fail-closed)**
  5) lifecycle — --extract-only 조기 종료 / questions_data.py 없을 때 안내 후 종료 /
                 --skip-extract 재개 시 counts.json 재사용
  6) 경로 — 한글·공백 섞인 과목명/출력 경로
  7) --final — validate 에 strict 플래그가 실제로 붙는지

실제 subprocess 는 하나도 띄우지 않는다(전부 가짜로 대체) — 빠르고, PDF·의존성이 없어도 돈다.

실행: python3 jokbo_pipeline/tests/test_main_lifecycle.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
ROOT = PIPE.parent
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(ROOT))

import main as M  # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRun:
    """subprocess.run 대역. 호출된 명령을 모으고 정해진 결과를 돌려준다."""

    def __init__(self, returncode=0, stdout="", raises=None):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.raises = raises

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        if self.raises:
            raise self.raises
        return FakeCompleted(self.returncode, self.stdout, "")

    def flat(self):
        return [" ".join(str(c) for c in call) for call in self.calls]


def with_fake_run(fake, fn):
    """M.subprocess.run 을 fake 로 바꾼 채 fn() 실행."""
    orig = M.subprocess.run
    M.subprocess.run = fake
    try:
        return fn()
    finally:
        M.subprocess.run = orig


# ═══ 1) 의존성 ══════════════════════════════════════════════════════════════
cmd = M.pip_install_command()
ok(cmd[:4] == [sys.executable, "-m", "pip", "install"], "pip 명령은 sys.executable -m pip install 로 시작")
ok("-r" in cmd and cmd[-1].endswith("requirements.txt"),
   "requirements.txt 가 있으면 -r 로 설치(버전 상한 적용)")
ok(not any(p in cmd for p in ("pypdf", "python-docx")),
   "requirements.txt 경로일 때 패키지 이름을 중복해 넘기지 않음")

_orig_req = M.REQUIREMENTS
M.REQUIREMENTS = Path("/definitely/not/here/requirements.txt")
fallback = M.pip_install_command()
M.REQUIREMENTS = _orig_req
ok("pypdf" in fallback and "pdfplumber" in fallback,
   "requirements.txt 가 없으면 패키지 이름 폴백(pdfplumber 포함)")
ok("-r" not in fallback, "폴백 경로엔 -r 이 없음")

for os_name in ("windows", "macos"):
    cmds = M.install_commands(os_name)
    ok(len(cmds) >= 2, f"{os_name} 설치 명령 존재")
    ok(any("pip" in " ".join(str(x) for x in c) for c in cmds), f"{os_name} 에 pip 설치 포함")
ok(M.install_commands("other") == [], "미지원 OS 는 빈 목록")

# 실행 파일이 없어도(=FileNotFoundError) 죽지 않고 계속한다
fake = FakeRun(raises=FileNotFoundError("no brew"))
with_fake_run(fake, lambda: M.install_deps("macos", dry_run=False))
ok(True, "install_deps 는 실행파일 부재에도 예외를 던지지 않음")

fake = FakeRun()
with_fake_run(fake, lambda: M.install_deps("macos", dry_run=True))
ok(fake.calls == [], "dry_run 은 실제로 아무것도 실행하지 않음")


# ═══ 2)(3) 추출 호출 + 카운트 ════════════════════════════════════════════════
def _extract_case(tmp, **kw):
    fake = FakeRun(stdout="페이지 3 · 임베드 이미지 1 · 헤더 2 · 답마커(문항) 9\n")
    counts = with_fake_run(fake, lambda: M.run_extraction(Path("a.pdf"), Path(tmp), **kw))
    return fake, counts


with tempfile.TemporaryDirectory() as tmp:
    fake, counts = _extract_case(tmp)
    line = fake.flat()[0]
    ok("extract.py" in line and "--pdf" in line and "--work" in line, "extract.py 를 --pdf/--work 로 호출")
    ok("--auto-format" not in line and "--segmentation" not in line, "기본 호출엔 옵션 플래그 없음")
    ok(counts["n_questions"] == 9 and counts["pages"] == 3,
       "counts.json 이 없으면 stdout 정규식으로 카운트 폴백")

with tempfile.TemporaryDirectory() as tmp:
    fake, _ = _extract_case(tmp, header_regex="RE", auto_format=True, segmentation="/s.json")
    line = fake.flat()[0]
    ok("--header-regex RE" in line, "--header-regex 전달")
    ok("--auto-format" in line, "--auto-format 전달")
    ok("--segmentation /s.json" in line, "--segmentation 전달")

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "counts.json").write_text(json.dumps({
        "pages": 40, "images": 7, "headers": 5, "questions": 120,
        "questions_by_number": 118, "absorbed_segments": 2, "mapped": 6,
        "unmerged": 1, "warnings": [{"code": "COUNT_DIVERGENCE", "severity": "warning"}],
    }), encoding="utf-8")
    fake, counts = _extract_case(tmp)
    ok(counts["n_questions"] == 120 and counts["pages"] == 40,
       "counts.json 이 있으면 stdout 보다 우선")
    ok(counts["warnings"][0]["code"] == "COUNT_DIVERGENCE", "counts.json 의 경고 taxonomy 를 실어 나름")
    ok(counts["n_absorbed"] == 2, "흡수 의심 건수 전달")

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "counts.json").write_text("{ 깨진 json", encoding="utf-8")
    fake, counts = _extract_case(tmp)
    ok(counts["n_questions"] == 9, "counts.json 이 깨져도 죽지 않고 stdout 폴백")


# ═══ 4) 체크포인트 ═══════════════════════════════════════════════════════════
def blocker_counts():
    return {"pages": 1, "n_headers": 0, "n_questions": 0,
            "warnings": [{"code": "HEADER_MISSING", "severity": "blocker",
                          "recommended_action": "헤더 정규식을 조정하세요"}]}


def clean_counts():
    return {"pages": 3, "n_headers": 2, "n_questions": 9, "warnings": []}


ok(M.should_block_checkpoint(blocker_counts()) is True, "blocker 경고는 체크포인트를 막는다")
ok(M.should_block_checkpoint(clean_counts()) is False, "경고 없으면 막지 않는다")

ok(M.human_checkpoint(clean_counts(), approved=True) is True,
   "--approve-extraction 은 프롬프트 없이 승인")
ok(M.human_checkpoint(blocker_counts(), approved=True) is False,
   "★ blocker 는 --approve-extraction 으로도 뚫리지 않는다(fail-closed)")


def _no_stdin(fn):
    """stdin 을 EOF 로 만들어 비대화형 실행을 흉내낸다."""
    import io
    orig = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        return fn()
    finally:
        sys.stdin = orig


ok(_no_stdin(lambda: M.human_checkpoint(clean_counts())) is False,
   "비대화형(EOF)에서는 승인되지 않는다")

for answer in ("yes", "y", "예", "네"):
    import io
    orig = sys.stdin
    sys.stdin = io.StringIO(answer + "\n")
    try:
        ok(M.human_checkpoint(clean_counts()) is True, f"'{answer}' 응답을 승인으로 인정")
    finally:
        sys.stdin = orig

import io as _io
orig = sys.stdin
sys.stdin = _io.StringIO("아니오\n")
try:
    ok(M.human_checkpoint(clean_counts()) is False, "'아니오' 는 미승인")
finally:
    sys.stdin = orig


# ═══ 5)(6)(7) lifecycle — main() 경로 ════════════════════════════════════════
def run_main(argv, counts=None, fake_run=None):
    """install/extract 를 가짜로 대체하고 main(argv) 실행 → (rc, subprocess 호출들)."""
    calls = fake_run or FakeRun()
    orig_extract, orig_install = M.run_extraction, M.install_deps
    made = counts if counts is not None else clean_counts()

    def fake_extract(pdf_path, work_dir, **kw):
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        c = dict(made)
        c.setdefault("returncode", 0)
        c.setdefault("stdout", "")
        c["all_questions_json"] = Path(work_dir) / "all_questions.json"
        return c

    M.run_extraction = fake_extract
    M.install_deps = lambda *a, **k: None
    try:
        return with_fake_run(calls, lambda: M.main(argv)), calls
    finally:
        M.run_extraction, M.install_deps = orig_extract, orig_install


with tempfile.TemporaryDirectory() as tmp:
    pdf = Path(tmp) / "a.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    rc, _ = run_main(["--pdf", str(pdf), "--subject", "테스트",
                      "--skip-install", "--extract-only", "--out-dir", tmp])
    ok(rc == 0, "--extract-only 는 사람에게 묻지 않고 0 으로 종료")

with tempfile.TemporaryDirectory() as tmp:
    pdf = Path(tmp) / "a.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    rc, _ = run_main(["--pdf", str(pdf), "--subject", "테스트",
                      "--skip-install", "--extract-only", "--out-dir", tmp],
                     counts=blocker_counts())
    ok(rc == 1, "--extract-only 도 blocker 앞에서는 1 로 종료")

# --extract-only 는 --skip-extract 와도 조합된다(직전 추출 결과를 다시 보여 주는 경우)
with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "테스트_work"; work.mkdir(parents=True)
    (work / "counts.json").write_text(json.dumps(
        {"pages": 2, "headers": 1, "questions": 5, "questions_by_number": 5,
         "warnings": []}), encoding="utf-8")
    rc, _ = run_main(["--pdf", str(Path(tmp) / "a.pdf"), "--subject", "테스트",
                      "--skip-install", "--skip-extract", "--extract-only",
                      "--out-dir", tmp])
    ok(rc == 0, "--skip-extract --extract-only 는 counts.json 을 다시 보여 주고 0 으로 종료")

with tempfile.TemporaryDirectory() as tmp:
    rc, _ = run_main(["--pdf", str(Path(tmp) / "a.pdf"), "--subject", "테스트",
                      "--skip-install", "--skip-extract", "--approve-extraction",
                      "--out-dir", tmp])
    ok(rc == 1, "questions_data.py 가 없으면 안내 후 1 로 종료(빌드로 넘어가지 않음)")

# 한글·공백이 섞인 과목명/경로에서도 작업 폴더가 만들어지고 재개 경로가 동작한다
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "출력 폴더"
    work = out / "예시과목_work"
    work.mkdir(parents=True)
    (work / "counts.json").write_text(json.dumps(
        {"pages": 9, "headers": 3, "questions": 40, "questions_by_number": 40,
         "warnings": []}), encoding="utf-8")
    (work / "questions_data.py").write_text("SCOPES = []\n", encoding="utf-8")
    fake = FakeRun(returncode=0)
    rc, calls = run_main(["--pdf", str(Path(tmp) / "족 보.pdf"), "--subject", "예시과목",
                          "--skip-install", "--skip-extract", "--approve-extraction",
                          "--out-dir", str(out)], fake_run=fake)
    flat = " | ".join(calls.flat())
    ok(rc == 0, "한글·공백 경로에서 빌드 경로까지 완주")
    ok("validate.py" in flat, "빌드 전에 validate.py 를 부른다")
    ok("build.py" in flat, "DOCX 빌드를 부른다")
    ok("build_viewer.py" in flat, "뷰어 빌드를 부른다")
    ok("--strict-detail" not in flat, "--final 없으면 strict 검증은 붙지 않는다")
    ok("--no-jeonnal" not in flat,
       "--viewer-no-jeonnal 없으면 뷰어 빌드에 --no-jeonnal 을 붙이지 않는다")
    ok(str(work / "counts.json") not in flat, "counts.json 은 인자가 아니라 직접 읽는다")

    fake2 = FakeRun(returncode=0)
    rc2, calls2 = run_main(["--pdf", str(Path(tmp) / "족 보.pdf"), "--subject", "예시과목",
                            "--skip-install", "--skip-extract", "--approve-extraction",
                            "--final", "--out-dir", str(out)], fake_run=fake2)
    flat2 = " | ".join(calls2.flat())
    ok("--strict-detail" in flat2 and "--strict-meta" in flat2,
       "--final 은 validate 에 strict-detail·strict-meta 를 붙인다")
    ok("--strict-scope" not in flat2, "--final 은 오탐 있는 strict-scope 는 붙이지 않는다")

    fake3 = FakeRun(returncode=0)
    rc3, calls3 = run_main(["--pdf", str(Path(tmp) / "족 보.pdf"), "--subject", "예시과목",
                            "--skip-install", "--skip-extract", "--approve-extraction",
                            "--viewer-no-jeonnal", "--out-dir", str(out)], fake_run=fake3)
    viewer_calls = [line for line in calls3.flat() if "build_viewer.py" in line]
    ok(rc3 == 0 and len(viewer_calls) == 1 and "--no-jeonnal" in viewer_calls[0],
       "--viewer-no-jeonnal 은 뷰어 빌드 subprocess 에 --no-jeonnal 을 전달한다")

# ★ 상대 --out-dir (기본값 'output' 이 상대경로다) — 하위 스크립트는 cwd=jokbo_pipeline
#   에서 돌기 때문에, 상대경로를 그대로 넘기면 파일을 못 찾는다. 절대경로로 굳혀야 한다.
with tempfile.TemporaryDirectory() as tmp:
    import os
    cwd0 = os.getcwd()
    os.chdir(tmp)
    try:
        work = Path("출력") / "T_work"
        work.mkdir(parents=True)
        (work / "counts.json").write_text(json.dumps(
            {"pages": 1, "headers": 1, "questions": 1, "questions_by_number": 1,
             "warnings": []}), encoding="utf-8")
        (work / "questions_data.py").write_text("SCOPES = []\n", encoding="utf-8")
        fake = FakeRun(returncode=0)
        rc, calls = run_main(["--pdf", "a.pdf", "--subject", "T",
                              "--skip-install", "--skip-extract", "--approve-extraction",
                              "--out-dir", "출력"], fake_run=fake)
        flat = " | ".join(calls.flat())
        ok(rc == 0, "상대 --out-dir 로도 빌드까지 완주")
        ok("--data /" in flat or "--data " + str(Path(tmp).resolve()) in flat,
           "★ 하위 스크립트에 절대경로가 전달된다(cwd=jokbo_pipeline 에서 깨지지 않게)")
        ok(" --data 출력/" not in flat, "상대경로가 그대로 새어 나가지 않는다")
    finally:
        os.chdir(cwd0)

# validate 가 실패하면 빌드로 넘어가지 않는다
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "out"
    work = out / "T_work"
    work.mkdir(parents=True)
    (work / "counts.json").write_text(json.dumps(
        {"pages": 1, "headers": 1, "questions": 1, "questions_by_number": 1,
         "warnings": []}), encoding="utf-8")
    (work / "questions_data.py").write_text("SCOPES = []\n", encoding="utf-8")
    fake = FakeRun(returncode=1)   # validate 실패
    rc, calls = run_main(["--pdf", str(Path(tmp) / "a.pdf"), "--subject", "T",
                          "--skip-install", "--skip-extract", "--approve-extraction",
                          "--out-dir", str(out)], fake_run=fake)
    flat = " | ".join(calls.flat())
    ok(rc != 0, "validate 실패 시 0 이 아닌 종료코드")
    ok("build.py" not in flat, "★ validate 실패 시 DOCX 빌드로 넘어가지 않는다")

# --dry-run 은 설치 명령만 보고 파이프라인을 돌리지 않는다
with tempfile.TemporaryDirectory() as tmp:
    rc, calls = run_main(["--pdf", str(Path(tmp) / "a.pdf"), "--subject", "T",
                          "--dry-run", "--out-dir", tmp])
    ok(rc == 0 and calls.calls == [], "--dry-run 은 이후 단계를 실행하지 않는다")

print(f"\n[test_main_lifecycle] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)
