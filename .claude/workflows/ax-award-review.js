export const meta = {
  name: 'ax-award-review',
  description: 'AX Award 지원서를 심사위원 패널·디자인·사실검증 에이전트로 채점하고 개선안을 적용한다',
  whenToUse: 'ax_award 지원서 docx 를 반복 개선할 때. args = { iter: 회차번호, version: 현재 버전번호 }',
  phases: [
    { title: '데이터 확인', detail: '싼 모델로 분량 실측·사실 대조 (haiku)' },
    { title: '심사', detail: '상위 모델 3개가 동시에 100점 채점' },
    { title: '토론', detail: '세 채점표를 서로 다 보고 반박·철회·합의' },
    { title: '디자인', detail: '상위 3개가 각각 시각화 처방 (ASCII·인포그래픽·이미지)' },
    { title: '계획', detail: '초안 3개 → 서로의 초안을 보고 합의안 3개' },
    { title: '마스터 논의', detail: '상위 3개가 동시에 합의안 도출' },
    { title: '적용', detail: '합의안을 content.py·figures.py 에 반영하고 재빌드' },
  ],
}

const DIR = 'D:/project/q-agent/ax_award'
const TOP = ['opus', 'sonnet', 'fable']

// ── 매 회차 여기 두 줄만 고치고 scriptPath 로 실행한다 ─────────────────────
//    name 으로 실행하면 처음 등록된 스크립트 사본이 쓰여 수정이 반영되지 않고,
//    args 도 스크립트까지 닿지 않는다 (2·3회차에서 iter=1·ver=10 으로 떨어져
//    심사위원이 구버전 9장짜리 v10 을 보고 채점했다). 그래서 리터럴로 박는다.
const ITER = 11       // 회차 — 마스터 모델 회전에 쓴다
const VER = 44        // 이번 회차가 검토할 현재 버전 (out/ 의 최신 번호)
// ────────────────────────────────────────────────────────────────────────

let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (e) { A = {} } }
if (!A || typeof A !== 'object') A = {}

const iter = Number(A.iter) || ITER
const ver = Number(A.version) || VER
// 마스터는 한 모델이 아니다. 상위 3개가 동시에 돌며 서로의 안을 보고 합의한다.
// 파일 편집만 직렬화가 필요해서 합의안을 집행하는 손 하나를 회차마다 돌린다.
const applier = TOP[(iter - 1) % 3]
log(`${iter}회차 · v${ver} 기준 · 마스터 3개 동시 논의 · 집행 ${applier}`)

const RULES = `
반드시 지킬 절대규칙 (${DIR}/CLAUDE.md §0). 어기는 제안은 하지 마라:
1. 서식 규격(여백 위3/아래·좌·우2.54, 표너비 15.99, 좌열 2.24 우열 13.75, 제목 바탕체22 진하게밑줄,
   표 큰제목 12pt / 중간제목 11pt / 본문 10pt, I.개요 II.Process III.Tech IIII.경영효과) 변경 금지.
   'IIII' 를 'IV' 로 고치지 마라.
2. 실측 성능치는 '검색 recall@10 = 0.500 (골든 4건/색인 50건)' 단 하나뿐이다.
   정답률·환각차단율·시간단축률 등 어떤 퍼센트도 새로 만들지 마라.
3. 리소스 얘기 금지 — GPU 장수, VM 대수/코어/메모리, NAS·OBJ 용량, FP8·80GB 같은 하드웨어 수치,
   DB 서버 버전, 소요 인력 표. '인프라' 라는 단어 자체를 쓰지 마라.
   허용: 알고리즘·모델명과 선택 근거 / 투자금액·ROI / "공정이 늘어도 추가 자원을 요청하지 않는다".
4. AI 말투 금지. 정본 문장을 가져와 어절만 덜어낸다. '~하고, ~하며, ~한다' 겹쳐쌓기 금지,
   항목마다 같은 문형 반복 금지, '즉/따라서/또한' 남발 금지, 결론 재요약 문장 금지,
   '혁신적인/획기적인/강력한' 같은 형용사 금지. 능동태 단정형으로 짧게.
5. 5장을 넘지 않는다. 페이지 예산: p1 문제정의 16.9cm / p2 Process 23.8 / p3 Tech① 23.2 /
   p4 Tech② 23.9 / p5 경영효과 23.1. 10pt 한 줄 ≈ 0.42cm.
6. 정본 docs/01_과제지원서_본문.md 에 없는 주장·수치·일정을 만들지 마라.
7. **1페이지 'I. 개요 > 분류' 의 두 칸(적용시점 V_WHEN · 횡전개 범위 V_SPREAD)은 더미 확정이다.**
   수정 제안을 내지 마라. 채점에서도 제외한다 — 그 칸을 근거로 감점하거나 지적하지 마라.
   ('적용시점에 근거가 없다', '횡전개 범위가 모호하다' 류의 지적 금지). 분량 계산에만 포함한다.
`

