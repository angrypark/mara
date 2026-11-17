"""Read a pinned, archived SEC companyfacts snapshot without normalizing concepts."""
import hashlib
import json
import re
from .domain import day,dumps
from .research_sources import EvidenceError,finite

VERSION='mara.xbrl-read/1.0'
HASH=re.compile(r'[0-9a-f]{64}')
FORMS={'10-K','10-Q','10-K/A','10-Q/A','20-F','20-F/A','40-F','40-F/A','6-K','6-K/A','8-K','8-K/A'}
SCOPE='SEC standard-taxonomy, entity-wide observations only. Not all custom concepts, segments or notes. No unit conversion, period aggregation, restatement selection or owner-earnings normalization.'


def snapshot(library,ticker,as_of,version=None,expected_sha256=None):
    from .company_research import symbol
    ticker=symbol(ticker)
    if version:
        if not isinstance(version,str) or not HASH.fullmatch(version):raise ValueError('Invalid dossier version')
        body=json.loads((library.root/'companies'/ticker/(version+'.json')).read_text())
    else:body=library.latest(ticker,as_of)
    if not body:raise EvidenceError('company_not_collected')
    original=dict(body);actual_version=original.pop('version')
    if hashlib.sha256(dumps(original).encode()).hexdigest()!=actual_version:raise EvidenceError('company_snapshot_hash_mismatch')
    if body['symbol']!=ticker or body['known_at']>as_of or version and actual_version!=version:raise EvidenceError('company_snapshot_identity_mismatch')
    url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(body['cik']):010d}.json"
    meta=next((r for r in body['raw_refs'] if r.get('source')==url),None)
    if not meta or not HASH.fullmatch(meta.get('sha256','')):raise EvidenceError('companyfacts_archive_unavailable')
    if expected_sha256 and expected_sha256!=meta['sha256']:raise EvidenceError('companyfacts_snapshot_changed')
    raw=(library.root/'raw'/(meta['sha256']+'.raw')).read_bytes()
    if len(raw)>8_000_000 or hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise EvidenceError('companyfacts_archive_hash_mismatch')
    value=json.loads(raw)
    if int(value['cik'])!=int(body['cik']):raise EvidenceError('companyfacts_identity_mismatch')
    return value,{'symbol':ticker,'cik':body['cik'],'entity':body['entity'],'dossier_version':actual_version,
        'raw_ref':meta,'as_of':as_of,'reader_version':VERSION,'scope':SCOPE}


def observations(rows,as_of):
    """Retain each reported row, including alternative/restated values and frames."""
    valid=[];rejected=0
    for row in rows:
        try:
            if row.get('form') not in FORMS:continue
            day(row['filed']);day(row['end'])
            if row['filed']>as_of or row['end']>row['filed']:continue
            if 'start' in row and day(row['start'])>day(row['end']):raise ValueError('Inverted period')
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',row['accn']):raise ValueError('Invalid accession')
            if type(row['val']) not in (int,float):raise ValueError('Numeric observation required')
            finite(row['val'])
            if len(dumps(row))>4000:raise ValueError('Observation metadata limit')
            valid.append(dict(row))
        except (KeyError,TypeError,ValueError):rejected+=1
    # fy/fp describe filing context, not the duration of an individual row.
    valid.sort(key=lambda r:(r['end'],r.get('start',''),r['filed'],r['accn'],dumps(r)),reverse=True)
    return valid,rejected


def page(args,identity):
    offset=args.get('offset',0);limit=args.get('limit',20)
    if type(offset)!=int or not 0<=offset<=100000 or type(limit)!=int or not 1<=limit<=20:raise ValueError('Invalid XBRL page')
    query={k:v for k,v in args.items() if k not in {'offset','limit','query_sha256','expected_sha256','dossier_version'}}
    query.update(as_of=identity['as_of'],dossier_version=identity['dossier_version'],raw_sha256=identity['raw_ref']['sha256'],reader_version=VERSION)
    digest=hashlib.sha256(dumps(query).encode()).hexdigest()
    if offset and (not args.get('dossier_version') or not args.get('expected_sha256') or args.get('query_sha256')!=digest):
        raise EvidenceError('xbrl_continuation_requires_same_query_and_snapshot')
    if args.get('query_sha256',digest)!=digest:raise EvidenceError('xbrl_query_changed_restart_cursor')
    return offset,limit,digest


def run(library,tool,args,as_of):
    if tool not in {'xbrl_search','xbrl_read'}:raise ValueError('Unknown XBRL tool')
    if tool=='xbrl_read' and (not args.get('dossier_version') or not args.get('expected_sha256')):
        raise EvidenceError('xbrl_read_requires_pinned_snapshot')
    raw,identity=snapshot(library,args['symbol'],as_of,args.get('dossier_version'),args.get('expected_sha256'))
    offset,limit,query_hash=page(args,identity)
    if tool=='xbrl_search':
        query=args['query']
        if not isinstance(query,str) or not 1<=len(query)<=200:raise ValueError('Invalid concept query')
        terms=[term.strip().casefold() for term in query.split('|') if term.strip()]
        if not terms or len(terms)>6:raise ValueError('Use one to six explicit search terms')
        found=[]
        for namespace,concepts in sorted(raw['facts'].items()):
            for tag,concept in sorted(concepts.items()):
                description=concept.get('description') or '';label=concept.get('label') or ''
                haystack=' '.join([tag,label,description]).casefold()
                if not any(term in haystack for term in terms):continue
                units={}
                for unit,rows in concept.get('units',{}).items():
                    eligible,_=observations(rows,as_of)
                    if eligible:units[unit]={'observations':len(eligible),'latest_end':max(r['end'] for r in eligible),'latest_filed':max(r['filed'] for r in eligible)}
                if units:found.append({'namespace':namespace,'tag':tag,'label':label[:500],'description':description[:4000],
                    'description_truncated':len(description)>4000,'units':units})
        return dict(identity,concepts=found[offset:offset+limit],total=len(found),offset=offset,
            next_offset=offset+limit if offset+limit<len(found) else None,query_sha256=query_hash,
            status='discovery_only',rule='Choose a concept and exact unit using this dossier version and raw hash; concept similarity does not establish accounting equivalence.')
    namespace,tag,unit=(args[k] for k in ('namespace','tag','unit'))
    concept=raw.get('facts',{}).get(namespace,{}).get(tag)
    if not concept or unit not in concept.get('units',{}):raise EvidenceError('xbrl_concept_or_unit_not_found')
    rows,rejected=observations(concept['units'][unit],as_of)
    for field in ('start','end'):
        key='period_'+field
        if key in args:
            day(args[key]);rows=[r for r in rows if r.get(field)==args[key]]
    selected=rows[offset:offset+limit]
    description=concept.get('description') or ''
    return dict(identity,namespace=namespace,tag=tag,unit=unit,label=(concept.get('label') or '')[:500],
        description=description[:4000],description_truncated=len(description)>4000,observations=selected,total=len(rows),offset=offset,
        next_offset=offset+limit if offset+limit<len(rows) else None,query_sha256=query_hash,
        malformed_rows_excluded=rejected,status='observations' if selected else 'no_observations',
        period_rule='Read start/end for each row; absent start means instant. fy/fp and frame are filing metadata. Quarterly, YTD, annual and amended rows remain separate; differing values are not silently resolved.')
