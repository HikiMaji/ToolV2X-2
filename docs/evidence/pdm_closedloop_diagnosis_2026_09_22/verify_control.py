"""Fixed secondary engineering diagnostics; does not replace original acceptance."""
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);result={}
for case in ['empty','lead']:
    rows=[json.loads(s) for s in (root/case/'frames.jsonl').read_text().splitlines()]
    rows=[r for r in rows if r['phase']=='driving'];tail=rows[-40:]
    max_accel=max(abs(r['tracked']['scene']['acceleration_mps2']) for r in rows)
    result[case]=dict(max_abs_acceleration=max_accel,acceleration_below_4=max_accel<4,
        tail40_max_speed=max(r['evaluation_only']['speed_mps'] for r in tail),
        tail40_all_below_half_mps=all(r['evaluation_only']['speed_mps']<.5 for r in tail))
print(json.dumps(result,indent=2))
assert all(r['acceleration_below_4'] for r in result.values()), 'excessive acceleration in fixed probe'
assert result['lead']['tail40_all_below_half_mps'], 'lead did not remain below 0.5 m/s for final 2 seconds'
