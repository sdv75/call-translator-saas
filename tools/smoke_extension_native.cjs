'use strict';
// Own temporary Chrome profile; no Google/provider credentials or real account.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {chromium}=require('../.tools/browser-qa/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const [stageArg,outputArg,voiceArg]=process.argv.slice(2);
const stage=path.resolve(stageArg),output=path.resolve(outputArg),voices=path.resolve(voiceArg);
const identity='afdgmhaicjhehhhhlahpeinieglofgml';
async function main(){
  const chrome=[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)']].filter(Boolean)
    .map(folder=>path.join(folder,'Google/Chrome/Application/chrome.exe')).find(file=>fs.existsSync(file));
  if(!chrome)throw Error('Chrome not found');
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'ct-ext-native-'));
  let context;
  try{
    const windowsKeys=new Set(['SYSTEMROOT','WINDIR','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE','COMSPEC','PATH','PATHEXT']);
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>windowsKeys.has(key.toUpperCase())));
    Object.assign(env,{PYTHONUTF8:'1',CT_LOCAL_VOICE_ROOT:voices,
      'PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL':path.join(output,'runtime')});
    context=await chromium.launchPersistentContext(profile,{executablePath:chrome,headless:true,timeout:60000,env,
      ignoreDefaultArgs:['--disable-extensions'],args:['--enable-unsafe-extension-debugging','--disable-background-networking','--mute-audio']});
    const session=await context.browser().newBrowserCDPSession();
    const loaded=await session.send('Extensions.loadUnpacked',{path:path.join(stage,'extension')});
    if(loaded.id!==identity)throw Error('Unexpected unpacked extension ID');
    const page=await context.newPage();
    await page.goto(`chrome-extension://${identity}/popup.html`);
    const status=await page.evaluate(async()=>{
      const value=await chrome.runtime.sendMessage({type:'native-status'});
      return {ok:value?.ok,ready:value?.result?.ready,reason:value?.result?.reason,error:value?.error,
        languages:value?.result?.voices?.map(voice=>voice.language)};
    });
    fs.writeFileSync(path.join(output,'chrome-native-status.json'),JSON.stringify(status,null,2)+'\n');
    if(!status.ok || !status.ready){
      const direct=await page.evaluate(()=>new Promise(resolve=>{
        const port=chrome.runtime.connectNative('org.call_translator.saas.local');
        const timer=setTimeout(()=>{port.disconnect();resolve({timeout:true});},90000);
        port.onMessage.addListener(message=>{clearTimeout(timer);resolve({ready:message.ready,reason:message.reason,error:message.error});port.disconnect();});
        port.onDisconnect.addListener(()=>{clearTimeout(timer);resolve({error:chrome.runtime.lastError?.message});});
        port.postMessage({id:901,type:'status'});
      }));
      fs.writeFileSync(path.join(output,'chrome-native-direct.json'),JSON.stringify(direct,null,2)+'\n');
      throw Error('Native component not ready; see safe QA status files');
    }
    const report=await page.evaluate(async()=>{
      const status=await chrome.runtime.sendMessage({type:'native-status'});
      const languages=status.result.voices.map(voice=>voice.language);
      if(!languages.includes('uk') || !languages.includes('en'))throw Error('Both technical voices required');
      const preview=await chrome.runtime.sendMessage({type:'voice-preview',voice_id:'en-basic'});
      if(!preview?.ok || !preview.result?.audio)throw Error('Native voice preview failed');
      const binary=atob(preview.result.audio);
      if(!binary.startsWith('RIFF') || binary.slice(8,12)!=='WAVE' || binary.length<=44)throw Error('Invalid native WAV');
      return {chrome_extension_loaded:true,chrome_native_messaging_verified:true,local_synthesis_verified:true,
        wav_bytes:binary.length,real_account_used:false,full_meet_call_verified:false,chrome_tab_capture_verified:false};
    });
    fs.writeFileSync(path.join(output,'chrome-native-smoke.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  }finally{
    await context?.close();
    // Only this mkdtemp-created directory under the OS temp root is removable.
    if(path.resolve(profile).startsWith(path.resolve(os.tmpdir())+path.sep) && path.basename(profile).startsWith('ct-ext-native-'))
      fs.rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:200});
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
