#!/usr/bin/env python3
"""Aggregate the JSON reports a dx-review run produced.

Usage: dx-aggregate.py <root> <expected agent count>
Exits non-zero unless every agent completed every step.
"""
import json, os, sys, collections
root, n = sys.argv[1], int(sys.argv[2])
rows, missing = [], []
for i in range(1, n + 1):
    p = os.path.join(root, f"agent-{i}", "report.json")
    try:
        with open(p) as f: rows.append(json.load(f))
    except Exception as e:
        missing.append((i, type(e).__name__))

print("\n" + "=" * 62)
print(f"DX REVIEW: {len(rows)}/{n} agents reported")
if missing:
    print("  no report from:", ", ".join(f"agent {i} ({w})" for i, w in missing))
if not rows:
    sys.exit(1)

TOTAL_STEPS = 14
def num(r, k):
    v = r.get(k)
    return v if isinstance(v, (int, float)) else 0

done = [len(r.get("completed_steps") or []) for r in rows]
full = sum(1 for d in done if d >= TOTAL_STEPS)
print(f"\ncompleted every step:  {full}/{len(rows)}")
print(f"steps completed:       min {min(done)}  median {sorted(done)[len(done)//2]}  max {max(done)}")

cmds = [num(r, "total_commands") for r in rows]
waste = [num(r, "wasted_commands") for r in rows]
if any(cmds):
    print(f"commands per agent:    min {min(cmds)}  median {sorted(cmds)[len(cmds)//2]}  max {max(cmds)}")
    print(f"wasted per agent:      min {min(waste)}  median {sorted(waste)[len(waste)//2]}  max {max(waste)}")
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

for key, title in [("misleading_messages", "MESSAGES THAT MISLED"),
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
sys.exit(0 if full == len(rows) else 1)
