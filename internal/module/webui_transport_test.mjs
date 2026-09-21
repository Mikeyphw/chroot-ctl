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
      const child=globalThis[callbackName];
      queueMicrotask(() => {
        child.stdout.emit('data','{"type":"operation_succeeded"}\n');
        child.emit('exit',0);
      });
    }
  };
  const payload=JSON.stringify({value:"O'Brien $HOME `id`\nnext"});
  const child=spawn('/data/adb/chrootctl/bin/chrootctl',['app','run','--request-json',payload,'--events','ndjson'],{});
  await new Promise((resolve,reject)=>{child.on('exit',resolve);child.on('error',reject)});
  assert.equal(seen.command,'/data/adb/chrootctl/bin/chrootctl');
  assert.equal(seen.args[0],"'app'");
  assert.equal(unquote(seen.args[0]),'app');
  assert.equal(unquote(seen.args[3]),payload);
  assert.equal(globalThis[seen.callbackName],undefined);
}
console.log('KernelSU real WebViewInterface transport tests passed');

{
  const commands=[];
  globalThis.ksu={exec(command,options,callbackName){commands.push(command);queueMicrotask(()=>globalThis[callbackName](0,command.includes("/system/bin/id")?"uid=0(root)\n":"chrootctl 0.11.0\n",""));},spawn(){},moduleInfo(){return '{"id":"chrootctl-magisk"}';}};
  const result=await selfTest('/data/adb/chrootctl/bin/chrootctl',1000);
  assert.equal(result.ok,true); assert.equal(result.identity,'uid=0(root)'); assert.equal(result.backend,'chrootctl 0.11.0');
  assert.ok(commands[0].includes("'/system/bin/id'")); assert.ok(commands[1].includes("'/data/adb/chrootctl/bin/chrootctl' 'version'"));
}
{
  globalThis.ksu={exec(){}};
  await assert.rejects(exec('/system/bin/true',[],{},25),(error)=>error?.code==='KSU_EXEC_TIMEOUT');
}
