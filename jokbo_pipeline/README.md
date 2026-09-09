# jokbo_pipeline — 족보 재검증 파이프라인

의대 족보 PDF 를 받아 **정답을 다시 검증하고 새 해설을 붙인** DOCX 를 만든다.
같은 데이터로 `kd_library` 가 웹 뷰어를 빌드한다. 과목에 종속되지 않는다.

```
족보 PDF ──extract──▶ 블라인드 문항 + 봉인 정답키 ──사람/AI 재검증──▶ questions_data.py
                                                                          │
                                                            validate ─────┤
                                                                          ├──▶ build.py      → DOCX
                                                                          └──▶ build_viewer  → HTML 뷰어
```

**이 문서가 문항 필드 규약의 정본이다.** 뷰어 쪽 문서는 [`../kd_library/README.md`](../kd_library/README.md).

---

## 1. 파일 지도

| 파일 | 역할 |
|---|---|
| **`schema.py`** | **스키마 단일 정의.** 필드 목록(`KEEP`)·범위 헤더 파싱(`clean_scope`/`scope_prof`)·교수명 정규화(`split_prof`/`meta_nameonly`)·왕족 태그(`is_royal`/`strip_royal`)·정답 개수(`n_correct`)·`load_scopes`·`FLAG_TAXONOMY`/`REQUIRED`·2026 범위 상태(`scope_tokens`/`scope_status`/`SCOPE_WEIGHT`) |
| **`validate.py`** | **빌드 전 통합 검증 게이트.** 필수필드 + 무결성 + strict 3종 + no-spoiler·커버리지 감사를 한 번에. 에러 있으면 exit 1 (빌드는 안 함) |
| `extract.py` | PDF 구조 추출(헤더·범위라벨·문항·도판). 족보 형식에 따라 헤더 정규식·정답 패턴 조정이 필요할 수 있다 |
| `build.py` | DOCX 빌더. 과목 무관, 경로만 인자로 받는다 |
| `parse_warnings.py` | **추출 경고 taxonomy·blocker 단일 정의.** `extract.py` 가 만들고 `main.py` 가 `counts.json` 으로 읽어 체크포인트를 막는다 |
| `format_probe.py` · `format_lab.py` | Phase1 결정론 포맷 추론 (`--auto-format`) |
| `llm_segment.py` | Phase2 포인터맵 절단·검증 (`--segmentation`). 결정론·stdlib·무-API |
| `coverage_audit.py` | 커버리지 감사 — 놓친 distinct 문항 탐지 |
| `nospoiler_audit.py` | 정답 노출 감사 |
| `merge_rtype.py` | 왕족 변형 병합 → R형 초안 (authoring 보조) |
| `extract_cols.py` | 2단 조판 좌/우 단 분리 추출 CLI |
| `batch_stats.py` | 연도·필드·왕족·범위 상태 집계 CLI |
| `questions_data_template.py` | 문항 dict 템플릿 + 빈 `SCOPES` |

> **`schema.py` 는 `build.py`·`validate.py`·`../kd_library/build_viewer.py` 가 import 한다. 복붙하지 않는다.**
> 뷰어 JS(`viewer_template.html`)에도 같은 로직의 미러가 있으므로 **고칠 때는 양쪽을 함께** 맞춘다.

---

## 2. 데이터 스키마 — 필드 규약 (정본)

```python
SCOPES = [
  ("범위 헤더 · [2026 담당교수: …]", [q1, q2, ...]),
  ...
]
```

`build.py`(DOCX)와 `build_viewer.py`(뷰어)는 **동일한 스키마**를 소비한다. 한 번 쓴 데이터로 양쪽을 빌드한다.

### 2.1 필드

