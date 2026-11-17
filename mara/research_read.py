"""Read bounded slices of this role's delivered evidence; no filesystem or network."""
import hashlib
from .domain import dumps
from .contracts import ContractError


def read(payload,call):
    args=call['arguments'];tool=call['tool']
    offset=args.get('offset',0);limit=args.get('limit',8000)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 500<=limit<=12000:
        raise ContractError('Invalid read range')
    if tool=='evidence_read':
        fact=next((f for f in payload.get('market',{}).get('facts',[]) if f['id']==args['fact_id']),None)
        if fact is None:raise ContractError('Evidence was not delivered to this role')
        value=fact;origin={'fact_id':fact['id'],'topic':fact['topic'],'source':fact['source']}
    elif tool=='analysis_read':
        path=args['path']
        if not path.startswith('/analysis/'):raise ContractError('Read must stay below /analysis/')
        from .evaluation import pointer
        value=pointer({'report':payload},'/report'+path);origin={'path':path}
    else:raise ContractError('Unknown read tool')
    text=dumps(value);digest=hashlib.sha256(text.encode()).hexdigest()
    if offset and not args.get('expected_sha256'):raise ContractError('Continuation requires content hash')
    if args.get('expected_sha256',digest)!=digest:raise ContractError('Read content changed; restart at offset 0')
    if offset>len(text):raise ContractError('Read offset outside content')
    end=min(len(text),offset+limit)
    return dict(origin,status='existing_content_read',sha256=digest,offset=offset,end=end,
                next_offset=end if end<len(text) else None,total_characters=len(text),text=text[offset:end],
                format='JSON character slice; may require continuation',
                scope='Current role input only. A read receipt is not new evidence or analytical resolution.')
