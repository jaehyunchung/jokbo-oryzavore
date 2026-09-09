# kd_library — 족보 뷰어 빌더

재검증이 끝난 `questions_data.py` 를 **파일 하나로 완결되는 HTML 퀴즈 뷰어**로 빌드한다.
서버·인터넷·설치가 필요 없고 `file://` 더블클릭으로 열린다. 과목에 종속되지 않는다.

```
questions_data.py + images/  ──build_viewer.py──▶  <과목>_뷰어.html  (단일 파일)
                                    ▲
                          viewer_template.html
```

---

## 1. 구성

| 파일 | 역할 |
|---|---|
| `build_viewer.py` | 빌드 스크립트. `SCOPES` 로드 → 이미지를 base64 data URI 로 인라인 → JSON 직렬화 → 템플릿의 `/*__DATA__*/` 자리에 주입 |
| `viewer_template.html` | 뷰어 본체. 주입된 `APP_DATA` 로 구동. 화면·채점·스케줄러 JS 가 전부 여기 있다 |
| `tests/test_engine.js` | 뷰어 JS 회귀 테스트 |
| `tests/test_build_viewer.py` | 빌더 회귀 테스트 |

**폴더 배치 제약** — `build_viewer.py` 는 필드 목록(`KEEP`)·`clean_scope`·`load_scopes` 를
sibling `../jokbo_pipeline/schema.py` 에서 **import** 한다(스키마 단일 정의, 복붙 금지).
따라서 `kd_library/` 와 `jokbo_pipeline/` 은 **반드시 같은 부모 폴더 아래** 있어야 한다.

`<script>` 안전을 위해 주입 시 `</` → `<\/` 로 이스케이프한다.

---

## 2. 빌드

```bash
python3 build_viewer.py \
  --data        <과목폴더>/questions_data.py \
  --images      <과목폴더>/images \
  --template    viewer_template.html \
  --out         족보뷰어_<과목>.html \
  --title       "족보 오리자보어 — <과목>" \
  --subject     "<과목 표시명>" \
  --storage-key <과목별_고유키>
```

| 옵션 | 필수 | 설명 |
|---|---|---|
| `--data` | | 문항 데이터 (기본 `questions_data.py`) |
| `--images` | | 도판 폴더 (기본 `images`) |
| `--template` | | 템플릿 (기본 `viewer_template.html`) |
| `--out` | ● | 출력 HTML 경로 |
| `--title` | ● | 뷰어 상단 제목 |
| `--subject` | ● | 과목 표시명 |
| `--storage-key` | | localStorage 접두사 (기본 `jokbo_v5`) |
| `--no-jeonnal` | | 전날 모드를 뺀 경량 빌드 |

**주의 3가지**

- **`--storage-key` 는 과목마다 다르게.** 같으면 다른 과목의 진도·통계가 섞인다.
- **`--images` 안의 파일명은 데이터의 `image`/`images` 필드와 정확히 일치해야 한다.** 없으면 그 자리에 `[이미지 누락]` 텍스트가 렌더된다. zero-padding(`p8_` vs `p08_`)에 특히 주의.
- **도판은 미리 재압축해서 넣는다** — 긴 변 1200~1400 px, JPEG q80~82. 뷰어가 base64 로 인라인하므로 원본을 그대로 넣으면 HTML 이 수십 MB 가 된다.

전날 모드는 기본 빌드에 포함된다. 제외하려면 `--no-jeonnal` 을 붙인다.

---

## 3. 데이터 스키마

DOCX 빌더와 **완전히 같은 `questions_data.py`** 를 소비한다. 한 번 작성한 데이터로 양쪽을 모두 빌드할 수 있다.

```python
SCOPES = [
  ("범위 헤더 · [2026 담당교수: …]", [q1, q2, ...]),   # 꼬리 '· [2026…]' 는 표시 시 자동 제거
  ...
]
```

