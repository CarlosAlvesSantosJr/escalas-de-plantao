# Rodar na Vercel com banco Neon (teste)

Esta versão roda o app na **Vercel** (servidor da Vercel, sem precisar de PC ligado)
e guarda tudo num **Postgres gratuito da Neon**. Ela está no ramo `vercel-neon`.
A versão estável, com Docker e Kubernetes, continua na tag `v1.4.1` e funciona
como antes.

```
Celular / PC ──HTTPS──▶ Vercel (Flask, região São Paulo) ──▶ Neon Postgres (São Paulo)
                         sem disco: cada acesso pode           escala, usuários, auditoria,
                         cair numa cópia diferente do app       tentativas de login, chave da sessão
```

## O que muda em relação ao Docker/Kubernetes

| | Docker / Kubernetes | Vercel + Neon |
|---|---|---|
| Onde ficam as escalas | Arquivo `dados_escala.json` no disco | Tabela `escala_estado` (Neon) |
| Usuários | Arquivo `usuarios.json` (Secret) | Tabela `escala_usuarios` |
| Auditoria (30 dias) | `auditoria.jsonl` | Tabela `escala_auditoria` |
| Bloqueio de tentativas de login | Memória do processo | Tabela `escala_falhas` (vale para todas as cópias) |
| Duas trocas ao mesmo tempo | Trava em memória (1 processo) | Trava do Postgres (`pg_advisory_xact_lock`) |
| Chave da sessão | `ESCALA_SECRET_KEY` ou arquivo | `ESCALA_SECRET_KEY` ou tabela `escala_config` |
| Fuso horário | TZ do contêiner | `America/Sao_Paulo` no código (a Vercel roda em UTC) |
| Atualização das telas | A cada 3 s, mesmo com a aba escondida | A cada 10 s, pausa com a aba escondida |
| Precisa de PC ligado | Sim | Não |

O app escolhe o modo sozinho: com a variável `DATABASE_URL` definida, usa o banco.
Sem ela, usa os arquivos, como sempre.

## Passo a passo

### 1. Projeto na Vercel

1. Entre em https://vercel.com com a sua conta do GitHub (plano **Hobby**, grátis).
2. **Add New → Project** → importe o repositório `escalas-de-plantao` → **Deploy**.
   O primeiro deploy **falha**, de propósito, porque ainda não há banco.
   A mensagem é "Defina DATABASE_URL".
3. **Settings → Git → Production Branch**: troque para `vercel-neon` e salve.
   Assim o endereço principal (`https://<projeto>.vercel.app`) usa esta versão.
   Não teste por um endereço de *preview*: ele vem protegido por login da Vercel,
   e a equipe não consegue abrir.

### 2. Banco Neon

1. No projeto: **Storage → Create Database → Neon** (Serverless Postgres) → plano **Free**.
2. Região: **São Paulo (aws-sa-east-1)**, a mesma da função (`gru1`, em `vercel.json`).
3. **Connect** ao projeto, marcando os ambientes Production e Preview.
   A Vercel cria a variável `DATABASE_URL`.

As tabelas são criadas sozinhas no primeiro acesso.

### 3. Levar os dados de hoje para o banco

No PC, com a escala atual e os usuários. Pegue a *connection string* em
**Storage → (banco) → .env.local → `DATABASE_URL`**:

```bash
pip install "psycopg[binary]" tzdata
# Escala e auditoria do Kubernetes (copie antes do pod: veja k8s/README.md, "Backup")
export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
python banco_cli.py enviar --dados dados/backup-AAAAMMDD/dados_escala.json \
                           --auditoria dados/backup-AAAAMMDD/auditoria.jsonl \
                           --usuarios k8s/base/segredos/usuarios.json
```

No PowerShell, troque `export X=...` por `$env:DATABASE_URL = "..."`.

### 4. Publicar

**Deployments → (o último) → Redeploy**. Depois abra
`https://<projeto>.vercel.app` e entre com o seu nome e matrícula.

Cada `git push` no ramo `vercel-neon` publica sozinho uma versão nova.

## Dia a dia

| Tarefa | Como |
|---|---|
| Backup | `python banco_cli.py baixar backups/2026-11-15` (gera os mesmos 3 arquivos do modo Docker) |
| Novo usuário ou troca de matrícula | `python usuarios_cli.py adicionar usuarios.json "Nome"` e depois `python banco_cli.py enviar --usuarios usuarios.json` |
| Domínio próprio | **Settings → Domains → Add** (ex.: `escala.seudominio.com.br`); a Vercel mostra o registro DNS a criar |
| Ver erros | **Deployments → Logs** (o plano grátis guarda 1 hora) |

A lista de usuários do banco é **substituída** a cada `enviar --usuarios`. Guarde
o `usuarios.json` (só com hashes) num lugar seguro, fora do GitHub.

## Limites do plano grátis (para uma equipe pequena, sobra)

- **Vercel Hobby:** 1 milhão de execuções por mês. Cada tela aberta consulta a
  cada 10 s só enquanto está visível. Dez pessoas com o app aberto 1 h por dia
  dão cerca de 110 mil consultas por mês.
- **Neon Free:** o banco "dorme" depois de 5 minutos sem uso. O primeiro acesso
  depois disso demora cerca de 1 s a mais.
- O plano Hobby é para uso pessoal e não comercial. Para uso oficial do
  serviço, avalie o plano Pro ou o modo Docker/Kubernetes.

## Testes

```bash
pytest                                   # modo arquivo (sempre)
docker run -d --rm --name escala-pg-teste -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=escala \
       -p 127.0.0.1:55432:5432 postgres:17-alpine
ESCALA_TESTE_BANCO=postgresql://postgres:teste@127.0.0.1:55432/escala pytest   # + modo banco
```

O `tests/test_banco.py` roda **todos** os testes do webapp de novo sobre o
Postgres, mais os casos que só existem na nuvem:
- duas cópias do app gravando ao mesmo tempo;
- a sessão valendo entre cópias;
- o bloqueio de login valendo entre cópias;
- a limpeza da auditoria no banco.

## Arquivos desta versão

| Arquivo | Papel |
|---|---|
| `vercel_app.py` | Ponto de entrada na Vercel (`app = create_app()`) |
| `pyproject.toml` | Dependências e `[tool.vercel] entrypoint` (o `app.py` da raiz é o app de desktop) |
| `vercel.json` | Região da função: São Paulo (`gru1`) |
| `.vercelignore` | Não envia dados reais, segredos, docs, testes nem k8s para a Vercel |
| `escala/banco.py` | Repositório, usuários, auditoria e bloqueio de login no Postgres |
| `escala/relogio.py` | Data e hora no fuso de São Paulo |
| `banco_cli.py` | Envia os arquivos atuais para o banco e baixa backups |
