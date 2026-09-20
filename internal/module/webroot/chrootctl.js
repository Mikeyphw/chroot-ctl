import { isAvailable as isKernelSUAvailable, spawn } from './kernelsu.js';

const OUTPUT_LIMIT = 1024 * 1024;
const LINE_LIMIT = 128 * 1024;
const EXECUTABLES = Object.freeze(['/system/bin/chrootctl','/data/adb/modules/chrootctl-magisk/system/bin/chrootctl']);
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const USER_RE = /^[a-z_][a-z0-9_-]{0,31}$/i;
const CATALOG_RE = /^[A-Za-z0-9][A-Za-z0-9+_.:@-]{0,127}$/;
const APP_QUERY_ALLOW = new Set(['install.form','catalog.tools','catalog.addons','remote.rclone.status','remote.rclone.list']);
const APP_PREVIEW_ALLOW = new Set(['install.preview']);
const APP_RUN_ALLOW = new Set(['install.run']);
const OPERATIONS = Object.freeze({
  version: { args:['--json','version'], commands:['version'], mutating:false },
  chrootsList: { args:['--json','chroots','list'], commands:['chroots.list','chroots list'], mutating:false },
});

export class ChrootCtlError extends Error {
  constructor(message, details={}) { super(message); this.name='ChrootCtlError'; this.code=details.code||'WEBUI_BACKEND_ERROR'; this.exitCode=details.exitCode??null; this.command=details.command||null; this.stderr=details.stderr||''; this.envelope=details.envelope||null; this.operationId=details.operationId||null; }
}
function safeName(value, field='name') { const v=String(value??'').trim(); if(!NAME_RE.test(v)) throw new ChrootCtlError(`Invalid ${field}`,{code:'WEBUI_INVALID_ARGUMENT'}); return v; }
function safeUser(value) { const v=String(value??'').trim(); if(!USER_RE.test(v)) throw new ChrootCtlError('Invalid username',{code:'WEBUI_INVALID_ARGUMENT'}); return v; }
function safeCatalogList(value, field) { const out=Array.isArray(value)?value:[]; if(out.length>128) throw new ChrootCtlError(`Too many ${field}`,{code:'WEBUI_INVALID_ARGUMENT'}); return [...new Set(out.map(v=>String(v??'').trim()).filter(Boolean).map(v=>{if(!CATALOG_RE.test(v))throw new ChrootCtlError(`Invalid ${field} entry`,{code:'WEBUI_INVALID_ARGUMENT'});return v;}))]; }
function boundedText(value, field, max=128) { const v=String(value??'').trim(); if(v.length>max) throw new ChrootCtlError(`${field} is too long`,{code:'WEBUI_INVALID_ARGUMENT'}); return v; }
function safeInstallPayload(payload={}) {
  const p={
    distro: boundedText(payload.distro,'distro',32).toLowerCase(),
    name: safeName(payload.name),
    username: safeUser(payload.username),
    arch: boundedText(payload.arch,'architecture',32).toLowerCase(),
    preset: boundedText(payload.preset,'preset',64).toLowerCase(),
    profile: boundedText(payload.profile,'profile',64).toLowerCase(),
    desktop: boundedText(payload.desktop,'desktop',64).toLowerCase(),
    mirror: boundedText(payload.mirror,'mirror',128),
    tools: safeCatalogList(payload.tools,'tool'),
    addons: safeCatalogList(payload.addons,'add-on'),
  };
  for(const key of ['release','version']) { const v=boundedText(payload[key],key,128); if(v)p[key]=v; }
  if(payload.resume===true)p.resume=true;
  if(payload.repair===true)p.repair=true;
  if(payload.overwriteExisting===true)p.overwriteExisting=true;
  for(const key of ['previewId','payloadHash','resourceRevision']) if(payload[key]) p[key]=boundedText(payload[key],key,256);
  return p;
}
function spec(operation,payload={}) {
  if (OPERATIONS[operation]) return OPERATIONS[operation];
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
function requestId(prefix='webui'){return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,9)}`.replace(/[^A-Za-z0-9._:-]/g,'').slice(0,128)}
function bridgeRequest(operation,payload){return JSON.stringify({protocolVersion:1,requestId:requestId('webui'),operation,payload});}
function parseBridgeResponse(result){let r;try{r=JSON.parse(result.stdout.trim())}catch(_){throw new ChrootCtlError('Bridge returned invalid JSON',{code:'WEBUI_INVALID_JSON',exitCode:result.exitCode,stderr:result.stderr})}if(!r||r.protocolVersion!==1||typeof r.ok!=='boolean')throw new ChrootCtlError('Bridge response contract is incompatible with this WebUI',{code:'WEBUI_CONTRACT_MISMATCH',exitCode:result.exitCode,stderr:result.stderr,envelope:r});if(!r.ok||result.exitCode!==0)throw new ChrootCtlError(r.error?.message||r.error?.code||'Bridge request failed',{code:r.error?.code||'WEBUI_BACKEND_FAILURE',exitCode:result.exitCode,stderr:result.stderr,envelope:r});return r;}
async function appRequest(mode,operation,payload={}){const allowed=mode==='query'?APP_QUERY_ALLOW:APP_PREVIEW_ALLOW;if(!allowed.has(operation))throw new ChrootCtlError('WebUI bridge operation is not allow-listed',{code:'WEBUI_OPERATION_NOT_ALLOWED'});const args=['app',mode,'--request-json',bridgeRequest(operation,payload)];return parseBridgeResponse(await runAllowedOperation({args}));}
function runStreaming(executable,args,onLine){return new Promise((resolve,reject)=>{let pending='',stderr='',settled=false;const finish=(fn,v)=>{if(settled)return;settled=true;fn(v)};let child;try{child=spawn(executable,args,{})}catch(e){reject(e);return}child.stdout.on('data',chunk=>{try{pending+=String(chunk??'');if(pending.length>LINE_LIMIT)throw new ChrootCtlError('Bridge event line exceeded the safety limit',{code:'WEBUI_OUTPUT_LIMIT'});let i;while((i=pending.indexOf('\n'))>=0){const line=pending.slice(0,i).trim();pending=pending.slice(i+1);if(line)onLine(line)}}catch(e){finish(reject,e)}});child.stderr.on('data',chunk=>{try{stderr=appendBounded(stderr,chunk)}catch(e){finish(reject,e)}});child.on('error',e=>finish(reject,e));child.on('exit',code=>{try{const line=pending.trim();if(line)onLine(line);finish(resolve,{exitCode:Number.isFinite(Number(code))?Number(code):1,stderr,executable})}catch(e){finish(reject,e)}})})}
async function runAllowedStream(args,onLine){let last=null;for(const executable of EXECUTABLES){try{const result=await runStreaming(executable,args,onLine);if(result.exitCode!==126&&result.exitCode!==127)return result;last=result}catch(error){last={error,executable};if(error?.code==='WEBUI_OUTPUT_LIMIT')throw error}}throw new ChrootCtlError('Unable to start the bundled chrootctl backend',{code:'WEBUI_BACKEND_UNAVAILABLE',exitCode:last?.exitCode??null,stderr:last?.stderr||''})}

export function isAvailable(){return isKernelSUAvailable()}
export async function invoke(operation,payload={}){const s=spec(operation,payload);if(!isKernelSUAvailable())throw new ChrootCtlError('Open this page from a KernelSU-compatible module WebUI host',{code:'WEBUI_BRIDGE_UNAVAILABLE'});if(s.composite==='remount'){const down={args:['--json','--name',s.name,'unmount'],commands:['unmount'],mutating:true};parseEnvelope(down,await runAllowedOperation(down));const up={args:['--json','--name',s.name,'mount'],commands:['mount'],mutating:true};return parseEnvelope(up,await runAllowedOperation(up));}return parseEnvelope(s,await runAllowedOperation(s));}
export async function installForm(distro=''){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});const payload={};if(distro)payload.distro=boundedText(distro,'distro',32);return appRequest('query','install.form',payload);}
export async function catalog(kind,distro=''){if(kind!=='tools'&&kind!=='addons')throw new ChrootCtlError('Unsupported catalog kind',{code:'WEBUI_INVALID_ARGUMENT'});const payload={};if(distro)payload.distro=boundedText(distro,'distro',32);return appRequest('query',`catalog.${kind}`,payload);}
export async function previewInstall(payload){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});return appRequest('preview','install.preview',safeInstallPayload(payload));}
export async function cancelOperation(operationId){const id=boundedText(operationId,'operation id',128);if(!/^[A-Za-z0-9._:-]+$/.test(id))throw new ChrootCtlError('Invalid operation id',{code:'WEBUI_INVALID_ARGUMENT'});return parseBridgeResponse(await runAllowedOperation({args:['app','cancel',id]}));}
export async function runInstall(payload,handlers={}){
  if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});
  const clean=safeInstallPayload(payload); if(!APP_RUN_ALLOW.has('install.run'))throw new ChrootCtlError('Install operation is not allow-listed',{code:'WEBUI_OPERATION_NOT_ALLOWED'});
  const args=['app','run','--request-json',bridgeRequest('install.run',clean),'--events','ndjson'];
  let operationId=null,terminal=null,bridgeFailure=null;
  const result=await runAllowedStream(args,line=>{
    let event;try{event=JSON.parse(line)}catch(_){throw new ChrootCtlError('Bridge returned invalid NDJSON',{code:'WEBUI_INVALID_JSON'})}
    if(event?.protocolVersion!==1)throw new ChrootCtlError('Bridge event protocol mismatch',{code:'WEBUI_CONTRACT_MISMATCH'});
    if(event.operationId)operationId=String(event.operationId);
    if(event.type==='bridge_error'&&event.ok===false)bridgeFailure=event;
    if(['operation_succeeded','operation_failed','operation_cancelled','operation_blocked'].includes(event.type))terminal=event;
    handlers.onEvent?.(event);
  });
  if(bridgeFailure)throw new ChrootCtlError(bridgeFailure.error?.message||'Install bridge request failed',{code:bridgeFailure.error?.code||'WEBUI_BACKEND_FAILURE',exitCode:result.exitCode,operationId,envelope:bridgeFailure,stderr:result.stderr});
  if(result.exitCode!==0||!terminal||terminal.type!=='operation_succeeded'){
    const payload=terminal?.payload||{};const code=payload.code||(terminal?.type==='operation_cancelled'?'OPERATION_CANCELLED':terminal?.type==='operation_blocked'?'OPERATION_BLOCKED':'INSTALL_FAILED');
    throw new ChrootCtlError(payload.message||`Install did not complete successfully`,{code,exitCode:result.exitCode,operationId,envelope:terminal,stderr:result.stderr});
  }
  return {operationId,event:terminal,result:terminal.payload?.result??null};
}

function safeTransferPath(value,required=true){const v=boundedText(value,'archive path',1024);if(required&&!v)throw new ChrootCtlError('Archive path is required',{code:'WEBUI_INVALID_ARGUMENT'});if(v.includes('\0')||/[\r\n]/.test(v))throw new ChrootCtlError('Invalid archive path',{code:'WEBUI_INVALID_ARGUMENT'});if(v.startsWith('rclone://'))return safeRemoteLocation(v);if(v.includes('://'))throw new ChrootCtlError('Unsupported transfer location',{code:'WEBUI_INVALID_ARGUMENT'});return v;}
function safePassword(value){const v=String(value??'');if(v.length>512)throw new ChrootCtlError('Password is too long',{code:'WEBUI_INVALID_ARGUMENT'});return v;}
function cleanTransferPayload(kind,payload={}){if(kind==='import'){const p={archive:safeTransferPath(payload.archive),conflict:['rename','overwrite'].includes(payload.conflict)?payload.conflict:'rename',importStrategy:['auto','streaming','staged'].includes(payload.importStrategy)?payload.importStrategy:'auto',allowLegacyMetadata:payload.allowLegacyMetadata===true,postImport:'register'};if(payload.name)p.name=safeName(payload.name);if(payload.password)p.password=safePassword(payload.password);return p;}const p={name:safeName(payload.name)};const a=safeTransferPath(payload.archive,false);if(a)p.archive=a;if(payload.password)p.password=safePassword(payload.password);return p;}
async function transferRequest(mode,operation,payload){const args=['app',mode,'--request-json',bridgeRequest(operation,payload)];return parseBridgeResponse(await runAllowedOperation({args}));}
export async function previewTransferImport(payload){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});return transferRequest('preview','transfer.import_preview',cleanTransferPayload('import',payload));}
export async function previewTransferExport(payload){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});return transferRequest('preview','transfer.preview_export',cleanTransferPayload('export',payload));}
export async function runTransfer(kind,payload,preview,handlers={}){if(!['import','export'].includes(kind))throw new ChrootCtlError('Unsupported transfer kind',{code:'WEBUI_OPERATION_NOT_ALLOWED'});const clean=cleanTransferPayload(kind,payload);for(const k of ['previewId','payloadHash','resourceRevision'])if(preview?.[k])clean[k]=boundedText(preview[k],k,256);const operation=`transfer.${kind}`;const args=['app','run','--request-json',bridgeRequest(operation,clean),'--events','ndjson'];let operationId=null,terminal=null,bridgeFailure=null;const result=await runAllowedStream(args,line=>{let event;try{event=JSON.parse(line)}catch(_){throw new ChrootCtlError('Bridge returned invalid NDJSON',{code:'WEBUI_INVALID_JSON'})}if(event?.protocolVersion!==1)throw new ChrootCtlError('Bridge event protocol mismatch',{code:'WEBUI_CONTRACT_MISMATCH'});if(event.operationId)operationId=String(event.operationId);if(event.type==='bridge_error'&&event.ok===false)bridgeFailure=event;if(['operation_succeeded','operation_failed','operation_cancelled','operation_blocked'].includes(event.type))terminal=event;handlers.onEvent?.(event)});if(bridgeFailure)throw new ChrootCtlError(bridgeFailure.error?.message||'Transfer bridge request failed',{code:bridgeFailure.error?.code||'WEBUI_BACKEND_FAILURE',exitCode:result.exitCode,operationId,envelope:bridgeFailure,stderr:result.stderr});if(result.exitCode!==0||!terminal||terminal.type!=='operation_succeeded'){const p=terminal?.payload||{};throw new ChrootCtlError(p.message||'Transfer did not complete successfully',{code:p.code||(terminal?.type==='operation_cancelled'?'OPERATION_CANCELLED':'TRANSFER_FAILED'),exitCode:result.exitCode,operationId,envelope:terminal,stderr:result.stderr})}return {operationId,event:terminal,result:terminal.payload?.result??null};}


function safeRemoteLocation(value){const v=boundedText(value,'remote location',1024);if(!/^rclone:\/\/[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?:\/[^?#\r\n]*)?$/.test(v)||v.includes('..')||v.includes('@'))throw new ChrootCtlError('Invalid credential-free rclone location',{code:'WEBUI_INVALID_ARGUMENT'});return v;}
export async function rcloneStatus(){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});return appRequest('query','remote.rclone.status',{});}
export async function rcloneList(location){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});return appRequest('query','remote.rclone.list',{location:safeRemoteLocation(location)});}
export async function importRcloneConfig(path,handlers={}){if(!isKernelSUAvailable())throw new ChrootCtlError('KernelSU WebUI bridge is unavailable',{code:'WEBUI_BRIDGE_UNAVAILABLE'});const clean=safeTransferPath(path);if(clean.startsWith('rclone://'))throw new ChrootCtlError('rclone.conf must come from local managed staging',{code:'WEBUI_INVALID_ARGUMENT'});const args=['app','run','--request-json',bridgeRequest('remote.rclone.config_import',{path:clean}),'--events','ndjson'];let terminal=null,bridgeFailure=null,operationId=null;const result=await runAllowedStream(args,line=>{let event;try{event=JSON.parse(line)}catch(_){throw new ChrootCtlError('Bridge returned invalid NDJSON',{code:'WEBUI_INVALID_JSON'})}if(event?.protocolVersion!==1)throw new ChrootCtlError('Bridge event protocol mismatch',{code:'WEBUI_CONTRACT_MISMATCH'});if(event.operationId)operationId=String(event.operationId);if(event.type==='bridge_error'&&event.ok===false)bridgeFailure=event;if(['operation_succeeded','operation_failed','operation_cancelled','operation_blocked'].includes(event.type))terminal=event;handlers.onEvent?.(event)});if(bridgeFailure)throw new ChrootCtlError(bridgeFailure.error?.message||'Rclone config import failed',{code:bridgeFailure.error?.code||'WEBUI_BACKEND_FAILURE',operationId});if(result.exitCode!==0||terminal?.type!=='operation_succeeded')throw new ChrootCtlError(terminal?.payload?.message||'Rclone config import failed',{code:terminal?.payload?.code||'RCLONE_CONFIG_IMPORT_FAILED',operationId});return {operationId,result:terminal.payload?.result??null};}
