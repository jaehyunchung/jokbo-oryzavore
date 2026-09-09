/**
 * test_engine.js — 뷰어 엔진(viewer_template.html)의 채점/키 로직 회귀 테스트.
 *
 * ../viewer_template.html 에서 **순수 함수를 직접 추출**해 검증한다(복사본 금지 →
 * 함수가 사라지거나 이름이 바뀌면 추출이 실패해 시끄럽게 깨진다). 추출기는 임의 소스와
 * 주석·문자열을 안전하게 처리한다. DOM 의존 함수는 제외하고 핵심 로직만 본다.
 *
 * 커버: 2026-06-14 출고차단 수정(빈 correctSet/빈 선택 → 'sk', 주관식·보기소실 무감점),
 *       복수정답 완전일치 채점, 단일정답 R형, getQid 충돌 방지, normMarker, isRoyal, 교수명.
 *
 * 실행: node tests/test_engine.js   (의존성 0 — 순수 Node)
 */
'use strict';
const fs = require('fs');
const path = require('path');

const TPL = path.join(__dirname, '..', 'viewer_template.html');
const src = fs.readFileSync(TPL, 'utf8');

// ── 템플릿에서 함수/상수 소스를 균형 중괄호로 추출 ───────────────────────────
function scanCode(source, start, visit, end = source.length) {
  let state = 'code', prev = '';
  for (let i = start; i < end; i++) {
    const ch = source[i], next = source[i + 1];
    if (state === 'line') { if (ch === '\n') state = 'code'; continue; }
    if (state === 'block') { if (ch === '*' && next === '/') { state = 'code'; i++; } continue; }
    if (state === 'regex') {
      if (ch === '\\') i++;
      else if (ch === '/') { state = 'code'; prev = 'x'; }
      continue;
    }
    if (state !== 'code') {
      if (ch === '\\') i++;
      else if (ch === state) { state = 'code'; prev = 'x'; }
      continue;
    }
    if (ch === '/' && next === '/') { state = 'line'; i++; continue; }
    if (ch === '/' && next === '*') { state = 'block'; i++; continue; }
    if (ch === '/' && (!prev || /[({[=,:;!?&|+\-*%^~<>]/.test(prev))) { state = 'regex'; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { state = ch; continue; }
    const result = visit(ch, i);
    if (result !== undefined) return result;
    if (!/\s/.test(ch)) prev = ch;
  }
  return undefined;
}
function codeRanges(source) {
  const ranges = [], open = /<script\b[^>]*>/gi, close = /<\/script\s*>/gi;
  let script, end;
  while ((script = open.exec(source))) {
    close.lastIndex = open.lastIndex;
    end = close.exec(source);
    if (!end) return [[0, source.length]];
    ranges.push([open.lastIndex, end.index]);
    open.lastIndex = close.lastIndex;
  }
  return ranges.length ? ranges : [[0, source.length]];
}
function findCodeMatch(source, pattern) {
  for (const [start, end] of codeRanges(source)) {
    const match = scanCode(source, start, (_ch, i) => {
      pattern.lastIndex = i;
      return pattern.exec(source) || undefined;
    }, end);
    if (match) return match;
  }
  return null;
}
function escapedName(name) { return name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function extractFnFrom(source, name) {
  const pattern = new RegExp('\\bfunction\\s+' + escapedName(name) + '\\s*\\(', 'y');
  const match = findCodeMatch(source, pattern);
  if (!match) throw new Error('소스에 함수 없음: ' + name);
  let parens = 1;
  const bodyStart = scanCode(source, match.index + match[0].length, (ch, i) => {
    if (ch === '(') parens++;
    else if (ch === ')') parens--;
    else if (ch === '{' && parens === 0) return i;
    return undefined;
  });
  if (bodyStart === undefined) throw new Error('소스에 함수 없음: ' + name);
  let depth = 1;
  const end = scanCode(source, bodyStart + 1, (ch, i) => {
    if (ch === '{') depth++;
    else if (ch === '}' && --depth === 0) return i + 1;
    return undefined;
  });
  if (end === undefined) throw new Error('소스에 함수 없음: ' + name);
  return source.slice(match.index, end);
}
function extractConstFrom(source, name) {
  const pattern = new RegExp('\\bconst\\s+' + escapedName(name) + '\\s*=', 'y');
  const match = findCodeMatch(source, pattern);
  if (!match) throw new Error('소스에 상수 없음: ' + name);
  const value = source.slice(match.index).match(new RegExp('^const\\s+' + escapedName(name) + '\\s*=[^;]*;'));
  if (!value) throw new Error('소스에 상수 없음: ' + name);
  return value[0];
}
function extractFn(name) { return extractFnFrom(src, name); }
function extractConst(name) { return extractConstFrom(src, name); }

const CONSTS = ['CIRCLED', 'DEPT_RE', 'ROYAL_RE', 'JN_CFG', 'SCOPE_WEIGHT', 'SCOPE_PROF_RE', 'SR_CFG'];
const FNS = ['getQid', 'loadStats', 'profSeg', 'getProf', 'metaName', 'getOptNum', 'getCorrectNum',
             'normMarker', 'correctSet', 'isMulti', 'asArr', 'isRoyal', 'judge', 'esc', 'bulletize',
             'jnSubjectContext', 'jnHasImage', 'jnFrequency', 'jnRecency', 'jnStudyCostFromStat',
             'jnPriorityFromStat', 'jnStudyCost', 'jnPriority', 'jnScopeUniverse', 'jnCoverage',
             'scopeTokens', 'scopeTokenStatus', 'scopeStatus', 'scopeMetaMap', 'qPriority', 'cpBuildToday',
             'srDefaultSched', 'normFont', 'srNextDue', 'srApplyResult', 'srNormalize', 'srNormalizeSched',
             'srIsGradable', 'srExamMs', 'srClampToExam', 'dbExamState', 'dbMastery',
             'jnCandidates', 'jnExtendPlan', 'jnBuildBlocks',
              'jnBuildPlan', 'jnMarginalGain', 'fnv1a32', 'jnFingerprint', 'jnValidatePlan',
               'jnPairsSeconds', 'jnDataMinutes', 'jnFormatDuration', 'jnClone',
               'jnRemainingSec', 'jnExpectedDoneMs', 'jnComputeDrift', 'jnReplan',
               'jnBuildAttemptSnapshots', 'jnBuildFinalPlanSnapshot', 'rrBack'];
const code = CONSTS.map(extractConst).join('\n') + '\n' + FNS.map(extractFn).join('\n')
           + '\nreturn {' + FNS.join(',') + '};';
const E = new Function(code)();   // 추출 함수들을 한 스코프에서 평가

// ── 미니 테스트 하니스 ───────────────────────────────────────────────────────
let pass = 0, fail = 0;
function ok(cond, msg) { if (cond) { pass++; } else { fail++; console.error('  ✗', msg); } }
function eq(a, b, msg) { ok(a === b, `${msg}  (got ${JSON.stringify(a)}, want ${JSON.stringify(b)})`); }
function close(a, b, msg, eps = 1e-9) { ok(Math.abs(a - b) < eps, `${msg}  (got ${a}, want ${b})`); }

// ── extractFnFrom/extractConstFrom 하드닝 자기테스트 ───────────────────────────
{
  const decoy = "// function foo(){ return 'decoy'; }\nfunction foo(){ return 'real'; }";
  const extracted = extractFnFrom(decoy, 'foo');
  ok(extracted.includes("'real'") && !extracted.includes("'decoy'"), '주석 속 가짜 함수 대신 실제 함수 추출');

  const prefix = 'function fooBar(){ return 1; }\nfunction foo(){ return 2; }';
  eq(extractFnFrom(prefix, 'foo'), 'function foo(){ return 2; }', '접두 이름 fooBar와 정확한 foo 구분');

  const nested = 'function foo(){ return {a:1, b:{c:2, d:{e:3}}}; }';
  const nestedFoo = new Function(extractFnFrom(nested, 'foo') + '\nreturn foo;')();
  eq(JSON.stringify(nestedFoo()), JSON.stringify({ a: 1, b: { c: 2, d: { e: 3 } } }), '중첩 객체 중괄호 끝까지 함수 추출');

  const stringBrace = 'function foo(){ return "a}b{c"; }';
  const stringFoo = new Function(extractFnFrom(stringBrace, 'foo') + '\nreturn foo;')();
  eq(stringFoo(), 'a}b{c', '문자열 속 중괄호를 깊이 계산에서 제외');

  const escapedTick = 'function foo(){ return `a\\`b`; }';
  const tickFoo = new Function(extractFnFrom(escapedTick, 'foo') + '\nreturn foo;')();
  eq(tickFoo(), 'a`b', '템플릿 리터럴의 이스케이프 백틱 처리');
}

// ── judge / correctSet : 채점 정확성(가장 중요) ──────────────────────────────
const single = { verified: '② 자궁내막증', options: ['① a', '② b', '③ c', '④ d', '⑤ e'] };
eq(E.judge(single, ['②']), 'ok', '단일정답 정답');
eq(E.judge(single, ['①']), 'ng', '단일정답 오답');
eq(E.judge(single, []), 'sk', '선택 없음 → sk(무감점)');

const rtypeSingle = { verified: '⑦ 정답', options: ['①a','②b','③c','④d','⑤e','⑥f','⑦g','⑧h'] }; // 8선지 R형·단일정답
eq(E.judge(rtypeSingle, ['⑦']), 'ok', '단일정답 R형(8선지) 정답');
eq(E.isMulti(rtypeSingle), false, 'R형이어도 정답 1개면 복수정답 아님');

const multi = { verified: '복수', answers: ['②', '④'], options: ['①a','②b','③c','④d','⑤e'] };
eq(E.isMulti(multi), true, 'answers≥2 → 복수정답');
eq(E.correctSet(multi).size, 2, '복수정답 correctSet 크기 2');
eq(E.judge(multi, ['②','④']), 'ok', '복수정답 완전일치');
eq(E.judge(multi, ['④','②']), 'ok', '복수정답 순서 무관');
eq(E.judge(multi, ['②']), 'ng', '복수정답 일부만 → 오답');
eq(E.judge(multi, ['②','④','①']), 'ng', '복수정답 초과선택 → 오답');

const idxAnswers = { verified: 'x', answers: [2, 4], options: ['①a','②b','③c','④d'] };
ok(E.correctSet(idxAnswers).has('②') && E.correctSet(idxAnswers).has('④'), '인덱스 answers [2,4] → ②④');

const lostOptions = { verified: '정답 보기 소실로 마커 없음', options: ['①a','②b'] };
eq(E.correctSet(lostOptions).size, 0, '마커 없으면 correctSet 빈 set');
eq(E.judge(lostOptions, ['①']), 'sk', '확정불가(빈 correctSet) → sk(자동오답 아님)  ★6/14 수정');

const subjective = { verified: '서술형 정답', options: [] };
eq(E.judge(subjective, []), 'sk', '주관식 → sk');

// ── normMarker ───────────────────────────────────────────────────────────────
eq(E.normMarker('②'), '②', 'normMarker 마커 그대로');
eq(E.normMarker('2'), '②', 'normMarker 숫자문자열 → 마커');
eq(E.normMarker(4), '④', 'normMarker 정수 → 마커');
eq(E.normMarker('x'), null, 'normMarker 비마커 → null');
eq(E.normMarker(null), null, 'normMarker null → null');
eq(E.normMarker(21), null, 'normMarker 범위초과 → null');

// ── getQid : 제시문 같은 R형 변형이 충돌하지 않아야(통계·🚩 키) ──────────────
const q2021 = { scope: '신생아', meta: '2021 · 김철수', stem: '10개월 영아의 원시반사로 옳은 것은?' };
const q2019 = { scope: '신생아', meta: '2019 · 김철수', stem: '10개월 영아의 원시반사로 옳은 것은?' };
ok(E.getQid(q2021) !== E.getQid(q2019), '제시문 동일·연도 다른 변형 → qid 충돌 안 함  ★6/14 수정');

// ── isRoyal ──────────────────────────────────────────────────────────────────
eq(E.isRoyal({ new_expl: '【왕족】 핵심은 …' }), true, 'isRoyal 문자열');
eq(!!E.isRoyal({ new_expl: ['【왕족】 a', 'b'] }), true, 'isRoyal 불릿배열');
eq(E.isRoyal({ new_expl: '【킹왕족】 핵심' }), true, 'isRoyal 킹왕족 별칭');
eq(!!E.isRoyal({ new_expl: '일반 해설' }), false, 'isRoyal 태그없음 → false');
eq(E.bulletize('【킹왕족】 핵심'), '핵심', 'bulletize 킹왕족 별칭 제거');
eq(E.bulletize(['【킹왕족】 a', 'b']), '<ul><li>a</li><li>b</li></ul>', 'bulletize 킹왕족 불릿 제거');

// ── getProf / metaName : 교수명 '이름만' ─────────────────────────────────────
eq(E.getProf('2023 · 예시과 김철수'), '김철수', 'getProf 과/교실명 제거');
eq(E.getProf('2023 · 김철수'), '김철수', 'getProf 이미 이름만');
eq(E.metaName('2023 · 예시과 김철수'), '2023 · 김철수', 'metaName 이름만 표시');

// ── 범위 2026 담당교수 상태: Python schema.py (a)–(h) 동형 벡터 ───────────────
{
  const a = E.scopeStatus(
    '총론 · [2026 담당교수: 이몽룡·성춘향]', new Set(['임꺽정', '성춘향']));
  eq(JSON.stringify(a), JSON.stringify({
    status: 'same', weight: 1, prof2026: '이몽룡·성춘향', tokens: ['이몽룡', '성춘향'],
  }), 'scopeStatus (a) 복수 교수 중 동일 교수 우선');

  const b = E.scopeStatus('… · [2026 담당교수: 미개설 (2025 장보고)]', new Set(['장보고']));
  eq(JSON.stringify(b), JSON.stringify({
    status: 'closed', weight: 0.3, prof2026: '미개설 (2025 장보고)',
    tokens: ['미개설 (2025 장보고)'],
  }), 'scopeStatus (b) 미개설 우선');

  const cHeader = '… · [2026 담당교수: 임꺽정(세부단원 신설) · CPX 미개설]';
  const c = E.scopeStatus(cHeader, new Set(['강감찬', '유관순']));
  eq(JSON.stringify(c), JSON.stringify({
    status: 'new', weight: 0.7, prof2026: '임꺽정(세부단원 신설) · CPX 미개설',
    tokens: ['임꺽정(세부단원 신설)', 'CPX 미개설'],
  }), 'scopeStatus (c) 신설이 미개설보다 높은 weight');
  eq(JSON.stringify(E.scopeTokens(cHeader)),
     JSON.stringify(['임꺽정(세부단원 신설)', 'CPX 미개설']),
     'scopeTokens (c) 괄호를 보존한 raw 토큰');

  const unknown = { status: 'unknown', weight: 1, prof2026: '', tokens: [] };
  eq(JSON.stringify(E.scopeStatus('부록 — 2022학년도 원본 시험지', new Set(['아무개']))),
     JSON.stringify(unknown), 'scopeStatus (d) 교수란 없는 헤더');
  eq(E.scopeStatus('… · [2026 담당교수: 김구]', new Set(['안중근'])).status, 'changed',
     'scopeStatus (e) 담당교수 변경');
  eq(E.scopeStatus('… · [2026 담당교수: 김구]', new Set(['안중근'])).weight, 0.7,
     'scopeStatus (e) 변경 weight');
  eq(E.scopeStatus('… · [2026 담당교수: 김구]', new Set(['김구'])).status, 'same',
     'scopeStatus (f) 담당교수 동일');
  eq(E.scopeStatus('… · [2026 담당교수: 미정 (2025 김유신)]', new Set(['김유신'])).status,
     'unknown', 'scopeStatus (g) 미정은 과거 교수와 무관하게 unknown');
  eq(E.scopeStatus('… · [2026 담당교수: 미정 (2025 김유신)]', new Set(['김유신'])).weight,
     1, 'scopeStatus (g) 미정 weight');
  eq(E.scopeStatus('… · [2026 담당교수: 임꺽정(세부단원 신설)]', new Set(['임꺽정'])).status,
     'new', 'scopeStatus (h) 신설은 동일 교수보다 우선');

  eq(E.scopeTokenStatus('CPX 미개설', new Set(['CPX'])), 'closed',
     'scopeTokenStatus 미개설은 이름 일치보다 우선');
  eq(E.scopeTokenStatus('임꺽정(세부단원 신설)', new Set(['임꺽정'])), 'new',
     'scopeTokenStatus 괄호 안 신설은 이름 일치보다 우선');
  eq(E.scopeTokenStatus('미정 (2025 김유신)', new Set(['김유신'])), 'unknown',
     'scopeTokenStatus 괄호 제거 뒤 미정은 unknown');
  eq(E.scopeTokenStatus('김구 (2025 담당)', new Set(['김구'])), 'same',
     'scopeTokenStatus 괄호 제거 뒤 과거 교수 Set과 비교');

  eq(E.scopeStatus('… · [2026 담당교수: 김구 · 미정]', new Set(['김구'])).status, 'same',
     'scopeStatus 동률 우선순위 same > unknown');
  eq(E.scopeStatus('… · [2026 담당교수: 외부교수 · 임꺽정(신설)]', new Set()).status, 'changed',
     'scopeStatus 동률 우선순위 changed > new');
}

// ── weaknessList : 약점 가중 출제 정렬(오답률 > 🚩 > 빈출 > 미시도 > 정답) ──────
{
  const wlSrc = extractConst('ROYAL_RE') + '\n' + ['getQid', 'isRoyal', 'weaknessList'].map(extractFn).join('\n');
  const makeWL = new Function('loadStats', 'loadFlags', 'ALL_Q', wlSrc + '\nreturn weaknessList;');
  const mk = (id, stem, royal) => ({ id, scope: 's', meta: '2021 · ' + id, stem, new_expl: royal ? '【왕족】 x' : '' });
  const q1 = mk('q1', 'wrong all'), q2 = mk('q2', 'correct all'), q3 = mk('q3', 'unseen plain'),
        q4 = mk('q4', 'unseen flagged'), q5 = mk('q5', 'unseen royal', true);
  const ALL = [q3, q5, q1, q4, q2];                              // 입력 순서는 섞어둠
  const stats = {}; stats[E.getQid(q1)] = { a: 4, c: 0, e: 0 }; stats[E.getQid(q2)] = { a: 4, c: 4, e: 0 };
  const flags = new Set([E.getQid(q4)]);
  const wl = makeWL(() => stats, () => flags, ALL);
  eq(JSON.stringify(wl(5).map(q => q.id)), JSON.stringify(['q1', 'q4', 'q5', 'q3', 'q2']),
     'weaknessList 정렬: 오답 > 🚩 > 빈출 > 미시도 > 정답');
  eq(JSON.stringify(wl(2).map(q => q.id)), JSON.stringify(['q1', 'q4']), 'weaknessList N개 제한');
}

// ── SCHED 시험일 역산 복습 스케줄러 ──────────────────────────────────────────
{
  const H = 3600000, DAY = 24 * H, T = Date.parse('2026-09-08T00:00:00Z');
  const defaultSched = { v: 1, examAt: null, conf: true, todayMin: 30, font: 'M', q: {} };
  const cfgSrc = extractConst('SR_CFG');
  eq((cfgSrc.match(/;/g) || []).length, 1, 'SR_CFG 내부 세미콜론 없이 단일 문으로 추출');
  eq(cfgSrc.includes('\n'), false, 'SR_CFG 한 줄 상수 유지');
  eq(JSON.stringify(E.srDefaultSched()), JSON.stringify(defaultSched), 'srDefaultSched 기본 형상');
  const garbage = E.srNormalizeSched('garbage', {}, T);
  eq(JSON.stringify(garbage.sched), JSON.stringify(defaultSched), '문자열 sched는 전체 기본값으로 복구');
  eq(garbage.changed, true, '문자열 sched 복구는 changed=true');

  // 글자 크기(S/M/L) 화이트리스트 — 손상 저장값이 CSS 선택자로 새어 나가지 않는다
  eq(E.normFont('S'), 'S', 'normFont S 통과');
  eq(E.normFont('M'), 'M', 'normFont M 통과');
  eq(E.normFont('L'), 'L', 'normFont L 통과');
  eq(E.normFont('XX'), 'M', 'normFont 손상값 XX → M');
  eq(E.normFont('s'), 'M', 'normFont 소문자 s → M');
  eq(E.normFont(undefined), 'M', 'normFont undefined → M');
  eq(E.normFont(null), 'M', 'normFont null → M');
  eq(E.normFont(''), 'M', 'normFont 빈 문자열 → M');
  eq(E.normFont(3), 'M', 'normFont 숫자 → M');
  eq(E.normFont(E.srDefaultSched().font), 'M', 'srDefaultSched.font 는 normFont 화이트리스트와 일치');

  eq(E.srNextDue(2, T, T + 10 * DAY), T + 72 * H, 'k=2·시험 10일 전 → 72시간');
  eq(E.srNextDue(3, T, T + 2 * DAY), T + 16.8 * H, 'k=3·시험 2일 전 → 16.8시간');
  eq(E.srNextDue(0, T, T + 2 * H), T + H, 'k=0·시험 2시간 전 → 최소 간격 1시간');
  eq(E.srNextDue(0, T, T + 0.5 * H), T + 0.5 * H, 'k=0·시험 30분 전 → 남은 시간 상한');
  eq(E.srNextDue(1, T, null), T + 24 * H, '시험일 없음 → k=1 기본 24시간');
  eq(E.srNextDue(1, T, T - 1), T + 24 * H, '과거 시험일 → k=1 기본 24시간');
  eq(E.srNextDue(9, T, null), T + 168 * H, 'k>=3 → 마지막 168시간 단계');

  const base = { k: 2, l: null, d: null, hc: 0, h: [] };
  const promoted = E.srApplyResult(base, 'ok', 3, T, T + 10 * DAY, 's', false);
  eq(promoted.k, 3, '확신 정답은 k 1 증가');
  eq(promoted.d, T + 72 * H, '확신 정답 due는 증가 전 k=2로 계산');
  eq(promoted.l, T, '확신 정답 last 시각 기록');
  eq(JSON.stringify(promoted.h), JSON.stringify([[T, 'ok', 3, 's']]), '확신 정답 history 선두 기록');
  eq(JSON.stringify(base), JSON.stringify({ k: 2, l: null, d: null, hc: 0, h: [] }),
     'srApplyResult 입력 rec 비변경');

  const firstCorrect = E.srApplyResult({ k: 0, l: null, d: null, hc: 0, h: [] },
                                       'ok', 2, T, null, 's', false);
  eq(JSON.stringify([firstCorrect.k, firstCorrect.d]), JSON.stringify([1, T + 4 * H]),
     'k=0 보통 확신 정답 → k=1·4시간');
  const guessed = E.srApplyResult(base, 'ok', 1, T, null, 's', false);
  eq(JSON.stringify([guessed.k, guessed.d]), JSON.stringify([2, T + 4 * H]),
     '찍은 정답은 k 불변·4시간 후');
  const highConfidenceWrong = E.srApplyResult(base, 'ng', 3, T, null, 's', false);
  eq(JSON.stringify([highConfidenceWrong.k, highConfidenceWrong.hc, highConfidenceWrong.d]),
     JSON.stringify([0, 1, T + H]), '확신 오답은 k=0·hc 증가·1시간 후');
  const partialWrong = E.srApplyResult(base, 'ng', 2, T, null, 's', true);
  eq(JSON.stringify([partialWrong.k, partialWrong.hc, partialWrong.d]),
     JSON.stringify([1, 0, T + H]), '부분 오답은 k 한 단계 감소·1시간 후');
  eq(JSON.stringify(E.srApplyResult(base, 'sk', 2, T, null, 's', false)), JSON.stringify(base),
     'sk는 rec 완전 불변');
  eq(JSON.stringify(E.srApplyResult(base, 'un', 2, T, null, 's', false)), JSON.stringify(base),
     'un은 rec 완전 불변');
  const defaultConfidence = E.srApplyResult(base, 'ok', undefined, T, null, 's', false);
  eq(defaultConfidence.h[0][2], 2, 'conf undefined는 history에서 2로 기록');
  eq(defaultConfidence.k, 3, 'conf undefined는 적용 분기에서도 2로 취급');
  let history = base;
  for (let i = 0; i < 21; i++) history = E.srApplyResult(history, 'ok', 2, T + i, null, 's', false);
  eq(history.h.length, 20, 'history는 최근 20개로 제한');
  eq(history.h[0][0], T + 20, 'history 최신 항목이 선두');

  const mixedLegacy = E.srNormalize(undefined, { a: 12, c: 9, e: 5000 }, 'q1', T);
  eq(mixedLegacy.k, 1, '레거시 일부 정답 이력 → k=1');
  ok(mixedLegacy.d >= T + 12 * H && mixedLegacy.d <= T + 24 * H,
     '레거시 k=1 due는 해시 분산 12~24시간');
  const masteredLegacy = E.srNormalize(undefined, { a: 5, c: 5, e: 0 }, 'q2', T);
  eq(masteredLegacy.k, 3, '레거시 전부 정답 이력 → MASTER_STREAK=3 clamp');
  ok(masteredLegacy.d >= T + 84 * H && masteredLegacy.d <= T + 168 * H,
     '레거시 k=3 due는 해시 분산 84~168시간');
  eq(E.srNormalize(undefined, { a: 0, c: 0, e: 0 }, 'q0', T), null,
     '시도 없는 레거시 항목은 생성하지 않음');

  const damaged = { k: 'x', d: 'y', h: null, hc: 2 };
  const repaired = E.srNormalize(damaged, { a: 1, c: 0, e: 0 }, 'q', T);
  eq(repaired.k, 0, '손상 k만 레거시 통계로 복구');
  ok(Number.isFinite(repaired.d) && repaired.d >= T + 2 * H && repaired.d <= T + 4 * H,
     '손상 d만 k=0 해시 분산값으로 재산출');
  eq(JSON.stringify(repaired.h), '[]', '손상 h만 빈 배열로 복구');
  eq(repaired.hc, 2, '유효한 hc는 다른 필드 손상과 무관하게 보존');
  eq(JSON.stringify(E.srNormalize(damaged, { a: 1, c: 0, e: 0 }, 'q', T)), JSON.stringify(repaired),
     '같은 srNormalize 입력은 결정론적');
  const preserved = E.srNormalize({ k: 2, l: T - 1, d: T + 7, hc: 4, h: [['keep']], extra: true },
                                  { a: 1, c: 0, e: 0 }, 'preserve', T);
  eq(JSON.stringify(preserved), JSON.stringify({ k: 2, l: T - 1, d: T + 7, hc: 4, h: [['keep']], extra: true }),
     '부분 복구는 유효 필드와 미지 필드를 보존');

  const migrated = E.srNormalizeSched({ v: 1, q: {} }, { q1: { a: 2, c: 2, e: 0 } }, T);
  eq(migrated.changed, true, 'stats 합집합에서 sched 항목 생성 시 changed=true');
  eq(migrated.sched.q.q1.k, 2, '레거시 2회 전부 정답 → k=2');
  const migratedAgain = E.srNormalizeSched(migrated.sched, { q1: { a: 2, c: 2, e: 0 } }, T);
  eq(migratedAgain.changed, false, '정규화 결과 재입력은 changed=false');
  eq(JSON.stringify(migratedAgain.sched), JSON.stringify(migrated.sched),
     '재정규화해도 최초 산출한 legacy due 불변');

  eq(E.srIsGradable({ options: [] }), true, '선지 없는 주관식은 채점 가능');
  eq(E.srIsGradable({ options: ['①a'], verified: '없음' }), false,
     '선지 있고 correctSet 비면 채점 불가');
  eq(E.srIsGradable({ options: ['①a'], verified: '①' }), true,
     '선지 있고 correctSet 있으면 채점 가능');

  ok(Number.isFinite(E.srExamMs({ examAt: '2099-01-01T09:00' }, T)), '미래 examAt은 유한 ms');
  eq(E.srExamMs({ examAt: '2000-01-01T09:00' }, T), null, '과거 examAt은 null');
  eq(E.srExamMs({ examAt: null }, T), null, 'null examAt은 null');

  const unclamped = { q: {
    a: { k: 3, d: T + 168 * H }, b: { k: 0, d: T + 2 * H }, c: { k: 1, d: null },
  } };
  const unclampedSnapshot = JSON.stringify(unclamped);
  const clamped = E.srClampToExam(unclamped, T, T + 2 * DAY);
  eq(clamped.q.a.d, T + 16.8 * H, '시험 2일 전 k=3 due를 16.8시간으로 당김');
  eq(clamped.q.b.d, T + 2 * H, '이미 이른 due는 유지');
  eq(clamped.q.c.d, null, 'null due는 유지');
  eq(JSON.stringify(unclamped), unclampedSnapshot, 'srClampToExam 입력 sched 비변경');
  eq(JSON.stringify(E.srClampToExam(clamped, T, T + 2 * DAY)), JSON.stringify(clamped),
     'srClampToExam 반복 적용 멱등');
  eq(E.srClampToExam(unclamped, T, null), unclamped, '시험일 없음은 원본 sched 그대로 반환');

  const inserted = [];
  const header = { insertAdjacentElement: (_where, element) => inserted.push(element) };
  const documentMock = {
    getElementById: id => inserted.find(element => element.id === id) || null,
    createElement: () => ({ setAttribute(name, value) { this[name] = value; } }),
    querySelector: () => header,
    body: { prepend: element => inserted.push(element) },
  };
  const throwingStorage = { setItem() { throw new Error('quota'); } };
  const persistenceCode = [
    "const STAT_KEY='fixture_stats', SCHED_KEY='fixture_sched';",
    extractFn('srWarnOnce'), extractFn('saveStats'), extractFn('saveSched'),
    'return {saveStats,saveSched};',
  ].join('\n');
  const persistence = new Function('localStorage', 'document', persistenceCode)(throwingStorage, documentMock);
  eq(persistence.saveStats({}), false, 'saveStats 저장 실패는 false');
  eq(persistence.saveSched(defaultSched), false, 'saveSched 저장 실패는 false');
  eq(inserted.filter(element => element.id === 'sr-warn').length, 1,
     '연속 저장 실패에도 #sr-warn 배너는 1개');
  eq(inserted[0].textContent, '저장 실패 — 브라우저 저장공간을 확인하세요', '저장 실패 배너 문구');

  const prefsValues = ['{"future":7,"shuffle":false}', '[]', '3', '{bad'];
  const prefsStorage = { getItem: () => prefsValues.shift() };
  const loadPrefsRaw = new Function('localStorage', "const PREF_KEY='fixture_prefs';\n" +
    extractFn('loadPrefsRaw') + '\nreturn loadPrefsRaw;')(prefsStorage);
  eq(JSON.stringify(loadPrefsRaw()), JSON.stringify({ future: 7, shuffle: false }),
     'loadPrefsRaw plain object 그대로 반환');
  eq(JSON.stringify(loadPrefsRaw()), '{}', 'loadPrefsRaw 배열은 빈 객체');
  eq(JSON.stringify(loadPrefsRaw()), '{}', 'loadPrefsRaw 원시값은 빈 객체');
  eq(JSON.stringify(loadPrefsRaw()), '{}', 'loadPrefsRaw 파싱 실패는 빈 객체');

  let prefsWrite = null;
  const prefsRoundTripStorage = {
    getItem: () => '{"future":7,"shuffle":false}',
    setItem: (_key, value) => { prefsWrite = value; },
  };
  const savePrefs = new Function('localStorage', "const PREF_KEY='fixture_prefs'; let shuffleOn=true, hideInfo=true, timerOn=false;\n" +
    extractFn('loadPrefsRaw') + '\n' + extractFn('savePrefs') + '\nreturn savePrefs;')(prefsRoundTripStorage);
  savePrefs();
  eq(JSON.stringify(JSON.parse(prefsWrite)), JSON.stringify({ future: 7, shuffle: true, hide: true, timer: false }),
     'savePrefs는 미지 필드를 보존하고 기존 토글만 덮어씀');

  let loadCalls = 0;
  const earlySrRecord = new Function('loadSched', extractFn('srRecord') + '\nreturn srRecord;')(
    () => { loadCalls++; return defaultSched; });
  earlySrRecord({}, 'sk', 2, 's', false);
  earlySrRecord({}, 'un', 2, 's', false);
  eq(loadCalls, 0, 'srRecord sk/un은 loadSched 없이 즉시 반환');
}

// ── DASH2: 시험일 상태 + 범위별 숙련도 ───────────────────────────────────────
{
  const H = 3600000, T = Date.parse('2026-09-08T00:00:00Z');
  const future = E.dbExamState({ examAt: '2099-09-19T09:00' }, T);
  eq(future.state, 'future', 'dbExamState 미래 시험일 → future');
  ok(Number.isFinite(future.ms), 'dbExamState 미래 시험일 ms는 유한');
  eq(E.dbExamState({ examAt: '2000-01-01T09:00' }, T).state, 'past',
     'dbExamState 과거 시험일 → past');
  eq(E.dbExamState({ examAt: 'bad' }, T).state, 'none',
     'dbExamState 파싱 불가 시험일 → none');
  eq(E.dbExamState({ examAt: null }, T).state, 'none',
     'dbExamState null 시험일 → none');

  const makeQ = (id, scope, gradable = true) => ({
    scope, meta: '2025 · ' + id, stem: '문항 ' + id,
    options: gradable ? [] : ['① 보기'], verified: gradable ? '서술형' : '정답 마커 없음',
  });
  const allQ = [
    makeQ('a0', 'A'), makeQ('a1', 'A'), makeQ('a2', 'A', false),
    makeQ('b0', 'B'), makeQ('b1', 'B'), makeQ('c0', 'C', false),
  ];
  const qid = index => E.getQid(allQ[index]);
  const sched = { q: {
    [qid(0)]: { k: 3, d: T - 1 },
    [qid(1)]: { k: 1, d: T + H },
    [qid(2)]: { k: 3, d: T - 1 },
    [qid(3)]: { k: 3, d: null },
  } };
  const mastery = E.dbMastery(allQ, sched, T);
  eq(JSON.stringify(mastery.get('A')),
     JSON.stringify({ gradable: 2, mastered: 1, due: 1, ungradable: 1 }),
     'dbMastery A: 채점불가 분모 제외·k=3 숙련·과거 due 1개');
  eq(JSON.stringify(mastery.get('B')),
     JSON.stringify({ gradable: 2, mastered: 1, due: 0, ungradable: 0 }),
     'dbMastery B: 미래/없는 due 제외·레코드 없는 문항 k=0 취급');
  eq(JSON.stringify(mastery.get('C')),
     JSON.stringify({ gradable: 0, mastered: 0, due: 0, ungradable: 1 }),
     'dbMastery C: 채점불가만 있는 범위도 Map에 유지');
}

// ── TODAY: due 복습 + 우선순위 신규 문항 ─────────────────────────────────────
{
  const nowMs = Date.parse('2026-09-08T00:00:00Z');
  const makeQ = (id, extra = {}) => ({
    scope: 'A', scope_header: 'A · [2026 담당교수: 김철수]', meta: '2025 · 김철수 ' + id,
    years: [2025], stem: '', options: [], verified: '서술형', new_expl: '', ...extra,
  });
  const fixture = [
    makeQ('q0'),
    makeQ('q1'),
    makeQ('q2', { years: [2024] }),
    makeQ('q3', {
      scope: 'B', scope_header: 'B · [2026 담당교수: 미개설 (2025 이영희)]',
      meta: '2023 · 이영희', years: [2023],
    }),
    makeQ('q4', { years: [2025, 2024] }),
    makeQ('q5', { options: ['① 보기'], verified: '정답 보기 소실' }),
  ];
  const ctx = E.jnSubjectContext(fixture), scopeMeta = E.scopeMetaMap(fixture);
  const emptySched = { q: {} }, emptyStats = {}, emptyFlags = new Set();
  const source = extractFn('cpBuildToday');

  for (const [label, pattern] of [
    ['loadStats(', /\bloadStats\s*\(/g], ['loadSched(', /\bloadSched\s*\(/g],
    ['localStorage', /\blocalStorage\b/g], ['scopesInData(', /\bscopesInData\s*\(/g],
    ['ALL_Q', /\bALL_Q\b/g], ['SCOPE_ORDER', /\bSCOPE_ORDER\b/g],
  ]) {
    eq((source.match(pattern) || []).length, 0, `cpBuildToday 순수성: ${label} 참조 0회`);
  }

  const isolatedSource = [
    extractConst('CIRCLED'), extractConst('JN_CFG'),
    ...['getQid', 'getCorrectNum', 'normMarker', 'correctSet', 'jnHasImage',
      'jnFrequency', 'jnRecency', 'jnStudyCostFromStat', 'jnPriorityFromStat',
      'qPriority', 'jnScopeUniverse', 'jnCoverage', 'srIsGradable', 'cpBuildToday'].map(extractFn),
    'return cpBuildToday;',
  ].join('\n');
  const isolatedBuild = new Function(isolatedSource)();

  // (a) 스케줄이 비면 채점 가능한 전 문항이 priority desc, index asc 신규 후보다.
  const emptyResult = isolatedBuild(fixture, emptySched, emptyStats, emptyFlags,
    nowMs, 600, ctx, scopeMeta);
  const expectedFresh = fixture.map((q, i) => ({
    i, qid: E.getQid(q), q, priority: E.qPriority(q, ctx, scopeMeta, undefined),
  })).filter(item => E.srIsGradable(item.q))
    .sort((a, b) => (b.priority - a.priority) || (a.i - b.i))
    .map(({ i, qid }) => ({ i, qid }));
  eq(emptyResult.due.length, 0, 'TODAY (a) sched 빈 경우 due 0개');
  eq(JSON.stringify(emptyResult.fresh), JSON.stringify(expectedFresh),
    'TODAY (a) gradable 전 문항 fresh priority desc·index asc');
  eq(emptyResult.skippedUngradable, 1, 'TODAY (a) 채점불가 1문항 제외');

  // (b) 같은 경과·priority에서는 확신 오답 이력이 있는 due가 먼저다.
  const qid0 = E.getQid(fixture[0]), qid1 = E.getQid(fixture[1]);
  const dueSched = { q: {
    [qid0]: { k: 1, l: nowMs - 7200000, d: nowMs - 3600000, hc: 0, h: [] },
    [qid1]: { k: 1, l: nowMs - 7200000, d: nowMs - 3600000, hc: 1, h: [] },
  } };
  const dueResult = isolatedBuild(fixture, dueSched, emptyStats, emptyFlags,
    nowMs, 600, ctx, scopeMeta);
  eq(JSON.stringify(dueResult.due.map(pair => pair.i)), JSON.stringify([1, 0]),
    'TODAY (b) due 2개·hc>0 문항 우선');

  // (c) due는 예산을 무시해 모두 포함하고 fresh만 남은 60초 안에서 채운다.
  const budgetResult = isolatedBuild(fixture, dueSched, emptyStats, emptyFlags,
    nowMs, 60, ctx, scopeMeta);
  eq(budgetResult.due.length, 2, 'TODAY (c) 60초 예산이어도 due 전부 포함');
  ok(budgetResult.fresh.length > 0, 'TODAY (c) due 뒤 남은 예산에 fresh 포함');
  ok(budgetResult.estSec <= 60, 'TODAY (c) 이 픽스처의 due+fresh 누적 비용은 60초 이하');
  const selectedCost = [...budgetResult.due, ...budgetResult.fresh]
    .reduce((total, pair) => total + E.jnStudyCostFromStat(fixture[pair.i], emptyStats[pair.qid]), 0);
  eq(budgetResult.estSec, selectedCost, 'TODAY (c) estSec는 선택 문항 실제 비용 합');

  // (d) 격리 스코프에서 같은 배열을 다른 변수명으로 넘겨도 완전히 결정론적이다.
  const sameFixtureUnderAnotherName = fixture;
  const goldenA = isolatedBuild(fixture, dueSched, emptyStats, emptyFlags,
    nowMs, 60, ctx, scopeMeta);
  const goldenB = isolatedBuild(sameFixtureUnderAnotherName, dueSched, emptyStats, emptyFlags,
    nowMs, 60, ctx, scopeMeta);
  eq(JSON.stringify(goldenB), JSON.stringify(goldenA), 'TODAY (d) 동일 입력 두 번 호출 JSON 완전 동일');

  // (e) qid가 같아도 index가 다르면 두 문항을 각각 보존한다.
  const duplicateFixture = [makeQ('duplicate'), makeQ('duplicate')];
  const duplicateResult = isolatedBuild(duplicateFixture, emptySched, emptyStats, emptyFlags,
    nowMs, 600, E.jnSubjectContext(duplicateFixture), E.scopeMetaMap(duplicateFixture));
  eq(JSON.stringify(duplicateResult.fresh.map(pair => pair.i)), JSON.stringify([0, 1]),
    'TODAY (e) 중복 qid의 서로 다른 index 두 항목 모두 보존');
  eq(duplicateResult.fresh[0].qid, duplicateResult.fresh[1].qid,
    'TODAY (e) 보존된 두 항목은 실제 동일 qid');

  // (f) 이미 1회 학습한 due와 신규 1개를 합치면 coverage가 0.5→1이다.
  const coverageFixture = [makeQ('covered'), makeQ('new')];
  const coveredQid = E.getQid(coverageFixture[0]);
  const coverageSched = { q: {
    [coveredQid]: { k: 1, l: nowMs - 7200000, d: nowMs - 3600000, hc: 0, h: [] },
  } };
  const coverageResult = isolatedBuild(coverageFixture, coverageSched, emptyStats, emptyFlags,
    nowMs, 600, E.jnSubjectContext(coverageFixture), E.scopeMetaMap(coverageFixture));
  eq(coverageResult.coverageBefore, 0.5, 'TODAY (f) 시작 전 coverage 0.5');
  eq(coverageResult.coverageAfter, 1, 'TODAY (f) due∪fresh 뒤 coverage 1');
  for (const [label, result] of [
    ['empty', emptyResult], ['due', dueResult], ['budget', budgetResult],
    ['duplicate', duplicateResult], ['coverage', coverageResult],
  ]) {
    ok(result.coverageAfter <= 1 && result.coverageAfter >= result.coverageBefore,
      `TODAY (f) ${label} coverageAfter는 [coverageBefore, 1] 범위`);
  }

  // (g) 한 줄 복습 기록만 있고 due가 미래인 문항은 due도 fresh도 아니다.
  const reviewOnlyFixture = [makeQ('review-only')];
  const reviewOnlyQid = E.getQid(reviewOnlyFixture[0]);
  const reviewOnlySched = { q: {
    [reviewOnlyQid]: { k: 0, l: nowMs - 3600000, d: nowMs + 10800000,
      hc: 0, h: [[nowMs - 3600000, 'ok', 2, 'r']] },
  } };
  const reviewOnlyResult = isolatedBuild(reviewOnlyFixture, reviewOnlySched, {}, emptyFlags,
    nowMs, 600, E.jnSubjectContext(reviewOnlyFixture), E.scopeMetaMap(reviewOnlyFixture));
  eq(reviewOnlyResult.due.length, 0, 'TODAY (g) 미래 due라 due 제외');
  eq(reviewOnlyResult.fresh.length, 0, 'TODAY (g) rec.l·history가 있어 fresh 제외');
}

// ── JEONNAL 우선순위 엔진 ────────────────────────────────────────────────────
{
  const jnCfgSrc = extractConst('JN_CFG');
  const cfg = new Function(jnCfgSrc + '\nreturn JN_CFG;')();
  ok(jnCfgSrc.includes('COST_BLEND_MAX') && jnCfgSrc.trim().endsWith('};'), 'JN_CFG 단일 문 전체 추출');
  ok(jnCfgSrc.includes('EXPAND_120MIN_SEC:7200') && (jnCfgSrc.match(/;/g) || []).length === 1,
     'JN_CFG 확장 마지막 필드까지 하나의 세미콜론 없는 객체문으로 추출');
  eq(JSON.stringify([cfg.FREQ_WEIGHT, cfg.REC_WEIGHT]), JSON.stringify([0.53, 0.47]), 'JN_CFG 우선순위 가중치');
  eq(JSON.stringify(cfg.RECENCY_TABLE), JSON.stringify([1, 0.9, 0.8, 0.65, 0.5, 0.35, 0.2]), 'JN_CFG recency 표');
  eq(JSON.stringify([cfg.COST_BASE, cfg.COST_LEN_COEF, cfg.COST_IMAGE_BONUS]), JSON.stringify([20, 0.15, 10]), 'JN_CFG 기본 학습비용 상수');
  eq(JSON.stringify([cfg.COST_MIN, cfg.COST_MAX]), JSON.stringify([20, 120]), 'JN_CFG 기본 학습비용 clamp');
  eq(JSON.stringify([cfg.COST_BLEND_MIN_ATTEMPTS, cfg.COST_BLEND_RATIO, cfg.COST_BLEND_MIN, cfg.COST_BLEND_MAX]),
     JSON.stringify([2, 0.5, 10, 300]), 'JN_CFG 실측 blend 상수');
  eq(JSON.stringify([cfg.SCOPE_CAP_RATIO, cfg.SCOPE_EXEMPT_SHARE]), JSON.stringify([0.6, 0.6]),
     'JN_CFG scope cap·지배 비중 상수');
  eq(JSON.stringify(cfg.TIER_RATIO), JSON.stringify({ PASS: 0.7, STANDARD: 0.6 }),
     'JN_CFG PASS/STANDARD tier ratio');
  eq(JSON.stringify([cfg.BLOCK_MAX_COUNT, cfg.BLOCK_MAX_SEC]), JSON.stringify([8, 900]),
     'JN_CFG block 문항수·시간 상한');
  eq(JSON.stringify([cfg.EXPAND_30MIN_SEC, cfg.EXPAND_60MIN_SEC, cfg.EXPAND_120MIN_SEC]),
     JSON.stringify([1800, 3600, 7200]), 'JN_CFG 확장 창 초 단위 상수');

  const obstetricsAll = [
    { years: ['2012', 2013, 2014, 2015, 2016, 2017, 2018] },
    { years: [2019, '2020', 2021, 2022, 2023, 2024, 2025, 'unknown', null] },
    { years: ['2025', Infinity] },
  ];
  const musculoskeletalAll = [
    { years: ['2015', 2016, 2017, 2018, 2019, 2020] },
    { years: [2021, '2022', 2023, 2024, 2025, 'bad'] },
  ];
  eq(JSON.stringify(E.jnSubjectContext(obstetricsAll)), JSON.stringify({ subjectYearCount: 14, yearAnchor: 2025 }),
     '실데이터 A 사실과 같은 분모 14·anchor 2025 계산');
  eq(JSON.stringify(E.jnSubjectContext(musculoskeletalAll)), JSON.stringify({ subjectYearCount: 11, yearAnchor: 2025 }),
     '실데이터 B 사실과 같은 분모 11·anchor 2025 계산');

  const stableAll = [{ years: ['2019', 2021] }, { years: [2025, 'garbage'] }];
  const stableSnapshot = JSON.stringify(stableAll);
  const firstCtx = E.jnSubjectContext(stableAll), secondCtx = E.jnSubjectContext(stableAll);
  eq(JSON.stringify(secondCtx), JSON.stringify(firstCtx), '오래된 universe ctx 반복 계산 불변');
  eq(JSON.stringify(stableAll), stableSnapshot, 'jnSubjectContext 입력 ALL_Q 비변경');

  const ctx2025 = { subjectYearCount: 14, yearAnchor: 2025 };
  eq(E.jnRecency({ years: ['2025'] }, ctx2025), 1.0, 'jnRecency 2025→1.0');
  eq(E.jnRecency({ years: ['2011'] }, ctx2025), 0.20, 'jnRecency 2011→0.20');
  eq(E.jnRecency({ years: [2024] }, ctx2025), 0.90, 'jnRecency diff=1→0.90');
  eq(E.jnRecency({ years: [2023] }, ctx2025), 0.80, 'jnRecency diff=2→0.80');
  eq(E.jnRecency({ years: [2022] }, ctx2025), 0.65, 'jnRecency diff=3→0.65');
  eq(E.jnRecency({ years: [2021] }, ctx2025), 0.50, 'jnRecency diff=4→0.50');
  eq(E.jnRecency({ years: [2020] }, ctx2025), 0.35, 'jnRecency diff=5→0.35');
  eq(E.jnRecency({ years: [2026] }, ctx2025), 1.0, 'jnRecency 음수 diff는 최신 bucket으로 clamp');

  eq(E.jnFrequency({ years: [] }, ctx2025), 0, 'jnFrequency 빈 years→0');
  eq(E.jnRecency({ years: [] }, ctx2025), 0, 'jnRecency 빈 years→0');
  eq(E.jnFrequency({}, ctx2025), 0, 'jnFrequency 누락 years→0 no-throw');
  eq(E.jnRecency({}, ctx2025), 0, 'jnRecency 누락 years→0 no-throw');
  eq(E.jnFrequency({ years: [2025] }, { subjectYearCount: 0, yearAnchor: 2025 }), 0, 'jnFrequency 분모 0→0');

  const mixedYears = { years: ['2023', 'unknown', null, 'abc', '2021'] };
  close(E.jnFrequency(mixedYears, ctx2025), 2 / 14, '연도 혼합 정규화: 유한 distinct 2개만 frequency 반영');
  eq(E.jnRecency(mixedYears, ctx2025), 0.80, '연도 혼합 정규화: garbage 무시·최신 2023 사용');
  close(E.jnFrequency({ years: ['2025', 2025, '2024', 2024] }, ctx2025), 2 / 14,
        '문자열·숫자 중복 연도는 정규화 후 distinct 처리');

  const fallbackQ = { scope: 's', meta: 'm', stem: 'abcdefghij', options: ['12345', '67890'] };
  eq(E.jnStudyCost(fallbackQ), 23, 'jnStudyCost stats 폴백: 길이 20의 base 공식은 23초');

  const costSrc = jnCfgSrc + '\n'
    + ['jnHasImage', 'jnStudyCostFromStat', 'jnStudyCost'].map(extractFn).join('\n');
  const makeStudyCost = new Function('loadStats', 'getQid', costSrc + '\nreturn jnStudyCost;');
  const costWithStat = (q, stat) => {
    const stats = { [E.getQid(q)]: stat };
    return makeStudyCost(() => stats, E.getQid)(q);
  };
  const underTriedQ = { scope: 's', meta: 'a1', stem: 'x'.repeat(20), options: ['a'.repeat(10), 'b'.repeat(10)] };
  eq(costWithStat(underTriedQ, { a: 1, c: 1, e: 500000 }), 26,
     'jnStudyCost 비블렌딩: a<2이면 큰 실측값을 무시하고 base 사용');

  const normalBlendQ = { scope: 's', meta: 'normal', stem: 'abcdefghij', options: ['12345', '67890'] };
  eq(costWithStat(normalBlendQ, { a: 2, c: 1, e: 90000 }), 34,
     'jnStudyCost 블렌딩: base 23초와 평균 45초를 50:50→34초');
  const directBlendStat = { a: 2, c: 1, e: 60000 };
  const directBlendExpected = Math.round((1 - cfg.COST_BLEND_RATIO) * 23
    + cfg.COST_BLEND_RATIO * (directBlendStat.e / directBlendStat.a / 1000));
  eq(E.jnStudyCostFromStat(normalBlendQ, directBlendStat), directBlendExpected,
     'jnStudyCostFromStat base 23초·평균 30초를 기존 blend 수식으로 계산');
  const highBlendQ = { scope: 's', meta: 'high', stem: 'abcdefghij', options: ['12345', '67890'] };
  eq(costWithStat(highBlendQ, { a: 2, c: 0, e: 2400000 }), 300,
     'jnStudyCost 블렌딩 상단 clamp→300초');
  const lowBlendQ = { scope: 's', meta: 'low', stem: '', options: [] };
  eq(costWithStat(lowBlendQ, { a: 2, c: 0, e: -80000 }), 10,
     'jnStudyCost 블렌딩 하단 clamp→10초');

  eq(E.jnHasImage({ image: 'x.png' }), true, 'jnHasImage 단일 image 감지');
  eq(E.jnHasImage({ images: ['a.png', 'b.png'] }), true, 'jnHasImage images 배열 감지');
  eq(E.jnHasImage({ images: [] }), false, 'jnHasImage 빈 images 배열은 false');
  eq(E.jnHasImage({}), false, 'jnHasImage 이미지 필드 누락은 false');
  const noImageQ = { scope: 's', meta: 'image', stem: 'x'.repeat(20), options: [] };
  const imageQ = { ...noImageQ, images: ['a.png'] };
  eq(E.jnStudyCost(imageQ) - E.jnStudyCost(noImageQ), 10,
     'jnHasImage 술어가 jnStudyCost base에 정확히 10초 반영');

  eq(Number.isInteger(E.jnStudyCost({ scope: 's', meta: 'short', stem: 'x', options: [] })), true,
     'jnStudyCost 짧은 stem 결과 정수');
  eq(Number.isInteger(E.jnStudyCost({ scope: 's', meta: 'long', stem: 'x'.repeat(1000), options: [] })), true,
     'jnStudyCost 긴 stem clamp 결과 정수');
  eq(Number.isInteger(E.jnStudyCost(imageQ)), true, 'jnStudyCost 이미지 포함 결과 정수');
  eq(Number.isInteger(costWithStat(normalBlendQ, { a: 2, c: 1, e: 90000 })), true,
     'jnStudyCost stats blend 결과 정수');

  const priorityCtx = { subjectYearCount: 4, yearAnchor: 2025 };
  const priorityRecent = { scope: 's', meta: 'p1', years: ['2025', 2025, 2024], stem: 'x'.repeat(20), options: [] };
  const recentExpected = (0.53 * 0.5 + 0.47 * 1.0) * (1 / Math.log2(23 / 60 + 2));
  close(E.jnPriority(priorityRecent, priorityCtx), recentExpected,
        'jnPriority distinct frequency·최신 recency·23초 비용 공식 일치');
  const priorityOlder = { scope: 's', meta: 'p2', years: [2023], stem: 'x'.repeat(40), options: [] };
  const olderExpected = (0.53 * 0.25 + 0.47 * 0.8) * (1 / Math.log2(26 / 60 + 2));
  close(E.jnPriority(priorityOlder, priorityCtx), olderExpected,
        'jnPriority 단일 과거 연도·26초 비용 공식 일치');
  close(E.jnPriority({ scope: 's', meta: 'p3', years: [], stem: 'x', options: [] }, priorityCtx), 0,
         'jnPriority years 빈 문항은 0');

  const scopeFixture = [
    { scope: 'A', scope_header: 'A · [2026 담당교수: 김철수]', meta: '2025 · 김철수' },
    { scope: 'A', scope_header: 'A · [2026 담당교수: 김철수]', meta: '2024 · 이영희' },
    { scope: 'B', scope_header: 'B', meta: '2025 · 박민수' },
  ];
  const scopeMeta = E.scopeMetaMap(scopeFixture);
  eq(scopeMeta instanceof Map, true, 'scopeMetaMap A·B 픽스처를 Map으로 반환');
  eq(scopeMeta.size, 2, 'scopeMetaMap scope A·B를 각각 1회 집계');
  eq(scopeMeta.get('A').status, 'same', 'scopeMetaMap A는 과거 담당교수와 동일');
  eq(scopeMeta.get('B').status, 'unknown', 'scopeMetaMap B는 꼬리 없어 unknown');

  const closedQ = {
    scope: 'closed', scope_header: 'closed · [2026 담당교수: 미개설 (2025 김철수)]',
    meta: '2025 · 김철수', years: [2025], stem: 'x'.repeat(20), options: [],
  };
  const closedMeta = E.scopeMetaMap([closedQ]);
  const unweighted = E.jnPriorityFromStat(closedQ, { subjectYearCount: 1, yearAnchor: 2025 }, undefined);
  close(E.qPriority(closedQ, { subjectYearCount: 1, yearAnchor: 2025 }, closedMeta, undefined),
        unweighted * 0.3, 'qPriority 미개설 범위는 순수 우선순위의 정확히 0.3배');
}

// ── JEONNAL 계획 생성기 ──────────────────────────────────────────────────────
{
  const makeQ = (id, scope = 's', years = [2025], stemLength = 0, extra = {}) => ({
    scope, meta: '2025 · ' + id, years, stem: 'x'.repeat(stemLength), options: [],
    verified: '①', new_expl: '', ...extra,
  });
  const tieCtx = { subjectYearCount: 1, yearAnchor: 2025 };
  const indices = pairs => pairs.map(pair => pair.i);

  // 1. budget 0: base는 비고 확장 창은 정상 계산한다.
  const budgetQs = [makeQ('budget-a'), makeQ('budget-b')];
  const zeroPlan = E.jnBuildPlan(budgetQs, ['s'], tieCtx, 0, 'STANDARD');
  eq(zeroPlan.tiers.essential.length, 0, 'budget 0 → 필수 없음');
  eq(zeroPlan.tiers.recommended.length, 0, 'budget 0 → 권장 없음');
  ok(zeroPlan.warnings.some(w => w.type === 'budget_zero'), 'budget 0 → budget_zero 경고');
  eq(zeroPlan.tiers.ifTime.length, 2, 'budget 0이어도 +30분 시간남으면 창 계산');

  // 2. 최저 비용보다 작은 budget도 빈 base 계획으로 안전하게 끝난다.
  const tinyPlan = E.jnBuildPlan(budgetQs, ['s'], tieCtx, 5, 'STANDARD');
  eq(tinyPlan.tiers.essential.length, 0, 'budget 5 < COST_MIN → 필수 없음');
  eq(tinyPlan.tiers.recommended.length, 0, 'budget 5 < COST_MIN → 권장 없음·no-throw');

  // 3. priority 동점은 originalIndex 오름차순으로 결정한다.
  const tieQs = [makeQ('tie-first'), makeQ('tie-second')];
  const tiedCandidates = E.jnCandidates(tieQs, ['s'], tieCtx);
  eq(tiedCandidates[0].priority, tiedCandidates[1].priority, '동점 golden 전제: priority 완전 동일');
  eq(JSON.stringify(indices(tiedCandidates)), JSON.stringify([0, 1]), '동점 golden → originalIndex ASC');
  const tiePlan = E.jnBuildPlan(tieQs, ['s'], tieCtx, 40, 'STANDARD');
  eq(JSON.stringify(indices(tiePlan.pairs)), JSON.stringify([0, 1]), '동점 plan.pairs 정준 순서 유지');
  eq(tiePlan.tiers.essential[0].i, 0, '동점 essential 첫 문항은 더 작은 originalIndex');

  // 4. coverage universe는 왕족 여부와 무관하게 distinct 연도만 센다.
  const royalQs = [
    makeQ('royal', 'royal-scope', ['2025', 2025, 2024], 0, { new_expl: '【왕족】 핵심' }),
    makeQ('plain', 'royal-scope', [2023], 0, { new_expl: '일반 해설' }),
    makeQ('king', 'royal-scope', [2022, null, ''], 0, { new_expl: '【킹왕족】 핵심' }),
    makeQ('other', 'other-scope', [2021, 2020]),
  ];
  eq(E.jnScopeUniverse(royalQs, new Set(['royal-scope'])), 4,
     'royalOnly 분모 불변: 왕족·킹왕족·일반 문항 연도 가중치 모두 합산');
  ok(!/isRoyal|royal/i.test(extractFn('jnScopeUniverse')),
     'jnScopeUniverse 구현은 isRoyal/royal 분기를 참조하지 않음');

  // 5. marginal gain은 append-only이고 base 전량 포함이면 모두 0이다.
  const fullQs = [makeQ('full-0'), makeQ('full-1'), makeQ('full-2')];
  const fullGain = E.jnMarginalGain(fullQs, ['s'], tieCtx, 60, 'STANDARD');
  eq(JSON.stringify(fullGain), JSON.stringify({ gain30: 0, gain60: 0, gain120: 0 }),
     'base 전량 포함 → +30/+60/+120 gain 모두 0');
  const gainQs = Array.from({ length: 400 }, (_, i) => makeQ('gain-' + i, 'gain'));
  const gain = E.jnMarginalGain(gainQs, ['gain'], tieCtx, 100, 'STANDARD');
  ok(gain.gain30 >= 0 && gain.gain30 <= gain.gain60 && gain.gain60 <= gain.gain120,
     '+30⊆+60⊆+120 → coverage gain 단조 비감소');
  close(gain.gain30, 22.5, '+30분 append-only gain');
  close(gain.gain60, 45, '+60분 append-only gain');
  close(gain.gain120, 76.25, '+120분 append-only gain은 표시 base 95문항부터 최대 400문항까지');

  // 5-b. 표시 coverage는 +30분 시간남으면 tier까지 포함하므로 gain도 그 기준에서 전방 계산한다.
  // scope별 총비용은 각각 6000초(50×120, 100×60)라 share=0.5이고 cap이 실제 발동한다.
  // 90분 계획의 표시 창(120분)은 96/150, 이후 150/180/240분은 120/140/150문항이다.
  const cappedGainQs = [
    ...Array.from({ length: 50 }, (_, i) => makeQ('capped-slow-' + i, 'capped-slow', [2025], 667)),
    ...Array.from({ length: 100 }, (_, i) => makeQ('capped-fast-' + i, 'capped-fast', [2025], 267)),
  ];
  const cappedScopes = ['capped-slow', 'capped-fast'];
  const cappedPlan = E.jnBuildPlan(cappedGainQs, cappedScopes, tieCtx, 90 * 60, 'PASS');
  const cappedGain = E.jnMarginalGain(cappedGainQs, cappedScopes, tieCtx, 90 * 60, 'PASS');
  close(cappedPlan.coverage, 96 / 150, '다중 scope binding 계획의 표시 coverage는 96/150');
  ok(cappedPlan.warnings.some(w => w.type === 'scope_breakthrough'),
     '다중 scope binding 회귀 벡터에서 scope cap 관통이 실제 발생');
  for (const [window, value] of [[30, cappedGain.gain30], [60, cappedGain.gain60], [120, cappedGain.gain120]]) {
    ok(value >= 0, `+${window}분 전방 gain은 음수가 아님`);
    ok(cappedPlan.coverage + value / 100 <= 1 + 1e-9,
       `+${window}분 gain은 표시 coverage와 합쳐 100%를 넘지 않음`);
  }
  close(cappedGain.gain30, 16, '다중 scope +30분 gain = (120-96)/150×100');
  close(cappedGain.gain60, 44 / 150 * 100, '다중 scope +60분 gain = (140-96)/150×100');
  close(cappedGain.gain120, 36, '다중 scope +120분 gain = (150-96)/150×100');
  ok(cappedGain.gain30 <= cappedGain.gain60 && cappedGain.gain60 <= cappedGain.gain120,
     '다중 scope +30⊆+60⊆+120 전방 gain 단조 비감소');

  // 6. block은 8문항과 900초 상한을 각각 지킨다.
  const countQs = Array.from({ length: 9 }, (_, i) => makeQ('count-' + i, 'count'));
  const countPlan = E.jnBuildPlan(countQs, ['count'], tieCtx, 1000, 'STANDARD');
  ok(countPlan.blocks.every(block => block.pairs.length <= 8), 'block 문항수는 항상 8 이하');
  eq(JSON.stringify(countPlan.blocks.map(block => block.pairs.length)), JSON.stringify([8, 1]),
     '같은 scope·tier 9문항은 count cap으로 8+1 분할');

  const timeQs = Array.from({ length: 8 }, (_, i) => makeQ('time-' + i, 'time', [2025], 1000));
  const timeCandidates = E.jnCandidates(timeQs, ['time'], tieCtx);
  const costByIndex = new Map(timeCandidates.map(c => [c.i, c.estSeconds]));
  const timePlan = E.jnBuildPlan(timeQs, ['time'], tieCtx, 2000, 'STANDARD');
  const blockSeconds = timePlan.blocks.map(block =>
    block.pairs.reduce((total, pair) => total + costByIndex.get(pair.i), 0));
  ok(blockSeconds.every(seconds => seconds <= 900), 'block 누적 학습시간은 항상 900초 이하');
  eq(JSON.stringify(timePlan.blocks.map(block => block.pairs.length)), JSON.stringify([7, 1]),
     '120초 문항 8개는 time cap으로 7+1 분할');
  eq(JSON.stringify(blockSeconds), JSON.stringify([840, 120]), 'time cap 분할의 실제 정수 초 합계');

  // 7-a. 후보 비용 비중이 60%를 초과하는 scope는 cap 자체가 면제된다.
  const dominantQs = [
    ...Array.from({ length: 4 }, (_, i) => makeQ('dominant-' + i, 'dominant', [2025])),
    ...Array.from({ length: 2 }, (_, i) => makeQ('minor-' + i, 'minor', [2019])),
  ];
  const dominantPlan = E.jnBuildPlan(dominantQs, ['dominant', 'minor'],
    { subjectYearCount: 2, yearAnchor: 2025 }, 120, 'STANDARD');
  const dominantBase = [...dominantPlan.tiers.essential, ...dominantPlan.tiers.recommended];
  eq(dominantBase.length, 6, '지배 scope 면제로 전체 후보가 base budget에 포함');
  eq(JSON.stringify(indices(dominantBase).filter(i => i < 4)), JSON.stringify([0, 1, 2, 3]),
     '60% 초과 지배 scope의 cap 초과 문항도 skip하지 않음');
  eq(dominantPlan.warnings.filter(w => w.type === 'scope_breakthrough' && w.scope === 'dominant').length, 0,
     '지배 scope 면제는 scope_breakthrough 경고를 만들지 않음');

  // 7-b. 비지배 scope에는 관통 1개만 허용하고 다음 cap 초과 문항은 skip한다.
  const limitedQs = [
    ...Array.from({ length: 3 }, (_, i) => makeQ('limited-' + i, 'limited', [2025])),
    ...Array.from({ length: 3 }, (_, i) => makeQ('balance-' + i, 'balance', [2019])),
  ];
  const limitedCandidates = E.jnCandidates(limitedQs, ['limited', 'balance'],
    { subjectYearCount: 2, yearAnchor: 2025 });
  const limitedResult = E.jnExtendPlan(limitedCandidates,
    { includedSet: new Set(), perScopeTotal: {}, breakthroughUsed: new Set() },
    60, { limited: 0.5, balance: 0.5 });
  const limitedWarnings = limitedResult.warnings.filter(w => w.scope === 'limited');
  eq(limitedWarnings.length, 1, '비지배 scope는 scope_breakthrough 경고 정확히 1개');
  eq(limitedWarnings[0].i, 1, 'scope cap을 처음 넘긴 문항이 관통 1개 사용');
  eq(JSON.stringify([...limitedResult.includedSet].filter(i => i < 3)), JSON.stringify([0, 1]),
     '같은 scope의 후속 cap 초과 문항은 관통 소진 후 skip');
  const limitedPlan = E.jnBuildPlan(limitedQs, ['limited', 'balance'],
    { subjectYearCount: 2, yearAnchor: 2025 }, 60, 'STANDARD');
  eq(limitedPlan.warnings.filter(w => w.type === 'scope_breakthrough' && w.scope === 'limited').length, 1,
     'jnBuildPlan도 base 관통 경고를 정확히 한 번 전달');

  // 8. threshold 등호 문항은 필수이고, 미도달하면 base 전체가 필수다.
  const thresholdQs = Array.from({ length: 5 }, (_, i) => makeQ('threshold-' + i, 'threshold'));
  const standardThresholdPlan = E.jnBuildPlan(thresholdQs, ['threshold'], tieCtx, 100, 'STANDARD');
  eq(JSON.stringify(indices(standardThresholdPlan.tiers.essential)), JSON.stringify([0, 1, 2]),
     'STANDARD 60초 threshold를 정확히 만든 세 번째 문항도 필수(>=)');
  eq(JSON.stringify(indices(standardThresholdPlan.tiers.recommended)), JSON.stringify([3, 4]),
     'threshold 도달 다음 문항부터 권장');
  const unreachedQs = [makeQ('unreached-0', 'unreached'), makeQ('unreached-1', 'unreached')];
  const unreachedPlan = E.jnBuildPlan(unreachedQs, ['unreached'], tieCtx, 100, 'STANDARD');
  eq(JSON.stringify(indices(unreachedPlan.tiers.essential)), JSON.stringify([0, 1]),
     '전체 40초 < threshold 60초이면 base 포함 문항 전부 필수');
  eq(unreachedPlan.tiers.recommended.length, 0, 'threshold 미도달 시 권장 공집합');

  // 9. base에서 쓴 관통 상태는 +30분 확장에도 이어져 두 번째 관통을 막는다.
  const carryCandidates = [
    ...Array.from({ length: 10 }, (_, i) =>
      ({ i, qid: 'carry-a-' + i, scope: 'carry-a', priority: 2, estSeconds: 300 })),
    ...Array.from({ length: 10 }, (_, i) =>
      ({ i: i + 10, qid: 'carry-b-' + i, scope: 'carry-b', priority: 1, estSeconds: 300 })),
  ];
  const carryBase = E.jnExtendPlan(carryCandidates,
    { includedSet: new Set(), perScopeTotal: {}, breakthroughUsed: new Set() },
    3000, { 'carry-a': 0.5, 'carry-b': 0.5 });
  eq(carryBase.warnings.filter(w => w.scope === 'carry-a').length, 1,
     'base pass에서 carry-a 관통을 정확히 한 번 사용');
  eq(carryBase.warnings.find(w => w.scope === 'carry-a').i, 6,
     'base 1800초 scope cap 다음 300초 문항이 관통');
  const carryExpanded = E.jnExtendPlan(carryCandidates, carryBase,
    3000 + 1800, { 'carry-a': 0.5, 'carry-b': 0.5 });
  eq(carryExpanded.perScopeTotal['carry-a'], 2700,
     '+30분 cap 아래 문항만 append하고 기존 scope 합계를 보존');
  eq(carryExpanded.includedSet.has(9), false,
     '+30분 cap을 다시 넘는 carry-a 문항은 두 번째 관통 없이 skip');
  eq(carryExpanded.warnings.filter(w => w.scope === 'carry-a').length, 0,
     '확장 pass는 이미 관통한 scope에 두 번째 경고를 만들지 않음');

  // 10. PASS 0.7은 STANDARD 0.6보다 필수 경계를 한 문항 더 뒤로 둔다.
  const passThresholdPlan = E.jnBuildPlan(thresholdQs, ['threshold'], tieCtx, 100, 'PASS');
  eq(standardThresholdPlan.tiers.essential.length, 3, 'STANDARD 필수 경계 정확히 3문항');
  eq(passThresholdPlan.tiers.essential.length, 4, 'PASS 필수 경계 정확히 4문항');
  eq(JSON.stringify(indices(passThresholdPlan.tiers.recommended)), JSON.stringify([4]),
     'PASS 70초 threshold는 80초 누계 문항까지 필수');

  // 11. scope 내부 pipe는 blockId 첫/끝 pipe 파싱으로 왕복한다.
  const pipeScope = '산과|부인과';
  const pipeQs = [makeQ('pipe-0', pipeScope), makeQ('pipe-1', pipeScope)];
  const pipePlan = E.jnBuildPlan(pipeQs, [pipeScope], tieCtx, 100, 'STANDARD');
  const pipeBlock = pipePlan.blocks.find(block => block.tier === '필수');
  ok(pipeBlock.blockId.includes('|산과|부인과|'), 'blockId 중간 segment에 pipe 포함 scope 전체 보존');
  const firstPipe = pipeBlock.blockId.indexOf('|');
  const parsedTier = pipeBlock.blockId.slice(0, firstPipe);
  const rest = pipeBlock.blockId.slice(firstPipe + 1);
  const lastPipe = rest.lastIndexOf('|');
  const parsedScope = rest.slice(0, lastPipe);
  const indexPart = rest.slice(lastPipe + 1);
  eq(parsedTier, '필수', 'blockId 첫 pipe 앞 tier 왕복');
  eq(parsedScope, pipeScope, 'blockId 첫/끝 pipe 사이 scope 왕복');
  eq(JSON.stringify(indexPart.split('-').map(Number)), JSON.stringify(indices(pipeBlock.pairs)),
     'blockId 마지막 segment originalIndex 목록 왕복');

  // 12. universe가 비어도 완전한 빈 계획과 경고를 반환한다.
  const emptyPlan = E.jnBuildPlan([], ['x'], { subjectYearCount: 0, yearAnchor: null }, 60, 'STANDARD');
  eq(JSON.stringify(emptyPlan.pairs), JSON.stringify([]), '빈 universe → pairs 공집합');
  eq(JSON.stringify(emptyPlan.tiers), JSON.stringify({ essential: [], recommended: [], ifTime: [], excluded: [] }),
     '빈 universe → 네 tier 모두 공집합');
  eq(JSON.stringify(emptyPlan.blocks), JSON.stringify([]), '빈 universe → blocks 공집합');
  eq(emptyPlan.coverage, 0, '빈 universe → coverage 0');
  ok(emptyPlan.warnings.some(w => w.type === 'universe_empty'), '빈 universe → universe_empty 경고·no-throw');

  // 13. coverage 분모 0은 NaN/Infinity 대신 0이다.
  const zeroCoverage = E.jnCoverage([{ i: 0, qid: 'missing' }], [], ['x']);
  eq(zeroCoverage, 0, 'jnCoverage 분모 0 → 0');
  eq(Number.isFinite(zeroCoverage), true, 'jnCoverage 분모 0 → finite 결과');
}

// ── JEONNAL adaptive 재계획 ──────────────────────────────────────────────────
{
  const cfg = new Function(extractConst('JN_CFG') + '\nreturn JN_CFG;')();
  const previousAllQ = global.ALL_Q;
  const hadAllQ = Object.hasOwn(global, 'ALL_Q');
  const makeQ = (id, scope = 's', years = [2025], stemLength = 0) => ({
    scope, meta: '2025 · ' + id, years, stem: 'x'.repeat(stemLength), options: [],
    verified: '①', new_expl: '',
  });
  const candidate = (i, scope, priority, estSeconds) => ({
    i, qid: 'q' + i, scope, priority, estSeconds,
  });
  const pair = i => ({ i, qid: 'q' + i });
  const block = (tier, scope, ids) => ({
    blockId: tier + '|' + scope + '|' + ids.join('-'), tier, scope, pairs: ids.map(pair),
  });
  const plan = (candidates, tiers, blocks, doneBlockIds = []) => ({
    pairs: candidates.map(c => pair(c.i)),
    tiers: {
      essential: (tiers.essential || []).map(pair),
      recommended: (tiers.recommended || []).map(pair),
      ifTime: (tiers.ifTime || []).map(pair),
      excluded: (tiers.excluded || []).map(pair),
    },
    blocks, doneBlockIds, totalActiveMs: 0, baselineActiveMs: 0,
    baselineExpectedDoneMs: 0, baselineDoneBlockIds: [], revision: 0,
  });
  const indices = pairs => pairs.map(item => item.i);

  eq(cfg.DRIFT_TRIGGER_SEC, 300, 'adaptive drift trigger는 정확히 5분');
  eq(cfg.EXAM_BUFFER_SEC, 1800, 'adaptive remainingSec는 기존 시험 30분 buffer 재사용');
  eq(Object.hasOwn(cfg, 'EXAM_BUFFER_MIN'), false, '중복 EXAM_BUFFER_MIN 상수 없음');
  const commitAt = Date.parse('2030-01-01T00:00:00Z');
  eq(E.jnRemainingSec({ examAt: '2030-01-01T01:00:00Z', inputBudgetSec: 4000 },
    600000, commitAt), 1800, 'jnRemainingSec는 active budget과 commitAt 기준 시험 buffer 중 작은 값');
  eq(E.jnRemainingSec({ examAt: '2030-01-01T00:20:00Z', inputBudgetSec: 4000 },
    0, commitAt), 0, 'jnRemainingSec 시험 buffer 이후 시간이 음수면 0 clamp');

  // 1. fit만 추가하며 yearWeight+priority 동점은 originalIndex ASC로 훑는다.
  {
    global.ALL_Q = Array.from({ length: 6 }, (_, i) => makeQ('add-' + i, 'add'));
    const candidates = [
      candidate(0, 'add', 10, 20), candidate(1, 'add', 9, 10),
      candidate(2, 'add', 5, 60), candidate(3, 'add', 5, 30),
      candidate(4, 'add', 5, 30), candidate(5, 'add', 5, 25),
    ];
    const start = plan(candidates,
      { essential: [0], recommended: [1], ifTime: [5, 3, 2], excluded: [4] },
      [block('필수', 'add', [0]), block('권장', 'add', [1]), block('시간남으면', 'add', [5, 3, 2])]);
    const result = E.jnReplan(start, 85, candidates,
      { ...cfg, SCOPE_CAP_RATIO: 1 }, E.jnSubjectContext(global.ALL_Q));
    eq(JSON.stringify(indices(result.tiers.recommended)), JSON.stringify([1, 3, 5]),
      'fit만 추가: 큰 i=2를 건너뛴 뒤 동점 originalIndex ASC로 i=3, i=5 추가');
    eq(result.tiers.recommended.some(item => item.i === 4), false,
      'fit만 추가: i=3 추가 뒤 더는 맞지 않는 i=4는 제외');
    eq(result.tiers.ifTime.length, 0, '첫 adaptive pass 뒤 ifTime은 excluded로 collapse');
    eq(result.overBudget, false, '추가 경로는 essential이 맞으면 overBudget false');
  }

  // 2. 지연 경로는 priority ASC, blockId ASC로 여러 권장을 딱 fit까지 제거한다.
  {
    global.ALL_Q = Array.from({ length: 5 }, (_, i) => makeQ('remove-' + i, 'remove'));
    const candidates = [
      candidate(0, 'remove', 10, 20), candidate(4, 'remove', 4, 20),
      candidate(3, 'remove', 3, 20), candidate(1, 'remove', 1, 20),
      candidate(2, 'remove', 1, 20),
    ];
    const start = plan(candidates,
      { essential: [0], recommended: [4, 3, 1, 2], excluded: [] },
      [block('필수', 'remove', [0]), block('권장', 'remove', [4]),
       block('권장', 'remove', [3]), block('권장', 'remove', [1]), block('권장', 'remove', [2])]);
    const result = E.jnReplan(start, 60, candidates, cfg, E.jnSubjectContext(global.ALL_Q));
    eq(JSON.stringify(indices(result.tiers.recommended)), JSON.stringify([4, 3]),
      'fit까지 복수 제거: 최저 priority 동점은 blockId ASC로 i=1, i=2 제거');
    eq(JSON.stringify(indices(result.tiers.excluded).sort((a, b) => a - b)), JSON.stringify([1, 2]),
      '제거된 권장 두 문항만 excluded로 이동하고 no over-removal');
    eq(result.overBudget, false, '권장 제거로 맞출 수 있으면 overBudget false');
  }

  // 3. baseline을 현재 회계로 리셋하면 동일 상태의 두 번째 drift는 정확히 0이다.
  {
    global.ALL_Q = [makeQ('drift-0'), makeQ('drift-1')];
    const done = block('필수', 's', [0, 1]);
    const before = { blocks: [done], baselineActiveMs: 100000, baselineExpectedDoneMs: 20000 };
    const expectedDoneMs = E.jnExpectedDoneMs(before, [done.blockId]);
    eq(expectedDoneMs, 40000, 'jnExpectedDoneMs는 완료 block의 두 문항 예상시간을 ms로 합산');
    eq(E.jnComputeDrift(before, 500000, [done.blockId]), 380000,
      'jnComputeDrift는 실제 증분에서 예상 완료 증분을 뺀 ms 값');
    const postReset = { ...before, totalActiveMs: 500000, doneBlockIds: [done.blockId],
      baselineActiveMs: 500000, baselineExpectedDoneMs: expectedDoneMs,
      baselineDoneBlockIds: [done.blockId] };
    eq(E.jnComputeDrift(postReset, postReset.totalActiveMs, postReset.doneBlockIds), 0,
      '동일 drift 2회째 무변경: post-reset baseline이면 정확히 0');
  }

  // 4. 남은 필수만으로 초과하면 권장을 하나도 제거하지 않고 overBudget만 세운다.
  {
    global.ALL_Q = [makeQ('over-0'), makeQ('over-1'), makeQ('over-2')];
    const candidates = [candidate(0, 'over', 10, 70), candidate(1, 'over', 5, 20),
      candidate(2, 'over', 4, 20)];
    const start = plan(candidates,
      { essential: [0], recommended: [1, 2], excluded: [] },
      [block('필수', 'over', [0]), block('권장', 'over', [1, 2])]);
    const before = JSON.stringify(start.tiers.recommended);
    const result = E.jnReplan(start, 60, candidates, cfg, E.jnSubjectContext(global.ALL_Q));
    eq(JSON.stringify(result.tiers.recommended), before,
      '필수 초과 → 권장 tier 완전 무변경');
    eq(result.overBudget, true, '필수 초과 → overBudget true');
    eq(JSON.stringify(result.tiers.essential), JSON.stringify(start.tiers.essential),
      'adaptive는 essential membership을 절대 변경하지 않음');
  }

  // 5. 시간에는 맞아도 재평가 scope cap을 넘는 추가는 거부하고 다음 후보를 계속 본다.
  {
    global.ALL_Q = [makeQ('cap-essential', 'a'), makeQ('cap-current', 'b'),
      makeQ('cap-reject', 'a', [2025, 2024]), makeQ('cap-admit', 'b')];
    const candidates = [candidate(0, 'a', 10, 20), candidate(1, 'b', 9, 20),
      candidate(2, 'a', 8, 50), candidate(3, 'b', 7, 30)];
    const start = plan(candidates,
      { essential: [0], recommended: [1], ifTime: [2, 3], excluded: [] },
      [block('필수', 'a', [0]), block('권장', 'b', [1]), block('시간남으면', 'a', [2]),
       block('시간남으면', 'b', [3])]);
    const result = E.jnReplan(start, 100, candidates, cfg, E.jnSubjectContext(global.ALL_Q));
    eq(JSON.stringify(indices(result.tiers.recommended)), JSON.stringify([1, 3]),
      'cap 위반 i=2 거부 뒤 다음 scope의 fit 후보 i=3은 추가');
    eq(result.tiers.recommended.some(item => item.i === 2), false,
      '추가 후 scope cap 위반 후보는 시간 budget에 맞아도 거부');
  }

  // 6. 빈 후보·0초·빈 done·malformed 입력도 throw 없이 완전한 결과를 돌려준다.
  {
    global.ALL_Q = [];
    let emptyResult = null, malformedResult = null, thrown = null;
    try {
      emptyResult = E.jnReplan({ pairs: [], tiers: { essential: [], recommended: [], ifTime: [], excluded: [] },
        blocks: [], doneBlockIds: [] }, 0, [], cfg, { subjectYearCount: 0, yearAnchor: null });
      malformedResult = E.jnReplan(null, NaN, [null, {}, { i: 'bad' }], null, null);
    } catch (error) { thrown = error; }
    eq(thrown, null, 'jnReplan malformed inputs no-throw');
    for (const [label, result] of [['empty', emptyResult], ['malformed', malformedResult]]) {
      ok(result && result.tiers && ['essential', 'recommended', 'ifTime', 'excluded']
        .every(key => Array.isArray(result.tiers[key])), `jnReplan ${label} 결과는 네 tier 배열 완비`);
      ok(result && Array.isArray(result.blocks) && Number.isFinite(result.coverage)
        && typeof result.overBudget === 'boolean', `jnReplan ${label} 결과 shape 완비`);
    }
  }

  // 7. cap 분모는 remainingSec 단독이 아니라 frozenEstSec+remainingSec이다.
  {
    global.ALL_Q = [makeQ('frozen', 'a', [2025], 133), makeQ('remaining-essential', 'b'),
      makeQ('denominator-admit', 'a', [2025, 2024]), makeQ('denominator-reject', 'a')];
    eq(E.jnStudyCost(global.ALL_Q[0]), 40, 'cap 분모 전제: 완료 frozen 문항 예상시간 40초');
    const candidates = [candidate(0, 'a', 10, 40), candidate(1, 'b', 9, 20),
      candidate(2, 'a', 8, 20), candidate(3, 'a', 7, 20)];
    const frozenBlock = block('필수', 'a', [0]);
    const start = plan(candidates,
      { essential: [0, 1], recommended: [], ifTime: [2, 3], excluded: [] },
      [frozenBlock, block('필수', 'b', [1]), block('시간남으면', 'a', [2, 3])],
      [frozenBlock.blockId]);
    const result = E.jnReplan(start, 80, candidates, cfg, E.jnSubjectContext(global.ALL_Q));
    eq(JSON.stringify(indices(result.tiers.recommended)), JSON.stringify([2]),
      'frozen 40+remaining 80 분모 cap 72: scope 40→60 추가는 허용하고 80은 거부');
    ok(result.blocks.some(item => JSON.stringify(item) === JSON.stringify(frozenBlock)),
      '완료 frozen block은 blockId와 pairs를 byte-equivalent로 보존');
  }

  {
    global.ALL_Q = [makeQ('frozen-low', 'freeze'), makeQ('frozen-high', 'freeze'),
      makeQ('frozen-if-time', 'freeze'), makeQ('excluded', 'freeze')];
    const candidates = [candidate(0, 'freeze', 1, 20), candidate(1, 'freeze', 10, 20),
      candidate(2, 'freeze', 5, 20), candidate(3, 'freeze', 4, 20)];
    const frozenLow = block('권장', 'freeze', [0]);
    const frozenHigh = block('권장', 'freeze', [1]);
    const frozenIfTime = block('시간남으면', 'freeze', [2]);
    const frozenBlocks = [frozenLow, frozenHigh, frozenIfTime];
    const start = plan(candidates,
      { recommended: [0, 1], ifTime: [2], excluded: [3] }, frozenBlocks,
      frozenBlocks.map(item => item.blockId));
    const result = E.jnReplan(start, 0, candidates, cfg, E.jnSubjectContext(global.ALL_Q));
    eq(JSON.stringify(indices(result.tiers.recommended)), JSON.stringify([0, 1]),
      '완료 권장 pair는 원래 tier와 순서를 유지');
    eq(JSON.stringify(indices(result.tiers.ifTime)), JSON.stringify([2]),
      '완료 시간남으면 pair는 collapse 대상에서 제외');
    eq(JSON.stringify(result.blocks), JSON.stringify(frozenBlocks),
      '완료 block 배열은 재정렬 없이 byte-equivalent 순서로 유지');
  }

  {
    global.ALL_Q = [makeQ('status-done', 'status'), makeQ('status-remove', 'status')];
    const candidates = [candidate(0, 'status', 10, 20), candidate(1, 'status', 1, 20)];
    const current = block('필수', 'status', [0]);
    const future = block('권장', 'status', [1]);
    const shrinking = {
      ...plan(candidates, { essential: [0], recommended: [1] }, [current, future]),
      planId: 'status-shrink', status: 'active', runState: 'inBlock', pendingCommit: null,
      pausedBlock: null, nextBlockIdx: 0, perBlock: {}, totalActiveMs: 600000,
      inputBudgetSec: 1, examAt: '2099-01-02T09:30', overBudget: false,
    };
    const shrunk = E.jnBuildFinalPlanSnapshot(shrinking, current.blockId, 1000, commitAt);
    eq(shrunk.blocks.length, 1, 'adaptive 제거로 미래 block이 사라짐');
    eq(shrunk.status, 'done', 'adaptive 제거 뒤 nextBlockIdx가 새 blocks 끝이면 done');

    global.ALL_Q = [makeQ('status-current', 'status'), makeQ('status-add', 'status')];
    const growingCandidates = [candidate(0, 'status', 10, 20), candidate(1, 'status', 9, 20)];
    const growing = {
      ...plan(growingCandidates, { essential: [0], excluded: [1] }, [current]),
      planId: 'status-grow', status: 'active', runState: 'inBlock', pendingCommit: null,
      pausedBlock: null, nextBlockIdx: 0, perBlock: {}, totalActiveMs: 600000,
      inputBudgetSec: 3600, examAt: '2099-01-02T09:30', overBudget: false,
    };
    const grown = E.jnBuildFinalPlanSnapshot(growing, current.blockId, 1000, commitAt);
    ok(grown.blocks.length > 1, 'adaptive 추가로 새 미래 block이 생성됨');
    eq(grown.status, 'active', 'adaptive 추가 뒤 새 blocks가 남으면 active');
  }

  if (hadAllQ) global.ALL_Q = previousAllQ;
  else delete global.ALL_Q;

  const pendingValidatorSource = extractFn('jnValidPending');
  ok(pendingValidatorSource.includes('pending.revision!==jnPlan.revision'),
     'pending source revision은 현재 inBlock revision과 정확히 일치');
  ok(pendingValidatorSource.includes('finalPlan.revision===jnPlan.revision')
    && !pendingValidatorSource.includes('revisionValid'),
     'jnValidPending 기존 final revision 동일성 검사를 확장하지 않음');
  const commitSource = extractFn('jnCommitBlock');
  ok(commitSource.includes('const pendingRevision=finalPlanSnapshot.revision'),
     'adaptive revision은 pending 생성 시 현재 plan revision으로 동결');
}

// ── JEONNAL 계획 영속화 지문·검증 ───────────────────────────────────────────
{
  const baseQ = {
    scope: '지문 범위', meta: '2025 · 지문교수', years: [2025, '2023'],
    stem: '가'.repeat(61), options: ['보기 하나', '보기 둘둘'], verified: '①', new_expl: '',
  };
  const baseFingerprint = E.jnFingerprint(baseQ);
  eq(E.jnFingerprint(baseQ), baseFingerprint, 'jnFingerprint 동일 문항 반복 호출 결정론');
  eq(E.jnFingerprint({ ...baseQ, years: ['2023', 2025, 2025] }), baseFingerprint,
     'jnFingerprint 연도 순서·정규화 후 중복은 동일 지문');
  ok(E.jnFingerprint({ ...baseQ, years: [2025, 2024, 2023] }) !== baseFingerprint,
     'jnFingerprint distinct 유한 연도 변경 감지');
  ok(E.jnFingerprint({ ...baseQ, stem: baseQ.stem + '나' }) !== baseFingerprint,
     'jnFingerprint qid 앞 60자는 같아도 stem 길이 변경 감지');
  ok(E.jnFingerprint({ ...baseQ, options: ['보기 하나!', '보기 둘둘'] }) !== baseFingerprint,
     'jnFingerprint 한 option 길이 변경 감지');
  ok(E.jnFingerprint({ ...baseQ, image: 'figure.png' }) !== baseFingerprint,
     'jnFingerprint jnHasImage false→true 변경 감지');
  ok(Number.isInteger(baseFingerprint) && baseFingerprint >= 0 && baseFingerprint <= 0xffffffff,
     'jnFingerprint 결과는 unsigned 32-bit 정수');

  const allQ = [baseQ];
  const savedPair = { i: 0, qid: E.getQid(baseQ) };
  const dataFingerprint = E.fnv1a32(String(E.jnFingerprint(baseQ)));
  const validRecord = {
    schemaVersion: 1,
    planId: 'jn_validation_fixture',
    status: 'planning',
    runState: 'planning',
    previousMode: null,
    pausedBlock: null,
    pendingCommit: null,
    examAt: '2099-01-02T09:30',
    inputBudgetSec: 3600,
    goal: 'STANDARD',
    storageKey: 'jn_validation_storage',
    dataFingerprint,
    pairs: [savedPair],
    tiers: { essential: [savedPair], recommended: [], ifTime: [], excluded: [] },
    blocks: [{ blockId: '필수|지문 범위|0', tier: '필수', scope: '지문 범위', pairs: [savedPair] }],
    coverage: 1,
    marginalGain: { gain30: 0, gain60: 0, gain120: 0 },
    nextBlockIdx: 0,
    doneBlockIds: [],
    perBlock: {},
    totalActiveMs: 0,
    baselineActiveMs: 0,
    baselineExpectedDoneMs: 0,
    baselineDoneBlockIds: [],
    overBudget: false,
    revision: 0,
    createdAt: 1,
  };
  const cloneRecord = () => JSON.parse(JSON.stringify(validRecord));
  eq(JSON.stringify(E.jnValidatePlan(validRecord, allQ, 'jn_validation_storage')),
      JSON.stringify({ valid: true, reason: null }), 'jnValidatePlan 완전한 planning 레코드 통과');

  const missingOverBudget = cloneRecord(); delete missingOverBudget.overBudget;
  eq(E.jnValidatePlan(missingOverBudget, allQ, 'jn_validation_storage').reason, 'schema',
     'jnValidatePlan overBudget 누락 거부');
  const invalidOverBudget = cloneRecord(); invalidOverBudget.overBudget = 'false';
  eq(E.jnValidatePlan(invalidOverBudget, allQ, 'jn_validation_storage').reason, 'schema',
     'jnValidatePlan overBudget 비boolean 거부');

  for (const [status, runState] of [
    ['planning', 'planning'], ['active', 'between'], ['active', 'inBlock'],
    ['active', 'paused'], ['done', 'between'],
  ]) {
    const record = cloneRecord(); record.status = status; record.runState = runState;
    eq(E.jnValidatePlan(record, allQ, 'jn_validation_storage').valid, true,
       `jnValidatePlan 호환 상태 ${status}/${runState} 통과`);
  }

  const missing = cloneRecord(); delete missing.perBlock;
  missing.status = 'active'; missing.runState = 'planning';
  eq(E.jnValidatePlan(missing, allQ, 'wrong_storage').reason, 'schema',
     'jnValidatePlan 누락 필드는 후속 오류보다 먼저 schema');

  const invalidExamAt = cloneRecord(); invalidExamAt.examAt = '2099-02-30T09:30';
  eq(E.jnValidatePlan(invalidExamAt, allQ, 'jn_validation_storage').reason, 'schema',
     'jnValidatePlan 존재하지 않는 examAt 거부');
  const negativeBudget = cloneRecord(); negativeBudget.inputBudgetSec = -60;
  eq(E.jnValidatePlan(negativeBudget, allQ, 'jn_validation_storage').reason, 'schema',
     'jnValidatePlan 음수 inputBudgetSec 거부');
  const invalidGoal = cloneRecord(); invalidGoal.goal = 'OTHER';
  eq(E.jnValidatePlan(invalidGoal, allQ, 'jn_validation_storage').reason, 'schema',
     'jnValidatePlan PASS/STANDARD 외 goal 거부');

  const incompatible = cloneRecord();
  incompatible.status = 'active'; incompatible.runState = 'planning'; incompatible.storageKey = 'wrong_storage';
  eq(E.jnValidatePlan(incompatible, allQ, 'jn_validation_storage').reason, 'compat',
     'jnValidatePlan 비호환 status/runState는 storageKey보다 먼저 compat');
  const unknownStatus = cloneRecord(); unknownStatus.status = 'unknown';
  eq(E.jnValidatePlan(unknownStatus, allQ, 'jn_validation_storage').reason, 'compat',
     'jnValidatePlan 미지원 status는 compat');

  const wrongStorage = cloneRecord();
  wrongStorage.storageKey = 'old_subject'; wrongStorage.pairs[0].qid = 'wrong_qid';
  eq(E.jnValidatePlan(wrongStorage, allQ, 'jn_validation_storage').reason, 'storageKey',
     'jnValidatePlan storageKey 불일치는 pairs보다 먼저 storageKey');

  const wrongPair = cloneRecord();
  wrongPair.pairs[0].qid = 'wrong_qid'; wrongPair.dataFingerprint = (dataFingerprint + 1) >>> 0;
  eq(E.jnValidatePlan(wrongPair, allQ, 'jn_validation_storage').reason, 'pairs',
     'jnValidatePlan qid 불일치는 fingerprint보다 먼저 pairs');

  const wrongFingerprint = cloneRecord(); wrongFingerprint.dataFingerprint = (dataFingerprint + 1) >>> 0;
  eq(E.jnValidatePlan(wrongFingerprint, allQ, 'jn_validation_storage').reason, 'fingerprint',
     'jnValidatePlan 페어 일치 후 조작 dataFingerprint 거부');

  const largeQuestions = Array.from({ length: 657 }, (_, i) => ({
    scope: '성능', meta: '2025 · 성능' + i, years: [2025, 2024, String(2023 - i % 10)],
    stem: ('성능 지문 ' + i + ' ').repeat(8), options: ['① 보기', '② 다른 보기'], new_expl: '',
  }));
  const startedAt = process.hrtime.bigint();
  const fingerprints = largeQuestions.map(E.jnFingerprint);
  const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;
  eq(fingerprints.length, 657, '657문항 지문 전체 계산');
  ok(elapsedMs < 50, `657문항 jnFingerprint <50ms (실측 ${elapsedMs.toFixed(3)}ms)`);
}

// ── JEONNAL 계획 요약 표시 헬퍼 ─────────────────────────────────────────────
{
  const makeQ = (id, stemLength) => ({
    scope: 's', meta: '2025 · ' + id, years: [2025], stem: 'x'.repeat(stemLength), options: [],
  });
  const allQ = [makeQ('a', 0), makeQ('b', 200), makeQ('c', 1000)];
  eq(E.jnStudyCost(allQ[0]), 20, 'jnPairsSeconds 전제: 최소 비용 20초');
  eq(E.jnStudyCost(allQ[1]), 50, 'jnPairsSeconds 전제: 200자 비용 50초');

  eq(E.jnPairsSeconds([{ i: 0, qid: 'a' }, { i: 1, qid: 'b' }], allQ), 70,
     'jnPairsSeconds 블록 pairs의 est초 합산');
  eq(E.jnPairsSeconds([], allQ), 0, 'jnPairsSeconds 빈 pairs는 0초');
  eq(E.jnPairsSeconds(null, allQ), 0, 'jnPairsSeconds pairs 누락 no-throw 0초');
  eq(E.jnPairsSeconds([{ i: 99, qid: 'z' }], allQ), 0, 'jnPairsSeconds 범위 밖 인덱스 무시');
  eq(E.jnPairsSeconds([{ i: 0, qid: 'a' }], null), 0, 'jnPairsSeconds allQ 누락 no-throw 0초');

  eq(E.jnDataMinutes(79), 1.31, 'jnDataMinutes 79초 → 1.31분(2자리 절사)');
  eq(E.jnDataMinutes(0), 0, 'jnDataMinutes 0초 → 0분');
  eq(E.jnDataMinutes(-30), 0, 'jnDataMinutes 음수 방어 → 0분');
  ok(E.jnDataMinutes(59) <= 59 / 60, 'jnDataMinutes 는 실제 분을 절대 올리지 않는다');

  // data-min 합 ≤ 예산 불변식: 40초 블록 15개(합 600초)가 10분 예산에 정확히 들어차는 경계
  const blockSeconds = Array.from({ length: 15 }, () => 40);
  const budgetMin = blockSeconds.reduce((total, sec) => total + sec, 0) / 60;
  const truncatedSum = blockSeconds.reduce((total, sec) => total + E.jnDataMinutes(sec), 0);
  ok(truncatedSum <= budgetMin,
     `data-min 합 ≤ 예산 (15블록×40초, 합 ${truncatedSum.toFixed(2)}분 ≤ ${budgetMin}분)`);
  ok(blockSeconds.reduce((total, sec) => total + Math.round(sec / 60), 0) > budgetMin,
     '같은 입력에서 블록별 정수 반올림은 예산을 초과 — 절사 유지 근거');

  eq(E.jnFormatDuration(0), '약 0초', 'jnFormatDuration 0초');
  eq(E.jnFormatDuration(59), '약 59초', 'jnFormatDuration 60초 미만은 초 표기');
  eq(E.jnFormatDuration(60), '약 1분', 'jnFormatDuration 60초는 분 표기');
  eq(E.jnFormatDuration(3594), '약 60분', 'jnFormatDuration 3594초 → 약 60분');
  eq(E.jnFormatDuration(-10), '약 0초', 'jnFormatDuration 음수 방어');

  ok(/if\s*\(\s*mode\s*!==\s*['"]exam['"]\s*\|\|\s*graded\s*\)\s*return/.test(extractFn('gradeExam')),
     'gradeExam 반복 호출은 graded guard로 즉시 반환');

  const CANONICAL = /출제됩니다|출제되지 않습니다|안 나옵니다|나오지 않습니다|반드시 나옵니다|확실히|몇 ?점|점입니다/;
  const summaryStart = src.indexOf('<div id="screen-jn-summary"');
  const summaryEnd = src.indexOf('<!-- JEONNAL:END -->');
  ok(summaryStart > 0 && summaryEnd > summaryStart, '#screen-jn-summary 는 JEONNAL 구획 안에 있다');
  ok(!CANONICAL.test(src.slice(summaryStart, summaryEnd)),
     '#screen-jn-summary 정적 마크업이 §46 canonical regex 와 불일치');
  const showExplStart = src.indexOf('function showExpl(');
  const showExplEnd = src.indexOf('function clickFlag(', showExplStart);
  ok(showExplStart > 0 && showExplEnd > showExplStart, 'showExpl 정적 검사 구획을 찾는다');
  for (const name of ['showExpl', 'cpRenderToday', 'dbRenderV2', 'rrRender', 'jnRenderSummary', 'jnRenderSummaryTiers',
                      'jnRenderSummaryGain', 'jnRenderSummaryBlocks', 'jnFormatDuration']) {
    const fnSource = name === 'showExpl' ? src.slice(showExplStart, showExplEnd) : extractFn(name);
    ok(!CANONICAL.test(fnSource), `${name} 출력 문구가 §46 canonical regex 와 불일치`);
  }
  for (const label of ['필수', '권장', '시간남으면', '제외']) {
    ok(extractConst('JN_TIER_VIEW').includes(`'${label}'`), `JN_TIER_VIEW 에 ${label} 라벨 존재`);
  }
}

// ── JEONNAL 블록 커밋 순수 회계 ───────────────────────────────────────────────
{
  const stats = {
    unrelated: { a: 7, c: 5, e: 1234 },
    duplicate: { a: 2, c: 1, e: 50 },
  };
  const daily = {
    '2026-09-01': { a: 4, c: 3 },
    '2026-09-05': { a: 9, c: 8 },
  };
  const staged = [
    { i: 0, qid: 'duplicate', result: 'ok', elapsedMs: 11, day: '2026-09-05' },
    { i: 1, qid: 'duplicate', result: 'ng', elapsedMs: 19, day: '2026-09-06' },
  ];
  const statsBefore = JSON.stringify(stats), dailyBefore = JSON.stringify(daily);
  const snapshots = E.jnBuildAttemptSnapshots(stats, daily, staged);
  eq(JSON.stringify(stats), statsBefore, '커밋 snapshot 생성은 원본 stats 맵을 변경하지 않음');
  eq(JSON.stringify(daily), dailyBefore, '커밋 snapshot 생성은 원본 daily 맵을 변경하지 않음');
  eq(JSON.stringify(snapshots.statsSnapshot.unrelated), JSON.stringify(stats.unrelated),
     'statsSnapshot 무관 qid 이력 보존');
  eq(JSON.stringify(snapshots.statsSnapshot.duplicate), JSON.stringify({ a: 4, c: 2, e: 80 }),
     '중복 qid staged 두 항목을 같은 stats bucket에 각각 1회 누적');
  eq(JSON.stringify(snapshots.dailySnapshot['2026-09-01']), JSON.stringify(daily['2026-09-01']),
     'dailySnapshot 무관 날짜 이력 보존');
  eq(JSON.stringify(snapshots.dailySnapshot['2026-09-05']), JSON.stringify({ a: 10, c: 9 }),
     'staged 자체 day에 기존 bucket 누적');
  eq(JSON.stringify(snapshots.dailySnapshot['2026-09-06']), JSON.stringify({ a: 1, c: 0 }),
     '자정 교차 staged는 두 번째 day bucket을 별도 생성');

  const plan = {
    planId: 'plan', status: 'active', runState: 'inBlock', previousMode: 'exam',
    pausedBlock: { stale: true }, pendingCommit: null, blocks: [{ blockId: 'b0' }, { blockId: 'b1' }],
    nextBlockIdx: 0, doneBlockIds: [], perBlock: {}, totalActiveMs: 100,
    baselineActiveMs: 10, baselineExpectedDoneMs: 20, baselineDoneBlockIds: ['old'], revision: 3,
    untouched: { value: 1 },
  };
  const final = E.jnBuildFinalPlanSnapshot(plan, 'b0', 250, 999);
  eq(final.status, 'active', '비마지막 블록 commit은 status active 유지');
  eq(final.runState, 'between', 'commit 후 runState between');
  eq(final.nextBlockIdx, 1, 'commit 후 nextBlockIdx 1 증가');
  eq(JSON.stringify(final.doneBlockIds), JSON.stringify(['b0']), 'commit blockId doneBlockIds append');
  eq(JSON.stringify(final.perBlock.b0), JSON.stringify({ actualMs: 250, completedAt: 999 }),
     'perBlock에 동결 actualMs/completedAt 기록');
  eq(final.totalActiveMs, 350, 'totalActiveMs는 성공 후보에 actualMs 1회 가산');
  eq(final.pendingCommit, null, 'finalPlanSnapshot 자체 pendingCommit null');
  eq(final.pausedBlock, null, 'finalPlanSnapshot 자체 pausedBlock null');
  eq(JSON.stringify([final.baselineActiveMs, final.baselineExpectedDoneMs, final.baselineDoneBlockIds, final.revision]),
     JSON.stringify([10, 20, ['old'], 3]), 'todo 10 기준선·revision은 plain commit에서 불변');
  eq(JSON.stringify(final.untouched), JSON.stringify(plan.untouched), '그 외 plan 필드 carry-through');
  eq(plan.nextBlockIdx, 0, 'finalPlanSnapshot 생성은 입력 plan을 변경하지 않음');

  const lastPlan = { ...plan, blocks: [{ blockId: 'b0' }] };
  const last = E.jnBuildFinalPlanSnapshot(lastPlan, 'b0', 1, 1000);
  eq(JSON.stringify([last.status, last.runState, last.nextBlockIdx]), JSON.stringify(['done', 'between', 1]),
     '마지막 블록은 done/between 호환 상태와 blocks.length 인덱스로 전이');
}

// ── RAPID (⚡ 한 줄 복습) ─────────────────────────────────────────────────────
{
  eq(E.rrBack({ verified: '③', imp: '핵심' }), '③ — 핵심', 'rrBack 은 verified — imp 형식');
  eq(E.rrBack({ verified: '③ 답', imp: '  핵심 한 줄  ' }), '③ 답 — 핵심 한 줄', 'rrBack imp 앞뒤 공백 제거');
  eq(E.rrBack({ verified: '② 답' }), '② 답', 'imp·new_expl 둘 다 없으면 verified 단독');
  eq(E.rrBack({ verified: '② 답', new_expl: [] }), '② 답', 'new_expl 빈 배열이면 verified 단독');

  const longFirst = '가'.repeat(250);
  const arrayExpl = E.rrBack({ verified: '④ 답', new_expl: [longFirst, '둘째 항목'] });
  eq(arrayExpl, '④ 답 — ' + '가'.repeat(200), 'imp 없으면 new_expl[0] 을 200자로 자른다');
  ok(!arrayExpl.includes('둘째 항목'), 'new_expl 두 번째 항목은 뒷면에 넣지 않는다');

  eq(E.rrBack({ verified: '① 답', new_expl: '【왕족】 자주 나온 개념' }), '① 답 — 자주 나온 개념',
     'new_expl 문자열은 그 자체를 쓰고 【왕족】 태그는 제거');
  eq(E.rrBack({ verified: '① 답', new_expl: ['【킹왕족】핵심 한 줄'] }), '① 답 — 핵심 한 줄',
     '【킹왕족】 태그도 ROYAL_RE 로 제거');
  eq(E.rrBack({ verified: '【왕족】 ⑤ 답', imp: '【왕족】요점' }), '⑤ 답 — 요점',
     'verified·imp 양쪽의 왕족 태그 제거');
  eq(E.rrBack({}), '', '빈 문항 방어 — 빈 문자열');

  const longImp = '나'.repeat(240);
  eq(E.rrBack({ verified: '③', imp: longImp }), '③ — ' + longImp,
     'imp 는 자르지 않는다 — 200자 절단은 new_expl 폴백에만 적용');

  const rateSrc = extractFn('rrRate');
  ok(/srRecord\(/.test(rateSrc), 'rrRate 는 srRecord 로 _sched 만 기록');
  ok(!/recordAttempt\(/.test(rateSrc), 'rrRate 는 recordAttempt 를 호출하지 않는다(_stats 불변)');
  ok(!/saveStats\(|bumpDaily\(/.test(rateSrc), 'rrRate 는 _stats·_daily 를 직접 쓰지 않는다');

  const renderSrc = extractFn('rrRender');
  ok(!/class="opt/.test(renderSrc), 'rrRender 는 선지(.opt) 를 렌더하지 않는다');
  ok(!/q\.options/.test(renderSrc), 'rrRender 는 q.options 를 읽지 않는다');
  ok(/rrBack\(q\)/.test(renderSrc), 'rrRender 뒷면은 rrBack(q) 결과를 쓴다');
  ok(/openLightbox\(this\.src\)/.test(renderSrc), 'rrRender 이미지는 기존 라이트박스를 재사용');

  ok(/alert\('출제할 문항이 없습니다\.'\)/.test(extractFn('rrStart')), '빈 목록이면 alert 후 반환');
  ok(/ALL_Q\.indexOf\(q\)/.test(extractFn('rrPairsFromList')),
     'rrPairsFromList 는 qid 조회가 아니라 indexOf 로 인덱스를 잡는다(중복 qid 보존)');

  const rapidStart = src.indexOf('/* RAPID:START */'), rapidEnd = src.indexOf('/* RAPID:END */');
  const jeonnalStart = src.indexOf('/* JEONNAL:START */');
  ok(rapidStart > 0 && rapidEnd > rapidStart, 'RAPID 구획 마커가 짝을 이룬다');
  ok(rapidEnd < jeonnalStart, 'RAPID 구획은 JEONNAL:START 앞 — --no-jeonnal 경량 빌드에도 남는다');
  const rapidScreen = src.indexOf('<div id="screen-rapid"');
  ok(rapidScreen > 0 && rapidScreen < src.indexOf('<!-- JEONNAL:START -->'),
     '#screen-rapid 정적 마크업도 JEONNAL 구획 밖');

  const keySrc = src.slice(src.indexOf("document.addEventListener('keydown'"));
  const rapidBranch = keySrc.slice(0, keySrc.indexOf('const onQ='));
  ok(/screen-rapid'\)\.classList\.contains\('active'\)/.test(rapidBranch),
     '키보드 핸들러는 screen-rapid 를 quiz 분기보다 먼저 조기 처리');
  for (const [pattern, label] of [[/rrFlip\(\)/, 'Space→rrFlip'], [/rrRate\('ok'\)/, "1→rrRate('ok')"],
                                  [/rrRate\('ng'\)/, "2→rrRate('ng')"], [/rrNext\(\)/, 'ArrowRight→rrNext']]) {
    ok(pattern.test(rapidBranch), `한 줄 복습 키 분기 ${label}`);
  }
}

// ── 요약 ─────────────────────────────────────────────────────────────────────
console.log(`\n[test_engine] ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
