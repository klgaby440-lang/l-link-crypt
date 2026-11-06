import base64
import json

from llink_api.api.routes import media


def _jpeg_data_url() -> str:
    # L'endpoint valide le type par signature ; le modèle est remplacé dans ce test.
    raw = b"\xff\xd8\xff" + b"primeink-test-image"
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def test_primeink_fiche_extract_returns_validated_json_and_sanitizes_ids_and_scores(
    client, monkeypatch
):
    payload_from_model = {
        "document_type": "fiche_notes",
        "school_name": "École test",
        "class_name": "3e A",
        "course_name": "Mathématiques",
        "academic_year": "2026-2027",
        "students": [
            {
                "matched_student_id": "student-1",
                "student_name": "MUKENDI Jean",
                "p1": 14,
                "p2": 12,
                "ex1": 45,
                "p3": None,
                "p4": 11,
                "ex2": None,
                "confidence": 0.94,
                "warning": None,
            },
            {
                "matched_student_id": "not-in-roster",
                "student_name": "Nom incertain",
                "p1": 8,
                "p2": None,
                "ex1": None,
                "p3": None,
                "p4": None,
                "ex2": None,
                "confidence": 0.35,
                "warning": "Nom partiellement illisible",
            },
        ],
        "warnings": [],
        "confidence": 0.88,
    }

    class FakeModel:
        def generate_content(self, contents):
            assert isinstance(contents, list)
            assert isinstance(contents[1], dict)
            return type("FakeResponse", (), {"text": json.dumps(payload_from_model)})()

    async def no_quota(**kwargs):
        return None

    async def fake_reserve_slot():
        return lambda: None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(media, "reserve_ai_slot", fake_reserve_slot)
    monkeypatch.setattr(media, "get_gemini_model", lambda **kwargs: FakeModel())

    response = client.post(
        "/api/primeink/fiche-extract",
        json={
            "imageBase64": _jpeg_data_url(),
            "class_name": "3e A",
            "course_name": "Mathématiques",
            "max_period_points": 20,
            "max_exam_points": 40,
            "students": [
                {"student_id": "student-1", "full_name": "MUKENDI Jean"},
                {"student_id": "student-2", "full_name": "KABUYA Marie"},
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["document_type"] == "fiche_notes"
    assert data["students"][0]["matched_student_id"] == "student-1"
    assert data["students"][0]["p1"] == 14
    assert data["students"][0]["ex1"] is None  # 45 dépasse le plafond d'examen 40.
    assert data["students"][1]["matched_student_id"] is None
    assert any("identifiant inconnu" in warning for warning in data["warnings"])


def test_primeink_fiche_extract_requires_a_roster(client, monkeypatch):
    async def no_quota(**kwargs):
        return None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    response = client.post(
        "/api/primeink/fiche-extract",
        json={
            "imageBase64": _jpeg_data_url(),
            "class_name": "3e A",
            "course_name": "Mathématiques",
            "max_period_points": 20,
            "max_exam_points": 40,
            "students": [],
        },
    )
    assert response.status_code == 422
