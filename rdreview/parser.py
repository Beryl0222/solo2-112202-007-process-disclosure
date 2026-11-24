"""规则解析器：把中文技术说明切成对象、动作、条件、强度与引用。

设计取舍：
- 只做受控词库内的规则匹配，不做相似度归并；认不出的关系留给工程员确认。
- “未说明 X”产生的是缺席要素（absent=True），绝不计入公开因子。
- 引用单独建 Reference 对象，区分同一实施方式续页、备选、同场指代、
  动作委托、图注来源、步骤重复六种。
- 引用不占用文本区间：图注引用内部的“低压/两段”等要素仍要抽出来，只是
  标注来源为图注；被引用语（如“接着 H1 的样架”）内的词不计入要素。
"""
from __future__ import annotations

import re

from .lexicon import (
    ABSENCE_PATTERN,
    ALTERNATIVE_HINTS,
    PATTERNS,
    REF_PATTERNS,
    SEQ_PATTERNS,
    FACTOR_DISPLAY,
)
from .models import (
    Disclosure,
    Element,
    ElementKind,
    Proposal,
    RefKind,
    Reference,
    Span,
    Status,
)

# 这些引用内部的词仍是本载体陈述的内容（图注是信息来源，不是被引用的他页）。
TRANSPARENT_REFS = {RefKind.CAPTION_SOURCE}


def _clause_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.compile(r"[；;。]").finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _seq_in(text: str) -> int | None:
    for pattern, seq in SEQ_PATTERNS:
        if pattern.search(text):
            return seq
    return None


def parse_text(text: str, id_prefix: str) -> tuple[list[Element], list[Reference]]:
    elements: list[Element] = []
    references: list[Reference] = []
    counter = 0
    ref_counter = 0
    occupied: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return not any(not (end <= s or start >= e) for s, e in occupied)

    # —— 先识别引用 ——
    for pattern in REF_PATTERNS:
        for match in re.finditer(pattern.regex, text):
            ref_counter += 1
            target = match.groupdict().get("target", "")
            if pattern.kind is RefKind.CAPTION_SOURCE:
                target = "图注"
            elif pattern.kind in (RefKind.ANAPHORA, RefKind.DELEGATE,
                                  RefKind.REPEAT_STEP):
                target = target or pattern.note
            references.append(Reference(
                rid=f"{id_prefix}:r{ref_counter}",
                kind=pattern.kind,
                target=target,
                span=Span(match.group(0), match.start(), match.end()),
                note=pattern.note,
                status=Status.OPEN,
            ))
            # 不透明引用（引用他页/他载体的话）内部不抽要素；图注保持透明
            if pattern.kind not in TRANSPARENT_REFS:
                occupied.append((match.start(), match.end()))

    clauses = _clause_spans(text)

    def clause_of(pos: int) -> str:
        for start, end in clauses:
            if start <= pos < end:
                return text[start:end]
        return text

    def inside_ref(pos: int, kinds: set[RefKind]) -> bool:
        return any(
            ref.kind in kinds and ref.span.start <= pos < ref.span.end
            for ref in references
        )

    # —— 缺席/否定：“未说明低压”——
    for match in ABSENCE_PATTERN.finditer(text):
        if not free(match.start(), match.end()):
            continue
        what = match.groupdict().get("what")
        factor = {
            "低压": "condition.low_pressure",
            "两段": "action.two_stage",
            "保持接触": "action.hold_contact",
            "弹性": "object.elastic_base",
            "刚性": "object.rigid_base",
        }.get(what or "")
        if factor is None:
            continue
        counter += 1
        elements.append(Element(
            eid=f"{id_prefix}:e{counter}",
            kind=ElementKind.ABSENCE,
            factor=factor,
            display=f"未记录：{FACTOR_DISPLAY[factor]}",
            span=Span(match.group(0), match.start(), match.end()),
            absent=True,
        ))
        occupied.append((match.start(), match.end()))

    # —— 受控要素匹配 ——
    for pattern in PATTERNS:
        for match in re.finditer(pattern.regex, text):
            start, end = match.start(), match.end()
            if not free(start, end):
                continue
            clause = clause_of(start)
            counter += 1
            element = Element(
                eid=f"{id_prefix}:e{counter}",
                kind=pattern.kind,
                factor=pattern.factor,
                display=pattern.display,
                span=Span(match.group(0), start, end),
            )
            # 动作先后只挂动作与条件（对象不承担顺序）
            if pattern.kind in (ElementKind.ACTION, ElementKind.CONDITION):
                element.seq = _seq_in(clause)
                for strength in ("正是", "仅", "只"):
                    if strength in clause:
                        element.strength = strength
                        break
            # 图注句中的要素标记来源，供联合推断使用
            if inside_ref(start, {RefKind.CAPTION_SOURCE}):
                element.extra["source"] = "caption"
            elements.append(element)
            occupied.append((start, end))

    # —— 备选实施方式信号 ——
    for hint in ALTERNATIVE_HINTS:
        for match in re.finditer(hint, text):
            ref_counter += 1
            references.append(Reference(
                rid=f"{id_prefix}:r{ref_counter}",
                kind=RefKind.ALTERNATIVE_IMPL,
                target="",
                span=Span(match.group(0), match.start(), match.end()),
                note="出现备选实施语言，相关要素不得与主实施方式并为同一先例",
                status=Status.OPEN,
            ))

    elements.sort(key=lambda e: e.span.start)
    references.sort(key=lambda r: r.span.start)
    return elements, references


def parse_disclosure(row: dict[str, str]) -> Disclosure:
    elements, references = parse_text(row["text"], row["id"])
    return Disclosure(
        rid=row["id"],
        edition=row["edition"],
        audience=row["audience"],
        context=row["context"],
        text=row["text"],
        elements=elements,
        references=references,
    )


def parse_proposal(row: dict[str, str]) -> Proposal:
    elements, references = parse_text(row["text"], row["id"])
    return Proposal(
        pid=row["id"],
        stage=row["stage"],
        bind=row["bind"],
        text=row["text"],
        elements=elements,
        references=references,
    )
