'use strict';
// Fresh Chrome profile and synthetic text only; no real account, Meet or native host.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {chromium}=require('../.tools/browser-qa/node_modules/playwright');
const root=path.resolve(__dirname,'..'),identity='afdgmhaicjhehhhhlahpeinieglofgml';
async function main(){
  const chromePath=[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)']].filter(Boolean).map(folder=>path.join(folder,'Google/Chrome/Application/chrome.exe')).find(fs.existsSync);
  const output=fs.mkdtempSync(path.join(root,'build','transcript-files-')),profile=path.join(output,'profile'),downloads=path.join(output,'downloads');fs.mkdirSync(downloads);
  fs.mkdirSync(path.join(profile,'Default'),{recursive:true});
  fs.writeFileSync(path.join(profile,'Default','Preferences'),JSON.stringify({download:{default_directory:downloads,prompt_for_download:false}}));
  const context=await chromium.launchPersistentContext(profile,{executablePath:chromePath,headless:true,acceptDownloads:true,
    ignoreDefaultArgs:['--disable-extensions'],args:['--enable-unsafe-extension-debugging','--disable-background-networking']});
  try{
    const cdp=await context.browser().newBrowserCDPSession();
    await cdp.send('Extensions.loadUnpacked',{path:path.join(root,'extension')});
    await cdp.send('Browser.setDownloadBehavior',{behavior:'default',eventsEnabled:true});
    const worker=context.serviceWorkers().find(item=>item.url().includes(identity))||await context.waitForEvent('serviceworker');
    for(let attempt=0;attempt<50;attempt++){
      if(await worker.evaluate(()=>typeof CTJournal!=='undefined'))break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    await worker.evaluate(()=>{
      globalThis.fixtureFolder=null;globalThis.fixtureFail=false;globalThis.fixtureOpened=null;
      CTTranscriptFiles.configure({request:async(type,data={})=>{
        if(type==='transcript-folder-choose'){globalThis.fixtureChooseStart=data.downloaded;fixtureFolder='Selected/Call_Translator_Stennograms';}
        if(type==='transcript-folder-default')fixtureFolder=null;
        if(type==='transcript-folder-open')fixtureOpened=fixtureFolder||data.downloaded;
        if(type==='transcript-write'){
          if(fixtureFail)throw Error('Synthetic write failure');
          const root=await (await navigator.storage.getDirectory()).getDirectoryHandle('Call_Translator_Stennograms',{create:true});
          const folder=await root.getDirectoryHandle(data.day,{create:true});
          const file=await folder.getFileHandle(data.filename,{create:true}),stream=await file.createWritable();
          await stream.write(data.html);await stream.close();
        }
        return {custom:!!fixtureFolder,path:fixtureFolder};
      }});
    });
    const page=await context.newPage();
    const pageCdp=await context.newCDPSession(page),target=await pageCdp.send('Target.getTargetInfo');
    if(target.targetInfo.browserContextId)await cdp.send('Browser.setDownloadBehavior',{behavior:'default',eventsEnabled:true,browserContextId:target.targetInfo.browserContextId});
    await page.goto(`chrome-extension://${identity}/transcript.html`);
    await worker.evaluate(async()=>{
      const session={id:'synthetic-files-test',source:'ru',target:'en',started_at:1700000000000,state:'stopped'};
      await CTJournal.putSession(session);
      await CTJournal.record(session.id,{type:'translation',direction:'outgoing',sequence:1,original:'<script>fixture</script>',text:'Synthetic translation'});
    });
    await page.reload();await page.waitForFunction(()=>document.querySelector('#session').value==='synthetic-files-test');
    await page.locator('#export').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('сохранена в выбранной папке')).catch(async error=>{console.log(await page.locator('#status').innerText());throw error;});
    const dayFolder=path.join(downloads,'Call_Translator_Stennograms','2023-11-15');
    const localDayFolder=fs.existsSync(dayFolder)?dayFolder:path.join(downloads,'Call_Translator_Stennograms','2023-11-14');
    let files=fs.readdirSync(localDayFolder).filter(name=>name.endsWith('.html'));
    if(!files.length)console.log(await page.evaluate(async()=>({downloads:(await chrome.downloads.search({})).map(item=>({state:item.state,filename:item.filename,error:item.error})),status:(await chrome.storage.local.get('transcriptFileStatus')).transcriptFileStatus})));
    assert.equal(files.length,1,'Chrome should create one HTML in the configured default download folder');
    const html=fs.readFileSync(path.join(localDayFolder,files[0]),'utf8');assert(html.includes('Synthetic translation'));assert(html.includes('&lt;script&gt;fixture'));assert(!html.includes('<script>fixture'));
    await page.locator('#export').click();await page.waitForFunction(()=>!document.querySelector('#export').disabled);
    assert.equal(fs.readdirSync(localDayFolder).filter(name=>name.endsWith('.html')).length,1,'Retry must not duplicate a saved conversation');
    await page.locator('#choose-folder').click();await page.waitForFunction(()=>document.querySelector('#folder-name').textContent.includes('Selected'));
    assert((await worker.evaluate(()=>fixtureChooseStart)).includes('Call_Translator_Stennograms'),'Folder picker must receive the actual current downloads path');
    await page.reload();assert((await page.locator('#folder-name').innerText()).includes('Call_Translator_Stennograms'));
    await page.locator('#export').click();await page.waitForFunction(()=>!document.querySelector('#export').disabled);
    const custom=await worker.evaluate(async()=>{
      const root=await (await navigator.storage.getDirectory()).getDirectoryHandle('Call_Translator_Stennograms'),files=[];
      for await(const folder of root.values())for await(const handle of folder.values())files.push(await (await handle.getFile()).text());return files;
    });assert.equal(custom.length,1);assert(custom[0].includes('Synthetic translation'));assert(custom[0].includes('<style>'));
    const denied=await worker.evaluate(async()=>{
      fixtureFail=true;let failed=false;
      try{await CTTranscriptFiles.exportSession((await CTJournal.sessions())[0],{force:true});}catch{failed=true;}
      fixtureFail=false;
      return {failed,status:(await chrome.storage.local.get('transcriptFileStatus')).transcriptFileStatus,
        entries:(await CTJournal.entries('synthetic-files-test')).length};
    });assert(denied.failed);assert.equal(denied.status.ok,false);assert.equal(denied.entries,1);
    await worker.evaluate(async()=>{
      await CTJournal.putSession({id:'synthetic-interrupted',source:'ru',target:'en',started_at:1700000001000,state:'active'});
      await CTJournal.record('synthetic-interrupted',{type:'recognition',direction:'incoming',sequence:1,original:'Last synthetic phrase'});
      await CTTranscriptFiles.recover(await CTJournal.sessions());
    });
    const recovered=await worker.evaluate(async()=>{
      const root=await (await navigator.storage.getDirectory()).getDirectoryHandle('Call_Translator_Stennograms');let found=false;
      for await(const folder of root.values())for await(const handle of folder.values())if((await (await handle.getFile()).text()).includes('Last synthetic phrase'))found=true;return found;
    });assert(recovered,'Interrupted transcript must be exported on recovery');
    await worker.evaluate(async()=>{await CTTranscriptFiles.open();});
    assert.equal(await worker.evaluate(()=>fixtureOpened),'Selected/Call_Translator_Stennograms');
    await page.locator('#default-folder').click();await page.waitForFunction(()=>document.querySelector('#folder-name').textContent.includes('Call_Translator_Stennograms'));
    await worker.evaluate(async()=>{await CTTranscriptFiles.open();});
    assert((await worker.evaluate(()=>fixtureOpened)).includes('Call_Translator_Stennograms'));
    const downloadFailure=await worker.evaluate(async()=>{
      const original=chrome.downloads.download;chrome.downloads.download=async()=>{throw Error('Synthetic disk failure');};
      try{
        let failed=false;try{await CTTranscriptFiles.exportSession((await CTJournal.sessions())[0],{force:true});}catch{failed=true;}
        return {failed,status:(await chrome.storage.local.get('transcriptFileStatus')).transcriptFileStatus};
      }finally{chrome.downloads.download=original;}
    });assert(downloadFailure.failed);assert.equal(downloadFailure.status.ok,false);
    console.log('Transcript files passed: actual Chrome download, safe HTML, idempotence, dated folders, worker file write, interrupted recovery, folder-opening command and default reset. Native folder commands use a sandbox-backed test adapter; Explorer and the Windows picker are not launched.');
  }finally{await context.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
