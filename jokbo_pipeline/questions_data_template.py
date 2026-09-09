# -*- coding: utf-8 -*-
"""
과목별 검증 데이터 템플릿.  이 파일을 과목 폴더의 _work/questions_data.py 로 복사해 채운다.

★★ 이 스키마는 build.py(DOCX) 와 kd_library/build_viewer.py(HTML 뷰어) 가 **동일하게** 소비한다.
   같은 questions_data.py 하나로 양쪽(DOCX·뷰어)을 모두 빌드할 수 있다(=정확히 호환).

문항 dict 스키마  (필수 ● / 선택 ○)
  ● meta      : "2023 · 홍길동"   ★교수명은 '이름만'(과/교실명 금지: '소아청소년과 홍길동' ✗ → '홍길동' ✓).
                연도로 시작해야 정렬·연도배지. build.py --strict-meta 가 과/교실명 포함을 차단.
  ● stem      : "문제 본문(교정·추정재구성된 텍스트)"
                ★No-spoiler: 이미지/도식으로 맞혀야 하는 문항은 stem 에 정답(진단명·정답항목·판정)을
                적지 말 것. 진단명 대신 임상 단서로 추론하게 하고, 정답 패턴 서술(예 가계도 양식 설명)·
                복원 편집메모(※원본…소실)는 stem 에서 빼 recon/source 로. (정당한 임상 단서·전제는 유지.)
                authoring 후 nospoiler_audit.py 로 점검. 자세히는 README 'No-spoiler 원칙'.
  ● options   : ["① ...", "② ...", ...]   ─ 마커 ①–⑳ 지원. **5개 초과 = R형**(단일정답·복수정답 둘 다 가능).
  ● verified  : "검증 정답 + (필요시 '원본 X에서 수정')"  ─ 복수정답이면 "②, ④ …" 처럼 모두 표기.
  ○ answers   : ["②","④"]   ★**복수정답(정답 2개 이상)일 때만** 작성. 정답 마커 리스트(1-based 인덱스 [2,4]도 허용).
                ─ R형(선지 5개 초과)과 복수정답은 **별개**다: R형이어도 정답이 1개면 answers 불필요(verified 만).
                  정답이 2개 이상('모두 고르시오' 등)일 때만 answers 로 전부 명시. 있으면(≥2) 뷰어=복수선택
                  (체크박스)+완전일치 채점, DOCX='(복수 정답)' 표기. 없으면 verified 선두 마커 1개=단일정답.
                  ⚠ 족보엔 5선지 초과(R형)·복수정답 문항이 존재할 수 있으니 정답 개수를 단정하지 말 것.
  ● years     : ["2019","2018","2017"]  수기 확인 실제 출제연도. 배지 '출제 N회 (연도들)' 기준.
                없으면 build.py --strict-years 시 '(연도 미확인)' 표기(자동추정 날조 금지).
  ● new_expl  : "새 의학 해설"  ─ 문자열 또는 **불릿 배열**(["불릿1","불릿2",...]). 배열이면 양쪽 다 불릿 렌더.
                선두에 "【왕족】 " 을 붙이면 고빈출(왕족) 표시 → DOCX·뷰어 모두 별도 배지로 분리하고
                본문 텍스트에서는 태그를 자동 제거한다. (예: "【왕족】 핵심은 …")
  ○ source    : "근거 출처(교과서/가이드라인/UpToDate 등). ANSWER_MATCH는 간략 가능"
  ○ orig_ans  : "답: N"          원본 답(있으면 항상 보존·분리 병기)
  ○ orig_expl : "원본 해설: ..."  원본 해설(있으면 항상 보존·분리 병기)
      ★ Blind 재검증: verified·new_expl 은 **문제만 보고 먼저 독립 확정**한 뒤 원본과 대조한다.
        불일치 시 **원본이 강의록 기반일 때만** 참고해 재고(복원자 추정이면 무시). 원본 선참조 금지(앵커링 노이즈).
        강의록 기반 원본 참고해 수정했으면 source 에 명시. 자세히는 README '규칙 > Blind 재검증'.
  ○ flags     : ["ANSWER_MATCH", ...]   (FLAG_TAXONOMY 7종 중. 없으면 FLAGS 줄 미렌더)
  ○ exam_count    : 3                        (보통 len(years)로 자동, 생략 가능)
  ○ recon         : "추정 재구성 사유"            (TEXT_RECONSTRUCTED)
  ○ image         : "p26_018_Im18.jpg"           (단일 이미지; images/ 안 파일명; STEM_IMAGE_A_PRESENT)
  ○ images        : ["p26_018_a.jpg","p26_018_b.jpg"]  (v2 #4 다중 이미지 — 문항에 여러 장이면 사용.
                    DOCX·뷰어 모두 전부 렌더. extract.py 가 준 candidate_images 에서 골라 채운다.)
  ○ image_caption : "[원본 stem 이미지(A)] ..."   ★No-spoiler: 캡션에 진단명/유전양식을 적지 말 것
                    (소견 기술만). '진단은?'·'유전형태는?' 문항인데 캡션이 답을 적으면 stem 정리가 무의미.
                    참고 도식은 답 가린 중립 라벨(곡선 A·B·C·D / ①·②·③ / 가계도 '가·나')로 생성·캡션.
  ○ image_captions: ["...","..."]                (v2 #4 images[] 와 1:1 평행 캡션 리스트; 선택)
                    ★extract.py 의 candidate_images 는 y좌표 추정 후보일 뿐 — PDF 원본과 대조 후 확정할 것.
  ○ image_missing : "원본 참조 이미지가 PDF에 없음 ..."   (IMAGE_MISSING)
  ○ scope_note    : "빈 범위 라벨을 ...로 추론"          (SCOPE_RECLASSIFIED_OR_INFERRED)

  ── 리치 블록 (전부 ○, 비면 양쪽에서 자동 숨김. DOCX·뷰어 동일 순서로 렌더) ──
  ○ imp                       : "한 줄 핵심(IMP)"                              (문자열)
  ○ clinical_summary          : {"진단":"...", "검사":"...", "치료":"..."}     (dict → 표; 빈값 자동 제외)
  ○ wrong_option_explanations : ["① 오답 이유", "③ 오답 이유", ...]            (배열 → 불릿)
  ○ tip                       : "시험 포인트 한 줄"                            (문자열)
  ○ related_theory            : "관련 기전/이론 설명"                          (문자열)

FLAG_TAXONOMY 7종 (상호배타: answer_group 1개 / image_group 1개)
  answer_group : ANSWER_MATCH | ANSWER_CORRECTED | ANSWER_DISPUTED
  image_group  : STEM_IMAGE_A_PRESENT | IMAGE_MISSING
  기타         : TEXT_RECONSTRUCTED, SCOPE_RECLASSIFIED_OR_INFERRED
병합 R형 출처 플래그(merge_rtype.py 가 부여 — 위 7종과 별개):
  MERGED_RTYPE   : 왕족 변형들을 병합해 만든 R형(합성 문항)임을 표시.
  ORIG_RTYPE     : 병합 전 '원래 문항'이 R형(선지 5개 초과; 단일·복수 무관)이었음.
  ORIG_SINGLE    : 원래 문항이 모두 단일정답 A형(≤5선지)이었음(이 R형은 순수 합성).

다회 출제(병합) 판정 규칙:
  · 제시문이 비슷하고 '정답이 같으면' 같은 문항으로 병합 → years 에 모든 연도 나열.
  · 선지/정답이 달라지는 '변형'은 분리(별도 dict) → 각자 own years.  ← 기본
  · (대안) '정답이 같고' distractor 풀만 다른 변형들을 한 R형으로 합치려면 merge_rtype.merge_to_rtype()
    로 초안 생성. **병합 게이트=정답 같을 때만**(다르면 거부·분리). 선지 union·재번호, 공통 정답 유지
    → 보통 **단일정답 R형**(R형≠복수정답), MERGED_RTYPE/ORIG_* 플래그 자동.
    ⚠ 검수 필수 — union 된 distractor 가 모두 실제 오답으로 타당한지 사람이 확인(날조 금지).
  · meta 연도 = 대표(보통 최신) 출제연도 → --year-desc 정렬 위치 결정.

SCOPES 범위 헤더 규약:
  ("범위 헤더 문자열   ·   [2026 담당교수: 김OO·이OO]", [문항, ...])
  꼬리 '· [2026 담당교수: …]' 는 선택. 있으면 뷰어는 표시에서 제거하고, DOCX 는 헤딩에서 떼어
  '2026 담당교수: …' 부제 줄로 보존한다(양쪽 동일 규약 — clean_scope 정규식 공유).
"""