const JUDGE = `
너희가 흉내 낼 심사위원은 이런 사람이다. 후하게 주는 사람이 아니다.

1. **깐깐하다.** 좋은 말은 세지 않는다. 문장마다 "그래서 근거가 뭐냐"를 묻는다.
   수식어("혁신적", "고도화", "체계적")는 그 자리에 근거가 없다는 신호로 읽고 감점한다.
2. **사내에 진짜 굴러가는지 본다.** 현업 심사위원이다. 다음을 안 믿는다 —
   - 정보계·기간계 접속이 실제로 뚫리는지, 조회 권한을 누가 주는지
   - 현업이 조사규칙을 정말 쓸지, 승인 버튼을 누를 시간이 있는지
   - 야간·주말에 알림이 오면 누가 받는지
   - 설비명·recipe·STEP 표기가 현장 표기와 맞는지 (틀리면 "현장을 모른다"로 통째로 신뢰를 잃는다)
   - 5장짜리 계획이 8분기 뒤에 실제로 그 상태가 되는지
3. **AI 기술력을 깊게 본다.** 사내에 ML 하는 사람이 심사에 들어온다. 다음을 반드시 캔다 —
   - 왜 그 모델인가. **기각한 대안과 기각 이유**가 없으면 "골랐다"가 아니라 "주워왔다"로 본다
   - 학습 데이터가 어디서 나오는가. 라벨은 누가 다는가. 라벨 비용을 어떻게 감당하는가
   - 평가를 어떻게 하는가. 표본 크기가 얼마인가. 그 수치가 절대 성능인지 회귀 기준선인지
   - 환각을 무엇으로 막는가. "프롬프트로 막는다"는 답은 감점이다
   - 검색이면 hard negative·리랭커·재검색을, 시계열이면 변화점 검출을, 이미지면 미지 클래스 처리를 묻는다
   - 파인튜닝한다면 무엇을 어떤 데이터로 얼마나. "SFT 한다"만 있으면 얕다고 본다
4. **모르는 것을 아는 척하면 가장 크게 깎는다.** 반대로 "이건 아직 실측 전이고 이렇게 잰다"는
   솔직한 서술은 깎지 않는다. 지어낸 수치가 하나라도 보이면 문서 전체의 신뢰를 내린다.

이 관점으로 채점하라. 지원자에게 유리하게 해석하지 마라.

**단, 채점은 배점표에만 한다.** 아래를 지켜라 — 안 그러면 회차가 겉돈다.
- **고칠 수 없는 것으로 깎지 마라.** 정본에 없는 수치를 요구하는 지적(월 판정 건수, 오판 손실액,
  현업 실사용 실적)은 '결함'이 아니라 '데이터가 없어 생긴 상한'이다. 상한은 상한으로 기록하고
  감점에서 빼라. 매 회차 같은 것으로 깎으면 점수가 영원히 안 오른다.
- **must_fix 는 이번 회차에 실제로 고칠 수 있는 것만 넣어라.** 각 항목에 어느 배점 항목이
  몇 점 오르는지 붙여라. 배점이 안 붙는 지적은 must_fix 가 아니라 관찰이다.
- **content.py 머리말의 회차별 집행 기록을 먼저 읽어라.** 지난 회차에 이미 처리된 항목을
  다시 지적하지 마라. 죽은 상수(DEAD 주석) 를 고치라는 처방도 내지 마라 — 렌더가 안 바뀐다.
- 점수를 깎을 때는 **그 자리에서 무엇을 어떻게 쓰면 몇 점 오르는지**를 함께 적어라.
  고칠 방법을 못 대면 그 감점은 근거가 약한 것이다.
`

const SCORING = `
채점 기준 (총 100점):
- Process 20 : 해결하려는 문제가 명확하고 현업 관점에서 중요도·개선 필요성이 높은가
- Process 20 : 단일 기능 개선을 넘어 업무의 시작부터 결과 활용까지 전체 프로세스를 개선·대체했는가
- Process 20 : 현업 활용도가 높고 확산 계획이 있는가
- TECH 30    : AI/Agent AI 로 풀어야 하는 문제인지 명확하고, 그 알고리즘을 고른 근거가 명확한가
- BIZ 10     : 실제 사용·파일럿·현업 검증·확산과 정량/정성 성과가 구체적인가 (신규과제는 예상 성과)
`

// 토큰 절약 — 16개 에이전트가 같은 파일을 각자 다 읽으면 회차당 수십만 토큰이 중복된다.
// haiku 가 한 번 읽어 만든 브리핑(BRIEF)을 프롬프트로 넘기고, 파일은 '확인이 필요할 때만' 열게 한다.
const FILES = `
자료는 아래 브리핑으로 이미 요약돼 있다. **브리핑으로 판단이 서면 파일을 열지 마라.**
어떤 주장을 실제로 검증해야 할 때만, 그 한 파일만 열어라.

- ${DIR}/CLAUDE.md            (절대규칙·규격·페이지예산·사실카드)
- ${DIR}/content.py           (지원서 본문 전체 — 고칠 대상)
- ${DIR}/build_docx.py        (조립 코드·페이지 배치)
- D:/project/q-agent/docs/01_과제지원서_본문.md      (정본)
- D:/project/q-agent/docs/04_과제_한장요약.md        (압축 기준)
- D:/project/q-agent/docs/03_소요자원_예산_ROI.md    (수치 산출식)
- D:/project/q-agent/docs/AI_Agent_Ablation_Study.pptx (시나리오·능력누적)
`

