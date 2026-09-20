import { isAvailable as isKernelSUAvailable, spawn } from './kernelsu.js';

const OUTPUT_LIMIT = 1024 * 1024;
const EXECUTABLES = Object.freeze(['/system/bin/chrootctl','/data/adb/modules/chrootctl-magisk/system/bin/chrootctl']);
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const STATIC = Object.freeze({
  version: { args:['--json','version'], commands:['version'], mutating:false },
  chrootsList: { args:['--json','chroots','list'], commands:['chroots.list','chroots list'], mutating:false },
});

export class ChrootCtlError extends Error {
  constructor(message, details={}) { super(message); this.name='ChrootCtlError'; this.code=details.code||'WEBUI_BACKEND_ERROR'; this.exitCode=details.exitCode??null; this.command=details.command||null; this.stderr=details.stderr||''; this.envelope=details.envelope||null; }
}
function safeName(value, field='name') { const v=String(value??'').trim(); if(!NAME_RE.test(v)) throw new ChrootCtlError(`Invalid ${field}`,{code:'WEBUI_INVALID_ARGUMENT'}); return v; }
function spec(operation,payload={}) {
  if (STATIC[operation]) return STATIC[operation];
  const name=safeName(payload.name);
  switch(operation) {
    case 'chrootShow': return {args:['--json','--name',name,'chroots','show'],commands:['chroots.show','chroots show'],mutating:false};
    case 'chrootStatus': return {args:['--json','--name',name,'status','--details'],commands:['status'],mutating:false};
    case 'chrootStart': return {args:['--json','--name',name,'mount'],commands:['mount'],mutating:true};
    case 'chrootStop': return {args:['--json','--name',name,'unmount'],commands:['unmount','chroots.stop'],mutating:true};
    case 'chrootRestart': return {composite:'remount',name,commands:['remount'],mutating:true};
    case 'chrootRename': { const next=safeName(payload.newName,'new name'); if(next===name) throw new ChrootCtlError('New name must be different',{code:'WEBUI_INVALID_ARGUMENT'}); return {args:['--json','--name',name,'chroots','rename',next],commands:['chroots.rename','chroots rename'],mutating:true}; }
    case 'chrootRemove': { const confirm=safeName(payload.confirm,'confirmation'); if(confirm!==name) throw new ChrootCtlError('Confirmation must exactly match the chroot name',{code:'WEBUI_CONFIRMATION_REQUIRED'}); return {args:['--json','--name',name,'chroots','remove','--yes'],commands:['chroots.remove','chroots remove'],mutating:true}; }
    default: throw new ChrootCtlError(`Unsupported WebUI operation: ${operation}`,{code:'WEBUI_OPERATION_NOT_ALLOWED'});
  }
}
function appendBounded(current,chunk){const next=current+String(chunk??'');if(next.length>OUTPUT_LIMIT)throw new ChrootCtlError('Backend output exceeded the WebUI safety limit',{code:'WEBUI_OUTPUT_LIMIT'});return next;}
function runProcess(executable,args){return new Promise((resolve,reject)=>{let stdout='',stderr='',settled=false,child;const finish=(fn,v)=>{if(settled)return;settled=true;fn(v)};try{child=spawn(executable,args,{})}catch(e){reject(e);return}child.stdout.on('data',c=>{try{stdout=appendBounded(stdout,c)}catch(e){finish(reject,e)}});child.stderr.on('data',c=>{try{stderr=appendBounded(stderr,c)}catch(e){finish(reject,e)}});child.on('error',e=>finish(reject,e));child.on('exit',code=>finish(resolve,{exitCode:Number.isFinite(Number(code))?Number(code):1,stdout,stderr,executable}))})}
async function runAllowedOperation(s){let last=null;for(const executable of EXECUTABLES){try{const result=await runProcess(executable,[...s.args]);if(result.exitCode!==126&&result.exitCode!==127)return result;last=result}catch(error){last={error,executable}}}throw new ChrootCtlError('Unable to start the bundled chrootctl backend',{code:'WEBUI_BACKEND_UNAVAILABLE',exitCode:last?.exitCode??null,stderr:last?.stderr||''})}
function parseEnvelope(s,result){let envelope;try{envelope=JSON.parse(result.stdout)}catch(_){throw new ChrootCtlError('Backend returned invalid JSON',{code:'WEBUI_INVALID_JSON',exitCode:result.exitCode,stderr:result.stderr})}if(!envelope||typeof envelope!=='object'||Array.isArray(envelope))throw new ChrootCtlError('Backend returned an invalid response envelope',{code:'WEBUI_INVALID_ENVELOPE'});const command=String(envelope.command||'');if(envelope.schema_version!==1||!s.commands.includes(command)||typeof envelope.ok!=='boolean')throw new ChrootCtlError('Backend response contract is incompatible with this WebUI',{code:'WEBUI_CONTRACT_MISMATCH',exitCode:result.exitCode,command,stderr:result.stderr,envelope});if(!envelope.ok||result.exitCode!==0)throw new ChrootCtlError(envelope.error?.message||envelope.error?.code||'chrootctl command failed',{code:envelope.error?.code||'WEBUI_BACKEND_FAILURE',exitCode:result.exitCode,command,stderr:result.stderr,envelope});return envelope;}
export function isAvailable(){return isKernelSUAvailable()}
export async function invoke(operation,payload={}){const s=spec(operation,payload);if(!isKernelSUAvailable())throw new ChrootCtlError('Open this page from a KernelSU-compatible module WebUI host',{code:'WEBUI_BRIDGE_UNAVAILABLE'});if(s.composite==='remount'){const down={args:['--json','--name',s.name,'unmount'],commands:['unmount'],mutating:true};parseEnvelope(down,await runAllowedOperation(down));const up={args:['--json','--name',s.name,'mount'],commands:['mount'],mutating:true};return parseEnvelope(up,await runAllowedOperation(up));}return parseEnvelope(s,await runAllowedOperation(s));}
