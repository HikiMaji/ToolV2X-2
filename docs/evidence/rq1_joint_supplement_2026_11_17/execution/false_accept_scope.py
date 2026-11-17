"""Reproduce the saved descriptive false-accept breakdown, without new decisions."""
import argparse
import gzip
import json
import math
from pathlib import Path
from scripts.rq1_temporal.run import primary, weights

def summarize(run):
    result={"scope":"descriptive_origin_of_additional_false_accepts_no_new_decisions","regimes":{}}
    for regime in ("mixed","F1_only","F2_only"):
        with gzip.open(run/"predictions/additional"/regime/"eval.jsonl.gz","rt") as stream:
            rows=[json.loads(line) for line in stream]
        false=[r for r in rows if primary(r,0)]
        accepted=[(r,float(w)) for r,w in zip(false,weights(false,0)) if r["decisions"]["Cond"]=="accept"]
        stats=dict(n_false_primary=len(false),n_Cond_false_accept=len(accepted),global_false_mass=math.fsum(w for _,w in accepted),
            count_already_accepted=sum(r["decisions"]["Count"]=="accept" for r,w in accepted),
            without_reject_eligibility=sum(not r["reject_eligible"] for r,w in accepted),
            zero_independent_R=sum(r["scores"]["Cond"]==0 for r,w in accepted),
            without_effective_misses=sum(sum(r["n_minus"])==0 for r,w in accepted),entities={},baseline_rates={})
        report=json.loads((run/"report/additional"/(regime+".json")).read_text())
        for method,value in report["metrics"]["eval"]["system_query"].items():
            stats["baseline_rates"][method]=dict(FA=value["false"]["weighted"]["accept"],TR=value["true"]["weighted"]["reject"],CD=value["correct_definite"])
        for row,weight in accepted:
            entity=stats["entities"].setdefault(row["job_id"],dict(parent=row["parent"],family=row["family"],attack_k=row["attack_k"],n=0,global_mass=0.,examples=[]))
            entity["n"]+=1;entity["global_mass"]+=weight
            if len(entity["examples"])<2:
                entity["examples"].append({k:row[k] for k in ("key","epoch","index","timestamp","Count_inputs","n_minus","reject_eligible","source_ids","scores","decisions")})
        result["regimes"][regime]=stats
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError("preserve the original description")
    args.out.write_text(json.dumps(summarize(args.run),ensure_ascii=False,indent=2)+"\n")