| 필드 | 필수 | 내용 |
|---|:--:|---|
| `meta` | ● | `"YYYY · 교수이름"` |
| `years` | ● | 실제 출제연도 배열. '출제 N회' 배지의 근거 |
| `stem` `options` `verified` | ● | 문제·선지·검증된 정답 |
| `new_expl` | ● | 새 해설. 문자열 또는 불릿 배열 |
| `answers` | | **복수정답일 때만** |
| `source` | | 출처 → Reference 블록 |
| `orig_ans` `orig_expl` | | 원본 답·해설 |
| `flags` | | 분류 마커 (`FLAG_TAXONOMY`) |
| `recon` | | 복원 사정 메모 |
| `image` `image_caption` `images` | | stem 도판 |
| `image_missing` | | 도판을 못 구했을 때의 한 줄 설명 |
| `scope_note` | | 범위 추론·원본 차이 메모 |
| `imp` `clinical_summary` `wrong_option_explanations` `tip` `related_theory` | | 리치 블록 |

선택 필드는 없으면 양쪽 모두 **미렌더**한다. 크래시하지 않는다.

### 2.2 `new_expl` 과 왕족

- 문자열 또는 불릿 배열 둘 다 된다.
- 선두 `【왕족】 ` 태그 → DOCX·뷰어 모두 **배지로 분리**(뷰어 👑 / DOCX 텍스트 `【왕족】`)하고 본문에서는 태그를 뗀다.
- **해설 본문에 마크다운을 쓰지 않는다.** 두 빌더 모두 마크다운을 파싱하지 않아 `**강조**` 가 별표째 출력된다. 강조는 문장 구조로 한다. 별표가 내용인 경우(치식 표기 등)는 그대로 두고, `validate.py` 가 `**…**`·`*…*` 쌍만 경고한다.
- **뷰어는 `flags`·`scope_note` 를 렌더하지 않는다.** 학습자에게 알려야 할 결함은 반드시 `new_expl` 본문에 쓴다.

### 2.3 리치 블록

전부 선택이고 비면 자동 숨김. DOCX·뷰어 **동일 순서**로 렌더된다.

`imp`(str) → `clinical_summary`(dict → 표, 빈값 제외) → `wrong_option_explanations`(list → 불릿) → `tip`(str) → `related_theory`(str)

### 2.4 R형과 복수정답은 **별개 축**이다

족보에는 **선지 5개 초과(R형)** 문항과 **정답이 여러 개(복수정답, "모두 고르시오")** 문항이 둘 다 있다. 둘은 독립이다.

| | 정답 1개 | 정답 ≥2개 |
|---|---|---|
| **선지 ≤5 (A형)** | `verified` 만 | `answers` 필수 |
| **선지 >5 (R형)** | `verified` 만 | `answers` 필수 |

- 선지 마커는 **①–⑳** 지원.
- **복수정답일 때만** `answers` 에 정답을 전부 명시한다. 마커 리스트 `["②","④"]` 또는 인덱스 `[2,4]`.
- `answers` 가 있으면(≥2) 뷰어는 **체크박스 + 완전일치 채점**, DOCX 는 **'(복수 정답)'** 표기.
- `--strict-detail` 의 오답선지 필요 개수는 `len(options) − 정답수` 로 자동 보정된다.

> ⚠ **정답 개수를 가정하지 않는다.** 단일정답이 기본이지만 R형·복수정답이 실제로 존재한다.

### 2.5 범위 헤더 꼬리

`· [2026 담당교수: …]` 꼬리는 **뷰어는 표시에서 제거**, **DOCX 는 헤딩에서 떼어 `2026 담당교수:` 부제 줄로 보존**한다. 동일한 `clean_scope` 정규식을 쓴다.

⚠ 범위 **제목** 문자열을 바꾸면 뷰어의 진도·🚩 가 stem 기반 `qid` 로 저장되므로 깨진다. **꼬리만 바꾸는 것은 안전**하다.

### 2.6 교수명은 '이름만'

`meta` 교수란은 이름만 쓴다 — `"2023 · 김철수"` ○ / `"예시과 김철수"` ✗.

- **표시 자동 정규화**: DOCX·뷰어 모두 `'…과/교실' + 이름` 패턴에서 과/교실 토큰을 떼고 이름만 보여준다. 기존 데이터도 자동 적용된다.
- **`--strict-meta`**: 데이터 자체에 과/교실명이 남아 있으면 빌드를 거부한다.

### 2.7 자주 걸리는 작성 함정

