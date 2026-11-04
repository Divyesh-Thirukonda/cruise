'use strict';
const {test,beforeEach,after}=require('node:test');
const assert=require('node:assert/strict');
const {nextHandler}=require('../server/next-adapter.cjs');
const grant=require('../server/speaker-grant.cjs');
const handler=nextHandler(require('../api/modulate-agent'),20000);
const gateway=nextHandler(require('../api/modulate'));
const session='s'.repeat(43),id='a'.repeat(32),job='b'.repeat(32),csrf='c'.repeat(64);
const saved={...process.env},savedFetch=global.fetch;
let calls;
beforeEach(()=>{
 process.env.MODULATE_REMOTE_SECRET='synthetic-private-gateway-'.repeat(3);
 process.env.MODULATE_COMPANION_URL='https://synthetic.example';
 process.env.MODULATE_PUBLIC_ORIGIN='https://modulate-connect.vercel.app';
 delete process.env.MODULATE_DEVICE_DISCOVERY;
 calls=[];global.fetch=async(...args)=>{calls.push(args);return Response.json({request_id:id,job_id:job,status:'running',running:true,phase:'queued',summary:'Queued',private:'secret',events:['secret']});};
});
after(()=>{global.fetch=savedFetch;for(const key of Object.keys(process.env))if(!(key in saved))delete process.env[key];Object.assign(process.env,saved);});
function request(method='GET',body,scope='device',query='?request_id='+id){
 const token=grant.issue(session,Date.now()/1000+600,Date.now()/1000,scope).token;
 return new Request('https://modulate-connect.vercel.app/api/modulate-agent'+query,{method,headers:{authorization:'Bearer '+token,'content-type':'application/json'},...(body!==undefined?{body:JSON.stringify(body)}:{})});
}
test('speaker token cannot submit, read or cancel agent requests; device token is also accepted for speaker',async()=>{
 for(const method of ['GET','POST','DELETE'])assert.equal((await handler(request(method,method==='POST'?{request_id:id,text:'Hello'}:undefined,'speaker'))).status,401);
 assert.equal(calls.length,0);
 const speaker=nextHandler(require('../api/modulate-muse'));
 global.fetch=async()=>Response.json({volume:80,muted:false,verified:true});
 const token=grant.issue(session,Date.now()/1000+600,Date.now()/1000,'device').token;
 assert.equal((await speaker(new Request('https://modulate-connect.vercel.app/api/modulate-muse',{headers:{authorization:'Bearer '+token}}))).status,200);
});
test('public Modulate schema includes task operations and the existing approved logo',async()=>{
 const response=await handler(request('GET',undefined,'speaker','?action=schema'));
 const data=await response.json();assert.equal(response.status,200);
 assert.equal(data.info.title,'Modulate');assert.match(data.info['x-logo'].url,/\/brand\/modulate.png$/);
 assert.deepEqual(Object.keys(data.paths),['/api/modulate-agent','/api/modulate-muse']);assert.equal(calls.length,0);
});
test('request dispatch returns immediately and projects only owned job fields',async()=>{
 const result=await handler(request('POST',{request_id:id,text:'Make an original game',followup_id:null},'device',''));
 const data=await result.json();assert.equal(result.status,200);assert.equal(data.running,true);assert.equal(data.job_id,job);assert.equal(data.private,undefined);assert.equal(data.events,undefined);
 assert.equal(calls[0][0],'https://synthetic.example/connector-request');
 assert.equal(calls[0][1].headers['X-Modulate-Session'],session);
 assert.deepEqual(JSON.parse(calls[0][1].body),{request_id:id,text:'Make an original game',followup_id:null});
});
test('malformed requests cannot dispatch or choose arbitrary routes',async()=>{
 for(const body of [{request_id:id,text:'Hi',path:'/permissions'},{request_id:id,text:'Hi',followup_id:'bad'},{request_id:'bad',text:'Hi'},{request_id:id,text:''}])assert.equal((await handler(request('POST',body))).status,400);
 for(const query of ['?request_id=bad','?request_id='+id+'&request_id='+job,'?action=state'])assert.equal((await handler(request('GET',undefined,'device',query))).status,400);
 assert.equal(calls.length,0);
});
test('poll and cancel use the same fixed request identity without replaying dispatch',async()=>{
 assert.equal((await handler(request())).status,200);
 assert.equal(calls[0][0],'https://synthetic.example/connector-request?request_id='+id);
 global.fetch=async(...args)=>{calls.push(args);return Response.json({cancelled:true,private:'hidden'});};
 const result=await handler(request('DELETE'));assert.deepEqual(await result.json(),{cancelled:true});
 assert.equal(calls[1][0],calls[0][0]);assert.equal(calls[1][1].method,'DELETE');
 global.fetch=async(...args)=>{calls.push(args);throw Error('uncertain action');};calls=[];
 assert.equal((await handler(request('POST',{request_id:id,text:'Make a game'}))).status,502);assert.equal(calls.length,1);
});
test('week grant issuance creates a dedicated scoped session with CSRF and no permission change',async()=>{
 const connector='w'.repeat(43),connectionId='d'.repeat(64),expiry=Math.floor(Date.now()/1000)+604800;
 global.fetch=async(...args)=>{calls.push(args);return Response.json({token:connector,kind:'connector',id:connectionId,expires_at:expiry});};
 const response=await gateway(new Request('https://modulate-connect.vercel.app/api/modulate?action=muse-link',{method:'POST',headers:{cookie:`__Host-modulate_session=${session}; __Host-modulate_csrf=${csrf}`,origin:'https://modulate-connect.vercel.app','x-modulate-csrf':csrf,'content-type':'application/json'},body:'{}'}));
 assert.equal(response.status,200);const data=await response.json();assert.equal(grant.verify(data.token,Date.now()/1000,['device-week']).scope,'device-week');
 assert.equal(grant.verify(data.token,Date.now()/1000+6*86400,['device-week']).session,connector);
 assert.throws(()=>grant.verify(data.token,expiry,['device-week']),e=>e.status===401);
 assert.equal(data.expires_at,expiry);assert.equal(data.id,connectionId);assert.ok(!data.token.includes(connector));
 assert.equal(calls.length,1);assert.equal(calls[0][0],'https://synthetic.example/connector-session');assert.equal(calls[0][1].method,'POST');
 assert.deepEqual(JSON.parse(calls[0][1].body),{});assert.equal(calls[0][1].headers['X-Modulate-Session'],session);
});

