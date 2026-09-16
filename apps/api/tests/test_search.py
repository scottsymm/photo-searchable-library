def test_who_search_matches_person_alias_case_insensitively(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (1, '/tmp/a.jpg', ?, 1, 'image/jpeg')", ("a" * 64,))
        conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (1, 1, '[]')")
        conn.execute("INSERT INTO persons(id, name) VALUES (1, 'Robert')")
        conn.execute("INSERT INTO person_aliases(person_id, alias) VALUES (1, 'Dad')")
        conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (1, 1, 'manual')")
        conn.commit()
    finally:
        connection_generator.close()

    alias_response = client.get("/search", params={"who": "dA"})
    name_response = client.get("/search", params={"who": "rob"})
    missing_response = client.get("/search", params={"who": "sibling"})

    assert [result["id"] for result in alias_response.json()["results"]] == [1]
    assert [result["id"] for result in name_response.json()["results"]] == [1]
    assert missing_response.json()["results"] == []
