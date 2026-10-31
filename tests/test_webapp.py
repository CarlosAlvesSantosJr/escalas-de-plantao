import json

import pytest

from webapp import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "dados.json")
    app.testing = True
    return app.test_client()


def test_fluxo_completo(client):
    assert client.put("/api/periodo", json={"inicio": "2026-11-01", "fim": "2026-11-07"}).status_code == 200

    ids = []
    for nome, cargo in [("ana", "ENFERMEIRO"), ("bia", "ENFERMEIRO"),
                        ("caio", "MOTORISTA"), ("davi", "MOTORISTA")]:
        r = client.post("/api/funcionarios", json={"nome": nome, "cargo": cargo})
        assert r.status_code == 201
        ids.append(r.get_json()["id"])

    r = client.patch(f"/api/funcionarios/{ids[0]}/disponibilidade",
                     json=[{"data": "2026-11-01", "turno": "DIA", "status": "FERIAS"}])
    assert r.get_json()["disponibilidade"] == {"2026-11-01|DIA": "FERIAS"}

    escala = client.post("/api/escala").get_json()
    assert len(escala["plantoes"]) == 14
    assert escala["plantoes"][0]["enfermeiro"]["nome"] == "BIA"

    pdf = client.get("/api/escala.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")


def test_nome_duplicado_e_invalido(client):
    client.post("/api/funcionarios", json={"nome": "Ana", "cargo": "ENFERMEIRO"})
    assert client.post("/api/funcionarios", json={"nome": " ana ", "cargo": "MOTORISTA"}).status_code == 409
    r = client.post("/api/funcionarios", json={"nome": "Ana 2", "cargo": "MOTORISTA"})
    assert r.status_code == 400 and "letras" in r.get_json()["erro"]


def test_gerar_sem_periodo(client):
    r = client.post("/api/escala")
    assert r.status_code == 400


def test_le_formato_legado(tmp_path):
    legado = {"funcionarios": [{"nome": "ANA", "tipo": "ENFERMEIRO",
                                "disponibilidade": {"2026-10-01|DIA": "INDISPONIVEL",
                                                    "2026-10-01|NOITE": "DISPONIVEL"}}]}
    caminho = tmp_path / "dados.json"
    caminho.write_text(json.dumps(legado), encoding="utf-8")
    client = create_app(caminho).test_client()
    f = client.get("/api/estado").get_json()["funcionarios"][0]
    assert f["cargo"] == "ENFERMEIRO" and f["id"]
    assert f["disponibilidade"] == {"2026-10-01|DIA": "INDISPONIVEL"}