// 렌더 PNG 는 vision 토큰이 비싸다. 지면을 눈으로 봐야만 하는 심사·디자인에만 준다.
const RENDER = `
- ${DIR}/out/render_v${ver}/page-1..5.png — 실제 지면. Read 로 직접 열어 심사위원이 보는 그대로 확인하라.
`

const FIT_SCHEMA = {
  type: 'object',
  required: ['pages', 'overflow_cm', 'cuts'],
  properties: {
    pages: { type: 'integer' },
    overflow_cm: { type: 'number', description: '5장 예산 대비 총 초과 cm' },
    per_section: {
      type: 'array',
      items: {
        type: 'object',
        required: ['section', 'used_cm', 'budget_cm'],
        properties: {
          section: { type: 'string' }, used_cm: { type: 'number' }, budget_cm: { type: 'number' },
        },
      },
    },
    cuts: {
      type: 'array', description: '어느 상수의 어느 항목을 몇 줄 줄일지 구체 지시',
      items: {
        type: 'object',
        required: ['const_name', 'what', 'save_lines'],
        properties: {
          const_name: { type: 'string' }, what: { type: 'string' }, save_lines: { type: 'number' },
        },
      },
    },
  },
}

const FACT_SCHEMA = {
  type: 'object',
  required: ['unsupported', 'rule_violations'],
  properties: {
    unsupported: {
      type: 'array', description: '정본에 근거가 없는 수치·주장',
      items: {
        type: 'object', required: ['claim', 'where'],
        properties: { claim: { type: 'string' }, where: { type: 'string' } },
      },
    },
    rule_violations: {
      type: 'array', description: '절대규칙 위반 (리소스 언급, 새 퍼센트, AI 말투 등)',
      items: {
        type: 'object', required: ['rule', 'text', 'where'],
        properties: { rule: { type: 'string' }, text: { type: 'string' }, where: { type: 'string' } },
      },
    },
  },
}

const SCORE_SCHEMA = {
  type: 'object',
  required: ['total', 'items', 'top_fixes'],
  properties: {
    total: { type: 'integer' },
    items: {
      type: 'array',
      items: {
        type: 'object',
        required: ['criterion', 'max', 'score', 'why_lost'],
        properties: {
          criterion: { type: 'string' }, max: { type: 'integer' },
          score: { type: 'integer' }, why_lost: { type: 'string' },
        },
      },
    },
    top_fixes: {
      type: 'array', description: '점수를 가장 많이 올릴 수정 3~5개, 큰 것부터',
      items: {
        type: 'object', required: ['fix', 'gain'],
        properties: { fix: { type: 'string' }, gain: { type: 'integer' }, where: { type: 'string' } },
      },
    },
  },
}

const DEBATE_SCHEMA = {
  type: 'object',
  required: ['agree', 'disagree', 'final_total'],
  properties: {
    agree: { type: 'array', items: { type: 'string' } },
    disagree: {
      type: 'array',
      items: {
        type: 'object', required: ['point', 'my_view'],
        properties: { point: { type: 'string' }, my_view: { type: 'string' } },
      },
    },
    final_total: { type: 'integer' },
    must_fix: { type: 'array', items: { type: 'string' }, description: '패널이 합의할 만한 필수 수정' },
  },
}

const DESIGN_SCHEMA = {
  type: 'object',
  required: ['visuals', 'findings'],
  properties: {
    visuals: {
      type: 'array',
      description: '표가 아닌 시각 요소 처방. 최소 2개 이상 반드시 낼 것.',
      items: {
        type: 'object',
        required: ['page', 'kind', 'what', 'replaces', 'how'],
        properties: {
          page: { type: 'integer' },
          kind: {
            type: 'string',
            description: 'ascii | infographic | icon_row | bar_compare | gauge | flow_diagram | callout',
          },
          what: { type: 'string', description: '무엇을 보여주는 그림인가' },
          replaces: { type: 'string', description: '지금 그 자리를 차지한 표·문단 (자리를 비워야 넣는다)' },
          how: {
            type: 'string',
            description: 'ascii 면 실제 도해 텍스트를, infographic 이면 figures.py 에 추가할 함수 사양을 적어라',
          },
          gain: { type: 'string', description: '어느 배점 항목이 왜 올라가는가' },
        },
      },
    },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['page', 'problem', 'fix'],
        properties: {
          page: { type: 'integer' }, problem: { type: 'string' },
          fix: { type: 'string' }, severity: { type: 'string' },
        },
      },
    },
  },
}

const PLAN_SCHEMA = {
  type: 'object',
  required: ['edits'],
  properties: {
    edits: {
      type: 'array',
      items: {
        type: 'object',
        required: ['target', 'action', 'detail'],
        properties: {
          target: { type: 'string', description: 'content.py 의 상수명 또는 build_docx.py 함수명' },
          action: { type: 'string', description: 'shorten | replace | add | remove | reorder' },
          detail: { type: 'string' },
          reason: { type: 'string' },
        },
      },
    },
  },
}

