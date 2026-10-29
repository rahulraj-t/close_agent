"""Plain-English explanations for finance users.
Default: deterministic templates (no network, reproducible). Optional LLM wording is subject to a
numeric-consistency check and an exact-status-label check. These checks are limited safeguards, not proof
that the explanation is factually correct. The structured decision remains the deterministic rules output."""
import os
import re
from .model import fmt

HEAD = {
    "ACCEPTED": "Posted. No problems found.",
    "ACCEPTED_WITH_FLAGS": "Posted, but please review the flag(s) below.",
    "QUARANTINED": "NOT posted. It is held back until the problem below is fixed.",
}


def template(res):
    lines = [f"{res['id']} - {res['description']}: {HEAD[res['status']]}"]
    for f in res["findings"]:
        lines.append(f"  - {f.message}")
        for o in f.options:
            lines.append(f"      option: {o}")
    if res["status"] != "QUARANTINED":
        lines.append(f"  Effect: moves {fmt(__import__('decimal').Decimal(res['debits']))} between accounts (debits = credits).")
    return "\n".join(lines)


_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _nums(t):
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(t)}


def numeric_consistent(llm_text, facts_text):
    """Check only that output numeric tokens occur in supplied facts.

    This does not verify semantic correctness, causal claims, omissions, or all paraphrases.
    """
    return _nums(llm_text) <= _nums(facts_text)


def safe_rewrite(llm_text, facts_text, status):
    """Apply narrow mechanical checks; the deterministic decision remains authoritative."""
    return status in llm_text and numeric_consistent(llm_text, facts_text)


def explain(res, use_llm=False):
    base = template(res)
    if not use_llm or not os.environ.get("ANTHROPIC_API_KEY"):
        return base, "template"
    try:  # pragma: no cover - needs network
        import anthropic
        c = anthropic.Anthropic()
        m = c.messages.create(model=os.environ.get("CLOSE_AGENT_MODEL", "claude-sonnet-5-5"), max_tokens=400,
            messages=[{"role": "user", "content": (
                "Rewrite for a busy controller in 3-5 plain sentences. Preserve the exact status label "
                + res["status"]
                + " somewhere in your response. Use only numeric values present below. Do not add facts, causes, "
                + "or accounting conclusions that are not stated. This is wording only; do not change the underlying decision.\n\n"
                + base
            )}])
        out = m.content[0].text
        return (out, "llm(numeric/status checks passed)") if safe_rewrite(out, base, res["status"]) else (base, "template(llm numeric/status check failed)")
    except Exception as e:  # pragma: no cover
        return base, f"template(llm error: {type(e).__name__})"
