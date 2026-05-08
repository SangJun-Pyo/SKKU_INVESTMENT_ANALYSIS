/**
 * aiCommittee.js — AI 투자위원회 채팅 모듈
 *
 * 역할:
 * - CIO/CRO/Research/Report Writer 역할 선택
 * - AppState에서 과제용 컨텍스트 생성 → 시스템 프롬프트에 포함
 * - /chat API로 메시지 전송
 * - 단타 매매 조언 대신 포트폴리오 리스크 관점 답변 유도
 *
 * 단타 조언 방지 전략:
 *   시스템 프롬프트에 "LONG/SHORT 단타 아닌 포트폴리오 CIO 관점"을 명시합니다.
 *   역할별 시스템 프롬프트를 다르게 구성하여 AI의 답변 방향을 제어합니다.
 */
window.AICommitteeModule = (() => {
  'use strict';

  /* 현재 채팅 히스토리 (서버로 전송하여 대화 맥락 유지) */
  let _chatHistory = [];

  /* ══════════════════════════════════════════════════════════
     역할별 시스템 프롬프트
     각 역할에 맞는 관점과 제약사항을 명시합니다.
  ══════════════════════════════════════════════════════════ */
  const ROLE_PROMPTS = {
    'CIO Assistant': `당신은 마코프 자산운용의 CIO 어시스턴트입니다.
역할: 포트폴리오 배분 전략 수립 및 리스크 관리 지원
관점: 중장기 포트폴리오 관점, ETF 중심 자산배분, 벤치마크 대비 초과수익 최적화
제약사항:
- 단타 매매(1일 이내 진입/청산) 조언 금지
- 모든 체결은 금요일 종가 기준임을 전제
- ETF 개수 10개 미만 규칙 준수
- 총 익스포저 130억 한도 내에서 조언
- 레버리지 30% 이하 유지 권고`,

    'CRO Checker': `당신은 마코프 자산운용의 CRO(최고리스크관리자)입니다.
역할: 포트폴리오 리스크 규칙 준수 검증, 위반 항목 지적, 개선 방안 제시
관점: 리스크 우선, 규칙 준수, 하방 보호
주요 점검 항목:
1. 총 익스포저 ≤ 130억 KRW
2. 레버리지 ≤ 30%
3. 숏 비중 ≤ 30%
4. ETF 수 < 10개
5. 주간 변동성 ≤ 1.5%
6. 95% VaR ≥ -20억
7. 벤치마크 베타 ≤ 1.2
8. 단일 ETF ≤ 40억
9. MDD -3% 트리거 시 디레버리징
10. 알파 리스크 ≤ 40%
제약사항: 위험 조언 시 반드시 구체적인 수치와 함께 제시`,

    'Research Summarizer': `당신은 마코프 자산운용의 리서치 분석가입니다.
역할: ETF 시장 분석, 매크로 환경 요약, 투자 아이디어 발굴
관점: 데이터 중심, 객관적 분석, 벤치마크 대비 시각
분석 프레임워크:
- 추세: 20일/60일 이동평균 방향
- 모멘텀: 최근 4주 수익률, RSI
- 변동성: 실현 변동성, VIX 레벨
- 상관관계: 포트폴리오 내 분산 효과
제약사항: 단타 시그널이 아닌 주간 배분 관점으로 분석`,

    'Report Writer': `당신은 마코프 자산운용의 보고서 작성 전문가입니다.
역할: 교수 제출용 과제 보고서 초안 작성, 전문적이고 간결한 문서화
보고서 톤: CIO 관점, 전문적, 정량적 근거 강조
작성 원칙:
1. 규칙 준수 여부를 항상 먼저 언급
2. 투자 근거는 점수/데이터 기반으로 기술
3. 불필요한 수식어 최소화
4. 금요일 종가 체결 기준 명시
5. 벤치마크 대비 초과수익 목표 강조
제약사항: 추측성 조언 대신 데이터 기반 서술`,
  };

  /* ══════════════════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════════════════ */
  function init() {
    /* 역할 버튼 이벤트 */
    document.querySelectorAll('.role-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        /* 기존 active 제거 후 클릭한 버튼 활성화 */
        document.querySelectorAll('.role-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const role = btn.dataset.role;
        AppState.set('role', role);
        _updateContextSummary();

        /* 역할 전환 시 채팅 히스토리 초기화 (새 컨텍스트에서 시작) */
        _chatHistory = [];
        _appendMessage('assistant', `역할이 [${role}]로 변경되었습니다. 이전 대화 내용이 초기화됩니다.`);
      });
    });

    /* 전송 버튼 */
    const sendBtn = document.getElementById('chat-send-btn');
    if (sendBtn) {
      sendBtn.addEventListener('click', _handleSend);
    }

    /* Ctrl+Enter로도 전송 가능 */
    const textarea = document.getElementById('chat-input');
    if (textarea) {
      textarea.addEventListener('keydown', e => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          _handleSend();
        }
      });
    }

    /* 컨텍스트 요약 초기 렌더링 */
    _updateContextSummary();

    /* portfolio/riskBudget/universe 변경 시 컨텍스트 자동 업데이트 */
    AppState.on('portfolio',  _updateContextSummary);
    AppState.on('riskBudget', _updateContextSummary);
    AppState.on('universe',   _updateContextSummary);
    AppState.on('week',       _updateContextSummary);
  }

  /* ══════════════════════════════════════════════════════════
     컨텍스트 요약 업데이트
     사이드바에 현재 포트폴리오 상태를 표시합니다.
  ══════════════════════════════════════════════════════════ */
  function _updateContextSummary() {
    const el = document.getElementById('context-summary');
    if (!el) return;

    const week      = AppState.get('week');
    const universe  = AppState.get('universe');
    const portfolio = AppState.get('portfolio');
    const risk      = AppState.get('riskBudget');

    const lines = [
      `Week ${week}`,
      `ETF ${universe.length}개`,
      `포지션 ${portfolio.positions.length}개`,
      portfolio.totalExposure > 0
        ? `노출 ${AppState.formatAmount(portfolio.totalExposure)}`
        : '배분 미완료',
      risk
        ? `리스크 위반 ${risk.violations.length}건`
        : '리스크 미검증',
    ];

    el.textContent = lines.join(' | ');
  }

  /* ══════════════════════════════════════════════════════════
     채팅 메시지 전송
  ══════════════════════════════════════════════════════════ */
  async function _handleSend() {
    const textarea = document.getElementById('chat-input');
    const sendBtn  = document.getElementById('chat-send-btn');
    if (!textarea) return;

    const userMessage = textarea.value.trim();
    if (!userMessage) return;

    /* 단타 키워드 감지: 단타 조언 요청 시 안내 메시지 */
    const shortTermKeywords = ['단타', 'LONG', 'SHORT', '1분', '5분', '즉시매수', '지금사', '손절가', '스탑로스'];
    const isShortTerm = shortTermKeywords.some(kw => userMessage.includes(kw));

    /* UI 업데이트 */
    textarea.value = '';
    _appendMessage('user', userMessage);

    if (sendBtn) sendBtn.disabled = true;

    /* 단타 요청 감지 시 안내 */
    if (isShortTerm) {
      _appendMessage('assistant',
        '이 AI 투자위원회는 단타 매매 조언을 제공하지 않습니다.\n' +
        '포트폴리오 배분, 리스크 관리, 벤치마크 분석, ' +
        '보고서 작성에 관한 질문을 해주세요.'
      );
      if (sendBtn) sendBtn.disabled = false;
      return;
    }

    /* 로딩 표시 */
    const loadingEl = _appendMessage('assistant', '답변 생성 중...');
    loadingEl.classList.add('loading');

    try {
      const role = AppState.get('role') || 'CIO Assistant';

      /* 서버 ChatRequest 스키마: { message, role, context: dict | null }
         context는 반드시 dict 형태로 전송 (문자열 전송 시 422 에러) */
      const contextDict = _buildContextDict();

      /* 채팅 히스토리에 사용자 메시지 추가 */
      _chatHistory.push({ role: 'user', content: userMessage });

      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage,
          role:    role,          // CIO Assistant / CRO Checker 등
          context: contextDict,   // dict 형태로 전송
        }),
      });

      loadingEl.remove();

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      /* 서버 ChatResponse: { response: str, role: str } */
      const reply = data.response || data.reply || data.content || data.message || '응답이 없습니다.';

      _appendMessage('assistant', reply);

      /* 채팅 히스토리에 AI 응답 추가 */
      _chatHistory.push({ role: 'assistant', content: reply });

      /* 히스토리가 너무 길어지면 오래된 것부터 제거 (메모리 관리) */
      if (_chatHistory.length > 40) {
        _chatHistory = _chatHistory.slice(-30);
      }

    } catch (err) {
      loadingEl.remove();
      console.error('[AICommittee] 채팅 오류:', err);
      _appendMessage('assistant',
        `오류가 발생했습니다: ${err.message}\n` +
        '백엔드 서버가 실행 중인지 확인하세요.'
      );
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      textarea.focus();
    }
  }

  /* ══════════════════════════════════════════════════════════
     컨텍스트 딕셔너리 빌드
     서버 ChatRequest.context는 Optional[dict] 타입 — 문자열 전송 시 422 에러
     AppState의 현재 상태를 dict로 직렬화하여 전송합니다.
  ══════════════════════════════════════════════════════════ */
  function _buildContextDict() {
    const s = AppState.get();
    return {
      week:        s.week,
      base_capital: s.baseCapital,
      benchmark:   s.benchmark,
      universe_count: s.universe.length,
      positions:   (s.portfolio.positions || []).map(p => ({
        ticker:        p.ticker,
        name:          p.name,
        role:          p.role,
        target_amount: p.target_amount,
        target_weight: p.target_weight,
        signal_score:  p.signal_score,
      })),
      total_exposure: s.portfolio.totalExposure,
      leverage_ratio: s.portfolio.borrowedCash / s.baseCapital,
      scores: Object.fromEntries(
        Object.entries(s.signalScores).map(([t, sc]) => [t, {
          total_score: sc.total_score,
          action:      sc.action,
          regime:      sc.regime,
        }])
      ),
      risk_violations: s.riskBudget?.violations || [],
      execution_rule:  '금요일 종가만 체결',
      mode:            'papertrade',
    };
  }

  /* ══════════════════════════════════════════════════════════
     채팅 메시지 DOM 추가
  ══════════════════════════════════════════════════════════ */
  function _appendMessage(role, text) {
    const container = document.getElementById('chat-messages');
    if (!container) return null;

    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;

    /* 줄바꿈을 <br>로 변환하여 표시 */
    div.innerHTML = text.replace(/\n/g, '<br/>');

    container.appendChild(div);

    /* 새 메시지가 보이도록 스크롤 */
    container.scrollTop = container.scrollHeight;

    return div;
  }

  /* ══════════════════════════════════════════════════════════
     공개 API
  ══════════════════════════════════════════════════════════ */
  return { init };
})();