# 예시 1: 최소 문항 (선택 필드 생략 가능 — KeyError 없음)
example_min = {
  "meta": "2023 · ○○○",
  "years": ["2023", "2021"],
  "stem": "예시 문제 본문?",
  "options": ["① 보기1", "② 보기2", "③ 보기3", "④ 보기4", "⑤ 보기5"],
  "verified": "③ 보기3",
  "new_expl": "정답 근거를 의학적으로 설명.",
}

# 예시 2: 풀옵션 (왕족·리스트 해설·리치블록·원본보존)
example_full = {
  "meta": "2022 · △△△",
  "flags": ["ANSWER_CORRECTED"],
  "years": ["2022", "2020", "2018"],
  "stem": "예시 문제 본문(왕족·리치블록)?",
  "options": ["① 보기1", "② 보기2", "③ 보기3"],
  "verified": "② 보기2 (원본 ①에서 수정)",
  "source": "표준 교과서 등.",
  "new_expl": ["【왕족】 정답이 옳은 이유를 기전·근거와 함께 한 문장 이상으로 충실히 서술한다.",
               "감별·예외 등 보강 포인트를 덧붙인다.",
               "필요시 가이드라인/교과서 근거를 명시한다."],
  "imp": "한 줄 핵심(IMP).",
  "clinical_summary": {"진단": "○○", "검사": "○○", "치료": "○○"},
  "wrong_option_explanations": ["① 는 ~때문에 오답", "③ 은 ~때문에 오답"],
  "tip": "시험에 이렇게 나온다.",
  "related_theory": "관련 기전 설명.",
  "orig_ans": "답: 1",
  "orig_expl": "원본 해설 원문.",
}