- **누락 선지는 번호를 비우지 말고 플레이스홀더로 채운다.** `①②③⑤` 처럼 건너뛰면 `verified 정답(5)이 선지 수(4) 초과` 에러가 난다. `"④ (족보에 복원되어 있지 않음)"` 을 넣고 `recon` 에 사정을 적는다.
- **연도별 반복 왕족은 하나로 합치고 `years` 에 전 연도**를 넣는다. 선지 배치만 바뀐 해는 `orig_ans` 에 병기한다.
- **같은 해를 두 사람이 각각 복원한 경우**는 합치지 말고 별도 문항으로 싣고 `tip` 에서 서로를 가리킨다.
- **중복 stem 경고는 대부분 의도된 것**(연도별 변형, 부록과 주제별 단위 병존)이다. 지우지 않는다.

---

## 3. Authoring 규칙

### 3.1 ★ 블라인드 재검증 — 원본 답을 처음부터 보지 않는다

원본(특히 복원 과정의 오답·오해설)을 먼저 보면 거기에 앵커링되어 검증이 추인이 된다. 순서를 고정한다.

1. **문제(stem + 선지)만 보고** 답과 해설을 **독립적으로 확정**한다. 이 단계에서 `orig_ans`·`orig_expl` 을 **보지 않는다.**
2. 확정한 뒤에 원본과 **대조**한다.
3. **불일치할 때만**, 그리고 **원본이 강의록 기반일 때에 한해** 원본을 참고해 재고·수정한다. 원본이 복원자 추정이거나 출처 불명이면 무시하고 내 확정을 유지한다.
4. 결과를 `flags` 에 남긴다 — `ANSWER_MATCH` / `ANSWER_CORRECTED`(근거를 `source` 에) / `ANSWER_DISPUTED`.

원본은 늘 `orig_ans`/`orig_expl` 로 **분리 보존**한다. 합치지 않는다.

### 3.2 ★ No-spoiler — 재구성한 stem 이 정답을 알려주면 안 된다

도판으로 맞혀야 하는 문항을 복원하면서 정답을 stem·도식·캡션에 적어 버리면 문제가 무력화된다.

| 흔한 실수 | 처방 |
|---|---|
| **stem 에 진단명 박기** — 사진으로 진단을 맞히는 문항을 `"○○ 증후군 환아의 사진…"` 으로 복원 | 진단명을 빼고 **사진 + 임상 단서**로 추론하게 한다. 단, 임상 vignette 의 검사 결과는 전제로 줄 수 있다 |
| **참고 도식에 답 라벨** — 직접 만든 도식에 정답 장기·진단·판정을 적음 | 중립 라벨(곡선 `A·B·C·D`, `①②③`, 가계도 '가·나')로 그리고 **캡션도 중립**으로 |
| **stem 이 정답 패턴을 서술** — 정답의 정의를 문장으로 풀어 씀 | 서술을 빼고 도식을 보고 판단하게 한다 |
| **편집메모 leak** — `※원본은 5선지형…소실`·`(보기 소실)` 같은 복원 주석이 stem 에 | `recon`/`source` 로 옮긴다. ※ `verified` 의 '원본에서 수정' 주석은 답 영역이라 유지해도 된다 |
| **도식 오매칭** | 도식은 질환마다 다르다. 키워드로 일괄 부착하지 말고 문항별로 매칭한다 |

**정당한 단서는 남긴다** — 진단의 근거가 되는 임상 소견은 스포일러가 아니라 풀이 단서다.

작성 후 `nospoiler_audit.py --data questions_data.py` 로 (정답어 stem 노출 / 캡션 답라벨 / 편집메모 leak) 후보를 전수 스캔한다. **오탐이 있으니 사람이 판정**한다.

### 3.3 공통 규칙

재검증 후 수정 시 출처 명시 · 새 의학 해설 추가 · **원본 답·해설 항상 분리 보존** ·
정렬 **범위 > 연도 > 교수** · 깨진 텍스트는 추정 재구성 · 도판은 A(stem)/B(해설) 구분해 **A만** 삽입 ·
누락은 텍스트 `[이미지 누락]`(이모지 금지) · 사용자 검수 승인으로 완료.

