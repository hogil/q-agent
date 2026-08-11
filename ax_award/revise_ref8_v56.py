from pathlib import Path
import argparse
import re

OUT = Path(r"D:\project\q-agent\ax_award\html\AX_Award_지원서_v56.html")
BANNED = ["완전한", "살아있는", "스스로", "통째로", "정거장", "자란다", "닫힌다", "관문", "걷는다", "돌파", "\u00b7", "IV."]


def box(title, body, cls=""):
    return f'<div class="box {cls}"><div class="box-title">{title}</div><div class="box-body">{body}</div></div>'


def flow(items, cls="flow"):
    return '<div class="%s">%s</div>' % (cls, ''.join(f'<div class="step">{x}</div>' for x in items))


def page(num, content):
    return f'<section class="page"><div class="safe">{content}</div><div class="page-no">- {num} -</div></section>'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--replace-generated', action='store_true')
    args = parser.parse_args()
    p1 = f'''
      <h1>AX Award 지원서</h1>
      <table class="form overview"><colgroup><col class="leftcol"><col class="rightcol"></colgroup><tr class="section-row"><td colspan="2">I. 개요</td></tr>
      <tr><th>지원부문</th><td>제조 AX 부문</td></tr>
      <tr><th>팀/그룹</th><td>제조기술센터 품질기술그룹 <span class="split">대표자</span> 홍길동</td></tr>
      <tr><th>제목</th><td>반도체 품질 이상감지, 판단 AI Agent Orchestration 구축 Q-Agent</td></tr>
      <tr><th>분류</th><td>적용시점 <span class="split">1차년 포토, 2차년 etch, CMP</span></td></tr>
      <tr><th>분류</th><td>횡전개 범위 <span class="split">품질 이상감지, 원인조사, 조치 업무</span></td></tr></table>
      <table class="form issue"><colgroup><col class="leftcol"><col class="rightcol"></colgroup><tr class="section-row"><td colspan="2">II. Process</td></tr><tr><th>문제 정의</th><td>
        <div class="lead">이상은 빨리 오지만, 판단은 사람의 조회 경험과 근무 시간에 묶여 있습니다.</div>
        <div class="ribbon"><b>PHO-D03 사례</b><span>07:20 SPC 이상</span><i>→</i><span>이력, 설비, 이미지 대조</span><i>→</i><span>조치안 확정까지 지연</span></div>
        <div class="case-line"><span>신호</span><b>CD 급등 알람</b><span>조사</span><b>기간계 5종, 이미지, 과거 조치 이력</b><span>결과</span><b>담당자 경험에 따라 순서와 결론이 달라짐</b></div>
        <div class="four-grid">
          {box('시간', '알람 뒤 사람이 여러 화면과 문서를 오가며 확인한다. 조사 코어는 수초 안에 근거 후보를 모은다.')}
          {box('편차', '같은 현상도 담당자별로 조회 순서와 참고 사례가 달라 판정 근거가 흔들린다.')}
          {box('공백', '야간과 주말에는 조사 착수와 인계가 늦어진다. 무인 접수와 기록이 필요하다.')}
          {box('휘발', '확정된 원인과 조치가 개인 메모에 남으면 다음 사건에서 다시 찾기부터 시작한다.')}
        </div>
        <div class="why"><b>왜 지금인가</b><span>이상 감지, 이미지, 이력 데이터는 이미 분산돼 있다. 필요한 것은 화면을 더하는 일이 아니라, 데이터 조회부터 판단, 승인, 등록까지 이어지는 업무 재설계다.</span></div>
        <div class="mini-compare"><div><b>기존 자동화</b><br>이상 신호까지만 전달</div><div><b>BI 화면</b><br>조회 항목을 늘림</div><div class="accent"><b>Q-Agent</b><br>근거를 모아 판단안과 조치안을 제시</div></div>
      </td></tr></table>'''

    p2 = f'''
      <table class="form full"><colgroup><col class="leftcol"><col class="rightcol"></colgroup><tr><th>Process 재설계</th><td>
        <div class="lead">사람이 하던 조사 업무를 줄이는 것이 아니라, 사건 접수부터 결과 등록까지 한 흐름으로 재구성합니다.</div>
        <div class="lanes"><div class="lane-title human">Human</div><div class="lane-body">이상 확인 <i>→</i> 화면별 조회 <i>→</i> 원인 토의 <i>→</i> 승인 <i>→</i> 결과 기록</div><div class="lane-title agent">Q-Agent</div><div class="lane-body">이벤트 또는 질문 입력 <i>→</i> 근거 조사 <i>→</i> 판단안 <i>→</i> 권한별 조치 <i>→</i> Inform Note 등록</div></div>
        <div class="process-hero">{flow(['Adapter<br><small>이상을 질문으로</small>', 'Investigator<br><small>도구 반복 조회</small>', 'Judgment<br><small>근거 판정</small>', 'Action<br><small>권한별 조치</small>', 'Answer<br><small>사람에게 반환</small>', 'Register<br><small>확정 결과 등록</small>'])}</div>
        <div class="two-col">
          {box('코어 하나, 입구 둘', '<b>Chat</b>은 엔지니어 질문으로 시작한다. <b>Adapter</b>는 SPC 알람을 조사 질문으로 바꾼다. 두 입구는 같은 조사 코어와 도구를 쓴다.')}
          {box('도구는 결과만 반환', 'SQL 조회, 공통성 분석, wafer map, 이미지 판독, 유사 사례 검색은 정해진 함수가 수행한다. 판단은 인용 가능한 반환값에만 기대게 한다.')}
        </div>
        <div class="approval"><div class="approval-title">조치 승인 경계</div><div><b>L0</b><span>조회와 요약</span></div><div><b>L1</b><span>알림과 티켓 제안</span></div><div><b>L2</b><span>사람 승인 뒤 조치</span></div><div><b>L3</b><span>저위험 항목만 개별 심의 뒤 자동</span></div></div>
        <div class="feedback"><b>사람의 판정</b> 승인, 수정, 반려 <i>→</i> <b>Register</b> 조사규칙과 Inform Note로 등록 <i>→</i> 다음 조사에서 유사 사례로 재사용. 미승인 L2 조치는 감사 로그에서 0건으로 관리한다.</div>
        <div class="spread"><div class="spread-title">확산 계획</div>{flow(['1Q 조사 코어, 도구, 검증기', '2Q Shadow 운영, 조치 미실행', '3Q Chat 파일럿 확대', '4Q 무인 접수, 누락 0건', '2차년 etch, CMP 확산'])}</div>
        <div class="note">5Q는 etch 골든셋 회귀 통과와 코어 변경 0을 확인한다. 공정별로 조사규칙과 시스템 지도만 추가해 확산 비용을 낮춘다.</div>
      </td></tr></table>'''

    p3 = f'''
      <table class="form tech"><colgroup><col class="leftcol"><col class="rightcol"></colgroup><tr class="section-row"><td colspan="2">III. Tech</td></tr><tr><th>기술적<br>해결 방안</th><td>
        <div class="lead">이 문제는 질문마다 필요한 데이터와 조사 순서가 달라, 고정 규칙이나 단일 검색으로 끝낼 수 없습니다.</div>
        <div class="reason-grid">
          {box('왜 Agent인가', '사건마다 설비, 기간, 이미지, 과거 조치의 조합이 다르다. 조사 중 얻은 결과에 따라 다음 조회를 골라야 한다.', 'dark')}
          {box('무엇을 고정하는가', '판단 절차는 도구 호출, 근거 인용, 검증기, 승인 경계로 고정한다. 언어 모델은 도구 선택과 근거 종합에만 쓴다.')}
        </div>
        <div class="compare-table"><div class="ct-head"><span>대안</span><span>업무 한계</span><span>Q-Agent 선택</span></div><div><span>사내 공용 RAG</span><span>설비 ID 토큰 보호, 메타 필터, 검색 지표 운영을 요구대로 다루기 어렵다.</span><span>도메인 색인과 회귀 측정을 분리 운영</span></div><div><span>BI, 대시보드</span><span>사람이 봐야 할 화면만 늘리고, 조사 순서를 정하지 못한다.</span><span>도구 호출 뒤 판단안 반환</span></div><div><span>규칙 기반 SPC</span><span>이상 신호는 주지만 원인과 조치안을 만들지 못한다.</span><span>이상 신호를 Adapter 입력으로 사용</span></div></div>
        <div class="select"><div class="select-title">알고리즘 선택</div><div class="algo"><b>Agent orchestration</b><span>ReAct 도구 루프로 필요한 조회를 반복</span></div><div class="algo"><b>Hybrid retrieval</b><span>벡터와 키워드로 과거 Inform Note 후보 검색</span></div><div class="algo"><b>Reranking</b><span>사건 조건과 가까운 근거를 위로 정렬</span></div><div class="algo"><b>Grounding verifier</b><span>숫자, 인용, 조치 권한을 별도 검증</span></div></div>
        <div class="metric"><div><span>Q-Agent 회귀 러너 실측</span><strong>recall@10 0.500</strong><em>골든 4건, 색인 50건</em></div><p>현재 수치는 검색 회수율 하나만 적는다. 판정 일치율은 2Q 그림자 운영에서 기준선을 실측한 뒤 회귀 게이트로 고정한다.</p></div>
        <div class="improve"><b>개선 과정</b>{flow(['골든 시나리오와 실패 사례 수집', '질의 재작성, 검색기, 리랭커 변경', 'recall@10 재측정', '검증기와 회귀 러너 통과 뒤 배포'], 'flow compact')}</div>
        <div class="note">프롬프트, 모델, 임베딩, 색인을 바꿀 때마다 회귀 러너를 실행한다. 근거 없는 판단과 미승인 조치는 배포 단계에서 막는다.</div>
      </td></tr></table>'''

    p4 = f'''
      <table class="form tech"><colgroup><col class="leftcol"><col class="rightcol"></colgroup><tr class="section-row"><td colspan="2">III. Tech</td></tr><tr><th>기술적<br>해결 방안</th><td>
        <div class="architecture"><div class="arch-in">입구<br><small>Chat, SPC 이벤트</small></div><div class="arch-arrow">→</div><div class="arch-router"><b>Router</b><small>반복 조회와 증거 축적</small><div class="tools">SQL 조회 / 공통성 분석 / Map / Image / 유사 사례</div></div><div class="arch-arrow">→</div><div class="arch-judge">판정<br><small>근거 검증</small></div><div class="arch-arrow">→</div><div class="arch-action">조치<br><small>L0~L3</small></div></div>
        <div class="loop-caption">조사 결과가 부족하면 Router가 다음 도구를 고른다. 도구 반환이 쌓인 뒤에만 판정과 조치안이 나온다.</div>
        <div class="trace-wrap"><div class="trace-title">A/B 조사 Trace</div><div class="trace"><div><b>A. PHO-D03 CD 급등</b><span>설비 이력 조회</span><i>→</i><span>공통성 분석</span><i>→</i><span>세정 후 계측 사례 검색</span><i>→</i><span>점검 티켓 L1 제안</span></div><div><b>B. wafer map 이상</b><span>Map 분류</span><i>→</i><span>이미지 판독</span><i>→</i><span>과거 불량 사례</span><i>→</i><span>사람 승인 L2</span></div></div></div>
        <div class="stack-title">4층 Evidence Stack</div><div class="stack"><div><b>1</b><span>사건 입력</span><small>SPC, Chat, 기간, 설비 조건</small></div><div><b>2</b><span>도구 반환</span><small>코드 계산과 원문 조회 결과</small></div><div><b>3</b><span>인용 근거</span><small>문서, 이력, 이미지 출처</small></div><div><b>4</b><span>판정과 조치</span><small>근거 부족이면 판단 보류</small></div></div>
        <div class="action-plan"><b>조치안 출력 형식</b><span>원인 가설</span><span>근거 3종</span><span>권고 조치</span><span>조치 등급</span><span>승인자</span></div>
        <div class="ablation"><b>개선 검증</b><div><span>검색만</span><span>검색 + 리랭커</span><span>검색 + 도구 반복 조회</span><span>전체 + 검증기</span></div><p>같은 골든 시나리오로 후보 근거, 인용, 조치 권한을 비교한다. 검색 품질은 recall@10으로, 판정은 그림자 일치율 기준선으로 관리한다.</p></div>
        <div class="funnel"><div>입력</div><i>→</i><div>근거 없음 차단</div><i>→</i><div>권한 확인</div><i>→</i><div>사람 승인 또는 등록</div><small>배포 전: 검증기 3종 차단 재현, 골든셋 회귀, 미승인 조치 거부</small></div>
      </td></tr></table>'''

    p5 = f'''
      <table class="form benefit"><colgroup><col class="leftcol"><col class="rightcol"></colgroup><tr class="section-row"><td colspan="2">IIII. 경영효과</td></tr><tr><th>예상 성과</th><td>
        <div class="lead">수치는 가정 기반 업무시간 환산가치이며, 1차년 포토 파일럿은 실측 구간으로 두고 전면 산정에 넣지 않습니다.</div>
        <div class="numbers"><div><small>확산 완료 후 연간</small><strong>200억</strong><span>업무시간 환산가치</span></div><div><small>연간 기준 ROI</small><strong>57.5배</strong><span>투자 347,794,165원 기준</span></div><div><small>연간 기준 회수</small><strong>6.3일</strong><span>2개년 총투자 기준 12.7일</span></div></div>
        <div class="formula">[ (개선 전 4h ÷ 8h) − (개선 후 2h ÷ 8h) ] × 연봉 80,000,000원 × 1,000명 = 연 200억 원</div>
        <div class="assume"><b>산정 가정</b><span>3개 공정 확산 후 1,000명 전면 적용</span><span>개선 전 1인 일 4시간, 개선 후 2시간</span><span>연봉은 사내 산정 기준값</span></div>
        <div class="sensitivity"><div class="sens-title">민감도</div><div><span>개선 후 2.0h</span><b style="width:100%">200억, 57.5배</b></div><div><span>2.5h</span><b style="width:75%">150억, 43.1배</b></div><div><span>3.0h</span><b style="width:50%">100억, 28.8배</b></div><div><span>3.5h</span><b style="width:25%">50억, 14.4배</b></div><p>실측 처리 시간이 가정보다 길면 같은 산식으로 하향한다. 30분 절감 시에도 ROI 14.4배다.</p></div>
        <div class="two-col intangible">{box('무형 효과', '야간과 주말의 조사 착수 공백을 줄인다. 같은 현상에 같은 조사 경로를 남겨 판단 편차와 인계 부담을 낮춘다. 근거 원문과 승인 이력이 남아 감사 대응도 가능하다.')}{box('확산 효과', '조사 코어, 공정별 조사규칙 템플릿, 골든셋 구축 절차를 표준안으로 만든다. 다른 공정은 코어를 다시 개발하지 않고 규칙과 데이터를 추가한다.')}</div>
        <div class="achievement"><b>선행 추진 실적</b><span>설계 문서 31종</span><span>조사 코어 스켈레톤 실행</span><span>검증기 5칙</span><span>회귀 러너와 골든 4건</span><span>recall@10 0.500 실측</span></div>
        <div class="roadmap"><div><b>2Q</b><span>Shadow 운영</span><small>조치 미실행, 일치율 기준선 실측</small></div><i>→</i><div><b>3Q</b><span>Chat 파일럿</span><small>현업 사용, 반려율과 재사용률 측정</small></div><i>→</i><div><b>2차년</b><span>3개 공정 확산</span><small>저위험 조치만 개별 심의 뒤 확대</small></div></div>
      </td></tr></table>'''

    css = '''
@page { size: 794px 1123px; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #dfe5ec; color: #101926; font-family: Batang, "BatangChe", serif; font-size: 10pt; }
.page { width: 794px; height: 1123px; position: relative; page-break-after: always; background: #fff; overflow: hidden; }
.safe { position: absolute; left: 96px; top: 113.4px; width: 602px; height: 913.6px; overflow: hidden; }
.page-no { position: absolute; bottom: 36px; left: 0; width: 100%; text-align: center; font: 10pt Batang, serif; color: #65707d; }
h1 { margin: 0 0 13px; text-align: center; font-size: 22pt; font-weight: 700; text-decoration: underline; line-height: 1.05; }
.form { width: 602px; border-collapse: collapse; table-layout: fixed; font-size: 10pt; }
.form th, .form td { border: 1px solid #384553; vertical-align: top; }
.form td { vertical-align: top !important; }
.leftcol { width: 84.7px; }.rightcol { width: 517.3px; }
.form th { width: 84.7px; padding: 6px 5px; background: #e8edf1; font-size: 11pt; font-weight: 700; text-align: center; vertical-align: middle; }
.form td { width: 517.3px; padding: 7px 8px; line-height: 1.42; }
.section-row td { padding: 5px 8px; background: #dfe9ef; font-size: 12pt; font-weight: 700; }
.overview td { padding: 4px 7px; height: 25px; }.overview th { padding: 4px; }.split { margin-left: 26px; font-weight: 700; }
.issue { margin-top: 10px; }.issue tr:not(.section-row) td { height: 585px; }.full tr:not(.section-row) td { height: 908px; }.tech tr:not(.section-row) td { height: 868px; }.benefit tr:not(.section-row) td { height: 868px; }
.lead { font-weight: 700; color: #193b55; margin-bottom: 8px; }.ribbon { display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-left: 6px solid #bf4b35; background: #f7eae6; font-size: 10pt; }.ribbon b { color: #8d2c20; }.ribbon i, .flow i { font-style: normal; color: #8d2c20; font-weight: 700; }
.case-line { display: grid; grid-template-columns: 48px 1.1fr 48px 1.6fr 48px 1.7fr; margin: 8px 0; border-top: 1px solid #9aa6b0; border-bottom: 1px solid #9aa6b0; padding: 6px 0; gap: 4px; }.case-line span { color: #65707d; font-weight: 700; }.case-line b { font-weight: 700; }
.four-grid, .two-col, .reason-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }.box { border: 1px solid #9aa6b0; padding: 6px 7px; min-height: 90px; }.box-title { font-size: 11pt; font-weight: 700; color: #1c506d; margin-bottom: 3px; }.box-body { font-size: 10pt; line-height: 1.42; }.dark { background: #1b394e; color: #fff; border-color: #1b394e; }.dark .box-title { color: #fff; }
.why { margin-top: 8px; padding: 7px 8px; border-top: 2px solid #1c506d; background: #edf4f7; }.why b { color: #1c506d; margin-right: 10px; }.mini-compare { display: grid; grid-template-columns: 1fr 1fr 1.2fr; gap: 6px; margin-top: 9px; }.mini-compare div { border: 1px solid #aab4bd; padding: 6px; background: #f8fafb; }.mini-compare .accent { background: #e8f1f5; border-top: 4px solid #1c506d; }
.lanes { display: grid; grid-template-columns: 85px 1fr; border: 1px solid #8796a2; margin: 8px 0; }.lane-title { padding: 8px 5px; font-size: 11pt; font-weight: 700; text-align: center; }.lane-title.human { background: #edf0f2; }.lane-title.agent { background: #dcecf1; color: #16445e; }.lane-body { padding: 8px; border-left: 1px solid #8796a2; }.lane-body i { color: #8d2c20; font-style: normal; font-weight: 700; padding: 0 3px; }.lanes > :nth-child(n+3) { border-top: 1px solid #8796a2; }
.process-hero { padding: 10px 8px; background: #eaf3f6; border: 1px solid #5e8598; }.flow { display: flex; align-items: stretch; gap: 5px; }.step { flex: 1; position: relative; padding: 6px 4px; text-align: center; font-weight: 700; border: 1px solid #7191a1; background: #fff; font-size: 9.5pt; line-height: 1.2; }.step:not(:last-child)::after { content: '→'; position: absolute; right: -10px; top: 25%; z-index: 1; color: #8d2c20; font-size: 12pt; }.step small { font-size: 9.5pt; font-weight: 400; }.two-col { margin-top: 9px; }.two-col .box { min-height: 112px; }.approval { display: grid; grid-template-columns: 95px repeat(4, 1fr); margin-top: 8px; border: 1px solid #7b8993; }.approval > * { padding: 6px 4px; border-left: 1px solid #7b8993; font-size: 9.5pt; }.approval > :first-child { border-left: 0; background: #e8edf1; font-size: 10pt; font-weight: 700; }.approval b { display: block; color: #8d2c20; font-size: 10pt; }.approval span { font-size: 9.5pt; }.feedback, .note { margin-top: 8px; padding: 7px; border-left: 4px solid #1c506d; background: #f0f4f6; }.feedback i { font-style: normal; color: #8d2c20; }.spread { margin-top: 10px; }.spread-title, .select-title, .stack-title, .trace-title, .sens-title { font-size: 11pt; font-weight: 700; color: #193b55; margin-bottom: 5px; }.spread .step { font-size: 9.5pt; min-height: 55px; display: flex; align-items: center; justify-content: center; }.spread .flow { gap: 9px; }.spread .step:not(:last-child)::after { right: -13px; }
.compare-table { margin: 9px 0; border: 1px solid #7e8b96; }.compare-table > div { display: grid; grid-template-columns: 118px 1.5fr 1.05fr; border-top: 1px solid #a5afb7; }.compare-table > div:first-child { border-top: 0; }.compare-table span { padding: 5px 6px; border-left: 1px solid #a5afb7; font-size: 9.5pt; }.compare-table span:first-child { border-left: 0; font-weight: 700; }.ct-head { background: #e4edf1; font-weight: 700; }.select { margin-top: 8px; }.algo { display: grid; grid-template-columns: 160px 1fr; border-top: 1px solid #bac3ca; padding: 5px 0; }.algo b { color: #1b4b65; font-size: 10pt; }.metric { display: grid; grid-template-columns: 200px 1fr; gap: 10px; margin-top: 10px; padding: 8px; background: #edf4f6; border-top: 4px solid #1c506d; }.metric span, .metric em { display: block; font-size: 9.5pt; }.metric strong { display: block; color: #8d2c20; font-size: 15pt; }.metric p, .ablation p { margin: 0; font-size: 9.5pt; }.compact .step { min-height: 54px; display: flex; align-items: center; justify-content: center; font-size: 9.5pt; }
.architecture { display: grid; grid-template-columns: 75px 16px 175px 16px 75px 16px 75px; align-items: center; justify-content: center; margin: 5px 0 8px; }.architecture > div:not(.arch-arrow) { min-height: 86px; padding: 8px 5px; display: flex; flex-direction: column; justify-content: center; text-align: center; border: 1px solid #496a7b; background: #f4f8f9; font-weight: 700; font-size: 10pt; }.architecture small { font-size: 9.5pt; font-weight: 400; }.arch-router { background: #1b465e !important; color: #fff; }.tools { margin-top: 5px; padding-top: 4px; border-top: 1px solid #abc4d0; font-size: 9.5pt; font-weight: 400; }.arch-arrow { text-align: center; color: #8d2c20; font-size: 15pt; font-weight: 700; }.loop-caption { text-align: center; font-size: 9.5pt; color: #445460; margin-bottom: 8px; }.trace-wrap { border: 1px solid #8696a0; }.trace-title { padding: 5px 7px; background: #e8eff2; margin: 0; }.trace > div { display: grid; grid-template-columns: 110px 1fr 14px 1fr 14px 1fr 14px 1fr; gap: 3px; padding: 5px 7px; border-top: 1px solid #c0c8ce; align-items: center; font-size: 9.5pt; }.trace b { color: #1b4b65; }.trace i { color: #8d2c20; font-style: normal; font-weight: 700; }.stack-title { margin-top: 9px; }.stack { border-left: 4px solid #1d607b; }.stack > div { display: grid; grid-template-columns: 30px 120px 1fr; border: 1px solid #95a2ac; border-left: 0; margin-top: -1px; padding: 5px 7px; align-items: center; }.stack b { color: #8d2c20; font-size: 12pt; }.stack span { font-weight: 700; font-size: 10pt; }.stack small { font-size: 9.5pt; }.action-plan { display: flex; gap: 6px; align-items: center; margin-top: 9px; padding: 6px 7px; background: #edf4f6; border: 1px solid #99a9b3; }.action-plan b { font-size: 10pt; color: #1c506d; }.action-plan span { border-left: 1px solid #9ba8b1; padding-left: 6px; font-size: 9.5pt; }.ablation { margin-top: 9px; }.ablation > div { display: grid; grid-template-columns: repeat(4, 1fr); }.ablation span { padding: 5px; text-align: center; border: 1px solid #9eaab3; margin-left: -1px; font-size: 9.5pt; }.ablation span:last-child { background: #dcecf1; font-weight: 700; }.ablation p { margin-top: 5px; }.funnel { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 10px; padding: 8px; border-top: 3px solid #8d2c20; background: #f7eeee; }.funnel div { padding: 5px 6px; background: #fff; border: 1px solid #b56c60; font-size: 9.5pt; font-weight: 700; }.funnel i { font-style: normal; color: #8d2c20; font-weight: 700; }.funnel small { width: 100%; font-size: 9.5pt; }
.numbers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 8px 0; }.numbers div { border: 1px solid #85949e; border-top: 5px solid #1c506d; padding: 7px; }.numbers small, .numbers span { display: block; font-size: 9.5pt; }.numbers strong { display: block; margin: 2px 0; color: #8d2c20; font-size: 18pt; }.formula { padding: 8px; text-align: center; background: #edf4f6; border: 1px solid #9eadb5; font-weight: 700; font-size: 10pt; }.assume { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; padding-bottom: 7px; border-bottom: 1px solid #a9b4bb; }.assume b { color: #1c506d; font-size: 10pt; }.assume span { font-size: 9.5pt; }.assume span::before { content: '□ '; color: #8d2c20; }.sensitivity { margin-top: 9px; }.sensitivity > div:not(.sens-title) { display: grid; grid-template-columns: 115px 1fr; align-items: center; gap: 7px; margin-top: 4px; }.sensitivity span { font-size: 9.5pt; }.sensitivity b { display: block; padding: 3px 6px; background: #1c506d; color: #fff; font-size: 9.5pt; white-space: nowrap; }.sensitivity p { margin: 5px 0 0; font-size: 9.5pt; }.intangible { margin-top: 10px; }.intangible .box { min-height: 115px; }.achievement { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; padding: 7px; border: 1px solid #95a3ad; }.achievement b { color: #1c506d; font-size: 10pt; margin-right: 5px; }.achievement span { padding-left: 6px; border-left: 1px solid #a8b2b8; font-size: 9.5pt; }.roadmap { display: grid; grid-template-columns: 1fr 15px 1fr 15px 1fr; gap: 3px; align-items: center; margin-top: 10px; }.roadmap > div { min-height: 69px; border: 1px solid #7f909a; padding: 5px 6px; }.roadmap b { display: block; font-size: 11pt; color: #8d2c20; }.roadmap span, .roadmap small { display: block; font-size: 9.5pt; }.roadmap i { text-align: center; color: #8d2c20; font-size: 13pt; font-style: normal; font-weight: 700; }
@media screen { body { padding: 20px; display: flex; flex-direction: column; align-items: center; gap: 20px; } }
@media print { body { background: #fff; } .page { margin: 0; } }
'''
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AX Award 지원서 v56</title><style>{css}</style></head><body>{page(1,p1)}{page(2,p2)}{page(3,p3)}{page(4,p4)}{page(5,p5)}</body></html>'''
    layout_probe = '''<script>window.addEventListener('load', () => { const result = [...document.querySelectorAll('section.page')].map((p) => { const safe = p.querySelector('.safe'); const bottom = Math.max(...[...safe.children].map((n) => n.getBoundingClientRect().bottom - p.getBoundingClientRect().top)); return { pageHeight: p.scrollHeight, safeHeight: safe.clientHeight, contentBottom: Number(bottom.toFixed(1)) }; }); document.documentElement.dataset.layout = JSON.stringify(result); });</script>'''
    html = html.replace('</body>', layout_probe + '</body>')
    for term in BANNED:
        assert term not in html, f"forbidden term found: {term}"
    assert html.count('<section class="page">') == 5, "page count must be five"
    assert 'width: 602px' in html and 'width: 84.7px' in html and 'width: 517.3px' in html
    assert 'overflow: hidden' in html and 'height: 913.6px' in html
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and not args.replace_generated:
        raise FileExistsError(f"Refusing to overwrite existing file: {OUT}")
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")
    print("checks: forbidden terms, five pages, fixed table widths, safe-area overflow guard")


if __name__ == '__main__':
    main()
