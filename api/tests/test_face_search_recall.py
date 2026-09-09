from __future__ import annotations

from sqlalchemy import text

from app.services.face_search import search_faces
from tests.factories import biased_unit_vector, make_event, make_face, make_organization, make_photo, random_unit_vector

THRESHOLD = 0.38


def test_scoped_search_returns_full_recall_across_three_events(db_session):
    """NOT a real-world recall measurement -- this test artificially forces
    Postgres into the buggy plan shape with three session GUCs, on purpose,
    so the bug is reproducible in a fast, tiny, deterministic test rather
    than requiring a production-scale table. Treat it as an existence proof
    ("this plan shape drops matches without iterative_scan, and the fix
    recovers them"), not as a measured recall rate.

    Without the GUCs below, this test's table is small enough that
    Postgres's planner reaches its own conclusion -- filter photos by
    event_id first (cheap, selective), then sort the resulting handful of
    faces -- and recall is trivially 100% regardless of iterative_scan.
    That's a *different, equally valid* plan Postgres picks on its own for
    small/selective queries; it just doesn't exercise the bug. To force the
    specific plan where event_id is applied as a post-scan filter *after*
    an HNSW ORDER BY/LIMIT scan (pgvector's documented filtered-ANN case,
    see app/services/face_search.py):

      - `enable_bitmapscan = off` and `enable_sort = off` rule out the
        "filter first, then sort" plan, leaving the HNSW-ordered-scan plan
        as the planner's only option.
      - `hnsw.ef_search = 10` shrinks the index scan's candidate window so
        that ~120 near-duplicate decoys (constructed below) are enough to
        crowd out the 8 true matches -- without this, reproducing the
        under-return would need a much larger decoy set.

    Confirmed via EXPLAIN during development: with these three GUCs set and
    hnsw.iterative_scan forced 'off', this scenario returns 0/8 true
    matches. search_faces() sets hnsw.iterative_scan = 'relaxed_order',
    which recovers all 8 -- flip that back to 'off' locally to see the
    test fail.
    """
    db_session.execute(text("SET hnsw.ef_search = 10"))
    db_session.execute(text("SET enable_bitmapscan = off"))
    db_session.execute(text("SET enable_sort = off"))

    org = make_organization(db_session)
    query_vector = random_unit_vector(seed=1)

    target_event = make_event(db_session, org, name_en="Target Event")
    target_photo = make_photo(db_session, target_event)

    # True matches: same cosine neighborhood as the query (>= threshold),
    # but not near-duplicates -- these are the ones a pruned index scan
    # would drop first.
    expected_face_ids = set()
    for i in range(8):
        v = biased_unit_vector(query_vector, cosine_target=0.55, seed=100 + i)
        face = make_face(db_session, target_photo, v)
        db_session.flush()
        expected_face_ids.add(face.id)

    # Decoys in two other events: near-duplicates of the query (cosine
    # ~0.999) that dominate the nearest-neighbor ordering ahead of the
    # true target-event matches.
    for other_idx in range(2):
        other_event = make_event(db_session, org, name_en=f"Decoy Event {other_idx}")
        other_photo = make_photo(db_session, other_event)
        for i in range(60):
            v = biased_unit_vector(query_vector, cosine_target=0.999, seed=200 + other_idx * 100 + i)
            make_face(db_session, other_photo, v)
    db_session.flush()

    results = search_faces(
        db_session,
        event_id=target_event.id,
        query_embedding=query_vector,
        threshold=THRESHOLD,
        candidate_limit=20,
    )

    found_ids = {r.face_id for r in results}
    missing = expected_face_ids - found_ids
    assert not missing, (
        f"scoped search under-returned: missing {len(missing)}/{len(expected_face_ids)} "
        "true above-threshold matches in the target event -- HNSW filtered-ANN "
        "recall bug (see app/services/face_search.py)"
    )
    assert all(r.score >= THRESHOLD for r in results)