| 필드 | 필수 | 뷰어에서의 쓰임 |
|---|:--:|---|
| `meta` | ● | `"YYYY · 교수"` — 교수 필터·연도 표시 |
| `years` | ● | 연도 필터 + '출제 N회' 배지 |
| `stem` `options` `verified` | ● | 문제·선지·정답 |
| `new_expl` | ● | 해설(문자열 또는 불릿 배열). 선두 `【왕족】` → 👑 배지로 분리 |
| `answers` | | **복수정답일 때만.** 있으면 체크박스 + 완전일치 채점 |
| `orig_ans` `orig_expl` | | 원본 답·해설(분리 보존) |
| `source` | | Reference 블록 |
| `image` `image_caption` | | stem 도판 → base64 인라인 |
| `flags` | | 분류 마커 |
| `imp` `clinical_summary` `wrong_option_explanations` `tip` `related_theory` | | 리치 블록 — 비면 자동 숨김 |

필드 규약의 **정본은 [`../jokbo_pipeline/README.md`](../jokbo_pipeline/README.md)** 다. 여기 표는 뷰어 관점의 요약이다.

> **★ No-spoiler** — 뷰어는 `stem`·`image_caption`·도판을 **그대로** 보여준다. 정답이 거기 적혀 있으면 그대로 노출된다.
> 도판으로 맞히는 문항은 stem·캡션에 진단명을 쓰지 말고, 참고 도식은 중립 라벨(`A·B·C·D`, `①②③`)로 만든다.
> 작성 후 `jokbo_pipeline/nospoiler_audit.py` 로 점검할 것.

**뷰어는 `flags`·`scope_note` 를 렌더하지 않는다.** 학습자에게 알려야 할 결함(정답 논쟁 등)은 반드시 `new_expl` 본문에 쓴다.

---

## 4. 뷰어 기능

### 풀이

| 기능 | 동작 |
|---|---|
| 학습 / 시험 모드 | 시험 모드는 제한시간 타이머 + 일괄 채점 |
| 🔀 셔플 | Fisher-Yates(`shuffleArr`). 전체 풀기·다시 풀기·체크 문항 풀기 모두 적용 |
| 🙈 정보 가리기 | 범위·교수·출제연도·👑 배지를 숨김. 학습 모드는 **정답 확인 직후**, 시험 모드는 **채점 직후** 자동 공개 (`showMeta = !hideInfo \|\| (mode==='exam' ? graded : locked)`) |
| 주관식 | `options` 가 없으면 보기 버튼 대신 '✏️ 주관식' 안내 → 정답 확인 시 자가채점(맞음/틀림/건너뜀). 시험 모드에서는 미채점(`sk`) |
| 🖼 라이트박스 | stem 도판 클릭 → 전체화면. 오버레이·이미지·Esc 로 닫기 |
| 필터 | 범위 > 연도 > 교수 |

### 채점

- **문항 상태**: `ok`(정답) / `ng`(오답) / `sk`(건너뜀·미채점) / `un`(미응답). `un` 은 회색 점선.
- **정답률 분모 = `ok+ng+sk`. `un` 은 제외**하고 "확인한 문항 N개 기준"으로 표기한다.
- **채점 불가 문항**(정답 마커를 확정할 수 없어 `correctSet` 이 빈 경우 — 예: 보기 소실)은 `ng`(자동 오답)가 아니라 **`sk`(미채점)** 로 처리해 감점하지 않는다. 빌더도 '선지는 있는데 정답 마커가 없는' 문항을 빌드 시 경고한다.
- **`qid` = `scope + meta + stem[:60]`.** `meta`(연도·교수)를 넣어 제시문이 같은 R형 변형끼리 🚩·통계 키가 충돌하지 않게 한다.

### 복습·우선순위

