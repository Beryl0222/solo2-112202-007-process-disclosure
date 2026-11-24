"""核心数据模型。

要素（Element）是工具的最小语义单位：对象、动作、条件、强度标记等都带原文
区间（span）与规范化后的因子（factor）。因子比较只走规范化签名，绝不按字面
相似度配对——资料中未记录的关系不允许用相似词补齐。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class ElementKind(str, Enum):
    OBJECT = "object"            # 对象：弹性底座、刚性底座、样架、转台……
    ACTION = "action"            # 动作：抬升、分两段、一步到位、保持接触……
    CONDITION = "condition"      # 条件：低压、空台……
    STRENGTH = "strength"        # 描述强度：只、仅、正是、一般……
    GENERIC = "generic"          # 通用性自称：示范、一般说明……
    REFERENCE = "reference"      # 引用另一页/另一载体的话
    ABSENCE = "absence"          # 明确未记录/否定：未说明、不……


class RefKind(str, Enum):
    SAME_IMPL = "same_impl"          # “接着 H1 的样架”——同一实施方式的续页
    ALTERNATIVE_IMPL = "alternative"  # 备选实施方式
    ANAPHORA = "anaphora"            # “刚才那台样架”——同场指代
    DELEGATE = "delegate"            # “动作按旁边口头提示”——动作交给另一载体
    CAPTION_SOURCE = "caption"       # “图注说明……”——信息来自图注
    REPEAT_STEP = "repeat_step"      # “步骤二只重复步骤一”


class Clearance(str, Enum):
    # 许可层级从宽到严
    PUBLIC = "可公开"
    SIGNED_ONLY = "签约可见"
    SECRET = "暂时保密"
    UNCONFIRMED = "待确认"

    @property
    def rank(self) -> int:
        return {"可公开": 0, "签约可见": 1, "暂时保密": 2, "待确认": 3}[self.value]


class Status(str, Enum):
    OPEN = "待确认"           # 引用/实施方式尚未验到签名原件
    VERIFIED = "已确认"       # 已验到签名公开存档
    REJECTED = "未采信"       # 核验未通过


class Phase(str, Enum):
    UNRELEASED = "未发"
    REHEARSAL = "排练"
    ONGOING = "进行中"
    ENDED = "活动结束"
    DISTRIBUTED = "已发"


# ---------------------------------------------------------------------------
# 文本要素
# ---------------------------------------------------------------------------
@dataclass
class Span:
    """原文区间。所有判断都要能回指到具体字串。"""
    text: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Element:
    eid: str                          # 记录内编号，如 D1:e1
    kind: ElementKind
    factor: str                       # 规范化因子，如 object.elastic_base
    display: str                      # 人类可读名称（中文）
    span: Span
    strength: str | None = None       # 同句强度标记，如 只/仅/正是
    seq: int | None = None            # 动作先后：1、2……
    absent: bool = False              # 是否为“未记录/否定”要素
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass
class Reference:
    rid: str
    kind: RefKind
    target: str                       # 被引用的 edition / 载体 / 步骤标识
    span: Span
    note: str = ""                    # 解析说明
    status: Status = Status.OPEN
    verified_against: str | None = None  # 验到的签名原件记录 id

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["status"] = self.status.value
        return data


# ---------------------------------------------------------------------------
# 记录
# ---------------------------------------------------------------------------
@dataclass
class Disclosure:
    """一份可确认公开记录（旧展示物的一个发行版）。"""
    rid: str
    edition: str
    audience: str
    context: str
    text: str
    elements: list[Element] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    impl_group: str = ""              # 同一实施方式分组 id
    signed: bool = False              # 是否已进入带签名公开存档

    @property
    def positive_factors(self) -> set[str]:
        """该记录确实陈述（而非否定/未说明）的因子集合。"""
        return {e.factor for e in self.elements if not e.absent}

    def to_dict(self) -> dict[str, Any]:
        return {
            "rid": self.rid,
            "edition": self.edition,
            "audience": self.audience,
            "context": self.context,
            "text": self.text,
            "elements": [e.to_dict() for e in self.elements],
            "references": [r.to_dict() for r in self.references],
            "impl_group": self.impl_group,
            "signed": self.signed,
        }


@dataclass
class Proposal:
    """一份拟演示稿（展板/讲解/闭门讲义/会后材料）。"""
    pid: str
    stage: str
    bind: str
    text: str
    elements: list[Element] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    @property
    def positive_factors(self) -> set[str]:
        return {e.factor for e in self.elements if not e.absent}

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "stage": self.stage,
            "bind": self.bind,
            "text": self.text,
            "elements": [e.to_dict() for e in self.elements],
            "references": [r.to_dict() for r in self.references],
        }


@dataclass
class Approval:
    """工程员登记的批准。scope 保留原话，另做结构化解析。"""
    aid: str
    proposal_id: str
    canonical_id: str
    scope_text: str
    clearance: Clearance
    factor_grants: dict[str, Clearance] = field(default_factory=dict)
    guarded_combos: list[list[str]] = field(default_factory=list)
    conditional: bool = False         # 需先验到签名公开页（如 A3）
    condition_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aid": self.aid,
            "proposal_id": self.proposal_id,
            "canonical_id": self.canonical_id,
            "scope_text": self.scope_text,
            "clearance": self.clearance.value,
            "factor_grants": {k: v.value for k, v in self.factor_grants.items()},
            "guarded_combos": self.guarded_combos,
            "conditional": self.conditional,
            "condition_note": self.condition_note,
        }


@dataclass
class AudienceBatch:
    """一批观众及其实际接触/计划接触的材料。"""
    sid: str
    viewers: str
    phase: Phase
    seen: list[str]                   # 实际已被看到的 proposal id
    planned: list[str]                # 待处理组合

    def to_dict(self) -> dict[str, Any]:
        return {
            "sid": self.sid,
            "viewers": self.viewers,
            "phase": self.phase.value,
            "seen": self.seen,
            "planned": self.planned,
        }


# ---------------------------------------------------------------------------
# 编审结论
# ---------------------------------------------------------------------------
@dataclass
class PrecedentHit:
    """一组相互约束要素在同一份公开记录、同一实施条件下同时出现的证据。"""
    factors: list[str]
    record_id: str
    impl_group: str
    audience: str
    spans: list[Span]
    same_record: bool
    same_impl: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "factors": self.factors,
            "record_id": self.record_id,
            "impl_group": self.impl_group,
            "audience": self.audience,
            "spans": [s.to_dict() for s in self.spans],
            "same_record": self.same_record,
            "same_impl": self.same_impl,
        }


@dataclass
class SplitTrap:
    """相似但不相干的两条被误凑成先例的情形。"""
    factors: list[str]
    across_records: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LeakPath:
    """观众联合多份材料推出保密关系的推理路径。"""
    combo: list[str]
    guarded_basis: str               # 保密依据（批准原话或工程员标记）
    contributed: dict[str, list[str]]  # proposal_id -> 该稿贡献的因子
    linking_cues: list[str]          # 让两稿能被串起来的指代/图注/顺序线索
    evidence: list[str]              # 原文摘录

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EditOption:
    kind: str                        # delete / replace / restrict_audience
    target_pid: str
    factors: list[str]
    description: str
    principle_kept: list[str]        # 该改法仍保留的公开原理动作
    broken_premises: list[str]       # 失去前提、讲不清原理的部分


@dataclass
class BundleVerdict:
    bind: str
    audience: str
    approvable: bool
    reasons: list[str]
    leak_paths: list[LeakPath] = field(default_factory=list)
    options: list[EditOption] = field(default_factory=list)
    precedent_hits: list[PrecedentHit] = field(default_factory=list)
    split_traps: list[SplitTrap] = field(default_factory=list)
    unconfirmed_relations: list[str] = field(default_factory=list)
    generic_overreach: list[str] = field(default_factory=list)
    broken_premises: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bind": self.bind,
            "audience": self.audience,
            "approvable": self.approvable,
            "reasons": self.reasons,
            "leak_paths": [p.to_dict() for p in self.leak_paths],
            "options": [asdict(o) for o in self.options],
            "precedent_hits": [h.to_dict() for h in self.precedent_hits],
            "split_traps": [t.to_dict() for t in self.split_traps],
            "unconfirmed_relations": self.unconfirmed_relations,
            "generic_overreach": self.generic_overreach,
            "broken_premises": self.broken_premises,
        }


@dataclass
class Event:
    """留痕事件：项目要能回查每次判断的来由。"""
    seq: int
    time: str
    actor: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
