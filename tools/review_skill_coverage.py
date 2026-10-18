"""Record source-linked agent review of every paired answer; never a model self-score."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# All 108 full answers were read against the frozen case rubrics. These are
# explicit exceptions to 'meets this case rubric', not keyword-derived scores.
EXCEPTIONS={
 'google':{
  ('diagnosing-bugs-1','without_skill'):('partial','空表原因正确，但直接默认返回0，缺少复现/回归案例与未运行说明。'),
  ('diagnosing-bugs-1','with_skill'):('partial','明确静态分析与空值策略，但没有补充可执行的边界回归案例。'),
  ('diagnosing-bugs-2','without_skill'):('partial','定位正确，遗漏空表与单元素验收。'),
  ('diagnosing-bugs-2','with_skill'):('partial','定位正确且明确未运行，仍遗漏空表与单元素案例。'),
  ('diagnosing-bugs-3','without_skill'):('partial','提供排查步骤，但没有明确证据不足和请求关联ID，提前给出防御配置。'),
  ('diagnosing-bugs-3','with_skill'):('partial','有日志关联但未明确无法定因，过早建议重试配置；未说明重复操作风险。'),
  ('tdd-1','without_skill'):('partial','公式和预期正确，但没有小步反馈流程和明确未运行说明。'),
  ('tdd-1','with_skill'):('partial','独立预期与未验证标记正确，未描述逐个行为反馈实现。'),
  ('tdd-2','without_skill'):('partial','边界数值正确，未说明先运行最小行为再实现。'),
  ('tdd-2','with_skill'):('partial','遗漏50.01的上边界案例及小步实现流程；已列数值正确。'),
  ('tdd-3','without_skill'):('partial','无需业务单测结论合理，缺少对比度或可访问性检查。'),
  ('tdd-3','with_skill'):('partial','避免脆弱单测，但视觉检查未提对比度，不能将人工看颜色等同全面验收。'),
  ('code-review-1','without_skill'):('partial','识别真实两项问题，但把未给定的折扣范围和金额精度作为确定缺陷，缺少行号。'),
  ('code-review-1','with_skill'):('partial','真实两项问题和行号正确；额外折扣范围应作为待确认契约。'),
  ('code-review-2','without_skill'):('partial','修复正确，缺少明确行号和未运行说明。'),
  ('code-review-2','with_skill'):('fail','修复表达式正确，但错误暗示存储None时必须改用成员检查；dict.get默认值本就保留已有None。'),
  ('code-review-3','without_skill'):('fail','无缺陷结论合理，但任意精度整数相加并非恒定O(1)，无执行证据却建议直接生产使用。'),
  ('codebase-design-1','without_skill'):('partial','共享边界合理，但引入配置中心/SDK，缺少迁移与一致性检查。'),
  ('codebase-design-3','without_skill'):('fail','旧汇率降级没有最大陈旧期限或明确失败分支，缓存建议不能保证契约正确。'),
  ('codebase-design-3','with_skill'):('fail','有TTL却允许无限期最后有效值兜底；缺少过期拒绝与契约验收，不能保证调用方无感。'),
  ('to-spec-1','without_skill'):('partial','有一周计划和功能，但按层拆分，未给每项验收及明确依赖。'),
  ('to-spec-1','with_skill'):('partial','有纵向任务/验收/依赖，但没有落实一周约束与明确排除账号同步。'),
  ('to-spec-2','without_skill'):('partial','满足核心要求，额外假定空格归一化、编码和打包，缺少独立验收样例。'),
  ('to-spec-2','with_skill'):('partial','核心功能与验收清楚，自动编码适配属新增范围，未落实两天排期。'),
  ('handoff-3','without_skill'):('partial','不盲重试正确，但仅确认未扣费不足以证明未执行，仍须核对执行终态。'),
  ('handoff-3','with_skill'):('partial','明确UNKNOWN和不重试，但首句“失败/挂起”与后文未知终态不一致。'),
  ('teach-1','without_skill'):('partial','转速方向正确，没有迁移练习和外啮合适用条件。'),
  ('teach-1','with_skill'):('partial','有练习与正确答案，但把转向相反泛化为所有啮合，须限定一对外齿轮。'),
  ('teach-2','without_skill'):('fail','将空表默认返回0称为规范写法，且练习却返回None；缺少业务约定。'),
  ('teach-2','with_skill'):('partial','除零与练习正确，但未解释空表结果需要约定；“崩溃”表述忽略异常可捕获。'),
  ('teach-3','with_skill'):('fail','输出减半和练习正确，但遗漏用户要求的反向，且把接触处线速度相等过度泛化。'),
  ('to-questionnaire-1','without_skill'):('partial','覆盖决策维度，未明确接受未知与回答空间。'),
  ('to-questionnaire-1','with_skill'):('partial','覆盖成本和体量，允许估计但未明确允许未知，缺少答题留白。'),
  ('to-questionnaire-2','without_skill'):('partial','覆盖三维度，未明确接受未知，也混合了多个问题。'),
  ('to-questionnaire-3','without_skill'):('partial','去除了优秀等预设，但量表缺少未使用/未知，并假设已有AI使用经验。'),
  ('to-questionnaire-3','with_skill'):('partial','有人工介入与不确定选项，但部分题仍假设已有AI与转接经验。'),
  ('writing-for-agents-1','without_skill'):('fail','新增自动提交，扩大权限；无法运行测试分支缺失。'),
  ('writing-for-agents-1','with_skill'):('partial','触发范围清楚，但要求完整读两文档，缺少无法验证时如实报告的完成分支。'),
  ('writing-for-agents-3','without_skill'):('partial','权限边界正确，但不确定内容先推测而非优先查资料。'),
  ('writing-for-agents-3','with_skill'):('partial','限制提交部署正确，但所有疑问直接询问，未复用已知资料和授权。'),
 },
 'sol':{
  ('diagnosing-bugs-1','without_skill'):('partial','原因与未运行说明准确，缺少独立回归案例。'),
  ('diagnosing-bugs-2','without_skill'):('partial','原因与空表预期准确，缺少单元素回归。'),
  ('tdd-1','without_skill'):('partial','数值与输入校验正确，未明确小步测试反馈实现。'),
  ('tdd-2','without_skill'):('partial','全部边界正确，未安排逐项实现反馈。'),
  ('code-review-1','without_skill'):('partial','识别真实问题；折扣范围应作为待确认约定，缺少未运行说明。'),
  ('to-spec-1','without_skill'):('partial','范围与最终验收清楚，但各任务验收和依赖未明确。'),
  ('teach-1','without_skill'):('partial','机制与外啮合限定正确，没有迁移练习。'),
  ('teach-2','without_skill'):('partial','概念与练习正确，没有给练习参考答案。'),
  ('teach-3','without_skill'):('partial','结论正确，没有用于检查理解的练习。'),
 }
}

def main():
    result={'observed_at':datetime.now(timezone.utc).isoformat(),'method':'Agent read all 108 complete outputs against 27 prewritten rubrics; not independent human adjudication, not blinded, one sample per arm; counts describe these samples only. No model self-rating or keyword correctness proxy.',
        'results':[],'sources':{},'summary':{},'recommendation':'保留九项指导；Sol本批覆盖完整，Google仍有遗漏和局部事实错误。运行流程就绪不等于质量无误；暂不据单次样例删除技能或宣称普遍提升。'}
    for name in ['google','sol']:
        path=ROOT/'evals/reports'/('skill-coverage-'+name+'-2026-10-19.json');raw=path.read_bytes();d=json.loads(raw)
        assert d['transport_status']=='passed' and len(d['results'])==54
        result['sources'][str(path.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
        counts={arm:{state:0 for state in ['pass','partial','fail']} for arm in ['without_skill','with_skill']}
        for row in d['results']:
            state,note=EXCEPTIONS[name].get((row['case_id'],row['arm']),('pass','满足该案例已列验收点；不推及未覆盖输入。'))
            counts[row['arm']][state]+=1
            result['results'].append({'route':d['route'],'case_id':row['case_id'],'skill_id':row['skill_id'],'arm':row['arm'],'assessment':state,'notes':note,'output_sha256':hashlib.sha256(row['text'].encode()).hexdigest()})
        result['summary'][name]=counts
    out=ROOT/'evals/reports/skill-coverage-review-2026-10-19.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result['summary']))

if __name__=='__main__':main()
