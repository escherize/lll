#!/usr/bin/env python3
"""Aggregate the JSON reports a dx-review run produced.

Usage: dx-aggregate.py <root> <expected agent count>
Exits non-zero unless every agent completed every step.
"""
import json, os, sys, collections, statistics
root, n = sys.argv[1], int(sys.argv[2])
TOTAL_STEPS = 14
EXPECTED_STEPS = set(range(1, TOTAL_STEPS + 1))

def validate_report(row, agent):
    if not isinstance(row, dict) or row.get("agent") != agent:
        raise ValueError("report must identify its expected agent")
    completed = row.get("completed_steps")
    failed = row.get("failed_steps")
    if not isinstance(completed, list) or not isinstance(failed, list):
        raise ValueError("completed_steps and failed_steps must be lists")
    failed_ids = [f.get("step") if isinstance(f, dict) else None for f in failed]
    steps = completed + failed_ids
    if any(type(step) is not int for step in steps):
        raise ValueError("step IDs must be integers")
    if len(steps) != TOTAL_STEPS or set(steps) != EXPECTED_STEPS:
        raise ValueError("each of steps 1–14 must appear exactly once, completed or failed")
    for key in ("total_commands", "wasted_commands"):
        if type(row.get(key)) is not int or row[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if row["wasted_commands"] > row["total_commands"]:
        raise ValueError("wasted_commands exceeds total_commands")
    if "clean_bill_of_health" in row:
        if type(row["clean_bill_of_health"]) is not bool:
            raise ValueError("clean_bill_of_health must be a boolean")
        friction = row.get("avoidable_friction")
        if not isinstance(friction, list) or any(not isinstance(v, str) for v in friction):
            raise ValueError("avoidable_friction must be a list of strings")
        if row["clean_bill_of_health"] and (friction or failed):
            raise ValueError("a clean verdict cannot contain avoidable friction or failed steps")
    if type(row.get("consulted_help")) is not bool:
        raise ValueError("consulted_help must be a boolean")
    for key in ("first_command", "worst_moment"):
        if not isinstance(row.get(key), str):
            raise ValueError(f"{key} must be a string")
    for key in ("misleading_messages", "helpful_messages", "surprises"):
        if not isinstance(row.get(key), list) or any(not isinstance(v, str) for v in row[key]):
            raise ValueError(f"{key} must be a list of strings")

rows, missing = [], []
for i in range(1, n + 1):
    p = os.path.join(root, f"agent-{i}", "report.json")
    try:
        with open(p) as f:
            row = json.load(f)
        validate_report(row, i)
        rows.append(row)
    except Exception as e:
        missing.append((i, f"{type(e).__name__}: {e}"))

print("\n" + "=" * 62)
print(f"DX REVIEW: {len(rows)}/{n} agents reported")
if missing:
    print("  no report from:", ", ".join(f"agent {i} ({w})" for i, w in missing))
if not rows:
    sys.exit(1)

def num(r, k):
    v = r.get(k)
    return v if isinstance(v, (int, float)) else 0

done = [len(r.get("completed_steps") or []) for r in rows]
full = sum(1 for r in rows if set(r["completed_steps"]) == EXPECTED_STEPS and not r["failed_steps"])
print(f"\ncompleted every step:  {full}/{len(rows)}")
clean = sum(r.get("clean_bill_of_health") is True for r in rows)
print(f"clean usability verdict: {clean}/{len(rows)} (legacy reports have no verdict)")
print(f"steps completed:       min {min(done)}  median {statistics.median(done)}  max {max(done)}")

cmds = [num(r, "total_commands") for r in rows]
waste = [num(r, "wasted_commands") for r in rows]
if any(cmds):
    print(f"commands per agent:    min {min(cmds)}  median {statistics.median(cmds)}  max {max(cmds)}")
    print(f"wasted per agent:      min {min(waste)}  median {statistics.median(waste)}  max {max(waste)}")
    print(f"agents needing --help: {sum(1 for r in rows if r.get('consulted_help'))}/{len(rows)}")

fails = collections.Counter()
for r in rows:
    for f in (r.get("failed_steps") or []):
        if isinstance(f, dict) and f.get("step") is not None:
            fails[f["step"]] += 1
if fails:
    print("\nSTEPS THAT FAILED, most agents first")
    for step, c in fails.most_common():
        why = ""
        for r in rows:
            for f in (r.get("failed_steps") or []):
                if isinstance(f, dict) and f.get("step") == step and f.get("why"):
                    why = str(f["why"])[:90]; break
            if why: break
        print(f"  {c:3}/{len(rows)}  step {step}: {why}")

firsts = collections.Counter((r.get("first_command") or "?").strip() for r in rows)
print("\nFIRST COMMAND, which is what the design has to answer")
for c, k in firsts.most_common(6):
    print(f"  {k:3}  {c[:70]}")

for key, title in [("avoidable_friction", "ACTIONABLE FRICTION"),
                   ("misleading_messages", "MESSAGES THAT MISLED"),
                   ("surprises",           "SURPRISES"),
                   ("helpful_messages",    "MESSAGES THAT HELPED")]:
    seen = collections.Counter()
    for r in rows:
        for m in (r.get(key) or []):
            seen[str(m).strip()[:100]] += 1
    if seen:
        print(f"\n{title}, by how many agents hit it")
        for m, c in seen.most_common(8):
            print(f"  {c:3}  {m}")

worst = [str(r.get("worst_moment") or "").strip() for r in rows]
worst = [w for w in worst if w]
if worst:
    print("\nWORST MOMENT, one per agent")
    for w in worst[:12]:
        print(f"  - {w[:96]}")
print("=" * 62)
sys.exit(0 if not missing and full == n and clean == n else 1)
