"""逐次关闭一个机制，冻结模型文件不作实验性修改。"""
from 问题三四_正式算法与参数入口 import load


def solve(session, problem, settings=None):
    rt = load(problem)
    cfg = dict(settings or rt['settings'])
    label = cfg.pop('_ablation_label')
    expected = dict(rt['settings'])
    if label == 'no_posterior_optical':
        assert problem == 'q3'
        expected['posterior_optical'] = False
    elif label == 'no_cost_pair':
        assert problem == 'q3'
    elif label == 'no_transit':
        assert problem == 'q4'
        expected['intercept_cap'] = 0
    elif label == 'no_known_gate':
        assert problem == 'q4'
        expected['scan_gain_m'] = None
    else:
        assert label == 'complete'
    assert cfg == expected, 'Unexpected ablation configuration difference'
    cls = rt['klass']
    if label == 'no_cost_pair':
        class GeometryPairOnly(cls):
            def choose_pair(self, original, track, **kwargs):
                # 取费用混入类排名前的原几何候选。
                # 仍由阴性定位器的近点规则决定双侧点的先后。
                # 保留后验历史、光学位置选择和全部安全检查。
                pair = original(track, **kwargs)
                self.events.append(dict(method='v14_geometric_pair_without_cost_ranking',
                                        channel=track.channel,
                                        selected_points=pair['points'] if pair else None,
                                        ranking_only=True))
                return pair
        cls = GeometryPairOnly
    return cls(session, problem, cfg).run()
