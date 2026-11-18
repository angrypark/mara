"""Bound research extensions by observed reading progress, never by conclusions."""
import hashlib
import json
from .domain import dumps


class Progress:
    def __init__(self):self.ranges={};self.observations=set();self.discoveries=set();self.history=[];self.grace_used=False
    def interval(self,key,start,end):
        if not isinstance(start,int) or not isinstance(end,int) or end<=start:return 0
        intervals=self.ranges.setdefault(key,[]);covered=sum(max(0,min(end,b)-max(start,a)) for a,b in intervals)
        merged=[]
        for a,b in sorted(intervals+[(start,end)]):
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        self.ranges[key]=merged;return max(0,end-start-covered)
    def unique(self,key,rows,seen):
        count=0
        for row in rows:
            digest=key+hashlib.sha256(dumps(row).encode()).hexdigest()
            if digest not in seen:seen.add(digest);count+=1
        return count
    def observe(self,call,answer,new_facts=(),source_fact=None):
        tool=call['tool'];result=answer.get('result',{});linked=bool(call.get('question_ids'))
        record={'kind':'no_new_source_content','new_units':0,'eligible_for_extension':False,'discovery_bridge':False}
        if answer.get('status') in {'unavailable','stored_not_activated'}:
            return dict(record,kind=answer['status'],acquired=answer['status']=='stored_not_activated',delivered=False)
        if not linked:return dict(record,kind='unlinked_discovery',delivered=bool(answer.get('fact_id')))
        raw=result.get('raw_ref',{}).get('sha256','');version=result.get('extraction_version','')
        if tool=='evidence_read' and result.get('text'):
            kind=(source_fact or {}).get('research_tool')
            if kind in {'company_valuation','company_normalize_earnings','valuation'}:return dict(record,kind='calculation_read_or_assumption_model',delivered=True)
            source_types={'sec_financials','treasury','bls','fed_statement','fed','fund_profile','fund_holdings','fund_history',
                'fx_history','release_notes','institutional_reports','financial_news','candles','orderbook',
                'company_filing_read','company_filing_search','company_xbrl_read'}
            if kind not in source_types:return dict(record,kind='unclassified_or_summary_read',delivered=True)
            serialized=dumps(source_fact);sha=hashlib.sha256(serialized.encode()).hexdigest()
            if result.get('sha256')!=sha or result.get('total_characters')!=len(serialized):
                return dict(record,kind='unclassified_or_summary_read',delivered=True)
            key='wrapper:'+sha;self.interval(key,result['offset'],result['end'])
            # Partial JSON may contain only metadata. Count source observations
            # after the complete wrapper was read, using the same identity as
            # the direct filing/XBRL tool, never the wrapper's ID or byte count.
            if self.ranges[key]!=[(0,len(serialized))]:return dict(record,kind='partial_source_wrapper_read',delivered=True)
            try:content=json.loads(source_fact['text'])
            except (ValueError,TypeError):content=source_fact['text']
            if kind in {'company_filing_read','company_filing_search','company_xbrl_read'}:
                if not isinstance(content,dict):return dict(record,kind='unclassified_or_summary_read',delivered=True)
                direct=dict(call,tool=kind.removeprefix('company_'))
                return self.observe(direct,{'fact_id':source_fact['id'],'result':content})
            if kind=='sec_financials':
                count=self.unique('financial:',[{'source':source_fact['source'],'text':source_fact['text']}],self.observations)
            else:count=self.unique('source:'+kind+source_fact['source'],[content],self.observations)
            record.update(kind='delivered_evidence_range',new_units=count)
        elif tool in {'filing_read','filing_search'} and answer.get('fact_id') and raw:
            ranges=[result] if tool=='filing_read' else result.get('hits',[])
            record.update(kind='delivered_document_range',new_units=sum(self.interval('document:'+raw+version,r['start'],r['end']) for r in ranges))
        elif tool=='xbrl_read' and answer.get('fact_id') and raw:
            key='xbrl:'+raw+':'+dumps([result[k] for k in ('namespace','tag','unit')])
            record.update(kind='delivered_xbrl_observations',new_units=self.unique(key,result.get('observations',[]),self.observations))
        elif tool=='company':
            rows=[{'source':f['source'],'text':f['text']} for f in new_facts if f.get('research_tool')=='sec_financials']
            record.update(kind='delivered_financial_observations',new_units=self.unique('financial:',rows,self.observations))
        elif tool in {'xbrl_search','filing_list'}:
            rows=result.get('concepts',[]) if tool=='xbrl_search' else result.get('filings',[])
            key='discovery:'+call['arguments']['symbol']+':'+raw
            count=self.unique(key,rows,self.discoveries)
            record.update(kind='new_discovery' if count else 'repeated_discovery',new_units=count,discovery_bridge=count>0)
            return record
        elif tool in {'analysis_read','valuation','normalize_earnings'}:
            return dict(record,kind='calculation_read_or_assumption_model',delivered=bool(answer.get('fact_id')) or tool=='analysis_read')
        record['eligible_for_extension']=record['new_units']>0
        record['delivered']=bool(answer.get('fact_id')) or tool=='evidence_read'
        return record
    def finish_round(self,records):
        self.history.append({'source_progress':any(r['eligible_for_extension'] for r in records),
            'new_discovery':any(r['discovery_bridge'] for r in records),'records':records})
    def extend(self):
        if any(r['source_progress'] for r in self.history[-2:]):return 'recent_delivered_source_content'
        if self.history and self.history[-1]['new_discovery'] and not self.grace_used:
            self.grace_used=True;return 'one_discovery_to_read_bridge'
        return None
