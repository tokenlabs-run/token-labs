import argparse, base64, json, subprocess, time, urllib.request, urllib.error
p=argparse.ArgumentParser(); p.add_argument('base'); p.add_argument('--allow-public-auth',action='store_true'); a=p.parse_args()
if a.base.startswith('https://') and not a.allow_public_auth:
    p.error('Public authenticated checks require explicit authorization and --allow-public-auth')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Redirect refused; credentials must remain on the configured provider')
assert a.base in {'https://api.tokenlabs.run', 'http://10.100.90.120:8000', 'http://10.244.2.11:8000'}
opener=urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
model='nvidia/Qwen3.6-35B-A3B-NVFP4'
k=['kubectl','--context=kubernetes-admin@kubernetes','-n','token-labs']
secret=json.loads(subprocess.check_output(k+['get','secret','openrouter-provider-auth','-o','json']))
key=base64.b64decode(secret['data']['api-key']).decode()
def request(path, body=None, authenticated=False):
    headers={'Content-Type':'application/json'}
    if authenticated: headers['Authorization']='Bearer '+key
    req=urllib.request.Request(a.base+path, data=None if body is None else json.dumps(body).encode(),headers=headers)
    return opener.open(req,timeout=90)
for path,auth in [('/v1/models',False),('/openrouter/v1/models',True)]:
    with request(path,authenticated=auth) as r: d=json.load(r)
    assert {x['id'] for x in d['data']}=={model}, d
    print('PASS',path,'Qwen only',flush=True)
with request('/openrouter/models') as r: d=json.load(r)
assert d=={'data':[]}, 'Static catalog still advertises retired model'
print('PASS static provider catalog empty',flush=True)
try:
    request('/openrouter/v1/models').close()
    raise AssertionError('Anonymous provider access accepted')
except urllib.error.HTTPError as e:
    assert e.code==401, e.code
print('PASS provider authentication enforced',flush=True)
body={'model':model,'messages':[{'role':'user','content':'Reply with exactly OK.'}],'max_tokens':32,'temperature':0}
start=time.monotonic()
with request('/openrouter/v1/chat/completions',body,True) as r: d=json.load(r)
assert d.get('choices') and d.get('usage',{}).get('completion_tokens',0)>0, 'No generated tokens'
print('PASS non-streaming inference',round(time.monotonic()-start,2),'seconds',flush=True)
body['stream']=True
with request('/openrouter/v1/chat/completions',body,True) as r: s=r.read().decode()
assert 'data: [DONE]' in s and '"choices"' in s, 'Incomplete inference stream'
assert '"error"' not in s, 'Stream contained error'
print('PASS streaming inference with DONE',flush=True)