// ─────────────────────────────────────────── 1. 데이터 확인 (싼 모델)
phase('데이터 확인')
const [fit, facts, brief] = await parallel([
  () => agent(
    `AX Award 지원서의 분량 초과를 실측해서 어디를 얼마나 줄일지 정하라.\n${FILES}\n` +
    `먼저 \`cd ${DIR} && python measure.py ${ver}\` 를 실행해 페이지별 실측치를 얻어라.\n` +
    `그다음 content.py 를 읽고, 페이지 예산(p1 문제정의 16.9cm / p2 23.8 / p3 23.2 / p4 23.9 / p5 23.1)을 ` +
    `초과한 섹션마다 어느 상수의 어느 항목을 몇 줄 줄여야 하는지 구체적으로 지목하라.\n` +
    `표 칸은 좁다 — 1cm 당 약 3글자, 10pt 한 줄 ≈ 0.42cm 로 계산하라.\n` +
    `내용의 가치가 낮은 것부터 자르되, 채점 배점이 걸린 문장은 남겨라.\n${SCORING}`,
    { label: 'fit:분량실측', phase: '데이터 확인', model: 'haiku', schema: FIT_SCHEMA }),
  () => agent(
    `AX Award 지원서 본문의 사실관계와 규칙 위반을 점검하라.\n${FILES}\n${RULES}\n` +
    `content.py 의 모든 수치·고유명사·주장이 정본(docs/01_과제지원서_본문.md, 04_한장요약, 03_ROI)에 ` +
    `실제로 있는지 대조하라. 없으면 unsupported 에 넣어라.\n` +
    `그리고 절대규칙 위반(리소스 언급, recall@10 외의 새 퍼센트, AI 말투, 5장 초과 유발)을 찾아라.\n` +
    `추측하지 말고 파일에서 확인한 것만 보고하라.`,
    { label: 'fact:사실대조', phase: '데이터 확인', model: 'haiku', schema: FACT_SCHEMA }),
  // 뒤따르는 16개 에이전트가 원본 파일을 각자 다시 읽지 않도록 브리핑을 한 번만 만든다.
  () => agent(
    `AX Award 지원서의 현재 상태 브리핑을 만들어라. 이 글 하나로 뒤 단계 에이전트들이 ` +
    `원본 파일을 열지 않고도 판단할 수 있어야 한다.\n\n` +
    `읽을 것: ${DIR}/content.py · ${DIR}/build_docx.py 의 페이지 함수부 · ${DIR}/CLAUDE.md §0·§4-B·§9\n\n` +
    `다음을 그대로 옮겨 적어라 (요약하지 말고 실제 문장을 인용하라):\n` +
    `1. 페이지별 구성 — 각 페이지에 어떤 상수가 어떤 순서로 들어가는지, 표인지 문단인지 그림인지.\n` +
    `2. content.py 의 모든 상수명과 그 안의 실제 문장. 표 상수는 행 수와 각 행의 짧은 인용.\n` +
    `3. 현재 들어가 있는 수치 전부 (recall@10, hit@1, AMI, 200억, 57.5배, 6.3일, 12.7일 등)와 그 위치.\n` +
    `4. 절대규칙 §0 의 금지 항목 요약 — 특히 리소스 금지어 목록과 쓸 수 있는 실측치 표.\n` +
    `5. figures.py 가 현재 만드는 그림 목록과 각각 어느 페이지에 들어가 있는지 (안 들어갔으면 '미사용').\n\n` +
    `길어도 좋다. 빠뜨리는 것이 훨씬 비싸다. 판단·평가는 하지 말고 사실만 옮겨라.`,
    { label: 'brief:현황브리핑', phase: '데이터 확인', model: 'haiku' }),
])

const BRIEF = `
[현재 문서 브리핑 — 아래로 판단이 서면 파일을 열지 마라]
${brief || '(브리핑 생성 실패 — 필요한 파일을 직접 열어라)'}
`

log(`분량: ${fit ? fit.pages + '장, 초과 ' + fit.overflow_cm + 'cm' : '실측 실패'} / ` +
    `사실검증: 미근거 ${facts ? facts.unsupported.length : '?'}건, 규칙위반 ${facts ? facts.rule_violations.length : '?'}건`)

// ─────────────────────────────────────────── 2. 심사 (상위 3개 동시 채점 — 배리어)
phase('심사')
const rawScores = await parallel(TOP.map((m) => () => agent(
  `너는 사내 AX 경진대회 심사위원이다. 아래 지원서를 채점 기준대로 냉정하게 채점하라.\n` +
  `${BRIEF}\n${FILES}\n${RENDER}\n${JUDGE}\n${SCORING}\n` +
  `본문 내용은 위 브리핑에 다 있다. 하지만 **렌더 이미지는 반드시 직접 열어라** — ` +
  `심사위원은 지면을 보지 소스를 보지 않는다.\n` +
  `후하게 주지 마라. 감점 사유를 구체적으로 쓰고, 점수를 가장 많이 올릴 수정을 큰 것부터 제시하라.\n` +
  `${RULES}`,
  { label: `심사:${m}`, phase: '심사', model: m, schema: SCORE_SCHEMA })))

const board = TOP.map((m, i) => ({ 심사위원: m, 채점: rawScores[i] })).filter(x => x.채점)
log(`1차 채점 ${board.map(b => `${b.심사위원} ${b.채점.total}`).join(' / ')}`)