---

## 4. 검증 — `validate.py`

빌드 전에 **이것 하나만** 돌린다. 개별 감사를 따로 돌릴 필요가 없다.

```bash
python3 validate.py --data "$WORK/questions_data.py" --raw "$WORK/all_questions.json" \
  --strict-detail --strict-meta --strict-scope
```

### 4.1 항상 실행

- **스키마** — `REQUIRED` 필드 누락·빈값 = 에러.
- **무결성** — 정답 인덱스 범위·중복, `verified`↔`answers` 일치, flag 그룹 상호배타, 정정/논쟁의 `source` 필수, **`STEM_IMAGE_A_PRESENT` ↔ 실제 이미지**(에러), `IMAGE_MISSING` ↔ `image_missing` 설명, 선지 마커 연속성, 해설의 마크다운 잔존, 동일 stem 중복(경고).

굵은 항목들은 **authoring 규칙을 손이 아니라 게이트가 지키게** 한 것이다. 마크다운이 별표째 나가는 것, 플래그만 붙고 사진이 없는 문항, 건너뛴 선지가 여기서 걸린다.

### 4.2 opt-in strict 게이트

| 플래그 | 막는 것 |
|---|---|
| `--strict-detail` | 자세한 authoring 미달 (아래 4.3) |
| `--strict-meta` | `meta` 교수란에 과/교실명이 붙어 있음 |
| `--strict-scope` | 범위 오배치 의심 (아래 4.4) |

기본 OFF 라서 기존 데이터 빌드는 깨지지 않는다. **새 과목은 셋 다 켜서 작업**한다.

### 4.3 `--strict-detail` 기준

문항마다 전부 충족해야 통과한다.

- **`new_expl` 충실** — 왕족 태그를 뗀 뒤 `MIN_NEW_EXPL`(기본 40자, `build.py` 상단 상수) 이상.
- **`imp`** — 한 줄 핵심. 비면 미달.
- **`wrong_option_explanations`** — 정답 외 선지 각각. 개수 `≥ len(options) − 정답수`.

⚠ `build.py` 는 `need = max(1, len(options) − 정답수)` 로 보므로 **주관식(`options=[]`)·보기 소실 문항도 1개를 요구**한다. 날조하지 말고 `"주관식 문항 — 선택지가 없어 오답 보기 해설은 해당 없음."` 같은 **정직한 한 줄**로 채운다.

`clinical_summary`·`tip`·`related_theory` 는 **강제하지 않는다.** 채울 내용이 없는 문항에 억지로 생성하는 것을 막기 위해서다.

미달 시 출력:

```
✗ --strict-detail: 자세한 authoring 기준 미달 N문항 — 빌드 중단
   [범위] 2023 · ○○과 ○○○ — 누락: imp, 오답선지(0/4)
```

### 4.4 `--strict-scope` — 범위 오배치 검출

복원 오류로 문항이 엉뚱한 범위에 들어간 경우를 잡는다.

- **전략**: 각 범위 헤더에서 **대표 키워드**(헤더 문서빈도 ≤ `HEAD_DF_MAX`(=2) 인 희소 토큰 = 질환·토픽명)만 뽑는다. 범용 해부·증상어는 stopword·다빈도로 자동 제외. **stem 만** 본다(해설 교차참조 노이즈 배제).
- **판정**: stem 이 *다른* 범위의 대표 키워드를 `SCOPE_HITS`(=2)개 이상 포함하고 **자기 범위보다 많이** 맞으면 오배치 의심. 추천 범위·근거 키워드와 함께 출력하고 빌드를 거부한다.
- **재배치는 수동.** 자동 이동은 오판 위험이라 하지 않는다. 임계는 `build.py` 상단 상수로 조정한다.
- **오탐이 나면 문항을 옮기지 말고 범위 헤더 문구를 바꾼다.** 희귀 토큰 때문에 생기는 경우가 대부분이다.

---

## 5. 빌드 — `build.py`

