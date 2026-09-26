"""Scratch: poke retrieval by hand. Not a test."""
from app.db import SessionLocal
from app.kb.search import search

QUERIES = [
    ("كم سعر الباقة القياسية؟",            "customer", "should answer"),
    ("هل تحفظون صورة السيلفي؟",             "customer", "should answer"),
    ("كم فعالية تقدرون تغطون باليوم؟",      "customer", "MUST be empty"),
    ("كم فعالية تقدرون تغطون باليوم؟",      "staff",    "should reach سعة التشغيل"),
    ("وش أفضل مطعم في جدة؟",                "customer", "MUST be empty"),
    ("كيف أغير إطارات السيارة؟",            "customer", "MUST be empty"),
]

with SessionLocal() as s:
    for q, kind, expect in QUERIES:
        hits = search(s, q, identity_kind=kind, min_score=0.0)  # forced, to see raw scores
        print(f"\n{q}  [{kind}] — {expect}")
        for h in hits:
            flag = "✓" if h.score >= 0.45 else " "
            print(f"  {flag} {h.score:.3f}  {h.section_title}")