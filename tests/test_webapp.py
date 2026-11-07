import io
import json
from datetime import date

import pytest

from escala.usuarios import Papel, novo_usuario
from webapp import create_app


def _usuarios(pasta):
    """Cadastro de teste: um ADMIN e dois usuários comuns, na pasta dos dados."""
    caminho = pasta / "usuarios.json"
    if not caminho.exists():
        lista = [novo_usuario("Márcia", "11111", Papel.ADMIN), novo_usuario("Bruna", "22222"),
                 novo_usuario("Caio", "033333")]
        caminho.write_text(json.dumps({"usuarios": [u.para_dict() for u in lista]}), encoding="utf-8")


HOJE = date(2026, 11, 3)  # "hoje" fixo: a escala de 02 a 04/11 é a atual


def _cliente(caminho_dados, nome="Marcia", matricula="11111", hoje=HOJE):
    _usuarios(caminho_dados.parent)
    app = create_app(caminho_dados)
    app.testing = True
    app.config["HOJE"] = lambda: hoje
    c = app.test_client()
    c.environ_base["HTTP_X_REQUESTED_WITH"] = "fetch"
    if nome:
        r = c.post("/api/login", json={"nome": nome, "matricula": matricula})
        assert r.status_code == 200, r.get_json()
    return c


@pytest.fixture
def client(tmp_path):
    return _cliente(tmp_path / "dados.json")


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
    client = _cliente(caminho)
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
    assert r.status_code == 400 and "Socorrista" in r.get_json()["erro"]


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

    outra = _cliente(tmp_path / "outra.json")
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


# --- login, perfis e auditoria ------------------------------------------

def _escala_confirmada(client):
    ids = _preparar(client)
    client.post("/api/rascunho")
    return ids, client.post("/api/escala").get_json()


def test_sem_login_nao_acessa(tmp_path):
    c = _cliente(tmp_path / "dados.json", nome=None)
    assert c.get("/api/estado").status_code == 401
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert c.get("/login").status_code == 200
    assert c.get("/saude").status_code == 200


def test_login_aceita_nome_sem_acento_e_recusa_matricula_errada(tmp_path):
    c = _cliente(tmp_path / "dados.json", nome=None)
    assert c.post("/api/login", json={"nome": "  marcia ", "matricula": "11111"}).get_json()["admin"] is True
    c2 = _cliente(tmp_path / "dados.json", nome=None)
    r = c2.post("/api/login", json={"nome": "Caio", "matricula": "33333"})  # sem o zero à esquerda
    assert r.status_code == 401
    assert c2.post("/api/login", json={"nome": "Caio", "matricula": "033333"}).get_json()["admin"] is False


def test_login_bloqueia_apos_muitas_tentativas(tmp_path):
    c = _cliente(tmp_path / "dados.json", nome=None)
    for _ in range(5):
        assert c.post("/api/login", json={"nome": "Bruna", "matricula": "1"}).status_code == 401
    r = c.post("/api/login", json={"nome": "Bruna", "matricula": "22222"})
    assert r.status_code == 429


def test_exige_cabecalho_contra_csrf(tmp_path):
    c = _cliente(tmp_path / "dados.json")
    del c.environ_base["HTTP_X_REQUESTED_WITH"]
    assert c.post("/api/funcionarios", json={"nome": "Ana", "cargo": "ENFERMEIRO"}).status_code == 403


