"""受控词库与匹配模式。

所有因子（factor）都有固定的规范化名称和中文显示名。两份材料里措辞不同的词
（如“弹性底座”与“弹性样架”）不会因为相似就合并——是否同一实施方式由引用
关系和工程员确认决定，词库本身不做相似度归并。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ElementKind, RefKind


@dataclass(frozen=True)
class Pattern:
    regex: str
    kind: ElementKind
    factor: str
    display: str


# 顺序即优先级：先长后短，避免“弹性底座”被“底座”抢先匹配。
PATTERNS: list[Pattern] = [
    # —— 对象 ——
    Pattern(r"弹性样架", ElementKind.OBJECT, "object.elastic_frame", "弹性样架"),
    Pattern(r"弹性底座", ElementKind.OBJECT, "object.elastic_base", "弹性底座"),
    Pattern(r"弹性", ElementKind.OBJECT, "object.elastic_base", "弹性（底座/样架）"),
    Pattern(r"刚性底座", ElementKind.OBJECT, "object.rigid_base", "刚性底座"),
    Pattern(r"刚性", ElementKind.OBJECT, "object.rigid_base", "刚性（底座/样架）"),
    Pattern(r"转台", ElementKind.OBJECT, "object.turn_table", "转台"),
    Pattern(r"样架", ElementKind.OBJECT, "object.sample_frame", "样架"),
    Pattern(r"底座", ElementKind.OBJECT, "object.base", "底座"),
    # —— 动作 ——
    Pattern(r"一步到位", ElementKind.ACTION, "action.one_step", "一步到位抬升"),
    Pattern(r"分两段抬升", ElementKind.ACTION, "action.two_stage_lift", "分两段抬升"),
    Pattern(r"两段往上", ElementKind.ACTION, "action.two_stage", "两段抬升"),
    Pattern(r"两段动作", ElementKind.ACTION, "action.two_stage", "两段抬升"),
    Pattern(r"第(?:二|2)段", ElementKind.ACTION, "action.two_stage", "第二段动作"),
    Pattern(r"第(?:一|1)段", ElementKind.ACTION, "action.lift", "第一段动作"),
    Pattern(r"两段抬升", ElementKind.ACTION, "action.two_stage_lift", "分两段抬升"),
    Pattern(r"分两段", ElementKind.ACTION, "action.two_stage", "分两段"),
    Pattern(r"两段", ElementKind.ACTION, "action.two_stage", "两段"),
    Pattern(r"保持接触", ElementKind.ACTION, "action.hold_contact", "段间保持接触"),
    Pattern(r"抬升", ElementKind.ACTION, "action.lift", "抬升"),
    Pattern(r"示范", ElementKind.ACTION, "action.demo", "示范"),
    # —— 条件 ——
    Pattern(r"低压", ElementKind.CONDITION, "condition.low_pressure", "低压"),
    Pattern(r"空台", ElementKind.CONDITION, "condition.empty_table", "空台"),
    # —— 描述强度 ——
    Pattern(r"正是", ElementKind.STRENGTH, "strength.exactly", "正是（限定）"),
    Pattern(r"只", ElementKind.STRENGTH, "strength.only", "只（限定）"),
    Pattern(r"仅", ElementKind.STRENGTH, "strength.only", "仅（限定）"),
    Pattern(r"一般(?:说明)?", ElementKind.STRENGTH, "strength.general", "一般性（不限定具体实施）"),
]

FACTOR_DISPLAY: dict[str, str] = {p.factor: p.display for p in PATTERNS}

# 通用性自称：材料自称通用/示范，但只给一款实物示例时要标出支持范围。
GENERIC_FACTORS = {"action.demo", "strength.general"}

# 参与“共同公开”比对的实质因子（强度标记是修饰，不单独构成先例）。
SUBSTANTIVE_KINDS = {ElementKind.OBJECT, ElementKind.ACTION, ElementKind.CONDITION}

# 否定/缺记模式：组内因子在本句中属于“明确未记录”，不能算作公开。
ABSENCE_PATTERN = re.compile(r"未说明(?P<what>低压|两段|保持接触|弹性|刚性)?")

# 动作先后线索
SEQ_PATTERNS = [
    (re.compile(r"第(一|1)段"), 1),
    (re.compile(r"第(二|2)段"), 2),
    (re.compile(r"步骤(一|1)"), 1),
    (re.compile(r"步骤(二|2)"), 2),
]


@dataclass(frozen=True)
class RefPattern:
    regex: str
    kind: RefKind
    note: str


# 引用模式：识别“引用另一页的是同一实施方式还是备选”。
REF_PATTERNS: list[RefPattern] = [
    RefPattern(r"本页接着\s*(?P<target>H\d+)\s*的样架", RefKind.SAME_IMPL,
               "续页明言接续同一实施方式"),
    RefPattern(r"刚才那台样架", RefKind.ANAPHORA,
               "同场回指上一份载体上的样架"),
    RefPattern(r"动作按旁边口头提示", RefKind.DELEGATE,
               "本载体不含动作，动作由旁边口头提示承载"),
    RefPattern(r"步骤(?:二|2)只重复(?:录屏)?步骤(?:一|1)", RefKind.REPEAT_STEP,
               "后一步骤只重复前一步骤，不新增动作"),
    RefPattern(r"图注说明(?P<what>[^；;。]+)", RefKind.CAPTION_SOURCE,
               "信息来源是图注而非正文动作"),
]

# 备选实施方式的语言信号（资料中出现时标为备选，不得与主实施方式凑成同一先例）。
ALTERNATIVE_HINTS = ("备选", "替代", "另一实施", "或者采用")

CLAUSE_SPLIT = re.compile(r"[；;。]")
