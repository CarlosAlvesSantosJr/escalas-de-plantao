"""Frontend web do Sistema de Escalas (Flask + SPA em static/)."""
from __future__ import annotations

import os
from datetime import date
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request

from escala.algoritmo import ResultadoEscala, gerar_escala
from escala.dominio import Cargo, Funcionario, Periodo, Status, Turno, normalizar_nome
from escala.relatorio_pdf import gerar_pdf
from escala.repositorio import EstadoApp, RepositorioJSON

BASE_DIR = Path(__file__).resolve().parent


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
        "periodo": ({"inicio": estado.periodo.inicio.isoformat(),
                     "fim": estado.periodo.fim.isoformat()} if estado.periodo else None),
        "funcionarios": [funcionario_json(f) for f in estado.funcionarios],
    }


def resultado_json(r: ResultadoEscala) -> dict:
    def membro(f):
        return {"id": f.id, "nome": f.nome} if f else None

    return {
        "cobertura": r.cobertura,
        "plantoes": [{"data": p.data.isoformat(), "turno": p.turno.value,
                      "enfermeiro": membro(p.enfermeiro), "motorista": membro(p.motorista)}
                     for p in r.plantoes],
        "vagas": [{"data": v.data.isoformat(), "turno": v.turno.value,
                   "cargo": v.cargo.value, "motivo": v.motivo} for v in r.vagas],
        "estatisticas": [{"id": s.funcionario.id, "nome": s.funcionario.nome,
                          "cargo": s.funcionario.cargo.value, "total": s.total,
                          "dias": s.dias, "noites": s.noites,
                          "fins_de_semana": s.fins_de_semana,
                          "preferenciais_atendidas": s.preferenciais_atendidas}
                         for s in r.estatisticas],
    }


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
            return jsonify(estado_json(repo.carregar()))

    @app.put("/api/periodo")
    @transacao
    def definir_periodo(estado: EstadoApp):
        corpo = request.get_json(force=True)
        estado.periodo = Periodo(_parse_data(corpo.get("inicio")), _parse_data(corpo.get("fim")))
        if estado.periodo.total_dias > 92:
            raise ErroDeNegocio("O período máximo é de 92 dias.")
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

    @app.post("/api/escala")
    def gerar():
        with repo.lock:
            estado = repo.carregar()
        return jsonify(resultado_json(gerar_escala(estado.funcionarios, exigir_periodo(estado))))

    @app.get("/api/escala.pdf")
    def exportar_pdf():
        with repo.lock:
            estado = repo.carregar()
        periodo = exigir_periodo(estado)
        pdf = gerar_pdf(gerar_escala(estado.funcionarios, periodo))
        nome = f"escala_samu_{periodo.inicio:%Y%m%d}_{periodo.fim:%Y%m%d}.pdf"
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    return app


def _buscar(estado: EstadoApp, id_: str) -> Funcionario:
    try:
        return estado.funcionario(id_)
    except KeyError:
        raise ErroDeNegocio("Profissional não encontrado.", 404)


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