def test_usuario_so_altera_plantao_da_escala_confirmada(client, tmp_path):
    ids, final = _escala_confirmada(client)
    bia = _cliente(tmp_path / "dados.json", "bruna", "22222")

    for metodo, url in [("post", "/api/funcionarios"), ("post", "/api/rascunho"), ("put", "/api/periodo"),
                        ("post", "/api/escala"), ("get", "/api/escala.pdf"), ("get", "/api/escala.json"),
                        ("post", "/api/escala/importar"), ("get", "/api/auditoria"),
                        ("post", "/api/escala/editar")]:
        assert getattr(bia, metodo)(url).status_code == 403, url

    estado = bia.get("/api/estado").get_json()
    assert estado["rascunho"] is None and estado["escala"]
    assert all(f["disponibilidade"] == {} for f in estado["funcionarios"])

    p = _plantao(final, "2026-11-03", "DIA")
    outro = next(i for n, i in ids.items() if n in ("ana", "bia") and i != p["enfermeiro"]["id"])
    posicao = {"data": "2026-11-03", "turno": "DIA", "cargo": "ENFERMEIRO"}
    assert bia.get("/api/escala/candidatos", query_string=posicao).status_code == 200
    r = bia.patch("/api/escala", json=[{**posicao, "funcionario_id": outro, "esperado": p["enfermeiro"]["id"]}])
    assert r.status_code == 200
    assert _plantao(r.get_json(), "2026-11-03", "DIA")["enfermeiro"]["id"] == outro

    # O ADM vê na hora e a versão muda para as outras telas recarregarem.
    assert _plantao(client.get("/api/escala").get_json(), "2026-11-03", "DIA")["enfermeiro"]["id"] == outro
    ultima = client.get("/api/versao").get_json()["ultima"]
    assert ultima["usuario"] == "Bruna" and ultima["tipo"] == "PLANTAO_ALTERADO"

    eventos = client.get("/api/auditoria", query_string={"usuario": "BRUNA"}).get_json()["eventos"]
    alteracao = next(e for e in eventos if e["tipo"] == "PLANTAO_ALTERADO")
    assert alteracao["detalhes"]["antes"] == p["enfermeiro"]["nome"]
    assert "→" in alteracao["descricao"] and "Enfermagem:" in alteracao["descricao"]
    assert any(e["tipo"] == "LOGIN" for e in eventos)


def test_usuario_nao_ve_conflitos_distribuicao_nem_ip(client, tmp_path):
    ids, final = _escala_confirmada(client)
    # Um ajuste do ADM que quebra regra: ANA de férias e escalada.
    client.patch(f"/api/funcionarios/{ids['ana']}/disponibilidade",
                 json=[{"data": "2026-11-02", "turno": "DIA", "status": "FERIAS"}])
    posicao = {"data": "2026-11-02", "turno": "DIA", "cargo": "ENFERMEIRO"}
    p = _plantao(final, "2026-11-02", "DIA")
    client.patch("/api/escala", json=[{**posicao, "funcionario_id": ids["ana"], "esperado": p["enfermeiro"]["id"]}])

    adm = client.get("/api/escala").get_json()
    assert adm["conflitos"] and all("total" in s for s in adm["estatisticas"])

    bia = _cliente(tmp_path / "dados.json", "Bruna", "22222")
    for escala in (bia.get("/api/escala").get_json(), bia.get("/api/estado").get_json()["escala"]):
        assert escala["conflitos"] == []
        assert all(set(s) == {"id", "nome", "cargo", "cor"} for s in escala["estatisticas"])
    cands = bia.get("/api/escala/candidatos", query_string=posicao).get_json()
    assert cands and all(c["total"] is None for c in cands)
    versao = bia.get("/api/versao").get_json()
    assert "ip" not in versao["ultima"]
    assert versao["usuario"] == "Bruna"  # a tela compara com quem ela acha que está logado


def test_alteracao_simultanea_nao_sobrescreve(client, tmp_path):
    ids, final = _escala_confirmada(client)
    p = _plantao(final, "2026-11-02", "NOITE")
    posicao = {"data": "2026-11-02", "turno": "NOITE", "cargo": "MOTORISTA"}
    bia = _cliente(tmp_path / "dados.json", "Bruna", "22222")
    caio = _cliente(tmp_path / "dados.json", "Caio", "033333")
    viu = p["motorista"]["id"]
    assert bia.patch("/api/escala", json=[{**posicao, "funcionario_id": None, "esperado": viu}]).status_code == 200
    r = caio.patch("/api/escala", json=[{**posicao, "funcionario_id": ids["eva"], "esperado": viu}])
    assert r.status_code == 409 and "outra pessoa" in r.get_json()["erro"]


