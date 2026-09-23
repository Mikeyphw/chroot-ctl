import assert from 'node:assert/strict';
import { exec, selfTest, spawn } from './webroot/kernelsu.js';

function unquote(token) {
  // Enough to model POSIX single-quote encoding used by the adapter.
  if (token.startsWith("'") && token.endsWith("'")) {
    return token.slice(1,-1).replace(/'\\''/g, "'");
  }
  return token;
}

{
  let seen;
  globalThis.ksu = {
    exec(command, options, callbackName) {
      seen={command,options,callbackName};
      globalThis[callbackName](0, '{"ok":true}', '');
    }
  };
  const payload=JSON.stringify({protocolVersion:1,payload:{name:"O'Brien",value:'$HOME `id` "x"\nline'}});
  const result=await exec('/data/adb/chrootctl/bin/chrootctl',['app','query','--request-json',payload],{});
  assert.equal(result.exitCode,0);
  assert.equal(seen.command.startsWith("'/data/adb/chrootctl/bin/chrootctl' 'app' 'query' '--request-json' "),true);
  assert.equal(seen.command.includes("'O'\\''Brien'"),false); // JSON is one quoted shell token, not re-tokenized.
  assert.equal(result.stdout,'{"ok":true}');
}

{
  let seen;
  globalThis.ksu = {
    spawn(command,argsJson,optionsJson,callbackName) {
      seen={command,args:JSON.parse(argsJson),callbackName};
      const callback=globalThis[callbackName];
      queueMicrotask(() => {
        // Match the current KernelSU manager ABI: stdout/stderr call emit('data').
        callback.stdout.emit('data','{"type":"operation_succeeded"}\n');
        callback.emit('exit',0);
      });
    }
  };
  const payload=JSON.stringify({value:"O'Brien $HOME `id`\nnext"});
  const child=spawn('/data/adb/chrootctl/bin/chrootctl',['app','run','--request-json',payload,'--events','ndjson'],{});
  let stdout='';
  let stderr='';
  child.stdout.on('data',chunk=>{stdout+=String(chunk)});
  child.stderr.on('data',chunk=>{stderr+=String(chunk)});
  await new Promise((resolve,reject)=>{child.on('exit',resolve);child.on('error',reject)});
  assert.match(stdout,/operation_succeeded/,'native callback stdout emit must feed data listeners');
  assert.equal(stderr,'');
  assert.deepEqual(seen.args,[],'native KSU argv must be empty because the host concatenates raw argv into a shell command');
  assert.ok(seen.command.startsWith("'/data/adb/chrootctl/bin/chrootctl' 'app' 'run' '--request-json' "));
  assert.ok(seen.command.includes(String.raw`O'\''Brien`),'single quotes inside JSON must survive the root-shell boundary');
  assert.equal(globalThis[seen.callbackName],undefined);
}

// Current KernelSU posts exit first and a separate error event for non-zero
// results. The adapter must retain that diagnostic before exposing final exit.
{
  let callbackName='';
  globalThis.ksu = {
    spawn(_command,argsJson,_optionsJson,name) {
      callbackName=name;
      assert.deepEqual(JSON.parse(argsJson),[]);
      const callback=globalThis[name];
      queueMicrotask(() => {
        callback.emit('exit',-1);
        queueMicrotask(() => {
          const error=new Error('libsu failed to start root-shell job --request-json {\"password\":\"swordfish\",\"token\":\"abc123\"} https://example.invalid/file?access_token=urlsecret&x=1 Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig');
          error.exitCode=-1;
          callback.emit('error',error);
        });
      });
    }
  };
  const child=spawn('/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl',['version'],{});
  let publicErrors=0;
  child.on('error',()=>{publicErrors+=1});
  const code=await new Promise((resolve,reject)=>{child.on('exit',resolve);setTimeout(()=>reject(new Error('non-zero KSU spawn did not settle')),1000)});
  assert.equal(code,-1);
  assert.equal(publicErrors,0,'non-zero process result is not a transport replay signal');
  assert.equal(child.bridgeError?.exitCode,-1);
  assert.match(child.bridgeError?.message||'',/libsu failed/);
  assert.doesNotMatch(child.bridgeError?.message||'',/swordfish|abc123|urlsecret|eyJhbGciOiJIUzI1NiJ9/,'native bridge diagnostics must redact request secrets before exposure');
  assert.match(child.bridgeError?.message||'',/<redacted>/);
  assert.equal(globalThis[callbackName],undefined,'native callback must be cleaned only after the follow-up error is captured');
}
// Hosts that only emit a non-zero exit must still settle and clean up rather
// than hanging forever waiting for a follow-up error event.
{
  let callbackName='';
  globalThis.ksu = {
    spawn(_command,_argsJson,_optionsJson,name) {
      callbackName=name;
      const callback=globalThis[name];
      queueMicrotask(() => callback.emit('exit',7));
    }
  };
  const child=spawn('/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl',['version'],{});
  const started=Date.now();
  const code=await new Promise((resolve,reject)=>{child.on('exit',resolve);child.on('error',reject);setTimeout(()=>reject(new Error('exit-only KSU host did not settle')),1200)});
  assert.equal(code,7);
  assert.ok(Date.now()-started>=450,'non-zero exit should wait briefly for a possible KSU error event');
  assert.equal(globalThis[callbackName],undefined);
}
console.log('KernelSU real WebViewInterface transport tests passed');

{
  const commands=[];
  globalThis.ksu={exec(command,options,callbackName){commands.push(command);queueMicrotask(()=>globalThis[callbackName](0,command.includes("/system/bin/id")?"uid=0(root)\n":"chrootctl 0.11.0\n",""));},spawn(){},moduleInfo(){return '{"id":"chrootctl"}';}};
  const result=await selfTest('/data/adb/chrootctl/bin/chrootctl',1000);
  assert.equal(result.ok,true); assert.equal(result.identity,'uid=0(root)'); assert.equal(result.backend,'chrootctl 0.11.0');
  assert.ok(commands[0].includes("'/system/bin/id'")); assert.ok(commands[1].includes("'/data/adb/chrootctl/bin/chrootctl' 'version'"));
}
{
  globalThis.ksu={exec(){}};
  await assert.rejects(exec('/system/bin/true',[],{},25),(error)=>error?.code==='KSU_EXEC_TIMEOUT');
}
