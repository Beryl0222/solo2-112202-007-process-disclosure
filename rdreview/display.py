"""人类可读的中文输出格式化。"""
from __future__ import annotations

from .lexicon import FACTOR_DISPLAY
from .models import BundleVerdict


def f(factor: str) -> str:
    return FACTOR_DISPLAY.get(factor, factor)


def fl(factors) -> str:
    return "、".join(f(x) for x in factors) if factors else "（无）"


def print_record(record) -> None:
    header = (
        f"{record.rid} [{record.edition}] 观众={record.audience} "
        f"场景={record.context}"
        if hasattr(record, "edition") else
        f"{record.pid} 载体={record.stage} 装订组={record.bind}"
    )
    print(header)
    print(f"  原文：{record.text}")
    for element in record.elements:
        tag = "［缺席］" if element.absent else ""
        seq = f" 顺序={element.seq}" if element.seq is not None else ""
        strength = f" 强度={element.strength}" if element.strength else ""
        source = f" 来源={element.extra['source']}" if element.extra.get("source") else ""
        print(f"  - {element.kind.value:9} {element.factor:28} "
              f"“{element.span.text}”{tag}{seq}{strength}{source}")
    for ref in record.references:
        print(f"  引用 [{ref.kind.value}] “{ref.span.text}” "
              f"目标={ref.target} 状态={ref.status.value}（{ref.note}）")


def print_verdict(verdict: BundleVerdict) -> None:
    print(f"装订组 {verdict.bind} / 观众：{verdict.audience}")
    print(f"结论：{'可盖章' if verdict.approvable else '不可盖章'}")
    print("判断理由：")
    for reason in verdict.reasons:
        print(f"  - {reason}")
    if verdict.precedent_hits:
        print("共同公开先例（同一记录、同一实施条件同时出现）：")
        for hit in verdict.precedent_hits:
            scope = "同一份记录" if hit.same_record else "同一实施方式续页"
            print(f"  - {fl(hit.factors)} → {hit.record_id}"
                  f"（{scope}，观众={hit.audience}）")
    if verdict.split_traps:
        print("拆分陷阱（不得按相似措辞拼凑的情形）：")
        for trap in verdict.split_traps:
            print(f"  - 涉及 {fl(trap.factors)}：{trap.reason}")
    if verdict.unconfirmed_relations:
        print("留待工程员确认的关系：")
        for item in verdict.unconfirmed_relations:
            print(f"  - {item}")
    if verdict.generic_overreach:
        print("通用性越界：")
        for item in verdict.generic_overreach:
            print(f"  - {item}")
    if verdict.leak_paths:
        print("联合推断泄密路径：")
        for path in verdict.leak_paths:
            print(f"  - 保密组合：{fl(path.combo)}（依据：{path.guarded_basis}）")
            for pid, part in path.contributed.items():
                print(f"      {pid} 贡献：{fl(part)}")
            print("    串接线索：")
            for cue in path.linking_cues:
                print(f"      · {cue}")
            print("    原文证据：")
            for evidence in path.evidence:
                print(f"      · {evidence}")
    if verdict.options:
        print("编审改法（优先保留讲清原理所需的公开动作）：")
        for index, option in enumerate(verdict.options, start=1):
            kind_name = {
                "delete": "可删",
                "replace": "可换",
                "restrict_audience": "只能给另一组观众",
            }[option.kind]
            print(f"  {index}. [{kind_name}] {option.description}")
            print(f"     保留的公开原理动作：{fl(option.principle_kept)}")
            if option.broken_premises:
                print(f"     失去前提、讲不清的部分：{fl(option.broken_premises)}")
    if verdict.broken_premises:
        print("前提缺失：")
        for item in verdict.broken_premises:
            print(f"  - {item}")


def verdict_to_dict(verdict: BundleVerdict) -> dict:
    return verdict.to_dict()
