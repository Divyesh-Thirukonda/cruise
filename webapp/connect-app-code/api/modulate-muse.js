'use strict';
const {HttpError,noStore,objectBody,fail}=require('../server/modulate-http.cjs');
const grant=require('../server/speaker-grant.cjs');
const gateway=require('./modulate');
const BASE='https://modulate-connect.vercel.app';
const tools=[
 {name:'get_speaker_volume',description:'Read the actual Modulate Pi speaker volume and mute state. No Mac control or private content.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,destructiveHint:false,idempotentHint:true}},
 {name:'set_speaker_volume',description:'Set the Modulate Pi speaker to an absolute percentage, 0–100. Returns verified physical readback. Does not change Mac volume or play audio. If confirmation fails, read volume before retrying.',inputSchema:{type:'object',properties:{volume:{type:'integer',minimum:0,maximum:100}},required:['volume'],additionalProperties:false},annotations:{readOnlyHint:false,destructiveHint:false,idempotentHint:true}},
];
const stateSchema={type:'object',properties:{verified:{type:'boolean',const:true},volume:{type:'integer',minimum:0,maximum:100},muted:{type:'boolean'}},required:['verified','volume','muted'],additionalProperties:false};
const schema={openapi:'3.1.0',info:{title:'Modulate Speaker',version:'1.0.0',description:'Read and set the paired Modulate Pi speaker. Use a speaker-only token from Modulate Connect in a secure credential store. Never paste the token in chat. Grant expires with the linked browser session, within eight hours. Disconnect that browser or disable speaker access to revoke. No app, email, camera, microphone or Mac access.'},servers:[{url:BASE}],paths:{'/api/modulate-muse':{get:{operationId:'get_speaker_volume',summary:tools[0].description,security:[{speakerToken:[]}],responses:{200:{description:'Verified speaker state',content:{'application/json':{schema:stateSchema}}}}},post:{operationId:'set_speaker_volume',summary:tools[1].description,security:[{speakerToken:[]}],requestBody:{required:true,content:{'application/json':{schema:tools[1].inputSchema}}},responses:{200:{description:'Verified applied speaker level',content:{'application/json':{schema:stateSchema}}}}}}},components:{securitySchemes:{speakerToken:{type:'http',scheme:'bearer'}}}};
async function speaker(session,volume) {
 const result=await gateway.forward('/speaker-control','POST',volume===undefined?{action:'get'}:{action:'set',value:volume},session);
 let data;try{data=JSON.parse(result.bytes.toString());}catch{throw new HttpError(502,'Speaker readback unavailable. Check its state before retrying.');}
 if(!result.response.ok)throw new HttpError([401,403,503].includes(result.response.status)?result.response.status:502,'Speaker request was not confirmed. Check its current state before retrying.');
 if(data.verified!==true||!Number.isInteger(data.volume)||data.volume<0||data.volume>100||typeof data.muted!=='boolean')throw new HttpError(502,'Speaker readback was not verified.');
 return {verified:true,volume:data.volume,muted:data.muted};
}
module.exports=async function handler(req,res) {
 noStore(res);
 res.setHeader('Vary','Authorization');
 try {
  if(req.method==='GET'&&req.query?.action==='schema')return res.status(200).json(schema);
  if(!['GET','POST'].includes(req.method))throw new HttpError(405,'Method not allowed.');
  const auth=req.headers.authorization||'';
  const session=grant.verify(auth.startsWith('Bearer ')?auth.slice(7):'',Date.now()/1000,['speaker','device','device-week']).session;
  if(req.query?.action!==undefined)throw new HttpError(400,'Unknown action.');
  let volume;
  if(req.method==='POST'){
   const body=objectBody(req,1024);
   if(Object.keys(body).length!==1||!Number.isInteger(body.volume)||body.volume<0||body.volume>100)throw new HttpError(400,'Send an integer volume from 0 to 100.');
   volume=body.volume;
  }
  return res.status(200).json(await speaker(session,volume));
 }catch(error){if(error.status===401)res.setHeader('WWW-Authenticate','Bearer realm="Modulate Speaker"');return fail(res,error,'Speaker request was not confirmed. Check current volume before retrying.');}
};

module.exports.schema=schema;
