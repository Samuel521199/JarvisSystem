#!/usr/bin/env node
'use strict';

/*
 * Render all docs/diagrams/*.mmd without touching the documentation manifest.
 * Dependencies: npm install --prefix tools
 * Usage: node tools/render_docs.cjs [--mermaid-js FILE] [--executable-path FILE]
 * Windows can reuse installed Edge; otherwise install Playwright Chromium:
 * npm exec --prefix tools -- playwright install chromium
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const ROOT = path.resolve(__dirname, '..');
const DIAGRAMS = path.join(ROOT, 'docs', 'diagrams');
const VALIDATION = path.join(DIAGRAMS, 'render-validation.json');
const MERMAID_VERSION = '11.12.2';
// Exact npm browser bundle, also published at the versioned jsDelivr URL.
const MERMAID_SHA256 = 'd0830a6c05546e9edb8fe20a8f545f3e0dc7c4c3134d584bad9c13a99d7a71e0';
const FONT = '"Microsoft YaHei", "Noto Sans CJK SC", sans-serif';
const SETTINGS = Object.freeze({
  theme: 'neutral',
  font_family: FONT,
  background: '#ffffff',
  padding_css_px: 20,
  device_scale_factor: 2,
  deterministic_ids: true,
  random_seed_strategy: 'source-sha256-xorshift32'
});

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function relative(file) {
  return path.relative(ROOT, file).split(path.sep).join('/');
}

function options(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === '--help' || key === '-h') {
      result.help = true;
      continue;
    }
    if (key !== '--mermaid-js' && key !== '--executable-path') {
      throw new Error('Unknown option: ' + key);
    }
    if (!argv[i + 1] || argv[i + 1].startsWith('--')) {
      throw new Error('Missing value for ' + key);
    }
    result[key.slice(2)] = path.resolve(argv[++i]);
  }
  return result;
}

function packageInfo(name) {
  try {
    const file = require.resolve(name + '/package.json');
    return { directory: path.dirname(file), data: JSON.parse(fs.readFileSync(file, 'utf8')) };
  } catch (original) {
    let directory;
    try {
      directory = path.dirname(require.resolve(name));
    } catch {
      throw new Error('Cannot find ' + name + '. Run npm install --prefix tools, or provide NODE_PATH.');
    }
    for (let depth = 0; depth < 6; depth += 1) {
      const file = path.join(directory, 'package.json');
      if (fs.existsSync(file)) {
        const data = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (data.name === name) return { directory, data };
      }
      const parent = path.dirname(directory);
      if (parent === directory) break;
      directory = parent;
    }
    throw original;
  }
}

function findBundle(explicit) {
  const file = explicit || path.join(packageInfo('mermaid').directory, 'dist', 'mermaid.min.js');
  const bytes = fs.readFileSync(file);
  const hash = sha256(bytes);
  if (hash !== MERMAID_SHA256) {
    throw new Error('Mermaid bundle integrity mismatch. Expected the unmodified mermaid@' +
      MERMAID_VERSION + '/dist/mermaid.min.js; received SHA256 ' + hash + '.');
  }
  return { file, text: bytes.toString('utf8'), hash };
}

function browserOptions(explicit, chromium) {
  if (explicit) {
    if (!fs.existsSync(explicit)) throw new Error('The specified browser executable does not exist.');
    return { launch: { executablePath: explicit }, source: 'explicit-chromium-executable' };
  }
  if (process.platform === 'win32') {
    const bases = [
      process.env['ProgramFiles(x86)'],
      process.env.ProgramFiles,
      process.env.LOCALAPPDATA
    ].filter(Boolean);
    for (const base of bases) {
      const file = path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe');
      if (fs.existsSync(file)) {
        return { launch: { executablePath: file }, source: 'system-edge' };
      }
    }
  }
  if (!fs.existsSync(chromium.executablePath())) {
    throw new Error('No supported browser found. Supply --executable-path, or run ' +
      'npm exec --prefix tools -- playwright install chromium.');
  }
  return { launch: {}, source: 'playwright-chromium' };
}

function writeAtomic(file, value) {
  const temporary = file + '.render-tmp-' + process.pid;
  try {
    fs.writeFileSync(temporary, value);
    fs.renameSync(temporary, file);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

function portableError(error, bundle) {
  let message = String(error && error.message ? error.message : error);
  for (const local of [ROOT, bundle && bundle.file, process.cwd()].filter(Boolean)) {
    message = message.split(local).join('<local-path>');
    message = message.split(local.split(path.sep).join('/')).join('<local-path>');
  }
  return message.replace(/[A-Za-z]:[\\/][^\s"'<>]+/g, '<local-path>')
    .split('\n').slice(0, 10).join('\n');
}

async function main() {
  const args = options(process.argv.slice(2));
  if (args.help) {
    process.stdout.write([
      'Render docs/diagrams/*.mmd to sibling PNG and SVG files.',
      '',
      'node tools/render_docs.cjs [--mermaid-js FILE] [--executable-path FILE]',
      '',
      'Mermaid is fixed to 11.12.2 and verified by SHA256.',
      'Dependencies resolve through tools/node_modules or NODE_PATH.',
      'Windows automatically reuses Edge when available.',
      'Other systems can run: npm exec --prefix tools -- playwright install chromium',
      'The script never updates documentation manifest hashes.',
      ''
    ].join('\n'));
    return;
  }

  const names = fs.readdirSync(DIAGRAMS)
    .filter((name) => name.endsWith('.mmd'))
    .sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
  if (!names.length) throw new Error('No Mermaid sources found in docs/diagrams.');
  const entries = names.map((name) => {
    const file = path.join(DIAGRAMS, name);
    if (!fs.lstatSync(file).isFile()) throw new Error('Expected an ordinary .mmd file: ' + name);
    const bytes = fs.readFileSync(file);
    return {
      name, file, sourceHash: sha256(bytes),
      source: bytes.toString('utf8').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n')
    };
  });

  const ownPackage = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json'), 'utf8'));
  const playwrightPackage = packageInfo('playwright');
  const { chromium } = require('playwright');
  const bundle = findBundle(args['mermaid-js']);
  const selection = browserOptions(args['executable-path'], chromium);
  const report = {
    schema_version: 1,
    generator: {
      name: ownPackage.name,
      version: ownPackage.version,
      source: 'tools/render_docs.cjs',
      source_sha256: sha256(fs.readFileSync(__filename)),
      package_sha256: sha256(fs.readFileSync(path.join(__dirname, 'package.json'))),
      mermaid_version: MERMAID_VERSION,
      mermaid_bundle_sha256: bundle.hash,
      playwright_version: playwrightPackage.data.version,
      browser_engine: 'chromium',
      browser_source: selection.source
    },
    settings: SETTINGS,
    status: 'failed',
    checks: []
  };

  let browser;
  let fatal;
  const staged = [];
  try {
    browser = await chromium.launch({ headless: true, ...selection.launch });
    report.generator.browser_version = browser.version();
    const context = await browser.newContext({
      viewport: { width: 1280, height: 960 },
      deviceScaleFactor: SETTINGS.device_scale_factor,
      locale: 'zh-CN',
      timezoneId: 'UTC',
      colorScheme: 'light',
      reducedMotion: 'reduce'
    });
    const page = await context.newPage();
    page.setDefaultTimeout(60000);
    // All render inputs are local; diagrams must not fetch remote resources.
    await page.route('**/*', (route) => route.abort());
    await page.setContent('<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">' +
      '<style>html,body{margin:0;background:#fff;}#diagram{display:inline-block;' +
      'padding:20px;background:#fff;}svg{display:block;}</style>' +
      '</head><body><main id="diagram"></main></body></html>');
    await page.addScriptTag({ content: bundle.text });

    for (const entry of entries) {
      const check = {
        source: relative(entry.file),
        source_sha256: entry.sourceHash,
        parse: 'pending',
        render: 'pending'
      };
      report.checks.push(check);
      try {
        const identifier = 'jarvis_' + path.basename(entry.name, '.mmd')
          .replace(/[^A-Za-z0-9_]/g, '_') + '_' + entry.sourceHash.slice(0, 12);
        const parsed = await page.evaluate(async (input) => {
          // Some Mermaid state shapes use RoughJS randomness even with classic
          // styling. Seed the isolated rendering page per source as well as IDs.
          let randomState = input.seed || 0x6d2b79f5;
          Math.random = () => {
            randomState ^= randomState << 13;
            randomState ^= randomState >>> 17;
            randomState ^= randomState << 5;
            return (randomState >>> 0) / 4294967296;
          };
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            theme: input.theme,
            fontFamily: input.font,
            deterministicIds: true,
            deterministicIDSeed: input.identifier,
            flowchart: { useMaxWidth: false, htmlLabels: true },
            sequence: { useMaxWidth: false }
          });
          const result = await mermaid.parse(input.source);
          return { diagram_type: result.diagramType };
        }, { source: entry.source, identifier, seed: Number.parseInt(entry.sourceHash.slice(0, 8), 16),
          theme: SETTINGS.theme, font: FONT });
        check.parse = 'passed';
        check.diagram_type = parsed.diagram_type;
        const rendered = await page.evaluate(async (input) => {
          const container = document.getElementById('diagram');
          container.replaceChildren();
          const result = await mermaid.render(input.identifier, input.source);
          container.innerHTML = result.svg;
          const svg = container.querySelector('svg');
          if (!svg) throw new Error('Mermaid did not return an SVG.');
          await document.fonts.ready;
          const box = svg.viewBox.baseVal;
          const width = Math.max(1, Math.ceil(box.width));
          const height = Math.max(1, Math.ceil(box.height));
          svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
          svg.setAttribute('width', String(width));
          svg.setAttribute('height', String(height));
          svg.style.width = width + 'px';
          svg.style.height = height + 'px';
          svg.style.maxWidth = 'none';
          svg.style.background = '#ffffff';
          return { svg: svg.outerHTML, width, height };
        }, { identifier, source: entry.source });
        const width = rendered.width + SETTINGS.padding_css_px * 2;
        const height = rendered.height + SETTINGS.padding_css_px * 2;
        const pixels = width * height * SETTINGS.device_scale_factor ** 2;
        if (width > 8192 || height > 12000 || pixels > 48000000) {
          throw new Error('Diagram exceeds the renderer size limit; split the source into smaller diagrams.');
        }
        await page.setViewportSize({ width, height });
        const png = await page.locator('#diagram').screenshot({
          type: 'png',
          animations: 'disabled',
          caret: 'hide',
          scale: 'device'
        });
        const svg = Buffer.from('<?xml version="1.0" encoding="UTF-8"?>\n' + rendered.svg + '\n', 'utf8');
        const base = path.join(DIAGRAMS, path.basename(entry.name, '.mmd'));
        staged.push({ file: base + '.svg', data: svg }, { file: base + '.png', data: png });
        check.render = 'passed';
        check.dimensions_css_px = { width, height };
        check.artifacts = [
          { path: relative(base + '.svg'), sha256: sha256(svg) },
          { path: relative(base + '.png'), sha256: sha256(png) }
        ];
        process.stdout.write('Rendered ' + entry.name + '\n');
      } catch (error) {
        if (check.parse === 'pending') check.parse = 'failed';
        check.render = 'failed';
        check.error = portableError(error, bundle);
        process.stderr.write('Failed ' + entry.name + ': ' + check.error + '\n');
      }
    }
    if (report.checks.some((check) => check.render !== 'passed')) {
      throw new Error('One or more diagrams failed. Existing image files were not replaced.');
    }
    for (const entry of entries) {
      if (sha256(fs.readFileSync(entry.file)) !== entry.sourceHash) {
        throw new Error('A source changed during rendering. Re-run after editing finishes.');
      }
    }
    const currentNames = fs.readdirSync(DIAGRAMS).filter((name) => name.endsWith('.mmd'))
      .sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
    if (JSON.stringify(currentNames) !== JSON.stringify(names)) {
      throw new Error('The diagram source set changed during rendering. Re-run after editing finishes.');
    }
    for (const artifact of staged) writeAtomic(artifact.file, artifact.data);
    report.status = 'passed';
  } catch (error) {
    fatal = error;
    report.error = portableError(error, bundle);
    for (const check of report.checks) delete check.artifacts;
  } finally {
    if (browser) await browser.close().catch(() => {});
    writeAtomic(VALIDATION, JSON.stringify(report, null, 2) + '\n');
  }

  if (fatal) throw fatal;
  process.stdout.write('Validated ' + entries.length + ' diagrams. Wrote docs/diagrams/render-validation.json.\n');
  process.stdout.write('Documentation manifest hashes were NOT changed. Review regenerated assets before refreshing that manifest.\n');
}

main().catch((error) => {
  process.stderr.write('render_docs: ' + error.message + '\n');
  process.exitCode = 1;
});