// ─────────────────────────────────────────── 3. 토론 (셋이 서로의 채점을 보고)
phase('토론')
const debates = (await parallel(TOP.map((m, i) => () => agent(
  `너는 심사위원 ${m} 이다. 셋이 같은 지원서를 각자 채점했고, 이제 **한 자리에서 토론한다**.\n\n` +
  `[세 심사위원의 채점표 전문]\n${JSON.stringify(board)}\n\n` +
  `네 채점은 ${rawScores[i] ? rawScores[i].total : '?'}점이었다.\n` +
  `다른 두 사람의 채점표를 실제로 읽고 다음을 하라:\n` +
  `1. 다른 사람이 짚었는데 네가 놓친 것 — 인정하고 agree 에 넣어라.\n` +
  `2. 다른 사람이 과하게 깎았거나 사실을 잘못 본 것 — disagree 에 넣고 근거를 대라. ` +
  `파일을 다시 열어 확인한 뒤 반박하라. 인상으로 반박하지 마라.\n` +
  `3. 네 원 채점이 틀렸으면 스스로 철회하고 점수를 조정하라. 철회도 disagree 에 적어라.\n` +
  `4. **규칙상 고칠 수 없는 것으로 감점하지 마라.** 정본에 없는 수치를 넣으라는 요구는 ` +
  `규칙 위반이므로, 그런 항목은 '고칠 수 있는 결함'이 아니라 '데이터가 없어 생긴 상한'으로 분류하라.\n` +
  `5. 셋이 합의할 만한 필수 수정만 must_fix 에 남겨라. 셋 중 둘 이상이 지목한 것이 우선이다.\n\n` +
  `${BRIEF}\n${FILES}\n${JUDGE}\n${SCORING}\n${RULES}`,
  { label: `토론:${m}`, phase: '토론', model: m, schema: DEBATE_SCHEMA })))).filter(Boolean)

const avg = debates.length
  ? Math.round(debates.reduce((s, d) => s + (d.final_total || 0), 0) / debates.length)
  : 0
log(`토론 후 평균 ${avg}점 (${debates.map(d => d.final_total).join(' / ')})`)

// ─────────────────────────────────────────── 4. 디자인 (상위 3개 동시)
phase('디자인')

const VISUAL_BRIEF = `
지금 이 지원서는 **전 페이지가 표로만 채워져 있다.** 심사위원 눈에 다 똑같아 보이고 아무것도 안 남는다.
네 임무는 표 지적이 아니라 **표를 무엇으로 바꿀지 처방하는 것**이다.

쓸 수 있는 수단은 이미 코드에 다 있다:
1. **인포그래픽 PNG** — ${DIR}/figures.py 가 PIL 로 그린다. 이미 3개 있다
   (orchestration 구조도 / time_compare 시간대비 막대 / action_ladder 조치 게이지).
   ${DIR}/out/fig/*.png 를 Read 로 열어 실물을 확인하라.
   새 그림이 필요하면 figures.py 에 추가할 함수 사양(크기·요소·배치)을 how 에 적어라.
2. **ASCII 도해** — build_docx.py 의 Cell.mono(lines) 로 넣는다. 바탕체는 고정폭이라 자리가 맞는다.
   how 에 실제 도해 텍스트를 그대로 적어라. 박스·화살표·트리 구조에 적합하다.
3. **아이콘 행·게이지·콜아웃** — 표 대신 큰 숫자 하나와 한 줄 설명, ●○ 게이지, 붉은 테두리 강조 박스.

넣으려면 반드시 그 자리의 표나 문단을 **먼저 비워야 한다** (5장 예산이 이미 꽉 찼다).
replaces 에 무엇을 걷어낼지 반드시 적어라. 자리 없이 "추가하라"는 처방은 쓸모없다.

**표를 없애라는 뜻이 아니다.** 표는 양식·정렬·항목 대응을 보여주는 데 여전히 필요하다.
문제는 지금 **처음부터 끝까지 표뿐이라 다섯 장이 다 똑같아 보인다**는 것이다.
표는 표대로 두되, 아래 세 종류가 **각각 최소 하나씩은** 지면에 있어야 한다:

  (가) **ASCII 텍스트 시각화** — 박스·화살표·트리. 코어 흐름, 3층 분기, 선순환 루프처럼
       "무엇이 무엇으로 흘러가는가"는 표보다 도해가 낫다. how 에 실제 도해 텍스트를 그려서 적어라.
       예:  ┌─ Chat ─┐        ┌──────────┐
            │        ├──────▶ │ 마스터   │ ──▶ …
            └─ 감지 ─┘        └──────────┘
  (나) **flow diagram / 인포그래픽 PNG** — figures.py 에 함수로 추가한다. 단계 흐름, 분기,
       비교 막대, 게이지, 큰 숫자 콜아웃. how 에 크기·요소·배치를 사양으로 적어라.
  (다) **강조 블록** — 큰 숫자 하나 + 한 줄, 붉은 테두리 콜아웃, ●○ 게이지 같은 비표 요소.

visuals 를 **최소 3개 이상** 내되 위 (가)·(나)·(다)가 각각 하나씩은 들어가게 하라.
표를 다른 표로 바꾸는 처방은 내지 마라 — 그건 이미 4회차 동안 반복했고 점수가 안 올랐다.
`