```bash
python3 build.py --data "$WORK/questions_data.py" --img "$WORK/images" \
  --out "$SUBJ/<과목> 족보_재검증본.docx" \
  --title "<과목> 족보 — 재검증본" --subtitle "… · 정렬: 범위 > 연도(최신순) > 교수" \
  --year-desc --strict-detail
```

| 옵션 | 설명 |
|---|---|
| `--strict-years` | **기본 ON.** `years` 미입력 문항은 자동 추정 대신 `(연도 미확인)` 으로 표기한다(날조 금지가 기본) |
| `--no-strict-years` | 끄면 `freq()` 토큰 유사도 자동 추정으로 폴백. 노이즈가 많아 비권장 |
| `--inscope "2차,총론"` | `--no-strict-years` 일 때 `freq()` 폴백 대상 bucket. 비우면 전체 |
| `--year-desc` | 연도 정렬을 최신→과거로 (미지정 시 과거→최신) |
| `--strict-detail` · `--strict-meta` · `--strict-scope` | 4.2 참조 |

**출제횟수 배지 '출제 N회 (연도들)' 는 문항 dict 의 수기 `years` 가 1순위다.** 사람이 확인한 실제 출제연도이며 알고리즘·임계와 무관하다.

**다회 판정(병합) 규칙**: 제시문이 비슷하고 **정답이 같으면 병합**(`years` 에 연도 누적), **정답·선지가 달라지는 변형은 분리**(별도 dict).

> 폴백 `freq()` 는 `years` 가 없고 strict 가 아닐 때만 동작한다(토큰 유사도, bucket 한정, 임계 ≥8 AND jaccard ≥0.45). 신뢰도가 낮으니 **최종본은 전부 수기 `years`** 를 권장한다.

---

## 6. 추출 — 3단 에스컬레이션

족보 형식이 지저분할수록 위 단계로 올린다. **아래 단계가 실패했을 때만** 올리고 기본은 항상 결정론이다.

| 단계 | 경로 | 언제 | provenance |
|:--:|---|---|---|
| 0 | `split_blind_key` (기본) | 답 마커가 규칙적 | `deterministic` |
| 1 | `--auto-format` (`format_probe`) | 반복되는 답·해설 **블록 구분자**가 있음 | `auto-format` |
| 2 | `--segmentation` (`llm_segment`) | 규칙적 구분자가 **아예 없음** (freeform 합본·인라인 코멘트형) | `llm-segment` |

Phase1 이 구분자를 못 찾으면 조용히 단계 0 으로 폴백한다(`#P1 … 미검출 → 기본 분절 사용`). 그 상태로 해설 침범·유령 문항이 남으면 Phase2 로 올린다.

### 6.1 Phase2 가 블라인드를 깨지 않는 이유

정답을 본 역할(LLM Segmenter)은 **라인ID → 역할 라벨(포인터맵)만** 내보낸다. 실제 절단은 `llm_segment.apply_segmentation` 이 **원본 라인으로** 한다. LLM 이 텍스트를 한 글자도 재작성하지 않으므로 답이 stem 으로 섞일 물리적 경로가 없다.

포인터맵 스키마(과목·이름·문구 하드코딩 0):

```json
{"questions":[{"qid":1,"stem_lines":[12,13],"option_lines":[14,15,16,17,18],
               "answer_lines":[19],"explanation_lines":[20,21]}],
 "ignore_lines":[0,1,2]}
```

입력은 `extract.py` 가 떨구는 `<work>/lines.json`(라인 인덱싱 원문, 답 포함 → `answer_key.json` 과 같은 노출 수준).

```bash
python3 extract.py --pdf "<pdf>" --work "<work>" --segmentation "<work>/segmentation.json"
# main.py 원클릭 경로도 같은 플래그를 지원한다
python3 main.py --pdf "<pdf>" --subject "<과목>" --segmentation "<work>/segmentation.json"
```

### 6.2 검증 게이트 — LLM 출력을 신뢰하지 않는다 (fail-closed)

`verify_segmentation` 이 기계적으로 증명하고, 실패하면 **blocker 로 체크포인트를 막는다**.

