// Manual browser check of the chat document picker against documents_hub_server.py (real hub, core, MinerU worker and, with E2E_LLM_BASE_URL, a real local model).
//   node e2e/chat-documents.mjs <hub port> <directory with northwind.pdf and complex.pdf>
import { chromium } from '@playwright/test';

const [port, samples] = process.argv.slice(2);
const base = `http://127.0.0.1:${port}/web/`;
const browser = await chromium.launch();
const results = [];
const note = (ok, label) => { results.push(ok); console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}`); };

for (const [name, viewport] of [['desktop', { width: 1280, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/40[0-9]|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  const attachment = () => page.getByLabel('Document attachment');
  const ask = async (text) => {
    const before = await page.getByRole('log', { name: 'Conversation' }).locator('article').count();
    await page.getByRole('textbox', { name: 'Message' }).fill(text);
    await page.getByRole('button', { name: 'Send' }).click();
    await page.getByRole('log', { name: 'Conversation' }).locator('article').nth(before + 1).waitFor({ timeout: 180000 });
    return page.getByRole('log', { name: 'Conversation' }).locator('article').nth(before + 1).innerText();
  };
  const choose = async (title) => {
    await page.getByRole('button', { name: /Attach a document|Replace/ }).click();
    await page.getByRole('dialog', { name: 'Choose a document' }).getByRole('button', { name: `Use: ${title}` }).click();
  };

  await page.goto(base + '#/login');
  await page.getByLabel(/username/i).fill('owner');
  await page.getByLabel(/password/i).fill('correct-password');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByRole('navigation', { name: 'Main' }).waitFor();

  // two ready documents
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: /^Library/ }).click();
  await page.getByRole('link', { name: 'Documents' }).click();
  for (const [file, title] of [['northwind.pdf', `Vendor requirements ${name}`], ['complex.pdf', `Capacity report ${name}`]]) {
    await page.setInputFiles('input[type=file]', `${samples}/${file}`);
    await page.getByLabel('Title (optional)').fill(title);
    await page.getByRole('button', { name: 'Upload' }).click();
    await page.getByRole('article', { name: new RegExp(title) }).getByText(/●\s*Ready/).first().waitFor({ timeout: 240000 });
  }
  note(true, `${name}: two documents uploaded and ready`);

  // attach in a brand-new conversation, ask, follow up
  await page.getByRole('link', { name: 'Chat' }).click();
  await page.getByRole('button', { name: /New chat record/ }).click();
  note((await page.getByRole('button', { name: 'Attach a document' }).count()) === 1 && (await attachment().innerText()).includes('Attach'), `${name}: a new conversation starts with nothing attached`);
  await choose(`Vendor requirements ${name}`);
  note((await attachment().innerText()).includes(`Answering from: Vendor requirements ${name}`), `${name}: indicator "Answering from: <title>" after attaching`);
  const first = await ask('How long must audit logs be kept?');
  note(/ninety|90/i.test(first) && new RegExp(`From pages .* of “Vendor requirements ${name}”`).test(first), `${name}: answered from the document with page citations — ${first.replace(/\s+/g, ' ').slice(0, 150)}`);
  const follow = await ask('What is the deadline for the first compliance confirmation?');
  note(/month|signature/i.test(follow) && /From pages/.test(follow), `${name}: the follow-up is answered from the same document with no re-attach — ${follow.replace(/\s+/g, ' ').slice(0, 120)}`);

  // refresh keeps it, with the transcript's pages
  await page.reload();
  await page.getByRole('navigation', { name: 'Main' }).waitFor();
  await attachment().waitFor({ timeout: 30000 });
  await page.getByText(/From pages/).nth(1).waitFor({ timeout: 30000 });
  note((await attachment().innerText()).includes(`Vendor requirements ${name}`) && (await page.getByText(/From pages/).count()) >= 2, `${name}: after a page refresh the attachment and the page citations are still there`);

  // another conversation has none
  await page.getByRole('button', { name: /New chat record/ }).click();
  note((await page.getByRole('button', { name: 'Attach a document' }).count()) === 1, `${name}: a new conversation has none`);
  const plain = await ask('What is two plus two?');
  note(/four|4/i.test(plain) && !/From pages/.test(plain), `${name}: ordinary chat is unchanged without an attachment — ${plain.replace(/\s+/g, ' ').slice(0, 80)}`);

  // switching back restores it; replace; remove
  await page.getByRole('button', { name: /^How long must audit logs/ }).first().click();
  await attachment().getByText(`Vendor requirements ${name}`).waitFor({ timeout: 30000 });
  note(true, `${name}: switching back to the first conversation restores its attachment`);
  await choose(`Capacity report ${name}`);
  await attachment().getByText(`Capacity report ${name}`).waitFor();
  const capacity = await ask('What is the capacity of Beta in TB?');
  note(/85/.test(capacity) && new RegExp(`of “Capacity report ${name}”`).test(capacity), `${name}: replaced: answers from the new document — ${capacity.replace(/\s+/g, ' ').slice(0, 120)}`);
  await page.getByRole('button', { name: 'Stop answering from this document' }).click();
  await page.getByRole('button', { name: 'Attach a document' }).waitFor();
  const after = await ask('What is two plus two?');
  note(!/From pages/.test(after), `${name}: removed: the next message is ordinary chat`);

  // a deleted document is shown as unavailable and gets the fixed reply
  await choose(`Vendor requirements ${name}`);
  await attachment().getByText(`Vendor requirements ${name}`).waitFor();
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: /^Library/ }).click();
  await page.getByRole('link', { name: 'Documents' }).click();
  await page.getByRole('button', { name: new RegExp(`Vendor requirements ${name}`) }).first().click();
  await page.getByRole('button', { name: 'Delete…' }).click();
  await page.getByRole('button', { name: 'Delete it' }).click();
  await page.getByRole('list', { name: 'Documents' }).getByText(`Vendor requirements ${name}`).waitFor({ state: 'detached', timeout: 120000 }); // the deletion has completed
  await page.getByRole('link', { name: 'Chat' }).click();
  await page.reload();
  await page.getByRole('navigation', { name: 'Main' }).waitFor();
  await page.getByRole('button', { name: /^How long must audit logs/ }).first().click();
  await attachment().getByRole('alert').waitFor({ timeout: 30000 });
  note(/no longer available/.test(await attachment().innerText()), `${name}: a deleted document is shown as no longer available`);
  const gone = await ask('What did it say about backups?');
  note(/can't find the document you attached/.test(gone) && !/From pages/.test(gone), `${name}: the fixed reply for a deleted document — ${gone.replace(/\s+/g, ' ').slice(0, 90)}`);
  await page.getByRole('button', { name: 'Stop answering from this document' }).click();
  await page.getByRole('button', { name: 'Attach a document' }).waitFor();

  note(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)), `${name}: no horizontal overflow`);
  await page.screenshot({ path: `/tmp/claude-1000/shots/chat-docs-${name}.png`, fullPage: true });
  note(errors.length === 0, `${name}: no console or page errors${errors.length ? ' ' + JSON.stringify(errors) : ''}`);
  await context.close();
}
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
