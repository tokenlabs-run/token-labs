import argparse,asyncio,json,os,signal,socket,sqlite3,sys,time
from dataclasses import dataclass,field
from pathlib import Path
import aiohttp
from aiohttp import web

def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

async def worker(a):
 async def health(r):return web.Response(text='ready')
 async def generate(r):
  n=int((await r.json())['tokens']);z=web.StreamResponse();await z.prepare(r)
  for i in range(n):await asyncio.sleep(a.delay);await z.write((json.dumps({'generation':a.generation,'token':i})+'\n').encode())
  await z.write_eof();return z
 app=web.Application();app.router.add_get('/health',health);app.router.add_post('/generate',generate)
 await web._run_app(app,host='127.0.0.1',port=a.port,print=None)

@dataclass
class W:
 generation:int;process:object;port:int;active:int=0;drained:asyncio.Event=field(default_factory=asyncio.Event)

async def probe(a):
 out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 for p in out.iterdir():
  if p.is_file():p.unlink()
 db=sqlite3.connect(out/'config.sqlite');db.execute('create table desired(generation integer primary key,delay real)');db.execute('insert into desired values(1,.02)');db.commit()
 session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30));workers=[];events=[];tasks=[];active=None;start=time.monotonic();ready=asyncio.Event();switched=asyncio.Event();runner=None
 def emit(kind,**x):
  e={'at':time.monotonic()-start,'event':kind,**x};events.append(e)
  with (out/'events.jsonl').open('a') as f:f.write(json.dumps(e)+'\n')
 async def launch(g,d):
  p=port();proc=await asyncio.create_subprocess_exec(sys.executable,__file__,'--worker','--generation',str(g),'--delay',str(d),'--port',str(p),start_new_session=True);w=W(g,proc,p);w.drained.set();workers.append(w);emit('spawn',generation=g,pid=proc.pid,delay=d)
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   if proc.returncode is not None:raise RuntimeError(f'worker {g} exited')
   try:
    async with session.get(f'http://127.0.0.1:{p}/health') as r:
     if r.status==200:emit('ready',generation=g,pid=proc.pid);return w
   except aiohttp.ClientError:pass
   await asyncio.sleep(.02)
  raise TimeoutError('ready')
 async def retire(w):
  os.killpg(w.process.pid,signal.SIGTERM)
  try:await asyncio.wait_for(w.process.wait(),5)
  except asyncio.TimeoutError:os.killpg(w.process.pid,signal.SIGKILL);await w.process.wait()
  emit('retired',generation=w.generation,active=w.active)
 async def proxy(r):
  w=active;w.active+=1;w.drained.clear();rid=r.headers.get('X-Request-ID','?');emit('admit',generation=w.generation,request_id=rid)
  try:
   async with session.post(f'http://127.0.0.1:{w.port}/generate',data=await r.read(),headers={'content-type':'application/json'}) as u:
    z=web.StreamResponse(status=u.status,headers={'X-Generation':str(w.generation)});await z.prepare(r)
    async for chunk in u.content.iter_any():await z.write(chunk)
    await z.write_eof();return z
  finally:
   w.active-=1;emit('complete',generation=w.generation,request_id=rid)
   if w.active==0:w.drained.set()
 async def send(base,rid,n):
  begin=time.monotonic()-start
  async with session.post(base+'/generate',json={'tokens':n},headers={'X-Request-ID':rid}) as r:
   g=int(r.headers['X-Generation']);lines=[line async for line in r.content]
  return {'request_id':rid,'generation':g,'tokens':len(lines),'begin':begin,'end':time.monotonic()-start,'status':r.status}
 async def watch():
  nonlocal active
  while 1:
   g,d=db.execute('select generation,delay from desired order by generation desc limit 1').fetchone()
   if g>active.generation:
    replacement=await launch(g,d);ready.set();await asyncio.sleep(.1);old=active;active=replacement;emit('cutover',old_generation=old.generation,generation=g,old_active=old.active);switched.set();await asyncio.wait_for(old.drained.wait(),10);await retire(old);return
   await asyncio.sleep(.02)
 try:
  active=await launch(1,.02);app=web.Application();app.router.add_post('/generate',proxy);runner=web.AppRunner(app);await runner.setup();p=port();await web.TCPSite(runner,'127.0.0.1',p).start();base=f'http://127.0.0.1:{p}'
  baseline=await send(base,'baseline',2);watcher=asyncio.create_task(watch());tasks.append(watcher);db.execute('insert into desired values(2,.005)');db.commit();emit('config_commit',generation=2,delay=.005);await asyncio.wait_for(ready.wait(),10);oldtask=asyncio.create_task(send(base,'old-long',100));tasks.append(oldtask);await asyncio.wait_for(switched.wait(),2);new=await send(base,'new-short',4);old=await oldtask;await watcher
  cut=next(e for e in events if e['event']=='cutover');ret=next(e for e in events if e['event']=='retired');assert baseline['generation']==1 and old['generation']==1 and old['tokens']==100 and new['generation']==2 and new['tokens']==4;assert cut['old_active']==1 and new['end']<old['end']<ret['at'];assert all(e['generation']==2 for e in events if e['event']=='admit' and e['at']>cut['at'])
  summary={'passed':True,'baseline':baseline,'old_request':old,'new_request':new,'cutover':cut,'retired':ret,'invariants':{'old_stream_completed':True,'new_stream_completed_before_old':True,'no_post_cutover_admission_to_old':True,'old_retired_after_drain':True}};(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
 finally:
  for t in tasks:
   if not t.done():t.cancel()
  await asyncio.gather(*tasks,return_exceptions=True)
  if runner:await runner.cleanup()
  for w in reversed(workers):
   if w.process.returncode is None:await retire(w)
  await session.close();db.close()

if __name__=='__main__':
 q=argparse.ArgumentParser();q.add_argument('--worker',action='store_true');q.add_argument('--generation',type=int);q.add_argument('--delay',type=float);q.add_argument('--port',type=int);q.add_argument('--output');a=q.parse_args();asyncio.run(worker(a) if a.worker else probe(a))
