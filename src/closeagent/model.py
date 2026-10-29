from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP

D = Decimal
CENT = D("0.01")


def money(x) -> Decimal:
    return D(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(x: Decimal) -> str:
    return f"{x:,.2f}"


@dataclass
class Finding:
    code: str            # stable machine code, e.g. UNBALANCED
    severity: str        # ERROR (blocks) | WARN (flag, human review) | INFO
    subject: str         # e.g. "JE-002", "TB:9999", "COA:1150"
    message: str         # deterministic, fact-only English
    evidence: dict = field(default_factory=dict)
    options: list = field(default_factory=list)   # candidate fixes; NEVER auto-applied

    def to_dict(self):
        return asdict(self)
