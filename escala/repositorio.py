"""Persistência em JSON.

Lê o formato antigo (campo "tipo", sem "id", sem período) e grava o novo.
A gravação é atômica (arquivo temporário + rename) para não corromper os
dados se o processo cair no meio da escrita.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .dominio import Cargo, Funcionario, Periodo, Status, Turno


@dataclass
class EstadoApp:
    funcionarios: list[Funcionario] = field(default_factory=list)
    periodo: Periodo | None = None

    def funcionario(self, id_: str) -> Funcionario:
        for f in self.funcionarios:
            if f.id == id_:
                return f
        raise KeyError(id_)

    def nome_em_uso(self, nome: str, ignorar_id: str | None = None) -> bool:
        return any(f.nome == nome and f.id != ignorar_id for f in self.funcionarios)


def _funcionario_para_dict(f: Funcionario) -> dict:
    return {
        "id": f.id,
        "nome": f.nome,
        "tipo": f.cargo.value,
        "disponibilidade": {f"{d.isoformat()}|{t.value}": s.value
                            for (d, t), s in sorted(f.disponibilidade.items())},
    }


def _funcionario_de_dict(item: dict) -> Funcionario:
    extras = {"id": item["id"]} if item.get("id") else {}
    f = Funcionario(nome=item["nome"], cargo=Cargo(item.get("tipo") or item["cargo"]), **extras)
    for chave, valor in item.get("disponibilidade", {}).items():
        data_str, turno = chave.split("|")
        f.definir_status(date.fromisoformat(data_str), Turno(turno), Status(valor))
    return f


class RepositorioJSON:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.lock = threading.RLock()

    def carregar(self) -> EstadoApp:
        if not self.caminho.exists():
            return EstadoApp()
        with self.caminho.open(encoding="utf-8") as fp:
            dados = json.load(fp)
        periodo = None
        if p := dados.get("periodo"):
            periodo = Periodo(date.fromisoformat(p["inicio"]), date.fromisoformat(p["fim"]))
        return EstadoApp(
            funcionarios=[_funcionario_de_dict(i) for i in dados.get("funcionarios", [])],
            periodo=periodo,
        )

    def salvar(self, estado: EstadoApp) -> None:
        dados = {
            "periodo": ({"inicio": estado.periodo.inicio.isoformat(),
                         "fim": estado.periodo.fim.isoformat()} if estado.periodo else None),
            "funcionarios": [_funcionario_para_dict(f) for f in estado.funcionarios],
        }
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.caminho.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(dados, fp, indent=2, ensure_ascii=False)
            os.replace(tmp, self.caminho)
        except BaseException:
            os.unlink(tmp)
            raise
