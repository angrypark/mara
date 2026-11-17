"""Runtime validation for the published JSON Schema subset; semantic checks are explicit."""
import json
import math
import re
from functools import lru_cache
from .registry import resource, agent


class ContractError(ValueError):pass


@lru_cache(maxsize=32)
def schema(name):
    if not re.fullmatch(r'[a-z-]+',name):raise ContractError('Unknown contract')
    return json.loads(resource('contracts/'+name+'.schema.json').read_text())


def validate(value, spec, path='$', root=None):
    root=spec if root is None else root
    for rule in spec.get('allOf',[]):validate(value,rule,path,root)
    if 'if' in spec:
        try:validate(value,spec['if'],path,root);matched=True
        except ContractError:matched=False
        validate(value,spec.get('then' if matched else 'else',{}),path,root)
    if '$ref' in spec:
        target=root
        for key in spec['$ref'].removeprefix('#/').split('/'):
            target=target[key]
        return validate(value,target,path,root)
    for key in ('anyOf','oneOf'):
        if key in spec:
            count=0
            for option in spec[key]:
                try:validate(value,option,path,root);count+=1
                except ContractError:pass
            if not count or key=='oneOf' and count!=1:raise ContractError(path+': schema choice failed')
    kind=spec.get('type')
    checks={'object':lambda:type(value) is dict,'array':lambda:type(value) is list,
            'string':lambda:type(value) is str,'boolean':lambda:type(value) is bool,
            'number':lambda:type(value) in (float,int) and math.isfinite(value),
            'integer':lambda:type(value) is int,'null':lambda:value is None}
    if kind and not any(checks[k]() for k in (kind if isinstance(kind,list) else [kind])):
        raise ContractError(path+': expected '+str(kind))
    if 'const' in spec and (type(value)!=type(spec['const']) or value!=spec['const']):raise ContractError(path+': unsupported constant/version')
    if 'enum' in spec and value not in spec['enum']:raise ContractError(path+': invalid enum')
    if isinstance(value,dict):
        if set(spec.get('required',[]))-value.keys():raise ContractError(path+': missing required field')
        if len(value)<spec.get('minProperties',0):raise ContractError(path+': too few keys')
        properties=spec.get('properties',{})
        for key,item in value.items():
            if 'propertyNames' in spec:validate(key,spec['propertyNames'],path,root)
            if key in properties:validate(item,properties[key],path+'.'+key,root)
            elif spec.get('additionalProperties') is False:raise ContractError(path+': unknown field '+key)
            elif isinstance(spec.get('additionalProperties'),dict):validate(item,spec['additionalProperties'],path+'.'+key,root)
    if isinstance(value,list):
        if not spec.get('minItems',0)<=len(value)<=spec.get('maxItems',100000):raise ContractError(path+': array length')
        if spec.get('uniqueItems') and len({json.dumps(x,sort_keys=True) for x in value})!=len(value):raise ContractError(path+': duplicate items')
        for i,item in enumerate(value):validate(item,spec.get('items',{}),path+'['+str(i)+']',root)
        if 'contains' in spec:
            matches=0
            for item in value:
                try:validate(item,spec['contains'],path,root);matches+=1
                except ContractError:pass
            if not spec.get('minContains',1)<=matches<=spec.get('maxContains',len(value)):raise ContractError(path+': contains count')
    if isinstance(value,str):
        if not spec.get('minLength',0)<=len(value)<=spec.get('maxLength',1000000):raise ContractError(path+': text length')
        if 'pattern' in spec and not re.search(spec['pattern'],value):raise ContractError(path+': text pattern')
    if type(value) in (int,float):
        if not math.isfinite(value) or not spec.get('minimum',-math.inf)<=value<=spec.get('maximum',math.inf):raise ContractError(path+': number range')
    return value


def output_schema(role):return schema('agent-'+agent(role)['kind'])


def validate_workbench(doc):
    validate(doc,schema('workbench'))
    from .sleeves import validate as validate_sleeves
    if doc.get('extensions',{}).get('analysis'):validate_sleeves(doc['extensions']['analysis'])
    ids=[c['id'] for c in doc['components']];sources=[s['id'] for s in doc['sources']]
    if len(set(ids))!=len(ids) or len(set(sources))!=len(sources):raise ContractError('Duplicate component/source')
    for c in doc['components']:
        if not set(c['source_ids'])<=set(sources):raise ContractError('Unknown source reference')
        if c['output'] and 'weights' in c['output']:
            from .domain import weights
            weights(c['output']['weights'])
    for edge in doc['edges']:
        if edge['from'] not in ids or edge['to'] not in ids:raise ContractError('Unknown component reference')
    flow=doc.get('extensions',{}).get('flow',[]);steps={step['id'] for step in flow}
    if len(steps)!=len(flow):raise ContractError('Duplicate flow step')
    for step in flow:
        if step['agent_id'] not in ids or not set(step['depends_on'])<=steps:raise ContractError('Unknown flow reference')
        c=next(c for c in doc['components'] if c['id']==step['agent_id']);records={r['output_id'] for r in c['records']}
        if not set(step['record_ids'])<=records:raise ContractError('Unknown flow output')
        snap=step.get('snapshot')
        if snap:
            if snap['source_output_id'] is not None and snap['source_output_id'] not in step['record_ids']:raise ContractError('Stage output mismatch')
            if not set(snap['source_ids'])<=set(sources):raise ContractError('Unknown stage evidence')
            if snap['status']!=step['status']:raise ContractError('Stage status mismatch')
    if doc['portfolio']:
        from .domain import weights
        weights(doc['portfolio']['proposal']['weights'])
        for key in ('actual',):
            if doc['portfolio'][key]['nav']>0:weights(doc['portfolio'][key]['weights'])
    return doc
