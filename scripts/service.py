#!/usr/bin/env python3
"""Manage the persistent local demo service; never starts a live trading process."""
import argparse
import json
import os
import plistlib
import subprocess
import sys
import urllib.request
from pathlib import Path

LABEL='com.angrypark.mara'
ROOT=Path(__file__).resolve().parent.parent
PLIST=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
DOMAIN='gui/'+str(os.getuid())
TARGET=DOMAIN+'/'+LABEL


def main():
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['install','status','restart','stop'])
    args=p.parse_args()
    if args.action=='install':
        state=ROOT/'.local/service'; state.mkdir(parents=True,exist_ok=True,mode=0o700)
        logs=state/'logs'; logs.mkdir(exist_ok=True,mode=0o700)
        obj={'Label':LABEL,'ProgramArguments':[sys.executable,'-m','mara.service','--directory',str(state),'--port','8788'],
             'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
             'ProcessType':'Background','Umask':63,
             'StandardOutPath':str(logs/'stdout.log'),'StandardErrorPath':str(logs/'stderr.log')}
        PLIST.parent.mkdir(parents=True,exist_ok=True)
        if PLIST.exists():
            old=plistlib.loads(PLIST.read_bytes())
            if old.get('Label')!=LABEL: raise ValueError('Unrelated LaunchAgent exists')
            subprocess.run(['launchctl','bootout',TARGET],capture_output=True)
        PLIST.write_bytes(plistlib.dumps(obj)); PLIST.chmod(0o600)
        subprocess.run(['launchctl','bootstrap',DOMAIN,str(PLIST)],check=True)
    elif args.action=='restart': subprocess.run(['launchctl','kickstart','-k',TARGET],check=True)
    elif args.action=='stop': subprocess.run(['launchctl','bootout',TARGET],check=True)
    else:
        r=subprocess.run(['launchctl','print',TARGET],capture_output=True,text=True)
        summary=[line.strip() for line in r.stdout.splitlines() if any(k in line for k in ['state =','pid =','last exit code ='])]
        print('\n'.join(summary) if r.returncode==0 else 'Not loaded')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8788/health',timeout=3) as response: print(response.read().decode())
        except Exception: print('HTTP unavailable')

if __name__=='__main__': main()
