'use strict';
// UI fixtures only. No real accounts, downloads, microphone or backend calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {chromium}=require('../.tools/browser-qa/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const files=['popup.html','popup.css','popup.js','language-library.js','voice-setup.js','service-config.js','protocol.js','conversation.js','conversation.html','conversation-window.js'];
const fixture=()=>{
  let callState={phase:'stopped',text:'Перевод выключен.'},changed;
  window.fixtureCall=state=>{callState=state;changed?.({callStatus:{newValue:state}},'session');};
  window.fixtureLive=data=>{window.fixtureConversation=data;changed?.({liveConversation:{newValue:data}},'session');};
  window.fixtureFileStatus=value=>changed?.({transcriptFileStatus:{newValue:value}},'local');
  const catalog=[['ru','Русский'],['uk','Українська'],['en','English']].map(([language,display_name])=>({id:language+'-basic',language,gender:language==='ru'?'male':'female',display_name,version:'1',compatible:true,download_bytes:1000}));
  catalog.push({id:'en-male',language:'en',gender:'male',display_name:'English — male',version:'1',compatible:true,download_bytes:1000});
  const read=()=>JSON.parse(localStorage.getItem('fixture')||'{"voices":[],"selected":{}}');
  const save=data=>localStorage.setItem('fixture',JSON.stringify(data));
  window.chrome={runtime:{getManifest:()=>({version:'0.1.6'}),sendMessage:async message=>{
    const data=read();let result;
    if(message.type==='state')result={connected:true,balance_ms:300000};
    if(message.type==='call-state')result=callState;
    if(message.type==='conversation-state')result=window.fixtureConversation||{events:[],partial:{}};
    if(message.type==='transcript-destination')result={name:'Загрузки Chrome\\Call_Translator_Stennograms',path:'Загрузки Chrome\\Call_Translator_Stennograms',custom:false};
    if(message.type==='transcript-folder-choose'){window.fixtureFolderChanged=true;result={name:'Selected\\Call_Translator_Stennograms',path:'Selected\\Call_Translator_Stennograms',custom:true};}
    if(message.type==='open-transcripts'){window.fixtureHistoryOpened=true;result={};}
    if(message.type==='call-start'){window.fixtureLastStart=message;return new Promise(resolve=>{window.fixtureFinishStart=()=>{window.fixtureCall({phase:'active',text:'Всё готово, начинайте разговор.'});resolve({ok:true,result:callState});};});}
    if(message.type==='call-stop'){window.fixtureCall({phase:'stopped',text:'Перевод выключен.'});result=callState;}
    if(message.type==='native-status'){
      if(location.search.includes('missing'))return {ok:false,error:'fixture missing'};
      result={ready:!!data.voices.length,voices:data.voices,selected:data.selected,reason:null,capabilities:['remove-voice','language-variants']};
    }
    if(message.type==='voice-catalog')result={voices:catalog};
    if(message.type==='voice-install'){data.voices.push(catalog.find(voice=>voice.id===message.voice_id));save(data);result={};}
    if(message.type==='voice-select'){data.selected[message.direction]=message.voice_id;save(data);result={};}
    if(message.type==='voice-remove'){data.voices=data.voices.filter(voice=>voice.id!==message.voice_id);for(const direction of ['incoming','outgoing'])if(data.selected[direction]===message.voice_id)delete data.selected[direction];save(data);result={};}
    return {ok:true,result};
  }},storage:{local:{get:async()=>read(),set:async value=>save({...read(),...value})},onChanged:{addListener(fn){changed=fn;}}}};
};
async function main(){
  const server=http.createServer((request,response)=>{
    const file=new URL(request.url,'http://localhost').pathname.slice(1);
    if(!files.includes(file)){response.writeHead(404);response.end();return;}
    response.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');
    response.end(fs.readFileSync(path.join(root,'extension',file)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const chromePath=[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)']].filter(Boolean).map(folder=>path.join(folder,'Google/Chrome/Application/chrome.exe')).find(fs.existsSync);
  let browser;
  try{
    browser=await chromium.launch({executablePath:chromePath,headless:true});
    const page=await browser.newPage({viewport:{width:420,height:900}});await page.addInitScript(fixture);
    const url=`http://127.0.0.1:${server.address().port}/popup.html`;
    await page.goto(url);
    assert(!(await page.locator('body').innerText()).includes('Недоступные варианты отмечены в списке.'));
    assert(!(await page.locator('body').innerText()).includes('Выберите язык вместе с полом голоса. Например:'));
    assert((await page.locator('#settings-panel').innerText()).includes('Выберите язык.'));
    await page.locator('#view-conversation').click();
    assert.equal(await page.locator('#transcripts').innerText(),'История стенограмм');
    await page.locator('#transcripts').click();assert(await page.evaluate(()=>window.fixtureHistoryOpened));
    await page.locator('#transcript-folder').click();assert(await page.evaluate(()=>window.fixtureFolderChanged));
    assert((await page.locator('#transcript-path').innerText()).includes('Call_Translator_Stennograms'));
    await page.evaluate(()=>fixtureFileStatus({ok:true,text:'Стенограмма сохранена: старое сообщение.'}));
    assert(await page.locator('#transcript-file-status').isHidden(),'Successful-save notices must be absent, including old stored values');
    await page.evaluate(()=>fixtureFileStatus({ok:false,text:'Ошибка записи теста'}));
    assert.equal(await page.locator('#transcript-file-status').innerText(),'Ошибка записи теста');
    await page.evaluate(()=>fixtureFileStatus({ok:true,text:''}));
    await page.locator('#view-settings').click();
    assert(await page.locator('#catalog-refresh').isDisabled());
    await page.locator('#native-check').click();
    await page.waitForFunction(()=>!document.getElementById('catalog-refresh').disabled);
    assert((await page.locator('#native-state').innerText()).includes('Голоса ещё не установлены'));
    await page.locator('#catalog-refresh').click();
    await page.locator('#source-language').selectOption('ru:male');await page.waitForFunction(()=>!document.getElementById('target-language').disabled);
    assert.equal(await page.locator('#voices .voice').count(),1,'Selecting one side must show its own voice immediately');
    await page.locator('#target-language').selectOption('uk:female');await page.waitForFunction(()=>!document.getElementById('target-language').disabled);
    assert.equal(await page.locator('#voice-filters').count(),0,'No repeated gender choice in step 3');
    assert.equal(await page.locator('#source-language option[value="de:male"]').count(),0,'Languages absent from the verified catalog must be hidden');
    assert.equal(await page.locator('#source-language option[value="ru:female"]').count(),0,'Missing voices must be hidden');
    assert.equal(await page.locator('#source-language option[value^="vi:"]').count(),0,'Unready languages must be hidden');
    assert.equal(await page.locator('#voices .voice').count(),2);
    assert(!(await page.locator('#voices').innerText()).includes('English'));
    assert(await page.locator('#call-start').isDisabled());
    await page.locator('#voices button[data-voice-action=install]').nth(0).click();
    await page.waitForFunction(()=>!document.getElementById('catalog-refresh').disabled);
    await page.locator('#voices button[data-voice-action=install]').nth(1).click();
    await page.waitForFunction(()=>!document.getElementById('catalog-refresh').disabled);
    await page.waitForFunction(()=>!document.getElementById('call-start').disabled);
    await page.reload();await page.waitForFunction(()=>!document.getElementById('call-start').disabled);
    assert.equal(await page.locator('#source-language').inputValue(),'ru:male');
    assert.equal(await page.locator('#target-language').inputValue(),'uk:female');
    assert(await page.locator('#target-language option[value="ru:male"]').isDisabled(),'Same language is not a translation pair');
    await page.locator('#call-start').click();
    assert.deepEqual(await page.evaluate(()=>({source:window.fixtureLastStart.source,target:window.fixtureLastStart.language})),{source:'ru',target:'uk'});
    assert(await page.locator('#call-start').isDisabled());assert(await page.locator('#call-stop').isEnabled());
    assert((await page.locator('#call-heading').innerText()).includes('Подготовка'));
    await page.evaluate(()=>window.fixtureFinishStart());
    await page.waitForFunction(()=>document.getElementById('call-panel').dataset.phase==='active');
    assert(await page.locator('#call-start').isDisabled());assert(await page.locator('#call-stop').isEnabled());
    assert((await page.locator('#call-state').innerText()).includes('Всё готово'));
    await page.evaluate(()=>window.fixtureLive({source:'ru',target:'uk',guarded:true,suppressed_ms:1200,partial:{incoming:'Продовження розмови'},events:[
      {direction:'outgoing',sequence:1,original:'Последняя фраза проверки.',text:'Остання фраза перевірки.',timing:{translation_ms:240,tts_ms:180,after_recognition_ms:510}},
      {direction:'incoming',sequence:1,original:'Я вас добре чую.',text:'Я вас хорошо слышу.',timing:{translation_ms:260,tts_ms:190,after_recognition_ms:540}}
    ]}));
    assert((await page.locator('#outgoing-feed').innerText()).includes('Последняя фраза проверки.'));
    assert((await page.locator('#outgoing-feed').innerText()).includes('Остання фраза перевірки.'));
    assert((await page.locator('#incoming-feed').innerText()).includes('Я вас добре чую.'));
    assert((await page.locator('#incoming-feed').innerText()).includes('Я вас хорошо слышу.'));
    assert(await page.locator('#microphone-warning').isVisible());
    await page.screenshot({path:'build/conversation-popup-preview.png',fullPage:true});
    await page.locator('.diagnostics summary').click();
    const downloadPromise=page.waitForEvent('download');await page.locator('#export-metrics').click();
    const download=await downloadPromise;
    const exported=fs.readFileSync(await download.path(),'utf8');
    assert(!exported.includes('Последняя')&&!exported.includes('Остання')&&!exported.includes('original'),'Diagnostics export must not contain conversation text');
    assert.equal(JSON.parse(exported).samples.length,2);
    const sample=await page.evaluate(()=>window.fixtureConversation);
    const wide=await browser.newPage({viewport:{width:1100,height:800}});await wide.addInitScript(fixture);
    await wide.goto(url.replace('popup.html','conversation.html'));
    await wide.waitForFunction(()=>document.getElementById('call-state').textContent!=='Подключаемся к расширению…');
    await wide.evaluate(data=>window.fixtureLive(data),sample);
    const left=await wide.locator('#outgoing-feed').boundingBox(),right=await wide.locator('#incoming-feed').boundingBox();
    assert(right.x>left.x,'Standalone conversation must show participants side by side');
    await wide.screenshot({path:'build/conversation-window-preview.png',fullPage:true});
    await page.locator('#view-settings').click();
    await page.evaluate(()=>window.fixtureCall({phase:'active',text:'Всё готово, начинайте разговор.',balance_ms:290000}));
    assert(await page.locator('#settings-panel').isVisible(),'Balance updates must not switch away from settings');
    await page.locator('#view-conversation').click();
    await page.locator('#call-stop').click();
    await page.waitForFunction(()=>!document.getElementById('call-start').disabled);
    await page.evaluate(()=>window.fixtureCall({phase:'error',text:'Сбой передачи звука. Обновите вкладку Meet.',code:'protocol_error'}));
    assert((await page.locator('#call-heading').innerText()).includes('ошибка'));
    assert((await page.locator('#call-error-code').innerText()).includes('protocol_error'));
    assert(await page.locator('#call-stop').isDisabled());
    await page.locator('#view-settings').click();
    await page.evaluate(()=>document.getElementById('setup-details').open=true);
    await page.locator('#target-language').selectOption('en:male');await page.waitForFunction(()=>!document.getElementById('target-language').disabled);
    assert.equal(await page.locator('#voices .voice').count(),2);
    const englishMale=page.locator('#voices .voice[data-direction=outgoing]');
    await englishMale.locator('[data-voice-action=install]').click();
    await page.waitForFunction(()=>!document.getElementById('catalog-refresh').disabled);
    await page.waitForFunction(()=>!document.getElementById('call-start').disabled);
    await page.locator('#view-settings').click();await page.evaluate(()=>document.getElementById('setup-details').open=true);
    page.once('dialog',dialog=>dialog.accept());await englishMale.locator('[data-voice-action=remove]').click();
    await page.waitForFunction(()=>!document.getElementById('catalog-refresh').disabled);
    assert(await page.locator('#call-start').isDisabled(),'Deleting a selected voice must disable call start');
    assert(await englishMale.locator('[data-voice-action=install]').isEnabled());
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('fixture')).selected.outgoing),undefined);
    await page.screenshot({path:'build/setup-popup-preview.png',fullPage:true});
    const migration=await browser.newPage();await migration.addInitScript(fixture);
    await migration.addInitScript(()=>localStorage.setItem('fixture',JSON.stringify({
      voices:[{id:'ru-basic',language:'ru',gender:'male',version:'1'},{id:'en-male',language:'en',gender:'male',version:'1'}],
      selected:{incoming:'ru-basic',outgoing:'en-male'},callLanguages:{source:'ru',target:'en'},voiceGenders:{incoming:'all',outgoing:'male'}
    })));
    await migration.goto(url);await migration.waitForFunction(()=>!document.getElementById('call-start').disabled);
    assert.equal(await migration.locator('#source-language').inputValue(),'ru:male');
    assert.equal(await migration.locator('#target-language').inputValue(),'en:male');
    await page.goto(url+'?missing=1');await page.waitForFunction(()=>!document.getElementById('native-help').hidden);
    assert(await page.locator('#catalog-refresh').isDisabled());
    assert((await page.locator('#native-help').innerText()).includes('скачайте установщик'));
    const guide=await browser.newPage({viewport:{width:1120,height:1000}});
    await guide.goto('file:///'+path.join(root,'installer/INSTALL.html').replaceAll('\\','/'));
    assert.equal(await guide.locator('.step').count(),6);
    assert(!(await guide.locator('body').innerText()).includes('Адрес сервера вводить не требуется'));
    await guide.screenshot({path:'build/setup-instructions-preview.png'});
    console.log('Setup UI passed: missing/found program, selected ru/uk voices only, saved settings restored, six-step guide');
  }finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
