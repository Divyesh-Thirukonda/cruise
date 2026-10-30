'use strict';
const { createHmac, createCipheriv, createDecipheriv, randomBytes } = require('node:crypto');
const { HttpError } = require('./modulate-http.cjs');
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
function key() {
  const secret=process.env.MODULATE_REMOTE_SECRET;
  if(!secret || secret.length<32)throw new HttpError(503,'Connector is not configured.');
  return createHmac('sha256',secret).update('modulate-speaker-grant-v1').digest();
}
function issue(session, expiresAt, now=Date.now()/1000, scope='speaker') {
  const expiry=Math.floor(Math.min(expiresAt,now+28800));
  if(!['speaker','device'].includes(scope) || !TOKEN.test(session||'') || !Number.isFinite(expiry) || expiry<=now)throw new HttpError(401,'Reconnect this browser first.');
  const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key(),iv);
  const bytes=Buffer.concat([cipher.update(JSON.stringify({scope,session,expires_at:expiry})),cipher.final()]);
  return {token:'msg1.'+Buffer.concat([iv,cipher.getAuthTag(),bytes]).toString('base64url'),expires_at:expiry};
}
function verify(token,now=Date.now()/1000,scopes=['speaker']) {
  try {
    if(typeof token!=='string'||!/^msg1\.[A-Za-z0-9_-]{50,600}$/.test(token))throw Error();
    const b=Buffer.from(token.slice(5),'base64url');
    const cipher=createDecipheriv('aes-256-gcm',key(),b.subarray(0,12));cipher.setAuthTag(b.subarray(12,28));
    const grant=JSON.parse(Buffer.concat([cipher.update(b.subarray(28)),cipher.final()]));
    if(Object.keys(grant).sort().join(',')!=='expires_at,scope,session'||!scopes.includes(grant.scope)||!TOKEN.test(grant.session)||!Number.isSafeInteger(grant.expires_at)||grant.expires_at<=now||grant.expires_at>now+28800)throw Error();
    return grant;
  }catch{throw new HttpError(401,'Connector connection expired or is invalid. Reconnect through Modulate.');}
}
module.exports={issue,verify};
