"""Lossless JSON sharing for role inputs; persisted inputs remain original."""
import json
import re
from collections import Counter

MARKER='$mara_input_ref'
VALUE_MARKER='$mara_value'
JSON_MARKER='$mara_json_text'
VERSION='mara.model-wire/3.0'

def supported(model,role):
    return (getattr(model,'input_wire_version',None)==VERSION or
        role=='evaluator' and getattr(model,'evaluator_wire_version',None)==VERSION)

INSTRUCTION=('Input serialization mara.model-wire/3.0: root is the original JSON document. '
    'An object with only $mara_value and an integer means the EXACT value at that index in values, recursively. '
    'An object with only $mara_json_text contains {style,value}: serialize resolved value as JSON text '
    '(Unicode, sorted keys). style compact uses comma and colon without spaces; style spaced uses comma-space and colon-space. '
    'This restores the EXACT original JSON string, e.g. fact.text. '
    'Resolve these references before reading role_guide, contract and input. '
    'No original text, number, list order or evidence is removed. '
    'Citations use paths in the decoded input, never paths into this serialization envelope. ')

def serialized(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def packed(value):
    # Same wire language; choose the smaller lossless sharing plan. Short
    # repeated values become significant when correction feedback is attached.
    return min((_packed(value,64),_packed(value,24)),key=lambda x:len(serialized(x)))

def _packed(value,minimum_shared_size):
    def encode(item):
        if isinstance(item,dict):
            if {MARKER,VALUE_MARKER,JSON_MARKER}&set(item):raise ValueError('Reserved input reference key')
            return {k:encode(v) for k,v in item.items()}
        if isinstance(item,list):return [encode(v) for v in item]
        if isinstance(item,str) and len(item)>=256 and item[:1] in ('{','['):
            try:
                parsed=json.loads(item)
                for style,separators in (('compact',(',',':')),('spaced',(', ',': '))):
                    if json.dumps(parsed,ensure_ascii=False,sort_keys=True,separators=separators,allow_nan=False)==item:
                        return {JSON_MARKER:{'style':style,'value':encode(parsed)}}
            except (ValueError,TypeError):pass  # Noncanonical or reserved-key source stays literal text.
        return item
    value=encode(value)
    counts=Counter()
    def count(item):
        raw=serialized(item)
        if len(raw)>=minimum_shared_size:
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
    if isinstance(value,dict) and value.get('version') in (VERSION,'mara.model-wire/2.0'):
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
            if isinstance(item,dict) and JSON_MARKER in item and value['version']==VERSION:
                if set(item)!={JSON_MARKER}:raise ValueError('Invalid JSON text reference')
                text=restore(item[JSON_MARKER],trail)
                if not isinstance(text,dict) or set(text)!={'style','value'} or text['style'] not in ('compact','spaced'):
                    raise ValueError('Invalid JSON text representation')
                return json.dumps(text['value'],ensure_ascii=False,sort_keys=True,allow_nan=False,
                    separators=(',',':') if text['style']=='compact' else (', ',': '))
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
