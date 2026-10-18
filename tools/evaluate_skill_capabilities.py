"""Small paired behavior samples; raw outputs retained for review, not a quality benchmark."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.skills import catalog
from eval_policy import default_route, report_path

CASES=[
 ('diagnosing-bugs','这段 Python 偶尔失败，帮我排查。已知调用 f([]) 报 ZeroDivisionError，f([2,4]) 返回 3。代码 calc.py 第 1 行 def f(xs): 第 2 行 return sum(xs)/len(xs)。没有运行工具。','区分已知零长度原因和未验证输入；提供可复现检查，不能编造运行'),
 ('tdd','我要实现计费：0 到 100 件每件 2 元，第 101 件起每件 1 元，负数和非整数拒绝。设计实现办法。没有执行工具。','行为案例有独立数值预期，尤其 0、100、101、非法输入；诚实标明未运行'),
 ('code-review','审阅 calc.py：1 def discounted(price, percent):\n2     return price * percent / 100\n要求 percent=20 表示八折，价格不能为负。指出具体问题。','识别折后价公式和负数契约，引用行号与影响，不编造测试'),
 ('codebase-design','订单服务和退款服务各复制了 100 行税费计算；税率每月变动且两处常不同步，项目很小。帮我设计模块边界。','提出小接口隐藏税费规则、渐进迁移和一致性检查，不引入无谓平台'),
 ('to-spec','把目标变成可执行计划：离线笔记应用，本地新建编辑删除，搜索标题，退出再打开保留。只有一周。不需要账号和同步。','范围遵守无账号无同步，规格和有验收的纵向任务，依赖明确且无环'),
 ('handoff','给下一位开发者写交接：目标是修复导入中文乱码；已定位 loader.py:18 使用 latin1，尚未修改。复现记录 artifacts/repro.txt。明天先决定兼容策略，再修改和回归。不能说已经修好了。','准确区分已定位与未修改；引用记录和明确下一步，不发消息'),
 ('teach','教一位会加减乘除的初学者理解齿轮传动比，目标是能判断 12 齿带 24 齿时的转速和方向。','具体例子、2:1减速与反向、一个迁移练习和解释答案，标明理想外啮合假设'),
 ('to-questionnaire','帮我写问卷给售后主管，用来决定先做自动分类还是自动回复。他了解工单量和重复问题，我们还不知道错误回复造成的损失。','问题覆盖量、重复率、错误代价和决策；给回答空间、接受未知，不代发'),
 ('writing-for-agents','把这段协作规则改成可使用的 Agent 指令：所有任务都要读全部文档，要认真测试，做好以后结束。项目有 docs/README.md 和 docs/testing.md。我们只想针对代码变更使用这套流程。','有代码变更触发、按需引用测试文档、可观察完成条件，避免所有任务读全部资料'),
]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--repair',action='store_true');parser.add_argument('--route',default=default_route());parser.add_argument('--report',type=Path);args=parser.parse_args()
    if not args.live:parser.error('--live required; 18 configured model calls may incur charges')
    route,model=args.route.split('::',1)
    record={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'route':args.route,'catalog_digest':catalog()[1],
            'scope':'nine paired examples, one run per arm; no statistical improvement or universal correctness claim','results':[],'review_status':'pending'}
    target=args.report or report_path('skill-capabilities',args.route)
    if args.repair:
        record=json.loads(target.read_text(encoding='utf-8'))
        if record['route']!=args.route:parser.error('Repair comparison must keep the original model route')
        record['repair_catalog_digest']=catalog()[1]
    with tempfile.TemporaryDirectory(prefix='jarvis-capability-eval-') as tmp:
        core=CoreService(Path(tmp)/'data');core.initialize(ROOT);chat=ChatService(core)
        for name,prompt,rubric in CASES:
            if args.repair and name not in {'to-spec','to-questionnaire'}:continue
            for arm in (['with_skill_repaired'] if args.repair else ['without_skill','with_skill']):
                context={'enabled':False} if arm=='without_skill' else {'explicit':'matt-pocock.'+name}
                response=chat.reply(prompt+'\n回答控制在 400 个汉字以内。',provider=route,model=model,skill_context=context,_route_attempt_limit=1)
                record['results'].append({'skill_id':'matt-pocock.'+name,'arm':arm,'prompt':prompt,'review_points':rubric,
                                          **{k:response[k] for k in ('status','text','history_info','usage','billing','output_incomplete','user_message') if k in response}})
                target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(json.dumps({'skill':name,'arm':arm,'status':response['status']},ensure_ascii=False),flush=True)
                if response['status']!='SUCCEEDED' or response.get('output_incomplete'):
                    return 1 # No automatic replay of paid/unknown calls.
    record['transport_status']='passed';target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return 0

if __name__=='__main__':raise SystemExit(main())