# 예시 3: R형 + 복수정답 (선지 5개 초과, 정답 여러 개 — answers 로 모두 명시)
example_rtype_multi = {
  "meta": "2021 · ◇◇◇",
  "flags": ["ANSWER_MATCH"],
  "years": ["2021"],
  "stem": "다음 중 옳은 것을 모두 고르시오. (R형·복수정답)",
  "options": ["① 보기1", "② 보기2", "③ 보기3", "④ 보기4", "⑤ 보기5", "⑥ 보기6", "⑦ 보기7"],
  "verified": "②, ④, ⑥",
  "answers": ["②", "④", "⑥"],     # ★복수정답: 마커 전부 명시(인덱스 [2,4,6]도 허용)
  "new_expl": "②·④·⑥ 이 옳은 이유를 각각 기전·근거와 함께 한 문장 이상으로 충실히 서술하고, 왜 나머지가 아닌지 대비한다.",
  "imp": "복수정답 R형의 한 줄 핵심.",
  "wrong_option_explanations": ["① 오답 이유", "③ 오답 이유", "⑤ 오답 이유", "⑦ 오답 이유"],  # 오답 = 전체-정답수 = 4개
}

SCOPES = [
  ("범위 ① ○○○   ·   [2026 담당교수: ○○○]", [example_min, example_full, example_rtype_multi]),
  # ("범위 ② ○○○", [q1, q2, ...]),
]
