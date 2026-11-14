"""Explicit read-only broker connection check. Never submits or enables orders."""
import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from .toss import TossClient,secret_config


def identity(config):
    return hashlib.sha256(json.dumps([config['client_id'],config.get('account_seq')]).encode()).hexdigest()


def save_private(path,value):
    fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix='.connection-')
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def verify(directory,client_factory=TossClient):
    root=Path(directory); status_path=root/'connection-status.json'
    lock_fd=os.open(str(root/'operator.lock'),os.O_WRONLY|os.O_CREAT,0o600)
    with os.fdopen(lock_fd,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result={'verified':False,'checked_at':datetime.now(timezone.utc).isoformat(),'read_only':True}
        try:
            config=secret_config(root/'credentials.json')
            policy=json.loads((root/'policy.json').read_text())
            broker=client_factory(config,root/'access-token.json')
            accounts=[a for a in broker.accounts() if a.get('accountType')=='BROKERAGE']
            chosen=config.get('account_seq')
            if chosen is None:
                if len(accounts)!=1: raise ValueError('Choose account_seq explicitly when account is not unique')
                chosen=accounts[0]['accountSeq']
            if not any(a['accountSeq']==chosen for a in accounts): raise ValueError('Configured account not available')
            if policy.get('account_seq') not in (None,chosen): raise ValueError('Policy and credential accounts differ')
            broker.account=chosen
            broker.holdings(); broker.buying_power(); broker.open_orders()
            # Persist account selection only after all read-only requests succeed.
            config['account_seq']=chosen; policy['account_seq']=chosen
            save_private(root/'credentials.json',config)
            save_private(root/'policy.json',policy)
            result.update(verified=True,identity=identity(config),checks=['authentication','accounts','holdings','buying_power','open_orders'])
            save_private(status_path,result)
            return {k:v for k,v in result.items() if k!='identity'}
        except Exception as exc:
            result['error_type']=type(exc).__name__
            save_private(status_path,result)
            raise


def status(directory):
    root=Path(directory)
    try:
        stored=json.loads((root/'connection-status.json').read_text())
        config=secret_config(root/'credentials.json')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(stored['checked_at'])).total_seconds()
        verified=stored.get('verified') is True and stored.get('identity')==identity(config) and 0<=age<86400
        return {'verified':verified,'checked_at':stored['checked_at'],'read_only':True}
    except (OSError,ValueError,KeyError):
        return {'verified':False,'checked_at':None,'read_only':True}


def main():
    p=argparse.ArgumentParser(description='Verify Toss authentication and account reads, without orders')
    p.add_argument('--directory',default='.local/toss')
    args=p.parse_args()
    try: print(json.dumps(verify(args.directory)))
    except Exception as exc:
        print(json.dumps({'verified':False,'error_type':type(exc).__name__}))
        raise SystemExit(2)

if __name__=='__main__': main()
