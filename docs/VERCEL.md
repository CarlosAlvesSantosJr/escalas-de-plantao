# Produção: Vercel + Neon

O sistema está no ar em **[minhaescala192.vercel.app](https://minhaescala192.vercel.app)** e é usado
no dia a dia pela equipe. O app roda como função Python na **Vercel** e guarda tudo num
**Postgres da Neon**, os dois em São Paulo. Não depende de nenhum computador ligado.

```
Celular / PC ──HTTPS──▶ Vercel (Flask, região gru1, São Paulo) ──▶ Neon Postgres (São Paulo)
                         sem disco: cada acesso pode                escala, usuários, auditoria,
                         cair numa cópia diferente do app            tentativas de login, chave da sessão
```

| Item | Valor |
|---|---|
| Endereço | https://minhaescala192.vercel.app |
| Projeto Vercel | `minhaescala192` (time `plantao-samu`, plano Hobby) |
| Banco | Neon Free, região `gru1` (São Paulo), criado pela integração da Vercel |
| Variável com a conexão | `DATABASE_URL` (criada pela integração) |
| Publicação | `vercel deploy --prod`, a partir do PC |

## O que muda em relação ao Docker/Kubernetes

| | Docker / Kubernetes | Vercel + Neon (produção) |
|---|---|---|
| Onde ficam as escalas | Arquivo `dados_escala.json` no disco | Tabela `escala_estado` (JSONB) |
| Usuários | Arquivo `usuarios.json` (Secret) | Tabela `escala_usuarios` |
| Auditoria (30 dias) | `auditoria.jsonl` | Tabela `escala_auditoria` |
| Bloqueio de tentativas de login | Memória do processo | Tabela `escala_falhas` (vale para todas as cópias) |
| Duas trocas ao mesmo tempo | Trava em memória (1 processo) | Trava do Postgres (`pg_advisory_xact_lock`) |
| Chave da sessão | `ESCALA_SECRET_KEY` ou arquivo | `ESCALA_SECRET_KEY` ou tabela `escala_config` |
| Fuso horário | TZ do contêiner | `America/Sao_Paulo` no código (a Vercel roda em UTC) |
| Atualização das telas | A cada 3 s | A cada 10 s, pausando com a aba escondida |
| Precisa de PC ligado | Sim | Não |

O app escolhe o modo sozinho: com `DATABASE_URL` definida, usa o banco. Sem ela, usa
os arquivos, como sempre.

## Como foi montado (para refazer do zero)

Tudo pela linha de comando da Vercel (`npm install -g vercel`), na pasta do projeto:

```bash
vercel login                                         # aprova no navegador
vercel project create minhaescala192                 # o nome vira o endereço .vercel.app
vercel link --yes --project minhaescala192

# Banco Neon grátis em São Paulo, já conectado ao projeto (cria DATABASE_URL).
# Na primeira vez a Neon pede para aceitar os termos no navegador.
vercel integration add neon --billing-plan free_v3 --meta region=gru1

# Leva os dados atuais (backup do Kubernetes) e os usuários para o banco.
# A conexão vem do .env.local que o comando acima baixou (fica fora do Git).
pip install "psycopg[binary]" tzdata
export DATABASE_URL="$(grep '^DATABASE_URL=' .env.local | cut -d= -f2- | tr -d '"')"
python banco_cli.py enviar --dados dados/backup-AAAAMMDD/dados_escala.json \
                           --auditoria dados/backup-AAAAMMDD/auditoria.jsonl \
                           --usuarios k8s/base/segredos/usuarios.json

vercel deploy --prod                                 # publica
```

No PowerShell, troque `export X=...` por `$env:DATABASE_URL = "..."`.

**Detalhes que importam:**
- **`vercel.json` precisa de `"framework": "flask"`.** Sem isso, um projeto criado pela
  linha de comando é publicado como site estático vazio, e todas as páginas dão 404.
- **`pyproject.toml` define a entrada** (`[tool.vercel] entrypoint = "vercel_app:app"`),
  porque a raiz também tem o `app.py` do app de desktop.
- **`.vercelignore`** impede que dados reais, segredos, docs, testes e manifests do
  Kubernetes subam para a Vercel.
- As tabelas são criadas sozinhas no primeiro acesso.

## Dia a dia

| Tarefa | Como |
|---|---|
| Publicar uma versão nova | Rodar os testes e depois `vercel deploy --prod` |
| Backup | `python banco_cli.py baixar backups/AAAA-MM-DD` (gera os mesmos 3 arquivos do modo Docker) |
| Novo usuário ou troca de matrícula | `python usuarios_cli.py adicionar usuarios.json "Nome"` e depois `python banco_cli.py enviar --usuarios usuarios.json` |
| Domínio próprio | Na Vercel: **Settings → Domains → Add** (ex.: `escala.seudominio.com.br`); ela mostra o registro DNS a criar |
| Ver erros | `vercel logs minhaescala192.vercel.app` ou **Deployments → Logs** (o plano grátis guarda 1 hora) |

A lista de usuários do banco é **substituída** a cada `enviar --usuarios`. Guarde o
`usuarios.json` (só com hashes) num lugar seguro, fora do GitHub.

## Limites do plano grátis (para uma equipe pequena, sobra)

- **Vercel Hobby:** 1 milhão de execuções por mês. Cada tela aberta consulta a cada 10 s
  só enquanto está visível: dez pessoas com o app aberto 1 h por dia dão cerca de
  110 mil consultas por mês.
- **Neon Free:** o banco "dorme" depois de 5 minutos sem uso. O primeiro acesso depois
  disso demora cerca de 1 s a mais.
- **Auditoria:** guarda os últimos 30 dias; a limpeza roda quando há uso, no máximo 1×/hora.
- O plano Hobby é para uso pessoal e não comercial. Se o uso virar oficial do serviço,
  avalie o plano Pro ou o modo Docker/Kubernetes.

## Testes

```bash
pytest                                   # modo arquivo (sempre)
docker run -d --rm --name escala-pg-teste -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=escala \
       -p 127.0.0.1:55432:5432 postgres:17-alpine
ESCALA_TESTE_BANCO=postgresql://postgres:teste@127.0.0.1:55432/escala pytest   # + modo banco
```

O `tests/test_banco.py` roda **todos** os testes do webapp de novo sobre o Postgres, mais
os casos que só existem na nuvem:
- duas cópias do app gravando ao mesmo tempo;
- a sessão valendo entre cópias;
- o bloqueio de login valendo entre cópias;
- a limpeza da auditoria no banco.

## Arquivos desta implantação

| Arquivo | Papel |
|---|---|
| `vercel_app.py` | Ponto de entrada na Vercel (`app = create_app()`) |
| `pyproject.toml` | Dependências e `[tool.vercel] entrypoint` |
| `vercel.json` | Framework `flask` e região da função: São Paulo (`gru1`) |
| `.vercelignore` | Não envia dados reais, segredos, docs, testes nem k8s para a Vercel |
| `escala/banco.py` | Repositório, usuários, auditoria e bloqueio de login no Postgres |
| `escala/relogio.py` | Data e hora no fuso de São Paulo |
| `banco_cli.py` | Envia os arquivos atuais para o banco e baixa backups |