| 기능 | 동작 |
|---|---|
| 🎯 약점 집중 | 누적 통계로 약한 문항 20개를 가중 선별. 점수 = 오답률 위주(`(1−정답/시도)*3+0.3`) + 🚩(+1.5) + 빈출 왕족(+0.6), 미시도 1.0. weakest-first 정렬(셔플 켜면 무작위). 필터 단계를 건너뛴다 |
| 🎯 오늘 할 일 | 오늘 due 인 복습 문항 + 우선순위 높은 새 문항을 **분 예산** 안에서 함께 고르고, 범위 coverage 변화를 보여 준다 |
| 확신도 | 답 확인 후 **A 확신 / S 반반 / D 찍음**. 확신했는데 틀린 문항을 우선 복습한다(설정에서 끌 수 있음) |
| ⚡ 한 줄 복습 | 앞면=문제, 뒷면=정답+`imp` 한 줄. `_stats` 정답률은 건드리지 않고 `_sched` 만 갱신 |
| 📊 대시보드 | 시험일을 저장하면 D-day·오늘 할 일 요약·범위별 숙련도·2026 범위 상태·확신 오답 진입점을 보여 준다. 복습 due 를 시험일에 맞춰 앞당긴다 |
| 전날 모드 | 남은 시간과 목표를 넣으면 무엇부터 풀지 블록 단위 계획을 짜고, 진행 상황에 맞춰 재계획한다 |

### 저장

모든 저장은 브라우저 localStorage 이며 키는 `<storage-key>` + 아래 suffix 다.

| suffix | 내용 |
|---|---|
| `_stats` | 문항별 정답 이력·풀이시간 |
| `_flagged` | 🚩 체크 |
| `_daily` | 일별 추세 |
| `_session` | 진행 중 세션 |
| `_prefs` | 셔플·정보 가리기 등 토글 상태 |
| `_sched` | 문항별 복습 due·연속 정답·확신도 이력·시험일 |

- **💾 진도 백업**(⚙ 설정 → `exportProgress`/`importProgress`): 위 전부를 JSON 파일로 내보내고 불러온다. **suffix 기준으로 저장**하므로 storage-key 버전이 바뀌어도(`ob2_v5` → `ob2_v6`) 현재 과목 키로 복원된다. 다른 키의 백업을 불러오면 경고 후 현재 과목에 복원. `file://` 에서도 동작(Blob 다운로드 + FileReader).
- 누적 통계는 **내 정답률·푼 횟수·누적 풀이시간**뿐이다. 보기별 응답률 같은 모집단 통계는 없다(있는 척하지 않는다).
- 타이머는 **내 풀이시간**만 잰다.
- localStorage 쓰기는 try/catch — 브라우저가 막아도 뷰어가 깨지지 않고 배너로 알린다.

### 오프라인

외부 fetch·CDN 이 **0** 이다. 도판까지 base64 로 들어 있어 인터넷 없이 완결된다.

---

## 5. 키보드 단축키

| 키 | 동작 |
|---|---|
| `A` / `S` / `D` | 확신 / 반반 / 찍음 |
| `Space` / `1` / `2` / `→` | 한 줄 복습에서 알았다 / 몰랐다 / 다음 문항 |

---

## 6. 회귀 테스트

엔진이나 빌더를 고쳤으면 **빌드 전에 저장소 루트의 `../run_tests.sh`** 를 돌린다.

- **`tests/test_engine.js`** — 뷰어 JS 를 `viewer_template.html` 에서 **정규식으로 함수 소스를 추출**해 검증한다. judge/correctSet 완전일치 · 빈 correctSet→`sk` · 주관식 무크래시 · `getQid` 충돌 방지 · `normMarker` · `isRoyal` · 교수명 '이름만' · `weaknessList` 가중 정렬 · `scopeStatus` 범위 상태.
  ⚠ **함수 이름이나 시그니처를 바꾸면 추출이 실패해 시끄럽게 깨진다.** 의도된 리팩터 안전망이니, 바꿔야 하면 테스트도 같이 고친다. `node tests/test_engine.js` 로 단독 실행 가능(의존성 0).
- **`tests/test_build_viewer.py`** — `build_questions` 의 주관식 `options` 키 보장 · 도판 base64 인라인 · 없는 이미지 보고 · 빈 optional 제거 · `clean_scope` 적용.

과거에는 jsdom 셰임을 즉석에서 만들고 검증 후 버려서 같은 회귀가 반복됐다. 지금은 테스트를 상주시킨다.

---

## 7. 의존성

- **빌드**: Python 3 표준 라이브러리만(`base64`·`json`·`runpy` 등). 추가 설치 불필요.
- **뷰어**: 순수 정적 HTML. 런타임 의존성 0.
