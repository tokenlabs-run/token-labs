import asyncio,json,pathlib,sys,tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from aiohttp import web
from run_batching_open_loop import measure

async def main():
    active=0; peak=0; arrivals=[]; mode='normal'
    async def completion(req):
        nonlocal active,peak
        active+=1;peak=max(peak,active);arrivals.append(asyncio.get_running_loop().time())
        payload=await req.json()
        if mode=='error':
            active-=1
            return web.Response(status=503,text='injected failure')
        assert payload['ignore_eos'] and payload['min_tokens']==128
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream'})
        await response.prepare(req)
        await asyncio.sleep(.3)
        counts=([1,36]+[1]*91) if mode=='coalesced' else [1]*128
        for n in counts:
            await response.write(('data: '+json.dumps({'choices':[{'logprobs':{'tokens':['x']*n}}]})+'\n\n').encode())
        await response.write(('data: '+json.dumps({'usage':{'prompt_tokens':512,'completion_tokens':128},'choices':[]})+'\n\ndata: [DONE]\n\n').encode())
        active-=1
        return response
    async def metrics(req):
        return web.Response(text='vllm:num_requests_running{engine="0"} '+str(active)+'\nvllm:num_requests_waiting{engine="0"} 0\n')
    app=web.Application();app.router.add_post('/v1/completions',completion);app.router.add_get('/metrics',metrics)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    port=site._server.sockets[0].getsockname()[1];url=f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory() as d:
        summary=await measure(url,'mock',[{'id':i,'prompt':'test'} for i in range(6)],20,6,pathlib.Path(d)/'run',[url+'/metrics'])
        assert summary['valid'],summary
        assert peak>=5,peak
        assert max(arrivals)-min(arrivals)<.3,arrivals
        assert summary['itl_sample_count']==6*127
        print(json.dumps({'open_loop_verified':True,'peak_overlapping_requests':peak,'offered_rps':20,'actual_dispatch_rps':summary['actual_dispatch_rps'],'completed':summary['completed'],'itl_samples':summary['itl_sample_count']}))
    mode='coalesced'
    with tempfile.TemporaryDirectory() as d:
        coalesced=await measure(url,'mock',[{'id':i,'prompt':'test'} for i in range(3)],10,3,pathlib.Path(d)/'coalesced',[url+'/metrics'])
        assert coalesced['valid'] and coalesced['coalesced_events']==3 and coalesced['itl_sample_count']==3*127,coalesced
        print(json.dumps({'coalescing_counted':True,'events':coalesced['coalesced_events'],'valid':coalesced['valid']}))
    mode='error'
    with tempfile.TemporaryDirectory() as d:
        failed=await measure(url,'mock',[{'id':i,'prompt':'test'} for i in range(4)],20,4,pathlib.Path(d)/'failed',[url+'/metrics'])
        saved=[json.loads(line) for line in (pathlib.Path(d)/'failed'/'requests.jsonl').open()]
        assert not failed['valid'] and failed['errors']>=1 and any(row['http_status']==503 for row in saved),failed
        print(json.dumps({'failure_preserved':True,'errors':failed['errors'],'completed':failed['completed']}))
    await runner.cleanup()
asyncio.run(main())
