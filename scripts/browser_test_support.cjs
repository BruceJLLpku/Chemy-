const fs=require('node:fs');
const path=require('node:path');

function browserLaunchOptions(){
  const executablePath=process.env.CHEMY_TEST_CHROMIUM||process.env.CHEMY_BROWSER_EXECUTABLE;
  return {headless:true,...(executablePath?{executablePath}:{})};
}

function artifactPath(...parts){
  const base=path.resolve(__dirname,'../output');
  const file=path.resolve(base,...parts);
  if(!file.startsWith(base+path.sep))throw Error('Test artifacts must stay inside output/');
  fs.mkdirSync(path.dirname(file),{recursive:true});
  return file;
}

async function isolateAccountServices(page){
  // Exercise the bundled SDK with fixture credentials; never contact a real project.
  await page.route('**/account-config.json',route=>route.fulfill({json:{url:'https://test.supabase.co',publishableKey:'public-test'}}));
  await page.route(/^https?:\/\/[^/]*\.supabase\.co(?::\d+)?\//,route=>route.abort('blockedbyclient'));
  // Individual AI tests can override this with their local mocked compose route.
  await page.route('**/ai-config.json*',route=>route.fulfill({json:{mode:'local',backendUrl:''}}));
}

module.exports={browserLaunchOptions,artifactPath,isolateAccountServices};
