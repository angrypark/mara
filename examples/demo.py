"""Run from repository root: python3 -m examples.demo. Never touches real data."""
import copy
import json
import tempfile
from pathlib import Path
from mara.store import Store
from mara.engine import Engine
from mara.agents import DemoModel


def main():
    with tempfile.TemporaryDirectory() as folder:
        db=Store(Path(folder)/'demo.sqlite3')
        session=db.session(db.create_user('demo'))
        engine=Engine(session,DemoModel())
        p=json.loads(Path('examples/profile.json').read_text())
        h=json.loads(Path('examples/holdings.json').read_text())
        m=json.loads(Path('examples/market.json').read_text())
        engine.set_profile(p,'2026-11-14'); engine.set_holdings(h)
        first=engine.run('2026-11-14',db.publish_market(m))
        m['as_of']='2026-11-21'
        for quote in m['prices'].values(): quote.update(observed_at='2026-11-20',known_at='2026-11-21')
        m['prices']['BROAD']['price']=404
        h.update(as_of='2026-11-21',cash=21000)
        engine.set_holdings(h)
        engine.cashflow({'date':'2026-11-18','amount':1000,'reference':'demo-deposit'})
        second=engine.run('2026-11-21',db.publish_market(m))
        print(json.dumps({'warning':'SYNTHETIC DEMO ONLY','initial':first,'weekly':second},ensure_ascii=False,indent=2))
        db.close()

if __name__=='__main__': main()
