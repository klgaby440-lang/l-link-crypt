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



def test_primeink_fiche_extract_falls_back_to_gemini_38_after_primary_503(
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
                "p2": None,
                "ex1": None,
                "p3": None,
                "p4": None,
                "ex2": None,
                "confidence": 0.94,
                "warning": None,
            }
        ],
        "warnings": [],
        "confidence": 0.88,
    }

    class ProviderUnavailable(Exception):
        code = 503

    class FakeModel:
        def __init__(self, overloaded=False):
            self.overloaded = overloaded

        def generate_content(self, contents):
            if self.overloaded:
                raise ProviderUnavailable("503 UNAVAILABLE")
            return type("FakeResponse", (), {"text": json.dumps(payload_from_model)})()

    requested_models = []

    def fake_get_model(**kwargs):
        model_name = kwargs.get("model_name", "primary")
        requested_models.append(model_name)
        return FakeModel(overloaded=model_name == "primary")

    async def no_quota(**kwargs):
        return None

    async def fake_reserve_slot():
        return lambda: None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(media, "reserve_ai_slot", fake_reserve_slot)
    monkeypatch.setattr(media, "get_gemini_model", fake_get_model)

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
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["students"][0]["p1"] == 14
    assert requested_models == ["primary", "gemini-3.8-flash"]