def test_auditoria_em_csv(client):
    _escala_confirmada(client)
    r = client.get("/api/auditoria.csv")
    assert r.status_code == 200 and "ESCALA_CONFIRMADA" in r.data.decode("utf-8-sig")


def test_logout_encerra_sessao(client):
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/estado").status_code == 401


# --- várias escalas: atual e do mês seguinte ------------------------------

def _confirmar(client, inicio, fim):
    client.put("/api/periodo", json={"inicio": inicio, "fim": fim})
    client.post("/api/rascunho")
    return client.post("/api/escala").get_json()


def test_escala_do_mes_seguinte_convive_com_a_atual(client, tmp_path):
    _preparar(client)
    _confirmar(client, "2026-11-02", "2026-11-04")
    _confirmar(client, "2026-12-01", "2026-12-03")
    _confirmar(client, "2026-10-01", "2026-10-03")  # anterior: só o ADM vê

    estado = client.get("/api/estado").get_json()
    assert [(e["periodo"]["inicio"], e["papel"]) for e in estado["escalas"]] == [
        ("2026-10-01", "anterior"), ("2026-11-02", "atual"), ("2026-12-01", "seguinte")]
    assert estado["escala"]["periodo"]["inicio"] == "2026-11-02"  # abre na atual

    bruna = _cliente(tmp_path / "dados.json", "Bruna", "22222")
    papeis = [e["papel"] for e in bruna.get("/api/estado").get_json()["escalas"]]
    assert papeis == ["atual", "seguinte"]
    assert bruna.get("/api/escala", query_string={"inicio": "2026-10-01"}).status_code == 404

    # A troca vai para a escala do mês seguinte, sem mexer na atual.
    dez = bruna.get("/api/escala", query_string={"inicio": "2026-12-01"}).get_json()
    p = _plantao(dez, "2026-12-02", "DIA")
    outro = next(s["id"] for s in dez["estatisticas"] if s["cargo"] == "MOTORISTA" and s["id"] != p["motorista"]["id"])
    r = bruna.patch("/api/escala?inicio=2026-12-01", json=[{"data": "2026-12-02", "turno": "DIA", "cargo": "MOTORISTA",
                                                           "funcionario_id": outro, "esperado": p["motorista"]["id"]}])
    assert r.status_code == 200 and _plantao(r.get_json(), "2026-12-02", "DIA")["motorista"]["id"] == outro
    assert bruna.patch("/api/escala?inicio=2026-12-01", json=[{"data": "2026-11-02", "turno": "DIA",
                                                               "cargo": "MOTORISTA", "funcionario_id": None}]
                       ).status_code == 400  # data fora da escala escolhida
    ultima = client.get("/api/versao").get_json()["ultima"]
    assert ultima["detalhes"]["escala"] == "2026-12-01"


def test_confirmar_o_mesmo_periodo_substitui(client):
    _preparar(client)
    _confirmar(client, "2026-11-02", "2026-11-04")
    _confirmar(client, "2026-11-02", "2026-11-04")
    assert len(client.get("/api/estado").get_json()["escalas"]) == 1


def test_so_escalas_futuras_viram_mes_atual_e_seguinte(tmp_path):
    c = _cliente(tmp_path / "dados.json", hoje=date(2026, 11, 20))
    _preparar(c)
    _confirmar(c, "2026-12-01", "2026-12-03")
    estado = c.get("/api/estado").get_json()
    assert estado["escala"]["periodo"]["inicio"] == "2026-12-01"
    assert estado["escalas"][0]["papel"] == "atual"
    _confirmar(c, "2027-01-01", "2027-01-03")
    papeis = [(e["periodo"]["inicio"], e["papel"]) for e in c.get("/api/estado").get_json()["escalas"]]
    assert papeis == [("2026-12-01", "atual"), ("2027-01-01", "seguinte")]


