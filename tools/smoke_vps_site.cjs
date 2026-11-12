'use strict';
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('../.tools/browser-qa/node_modules/playwright');
const base='https://ppsbot.pp.ua/call-translator-saas';
let phase='launch';
const networkErrors=[];
async function main(){
  const executablePath=[process.env.PROGRAMFILES,process.env['PROGRAMFILES(X86)']].filter(Boolean)
    .map(folder=>path.join(folder,'Google/Chrome/Application/chrome.exe')).find(file=>fs.existsSync(file));
  if(!executablePath)throw Error('Chrome unavailable');
  const browser=await chromium.launch({executablePath,headless:true,timeout:60000});
  try{
    const page=await browser.newPage({viewport:{width:1360,height:920}});
    page.on('requestfailed',request=>{const code=request.failure()?.errorText;if(code?.startsWith('net::'))networkErrors.push(code);});
    phase='account-navigation';
    await page.goto(base+'/account',{waitUntil:'domcontentloaded',timeout:60000});
    phase='account-ui';
    await page.locator('#signed-out').waitFor({state:'visible',timeout:30000});
    const login=await page.locator('#google-login').getAttribute('href');
    if(login!=='/call-translator-saas/auth/google')throw Error('Account login path differs');
    phase='account-screenshot';
    await page.screenshot({path:'build/vps-account-preview.png',fullPage:true});
    const report={vps_browser_account_rendered:true,google_login_button_visible:true,
      private_browser_profile_used:false,live_google_login_verified:false,full_meet_call_verified:false};
    phase='google-navigation';
    await page.locator('#google-login').click();
    await page.waitForURL(url=>url.hostname==='accounts.google.com',{timeout:30000});
    await page.waitForLoadState('domcontentloaded');
    const content=await page.locator('body').innerText();
    report.google_redirect_reached=true;
    report.google_redirect_uri_mismatch_detected=content.includes('redirect_uri_mismatch');
    fs.writeFileSync('build/vps-browser-smoke.json',JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(JSON.stringify({status:'failed',phase,error_type:error.name,network_errors:networkErrors}));process.exitCode=1;});