- **구조** (`SEGMENTATION_INVALID`) — 라인ID 범위 밖·중복 배정(파티션 위반)·미할당 본문, 블라인드 불변식 위반(blind 에 `answer`/`expl_raw` 키가 있음).
- **누출** (`SEGMENTATION_LEAK`) — ⓪ stem/option 으로 라벨된 **원본 라인**에 정답 마커(`ANS_RE`)나 해설 표기가 있는가(정제 이후가 아니라 원본에서 잡아야 `clean_stem` 이 '답:' 만 떼고 값을 남기는 구멍을 막는다), ① 정제된 blind 에 해설 마커 잔존, ② 봉인 해설의 핵심어가 같은 문항 blind 와 대량으로 겹침.

둘 다 비어야 `#P2 … ✓ 검증통과`. 하나라도 걸리면 해당 idx 를 재라벨해 재시도한다. **유한 재시도** — 무한 루프 금지.

### 6.3 섹션형 족보 (연도 혼재)

족보가 강의(범위) 섹션 단위로 묶이고 섹션 안에서 연도별 헤더 포맷이 다를 수 있다(예: 최근년 `YYYY년 NN학번[범위]–교수` / 구년도 `[YYYY 소속 교수]`). 단일 정규식이 아니라 **current-scope 추적**(범위 헤더가 scope 를 갱신, 연도-only 헤더는 scope 를 상속)이 필요하다.

이럴 땐 `extract.py` 를 **과목 작업 폴더로 복사해 그 사본에서** 헤더 처리를 손본다. 섹션 경계에서 scope 가 새므로 **최종 authoring 은 실제 페이지를 읽어** 보정한다.

### 6.4 2단 조판

```bash
python3 extract_cols.py --pdf "<pdf>" --out-dir _pages --first 1 --last 20
```

좌·우 단을 페이지별 `pNNN.txt` 로 분리해 순서대로 기록한다. `--engine auto` 는 pdfplumber 를 먼저 쓰고 실패하면 Poppler `pdftotext` 로 폴백한다. 한 번에 뽑으면 두 단이 줄 단위로 뒤섞여 읽을 수 없다.

---

## 7. 도판 패스

추출 도판(`images/pNNN_*.jpg`)은 **그 페이지 문항의 그림**이다. 몇 장만 표본 확인하고 멈추면 깨끗한 임상 사진을 놓친다 → **범위 안 페이지의 도판을 전수로 직접 보고 분류**한다.

| | 판단 |
|---|---|
| **삽입 O** | 깨끗한 임상 사진 — 초음파·CT·MRI, 육안 병리, 현미경 H&E, 임상 사진 |
| **제외 X** | 강의록 PPT 텍스트 캡처, 족보 페이지 스크린샷(질문·정답 포함), 진단명·검사명·구조명이 인쇄된 도해 |

- 삽입했으면 `image`(파일명) + `image_caption`(`"[원본 stem 이미지(A)] …"`) + `flags` 에 `STEM_IMAGE_A_PRESENT`. **플래그만 붙이고 이미지가 없으면 `validate.py` 가 에러로 막는다.**
- 사진이 핵심인데 못 구했으면 `image_missing`(그 사진이 무엇이었는지 한 줄) + `flags` 에 `IMAGE_MISSING`.
- ⚠ **애초에 도판이 없던 문항에 `IMAGE_MISSING` 을 붙이지 않는다.** 도판이 0장인 과목도 있다.
- 다년도 병합 문항에는 대표 1장만.
- **`candidate_images` 는 y좌표 추정일 뿐이다.** 그대로 믿으면 엉뚱한 문항에 붙는다. 페이지를 렌더해 눈으로 확인한다.

### 7.1 유실 도판 보강

원본 그림이 PDF 에 없을 때 둘 중 하나로 보강한다. **둘 다 정답을 노출하지 않게** 한다(3.2 참조).

