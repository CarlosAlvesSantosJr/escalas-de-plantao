"""Gera e mantém o arquivo de usuários (usuarios.json) com as matrículas em hash.

Uso:
  # A partir de uma lista "NOME;MATRICULA;PAPEL" (PAPEL = ADMIN ou USUARIO, opcional)
  python usuarios_cli.py gerar lista.csv dados/usuarios.json

  # Adiciona ou troca a matrícula de alguém (a matrícula é pedida sem aparecer na tela)
  python usuarios_cli.py adicionar dados/usuarios.json "Maria" --admin

  # Desativa ou lista
  python usuarios_cli.py desativar dados/usuarios.json "Maria"
  python usuarios_cli.py listar dados/usuarios.json

Apague a lista com as matrículas em texto depois de gerar o arquivo.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from escala.usuarios import Papel, Usuario, chave_nome, novo_usuario


def ler(caminho: Path) -> list[Usuario]:
    if not caminho.exists():
        return []
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return [Usuario.de_dict(u) for u in (dados["usuarios"] if isinstance(dados, dict) else dados)]


def gravar(caminho: Path, usuarios: list[Usuario]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    corpo = {"usuarios": [u.para_dict() for u in sorted(usuarios, key=lambda u: chave_nome(u.nome))]}
    caminho.write_text(json.dumps(corpo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def substituir(usuarios: list[Usuario], novo: Usuario) -> list[Usuario]:
    return [u for u in usuarios if chave_nome(u.nome) != chave_nome(novo.nome)] + [novo]


def cmd_gerar(a) -> None:
    usuarios: list[Usuario] = []
    for n, linha in enumerate(Path(a.lista).read_text(encoding="utf-8-sig").splitlines(), 1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        partes = [p.strip() for p in linha.replace("\t", ";").split(";")]
        if len(partes) < 2 or not partes[0] or not partes[1]:
            sys.exit(f"Linha {n}: use NOME;MATRICULA;PAPEL")
        papel = Papel((partes[2] if len(partes) > 2 and partes[2] else "USUARIO").upper())
        usuarios = substituir(usuarios, novo_usuario(partes[0], partes[1], papel))
    gravar(Path(a.saida), usuarios)
    print(f"{len(usuarios)} usuário(s) gravados em {a.saida}")


def cmd_adicionar(a) -> None:
    caminho = Path(a.arquivo)
    matricula = getpass.getpass(f"Matrícula de {a.nome}: ")
    if not matricula.strip():
        sys.exit("Matrícula vazia.")
    gravar(caminho, substituir(ler(caminho), novo_usuario(a.nome, matricula, Papel.ADMIN if a.admin else Papel.USUARIO)))
    print(f"{a.nome} gravado(a) em {caminho}")


def cmd_desativar(a) -> None:
    caminho = Path(a.arquivo)
    usuarios = ler(caminho)
    alvo = [u for u in usuarios if chave_nome(u.nome) == chave_nome(a.nome)]
    if not alvo:
        sys.exit(f"{a.nome} não encontrado(a).")
    u = alvo[0]
    gravar(caminho, substituir(usuarios, Usuario(u.nome, u.papel, u.hash_matricula, ativo=False)))
    print(f"{u.nome} desativado(a).")


def cmd_listar(a) -> None:
    for u in ler(Path(a.arquivo)):
        print(f"{u.nome:<20} {u.papel.value:<8} {'ativo' if u.ativo else 'DESATIVADO'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("gerar"); s.add_argument("lista"); s.add_argument("saida"); s.set_defaults(f=cmd_gerar)
    s = sub.add_parser("adicionar"); s.add_argument("arquivo"); s.add_argument("nome")
    s.add_argument("--admin", action="store_true"); s.set_defaults(f=cmd_adicionar)
    s = sub.add_parser("desativar"); s.add_argument("arquivo"); s.add_argument("nome"); s.set_defaults(f=cmd_desativar)
    s = sub.add_parser("listar"); s.add_argument("arquivo"); s.set_defaults(f=cmd_listar)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
