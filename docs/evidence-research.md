# 공개 근거 조사와 질문 추적

2026-11-17 구현 범위예요. 호스트의 스킬 설치 여부와 무관하게 `public-evidence` 지침을 회사 조사·투자 관점·검증·리더 역할의 입력에 전달해요. 실제 도구는 허용된 공개 자료 읽기만 수행해요.

## 조사 순서

1. `collect`로 SEC submissions/companyfacts를 확보하고 `company`로 읽어요. 수집 receipt 자체는 재무 근거가 아니에요.
2. `filing_list`에서 평가일 이전 공시를 선택해요. 최근 10-K/10-Q/20-F/6-K/8-K 및 일부 수정 공시를 형식별 최대 3개씩 유지해요. 전체 역사 검색은 지원하지 않아요.
3. `filing_search`로 공시 ID와 키워드를 지정해요. 다음 검색 위치로 넘어가면 목차 뒤의 주석을 찾을 수 있어요. `filing_read`는 최대 12,000자의 본문을 이어 읽어요.
4. 이어 읽기는 원본 `sha256`과 `extraction_version`을 함께 보내요. 원문이나 추출기가 바뀌면 기존 위치를 재사용하지 않아요. 표의 열·단위·기간이 보존됐다고 보장하지 않아요.
5. 희석 평균 주식수·SBC·감가상각·영업이익·R&D 등 표준 연간 수치를 전달해요. 분기/YTD를 연간 수치로 혼합하거나 CFO-capex를 정상화 이익으로 자동 바꾸지 않아요.

SEC 본문 접근에 실패하면 공식 관계와 공시 ID가 확인된 `issuer-documents.json`의 사본만 사용해요. 다른 공시, 오류 HTML, 발행사·기간 불일치는 거부해요. HTML/PDF 외에 공식 DOCX의 문단 텍스트도 읽으며 XML 16MB·결과 300만자 한도를 적용해요. OCR과 표 셀 복원은 지원하지 않아요.

## 질문과 종료 상태

실행 시작에 목표와 현재 투자 가능 후보를 `decision_scope`로 고정해요. 현금·보류를 선택해도 질문 분모는 줄이지 않아요. 새 실행의 조사 호출은 질문 ID에 연결하고, 공통 후보 탐색은 `discovery_reason`을 명시해요. 외부에서 새로 발견한 회사를 자동 투자 가능 후보로 승격하지 않아요.

보고서의 `research_questions`는 호출·실패 원인·활성화·역할 전달·최종 검증을 구분해요. 기존 자료로 검토한 질문도 출처와 계산 경로를 표시해요. 원문 접근 실패, 수집 실패, 검색 무결과, 활성 예산 제외는 각각 기록해요. 모델의 조사 종료 이유와 라운드/전사 예산 종료도 분리해요. 종료나 수집만으로 질문이 해결되지는 않아요.

최종 R4가 `question_reviews`를 반환하면 판단 근거 참조를 검증해요. 생략된 질문은 검토 대기로 남아요. Q1은 같은 질문 원장과 활동 요약을 전달받고, 다음 주에는 이전 질문 상태·검토·다음 행동을 전달받아요. 이것은 실제 분석의 타당성이나 Q1 통과를 보장하지 않아요. 구형 보고서와 범위 없는 기존 도구 호출은 계속 읽을 수 있어요.

## 참고한 공개 스킬

- [EdgarTools core](https://github.com/dgunning/edgartools/blob/main/edgar/ai/skills/core/SKILL.md), [reports](https://github.com/dgunning/edgartools/blob/main/edgar/ai/skills/reports/skill.yaml), [financials 주의점](https://github.com/dgunning/edgartools/blob/main/edgar/ai/skills/financials/sharp-edges.yaml): 회사→공시→재무·주석 탐색을 참고했어요. MIT이며 패키지 자체는 설치하지 않았어요.
- [Anthropic initiating-coverage](https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/equity-research/skills/initiating-coverage/SKILL.md), [dcf-model](https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/financial-analysis/skills/dcf-model/SKILL.md): 조사 선행 조건과 출처·민감도 확인을 참고했어요. Apache-2.0이며 Excel workflow·고정 WACC/성장률 예시는 채택하지 않았어요.
- [SEC 공식 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): companyfacts의 회사 전체 표준 태그 범위와 공시별 시점을 확인해요.

지침은 Mara용으로 작성했으며 외부 스킬 전문을 복사하지 않았어요. 외부 스킬은 유료 데이터 권한을 제공하지 않아요. ETF 전체 보유·해외 발행사·모든 회사 IR 자동 탐색은 별도 adapter가 필요한 다음 범위예요.