- **표준 모식도는 직접 생성**(matplotlib). 정확하고 라이선스 문제가 없으며 답을 가린 퀴즈용으로 그릴 수 있어 웹 스크래핑보다 우선한다. 곡선·항목은 `A·B·C·D`·`①②③` 기호로만. 캡션은 `[참고 도식 — …; 원본 그림 대체]`. 생성 스크립트는 그 과목의 작업 폴더에 둔다.
- **실제 사진은 생성 불가 → 라이선스가 명확한 출처**에서 받는다(Wikimedia Commons 등에서 직접 URL·라이선스·저자 확인). 받은 뒤 **반드시 눈으로 검증**한다 — 이름만 맞고 실제 내용이 다른 경우가 흔하다. 캡션에 출처·라이선스를 적고, 큰 파일은 다운사이즈해 뷰어 base64 비대화를 막는다.

---

## 8. 보조 도구

### 8.1 `merge_rtype.py` — 왕족 변형 병합

같은 개념을 여러 해에 걸쳐 **오답 선지만 바꿔** 낸 변형들을, 선지를 모두 모아 **R형 1문항**으로 합친다.

```python
from merge_rtype import merge_to_rtype, format_py
draft, msgs = merge_to_rtype([v2019, v2021, v2023])   # 정답이 같을 때만 병합
print(format_py(draft, msgs))                          # 붙여넣기용 dict + 출처·경고 주석
```

- **병합 게이트**: 제시문이 비슷하고 **정답이 같을 때만** 병합한다. 정답이 다르면 거부하고 '별도 분리' 를 안내한다.
- 정답이 같으므로 결과는 보통 **단일정답 R형**이다. **R형 ≠ 복수정답.**
- 자동 부여되는 `flags`: `MERGED_RTYPE` + `ORIG_RTYPE`/`ORIG_SINGLE`. `new_expl` 선두에 `【왕족】`.
- ⚠ **검수 필수.** union 된 distractor 가 모두 실제 오답으로 타당한지 사람이 확인한다. 결과는 초안이다.
- ⚠ **`years` 만 누적하고 끝내지 않는다.** 한 해 보기만 남기고 연도만 더하면 다른 해의 distractor 가 유실된다. 각 연도의 stem·보기를 원본에서 복구해 union 한다. union 결과가 5선지 이하면 R형 실익이 없으니 A형을 유지한다.
- **정답 텍스트가 해마다 다르나 개념이 같은 경우**는 `merge_to_rtype` 이 거부한다 → 정답 옵션을 하나로 정규화하고 **진짜 distractor 만** union 한다(다른 해의 정답 옵션을 distractor 로 넣지 않는다). 수동 처리.

### 8.2 `coverage_audit.py` — 놓친 문항 탐지

왕족(고빈도 반복) 위주로 authoring 하면 저빈도 1회성·주관식 문항을 놓치기 쉽다. 퍼지 텍스트 dedup 은 stem 노이즈로 신뢰도가 낮으므로 **카운트 대조**로 본다.

- **원리**: `raw 답마커 수`(extract 산출) vs `authored 출제연도 출현합(Σ len(set(years)))` 을 범위별로 대조. 제대로 병합했다면 둘이 근접한다. **gap 이 큰 범위 = 아직 정리 안 된 문항이 남은 곳.**
- **절차**: 배치를 끝낼 때마다 실행 → gap 큰 범위의 페이지 재독 → 보완 → gap 이 충분히 줄면 완료.
- **주의**: gap 일부는 '같은 해 중복 마커'(복원자 중복)라 0까지 내려가지 않을 수 있다. `years` 미입력 문항이 많으면 출현합이 과소해져 gap 이 과대해지니 `years` 부터 채운다.
- 과목 고유의 범위 이름은 코드에 넣지 않는다. 번호 없는 범위 헤더는 `--head-map "키워드=버킷"` 으로 넘긴다.

```bash
python3 coverage_audit.py --data "$WORK/questions_data.py" --raw "$WORK/all_questions.json" \
  [--inscope "2차,총론"] [--bucket 2차] [--head-map "총론=총론,수술=수술"]
```

### 8.3 `batch_stats.py` — 배치 통계

`questions_data.py` 또는 `_work/` 에서 연도별 출현·필드 사용률·왕족 수·플래그·범위별 2026 상태를 Markdown 표로 출력한다.

```bash
python3 batch_stats.py --work output/<과목>/_work        # --json 으로 기계 판독용 출력
```

