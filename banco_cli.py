"""Leva os dados para o Postgres (Neon) e faz backup de lá. Usa a variável DATABASE_URL.

  # Envia o que já existe hoje (escala, usuários e auditoria) para o banco
  python banco_cli.py enviar --dados dados/dados_escala.json --usuarios dados/usuarios.json \
                             --auditoria dados/auditoria.jsonl

  # Só os usuários (depois de mexer no arquivo com usuarios_cli.py)
  python banco_cli.py enviar --usuarios dados/usuarios.json

  # Backup: baixa tudo do banco para uma pasta (mesmo formato dos arquivos)
  python banco_cli.py baixar backups/2026-11-15

`enviar --dados` SUBSTITUI a escala do banco e `--usuarios` substitui a lista de
usuários. A auditoria é acrescentada.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from escala.banco import AuditoriaPostgres, Banco, CadastroPostgres, RepositorioPostgres
from escala.usuarios import Usuario
from webapp import url_do_banco


def conectar() -> Banco:
    url = url_do_banco()
    if not url:
        sys.exit("Defina DATABASE_URL com o endereço do Postgres (Neon → Connection string).")
    return Banco(url)


def cmd_enviar(a) -> None:
    banco = conectar()
    if not (a.dados or a.usuarios or a.auditoria):
        sys.exit("Nada a enviar: use --dados, --usuarios e/ou --auditoria.")
    if a.dados:
        dados = json.loads(Path(a.dados).read_text(encoding="utf-8"))
        repo = RepositorioPostgres(banco)
        with repo.lock:
            repo.salvar(_validar(dados))
        print(f"Escala enviada ({len(dados.get('escalas') or [])} escala(s) confirmada(s), "
              f"{len(dados.get('funcionarios') or [])} profissional(is)).")
    if a.usuarios:
        bruto = json.loads(Path(a.usuarios).read_text(encoding="utf-8"))
        lista = [Usuario.de_dict(u) for u in (bruto["usuarios"] if isinstance(bruto, dict) else bruto)]
        CadastroPostgres(banco).substituir_todos(lista)
        print(f"{len(lista)} usuário(s) enviados.")
    if a.auditoria:
        linhas = Path(a.auditoria).read_text(encoding="utf-8").splitlines()
        eventos = [json.loads(l) for l in linhas if l.strip()]
        print(f"{AuditoriaPostgres(banco).importar(eventos)} evento(s) de auditoria enviados.")


def _validar(dados: dict):
    """Lê com o mesmo código do app: um arquivo quebrado falha aqui, não em produção."""
    from escala.repositorio import estado_de_dados
    return estado_de_dados(dados)


def cmd_baixar(a) -> None:
    banco = conectar()
    pasta = Path(a.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    dados = RepositorioPostgres(banco).dados_brutos() or {}
    (pasta / "dados_escala.json").write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    usuarios = {"usuarios": [u.para_dict() for u in CadastroPostgres(banco).todos()]}
    (pasta / "usuarios.json").write_text(json.dumps(usuarios, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    eventos = list(reversed(AuditoriaPostgres(banco).listar(limite=1_000_000)))
    (pasta / "auditoria.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eventos),
                                           encoding="utf-8")
    print(f"Backup em {pasta}: escala, {len(usuarios['usuarios'])} usuário(s), {len(eventos)} evento(s).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enviar", help="envia arquivos locais para o banco")
    e.add_argument("--dados")
    e.add_argument("--usuarios")
    e.add_argument("--auditoria")
    e.set_defaults(func=cmd_enviar)
    b = sub.add_parser("baixar", help="backup do banco para uma pasta")
    b.add_argument("pasta")
    b.set_defaults(func=cmd_baixar)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
