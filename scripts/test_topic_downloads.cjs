/* Full-topic download regression against a source tree or staged Pages tree.
 * CHEMY_TEST_SITE_DIR selects the local tree (default: dist). An isolated HTTP
 * server is started unless CHEMY_TEST_URL already points to a running site.
 * Use --all-topics to exercise all 18 downloads; the default tests equilibrium.
 */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const site = path.resolve(root, process.env.CHEMY_TEST_SITE_DIR || 'dist');
const output = path.join(root, 'output');
const report = {checks:[], errors:[], downloads:[], site};
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const mime = {'.html':'text/html', '.js':'text/javascript', '.json':'application/json', '.css':'text/css', '.pdf':'application/pdf', '.jpg':'image/jpeg', '.webp':'image/webp', '.png':'image/png', '.svg':'image/svg+xml'};
function check(name, ok) {assert.ok(ok, name);report.checks.push(name);console.log('PASS', name);}
function serveSite() {
  return http.createServer((req, res) => {
    let pathname;
    try {pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);} catch {res.writeHead(400);res.end();return;}
    const relative = pathname.replace(/^\/+/, '') || 'index.html';
    const file = path.resolve(site, relative);
    if (!file.startsWith(site + path.sep)) {res.writeHead(403);res.end();return;}
    fs.stat(file, (err, stat) => {
      if (err || !stat.isFile()) {res.writeHead(404);res.end();return;}
      res.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
      res.setHeader('Content-Length', stat.size);
      fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
    });
  });
}
(async () => {
  let browser, server;
  fs.mkdirSync(path.join(output, 'pdf'), {recursive:true});
  fs.mkdirSync(path.join(output, 'continuous'), {recursive:true});
  try {
    let base = process.env.CHEMY_TEST_URL;
    if (!base) {
      server = serveSite();
      await new Promise((resolve, reject) => {server.once('error', reject);server.listen(0, '127.0.0.1', resolve);});
      base = `http://127.0.0.1:${server.address().port}/`;
    }
    if (!base.endsWith('/')) base += '/';
    report.base = base;
    const launch = {headless:true};
    if (process.env.CHEMY_TEST_CHROMIUM) launch.executablePath = process.env.CHEMY_TEST_CHROMIUM;
    browser = await chromium.launch(launch);
    const page = await browser.newPage({viewport:{width:1450,height:960},acceptDownloads:true});
    page.on('pageerror', e => report.errors.push(e.message));
    await page.goto(base + '#equilibrium');
    await page.waitForFunction(() => typeof ready !== 'undefined' && ready);
    const topicSlugs = process.argv.includes('--all-topics') ? await page.evaluate(() => [...slugs]) : ['equilibrium'];
    for (const slug of topicSlugs) {
      if (new URL(page.url()).hash !== '#' + slug) {
        await page.goto(base + '#' + slug);
        await page.waitForFunction(slug => typeof ready !== 'undefined' && ready && slugByTopic[activeTopic] === slug, slug);
      }
      const links = await page.locator('#downloads a').evaluateAll(items => items.map(x => x.href));
      check(`${slug}: both full-topic links are available`, links.length === 2);
      const metadata = {};
      for (const [i, kind] of ['questions', 'answers'].entries()) {
        const manifest = JSON.parse(fs.readFileSync(path.join(site, 'export-parts', `${slug}-${kind}.json`), 'utf8'));
        check(`${slug} ${kind}: complete clean book is built`, manifest.complete && manifest.cleanBook);
        metadata[kind] = manifest.cleanBook;
        const url = new URL(links[i]);
        check(`${slug} ${kind}: versioned clean-book link`, url.pathname.endsWith(`/export-parts/${manifest.cleanBook.path}`) && url.searchParams.get('v') === `${manifest.bookVersion}-${manifest.profile}`);
      }
      await page.locator('#edition-select').selectOption('39');
      check(`${slug}: filtering keeps the complete topic links`, JSON.stringify(links) === JSON.stringify(await page.locator('#downloads a').evaluateAll(items => items.map(x => x.href))));
      for (const [i, kind] of ['questions', 'answers'].entries()) {
        const event = page.waitForEvent('download', {timeout:180000});
        await page.locator('#downloads a').nth(i).click();
        const download = await event;
        const target = path.join(output, 'pdf', `topic-${slug}-${kind}.pdf`);
        await download.saveAs(target);
        const actual = fs.readFileSync(target);
        const expected = metadata[kind];
        const built = fs.readFileSync(path.join(site, 'export-parts', expected.path));
        check(`${slug} ${kind}: actual PDF matches clean-book bytes and manifest`, actual.subarray(0,5).toString() === '%PDF-' && actual.length === expected.bytes && hash(actual) === expected.sha256 && hash(actual) === hash(built));
        report.downloads.push({slug,kind,file:path.relative(output,target),bytes:actual.length,sha256:hash(actual),pages:expected.pages});
      }
      check(`${slug}: single-question action remains available`, await page.locator('[data-download-question]').count() > 0);
    }
    check('No browser errors', report.errors.length === 0);
  } catch (error) {
    report.failure = String(error.stack || error);
    throw error;
  } finally {
    if (browser) await browser.close();
    if (server) await new Promise(resolve => server.close(resolve));
    fs.writeFileSync(path.join(output, 'continuous/download-checks.json'), JSON.stringify(report, null, 2) + '\n');
  }
})().catch(error => {console.error(error);process.exitCode=1;});
