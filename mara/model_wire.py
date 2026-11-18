"""Lossless JSON sharing for large evaluator inputs; persisted inputs remain original."""
import json

MARKER='$mara_input_ref'

def packed(value):
    seen={}
    def visit(item,path):
        if isinstance(item,dict) and MARKER in item:raise ValueError('Reserved input reference key')
        raw=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        if len(raw)>=512:
            if raw in seen:return {MARKER:seen[raw]}
            seen[raw]=path
        if isinstance(item,dict):return {k:visit(v,path+'/'+k.replace('~','~0').replace('/','~1')) for k,v in sorted(item.items())}
        if isinstance(item,list):return [visit(v,path+'/'+str(i)) for i,v in enumerate(item)]
        return item
    return visit(value,'')

def unpacked(value):
    def expand(item,trail=()):
        if isinstance(item,dict) and set(item)=={MARKER}:
            path=item[MARKER]
            if path in trail:raise ValueError('Cyclic input reference')
            target=value
            for token in path.split('/')[1:]:
                token=token.replace('~1','/').replace('~0','~');target=target[int(token)] if isinstance(target,list) else target[token]
            return expand(target,trail+(path,))
        if isinstance(item,dict):return {k:expand(v,trail) for k,v in item.items()}
        if isinstance(item,list):return [expand(v,trail) for v in item]
        return item
    return expand(value)
