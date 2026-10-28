#!/usr/bin/env node
// 永続プロファイルの一覧・説明（メタデータ）管理。
// メタデータは <META_DIR>/<site>.md（フロントマター付き Markdown）に置く。
// プロファイル本体（Cookie などが入るディレクトリ）の中身は一切読まない。
//
// 使い方:
//   node profiles.mjs list [--json]          既存プロファイル + 説明の一覧
//   node profiles.mjs show <site>            1 件の詳細（メタの本文含む）
//   node profiles.mjs path <site>            --profile に渡すパスだけを出力
//   node profiles.mjs register <site> --description "..." [--url ...] [--tags a,b] [--note "..."]
//   node profiles.mjs used <site>            last-login を今日の日付に更新
//   node profiles.mjs config                 解決済みのパス設定を表示

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function loadDotenv() {
  const out = {};
  for (const file of ['.env.example', '.env']) {   // .env が後勝ち
    const p = path.join(SKILL_DIR, file);
    if (!fs.existsSync(p))
      continue;
    for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
      const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)$/.exec(line);
      if (!m)
        continue;
      const v = m[2].trim().replace(/^(["'])(.*)\1$/, '$2');
      if (v)
        out[m[1]] = v;
    }
  }
  return out;
}

function resolveConfig() {
  const dotenv = loadDotenv();
  const pick = key => process.env[key] || dotenv[key] || '';
  const localAppData = process.env.LOCALAPPDATA
    || (process.platform === 'win32'
      ? path.join(os.homedir(), 'AppData', 'Local')
      : path.join(os.homedir(), '.local', 'share'));
  const expand = s => s
    .replace(/%LOCALAPPDATA%/gi, localAppData)
    .replace(/\$LOCALAPPDATA\b/g, localAppData)
    .replace(/^~(?=[\\/]|$)/, os.homedir());

  const root = path.resolve(expand(pick('BROWSER_PROFILES_ROOT')
    || path.join(localAppData, 'claude-browser-profiles')));
  const meta = path.resolve(expand(pick('BROWSER_PROFILES_META') || path.join(root, '_meta')));
  return { root, meta };
}

const { root: ROOT, meta: META } = resolveConfig();

const isProfileDir = name => !name.startsWith('_') && !name.startsWith('.');

function listProfiles() {
  if (!fs.existsSync(ROOT))
    return [];
  return fs.readdirSync(ROOT, { withFileTypes: true })
    .filter(e => e.isDirectory() && isProfileDir(e.name))
    .map(e => e.name)
    .sort();
}

// フロントマターは「key: value」だけの浅い形式に限定（YAML パーサ依存を持たないため）
function readMeta(site) {
  const file = path.join(META, `${site}.md`);
  if (!fs.existsSync(file))
    return null;
  const raw = fs.readFileSync(file, 'utf8');
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(raw);
  if (!m)
    return { file, fields: {}, body: raw.trim() };
  const fields = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+)\s*:\s*(.*)$/.exec(line);
    if (kv)
      fields[kv[1]] = kv[2].trim().replace(/^(["'])(.*)\1$/, '$2');
  }
  return { file, fields, body: m[2].trim() };
}

function writeMeta(site, fields, body) {
  fs.mkdirSync(META, { recursive: true });
  const order = ['name', 'description', 'url', 'tags', 'created', 'last-login'];
  const keys = [
    ...order.filter(k => fields[k] !== undefined),
    ...Object.keys(fields).filter(k => !order.includes(k)),
  ];
  const fm = keys.map(k => `${k}: ${fields[k]}`).join('\n');
  const file = path.join(META, `${site}.md`);
  fs.writeFileSync(file, `---\n${fm}\n---\n\n${(body || '').trim()}\n`, 'utf8');
  return file;
}

// ローカル日付（toISOString は UTC なので日本時間だと前日になることがある）
const today = () => {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

function rows() {
  const seen = new Set();
  const out = [];
  const row = (site, exists) => {
    const meta = readMeta(site);
    return {
      site,
      profile: path.join(ROOT, site),
      exists,
      description: meta?.fields.description || '',
      url: meta?.fields.url || '',
      tags: meta?.fields.tags || '',
      'last-login': meta?.fields['last-login'] || '',
      meta: meta?.file || '',
    };
  };
  for (const site of listProfiles()) {
    seen.add(site);
    out.push(row(site, true));
  }
  // メタだけ残っている（プロファイルを消した／別マシン）ものも見えるようにする
  if (fs.existsSync(META)) {
    for (const f of fs.readdirSync(META).filter(f => f.endsWith('.md'))) {
      const site = f.slice(0, -3);
      if (!seen.has(site))
        out.push(row(site, false));
    }
  }
  return out;
}

// 全角（CJK）を 2 桁として数える。日本語の description が混ざると padEnd では桁が崩れるため
const displayWidth = s => [...String(s)]
  .reduce((n, ch) => n + (/[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹯＀-｠￠-￦]/.test(ch) ? 2 : 1), 0);

function table(data, cols) {
  const width = c => Math.max(displayWidth(c), ...data.map(r => displayWidth(r[c] ?? '')));
  const w = Object.fromEntries(cols.map(c => [c, width(c)]));
  const pad = (s, n) => String(s ?? '') + ' '.repeat(Math.max(0, n - displayWidth(s ?? '')));
  const line = r => cols.map(c => pad(r[c], w[c])).join('  ').trimEnd();
  return [
    line(Object.fromEntries(cols.map(c => [c, c]))),
    cols.map(c => '-'.repeat(w[c])).join('  '),
    ...data.map(line),
  ].join('\n');
}

function parseFlags(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--'))
      continue;
    const eq = a.indexOf('=');
    if (eq > -1)
      flags[a.slice(2, eq)] = a.slice(eq + 1);
    else
      flags[a.slice(2)] = (argv[i + 1] && !argv[i + 1].startsWith('--')) ? argv[++i] : 'true';
  }
  return flags;
}

const [cmd = 'list', ...rest] = process.argv.slice(2);
const flags = parseFlags(rest);
const site = rest.find((a, i) => !a.startsWith('--') && !/^--[^=]+$/.test(rest[i - 1] || '')) || '';

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

switch (cmd) {
  case 'list': {
    const data = rows();
    if (flags.json) {
      console.log(JSON.stringify({ root: ROOT, meta: META, profiles: data }, null, 2));
      break;
    }
    console.log(`ROOT: ${ROOT}`);
    console.log(`META: ${META}`);
    console.log('');
    if (!data.length) {
      console.log('(プロファイルなし。新規に作る場合は SKILL.md の Phase 1 へ)');
      break;
    }
    console.log(table(data.map(r => ({
      site: r.site + (r.exists ? '' : ' (削除済)'),
      description: r.description || '(説明なし: register で登録)',
      url: r.url,
      'last-login': r['last-login'],
      tags: r.tags,
    })), ['site', 'description', 'url', 'last-login', 'tags']));
    break;
  }
  case 'show': {
    if (!site)
      fail('usage: profiles.mjs show <site>');
    const r = rows().find(r => r.site === site);
    if (!r)
      fail(`不明なプロファイル: ${site}`, 1);
    console.log(`site        : ${r.site}`);
    console.log(`profile     : ${r.profile}${r.exists ? '' : '  (ディレクトリなし)'}`);
    console.log(`description : ${r.description || '-'}`);
    console.log(`url         : ${r.url || '-'}`);
    console.log(`tags        : ${r.tags || '-'}`);
    console.log(`last-login  : ${r['last-login'] || '-'}`);
    console.log(`meta        : ${r.meta || '(未登録)'}`);
    const meta = readMeta(site);
    if (meta?.body)
      console.log(`\n${meta.body}`);
    break;
  }
  case 'path': {
    if (!site)
      fail('usage: profiles.mjs path <site>');
    console.log(path.join(ROOT, site));
    break;
  }
  case 'register': {
    if (!site)
      fail('usage: profiles.mjs register <site> --description "..." [--url ...] [--tags a,b] [--note "..."]');
    const prev = readMeta(site);
    const fields = { ...(prev?.fields || {}) };
    fields.name = site;
    if (flags.description)
      fields.description = flags.description;
    if (flags.url)
      fields.url = flags.url;
    if (flags.tags)
      fields.tags = flags.tags;
    if (flags['last-login'])
      fields['last-login'] = flags['last-login'];
    if (!fields.created)
      fields.created = today();
    if (!fields.description)
      fail('--description は必須（一覧で「何用のプロファイルか」を判断するため）');
    const body = flags.note !== undefined ? flags.note : (prev?.body || '');
    console.log(`wrote ${writeMeta(site, fields, body)}`);
    break;
  }
  case 'used': {
    if (!site)
      fail('usage: profiles.mjs used <site>');
    const prev = readMeta(site);
    if (!prev)
      fail(`メタ未登録: 先に register を実行してください (${site})`, 1);
    prev.fields['last-login'] = flags.date && flags.date !== 'true' ? flags.date : today();
    console.log(`wrote ${writeMeta(site, prev.fields, prev.body)}`);
    break;
  }
  case 'config': {
    const envFile = path.join(SKILL_DIR, '.env');
    console.log(`BROWSER_PROFILES_ROOT=${ROOT}`);
    console.log(`BROWSER_PROFILES_META=${META}`);
    console.log(`(.env: ${envFile}${fs.existsSync(envFile) ? '' : ' — なし。既定値を使用'})`);
    break;
  }
  default:
    fail(`unknown command: ${cmd}\nsee: list | show | path | register | used | config`);
}
