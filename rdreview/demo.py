"""端到端编审故事线演示（只读资料包，状态写入临时目录）。

运行：python3 -I rdreview/demo.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rdreview.display import fl, print_verdict  # noqa: E402
from rdreview.models import Clearance  # noqa: E402
from rdreview.project import ReviewProject  # noqa: E402

MATERIALS = Path(__file__).resolve().parent.parent / "materials"


def line(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="rdreview_demo_"))
    project = ReviewProject(MATERIALS, work)

    line("一、初始状态：D4 续页未验签，实施方式关系留待确认")
    for note in project.grouping.unconfirmed:
        print("  -", note)

    line("二、公开登记组 S1（已看 P1 展板 + P2 讲解，待发 P4 会后资料）")
    print_verdict(project.review_session("S1"))

    line("三、签约组 S2：闭门讲义 P3 在签约范围内，可盖章")
    verdict_s2 = project.review_session("S2")
    print(f"结论：{'可盖章' if verdict_s2.approvable else '不可盖章'}")

    line("四、只删 P2 的“低压”一词：P4 图注仍带低压，组合仍可推出")
    project.store.drop_factor("P2", "condition.low_pressure", "编审员")
    project.reload()
    verdict = project.review_session("S1")
    print(f"泄密路径数：{len(verdict.leak_paths)}（>0 说明单删工艺词无效）")
    for path in verdict.leak_paths:
        print("  仍可推出：", fl(path.combo), "来源：", path.contributed)
    project.store.restore_factor("P2", "condition.low_pressure", "编审员")
    project.reload()

    line("五、排练后 D4 补入带签名公开存档：重新判断缺证实施方式")
    result = project.verify_signed_archive("D4", "张工")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    line("六、验签后先例：弹性底座+两段+保持接触 有续页先例；加低压仍无")
    supported = [
        "object.elastic_base", "action.two_stage_lift", "action.hold_contact"
    ]
    hits, traps = project.precedent_for_factors(supported)
    print("已公开组合：", fl(supported))
    for hit in hits:
        scope = "同一份记录" if hit.same_record else "同一实施方式续页"
        print(f"  先例命中：{hit.record_id}（{scope}）{fl(hit.factors)}")
    low_hits, low_traps = project.precedent_for_factors(
        ["object.elastic_base", "action.two_stage_lift",
         "condition.low_pressure"]
    )
    print("含低压组合的先例命中数：", len(low_hits))
    for trap in low_traps:
        print("  -", trap.reason)

    line("七、通用性越界：P1 自称示范，公开记录只支持一款实物")
    for finding in project.generic_overreach():
        print(f"  {finding.proposal_id}：{finding.note}")

    line("八、展示结束：会后资料 P4 把闭门限制扩到公开观众，立案处理")
    incident = project.handle_post_event_incident("S1", "编审员")
    print(json.dumps(incident, ensure_ascii=False, indent=2))

    line("九、回查：本次演示的先例出处、许可与不能合并发的来由")
    for event in project.trace():
        print(f"#{event['seq']} [{event['time']}] {event['actor']} "
              f"{event['action']}")
        if event["payload"]:
            print("    ", json.dumps(event["payload"], ensure_ascii=False))

    print("\n演示工作区：", work)
    print("（保留全部留痕与快照；如需清理可删除该目录）")


if __name__ == "__main__":
    main()
