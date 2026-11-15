"""Executed, reversible counterfactual policy exercise; never account outcomes."""
import copy,hashlib
from decimal import Decimal
from . import domain as d


def exercise(profile,household,monthly):
    original=d.dumps(profile);original_hash=hashlib.sha256(original.encode()).hexdigest()
    expenses=household['stress'][0]['expenses'];rows=[];scenario=copy.deepcopy(profile)
    def rule(income):
        available=max(Decimal(0),Decimal(str(income))-Decimal(str(expenses)))
        action='pause' if available<=0 and monthly>0 else 'reduce' if available<Decimal(str(monthly)) else 'maintain'
        return {'surplus_after_required_expenses':float(available),'permitted_new_contribution':float(min(Decimal(str(monthly)),available)),'action':action}
    for case,fraction in [('baseline',1),('income_70_percent',.7),('income_zero',0),('restore_baseline',1)]:
        scenario['monthly_income']=profile['monthly_income'] if fraction==1 else float(Decimal(str(profile['monthly_income']))*Decimal(str(fraction)))
        result=rule(scenario['monthly_income'])
        independent=max(Decimal(0),Decimal(str(profile['monthly_income']))*Decimal(str(fraction))-Decimal(str(expenses)))
        expected='pause' if independent<=0 and monthly>0 else 'reduce' if independent<Decimal(str(monthly)) else 'maintain'
        rows.append({'case':case,'income_fraction_assumption':fraction,'monthly_income_assumption':scenario['monthly_income'],'required_expenses':expenses,'planned_contribution':monthly,**result,'decimal_boundary_check':result['action']==expected and abs(Decimal(str(result['permitted_new_contribution']))-min(Decimal(str(monthly)),independent))<Decimal('0.000001')})
    restored=rows[0]['action']==rows[-1]['action'] and rows[0]['permitted_new_contribution']==rows[-1]['permitted_new_contribution'] and d.dumps(profile)==original and d.dumps(scenario)==original
    return {'schema_version':'mara.monitoring-exercise/1.0','scope':'현재 입력을 복사한 소득 충격 규칙 실제 실행 시험. 사용자 실제 소득 변화·투자 성과·실패 가설 학습 완료를 주장하지 않음.',
        'hypothesis':'필수 지출 뒤 잉여가 예정 납입보다 적으면 예정 납입을 그대로 지속할 수 없다. 소득 회복 시 현금 보충 등 별도 조건이 없다면 기존 납입 상한으로 복원 가능.',
        'rule':'available=max(0,income-required_expenses); contribution=min(planned,available); nonpositive→pause, less than planned→reduce, otherwise maintain',
        'results':rows,'source_profile_hash':original_hash,'source_profile_unchanged':d.dumps(profile)==original,'working_copy_restored':d.dumps(scenario)==original,'restoration_passed':restored,'all_checks_passed':restored and all(x['decimal_boundary_check'] for x in rows),
        'lesson':'일정 납입 가정은 소득 경로에 조건부다. 실제 적용은 가계 현금 보충·확인된 대출 조건·기타 제약까지 재검토하며 이 시험만으로 납입을 실행하지 않는다.',
        'limits':'세금·현금 보충·실제 외부 유동성 변화를 모형화하지 않음. maintain은 투자 또는 주문 승인이 아닌 지급 능력의 한 가지 조건. profile·actual·지식 가이드·실행 기록을 수정하지 않으며 실제 관측과 분리.'}