const designs = await parallel(TOP.map((m) => () => agent(
  `너는 문서 디자인 검토자다. AX Award 지원서의 실제 지면을 보고 시각화를 처방하라.\n` +
  `${BRIEF}\n${RENDER}\n` +
  `본문 내용은 브리핑에 있다. **렌더 PNG 5장은 반드시 직접 열어라** — 지면을 봐야 시각화를 처방한다.\n` +
  `${VISUAL_BRIEF}\n` +
  `findings 에는 레이아웃 결함만 적어라 — 글자 잘림, 페이지 쪼개짐, 반쯤 빈 페이지, ` +
  `한 칸만 4~5줄로 터지는 열 너비, 강조 남발, 하단 여유 불균형.\n\n` +
  `서식 규격 자체는 못 바꾼다. 아래 규칙 안에서만 처방하라.\n${RULES}\n${SCORING}`,
  { label: `디자인:${m}`, phase: '디자인', model: m, schema: DESIGN_SCHEMA })))

const designBoard = TOP.map((m, i) => ({ 작성자: m, 처방: designs[i] })).filter(x => x.처방)
log(`디자인 초안 — 처방 ${designBoard.map(d => (d.처방.visuals || []).length).join('/')}건`)

// 디자인 토론 — 셋이 서로의 처방을 보고 하나로 좁힌다
const designFinal = (await parallel(TOP.map((m) => () => agent(
  `너는 디자인 검토자 ${m} 이다. 셋이 각자 시각화를 처방했고 이제 **서로의 처방을 보고 논의한다**.\n\n` +
  `[세 사람의 처방 전문]\n${JSON.stringify(designBoard)}\n\n` +
  `할 일:\n` +
  `1. 셋 중 둘 이상이 같은 자리를 지목했으면 그것부터 채택한다.\n` +
  `2. 같은 자리에 서로 다른 그림을 처방했으면 하나로 정하라 — 심사위원 눈이 오래 머무는 쪽이다.\n` +
  `3. 지면 수지를 맞춰라. 넣는 그림마다 replaces 에 걷어낼 표·문단을 반드시 짝지어라. ` +
  `5장 예산이 이미 꽉 차 있어 자리 없는 처방은 무효다.\n` +
  `4. 실현 불가능한 처방은 빼라 — figures.py 는 PIL 로 도형·텍스트·화살표만 그린다. ` +
  `사진·아이콘 폰트·외부 이미지는 못 쓴다.\n` +
  `5. 최종 visuals 는 이번 회차에 실제로 만들 것만 남겨라. 욕심내면 5장이 깨진다.\n\n` +
  `${BRIEF}\n${RENDER}\n${RULES}\n${SCORING}`,
  { label: `디자인토론:${m}`, phase: '디자인', model: m, schema: DESIGN_SCHEMA })))).filter(Boolean)

const design = { visuals: [], findings: [] }
for (const d of (designFinal.length ? designFinal : designs.filter(Boolean))) {
  design.visuals.push(...(d.visuals || []))
  design.findings.push(...(d.findings || []))
}
log(`디자인 토론 후 — 시각화 ${design.visuals.length}건 / 레이아웃 ${design.findings.length}건`)

// ─────────────────────────────────────────── 5. 개선 계획 (상위 3개)
phase('계획')
const ctx = `
[분량 실측] ${JSON.stringify(fit)}
[사실·규칙 점검] ${JSON.stringify(facts)}
[심사 패널] 평균 ${avg}점 — ${JSON.stringify(debates)}
[디자인] ${JSON.stringify(design)}
`
// 1라운드 — 각자 초안 (배리어)
const drafts = await parallel(TOP.map((m) => () => agent(
  `AX Award 지원서를 다음 회차에서 어떻게 고칠지 실행 가능한 편집 계획을 써라.\n` +
  `${BRIEF}\n${FILES}\n${RULES}\n${SCORING}\n\n` +
  `이번 회차 진단:\n${ctx}\n\n` +
  `content.py 의 상수 단위로, 무엇을 어떻게 바꿀지 구체적으로 지시하라. ` +
  `"보강하라" 같은 추상적 지시 금지 — 실제 문장이나 줄 수를 적어라.\n` +
  `분량 초과가 있으면 줄이는 편집을 반드시 포함하라. 5장을 넘기면 그 자체로 실격이다.`,
  { label: `계획초안:${m}`, phase: '계획', model: m, schema: PLAN_SCHEMA })))

const draftBoard = TOP.map((m, i) => ({ 작성자: m, 계획: drafts[i] })).filter(x => x.계획)

// 2라운드 — 서로의 초안을 다 보고 다시 쓴다
const plans = await parallel(TOP.map((m, i) => () => agent(
  `너는 계획 작성자 ${m} 이다. 셋이 각자 초안을 냈고, 이제 **서로의 초안을 보고 논의한다**.\n\n` +
  `[세 사람의 초안 전문]\n${JSON.stringify(draftBoard)}\n\n` +
  `네 초안보다 다른 사람 안이 나은 항목은 그대로 가져와라. 자기 안을 고집하지 마라.\n` +
  `다른 안이 규칙을 어기거나 지면을 초과시키면 빼라.\n` +
  `셋이 같은 자리를 서로 다르게 고치라고 하면 하나로 정하라 — 채점 배점이 큰 쪽이다.\n` +
  `**지면 수지를 맞춰라.** 5장이 이미 꽉 찼다. 넣는 만큼 같은 페이지에서 빼는 편집을 짝지어 적어라.\n\n` +
  `${BRIEF}\n${FILES}\n${RULES}\n${SCORING}\n\n이번 회차 진단:\n${ctx}`,
  { label: `계획합의:${m}`, phase: '계획', model: m, schema: PLAN_SCHEMA })))

