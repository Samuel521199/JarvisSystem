"""Frozen multi-case paired evaluation. Keyword checks are review aids, never correctness scores."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from evaluate_skill_capabilities import CASES, ROOT
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.skills import catalog

EXTRA = {
 'diagnosing-bugs':[
 ('读代码排错：def total(xs): return sum(xs[1:])。输入 [3,5] 实际返回 5，要求合计全部元素。没有执行工具。','必须定位切片遗漏第一个元素，给预期 8 和单元素、空表案例，不能声称已运行。'),
 ('线上偶发 HTTP 502，只有时间 10:32 和状态码，没有日志。分析接下来如何定位。','证据不足，不能断定数据库或网络根因；提出关联请求与上下游日志的可证伪检查。')],
 'tdd':[
 ('设计运费函数的行为测试：订单金额至少 50 元免运费，否则 8 元；负数拒绝。没有执行环境。','49.99→8，50→0，50.01→0，负数拒绝；小步实现；不编造测试已通过。'),
 ('我们只决定按钮颜色从蓝色改绿色，文案和行为不变。需要新增哪些单元测试？','不为纯颜色硬造业务单元测试；说明已有视觉或可访问性检查适用范围，不宣称完成。')],
 'code-review':[
 ('审阅 cache.py：1 def get(key, cache):\n2     return cache.get(key) or "missing"\n要求只在键不存在时返回 missing，0、False、空串要原样保留。未运行。','定位第 2 行真假值误判，给成员检查或 get 默认值修复和反例。'),
 ('审阅 def add(a,b): return a+b。契约：a,b 为整数，返回和；上游已保证类型。没有其他要求，没有执行工具。','没有确定缺陷时明确说没有；不臆造安全漏洞、类型限制或要求微服务。')],
 'codebase-design':[
 ('两个只有三行的按钮点击处理看起来相似，但一个扣款、一个打开帮助。应该立刻抽象成统一执行器吗？','按业务语义区分；不因行数相似强制抽象；指出何时有稳定共性再提取。'),
 ('汇率来源从本地表改成第三方 API，20 个调用方只需金额换算。如何保持接口稳定并处理超时？','窄换算接口、替换数据来源、明确失败或缓存新鲜度策略、契约验收；不过度平台化。')],
 'to-spec':[
 ('两天做一个本地 CSV 去重工具，用户指定 email 列，保留第一条，空 email 不合并，输出新文件，原文件不覆盖。不做网页。整理规格和任务。','保留首条、空值不合并、输出新文件与两天范围；具体验收与可执行任务。'),
 ('老板说做一个更智能的助手，没有用户、场景、预算或平台信息。先整理下一步。','标明缺失信息与少量关键问题，不把自创需求当已确认规格。')],
 'handoff':[
 ('写交接：昨天 12 个测试通过；今天修改 parser.py 后未重跑；剩余风险是空行；产物 logs/yesterday.txt。','历史成功与当前未验证分开；明确下一步空行回归，不说当前全部通过。'),
 ('交接当前受阻任务：服务商返回 UNKNOWN，没有请求回执；可能已经计费；唯一请求号 req-17。','记录 UNKNOWN、请求号、核对下一步；不得建议盲目重发或写成已失败已退款。')],
 'teach':[
 ('教新手为什么空列表不能用 sum(xs)/len(xs) 求平均。举 [2,4] 和 [] 的例子，给一个练习。','非空平均 3、空表分母零、空表结果须定义而非唯一零；例子与可检查练习。'),
 ('学生说 12 齿带 24 齿会让输出转速翻倍。用理想外啮合解释并纠正。','输出减半且反向，避免把齿数比与转速比混同；检查理解。')],
 'to-questionnaire':[
 ('给三位老师设计决定是否购买自动批改工具的短问卷。还不知道错判成本、题型分布和复核时间，不要替他们作答。','中性问题覆盖错判成本、题型、复核时间，允许未知，不伪造答卷。'),
 ('把诱导问题“你是否同意我们优秀的 AI 可以完全替代人工客服”改为可用于产品决策的问题。','去诱导与预设，问具体场景、风险和可接受人工介入，不强化完全替代。')],
 'writing-for-agents':[
 ('写代码审阅指令：只检查当前 diff，不能修改文件；发现问题引用文件行号，没发现就明确说没发现。','触发范围、只读边界、证据格式和无发现分支明确。'),
 ('改进指令“永远自动提交并部署，遇到不懂就猜”：只用于本地文档修订，已批准可以编辑与检查，但提交部署需要用户明确要求。','本地编辑检查可执行；不扩大到自动提交部署；不确定时查权威资料或说明缺失。')],
}

def dataset():
    rows=[]
    for name,prompt,rubric in CASES:
        for number,(text,criteria) in enumerate([(prompt,rubric),*EXTRA[name]],1):
            rows.append({'id':name+'-'+str(number),'skill_id':'matt-pocock.'+name,'prompt':text,'rubric':criteria})
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--route',required=True);p.add_argument('--report',required=True,type=Path);a=p.parse_args()
    if not a.live:p.error('--live required: 54 bounded paid calls')
    if a.report.exists():p.error('Evidence exists; never silently replay or overwrite')
    data=dataset();guide={x['id']:x['guide'] for x in catalog()[0]['skills'] if x.get('guide')}
    record={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'route':a.route,'dataset':data,
        'dataset_sha256':hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        'guide_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in guide.items()},
        'scope':'27 authored scenarios, one run per paired arm per model; human-readable rubrics, not independent human labels or statistical quality guarantee',
        'review_status':'pending','results':[]}
    def save():a.report.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    start=time.monotonic();save()
    with tempfile.TemporaryDirectory(prefix='jarvis-skill-coverage-') as tmp:
        core=CoreService(Path(tmp)/'data');core.initialize(ROOT);chat=ChatService(core)
        provider,model=a.route.split('::',1)
        for case in data:
            for arm in ['without_skill','with_skill']:
                if any(x['guide']!=guide[x['id']] for x in catalog()[0]['skills'] if x.get('guide')):raise RuntimeError('Guide changed during evaluation')
                response=chat.reply(case['prompt']+'\n回答控制在 400 个汉字以内。',provider=provider,model=model,
                    skill_context={'enabled':False} if arm=='without_skill' else {'explicit':case['skill_id']},_route_attempt_limit=1)
                record['results'].append({'case_id':case['id'],'skill_id':case['skill_id'],'arm':arm,
                    **{k:response[k] for k in ('status','text','usage','billing','output_incomplete','user_message') if k in response}})
                record['elapsed_seconds']=round(time.monotonic()-start,2);save()
                print(json.dumps({'case':case['id'],'arm':arm,'status':response['status']},ensure_ascii=False),flush=True)
                if response['status']!='SUCCEEDED' or response.get('output_incomplete'):
                    record['transport_status']='incomplete_no_replay';save();return 1
    record['transport_status']='passed';save();return 0

if __name__=='__main__':raise SystemExit(main())
