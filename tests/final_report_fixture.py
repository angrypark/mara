"""Public synthetic report for browser and print regression checks."""
import copy
import json
from test_final_report import FinalReportTests,DAY
from mara.final_report import assemble
from mara.reporting import present


def fixture():
    case=FinalReportTests();case.setUp()
    try:
        report,_=case.full_document();report['proposal']['action']='defer'
        report['proposal']['decision_status']['status']='blocked';report['proposal']['monthly_allocation']['status']='blocked'
        report['proposal']['rationale']='신규 납입 계획은 검토했지만, 핵심 가정이 확인될 때까지 편입 판단을 보류해요.'
        report['proposal']['investment_case']['key_points']=['가정한 이익이 유지되는지 아직 확인하지 못했어요.','확인 전에는 정기 납입 계획을 실행하지 않아요.','같은 비중을 유지하는 안과 변경 조건을 비교했어요.']
        c=report['proposal']['investment_case']['claims'][0]
        c.update(statement='실적이 유지된다는 조건에서만 이 구성을 검토할 수 있어요.',assumptions=['추가 투자와 희석이 가정 범위를 넘지 않아야 해요.'],counterevidence='투자 지출이 늘면 주주에게 남는 현금이 줄 수 있어요.',decision_impact='확인 전에는 편입 판단을 보류해요.')
        case_doc=report['proposal']['investment_case']
        case_doc['alternatives'][0].update(name='기존 비중을 유지하는 비교안',reason='같은 자금 기준에서 현재 구성을 비교하기 위한 안이에요.',change_condition='추가 투자와 희석의 범위를 확인하면 다시 검토해요.')
        case_doc['monitoring']=[{'variable':'투자 지출과 주당 이익','condition':'투자 지출이 가정 범위를 넘는지 확인해요.','check_at':'다음 분기 실적 발표 후','owner':'기업 가치 분석 역할','action':'정상화 이익과 편입 판단을 다시 검토해요.','counterexample_test':'매출이 늘어도 주당 현금이 줄어드는지 확인해요.'}]
        case_doc['implementation']=['별도 주문 지시와 입금 확인 전에는 실행하지 않아요.'];case_doc['scope_limits']=['개인 정보를 쓰지 않은 합성 검증 사례예요.']
        report['validation']['final_critique'].update(qualitative_pass=False,reason='보류 이유는 타당하지만 성장 자산의 가치와 가격 연결은 아직 충분하지 않아요.',issues=['재투자 가정을 확인해야 해요.'],unsupported_claims=['원문만으로 미래 이익을 확정할 수 없어요.'])
        opposing={'id':'synthetic-opposing','topic':'합성 공시 발췌 · 반대 근거 검증용','source':'https://example.com/synthetic-filing',
            'published_at':DAY,'known_at':DAY,'valid_until':DAY,'research_tool':'company_filing_read','uncertainty':'실제 기업 자료가 아닌 화면 검증용 데이터예요.',
            'text':json.dumps({'text':'합성 공시의 투자 지출 설명','start':100,'end':600,'text_length':10000,'extraction_version':'synthetic/1',
                'filing':{'form':'10-Q','accession':'0000000001-26-000001'},'raw_ref':{'sha256':'f'*64}})}
        case.s.append('research_evidence',{'role':'validation','fact':opposing},DAY,report['run_id'])
        report['validation']['final_critique']['judgment_report']={'evidence_ids':['synthetic-opposing']}
        from test_fact_catalog import series
        price_fact={'id':'synthetic-prices','topic':'합성 가격 시계열 · 실제 투자 자료 아님','source':'https://example.com/source',
            'published_at':DAY,'known_at':DAY,'valid_until':DAY,'uncertainty':'화면 검증용 합성 관측값이에요.',
            'text':'관측 시작과 끝 사이에 가격이 낮아졌지만 중간에 상승한 관측도 있어요.','series':series()}
        case.s.append('research_evidence',{'role':'evidence','fact':price_fact},DAY,report['run_id'])
        price_claim=copy.deepcopy(c);price_claim.update(id='synthetic-price-claim',statement='이 표본의 처음과 마지막 가격을 비교하면 20% 하락했어요.',
            fact_ids=['synthetic-prices'],counterevidence='중간 관측에서는 가격이 올랐어요. 계속 하락했다는 뜻은 아니에요.',
            assumptions=['관측된 종가끼리만 비교했어요. 배당과 거래 비용은 반영하지 않았어요.'])
        case_doc['claims'].append(price_claim)
        report['market_observations']['analysis']['changes']=['EARLY_EMPTY_ALLOCATION_SENTINEL: 초기에는 제안 비중이 비어 있었어요.']
        report['final_report']=assemble(report,case.market['facts']+[opposing,price_fact])
        eid=case.s.append('completed',report,DAY,report['run_id']);row=present(case.s,case.s.get(eid))
        row['view']['market_analysis']=copy.deepcopy(report['market_observations']['analysis'])
        row['view']['judgment_report_history'].append({'role':'leader','stage':'proposal_synthesis','source_output_id':'synthetic-old-opinion',
            'contract_accepted':True,'latest_accepted_for_stage':False,'report':{'title':'EARLIER_ROLE_OPINION_SENTINEL','as_of':DAY,
            'portfolio_context':'합성 개인 맥락','market_context':'합성 시장 자료','decision_method':'당시 비교한 방법','conclusion':'이전 단계의 의견이에요.','evidence_ids':['demo-1']}})
        return row
    finally:case.tearDown()


if __name__=='__main__':print(json.dumps(fixture(),ensure_ascii=False))
