// Stores only a tunnel hostname and timestamp. No model keys, sessions or user content.
const json = (value, status=200) => Response.json(value, {status, headers:{'Cache-Control':'no-store'}});
const encoder = new TextEncoder();
async function signature(secret, text) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name:'HMAC',hash:'SHA-256'}, false, ['sign']);
  return [...new Uint8Array(await crypto.subtle.sign('HMAC',key,encoder.encode(text)))].map(b=>b.toString(16).padStart(2,'0')).join('');
}
function equal(a,b) {
  if(typeof a!=='string'||typeof b!=='string'||a.length!==b.length)return false;
  let difference=0;for(let i=0;i<a.length;i++)difference|=a.charCodeAt(i)^b.charCodeAt(i);
  return difference===0;
}
export class Registry {
  constructor(ctx) {this.ctx=ctx;}
  async fetch(request) {
    if(request.method==='GET') {
      const current=await this.ctx.storage.get('device');
      return current?json(current):json({error:'Device has not registered'},503);
    }
    const body=await request.json();
    return this.ctx.storage.transaction(async storage => {
      const current=await storage.get('device');
      if(current && current.timestamp>body.timestamp)return json({error:'Newer registration exists'},409);
      if(!current || current.timestamp!==body.timestamp || current.origin!==body.origin)await storage.put('device',body);
      return json({registered:true});
    });
  }
}
export default {
  async fetch(request,env) {
    const secret=env.REGISTRY_SECRET;
    if(typeof secret!=='string'||secret.length<32)return json({error:'Registry not configured'},503);
    const path=new URL(request.url).pathname;
    if(request.method==='GET' && path==='/resolve') {
      if(!equal(request.headers.get('Authorization'),'Bearer '+secret))return json({error:'Authentication required'},401);
    } else if(request.method==='POST' && path==='/register') {
      if(Number(request.headers.get('Content-Length'))>1024)return json({error:'Too large'},413);
      const reader=request.body?.getReader();
      let text='', size=0;
      if(reader) {
        const decoder=new TextDecoder();
        while(true) {
          const {value,done}=await reader.read();if(done)break;
          size+=value.byteLength;if(size>1024){await reader.cancel();return json({error:'Too large'},413);}
          text+=decoder.decode(value,{stream:true});
        }
        text+=decoder.decode();
      }
      let body;try{body=JSON.parse(text);}catch{return json({error:'Invalid JSON'},400);}
      if(!body || typeof body.origin!=='string' || !/^https:\/\/[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com$/.test(body.origin) ||
         !Number.isSafeInteger(body.timestamp) || Math.abs(Date.now()/1000-body.timestamp)>120)return json({error:'Invalid or expired registration'},400);
      if(!equal(request.headers.get('X-Modulate-Signature'),await signature(secret,`${body.timestamp}\n${body.origin}`)))return json({error:'Authentication required'},401);
      request=new Request(request.url,{method:'POST',body:JSON.stringify({origin:body.origin,timestamp:body.timestamp})});
    } else return json({error:'Unknown route'},404);
    const id=env.DEVICE_REGISTRY.idFromName('modulate-pi');
    return env.DEVICE_REGISTRY.get(id).fetch(request);
  }
};