def test_primeink_students_extract_returns_names_postnames_firstnames_and_sex(
    client, monkeypatch
):
    payload_from_model = {
        "document_type": "student_list",
        "class_name": "1ère Scientifique",
        "academic_year": "2026-2027",
        "students": [
            {
                "name": "MUKENDI",
                "postname": "KABUYA",
                "prename": "Aline",
                "sexe": "F",
                "confidence": 0.96,
                "warning": None,
            },
            {
                "name": "ILUNGA",
                "postname": None,
                "prename": None,
                "sexe": None,
                "confidence": 0.61,
                "warning": "Sexe non indiqué sur la photo",
            },
        ],
        "warnings": [],
        "confidence": 0.9,
    }

    class FakeModel:
        def generate_content(self, contents):
            assert isinstance(contents, list) and isinstance(contents[1], dict)
            return type("FakeResponse", (), {"text": json.dumps(payload_from_model)})()

    async def no_quota(**kwargs):
        assert kwargs["scope"] == "student_list_extract"

    async def fake_reserve_slot():
        return lambda: None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(media, "reserve_ai_slot", fake_reserve_slot)
    monkeypatch.setattr(media, "get_gemini_model", lambda **kwargs: FakeModel())

    response = client.post(
        "/api/primeink/students-extract",
        json={"imageBase64": _jpeg_data_url(), "class_name": "1ère Scientifique"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["document_type"] == "student_list"
    assert data["students"][0]["name"] == "MUKENDI"
    assert data["students"][0]["postname"] == "KABUYA"
    assert data["students"][0]["prename"] == "Aline"
    assert data["students"][0]["sexe"] == "F"
    assert data["students"][1]["sexe"] is None


def test_primeink_courses_extract_maps_bulletin_domains_and_subdomains(
    client, monkeypatch
):
    payload_from_model = {
        "document_type": "bulletin_courses",
        "school_name": "École test",
        "class_name": "4e Scientifique",
        "academic_year": "2026-2027",
        "courses": [
            {
                "name": "Algèbre",
                "domain": "Domaine des sciences",
                "subdomain": "Sous-domaine des mathématiques",
                "confidence": 0.94,
                "warning": None,
            },
            {
                "name": "Français",
                "domain": "Domaine des langues",
                "subdomain": None,
                "confidence": 0.97,
                "warning": None,
            },
        ],
        "warnings": [],
        "confidence": 0.93,
    }

    class FakeModel:
        def generate_content(self, contents):
            return type("FakeResponse", (), {"text": json.dumps(payload_from_model)})()

    async def no_quota(**kwargs):
        assert kwargs["scope"] == "course_list_extract"

    async def fake_reserve_slot():
        return lambda: None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(media, "reserve_ai_slot", fake_reserve_slot)
    monkeypatch.setattr(media, "get_gemini_model", lambda **kwargs: FakeModel())

    response = client.post(
        "/api/primeink/courses-extract",
        json={"imageBase64": _jpeg_data_url(), "class_name": "4e Scientifique"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["document_type"] == "bulletin_courses"
    assert data["courses"][0]["name"] == "Algèbre"
    assert data["courses"][0]["domain"] == "Domaine des sciences"
    assert data["courses"][0]["subdomain"] == "Sous-domaine des mathématiques"
    assert data["courses"][1]["subdomain"] is None


def test_primeink_students_extract_falls_back_to_gemini_38_when_primary_is_unavailable(
    client, monkeypatch
):
    payload_from_model = {
        "document_type": "student_list",
        "class_name": "1ère",
        "academic_year": "2026-2027",
        "students": [
            {
                "name": "MUKENDI",
                "postname": "KABUYA",
                "prename": "Aline",
                "sexe": "F",
                "confidence": 0.9,
                "warning": None,
            }
        ],
        "warnings": [],
        "confidence": 0.9,
    }

    class ProviderUnavailable(Exception):
        code = 503

    class FakeModel:
        def __init__(self, unavailable=False):
            self.unavailable = unavailable

        def generate_content(self, contents):
            if self.unavailable:
                raise ProviderUnavailable("503 UNAVAILABLE")
            return type("FakeResponse", (), {"text": json.dumps(payload_from_model)})()

    requested = []

    def fake_get_model(**kwargs):
        requested.append(kwargs)
        return FakeModel(unavailable=kwargs.get("model_name") is None)

    async def no_quota(**kwargs):
        return None

    async def fake_reserve_slot():
        return lambda: None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(media, "reserve_ai_slot", fake_reserve_slot)
    monkeypatch.setattr(media, "get_gemini_model", fake_get_model)

    response = client.post(
        "/api/primeink/students-extract",
        json={"imageBase64": _jpeg_data_url(), "class_name": "1ère"},
    )

    assert response.status_code == 200
    assert response.json()["students"][0]["name"] == "MUKENDI"
    assert requested[1]["model_name"] == "gemini-3.8-flash"
    assert requested[1]["effort"] == "extra"


def test_primeink_photo_extract_routes_reject_empty_images(client, monkeypatch):
    async def no_quota(**kwargs):
        return None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    for endpoint in ("/api/primeink/students-extract", "/api/primeink/courses-extract"):
        response = client.post(
            endpoint,
            json={"imageBase64": "dGVzdCBub3QgaW1hZ2U="},
        )
        assert response.status_code == 415



def test_primeink_photo_extraction_falls_back_after_schema_and_provider_errors(
    client, monkeypatch
):
    payload_from_model = {
        "document_type": "bulletin_courses",
        "school_name": "École test",
        "class_name": "4e",
        "academic_year": "2026-2027",
        "courses": [
            {
                "name": "Physique",
                "domain": "Sciences",
                "subdomain": "Physique",
                "confidence": 0.93,
                "warning": None,
            }
        ],
        "warnings": [],
        "confidence": 0.9,
    }

    class ProviderError(Exception):
        def __init__(self, code):
            super().__init__(str(code))
            self.code = code

    requested = []

    class FakeModel:
        def __init__(self, mode):
            self.mode = mode

        def generate_content(self, contents):
            if self.mode == "schema":
                raise ProviderError(400)
            if self.mode == "plain-primary":
                raise ProviderError(503)
            return type("FakeResponse", (), {"text": json.dumps(payload_from_model)})()

    def fake_get_model(**kwargs):
        requested.append(kwargs)
        if kwargs.get("model_name") == "gemini-3.8-flash":
            return FakeModel("fallback")
        return FakeModel("schema" if "response_json_schema" in kwargs else "plain-primary")

    async def no_quota(**kwargs):
        return None

    async def fake_reserve_slot():
        return lambda: None

    monkeypatch.setattr(media, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(media, "reserve_ai_slot", fake_reserve_slot)
    monkeypatch.setattr(media, "get_gemini_model", fake_get_model)

    response = client.post(
        "/api/primeink/courses-extract",
        json={"imageBase64": _jpeg_data_url(), "class_name": "4e"},
    )

    assert response.status_code == 200
    assert response.json()["courses"][0]["name"] == "Physique"
    assert len(requested) == 3
    assert requested[0].get("response_json_schema") is not None
    assert "response_json_schema" not in requested[1]
    assert requested[2]["model_name"] == "gemini-3.8-flash"
    assert "response_json_schema" not in requested[2]
    assert requested[2]["effort"] == "extra"
