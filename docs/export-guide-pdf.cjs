// Export the checked-in Markdown without changing its operating instructions.
// Requires marked and playwright-core (set PLAYWRIGHT_MODULE if installed elsewhere).
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { marked } = require('../LR-Web/node_modules/marked');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const folder = __dirname;
const source = fs.readFileSync(path.join(folder, '用户使用指南.md'), 'utf8');
const output = path.join(folder, '图书馆机器人用户使用指南.pdf');
const headings = source.split(String.fromCharCode(10)).filter(line => line.startsWith('## ')).map(line => line.slice(3));
let index = 0;
let content = marked.parse(source.slice(source.indexOf('## ')), { gfm: true });
content = content.replace(new RegExp('<h2>(.*?)</h2>', 'g'), (_, title) => {
  index += 1;
  return `<h2 id='section-${index}' class='${[6, 9, 10].includes(index) ? 'chapter' : ''}'>${title}</h2>`;
});
content = content.replace(new RegExp('<p><img src="([^"]+)" alt="([^"]*)"></p>', 'g'), (_, src, label) => {
  const image = fs.readFileSync(path.join(folder, src)).toString('base64');
  return `<figure class='${src.includes('phone') ? 'phone' : 'desktop'}'><img src='data:image/png;base64,${image}' alt='${label}'><figcaption>${label}</figcaption></figure>`;
});
content = content.replace('<a href="../deploy/HOTSPOT-ACCESS.md">热点与访客访问部署说明</a>', '项目文件 <code>deploy/HOTSPOT-ACCESS.md</code>《热点与访客访问部署说明》');
const toc = headings.map((title, i) => `<li><a href='#section-${i + 1}'>${title}</a></li>`).join('');
const sections = content.split(new RegExp('(?=<h2 id=)')).filter(part => part.trim());
content = [[1], [2], [3], [4, 5], [6], [7], [8], [9], [10, 11]].map(group => `<section class='sheet'>${group.map(number => sections[number - 1]).join('')}</section>`).join('');
const html = `<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>图书馆机器人用户使用指南</title><style>
@page { size: A4; margin: 18mm 17mm 19mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font: 10.2pt/1.6 'Noto Sans CJK SC',sans-serif; color: #23324a; }
h1,h2,h3 { color: #123d72; break-after: avoid; }
h1 { font-size: 30pt; line-height: 1.5; margin: 9mm 0 5mm; }
h2 { font-size: 16pt; margin: 6mm 0 3mm; padding-bottom: 2mm; border-bottom: 1px solid #c9dcf1; }
h3 { font-size: 11.5pt; margin: 4mm 0 2mm; }
p { margin: 2.8mm 0; orphans: 3; widows: 3; }
ol,ul { padding-left: 6mm; margin: 2.8mm 0; }
li { margin: 1.4mm 0; orphans: 2; widows: 2; }
strong { color: #163e6b; font-weight: 700; }
code { font: 9.4pt/1.6 'Noto Sans CJK SC',sans-serif; color: #114e89; background: #eef5fc; padding: .3mm 1mm; border-radius: 1mm; overflow-wrap: anywhere; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0; font-size: 9.2pt; table-layout: fixed; }
thead { display: table-header-group; }
th { text-align: left; background: #e8f1fc; color: #154c80; }
td,th { border: 1px solid #d7e2ee; padding: 1.8mm 3mm; vertical-align: top; overflow-wrap: anywhere; }
tr { break-inside: avoid; }
th:first-child,td:first-child { width: 29%; }
a { color: #1265b0; text-decoration: none; }
figure { margin: 5mm auto; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #dde7f0; border-radius: 3mm; }
.phone img { height: 108mm; width: auto; }
.desktop img { width: 158mm; height: auto; }
figcaption { color: #6b7d94; font-size: 8.5pt; margin-top: 1.5mm; }
.cover { break-after: page; }
.brand { font-size: 11pt; letter-spacing: 2pt; color: #146ed0; border-top: 4px solid #1677ff; padding-top: 7mm; }
.subtitle { font-size: 13pt; color: #526e92; margin-bottom: 9mm; }
.note { background: #fff6e8; border-left: 3px solid #e1a23d; padding: 4mm 5mm; line-height: 1.8; }
.meta { font-size: 9pt; color: #627991; margin-top: 5mm; }
.toc { margin-top: 9mm; }
.toc h2 { margin-top: 0; }
.toc ol { list-style: none; padding: 0; columns: 2; column-gap: 8mm; font-size: 9.5pt; }
.toc li { break-inside: avoid; padding: 1.5mm 0; }
.sheet { break-before: page; }
.sheet > h2:first-child { margin-top: 0; }
</style></head><body>
<section class='cover'><div class='brand'>智巡 · LIBRARY ROBOT</div><h1>图书馆机器人<br>用户使用指南</h1><p class='subtitle'>手机 · 平板 · 电脑<br>连接、登录与日常操作</p>
<div class='note'><strong>当前部署说明</strong><br>机器人热点尚未启用。本指南中的热点连接流程用于启用并验收后的正式交付；当前维护访问方式见第九节。</div>
<p class='meta'>部署状态核对：2026 年 10 月 23 日<br>适用对象：图书馆机器人操作人员</p>
<nav class='toc'><h2>目录</h2><ol>${toc}</ol></nav></section><main>${content}</main></body></html>`;
const htmlPath = path.join(folder, '.guide-print.html');
(async () => {
  fs.writeFileSync(htmlPath, html);
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/home/boreas/.cache/ms-playwright/chromium-1169/chrome-linux/chrome', headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
    await page.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(image => image.decode())); });
    const inspection = await page.evaluate(() => ({ sections: document.querySelectorAll('main h2').length, images: [...document.images].map(image => ({ complete: image.complete, width: image.naturalWidth })), textLength: document.querySelector('main').innerText.length }));
    if (inspection.sections !== 11 || inspection.images.length !== 2 || inspection.images.some(image => !image.width)) throw new Error('Content or images missing');
    await page.pdf({ path: output, format: 'A4', preferCSSPageSize: true, printBackground: true, displayHeaderFooter: true, tagged: true, outline: true, headerTemplate: '<div></div>', footerTemplate: `<div style='width:100%;font:8px sans-serif;color:#78879b;padding:0 17mm;display:flex;justify-content:space-between'><span>LIBRARY ROBOT | USER GUIDE</span><span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>` });
    console.log(JSON.stringify({ output, bytes: fs.statSync(output).size, ...inspection }));
  } finally { await browser.close(); fs.unlinkSync(htmlPath); }
})().catch(error => { console.error(error); process.exit(1); });
