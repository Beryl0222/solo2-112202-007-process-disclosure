"""命令行入口：反复接收编审动作，每次操作都留痕可回查。

用法示例：
  python3 -I rdreview/cli.py list
  python3 -I rdreview/cli.py review S1
  python3 -I rdreview/cli.py verify D4 --actor 张工
  python3 -I rdreview/cli.py incident S1 --actor 编审员
  python3 -I rdreview/cli.py trace 低压
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 本环境的隔离模式不保留当前目录，显式注入可信代码目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rdreview.display import f, fl, print_record, print_verdict  # noqa: E402
from rdreview.models import Clearance  # noqa: E402
from rdreview.project import ReviewProject  # noqa: E402

DEFAULT_MATERIALS = Path(__file__).resolve().parent.parent / "materials"
DEFAULT_WORK = Path(__file__).resolve().parent.parent / "review_workspace"


def _project(args: argparse.Namespace) -> ReviewProject:
    return ReviewProject(
        materials_dir=Path(args.materials),
        work_dir=Path(args.work),
    )


def cmd_list(args: argparse.Namespace) -> None:
    project = _project(args)
    print("== 旧展示物（可确认公开记录候选）==")
    for record in project.disclosures:
        signed = "已验签" if record.signed else "未验签"
        print(f"  {record.rid} {record.edition} {record.audience} "
              f"{record.context} 实施组={record.impl_group} [{signed}]")
    print("== 拟演示稿 ==")
    for record in project.proposals:
        print(f"  {record.pid} {record.stage} 装订组={record.bind}")
    print("== 批准登记 ==")
    for approval in project.approvals:
        print(f"  {approval.aid} {approval.proposal_id}←{approval.canonical_id} "
              f"{approval.clearance.value} 条件性={approval.conditional}")
        print(f"      原话：{approval.scope_text}")
    print("== 观众批次 ==")
    for batch in project.sessions:
        print(f"  {batch.sid} {batch.viewers} {batch.phase.value} "
              f"已看={batch.seen} 待发={batch.planned}")
    print("== 实施方式分组 ==")
    for group, members in project.grouping.groups.items():
        print(f"  组 {group}：{members}")
    for note in project.grouping.unconfirmed:
        print(f"  待确认：{note}")


def cmd_show(args: argparse.Namespace) -> None:
    project = _project(args)
    target = args.id
    record = next((d for d in project.disclosures if d.rid == target), None)
    if record is None:
        record = next((p for p in project.proposals if p.pid == target), None)
    if record is None:
        raise SystemExit(f"找不到记录 {target}")
    print_record(record)


def cmd_refs(args: argparse.Namespace) -> None:
    project = _project(args)
    for record in project.disclosures + project.proposals:
        rid = getattr(record, "rid", getattr(record, "pid", "?"))
        for ref in record.references:
            print(f"{rid} -> [{ref.kind.value}] {ref.target or ref.note} "
                  f"状态={ref.status.value}：{ref.note}")


def cmd_precedent(args: argparse.Namespace) -> None:
    project = _project(args)
    if args.proposal:
        factors, hits, traps = project.precedent_for_proposal(args.proposal)
        print(f"{args.proposal} 的实质因子：{fl(factors)}")
    else:
        factors = [x.strip() for x in args.factors.split(",") if x.strip()]
        hits, traps = project.precedent_for_factors(factors)
        print(f"待查因子：{fl(factors)}")
    print("命中先例：")
    for hit in hits:
        scope = "同一份记录" if hit.same_record else "同一实施方式续页"
        print(f"  - {hit.record_id}（{scope}，观众={hit.audience}）：{fl(hit.factors)}")
    print("拆分陷阱：")
    for trap in traps:
        print(f"  - {trap.reason}")


def cmd_review(args: argparse.Namespace) -> None:
    project = _project(args)
    verdict = project.review_session(
        args.session, include_planned=not args.seen_only
    )
    if args.json:
        print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_verdict(verdict)


def cmd_clear(args: argparse.Namespace) -> None:
    project = _project(args)
    clearance = Clearance(args.level)
    project.store.add_override(args.pid, args.factor, clearance.value, args.actor)
    project.reload()
    result = project.resolver.resolve(args.pid, args.factor)
    print(f"{args.pid}:{args.factor} -> {result.clearance.value}")
    for basis in result.basis:
        print(f"  依据：{basis}")


def cmd_verify(args: argparse.Namespace) -> None:
    project = _project(args)
    result = project.verify_signed_archive(args.id, args.actor)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_replace(args: argparse.Namespace) -> None:
    project = _project(args)
    project.store.add_replacement(
        args.pid, args.old, args.new, args.note, args.actor
    )
    project.reload()
    print(f"已登记替换：{args.pid} {f(args.old)} -> {args.note}")


def cmd_re_audience(args: argparse.Namespace) -> None:
    project = _project(args)
    project.store.set_re_audience(args.pid, args.audience, args.actor)
    project.reload()
    print(f"已限制 {args.pid} 仅向 {args.audience} 发放")


def cmd_drop(args: argparse.Namespace) -> None:
    project = _project(args)
    project.store.drop_factor(args.pid, args.factor, args.actor)
    project.reload()
    print(f"已在模拟版本中删除 {args.pid}:{f(args.factor)}")


def cmd_restore(args: argparse.Namespace) -> None:
    project = _project(args)
    project.store.restore_factor(args.pid, args.factor, args.actor)
    project.reload()
    print(f"已恢复 {args.pid}:{f(args.factor)}")


def cmd_generic(args: argparse.Namespace) -> None:
    project = _project(args)
    findings = project.generic_overreach()
    if not findings:
        print("未发现通用性越界")
    for item in findings:
        print(f"{item.proposal_id} 自称“{item.claim}”，"
              f"可支持实物仅 {item.supported_examples}")
        print(f"  {item.note}")


def cmd_incident(args: argparse.Namespace) -> None:
    project = _project(args)
    result = project.handle_post_event_incident(args.session, args.actor)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_ingest(args: argparse.Namespace) -> None:
    """重新接收资料包：解析新版 TSV，保留已登记的编审状态并重新评估。"""
    project = _project(args)
    project.reload()
    project.store.log(args.actor, "重新接收资料包并解析", {
        "materials": str(Path(args.materials).resolve()),
        "disclosures": [d.rid for d in project.disclosures],
        "proposals": [p.pid for p in project.proposals],
    })
    print(
        f"已接收：旧展示物 {len(project.disclosures)} 份、"
        f"拟演示稿 {len(project.proposals)} 份、"
        f"批准 {len(project.approvals)} 条、观众批次 {len(project.sessions)} 个"
    )
    # 状态里引用了已不存在的记录时显式告警，不静默丢弃
    stale = []
    pids = {p.pid for p in project.proposals}
    rids = {d.rid for d in project.disclosures}
    for pid, *_ in project.store.data["overrides"]:
        if pid not in pids:
            stale.append(f"确认记录引用了已不存在的稿件 {pid}")
    for rid in project.store.data["signed"]:
        if rid not in rids:
            stale.append(f"验签记录引用了已不存在的旧展示物 {rid}")
    for item in stale:
        print("  告警：", item)


def cmd_trace(args: argparse.Namespace) -> None:
    project = _project(args)
    for event in project.trace(args.keyword or ""):
        print(f"#{event['seq']} [{event['time']}] {event['actor']} "
              f"{event['action']} {json.dumps(event['payload'], ensure_ascii=False)}")


def cmd_snapshot(args: argparse.Namespace) -> None:
    project = _project(args)
    payload = {
        "sessions": [batch.to_dict() for batch in project.sessions],
        "signed": project.store.data["signed"],
        "overrides": project.store.data["overrides"],
        "freezes": project.store.data["freezes"],
    }
    path = project.store.snapshot(args.name, payload, args.actor)
    print(f"快照已保存：{path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="研发编审工具：公开先例与保密边界核查"
    )
    parser.add_argument("--materials", default=str(DEFAULT_MATERIALS))
    parser.add_argument("--work", default=str(DEFAULT_WORK))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出全部记录与分组").set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="展示单条记录的要素与引用")
    show.add_argument("id")
    show.set_defaults(func=cmd_show)

    sub.add_parser("refs", help="列出全部跨页/跨载体引用").set_defaults(func=cmd_refs)

    precedent = sub.add_parser("precedent", help="核查一组要素的共同公开先例")
    precedent.add_argument("--proposal", help="按某拟演示稿的全部因子核查")
    precedent.add_argument("--factors", help="手工指定因子，逗号分隔")
    precedent.set_defaults(func=cmd_precedent)

    review = sub.add_parser("review", help="按观众批次评审整组材料")
    review.add_argument("session")
    review.add_argument("--seen-only", action="store_true",
                        help="只评实际已看部分，不含待发组合")
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)

    clear = sub.add_parser("clear", help="工程员确认要素许可")
    clear.add_argument("pid")
    clear.add_argument("factor")
    clear.add_argument("level", choices=[c.value for c in Clearance])
    clear.add_argument("--actor", default="工程员")
    clear.set_defaults(func=cmd_clear)

    verify = sub.add_parser("verify", help="验签补入的签名公开存档")
    verify.add_argument("id")
    verify.add_argument("--actor", default="工程员")
    verify.set_defaults(func=cmd_verify)

    replace = sub.add_parser("replace", help="登记替换表述")
    replace.add_argument("pid")
    replace.add_argument("old")
    replace.add_argument("new")
    replace.add_argument("note")
    replace.add_argument("--actor", default="工程员")
    replace.set_defaults(func=cmd_replace)

    re_audience = sub.add_parser("re-audience", help="限制稿件发放观众")
    re_audience.add_argument("pid")
    re_audience.add_argument("audience")
    re_audience.add_argument("--actor", default="工程员")
    re_audience.set_defaults(func=cmd_re_audience)

    drop = sub.add_parser("drop", help="模拟删除因子")
    drop.add_argument("pid")
    drop.add_argument("factor")
    drop.add_argument("--actor", default="编审员")
    drop.set_defaults(func=cmd_drop)

    restore = sub.add_parser("restore", help="恢复被删因子")
    restore.add_argument("pid")
    restore.add_argument("factor")
    restore.add_argument("--actor", default="编审员")
    restore.set_defaults(func=cmd_restore)

    sub.add_parser("generic", help="通用性越界检查").set_defaults(func=cmd_generic)

    incident = sub.add_parser("incident", help="会后限制扩面事故立案")
    incident.add_argument("session")
    incident.add_argument("--actor", default="编审员")
    incident.set_defaults(func=cmd_incident)

    ingest = sub.add_parser(
        "ingest", help="重新接收资料包并解析（保留编审状态）"
    )
    ingest.add_argument("--actor", default="编审员")
    ingest.set_defaults(func=cmd_ingest)

    trace = sub.add_parser("trace", help="回查判断来由")
    trace.add_argument("keyword", nargs="?", default="")
    trace.set_defaults(func=cmd_trace)

    snapshot = sub.add_parser("snapshot", help="保存当前演示快照")
    snapshot.add_argument("name")
    snapshot.add_argument("--actor", default="编审员")
    snapshot.set_defaults(func=cmd_snapshot)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
