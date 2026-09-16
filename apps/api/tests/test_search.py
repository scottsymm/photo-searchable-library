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


def test_who_search_escapes_like_wildcards(client):
    from api.deps import get_conn

    connection_generator = client.app.dependency_overrides[get_conn]()
    conn = next(connection_generator)
    try:
        for asset_id in (1, 2, 3):
            conn.execute("INSERT INTO assets(id, path, sha256, size_bytes, mime) VALUES (?, ?, ?, 1, 'image/jpeg')", (asset_id, f"/tmp/{asset_id}.jpg", str(asset_id) * 64))
            conn.execute("INSERT INTO faces(id, asset_id, bbox) VALUES (?, ?, '[]')", (asset_id, asset_id))
        conn.execute("INSERT INTO persons(id, name) VALUES (1, '100% real')")
        conn.execute("INSERT INTO persons(id, name) VALUES (2, '1000 real')")
        conn.execute("INSERT INTO persons(id, name) VALUES (3, '100_real')")
        for person_id in (1, 2, 3):
            conn.execute("INSERT INTO person_faces(person_id, face_id, source) VALUES (?, ?, 'manual')", (person_id, person_id))
        conn.commit()
    finally:
        connection_generator.close()

    percent_response = client.get("/search", params={"who": "%"})
    underscore_response = client.get("/search", params={"who": "_"})

    assert [result["id"] for result in percent_response.json()["results"]] == [1]
    assert [result["id"] for result in underscore_response.json()["results"]] == [3]
