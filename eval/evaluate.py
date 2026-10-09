"""Measure how well the scorer ranks jobs you labelled yourself.

Usage:  python eval/evaluate.py [labels.csv] [profile.json]

labels.csv columns: company,title,location,description,label   (label: 1 = you would apply, 0 = you would not)
The bundled sample_labels.csv is 16 SYNTHETIC jobs for demonstration. Label 50+ real jobs
from your own search before quoting any number.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from jobengine import config  # noqa: E402
from jobengine.scoring import score_jobs  # noqa: E402


def baseline_v3(job, profile):
    """The old v3 rule: substring skill hits + role + location + entry words + a flat 10."""
    text = f"{job['title']} {job['description']} {job['location']}".lower()
    wanted = [x.strip().lower() for x in profile["skills"].split(",") if x.strip()]
    roles = [x.strip().lower() for x in profile["roles"].split(",") if x.strip()]
    locs = [x.strip().lower() for x in profile["locations"].split(",") if x.strip()]
    hit = sum(1 for x in wanted if x in text)
    skill = min(45, hit / max(1, min(len(wanted), 10)) * 45) if wanted else 0
    role = 20 if (any(r in text for r in roles) if roles else True) else 0
    loc = 15 if (("remote" in text) or any(x in text for x in locs)) else 0
    exp = 10 if any(x in text for x in ["fresher", "intern", "entry level", "0-1 year", "junior"]) else 0
    return min(100, skill + role + loc + exp + 10)


def precision_at_k(scores, labels, k):
    top = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return sum(labels[i] for i in top) / k


def threshold_stats(scores, labels, thr):
    tp = sum(1 for s, l in zip(scores, labels) if s >= thr and l)
    fp = sum(1 for s, l in zip(scores, labels) if s >= thr and not l)
    fn = sum(1 for s, l in zip(scores, labels) if s < thr and l)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return prec, rec


def main():
    labels_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sample_labels.csv"
    profile_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "profile.json"
    profile = json.loads(profile_path.read_text())
    jobs = list(csv.DictReader(labels_path.open(encoding="utf-8")))
    labels = [int(j["label"]) for j in jobs]
    v4 = [r.score for r in score_jobs(profile, jobs, config.MATCH_BACKEND)]
    v3 = [baseline_v3(j, profile) for j in jobs]
    k = min(5, len(jobs))
    print(f"{len(jobs)} jobs ({sum(labels)} relevant) from {labels_path.name}\n")
    print(f"{'':22}{'v3 baseline':>14}{'v4':>10}")
    print(f"{'precision@' + str(k):22}{precision_at_k(v3, labels, k):>14.2f}{precision_at_k(v4, labels, k):>10.2f}")
    print(f"\nThreshold sweep for v4 (pick the one that fits your own labels; current MIN_MATCH_SCORE={config.MIN_SCORE:g})")
    print(f"{'threshold':>9}{'precision':>11}{'recall':>9}{'F1':>7}")
    best = (0.0, None)
    for thr in range(30, 85, 5):
        p, r = threshold_stats(v4, labels, thr)
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        best = max(best, (f1, thr), key=lambda x: x[0])
        print(f"{thr:>9}{p:>11.2f}{r:>9.2f}{f1:>7.2f}")
    print(f"\nBest F1 on this file: {best[0]:.2f} at threshold {best[1]}")


if __name__ == "__main__":
    main()
