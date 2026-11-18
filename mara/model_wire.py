"""Lossless JSON sharing for role inputs; persisted inputs remain original."""
import json
import re
from collections import Counter

MARKER='$mara_input_ref'
VALUE_MARKER='$mara_value'
VERSION='mara.model-wire/2.0'

def supported(model,role):
    return (getattr(model,'input_wire_version',None)==VERSION or
        role=='evaluator' and getattr(model,'evaluator_wire_version',None)==VERSION)

INSTRUCTION=('Input serialization mara.model-wire/2.0: root is the original JSON document. '
    'An object with only $mara_value and an integer means the EXACT value at that index in values, recursively. '
    'Resolve these references before reading role_guide, contract and input. '
    'No original text, number, list order or evidence is removed. '
    'Citations use paths in the decoded input, never paths into this serialization envelope. ')

def serialized(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def packed(value):
    counts=Counter()
    def count(item):
        if isinstance(item,dict) and ({MARKER,VALUE_MARKER}&set(item)):
            raise ValueError('Reserved input reference key')
        raw=serialized(item)
        if len(raw)>=64:
            counts[raw]+=1
            # A shared parent is encoded once, so count its descendants once too.
            if counts[raw]>1:return
        if isinstance(item,dict):
            for child in item.values():count(child)
        elif isinstance(item,list):
            for child in item:count(child)
    count(value)
    values=[];indices={}
    def children(item):
        if isinstance(item,dict):return {k:visit(v) for k,v in sorted(item.items())}
        if isinstance(item,list):return [visit(v) for v in item]
        return item
    def visit(item):
        raw=serialized(item)
        if counts.get(raw,0)>1:
            if raw not in indices:
                index=len(values);indices[raw]=index;values.append(None)
                values[index]=children(item)
            return {VALUE_MARKER:indices[raw]}
        return children(item)
    root=visit(value)
    return {'version':VERSION,'root':root,'values':values}

def unpacked(value):
    if isinstance(value,dict) and value.get('version')==VERSION:
        if set(value)!={'version','root','values'} or not isinstance(value['values'],list):
            raise ValueError('Invalid shared input envelope')
        restored={}
        def resolve(index,trail):
            if type(index) is not int or not 0<=index<len(value['values']):
                raise ValueError('Invalid shared input reference')
            if index in trail:raise ValueError('Cyclic input reference')
            if index not in restored:restored[index]=restore(value['values'][index],trail+(index,))
            return restored[index]
        def restore(item,trail=()):
            if isinstance(item,dict) and MARKER in item:raise ValueError('Mixed input reference versions')
            if isinstance(item,dict) and VALUE_MARKER in item:
                index=item[VALUE_MARKER]
                if set(item)!={VALUE_MARKER}:raise ValueError('Invalid shared input reference')
                return resolve(index,trail)
            if isinstance(item,dict):return {k:restore(v,trail) for k,v in item.items()}
            if isinstance(item,list):return [restore(v,trail) for v in item]
            return item
        for index in range(len(value['values'])):resolve(index,())
        return restore(value['root'])
    if isinstance(value,dict) and isinstance(value.get('version'),str) and value['version'].startswith('mara.model-wire/'):
        raise ValueError('Unsupported input reference version')
    # Keep the original pointer format readable for previously saved diagnostics.
    def expand(item,trail=()):
        if isinstance(item,dict) and VALUE_MARKER in item:raise ValueError('Mixed input reference versions')
        if isinstance(item,dict) and MARKER in item:
            if set(item)!={MARKER}:raise ValueError('Invalid input reference object')
            path=item[MARKER]
            if not isinstance(path,str) or (path and not path.startswith('/')):
                raise ValueError('Invalid input reference pointer')
            if path in trail:raise ValueError('Cyclic input reference')
            target=value
            try:
                for token in path.split('/')[1:]:
                    if re.search(r'~(?![01])',token):raise ValueError('Invalid pointer escape')
                    token=token.replace('~1','/').replace('~0','~')
                    if isinstance(target,list):
                        if not re.fullmatch(r'0|[1-9][0-9]*',token):raise ValueError('Invalid pointer array index')
                        target=target[int(token)]
                    else:target=target[token]
            except (KeyError,IndexError,TypeError):raise ValueError('Unknown input reference pointer') from None
            return expand(target,trail+(path,))
        if isinstance(item,dict):return {k:expand(v,trail) for k,v in item.items()}
        if isinstance(item,list):return [expand(v,trail) for v in item]
        return item
    return expand(value)
