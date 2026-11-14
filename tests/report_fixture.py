"""Synthetic reports for DOM checks. No service, brokerage, or model calls."""
import copy
import json
import tempfile
from pathlib import Path
from mara.agents import DemoModel
from mara.engine import Engine
from mara.reporting import present
from mara.store import Store

ROOT=Path(__file__).resolve().parent.parent

def reports():
    with tempfile.TemporaryDirectory() as tmp:
        db=Store(Path(tmp)/'reports.sqlite3')
        try:
            s=db.session(db.create_user('report-test'));e=Engine(s,DemoModel())
            p=json.loads((ROOT/'examples/profile.json').read_text())
            h=json.loads((ROOT/'examples/holdings.json').read_text())
            m=json.loads((ROOT/'examples/market.json').read_text())
            e.set_profile(p,'2026-11-14');e.set_holdings(h)
            first=e.run('2026-11-14',db.publish_market(m))
            h.update(as_of='2026-11-21',cashflows_reconciled=False);e.set_holdings(h)
            m=copy.deepcopy(m);m['as_of']='2026-11-21'
            for q in m['prices'].values():q.update(observed_at='2026-11-20',known_at='2026-11-21')
            m['prices']['BROAD']['price']=404
            second=e.run('2026-11-21',db.publish_market(m))
            return {'initial':present(s,s.get(first['event_id'])),'weekly':present(s,s.get(second['event_id']))}
        finally:db.close()

if __name__=='__main__':print(json.dumps(reports(),ensure_ascii=False))