---

## 9. 새 과목 절차

> ⚠ 과목별 추출기 조정은 공유 `extract.py` 를 직접 고치지 않는다. **`--header-regex` 인자**로 주거나 과목 작업 폴더로 복사해 그 사본을 고친다. 공유 파일을 과목마다 손대면 다른 과목이 깨진다.

```bash
PIPE="<저장소>/jokbo_pipeline"
SUBJ="/path/to/<과목명>"
WORK="$SUBJ/_work"

# 0) 형식 확인 — PDF 3~4페이지를 떠서 헤더·정답 표기 패턴을 본다.
#    필요하면 --header-regex 로 조정(파일 수정 X). 스캔본이면 OCR 먼저.

# 1) 추출
python3 "$PIPE/extract.py" --pdf "$SUBJ/<과목> 족보.pdf" --work "$WORK"

# 2) 재검증 데이터 작성 — 템플릿을 복사해 페이지를 읽으며 SCOPES 를 채운다(배치로 누적).
cp "$PIPE/questions_data_template.py" "$WORK/questions_data.py"
#    가장 손이 많이 가는 단계다. 문항당 1~2분. 여러 세션에 나눠 한다.

# 3) ★ 빌드 전 통합 검증
python3 "$PIPE/validate.py" --data "$WORK/questions_data.py" --raw "$WORK/all_questions.json" \
  --strict-detail --strict-meta --strict-scope
#    에러 0 이 될 때까지 보완한다.
#    no-spoiler·커버리지 섹션은 '정보' — 사람이 판정한다.

# 4) 빌드
python3 "$PIPE/build.py" --data "$WORK/questions_data.py" --img "$WORK/images" \
  --out "$SUBJ/<과목> 족보_재검증본.docx" \
  --title "<과목> 족보 — 재검증본" --subtitle "… · 정렬: 범위 > 연도(최신순) > 교수" \
  --year-desc --strict-detail

# 5) 같은 데이터로 뷰어도
python3 "$PIPE/../kd_library/build_viewer.py" \
  --data "$WORK/questions_data.py" --images "$WORK/images" \
  --template "$PIPE/../kd_library/viewer_template.html" \
  --out "$SUBJ/족보뷰어_<과목>.html" \
  --title "족보 오리자보어 — <과목>" --subject "<과목>" --storage-key <과목>_v1

# 6) 렌더 확인
soffice --headless --convert-to pdf --outdir "$WORK" "$SUBJ/<과목> 족보_재검증본.docx"
```

**한 단위를 끝낼 때마다 3~5 를 돌린다.** 마지막에 몰아서 하면 어디서 깨졌는지 못 찾는다.

---

## 10. 회귀 테스트

파이프라인이나 뷰어 코드를 고쳤으면 **빌드 전에 저장소 루트의 `../run_tests.sh`** 를 돌린다. 전부 통과해야 한다.

| 테스트 | 검증 대상 |
|---|---|
| `tests/test_builders.py` | schema 헬퍼 + `build.detail_gaps`(strict-detail 게이트) + `scope_status` |
| `tests/test_extract.py` · `test_extract_improvements.py` · `test_extract_cols.py` | 추출 헬퍼·파싱 개선·2단 분리 |
| `tests/test_validate_integrity.py` | 무결성 검사(정답 범위·flag·이미지·마크다운) |
| `tests/test_llm_segment.py` | 포인터맵 절단·검증 |
| `tests/test_batch_stats.py` | 배치 통계 집계 |
| `tests/test_main_lifecycle.py` | `main.py` 단계 연결 |
| `../kd_library/tests/test_build_viewer.py` · `test_engine.js` | 뷰어 빌더·엔진 |

---

## 11. 의존성

- **python**: pypdf, python-docx, Pillow (`requirements.txt` 가 단일 정의)
- **CLI**: libreoffice(`soffice`) — 렌더 확인용 · poppler(`pdftoppm`/`pdftotext`) — 페이지 렌더·2단 분리용
- 도판이 많은 족보라면 `pdfplumber` 를 추가로 설치하면 `candidate_images` 가 채워진다
