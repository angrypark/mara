"""Official Toss Open API 1.2.28 adapter. No network calls at import/initialization."""
import fcntl
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from .feeds import NoRedirect

BASE='https://openapi.tossinvest.com'


class BrokerError(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__('Toss API request failed (status '+str(status)+'); inspect account/configuration')


def secret_config(path):
    p=Path(path)
    if p.stat().st_mode & 0o077: raise PermissionError('Credential file must have mode 0600')
    config=json.loads(p.read_text())
    if not config.get('client_id') or not config.get('client_secret'): raise ValueError('Fill local Toss credential template first')
    return config


class Transport:
    def __init__(self):
        self.next_request=0
        self.opener=urllib.request.build_opener(NoRedirect)
    def __call__(self,method,path,headers,body=None):
        # Conservative serial rate limit. A 429 is surfaced, never blindly retried.
        time.sleep(max(0,self.next_request-time.monotonic()))
        self.next_request=time.monotonic()+1.05
        req=urllib.request.Request(BASE+path,data=body,headers=headers,method=method)
        try:
            with self.opener.open(req,timeout=20) as response:
                raw=response.read(2_000_001)
                if len(raw)>2_000_000: raise BrokerError('oversize')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise BrokerError(exc.code) from None  # no credential-bearing body or URL in logs
        except (urllib.error.URLError,TimeoutError): raise BrokerError('transport') from None


class TossClient:
    def __init__(self,config,cache_path,transport=None):
        self.config=config
        self.cache=Path(cache_path)
        self.transport=transport or Transport()
        self.account=config.get('account_seq')
        if not config.get('client_id') or not config.get('client_secret'): raise ValueError('Credentials missing')

    def token(self):
        self.cache.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(str(self.cache),os.O_RDWR|os.O_CREAT,0o600)
        with os.fdopen(fd,'r+') as f:
            os.fchmod(f.fileno(),0o600)
            fcntl.flock(f,fcntl.LOCK_EX)
            try: cached=json.load(f)
            except (ValueError,json.JSONDecodeError): cached={}
            # Per-client shared cache prevents simultaneous processes invalidating each other's token.
            if cached.get('client_id')==self.config['client_id'] and cached.get('expires_at',0)>time.time()+60:
                return cached['access_token']
            form=urllib.parse.urlencode({'grant_type':'client_credentials','client_id':self.config['client_id'],
                                         'client_secret':self.config['client_secret']}).encode()
            value=self.transport('POST','/oauth2/token',{'Content-Type':'application/x-www-form-urlencoded'},form)
            if value.get('token_type')!='Bearer' or int(value['expires_in'])<=60: raise BrokerError('invalid-token-response')
            cached={'client_id':self.config['client_id'],'access_token':value['access_token'],
                    'expires_at':time.time()+int(value['expires_in'])}
            f.seek(0); f.truncate(); json.dump(cached,f); f.flush(); os.fsync(f.fileno())
            return cached['access_token']

    def request(self,method,path,query=None,payload=None,account=True):
        headers={'Authorization':'Bearer '+self.token(),'Content-Type':'application/json'}
        if account:
            if not isinstance(self.account,int) or isinstance(self.account,bool) or self.account<=0: raise ValueError('Choose account_seq explicitly')
            headers['X-Tossinvest-Account']=str(self.account)
        if query: path+='?'+urllib.parse.urlencode(query)
        raw=self.transport(method,path,headers,json.dumps(payload).encode() if payload is not None else None)
        if 'result' not in raw: raise BrokerError('invalid-response')
        return raw['result']

    def accounts(self): return self.request('GET','/api/v1/accounts',account=False)
    def holdings(self): return self.request('GET','/api/v1/holdings')
    def buying_power(self): return self.request('GET','/api/v1/buying-power',{'currency':'USD'})
    def sellable(self,symbol): return self.request('GET','/api/v1/sellable-quantity',{'symbol':symbol})
    def prices(self,symbols): return self.request('GET','/api/v1/prices',{'symbols':','.join(symbols)},account=False)
    def stocks(self,symbols): return self.request('GET','/api/v1/stocks',{'symbols':','.join(symbols)},account=False)
    def exchange_rate(self): return self.request('GET','/api/v1/exchange-rate',{'baseCurrency':'USD','quoteCurrency':'KRW'},account=False)
    def sectors(self): return self.request('GET','/api/v1/sectors',account=False)
    def sector_stocks(self,sector):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',sector): raise ValueError('Invalid sector')
        return self.request('GET','/api/v1/sectors/'+sector+'/stocks',{'marketCountry':'US'},account=False)
    def calendar(self,us_date): return self.request('GET','/api/v1/market-calendar/US',{'date':us_date},account=False)
    def open_orders(self): return self.request('GET','/api/v1/orders',{'status':'OPEN'})
    def order(self,order_id):
        return self.request('GET','/api/v1/orders/'+urllib.parse.quote(order_id,safe=''))
    def submit(self,order):
        # Only used by explicit user-run trading CLI, never by the installed demo service.
        return self.request('POST','/api/v1/orders',payload=order)

    def snapshot(self,symbols,now):
        from zoneinfo import ZoneInfo
        if not symbols or len(symbols)>200 or any(not re.fullmatch(r'[A-Za-z0-9.\-]+',s) for s in symbols):
            raise ValueError('One to 200 valid symbols required')
        return {'captured_at':now.isoformat(),'account_seq':self.account,'holdings':self.holdings(),
            'buying_power':self.buying_power(),'open_orders':self.open_orders(),
            'stocks':self.stocks(symbols),'prices':self.prices(symbols),'fx':self.exchange_rate(),
            'calendar':self.calendar(now.astimezone(ZoneInfo('America/New_York')).date().isoformat()),
            'sellable':{s:self.sellable(s)['sellableQuantity'] for s in symbols}}
