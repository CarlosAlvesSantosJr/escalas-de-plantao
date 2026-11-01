"""Frontend web do Sistema de Escalas (Flask + SPA em static/)."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request

from escala.algoritmo import gerar_escala
from escala.avaliacao import ResultadoEscala, avaliar_escala, candidatos
from escala.dominio import Cargo, Escala, Funcionario, Periodo, Status, Turno, normalizar_nome
from escala.relatorio_pdf import gerar_pdf, ler_dados_embutidos
from escala.repositorio import (EstadoApp, RepositorioJSON, escala_de_dict, escala_para_dict,
                                periodo_para_dict)

BASE_DIR = Path(__file__).resolve().parent
MAX_DIAS = 92
FORMATO_EXPORTACAO = "escala-samu"


class ErroDeNegocio(Exception):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


# --- serialização -------------------------------------------------------

def funcionario_json(f: Funcionario) -> dict:
    return {
        "id": f.id,
        "nome": f.nome,
        "cargo": f.cargo.value,
        "disponibilidade": {f"{d.isoformat()}|{t.value}": s.value
                            for (d, t), s in f.disponibilidade.items()},
    }


def estado_json(estado: EstadoApp) -> dict:
    return {
        "periodo": periodo_para_dict(estado.periodo) if estado.periodo else None,
        "funcionarios": [funcionario_json(f) for f in estado.funcionarios],
    }


def resultado_json(r: ResultadoEscala) -> dict:
    cores = r.cores

    def membro(f):
        return {"id": f.id, "nome": f.nome, "cor": cores[f.id]} if f else None

    return {
        "periodo": periodo_para_dict(r.periodo),
        "cobertura": r.cobertura,
        "plantoes": [{"data": p.data.isoformat(), "turno": p.turno.value,
                      "enfermeiro": membro(p.enfermeiro), "motorista": membro(p.motorista),
                      "editados": sorted(c.value for c in p.editados)}
                     for p in r.plantoes],
        "vagas": [{"data": v.data.isoformat(), "turno": v.turno.value,
                   "cargo": v.cargo.value, "motivo": v.motivo} for v in r.vagas],
        "conflitos": [{"data": c.data.isoformat(), "turno": c.turno.value, "cargo": c.cargo.value,
                       "id": c.funcionario.id, "nome": c.funcionario.nome, "motivo": c.motivo}
                      for c in r.conflitos],
        "estatisticas": [{"id": s.funcionario.id, "nome": s.funcionario.nome,
                          "cargo": s.funcionario.cargo.value, "cor": cores[s.funcionario.id],
                          "total": s.total, "dias": s.dias, "noites": s.noites,
                          "fins_de_semana": s.fins_de_semana,
                          "preferenciais_atendidas": s.preferenciais_atendidas}
                         for s in r.estatisticas],
    }


def avaliar(estado: EstadoApp, e: Escala) -> ResultadoEscala:
    return avaliar_escala(estado.funcionarios, e.periodo, e.plantoes)


def escala_json(estado: EstadoApp, e: Escala | None) -> dict | None:
    if e is None:
        return None
    dados = resultado_json(avaliar(estado, e))
    dados["confirmada_em"] = e.confirmada_em.isoformat(timespec="minutes") if e.confirmada_em else None
    return dados


def exportacao(e: Escala) -> dict:
    """Arquivo autocontido da escala, que pode ser importado em outra instalação."""
    return {"formato": FORMATO_EXPORTACAO, "versao": 1, **escala_para_dict(e)}


def _parse_data(valor) -> date:
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ErroDeNegocio(f"Data inválida: {valor!r}")


def _parse_enum(enum_cls, valor):
    try:
        return enum_cls(valor)
    except ValueError:
        raise ErroDeNegocio(f"Valor inválido: {valor!r}")


# --- aplicação ----------------------------------------------------------

def create_app(caminho_dados: str | Path | None = None) -> Flask:
    caminho_dados = caminho_dados or os.environ.get("ESCALA_DADOS") or BASE_DIR / "dados_escala.json"
    app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    repo = RepositorioJSON(caminho_dados)

    def transacao(func):
        """Carrega o estado, executa a operação e persiste, tudo sob lock."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            with repo.lock:
                estado = repo.carregar()
                resposta = func(estado, *args, **kwargs)
                repo.salvar(estado)
                return resposta
        return wrapper

    def exigir_periodo(estado: EstadoApp) -> Periodo:
        if not estado.periodo:
            raise ErroDeNegocio("Defina o período da escala primeiro.")
        if not estado.funcionarios:
            raise ErroDeNegocio("Cadastre a equipe antes de gerar a escala.")
        return estado.periodo

    @app.errorhandler(ErroDeNegocio)
    def _erro_negocio(e: ErroDeNegocio):
        return jsonify(erro=str(e)), e.status

    @app.errorhandler(ValueError)
    def _erro_validacao(e: ValueError):
        return jsonify(erro=str(e)), 400

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/saude")
    def saude():
        return jsonify(status="ok")

    @app.get("/api/estado")
    def obter_estado():
        with repo.lock:
            estado = repo.carregar()
            return jsonify(**estado_json(estado), rascunho=escala_json(estado, estado.rascunho),
                           escala=escala_json(estado, estado.escala))

    @app.put("/api/periodo")
    @transacao
    def definir_periodo(estado: EstadoApp):
        corpo = request.get_json(force=True)
        estado.periodo = Periodo(_parse_data(corpo.get("inicio")), _parse_data(corpo.get("fim")))
        if estado.periodo.total_dias > MAX_DIAS:
            raise ErroDeNegocio(f"O período máximo é de {MAX_DIAS} dias.")
        # Rascunho de outro período não serve mais; a escala final é mantida.
        if estado.rascunho and estado.rascunho.periodo != estado.periodo:
            estado.rascunho = None
        return jsonify(estado_json(estado))

    @app.post("/api/funcionarios")
    @transacao
    def criar_funcionario(estado: EstadoApp):
        corpo = request.get_json(force=True)
        nome = normalizar_nome(corpo.get("nome", ""))
        if estado.nome_em_uso(nome):
            raise ErroDeNegocio(f"Já existe um profissional chamado {nome}.", 409)
        f = Funcionario(nome, _parse_enum(Cargo, corpo.get("cargo")))
        estado.funcionarios.append(f)
        return jsonify(funcionario_json(f)), 201

    @app.put("/api/funcionarios/<id_>")
    @transacao
    def atualizar_funcionario(estado: EstadoApp, id_: str):
        corpo = request.get_json(force=True)
        f = _buscar(estado, id_)
        nome = normalizar_nome(corpo.get("nome", ""))
        if estado.nome_em_uso(nome, ignorar_id=id_):
            raise ErroDeNegocio(f"Já existe um profissional chamado {nome}.", 409)
        f.nome = nome
        f.cargo = _parse_enum(Cargo, corpo.get("cargo"))
        return jsonify(funcionario_json(f))

    @app.delete("/api/funcionarios/<id_>")
    @transacao
    def remover_funcionario(estado: EstadoApp, id_: str):
        estado.funcionarios.remove(_buscar(estado, id_))
        return "", 204

    @app.patch("/api/funcionarios/<id_>/disponibilidade")
    @transacao
    def alterar_disponibilidade(estado: EstadoApp, id_: str):
        """Corpo: lista de {data, turno, status}. Aplica todas em lote."""
        f = _buscar(estado, id_)
        alteracoes = request.get_json(force=True)
        if not isinstance(alteracoes, list):
            raise ErroDeNegocio("Envie uma lista de alterações.")
        for a in alteracoes:
            f.definir_status(_parse_data(a.get("data")), _parse_enum(Turno, a.get("turno")),
                             _parse_enum(Status, a.get("status")))
        return jsonify(funcionario_json(f))

    # --- revisão (rascunho) ---------------------------------------------

    def exigir_rascunho(estado: EstadoApp) -> Escala:
        if not estado.rascunho:
            raise ErroDeNegocio("Não há escala em revisão. Gere uma proposta primeiro.", 404)
        return estado.rascunho

    @app.get("/api/rascunho")
    def obter_rascunho():
        with repo.lock:
            estado = repo.carregar()
            return jsonify(escala_json(estado, estado.rascunho))

    @app.post("/api/rascunho")
    @transacao
    def gerar_rascunho(estado: EstadoApp):
        periodo = exigir_periodo(estado)
        estado.rascunho = Escala(periodo, gerar_escala(estado.funcionarios, periodo).plantoes)
        return jsonify(escala_json(estado, estado.rascunho))

    @app.patch("/api/rascunho")
    @transacao
    def editar_rascunho(estado: EstadoApp):
        """Corpo: lista de {data, turno, cargo, funcionario_id (null = vago), editado?}."""
        rascunho = exigir_rascunho(estado)
        alteracoes = request.get_json(force=True)
        if not isinstance(alteracoes, list):
            raise ErroDeNegocio("Envie uma lista de alterações.")
        # Quem já está na escala pode voltar ao lugar (desfazer), mesmo fora da equipe.
        pessoas = {**rascunho.pessoas(), **{f.id: f for f in estado.funcionarios}}
        for a in alteracoes:
            cargo = _parse_enum(Cargo, a.get("cargo"))
            try:
                plantao = rascunho.plantao(_parse_data(a.get("data")), _parse_enum(Turno, a.get("turno")))
            except KeyError:
                raise ErroDeNegocio("Turno fora do período da escala.")
            f = None
            if fid := a.get("funcionario_id"):
                f = pessoas.get(fid) or _buscar(estado, fid)
                if f.cargo is not cargo:
                    raise ErroDeNegocio(f"{f.nome} é {f.cargo.rotulo.lower()} e não pode ocupar "
                                        f"a vaga de {cargo.rotulo.lower()}.")
            plantao.equipe[cargo] = f
            if a.get("editado", True):
                plantao.editados.add(cargo)
            else:
                plantao.editados.discard(cargo)
        return jsonify(escala_json(estado, rascunho))

    @app.delete("/api/rascunho")
    @transacao
    def descartar_rascunho(estado: EstadoApp):
        estado.rascunho = None
        return "", 204

    @app.get("/api/rascunho/candidatos")
    def listar_candidatos():
        with repo.lock:
            estado = repo.carregar()
        rascunho = exigir_rascunho(estado)
        dia = _parse_data(request.args.get("data"))
        turno = _parse_enum(Turno, request.args.get("turno"))
        cargo = _parse_enum(Cargo, request.args.get("cargo"))
        return jsonify([{"id": c.funcionario.id, "nome": c.funcionario.nome, "total": c.total,
                         "preferencial": c.preferencial, "impedimentos": c.impedimentos}
                        for c in candidatos(estado.funcionarios, rascunho.plantoes, dia, turno, cargo)])

    # --- escala final ----------------------------------------------------

    def exigir_escala(estado: EstadoApp) -> Escala:
        if not estado.escala:
            raise ErroDeNegocio("Nenhuma escala confirmada. Revise e confirme a escala primeiro.", 404)
        return estado.escala

    @app.get("/api/escala")
    def obter_escala():
        with repo.lock:
            estado = repo.carregar()
            return jsonify(escala_json(estado, estado.escala))

    @app.post("/api/escala")
    @transacao
    def confirmar_escala(estado: EstadoApp):
        """Confirma o rascunho em revisão como a escala final."""
        rascunho = exigir_rascunho(estado)
        rascunho.confirmada_em = datetime.now()
        estado.escala, estado.rascunho = rascunho, None
        return jsonify(escala_json(estado, estado.escala))

    @app.post("/api/escala/editar")
    @transacao
    def editar_escala(estado: EstadoApp):
        """Abre uma cópia da escala final para revisão, substituindo o rascunho atual."""
        final = exigir_escala(estado)
        copia, _ = escala_de_dict(escala_para_dict(final), estado.funcionarios)
        copia.confirmada_em = None
        estado.rascunho, estado.periodo = copia, final.periodo
        return jsonify(rascunho=escala_json(estado, copia), estado=estado_json(estado))

    @app.post("/api/escala/importar")
    @transacao
    def importar_escala(estado: EstadoApp):
        """Recebe um .json exportado ou um PDF gerado pelo sistema e o abre para revisão."""
        arquivo = request.files.get("arquivo")
        if not arquivo:
            raise ErroDeNegocio("Selecione um arquivo para importar.")
        conteudo = arquivo.read()
        try:
            if conteudo.startswith(b"%PDF"):
                dados = ler_dados_embutidos(conteudo)
                if dados is None:
                    raise ErroDeNegocio("Este PDF não traz os dados da escala. Só é possível importar "
                                        "PDFs baixados desta versão do sistema.")
            else:
                dados = json.loads(conteudo.decode("utf-8"))
            if not isinstance(dados, dict) or dados.get("formato") != FORMATO_EXPORTACAO:
                raise ErroDeNegocio("O arquivo não é uma escala exportada por este sistema.")
            escala, novos = escala_de_dict(dados, estado.funcionarios, incluir_ausentes=True)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise ErroDeNegocio(f"Arquivo de escala inválido ou corrompido ({e}).")
        if escala.periodo.total_dias > MAX_DIAS:
            raise ErroDeNegocio(f"O período máximo é de {MAX_DIAS} dias.")
        escala.confirmada_em = None
        estado.rascunho, estado.periodo = escala, escala.periodo
        return jsonify(rascunho=escala_json(estado, escala), estado=estado_json(estado),
                       adicionados=[f.nome for f in novos])

    def _nome_arquivo(e: Escala, ext: str) -> str:
        return f"escala_samu_{e.periodo.inicio:%Y%m%d}_{e.periodo.fim:%Y%m%d}.{ext}"

    def _download(corpo, mimetype: str, nome: str) -> Response:
        return Response(corpo, mimetype=mimetype,
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    @app.get("/api/escala.pdf")
    def exportar_pdf():
        with repo.lock:
            estado = repo.carregar()
        final = exigir_escala(estado)
        pdf = gerar_pdf(avaliar(estado, final), dados=exportacao(final))
        return _download(pdf, "application/pdf", _nome_arquivo(final, "pdf"))

    @app.get("/api/escala.json")
    def exportar_json():
        with repo.lock:
            estado = repo.carregar()
        final = exigir_escala(estado)
        corpo = json.dumps(exportacao(final), indent=2, ensure_ascii=False)
        return _download(corpo, "application/json", _nome_arquivo(final, "json"))

    return app


def _buscar(estado: EstadoApp, id_: str) -> Funcionario:
    try:
        return estado.funcionario(id_)
    except KeyError:
        raise ErroDeNegocio("Profissional não encontrado.", 404)


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
