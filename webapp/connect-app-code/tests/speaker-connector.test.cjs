'use strict';
const {test,beforeEach,after}=require('node:test');
const assert=require('node:assert/strict');
const grant=require('../server/speaker-grant.cjs');
const gateway=require('../api/modulate');
const {nextHandler}=require('../server/next-adapter.cjs');
const connector=nextHandler(require('../api/modulate-muse'),16384);
const SESSION='s'.repeat(43),CSRF='a'.repeat(64);
const saved={...process.env},fetchSaved=global.fetch;
let calls;
beforeEach(()=>{
 process.env.MODULATE_REMOTE_SECRET='synthetic-private-gateway-'.repeat(3);
 process.env.MODULATE_COMPANION_URL='https://synthetic.example';
 process.env.MODULATE_PUBLIC_ORIGIN='https://modulate-connect.vercel.app';
 delete process.env.MODULATE_DEVICE_DISCOVERY;
 calls=[];
 global.fetch=async(url,opts)=>{calls.push([url,opts]);return Response.json({verified:true,volume:80,muted:false,private:'hidden'});};
});
after(()=>{global.fetch=fetchSaved;for(const key of Object.keys(process.env))if(!(key in saved))delete process.env[key];Object.assign(process.env,saved);});
function request(method='GET',body,token=grant.issue(SESSION,Date.now()/1000+600).token,action=''){
 return new Request('https://modulate-connect.vercel.app/api/modulate-muse'+action,{method,headers:{authorization:'Bearer '+token,...(body!==undefined?{'content-type':'application/json'}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
}
test('speaker credentials hide parent session, authenticate tampering, expire and cannot use generic gateway',async()=>{
 const issued=grant.issue(SESSION,1000,500);
 assert.equal(issued.expires_at,1000);
 assert.ok(!issued.token.includes(SESSION));
 assert.equal(grant.verify(issued.token,501).scope,'speaker');
 for(const token of [issued.token.slice(0,-5)+'AAAAA',SESSION,'',issued.token+'.'])assert.throws(()=>grant.verify(token,501),e=>e.status===401);
 assert.throws(()=>grant.verify(issued.token,1000),e=>e.status===401);
 assert.equal(grant.issue(SESSION,999999,500).expires_at,29300);
 const result={setHeader(){},status(n){this.code=n;return this;},json(v){this.body=v;}};
 await gateway({method:'GET',query:{action:'state'},headers:{cookie:'__Host-modulate_session='+issued.token}},result);
 assert.equal(result.code,401);assert.equal(calls.length,0);
});
test('public documentation contains only the two scoped operations and no credentials',async()=>{
 const result=await connector(request('GET',undefined,'','?action=schema'));
 assert.equal(result.status,200);
 const data=await result.json();assert.equal(data.openapi,'3.1.0');
 assert.deepEqual(Object.keys(data.paths),['/api/modulate-muse']);
 assert.deepEqual(Object.values(data.paths['/api/modulate-muse']).map(v=>v.operationId),['get_speaker_volume','set_speaker_volume']);
 assert.ok(!JSON.stringify(data).includes(SESSION));assert.equal(calls.length,0);
});
test('missing credentials and malformed or broader actions never reach Pi',async()=>{
 assert.equal((await connector(request('GET',undefined,''))).status,401);
 for(const body of [{volume:101},{volume:true},{volume:0,path:'/command'},{action:'set',value:80},{}])assert.equal((await connector(request('POST',body))).status,400);
 assert.equal((await connector(request('GET',undefined,undefined,'?action=state'))).status,400);
 assert.equal((await connector(request('DELETE'))).status,405);
 assert.equal(calls.length,0);
});
test('only fixed speaker route forwards credentials; responses discard private upstream fields',async()=>{
 for(const [method,body,expected]of [['GET',undefined,{action:'get'}],['POST',{volume:80},{action:'set',value:80}]]){
  const result=await connector(request(method,body));
  assert.equal(result.status,200);assert.deepEqual(await result.json(),{verified:true,volume:80,muted:false});
  assert.equal(result.headers.get('cache-control'),'private, no-store, max-age=0');
  const [url,opts]=calls.at(-1);assert.equal(url,'https://synthetic.example/speaker-control');
  assert.equal(opts.headers['X-Modulate-Session'],SESSION);assert.deepEqual(JSON.parse(opts.body),expected);
 }
});
test('failed writes never replay or expose provider errors; revoked parents are denied',async()=>{
 for(const status of [401,403,503,500]){
  calls=[];global.fetch=async(...args)=>{calls.push(args);return Response.json({error:'private-key'}, {status});};
  const result=await connector(request('POST',{volume:80}));assert.equal(result.status,status===500?502:status);
  assert.ok(!(await result.text()).includes('private-key'));assert.equal(calls.length,1);
 }
 calls=[];global.fetch=async(...args)=>{calls.push(args);throw Error('private destination');};
 assert.equal((await connector(request('POST',{volume:80}))).status,502);assert.equal(calls.length,1);
});
test('unverified or malformed physical readback never claims success',async()=>{
 for(const state of [{volume:80,muted:false},{verified:true,volume:101,muted:false},{verified:true,volume:80,muted:'no'}]){
  global.fetch=async()=>Response.json(state);
  assert.equal((await connector(request())).status,502);
 }
});