// ─────────────────────────────────────────── 6. 마스터 논의 (상위 3개 동시)
phase('마스터 논의')

const CONSENSUS_SCHEMA = {
  type: 'object',
  required: ['agreed', 'rejected'],
  properties: {
    agreed: {
      type: 'array',
      description: '세 안을 대조해 최종 실행할 편집. 우선순위 순.',
      items: {
        type: 'object',
        required: ['target', 'action', 'detail', 'frees_or_costs_cm'],
        properties: {
          target: { type: 'string', description: 'content.py 상수 / figures.py 함수 / build_docx.py 함수' },
          action: { type: 'string', description: 'shorten | replace | add | remove | reorder | visualize' },
          detail: { type: 'string', description: '실제 문장·줄 수·그림 사양까지. 추상 지시 금지' },
          frees_or_costs_cm: { type: 'number', description: '지면을 비우면 음수, 먹으면 양수' },
          why: { type: 'string' },
        },
      },
    },
    rejected: {
      type: 'array',
      description: '다른 두 안에서 나왔지만 버린 것과 그 이유',
      items: {
        type: 'object', required: ['what', 'why_not'],
        properties: { what: { type: 'string' }, why_not: { type: 'string' } },
      },
    },
    net_cm: { type: 'number', description: 'agreed 전체의 지면 순증감. 0 이하여야 5장이 유지된다' },
  },
}

const planCtx = `${ctx}\n[세 개의 개선 계획]\n${JSON.stringify(plans.filter(Boolean))}`

const consensus = await parallel(TOP.map((m) => () => agent(
  `너는 마스터 에이전트 ${m} 이다. 지금 상위 모델 셋이 **동시에** 같은 자료를 보고 논의한다.\n` +
  `세 개의 개선 계획과 세 개의 디자인 처방이 이미 나와 있다. 네 일은 새 안을 또 내는 것이 아니라 ` +
  `**셋을 대조해 실행할 것 하나로 좁히는 것**이다.\n\n` +
  `${BRIEF}\n${FILES}\n${RULES}\n${SCORING}\n\n${planCtx}\n\n` +
  `판단 기준:\n` +
  `1. 셋 중 둘 이상이 같은 것을 지목했으면 우선 채택한다.\n` +
  `2. 충돌하면 채점 배점이 큰 쪽을 택한다. 근거를 why 에 적어라.\n` +
  `3. 정본에 근거가 없거나 절대규칙을 어기는 제안은 rejected 로 보내라 — 점수가 오를 것 같아도 버린다.\n` +
  `4. **지면 수지를 맞춰라.** 5장 예산은 이미 꽉 찼다. 무언가 넣으려면 같은 페이지에서 같은 분량을 ` +
  `먼저 비워야 한다. net_cm 이 0 이하가 되게 짜라. 행 높이·여백·글자 크기로 자리를 만드는 것은 금지다.\n` +
  `4-B. **배점 이득 순으로 줄 세워라.** 같은 1cm 를 쓸 때 점수가 더 오르는 쪽을 먼저 넣는다. ` +
  `Process 60 · TECH 30 · BIZ 10 이므로, 지면이 하나뿐이면 Process 칸을 먼저 채운다. ` +
  `점수가 안 걸린 서술은 지면을 비우는 쪽(제거 대상)으로 분류하라.\n` +
  `5. 시각화 처방(visuals)은 표를 그림으로 바꾸는 것이므로 우선순위를 높게 두되, ` +
  `replaces 에 적힌 자리를 실제로 비우는 편집을 agreed 에 함께 넣어라.`,
  { label: `마스터논의:${m}`, phase: '마스터 논의', model: m, schema: CONSENSUS_SCHEMA })))

const consBoard = TOP.map((m, i) => ({ 마스터: m, 합의안: consensus[i] })).filter(x => x.합의안)
log(`마스터 1차 — 채택 ${consBoard.map(c => (c.합의안.agreed || []).length).join('/')}건`)

// 마스터 토론 — 셋이 서로의 합의안을 보고 최종본으로 좁힌다
const cons = (await parallel(TOP.map((m) => () => agent(
  `너는 마스터 ${m} 이다. 셋이 각자 합의안을 냈고 이제 **서로의 합의안을 보고 최종 논의를 한다**.\n` +
  `이번이 마지막 판단이다. 이 뒤로는 집행자가 그대로 실행한다.\n\n` +
  `[세 마스터의 합의안 전문]\n${JSON.stringify(consBoard)}\n\n` +
  `할 일:\n` +
  `1. 셋 중 둘 이상이 채택한 편집만 agreed 에 남겨라. 하나만 낸 것은 지면이 남을 때만 넣어라.\n` +
  `2. 셋이 서로 다르게 고치라는 자리는 하나로 정하라. 근거를 why 에 적어라.\n` +
  `3. **net_cm 을 반드시 0 이하로 맞춰라.** 이 숫자가 양수면 5장이 깨지고 회차가 통째로 헛돈다.\n` +
  `4. 규칙 위반·정본 미근거는 rejected 로 보내라. 점수가 오를 것 같아도 버린다.\n` +
  `5. 집행자가 그대로 실행할 수 있게 detail 을 구체적으로 써라 — 실제 문장, 줄 수, 그림 사양.\n\n` +
  `${BRIEF}\n${RULES}\n${SCORING}`,
  { label: `마스터토론:${m}`, phase: '마스터 논의', model: m, schema: CONSENSUS_SCHEMA })))).filter(Boolean)

