"""Refresh the curated, read-only source review. Does not install or execute servers."""
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    # These are configuration templates, not an executable allowlist.
    rows = [
        ('context7', 'Context7 文档助手', 'development', 'book', 'Upstash', 'vendor', 'https://github.com/upstash/context7',
         '查询开发库的版本文档与代码示例。', '编写或审阅依赖第三方库的代码，需要核对具体版本 API。', '普通聊天、项目内部事实；已有适用官方文档且无需更新。',
         ['联网', '较高额度建议配置 Context7 API Key', 'HTTP 运行适配器'], '免费额度及更高用量方案，按服务当前规则。',
         ['matt-pocock.code-review', 'matt-pocock.codebase-design', 'matt-pocock.diagnosing-bugs'], '',
         {'transport': 'streamable-http', 'url': 'https://mcp.context7.com/mcp'}),
        ('github', 'GitHub 仓库协作', 'development', 'github', 'GitHub', 'vendor', 'https://github.com/github/github-mcp-server',
         '读取仓库、Issue、PR 和 CI 信息。', '需要 GitHub 上的远程源码、问题或审阅记录；仓库范围已明确。', '只有本机代码时优先本机文件；发评论、推送和合并须有对应任务授权。',
         ['GitHub 账户与对应仓库权限', 'OAuth 或最小权限 PAT', '凭据绑定与 HTTP 运行适配器'], '遵循 GitHub 账户与 API 限额。',
         ['matt-pocock.code-review', 'matt-pocock.handoff', 'matt-pocock.to-spec'], '',
         {'transport': 'streamable-http', 'url': 'https://api.githubcopilot.com/mcp/'}),
        ('playwright', 'Playwright 浏览器测试', 'browser', 'browser', 'Microsoft', 'vendor', 'https://github.com/microsoft/playwright-mcp',
         '查看网页结构，操作浏览器并核对界面行为。', '需要真实网页交互、截图或界面回归；目标站点与操作范围明确。', '只查静态文档时优先检索；既有 Jarvis 浏览器适配器能完成时优先复用。',
         ['Node.js 与兼容浏览器', '独立浏览器配置与运行隔离', 'stdio 运行适配器'], '本地运行本身通常无 API 费；目标服务另计。',
         ['matt-pocock.diagnosing-bugs', 'matt-pocock.tdd', 'matt-pocock.code-review'], '',
         {'transport': 'stdio', 'command': 'npx', 'args': ['-y', '@playwright/mcp']}),
        ('brave-search', 'Brave 网页搜索', 'research', 'search', 'Brave', 'vendor', 'https://github.com/brave/brave-search-mcp-server',
         '检索网页、新闻和相关在线来源。', '需要时效信息、来源链接或跨站搜索。', '纯创作、已给齐资料；与 Tavily 同类任务优先选一个。',
         ['Brave Search API Key', 'Node.js', '凭据绑定与 stdio 运行适配器'], '使用 Brave Search API 额度与计费。',
         ['matt-pocock.to-spec', 'matt-pocock.teach'], 'web-search',
         {'transport': 'stdio', 'command': 'npx', 'args': ['-y', '@brave/brave-search-mcp-server', '--transport', 'stdio']}),
        ('tavily', 'Tavily 研究检索', 'research', 'compass', 'Tavily', 'vendor', 'https://github.com/tavily-ai/tavily-mcp',
         '为研究任务搜索并提取网页内容。', '需要带来源的研究、网页提取；已有 Tavily 账户与额度。', '本地资料已足够；与 Brave 重复搜索而无交叉核对需要。',
         ['Tavily 账户与额度', 'OAuth 或 API Key', '凭据绑定与 HTTP 运行适配器'], '使用 Tavily 的服务额度与计费。',
         ['matt-pocock.to-spec', 'matt-pocock.teach'], 'web-search',
         {'transport': 'streamable-http', 'url': 'https://mcp.tavily.com/mcp'}),
        ('firecrawl', 'Firecrawl 网页采集', 'research', 'flame', 'Firecrawl', 'vendor', 'https://github.com/firecrawl/firecrawl-mcp-server',
         '把网页与网站资料提取成便于分析的内容。', '需提取多个页面、结构化网页资料或站点地图。', '单个可直接读取页面；登录后私人内容或采集范围未经明确授权。',
         ['Firecrawl API Key 或自托管服务', 'Node.js', '凭据绑定与 stdio 运行适配器'], '云端抓取使用服务积分；自托管另有运行成本。',
         ['matt-pocock.to-spec', 'matt-pocock.teach'], '',
         {'transport': 'stdio', 'command': 'npx', 'args': ['-y', 'firecrawl-mcp']}),
        ('markitdown', 'MarkItDown 文件转换', 'files', 'document', 'Microsoft', 'vendor', 'https://github.com/microsoft/markitdown',
         '将 PDF、Office 等资料转换为可检索文本。', '项目资料需要文字提取，并已指定输入文件范围。', '需要保留精确版式、编辑 Word/PPT 或高精度扫描 OCR 时需专门工具。',
         ['Python 与 markitdown-mcp 及对应格式依赖', '限定文件范围', 'stdio 运行适配器'], '本地转换为主；可选外部识别服务另计。',
         ['matt-pocock.to-spec', 'matt-pocock.teach'], '',
         {'transport': 'stdio', 'command': 'uvx', 'args': ['markitdown-mcp']}),
        ('filesystem', 'Filesystem 文件工具', 'files', 'folder', 'MCP Reference', 'reference', 'https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem',
         '在明确限定的目录内读取和管理文件。', '外部 MCP 客户端需要文件工具，且现有文件接口无法满足。', 'Jarvis 已有项目文件读写时优先原接口；不授予整盘权限。',
         ['Node.js', '必须填写允许目录', '文件范围绑定与 stdio 运行适配器'], '本地运行；参考实现需按实际场景评估。',
         ['matt-pocock.code-review', 'matt-pocock.handoff'], '',
         {'transport': 'stdio', 'command': 'npx', 'args': ['-y', '@modelcontextprotocol/server-filesystem']}),
        ('git', 'Git 本地版本工具', 'development', 'branch', 'MCP Reference', 'reference', 'https://github.com/modelcontextprotocol/servers/tree/main/src/git',
         '查看本地仓库历史、差异与版本信息。', '需要通过 MCP 读取明确指定仓库的 Git 状态和差异。', '已有 Git CLI 可完成时优先复用；提交、切分支或重置需对应任务授权。',
         ['Python、Git 与 mcp-server-git', '必须指定仓库路径', 'stdio 运行适配器'], '本地运行；参考实现需按实际场景评估。',
         ['matt-pocock.code-review', 'matt-pocock.handoff'], '',
         {'transport': 'stdio', 'command': 'uvx', 'args': ['mcp-server-git']}),
        ('blender', 'Blender 三维创作', 'creative', 'cube', 'ahujasid / 社区维护', 'community', 'https://github.com/ahujasid/mcp-for-blender',
         '操作 Blender 场景，制作三维演示与拆解素材。', '需要 Blender 场景、机械展示、灯光或动画素材，并明确工程与输出要求。', '不能当作专业 CAD、公差或制造图验收；固定齿轮科普可先用现有 Anatomy。',
         ['Blender 与配套插件', 'Python、uvx 与 mcp-for-blender', '本机连接及脚本执行隔离验收'], '本地 Blender；可选外部素材或生成服务另计。',
         ['anatomy.explainer', 'matt-pocock.teach'], '',
         {'transport': 'stdio', 'command': 'uvx', 'args': ['mcp-for-blender']}),
    ]
    servers = []
    reviews = {}
    for row in rows:
        ident, name, category, icon, publisher, source_type, source, summary, use, avoid, requirements, cost, skills, group, template = row
        repo = '/'.join(source.split('/')[3:5])
        if repo not in reviews:
            try:
                request = Request('https://api.github.com/repos/' + repo, headers={'User-Agent': 'Jarvis-source-review'})
                with urlopen(request, timeout=20) as response:
                    meta = json.load(response)
                with urlopen(Request('https://api.github.com/repos/' + repo + '/commits/' + meta['default_branch'], headers={'User-Agent': 'Jarvis-source-review'}), timeout=20) as response:
                    commit = json.load(response)
                reviews[repo] = {'repository': meta['full_name'], 'archived': meta['archived'], 'pushed_at': meta['pushed_at'], 'revision': commit['sha'], 'license': (meta.get('license') or {}).get('spdx_id'), 'status': 'source_reviewed'}
            except Exception as exc:
                reviews[repo] = {'status': 'source_page_reviewed', 'metadata_error_type': type(exc).__name__}
        review = reviews[repo]
        if review.get('archived'):
            raise RuntimeError('Archived source must not enter curated catalog: ' + repo)
        servers.append(dict(id=ident, name=name, category=category, icon=icon, publisher=publisher, source_type=source_type,
            source_url=source, summary=summary, use_when=use, do_not_use_when=avoid, requirements=requirements,
            cost=cost, skills=skills, alternative_group=group, template=template,
            reviewed_at='2026-10-17', source_revision=review.get('revision', ''), review_status=review['status']))
    data = {'schema_version': 1, 'reviewed_at': '2026-10-17', 'servers': servers,
        'combinations': [
            {'name': '编程审阅', 'servers': ['github', 'context7'], 'skills': ['代码审阅', '故障诊断'], 'description': 'GitHub 提供远程证据，Context7 核对库文档；本机差异优先原文件与 Git 接口。'},
            {'name': '研究到方案', 'servers': ['brave-search', 'tavily', 'firecrawl', 'markitdown'], 'skills': ['需求到任务计划', '概念讲解与练习'], 'description': 'Brave / Tavily 按需二选一检索，再按资料类型选择网页采集或文件转换。'},
            {'name': '三维科普素材', 'servers': ['blender'], 'skills': ['概念讲解与练习'], 'description': '讲解流程组织原理与分镜，Blender 接入验收后承担三维场景与素材制作。固定齿轮交互仍可直接用 Anatomy。'}],
        'excluded': [
            {'name': '旧 GitHub / Brave / SQLite 等示例', 'reason': '官方参考仓库标记归档；GitHub、Brave 改选维护方服务器。', 'source_url': 'https://github.com/modelcontextprotocol/servers#archived'},
            {'name': 'Memory / Sequential Thinking / Time', 'reason': '暂不默认推荐：与既有记忆、模型推理或系统时间能力重叠，尚无明确新增收益。', 'source_url': 'https://github.com/modelcontextprotocol/servers'}]}
    path = ROOT / 'config/mcp/catalog.json'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = {'reviewed_at': data['reviewed_at'], 'sources': reviews, 'catalog_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'server_count': len(servers), 'installed': False, 'protocol_tested': False, 'tool_call_tested': False,
        'selection_basis': '维护方来源、具体用途、依赖与既有能力重叠；来源审阅不等于调用验证。'}
    (ROOT / 'evals/reports/mcp-source-review-2026-10-17.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'servers': len(servers), 'sources': {k: v['status'] for k, v in reviews.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