test('legacy device grants retain eight-hour expiry; new week grants work only on scoped tools',async()=>{
 const now=Date.now()/1000;
 const old=grant.issue(session,now+604800,now,'device');
 assert.ok(old.expires_at<=now+28800);assert.throws(()=>grant.verify(old.token,now+28801,['device']),e=>e.status===401);
 const weekly=grant.issue(session,now+604800,now,'device-week');
 assert.throws(()=>grant.verify(weekly.token,now,['speaker']),e=>e.status===401);
 for(const endpoint of ['state','session']){
  const result=await gateway(new Request('https://modulate-connect.vercel.app/api/modulate?action='+endpoint,{headers:{cookie:'__Host-modulate_session='+weekly.token}}));
  assert.equal(result.status,endpoint==='state'?401:200);
 }
});

test('Muse revocation is authenticated, CSRF-protected, fixed-route and never blindly replayed',async()=>{
 const connectionId='d'.repeat(64);
 const headers={cookie:`__Host-modulate_session=${session}; __Host-modulate_csrf=${csrf}`,origin:'https://modulate-connect.vercel.app','x-modulate-csrf':csrf,'content-type':'application/json'};
 const make=(overrides={},body={id:connectionId})=>new Request('https://modulate-connect.vercel.app/api/modulate?action=muse-disconnect',{method:'POST',headers:{...headers,...overrides},body:JSON.stringify(body)});
 assert.equal((await gateway(make({'x-modulate-csrf':'bad'}))).status,403);
 assert.equal((await gateway(make({origin:'https://evil.example'}))).status,403);
 assert.equal((await gateway(make({}, {id:'bad'}))).status,400);assert.equal(calls.length,0);
 global.fetch=async(...args)=>{calls.push(args);return Response.json({revoked:true,id:connectionId});};
 const result=await gateway(make());assert.deepEqual(await result.json(),{revoked:true,id:connectionId});
 assert.equal(calls[0][0],'https://synthetic.example/connector-session?id='+connectionId);assert.equal(calls[0][1].method,'DELETE');
 calls=[];global.fetch=async(...args)=>{calls.push(args);throw Error('unknown');};
 assert.equal((await gateway(make())).status,502);assert.equal(calls.length,1);
});