log(`마스터 토론 후 — 최종 채택 ${cons.map(c => (c.agreed || []).length).join('/')}건, ` +
    `순증감 ${cons.map(c => c.net_cm).join(' / ')}cm`)

// ─────────────────────────────────────────── 7. 집행 (합의안을 파일에 반영)
phase('적용')
const applied = await agent(
  `너는 ${iter}회차의 집행자다. 마스터 셋이 동시에 논의해 낸 **세 개의 합의안**이 아래에 있다.\n` +
  `새로 판단하지 말고, 세 합의안에서 겹치는 것부터 실제 파일에 반영하라.\n\n` +
  `${FILES}\n${RULES}\n${SCORING}\n\n` +
  `[진단]\n${ctx}\n\n[마스터 3개 합의안]\n${JSON.stringify(cons)}\n\n` +
  `해야 할 일:\n` +
  `1. 셋 중 둘 이상이 채택한 편집을 먼저 적용한다. 하나만 낸 것은 지면이 남을 때만 적용한다.\n` +
  `2. 시각화 처방이 있으면 실제로 만들어라 —\n` +
  `   · 인포그래픽이면 ${DIR}/figures.py 에 함수를 추가하고 ALL 에 등록한 뒤 \`python figures.py\` 로 생성,\n` +
  `     build_docx.py 의 해당 페이지 함수에서 \`c.image("이름", width_cm=13.3)\` 으로 넣는다.\n` +
  `   · ASCII 도해면 content.py 에 리스트 상수로 두고 \`c.mono(C.상수)\` 로 넣는다.\n` +
  `   · 넣기 전에 replaces 에 적힌 표·문단을 반드시 먼저 걷어내라.\n` +
  `3. Edit 툴로 ${DIR}/content.py · figures.py · build_docx.py 를 실제로 고쳐라.\n` +
  `4. \`cd ${DIR} && python figures.py && python build_docx.py ${ver + 1} && ` +
  `python render_check.py ${ver + 1} && python measure.py ${ver + 1}\` 실행.\n` +
  `5. 5장이 안 되거나 하단여유가 음수면 더 줄이고 다시 빌드하라. 최대 4번까지 반복하라.\n` +
  `6. 마지막에 render_v${ver + 1}/page-*.png 를 Read 로 열어 그림이 실제로 들어갔는지, ` +
  `잘리거나 찌그러지지 않았는지 눈으로 확인하라. 이상하면 크기를 고쳐 다시 빌드하라.\n` +
  `7. 기존 out/ 파일은 절대 지우지 마라. 새 버전 번호로만 만든다.\n` +
  `8. 끝나면 보고하라: 최종 페이지 수, 넣은 시각 요소, 걷어낸 것, 남은 문제.\n\n` +
  `주의: build_docx.py 의 규격 상수(여백·표너비·열너비·글자크기)는 건드리지 마라.`,
  { label: `집행:${applier}`, phase: '적용', model: applier })

// ─────────────────────────────────────────── 8. 검수 (싼 모델 — 기계적 확인만)
phase('적용')
const qa = await agent(
  `AX Award 지원서 v${ver + 1} 이 방금 만들어졌다. 기계적으로만 확인해 보고하라. 판단·평가는 하지 마라.\n\n` +
  `1. \`cd ${DIR} && python measure.py ${ver + 1}\` 실행 — 페이지 수와 페이지별 하단여유를 그대로 옮겨라.\n` +
  `2. ${DIR}/out/render_v${ver + 1}/page-*.png 를 전부 열어 다음만 확인하라 —\n` +
  `   빈 페이지가 있는가 / 글자가 잘렸는가 / 그림이 찌그러지거나 잘렸는가 / 표가 페이지를 넘어 쪼개졌는가.\n` +
  `3. ${DIR}/content.py 에서 금지어를 grep 하라: GPU, H100, BIG VM, NAS, OBJ, FP8, 인프라, vCPU.\n` +
  `   하나라도 나오면 그 줄을 그대로 인용하라.\n` +
  `4. content.py 에서 퍼센트(%)와 소수 지표를 전부 뽑아, CLAUDE.md §0-3 의 허용 실측치 표에 있는 것인지 대조하라.\n\n` +
  `발견한 것만 사실대로 적어라. 없으면 '없음'이라고 써라. 고치려 들지 마라.`,
  { label: 'QA:최종검수', phase: '적용', model: 'haiku' })

return {
  회차: iter,
  마스터: `${TOP.join('·')} 동시 논의`,
  집행: applier,
  검수: qa,
  분량: fit,
  사실검증: facts,
  심사평균: avg,
  심사상세: debates,
  디자인: design,
  합의안: cons,
  적용결과: applied,
}
