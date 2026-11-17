# 공개 원문 확보와 깊이 읽기
버전 1.0 · 2026-11-17

판단 질문 ID별로 필요한 수치·기간·근거를 먼저 정해요. 스킬은 접근권이 아니며 도구가 실제 반환한 자료만 인용해요. 조회 성공과 분석적 충분성은 달라요.

기업: search/collect → company로 기간·단위·누락 필드 확인 → filing_list로 공시 선택 → filing_search로 핵심어 찾기 → filing_read로 해당 주석·표 전후 읽기. 최신 분기와 연간 기준을 대조해요. 목차·첫 문장만 나오면 next_offset으로 뒤 매치를 찾거나 hit.start부터 읽어요. 이어 읽을 때 같은 accession과 raw_ref.sha256을 expected_sha256으로, extraction_version을 expected_extraction_version으로 보내요. 다른 문서를 같은 위치로 읽지 않아요.

희석 주식수는 연간 가중평균이며 기말 발행수와 달라요. 주식 보상·재투자·일회성·성장 가정은 주석을 읽고 분석 가정으로 표시해요. CFO-capex를 자동으로 owner earnings로 쓰지 않아요. 연간/YTD/분기·USD/주당/천/백만 단위를 혼합하지 않아요. 본문 추출은 표의 정렬까지 검증한 수치 API가 아니므로 헤더·주석을 대조해요. 가격·분할 기준이 모호하면 valuation을 만들지 않아요.

ETF: 운용사 상품·보유·비용·기준일을 우선해요. 지원 도구/운용사가 없으면 capability_gap으로 기록해요. 일부 자료 부족이 모든 후보의 탈락을 뜻하지 않아요.

실패는 company_not_collected, 접근/HTTP 실패, no_matches, document_changed_restart_cursor, stored_not_activated를 구분해요. no_matches면 검색어/위치를 바꾸고, 예산 제외면 좁은 범위를 읽어요. 같은 실패나 같은 원문을 무한 반복하지 않아요. 허용된 대체 원문도 없으면 출처·읽은 범위·남은 질문·다음 행동을 남겨요. 모든 tools calls에 관련 question_ids를 붙이고 calls=[]일 때 stop_reason을 명시해요.

참고 방법: EdgarTools core/reports/financials와 SEC API, Anthropic initiating-coverage를 2026-11-17에 검토. 외부 도구 설치·임의 웹/셸 권한을 의미하지 않아요. 공급자·스킬 목록은 docs/evidence-research.md에 있어요.
