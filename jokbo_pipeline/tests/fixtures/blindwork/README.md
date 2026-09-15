# blindwork 합성 픽스처

이 폴더의 문항, 인명, 단원, 이미지, 해설은 전부 합성 자료다.

- `batches/u01_예시단위.py`: 판단층을 포함한 D17 8문항 입력이다.
- `batches_struct_only/u01_예시단위.py`: 같은 8문항에서 판단층을 뺀 입력이다.
- `batches_leak/u02_누출예시.py`: 문두 누출과 허용 목록을 검사하는 2문항 입력이다.
- `extract/all_questions.json`: 구조층 추출 입력 4건이다.
- `extract/answer_key.json`: 구조층과 결합할 봉인 답 입력 4건이다.
- `image_map.json`: 기존 이미지를 덮어쓰는 이미지 맵 입력이다.
- `images/p01_1.jpg`: 배치 도판 입력으로 쓰는 8×8 JPEG다.
- `images/p02_1.jpg`: 추출 후보와 이미지 맵 입력으로 쓰는 8×8 JPEG다.
- `stages/solved_ok__t01.py`: 텍스트 슬라이스 7문항의 정상 SOLVED 표본이다.
- `stages/solved_ok__i01.py`: 도판 슬라이스 1문항의 정상 SOLVED 표본이다.
- `stages/solved_bad_keys__t01.py`: 풀이 단계 금지 키를 검사하는 표본이다.
- `stages/solved_bad_count__t01.py`: 보기 판정 수 부족을 검사하는 표본이다.
- `stages/solved_exec__t01.py`: 리터럴 전용 로더가 import를 거부하는 표본이다.
- `stages/adjudicated_ok.py`: 대기 4문항의 정상 ADJUDICATED 표본이다.
- `stages/adjudicated_bad_twoflags.py`: 상호 배타인 판정 플래그를 검사하는 표본이다.
- `stages/adjudicated_bad_nosource.py`: 정정 판정의 출처 누락을 검사하는 표본이다.
- `stages/adjudicated_bad_imgflag.py`: 판정 단계 이미지 플래그 금지를 검사하는 표본이다.
- `stages/explained_ok.py`: 8문항의 정상 EXPLAINED 표본이다.
- `stages/explained_bad_answerkey.py`: 해설 단계 정답 키 금지를 검사하는 표본이다.
- `stages/explained_bad_nowarn.py`: 논쟁 문항의 경고 문구 누락을 검사하는 표본이다.
- `stages/explained_objection.py`: 일곱 번째 문항 이의를 포함한 정상 해설 표본이다.
- `stages/adversarial_ok.py`: 팁만 교체하는 정상 레이어 표본이다.
- `stages/adversarial_bad_count.py`: 정답 교체 뒤 오답 해설 수 부족을 검사하는 표본이다.
- `stages/adversarial_bad_blind.py`: 레이어의 blind 키 금지를 검사하는 표본이다.
- `stages/adversarial_bad_match.py`: 원본과 다른 MATCH 판정을 검사하는 표본이다.
- `stages/adversarial_disposition.py`: 이의 기각 처분을 기록하는 레이어 표본이다.
- `expected.json`: D17 표를 손으로 계산한 scan, audit, slice 기대값이다.
