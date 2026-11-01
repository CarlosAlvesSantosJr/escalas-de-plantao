import io
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

    rascunho = client.post("/api/rascunho").get_json()
    assert len(rascunho["plantoes"]) == 14
    assert rascunho["plantoes"][0]["enfermeiro"]["nome"] == "BIA"
    assert client.get("/api/escala.pdf").status_code == 404  # nada confirmado ainda

    final = client.post("/api/escala").get_json()
    assert final["confirmada_em"] and client.get("/api/rascunho").get_json() is None

    pdf = client.get("/api/escala.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")


def test_nome_duplicado_e_invalido(client):
    client.post("/api/funcionarios", json={"nome": "Ana", "cargo": "ENFERMEIRO"})
    assert client.post("/api/funcionarios", json={"nome": " ana ", "cargo": "MOTORISTA"}).status_code == 409
    r = client.post("/api/funcionarios", json={"nome": "Ana 2", "cargo": "MOTORISTA"})
    assert r.status_code == 400 and "letras" in r.get_json()["erro"]


def test_gerar_sem_periodo(client):
    assert client.post("/api/rascunho").status_code == 400
    assert client.post("/api/escala").status_code == 404


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


# --- revisão, escala final e importação --------------------------------

def _preparar(client):
    client.put("/api/periodo", json={"inicio": "2026-11-02", "fim": "2026-11-04"})
    ids = {}
    for nome, cargo in [("ana", "ENFERMEIRO"), ("bia", "ENFERMEIRO"), ("caio", "MOTORISTA"),
                        ("davi", "MOTORISTA"), ("eva", "MOTORISTA")]:
        ids[nome] = client.post("/api/funcionarios", json={"nome": nome, "cargo": cargo}).get_json()["id"]
    return ids


def _plantao(escala, data, turno):
    return next(p for p in escala["plantoes"] if p["data"] == data and p["turno"] == turno)


def test_edicao_manual_aponta_conflitos_e_permite_desfazer(client):
    ids = _preparar(client)
    client.patch(f"/api/funcionarios/{ids['ana']}/disponibilidade",
                 json=[{"data": "2026-11-02", "turno": "DIA", "status": "FERIAS"}])
    original = _plantao(client.post("/api/rascunho").get_json(), "2026-11-02", "DIA")

    posicao = {"data": "2026-11-02", "turno": "DIA", "cargo": "ENFERMEIRO"}
    cands = client.get("/api/rascunho/candidatos", query_string=posicao).get_json()
    assert cands[-1]["nome"] == "ANA" and "De férias" in cands[-1]["impedimentos"]

    r = client.patch("/api/rascunho", json=[{**posicao, "funcionario_id": ids["ana"]}]).get_json()
    editado = _plantao(r, "2026-11-02", "DIA")
    assert editado["enfermeiro"]["nome"] == "ANA" and editado["editados"] == ["ENFERMEIRO"]
    assert any(c["nome"] == "ANA" and c["motivo"] == "De férias" for c in r["conflitos"])

    r = client.patch("/api/rascunho", json=[{**posicao, "funcionario_id": None}]).get_json()
    assert any(v["data"] == "2026-11-02" and v["cargo"] == "ENFERMEIRO" for v in r["vagas"])

    r = client.patch("/api/rascunho", json=[{**posicao, "funcionario_id": original["enfermeiro"]["id"],
                                             "editado": False}]).get_json()
    assert r["conflitos"] == [] and r["vagas"] == []
    assert _plantao(r, "2026-11-02", "DIA")["editados"] == []


def test_edicao_rejeita_cargo_errado(client):
    ids = _preparar(client)
    client.post("/api/rascunho")
    r = client.patch("/api/rascunho", json=[{"data": "2026-11-02", "turno": "DIA",
                                             "cargo": "ENFERMEIRO", "funcionario_id": ids["caio"]}])
    assert r.status_code == 400 and "motorista" in r.get_json()["erro"]


def test_mudar_periodo_descarta_rascunho_mas_mantem_final(client):
    _preparar(client)
    client.post("/api/rascunho")
    client.post("/api/escala")
    client.post("/api/rascunho")
    client.put("/api/periodo", json={"inicio": "2026-12-01", "fim": "2026-12-03"})
    estado = client.get("/api/estado").get_json()
    assert estado["rascunho"] is None and estado["escala"]["periodo"]["inicio"] == "2026-11-02"


@pytest.mark.parametrize("formato", ["json", "pdf"])
def test_exporta_e_importa_em_outra_instalacao(client, tmp_path, formato):
    ids = _preparar(client)
    client.post("/api/rascunho")
    client.patch("/api/rascunho", json=[{"data": "2026-11-02", "turno": "NOITE", "cargo": "MOTORISTA",
                                         "funcionario_id": ids["eva"]}])
    final = client.post("/api/escala").get_json()
    arquivo = client.get(f"/api/escala.{formato}").data

    outra = create_app(tmp_path / "outra.json").test_client()
    outra.post("/api/funcionarios", json={"nome": "Ana", "cargo": "ENFERMEIRO"})
    r = outra.post("/api/escala/importar", data={"arquivo": (io.BytesIO(arquivo), f"escala.{formato}")},
                   content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    corpo = r.get_json()
    assert sorted(corpo["adicionados"]) == sorted({p["motorista"]["nome"] for p in final["plantoes"]}
                                                  | {"BIA"})
    assert corpo["estado"]["periodo"] == final["periodo"]
    nomes = lambda e: [(p["enfermeiro"]["nome"], p["motorista"]["nome"]) for p in e["plantoes"]]
    assert nomes(corpo["rascunho"]) == nomes(final)
    assert _plantao(corpo["rascunho"], "2026-11-02", "NOITE")["editados"] == ["MOTORISTA"]


def test_importar_arquivo_invalido(client):
    for conteudo in (b"%PDF-1.4 qualquer", b'{"x": 1}', b"nao e json"):
        r = client.post("/api/escala/importar", data={"arquivo": (io.BytesIO(conteudo), "x")},
                        content_type="multipart/form-data")
        assert r.status_code == 400 and r.get_json()["erro"]


def test_editar_escala_final_abre_copia_para_revisao(client):
    _preparar(client)
    client.post("/api/rascunho")
    client.post("/api/escala")
    r = client.post("/api/escala/editar").get_json()
    assert r["rascunho"]["confirmada_em"] is None
    assert client.get("/api/escala").get_json()["confirmada_em"]


def test_profissional_removido_vira_conflito(client):
    _preparar(client)
    alvo = client.post("/api/rascunho").get_json()["plantoes"][0]["enfermeiro"]["id"]
    client.delete(f"/api/funcionarios/{alvo}")
    r = client.get("/api/rascunho").get_json()
    assert r["plantoes"][0]["enfermeiro"]["id"] == alvo
    assert any(c["id"] == alvo and "equipe" in c["motivo"] for c in r["conflitos"])
