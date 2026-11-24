"""实施方式分组与公开先例判断。

规则：
- 同一实施方式只由显式引用（“本页接着 Hx 的样架”）或工程员确认建立，
  绝不靠措辞相似合并。
- 一组相互约束的要素，只有在同一份公开记录、同一实施条件下同时出现，
  才构成可援引先例；跨记录拼凑只产生“拆分陷阱”提示，并逐条说明每条记录
  为什么不能凑用（闭门、未验签、缺记、实施条件不同）。
- “未说明 X”的缺席要素与闭门场记录都不能支持公开先例。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    Disclosure,
    PrecedentHit,
    RefKind,
    SplitTrap,
    Status,
)


@dataclass
class ImplLink:
    source_id: str
    target_edition: str
    target_id: str | None
    kind: RefKind
    note: str
    status: Status


@dataclass
class ImplGrouping:
    groups: dict[str, list[str]] = field(default_factory=dict)
    links: list[ImplLink] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)


def build_impl_groups(disclosures: list[Disclosure]) -> ImplGrouping:
    """按显式 same_impl 引用把旧展示物归入同一实施方式组。"""
    by_edition = {d.edition: d.rid for d in disclosures}
    grouping = ImplGrouping()
    member_of = {d.rid: d.rid for d in disclosures}

    for disclosure in disclosures:
        for ref in disclosure.references:
            if ref.kind is not RefKind.SAME_IMPL:
                continue
            target_id = by_edition.get(ref.target)
            link = ImplLink(
                source_id=disclosure.rid,
                target_edition=ref.target,
                target_id=target_id,
                kind=ref.kind,
                note=ref.note,
                status=ref.status,
            )
            grouping.links.append(link)
            if target_id is None or ref.status is not Status.VERIFIED:
                grouping.unconfirmed.append(
                    f"{disclosure.rid} 声称接续 {ref.target} 的同一实施方式，"
                    "但签名公开页尚未验到，关系留待工程员确认"
                )
                continue
            left, right = member_of[disclosure.rid], member_of[target_id]
            keep, drop = sorted((left, right))
            for rid, group in list(member_of.items()):
                if group == drop:
                    member_of[rid] = keep

    for rid, group in member_of.items():
        grouping.groups.setdefault(group, []).append(rid)
    for members in grouping.groups.values():
        members.sort()

    for disclosure in disclosures:
        disclosure.impl_group = member_of[disclosure.rid]
    return grouping


def _public_records(disclosures: list[Disclosure]) -> list[Disclosure]:
    """公开观众可援引的记录。

    - audience 为“公开”且已验到签名存档；
    - audience 为“公开待核”的续页，验签后同样成为可确认公开记录。
    闭门场记录任何情况下都不进入。
    """
    return [
        d for d in disclosures
        if d.audience in ("公开", "公开待核") and d.signed
    ]


def _record_blockers(record: Disclosure, wanted: set[str]) -> list[str]:
    """说明某条记录为什么不能完整支持这组因子。"""
    blockers: list[str] = []
    if record.audience == "闭门":
        blockers.append("闭门场记录，公开观众无法接触，不能充当公开先例")
    elif not record.signed:
        blockers.append(
            f"发行状态为“{record.audience}”且未验签，不是可确认公开记录"
        )
    missing = wanted - record.positive_factors
    if missing:
        # 区分“明确缺记/否定”与“根本没提”
        absent = {e.factor for e in record.elements if e.absent}
        noted = sorted(missing & absent)
        unmentioned = sorted(missing - absent)
        if noted:
            blockers.append(f"明确未记录/否定：{noted}")
        if unmentioned:
            blockers.append(f"未出现：{unmentioned}")
    return blockers


def check_precedent(
    factors: list[str],
    disclosures: list[Disclosure],
    grouping: ImplGrouping,
) -> tuple[list[PrecedentHit], list[SplitTrap]]:
    """判断一组相互约束要素是否在同一公开记录、同一实施条件下同时出现。"""
    wanted = set(factors)
    hits: list[PrecedentHit] = []
    traps: list[SplitTrap] = []

    public_ids = {d.rid for d in _public_records(disclosures)}

    for record in disclosures:
        supported = wanted & record.positive_factors
        if not supported:
            continue
        spans = [e.span for e in record.elements if e.factor in supported]
        if record.rid in public_ids and wanted <= record.positive_factors:
            hits.append(PrecedentHit(
                factors=sorted(wanted),
                record_id=record.rid,
                impl_group=record.impl_group,
                audience=record.audience,
                spans=spans,
                same_record=True,
                same_impl=True,
            ))
            continue
        blockers = _record_blockers(record, wanted)
        traps.append(SplitTrap(
            factors=sorted(supported),
            across_records=[record.rid],
            reason=(
                f"{record.rid}（{record.context}）只同时出现 {sorted(supported)}；"
                + "；".join(blockers)
                + "。不能把它与别的记录按相似措辞凑成同一先例"
            ),
        ))

    # 同一实施方式续页：各页均为可确认公开记录、续页关系已验签时才允许跨页并组
    for group_id, members in grouping.groups.items():
        group_records = [
            d for d in disclosures
            if d.rid in members and d.rid in public_ids
        ]
        if len(group_records) < 2:
            continue
        union: set[str] = set()
        for record in group_records:
            union |= wanted & record.positive_factors
        if wanted <= union and not any(wanted <= r.positive_factors
                                       for r in group_records):
            links = [
                link for link in grouping.links
                if link.source_id in members and link.target_id in members
            ]
            if links and all(link.status is Status.VERIFIED for link in links):
                spans = [
                    e.span
                    for record in group_records
                    for e in record.elements
                    if e.factor in wanted
                ]
                hits.append(PrecedentHit(
                    factors=sorted(wanted),
                    record_id="+".join(sorted(members)),
                    impl_group=group_id,
                    audience="公开（同一实施方式续页）",
                    spans=spans,
                    same_record=False,
                    same_impl=True,
                ))
            else:
                traps.append(SplitTrap(
                    factors=sorted(union),
                    across_records=sorted(members),
                    reason=(
                        f"同一实施方式续页关系未验签，{sorted(wanted)} 暂不能跨页并组"
                    ),
                ))

    if not hits and not traps:
        traps.append(SplitTrap(
            factors=sorted(wanted),
            across_records=[],
            reason="所有旧展示物都未出现这组要素，无任何可援引来源",
        ))
    return hits, traps