def test_par_so_avanca_quando_o_mes_vira_e_o_adm_confirma_a_nova():
    from escala.repositorio import EstadoApp
    from escala.dominio import Escala, Periodo

    def esc(ano, mes):
        return Escala(Periodo(date(ano, mes, 1), date(ano, mes, 28)), [])

    def papeis(escalas, hoje):
        e = EstadoApp(escalas=escalas)
        return [(x.periodo.inicio.month, p) for x, p in zip(escalas, e.classificar(hoje).values())]

    dez, jan, fev = esc(2026, 12), esc(2027, 1), esc(2027, 2)
    # Novembro: dezembro e janeiro publicados.
    assert papeis([dez, jan], date(2026, 11, 7)) == [(12, "atual"), (1, "seguinte")]
    # Dezembro, com fevereiro já confirmado: o mês ainda não virou para janeiro.
    assert papeis([dez, jan, fev], date(2026, 12, 20)) == [(12, "atual"), (1, "seguinte"), (2, "futura")]
    # Virou para janeiro, mas fevereiro ainda não foi confirmado: o par não avança.
    assert papeis([dez, jan], date(2027, 1, 5)) == [(12, "atual"), (1, "seguinte")]
    # Virou o mês E o ADM confirmou fevereiro: janeiro vira o atual, fevereiro o seguinte.
    assert papeis([dez, jan, fev], date(2027, 1, 5)) == [(12, "anterior"), (1, "atual"), (2, "seguinte")]


def test_le_arquivo_com_uma_unica_escala(client, tmp_path):
    _preparar(client)
    final = _confirmar(client, "2026-11-02", "2026-11-04")
    caminho = tmp_path / "dados.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    dados["escala"] = dados.pop("escalas")[0]  # como era gravado antes desta versão
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    assert client.get("/api/escala").get_json()["plantoes"] == final["plantoes"]


def test_paginas_marcam_a_versao_dos_arquivos(client):
    html = client.get("/").data.decode("utf-8")
    v = client.get("/api/versao").get_json()["app"]
    assert f"js/app.js?v={v}" in html and f"css/style.css?v={v}" in html


# --- retenção da auditoria -------------------------------------------------

def test_auditoria_guarda_so_os_ultimos_30_dias(tmp_path):
    import json
    from datetime import datetime, timedelta
    from escala.usuarios import Auditoria

    agora = datetime.now().astimezone()
    caminho = tmp_path / "auditoria.jsonl"
    linhas = [{"quando": (agora - timedelta(days=d)).isoformat(timespec="seconds"),
               "tipo": "LOGIN", "usuario": f"U{d}", "descricao": "", "ip": None} for d in (45, 31, 29, 1)]
    caminho.write_text("".join(json.dumps(l) + "\n" for l in linhas) + "linha quebrada\n", encoding="utf-8")

    aud = Auditoria(caminho)  # limpa ao iniciar
    assert [e["usuario"] for e in aud.listar()] == ["U1", "U29"]
    assert "linha quebrada" in caminho.read_text(encoding="utf-8")  # sem data: mantida

    aud.registrar("LOGOUT", "Ana", "Saiu")
    assert [e["usuario"] for e in aud.listar()] == ["Ana", "U1", "U29"]


# --- PWA (app instalável) --------------------------------------------------

def test_pwa_manifesto_e_service_worker_sao_publicos(tmp_path):
    from webapp import create_app
    app = create_app(tmp_path / "dados.json", tmp_path / "usuarios.json", tmp_path / "auditoria.jsonl")
    anonimo = app.test_client()  # o navegador busca o manifesto sem a sessão
    r = anonimo.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.mimetype == "application/manifest+json"
    manifesto = r.get_json(force=True)
    assert manifesto["start_url"] == "/" and manifesto["display"] == "standalone"
    for icone in manifesto["icons"]:
        assert anonimo.get("/" + icone["src"]).status_code == 200
    sw = anonimo.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Cache-Control"] == "no-cache"
    assert "/api/" in sw.data.decode()  # a API nunca vai para o cache
    assert anonimo.get("/offline.html").status_code == 200
