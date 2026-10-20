"""Host-owned bounded team allocation, never delegated to an untrusted model."""
from .resources import memory_snapshot, MIB


def allocate(args, probe=memory_snapshot):
    maximum = args.get('max_agents', 2)
    count = 2
    reason = '固定方案与独立审阅；按顺序执行，保留前台资源。'
    if args.get('auto_team'):
        desired = min(maximum, 2 + (len(args['criteria']) >= 3) + (len(args['criteria']) >= 5))
        try:
            sample = probe()
            headroom = min(sample['available_bytes'], sample['commit_available_bytes'])
            # A conservative admission signal, not an OS memory reservation.
            count = desired if headroom >= 1024*MIB else 2
            reason = f'按 {len(args["criteria"])} 条要求分配；内存余量支持 {count} 个顺序角色，上限 {maximum}。'
        except (OSError, KeyError, TypeError):
            reason = '资源信息不可用，缩减为两个顺序角色；执行前仍经过队列资源准入。'
    roles = ['planner'] + ['specialist'+str(i+1) for i in range(count-2)] + ['reviewer']
    return {'roles':roles, 'reason':reason, 'max_model_calls':count, 'concurrency':1,
            'max_output_tokens_per_call':2048, 'automatic_retries':0}


def model_role(role):
    return 'reviewer' if role == 'reviewer' else 'planner'
