"""Rich synthetic fixtures for the real workbench; no personal inputs or external calls."""
import copy
import json
import tempfile
from pathlib import Path
from mara.agents import DemoModel
from mara.engine import Engine,ContextNeedsInput
from mara.store import Store
from mara.workbench import project

ROOT=Path(__file__).resolve().parent.parent

class NarrativeDemo(DemoModel):
    def complete(self,role,guide,p,contract):
        out=super().complete(role,guide,p,contract)
        if contract.get('$id')=='urn:mara:dialogue-answer:1.0.0':return out
        if role=='context':out.update(summary='합성 사례: 5년 뒤 사용할 자금을 준비하며 월 납입과 생활비 현금을 함께 관리해요.',constraints=['필요 현금을 남겨요.','단기 가격 변화만으로 장기 계획을 바꾸지 않아요.'])
        if role=='evidence':out.update(summary='합성 시황 예시예요. 가격 변화와 확인된 사실을 분리해서 읽는 방법을 보여줘요.',drivers=['BROAD의 합성 가격이 지난 평가보다 1% 올랐어요.','가격만으로 기업 가치나 경기 전망을 확정할 수 없어요.'],portfolio_implications=['현재 집중도와 현금 필요를 먼저 비교해요.','구성 변경은 새로운 근거가 충분한지 확인한 후 검토해요.'],uncertainties=['실제 뉴스·거시 자료가 없는 데모예요.'])
        if role in ('buffett','marks','bogle','wood'):
            out['thesis']={'wood':'혁신 채택과 현재 가격의 가정을 확인해요.','buffett':'사업의 질과 가격을 확인하기 전에는 비중 확대를 서두르지 않아요.','marks':'수익 기회보다 먼저, 틀렸을 때 감당할 손실을 살펴봐요.','bogle':'단기 전망에 의존하지 않고 낮은 비용과 넓은 분산을 점검해요.'}[role]
            out['decision_basis']=['각 투자 철학을 설명하기 위한 합성 응답이에요.','동일한 자료를 여러 번 해석해도 독립적인 근거가 늘어나지는 않아요.']
            out['risks']=['자료가 부족하면 확신의 정도를 낮춰야 해요.','이 예시는 실제 투자 제안이 아니에요.'];out['falsifiers']=['목표 시점·현금 필요가 달라지거나 가설을 반박하는 자료가 생기면 다시 평가해요.']
        if role=='leader':out.update(rationale='합성 예시에서는 현재 구성을 유지해요. 시장 전망을 꾸며내지 않고, 현금 필요와 미해결 위험을 다음 평가까지 이어갑니다.',dissent=['가치 관점은 기업 자료를, 위험 관점은 손실 조건을, 분산 관점은 비용과 중복을 더 확인하자고 제안해요.'],next_checks=['다음 주에 목표·제약의 변화와 새로운 근거를 확인해요.'])
        return out


def seed(s):
    e=Engine(s,NarrativeDemo());p=json.loads((ROOT/'examples/profile.json').read_text());h=json.loads((ROOT/'examples/holdings.json').read_text());m=json.loads((ROOT/'examples/market.json').read_text())
    m['coverage']={'status':'synthetic','available':['합성 가격·설명'],'missing':['실제 투자 근거'],'actionable_risky_allocation':False}
    e.set_profile(p,'2026-11-14');e.set_holdings(h);first=e.run('2026-11-14',s.store.publish_market(m))
    h=copy.deepcopy(h);h['as_of']='2026-11-21';h['cashflows_reconciled']=False;e.set_holdings(h);m=copy.deepcopy(m);m['as_of']='2026-11-21'
    for q in m['prices'].values():q.update(observed_at='2026-11-20',known_at='2026-11-21')
    m['prices']['BROAD']['price']*=1.01
    second=e.run('2026-11-21',s.store.publish_market(m))
    class Missing(NarrativeDemo):
        def complete(self,role,*args):
            out=super().complete(role,*args)
            if role=='context':out['missing']=['목표 시점에 자금을 한 번에 쓰나요, 나누어 쓰나요?']
            return out
    try:Engine(s,Missing()).run('2026-11-21',s.store.publish_market(m),revision_reason='context clarification')
    except ContextNeedsInput:pass
    partial=s.latest('run_started')['run_id']
    return {'initial':project(s,first['run_id']),'weekly':project(s,second['run_id']),'partial':project(s,partial)}

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as tmp:
        db=Store(Path(tmp)/'fixture.sqlite3')
        try:print(json.dumps(seed(db.session(db.create_user('synthetic-fixture'))),ensure_ascii=False))
        finally:db.close()
