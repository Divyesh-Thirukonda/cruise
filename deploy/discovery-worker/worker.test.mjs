import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import worker, {Registry} from './worker.mjs';
const secret='test-only-'.repeat(5);
function fixture() {
  const records=new Map();let calls=0;
  const storage={get:async k=>records.get(k),put:async(k,v)=>records.set(k,v)};
  storage.transaction=fn=>fn(storage);
  const object=new Registry({storage});
  return {records,get calls(){return calls;},env:{REGISTRY_SECRET:secret,DEVICE_REGISTRY:{idFromName:()=> 'test',get:()=>({fetch:r=>{calls++;return object.fetch(r);}})}}};
}
function registration(body,signature) {
  return new Request('https://registry.test/register',{method:'POST',headers:{'X-Modulate-Signature':signature??createHmac('sha256',secret).update(`${body.timestamp}\n${body.origin}`).digest('hex')},body:JSON.stringify(body)});
}
const body=()=>({origin:'https://device-one.trycloudflare.com',timestamp:Math.floor(Date.now()/1000)});
test('unauthorized lookup and registration cannot reach storage',async()=>{
  const f=fixture();
  assert.equal((await worker.fetch(new Request('https://registry.test/resolve'),f.env)).status,401);
  assert.equal((await worker.fetch(registration(body(),'wrong'),f.env)).status,401);
  assert.equal(f.calls,0);
});
test('rejects expired, malformed, non-string and arbitrary origins before storage',async()=>{
  const f=fixture();
  for(const b of [{...body(),timestamp:1},{...body(),origin:'https://evil.test'},{...body(),origin:[body().origin]},null]){
    const r=new Request('https://registry.test/register',{method:'POST',body:JSON.stringify(b)});
    assert.equal((await worker.fetch(r,f.env)).status,400);
  }
  assert.equal((await worker.fetch(new Request('https://registry.test/register',{method:'POST',body:'x'.repeat(2048)}),f.env)).status,413);
  assert.equal(f.calls,0);
});
test('signed registration resolves only with authentication, strips extra fields, and rejects rollback',async()=>{
  const f=fixture(),first=body();
  assert.equal((await worker.fetch(registration({...first,extra:'not-stored'}),f.env)).status,200);
  assert.deepEqual(f.records.get('device'),first);
  const read=()=>worker.fetch(new Request('https://registry.test/resolve',{headers:{Authorization:`Bearer ${secret}`}}),f.env);
  assert.deepEqual(await (await read()).json(),first);
  const fresh={...first,timestamp:first.timestamp+1};
  assert.equal((await worker.fetch(registration(fresh),f.env)).status,200);
  assert.equal((await worker.fetch(registration({...first,origin:'https://older.trycloudflare.com'}),f.env)).status,409);
  assert.deepEqual(await (await read()).json(),fresh);
});
test('unconfigured registry and empty registry fail explicitly',async()=>{
  const f=fixture();
  assert.equal((await worker.fetch(new Request('https://registry.test/resolve'),{})).status,503);
  assert.equal((await worker.fetch(new Request('https://registry.test/resolve',{headers:{Authorization:`Bearer ${secret}`}}),f.env)).status,503);
});
