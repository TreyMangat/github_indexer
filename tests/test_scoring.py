from repo_recall.retrieval.scoring import aggregate_by_repo, combine_hits


def test_combine_hits_and_aggregate():
    vector_hits = [
        {"id": "c1", "repo_id": "r1", "file_path": "a.py", "text": "foo", "score": 0.9},
        {"id": "c2", "repo_id": "r2", "file_path": "b.py", "text": "bar", "score": 0.1},
    ]
    lexical_hits = [
        {"id": "c1", "repo_id": "r1", "file_path": "a.py", "text": "foo", "score": 0.2},
        {"id": "c3", "repo_id": "r2", "file_path": "c.py", "text": "baz", "score": 10.0},
    ]
    hits = combine_hits(vector_hits, lexical_hits)
    assert hits[0].chunk_id in {"c1", "c3"}
    aggs = aggregate_by_repo(hits, top_k_repos=2, top_k_chunks=2)
    assert len(aggs) == 2
