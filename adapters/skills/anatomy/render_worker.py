"""Trusted fixed HTML assembler. Runs in the existing Python LPAC/Job runtime."""
import json
import re
from pathlib import Path
import sys

root = Path(__file__).parent
request = json.loads((root / 'input.json').read_text(encoding='utf-8'))
p = request['parameters']
if (set(p) != {'driver_teeth', 'ratio', 'theme', 'title'} or p['driver_teeth'] != 12
        or type(p['ratio']) is not int or p['ratio'] not in (1, 2, 3)
        or p['theme'] not in ('light', 'dark') or not isinstance(p['title'], str) or len(p['title']) > 100):
    raise ValueError('Invalid fixed template parameters')
model = {'driver_teeth': 12, 'driven_teeth': 12 * p['ratio'], 'ratio': p['ratio'],
         'equation': 'driven_angle = -driver_angle * driver_teeth / driven_teeth',
         'geometry': 'simplified teaching gear teeth, not manufacturing geometry'}
kit = (root / 'iso-kit.mjs').read_text(encoding='utf-8')
kit = '\n'.join(line[7:] if line.startswith('export ') else line for line in kit.splitlines())
lesson = (root / 'lesson.js').read_text(encoding='utf-8')
license_text = (root / 'LICENSE.txt').read_text(encoding='utf-8')
script = '/*\n' + license_text.replace('*/', '* /') + '\n*/\n' + kit + '\nconst LESSON=' + json.dumps({'parameters': p, 'model': model}, ensure_ascii=False) + ';\n' + lesson
script = script.replace('</script', '<\\/script').replace('</SCRIPT', '<\\/SCRIPT')
html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Jarvis 机械科普</title></head><body><main id="lesson" class="iso-page"></main>'
        '<script type="module">' + script + '</script></body></html>')
output = {'binding': request['binding'], 'model': model,
          'samples': [{'driver': x, 'driven': -x / p['ratio']} for x in (0, 30, 90, 180, 360)],
          'html': html, 'source': lesson, 'license': license_text}
sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode('utf-8'))
