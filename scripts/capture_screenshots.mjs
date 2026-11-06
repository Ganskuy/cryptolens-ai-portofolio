import {chromium} from '../frontend/node_modules/playwright/index.mjs';
const browser=await chromium.launch();
const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
await page.goto('http://localhost:3100');
await page.getByText('Bitcoin',{exact:true}).first().waitFor();
await page.screenshot({path:'docs/dashboard-desktop.png',fullPage:true});
await page.setViewportSize({width:390,height:844});
await page.screenshot({path:'docs/dashboard-mobile.png',fullPage:true});
await browser.close();
