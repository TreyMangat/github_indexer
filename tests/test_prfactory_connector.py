from repo_recall.connectors.prfactory import (
    CatalogSuggestResponse,
    RepoRecallMockAdapter,
    SearchResponse,
)


def test_prfactory_search_response_parses() -> None:
    payload = {
        "query": "q",
        "results": [
            {
                "repo": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "name": "my-repo",
                    "source": "git",
                    "source_ref": "https://example.com/my-repo.git",
                    "default_branch": "main",
                },
                "score": 0.9,
                "evidence": [
                    {
                        "chunk_id": "22222222-2222-2222-2222-222222222222",
                        "file_path": "README.md",
                        "start_line": 1,
                        "end_line": 10,
                        "content_type": "docs",
                        "score": 0.8,
                        "text": "hello",
                    }
                ],
            }
        ],
        "debug": {"vector_hits": 0, "lexical_hits": 1, "used_embeddings": False},
    }

    resp = SearchResponse.from_api(payload)
    assert resp.query == "q"
    assert len(resp.results) == 1
    assert resp.results[0].repo.name == "my-repo"
    assert resp.results[0].evidence[0].file_path == "README.md"


def test_prfactory_mock_adapter_echoes_query() -> None:
    canned = SearchResponse.from_api({"query": "x", "results": []})
    adapter = RepoRecallMockAdapter(response=canned)
    resp = adapter.search("new query")
    assert resp.query == "new query"


def test_catalog_suggest_response_parses() -> None:
    payload = {
        "actor_id": "U123",
        "query": "api",
        "results": [
            {
                "repo": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "full_name": "org/api",
                    "freshness": "fresh",
                },
                "score": 1.2,
                "reason_codes": ["name_match"],
                "branches": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "name": "main",
                        "is_default": True,
                        "protected": True,
                        "is_generated": False,
                        "score": 0.7,
                        "reason_codes": ["default_branch"],
                    }
                ],
            }
        ],
        "auth_required": False,
    }
    resp = CatalogSuggestResponse.from_api(payload)
    assert resp.actor_id == "U123"
    assert resp.results[0].repo.full_name == "org/api"
    assert resp.results[0].branches[0].name == "main"


def test_prfactory_mock_adapter_catalog_method() -> None:
    canned = SearchResponse.from_api({"query": "x", "results": []})
    adapter = RepoRecallMockAdapter(response=canned)
    resp = adapter.suggest_repos_and_branches(actor_id="U1", query="repo")
    assert resp.actor_id == "U1"
    assert resp.query == "repo"
