# Arquitetura · Escala de Plantão SAMU 192

Documento técnico: componentes, modelo de domínio (UML), fluxos, perfis de acesso,
API e a lógica que decide **quem pode assumir um plantão**.

**Em produção:** [minhaescala192.vercel.app](https://minhaescala192.vercel.app), usado no dia a dia pela
equipe do SAMU 192 de Tubarão-SC (Vercel + Postgres Neon, região São Paulo).

Sumário: [Visão geral](#1-visão-geral) · [Módulos](#2-módulos) · [UML](#3-modelo-de-domínio-uml) ·
[Troca de plantão](#4-lógica-da-troca-de-plantão) · [Mês atual e seguinte](#5-mês-atual-e-mês-seguinte) ·
[Perfis](#6-perfis-e-acesso-às-informações) · [Fluxos](#7-fluxos-diagramas-de-sequência) · [API](#8-api) ·
[Segurança](#9-segurança) · [Dados](#10-dados-e-persistência) · [Frontend e PWA](#11-frontend-e-pwa) · [Testes](#12-testes) · [Implantação](#13-implantação)

---

## 1. Visão geral

```mermaid
flowchart LR
    subgraph Cliente["Celular ou computador da equipe"]
        PWA["Navegador / app instalado (PWA)<br/>HTML · CSS · JS sem framework"]
        SW["Service worker<br/>cache de CSS, JS e imagens"]
    end
    OM["Open-Meteo<br/>previsão de Tubarão-SC"]
    subgraph Vercel["Vercel · região gru1 (São Paulo)"]
        FN["Função Python<br/>Flask (vercel_app.py → webapp.py)<br/>sem disco · várias cópias"]
    end
    subgraph Neon["Neon · Postgres (São Paulo)"]
        T1[("escala_estado<br/>escala inteira em JSONB")]
        T2[("escala_usuarios · escala_auditoria<br/>escala_falhas · escala_config")]
    end
    PWA <--> SW
    PWA -- "HTTPS + JSON" --> FN
    PWA -- "fetch direto" --> OM
    FN -- "psycopg · transação + trava" --> T1
    FN --> T2
```

- **Produção na nuvem:** o app roda como função Python na **Vercel** e guarda tudo num
  **Postgres da Neon**, os dois em São Paulo. Não depende de nenhum computador ligado.
- **Sem disco e com várias cópias:** cada acesso pode cair numa cópia diferente do app. Por
  isso escala, usuários, auditoria, bloqueio de login e chave da sessão ficam no banco, e
  toda gravação passa por uma trava do Postgres (`pg_advisory_xact_lock`).
- **Mesmo código, dois modos de dados:** com `DATABASE_URL` definida, usa o Postgres
  (`escala/banco.py`). Sem ela, usa arquivos JSON (`escala/repositorio.py`), como no Docker,
  no Kubernetes e no app desktop. Veja a [seção 10](#10-dados-e-persistência).
- O núcleo de regras (`escala/`) não sabe onde os dados ficam: algoritmo, avaliação e PDF
  são os mesmos em todos os modos.

## 2. Módulos

```mermaid
flowchart TB
    subgraph Interfaces
        WEB["webapp.py<br/>API REST + perfis + auditoria"]
        TK["app.py<br/>desktop Tkinter"]
        CLI["usuarios_cli.py<br/>cria usuários (hash)"]
        BCLI["banco_cli.py<br/>envia dados · backup"]
        VA["vercel_app.py<br/>entrada na Vercel"]
    end
    subgraph escala["Pacote escala/ (domínio puro, sem Flask)"]
        DOM["dominio.py<br/>modelos e enums"]
        ALG["algoritmo.py<br/>gera a proposta"]
        AVA["avaliacao.py<br/>vagas · conflitos · candidatos · estatísticas"]
        REP["repositorio.py<br/>JSON atômico · papéis das escalas"]
        USR["usuarios.py<br/>login · limite de tentativas · auditoria"]
        PDF["relatorio_pdf.py<br/>PDF com dados embutidos"]
        BAN["banco.py<br/>mesmas interfaces no Postgres"]
        REL["relogio.py<br/>fuso de São Paulo"]
    end
    VA --> WEB
    WEB --> ALG & AVA & REP & USR & PDF & BAN
    BCLI --> BAN
    BAN --> REP & USR
    TK --> ALG & REP
    CLI --> USR
    ALG --> AVA --> DOM
    REP --> DOM
```

| Caminho | Responsabilidade |
|---|---|
| `escala/dominio.py` | `Funcionario`, `Periodo`, `Plantao`, `Escala`; enums `Cargo`, `Turno`, `Status` |
| `escala/algoritmo.py` | Gera a escala (guloso com "olhar adiante"), sem I/O |
| `escala/avaliacao.py` | **Uma única fonte de regras**: `impedimentos()`, `candidatos()`, `avaliar_escala()` |
| `escala/repositorio.py` | `EstadoApp` (equipe, período, rascunho, escalas confirmadas), gravação atômica, `classificar()` (mês atual/seguinte) |
| `escala/usuarios.py` | `CadastroUsuarios` (scrypt), `LimiteTentativas`, `Auditoria` (JSON Lines, retenção de 30 dias) |
| `escala/relatorio_pdf.py` | PDF da escala com os dados embutidos para reimportar |
| `escala/banco.py` | `RepositorioPostgres`, `CadastroPostgres`, `AuditoriaPostgres`, `LimitePostgres`: as mesmas interfaces das versões em arquivo, sobre o Postgres |
| `escala/relogio.py` | `agora()` e `hoje()` no fuso `America/Sao_Paulo` (a Vercel roda em UTC) |
| `vercel_app.py` · `pyproject.toml` · `vercel.json` | Entrada, dependências e região da função na Vercel |
| `banco_cli.py` | Envia os arquivos atuais para o banco e baixa backups |
| `webapp.py` | Rotas, permissões por perfil, filtro dos dados enviados a cada perfil |
| `static/` | SPA (`index.html`, `js/app.js`), login, clima (`js/clima.js`), PWA (`manifest.webmanifest`, `sw.js`, `offline.html`) |

## 3. Modelo de domínio (UML)

```mermaid
classDiagram
    direction LR
    class Cargo {
        <<enumeration>>
        ENFERMEIRO
        MOTORISTA
        +rotulo
    }
    class Turno {
        <<enumeration>>
        DIA
        NOITE
    }
    class Status {
        <<enumeration>>
        DISPONIVEL
        INDISPONIVEL
        PREFERENCIAL
        FERIAS
    }
    class Funcionario {
        +id: str
        +nome: str
        +cargo: Cargo
        +disponibilidade: dict~(date,Turno), Status~
        +status(dia, turno) Status
        +pode_trabalhar(dia, turno) bool
    }
    class Periodo {
        +inicio: date
        +fim: date
        +dias()
        +slots()
    }
    class Plantao {
        +data: date
        +turno: Turno
        +equipe: dict~Cargo, Funcionario?~
        +editados: set~Cargo~
        +completo: bool
    }
    class Escala {
        +periodo: Periodo
        +plantoes: list~Plantao~
        +confirmada_em: datetime?
        +plantao(dia, turno) Plantao
    }
    class EstadoApp {
        +funcionarios: list~Funcionario~
        +periodo: Periodo?
        +rascunho: Escala?
        +escalas: list~Escala~
        +publicar(nova) list~Escala~
        +classificar(hoje) dict
        +escala_padrao(hoje) Escala?
    }
    class Candidato {
        +funcionario: Funcionario
        +total: int
        +preferencial: bool
        +impedimentos: list~str~
    }
    class ResultadoEscala {
        +estatisticas
        +vagas: list~Vaga~
        +conflitos: list~Conflito~
        +cobertura: float
        +cores: dict
    }
    class Usuario {
        +nome: str
        +papel: Papel
        +hash_matricula: str
        +ativo: bool
        +admin: bool
    }
    class Papel {
        <<enumeration>>
        ADMIN
        USUARIO
    }
    class Auditoria {
        +dias_retencao = 30
        +registrar(tipo, usuario, descricao, ip)
        +listar(usuario, tipo)
        +expurgar()
    }
    Funcionario --> Cargo
    Funcionario ..> Status
    Plantao --> Turno
    Plantao "1" o-- "0..2" Funcionario : equipe
    Escala "1" *-- "1" Periodo
    Escala "1" *-- "*" Plantao
    EstadoApp "1" o-- "*" Funcionario
    EstadoApp "1" o-- "0..1" Escala : rascunho
    EstadoApp "1" o-- "*" Escala : confirmadas (até 12)
    Candidato --> Funcionario
    ResultadoEscala ..> Escala : avalia
    Usuario --> Papel
```

**Ciclo de vida de uma escala:**

```mermaid
stateDiagram-v2
    [*] --> Periodo: ADM define o período
    Periodo --> Rascunho: Gerar proposta (algoritmo)
    Rascunho --> Rascunho: ajustes na Revisão (com desfazer)
    Rascunho --> Confirmada: Confirmar escala
    Rascunho --> [*]: Descartar
    Confirmada --> Confirmada: troca de plantão (ADM ou usuário, auditada)
    Confirmada --> Rascunho: Revisar (cópia; a publicada não muda)
    Confirmada --> [*]: sai após 12 escalas mais novas
```

## 4. Lógica da troca de plantão

Clicar num nome da escala abre o editor da posição (dia, turno e função). O servidor
(`GET /api/escala/candidatos` ou `/api/rascunho/candidatos`) devolve **todos** os
profissionais daquela função, cada um com a lista de **impedimentos**: as regras que
ele quebraria se assumisse o plantão. A tela os divide em dois grupos:

| Grupo | Quem entra | Como aparece |
|---|---|---|
| **Podem assumir** | Nenhum impedimento | Nome e "Disponível" (usuário) ou o total de plantões (ADM); ⭐ quando o turno é preferencial da pessoa |
| **Com impedimento** | Um ou mais impedimentos | Cada motivo escrito; avatar esmaecido. *Pode escalar, mas fica como conflito* |
| **Deixar vago** | — | A posição fica em aberto (VAGO) |

<table><tr>
<td><img src="img/troca-usuario.jpg" alt="Editor de troca visto pelo usuário"></td>
<td><img src="img/troca-adm.jpg" alt="Editor de troca visto pelo ADM, com total de plantões"></td>
</tr><tr>
<td align="center"><sub>Usuário: quem pode assumir, sem números de ninguém</sub></td>
<td align="center"><sub>ADM: o mesmo editor, com o total de plantões de cada pessoa</sub></td>
</tr></table>

### Os impedimentos (`escala/avaliacao.py → impedimentos()`)

| Ordem | Regra | Mensagem na tela | Por quê |
|---|---|---|---|
| 1 | Não está mais na equipe | "Não faz mais parte da equipe" | Foi removido(a) do cadastro |
| 2 | Função diferente | "Cadastrado(a) em Socorrista" | Enfermagem só cobre enfermagem, e vice-versa |
| 3 | Férias | "De férias" | Marcado no pincel de disponibilidade |
| 4 | Indisponível | "Indisponível neste turno" | Marcado no pincel de disponibilidade |
| 5 | **Um plantão por dia** | "Já tem outro plantão neste dia" | Ninguém faz DIA e NOITE na mesma data |
| 6 | **Descanso pós-noite** | "Saindo do plantão da noite anterior" | Quem fez a NOITE de ontem não pega o DIA de hoje |
| 7 | **Descanso pós-noite (adiante)** | "Tem plantão de dia logo após esta noite" | Assumir esta NOITE colidiria com o DIA de amanhã que a pessoa já tem |

As regras 5 a 7 são as de **descanso**: olham os plantões que a pessoa já tem no dia, no
dia anterior e no seguinte (classe `Agenda`, que indexa as posições por pessoa e por dia
para a checagem ser instantânea).

```mermaid
flowchart TD
    A["Clique num nome<br/>(dia, turno, função)"] --> B["Para cada profissional da função"]
    B --> C{"Na equipe e na<br/>função certa?"}
    C -- não --> X["impedimento"]
    C -- sim --> D{"Férias ou<br/>indisponível?"}
    D -- sim --> X
    D -- não --> E{"Já tem plantão<br/>neste dia?"}
    E -- sim --> X
    E -- não --> F{"DIA e fez a<br/>NOITE de ontem?"}
    F -- sim --> X
    F -- não --> G{"NOITE e tem o<br/>DIA de amanhã?"}
    G -- sim --> X
    G -- não --> OK["Pode assumir"]
    X --> L["Com impedimento<br/>(motivos listados)"]
    OK --> O["Ordena: livres → preferencial →<br/>menos plantões → nome"]
```

**Ordenação** (`candidatos()`): primeiro quem não tem impedimento; entre eles, quem tem o
turno como preferencial; depois quem tem menos plantões no período; por fim, ordem alfabética.

**Avisa, não bloqueia.** Escolher alguém com impedimento é permitido (uma troca combinada
entre colegas, por exemplo), mas a posição passa a contar como **conflito** na avaliação da
escala. Os conflitos aparecem para o ADM nos indicadores e na lista de alertas; na Revisão,
um aviso diz na hora quais regras o ajuste quebrou, com botão de desfazer.

**Mesmas regras em todo lugar.** O algoritmo que gera a escala, a Revisão do ADM e a troca
na escala confirmada usam a mesma função `impedimentos()`. Não existe uma regra na tela e
outra no servidor.

**Concorrência.** O editor guarda quem estava na posição quando foi aberto (`esperado`).
Se outra pessoa trocou a mesma posição nesse meio-tempo, o servidor responde **409** em
vez de sobrescrever, e a tela se atualiza.

**Rastro.** Toda troca na escala confirmada vira um evento `PLANTAO_ALTERADO` na
auditoria: "Qua 02/12 DIA · Enfermagem: EMMA → OLIVER", com quem fez, quando e o IP.
As outras telas abertas mostram o aviso e piscam a posição em até 3 segundos.

## 5. Mês atual e mês seguinte

A equipe vê sempre um par de escalas. `EstadoApp.classificar(hoje)` dá a cada escala
confirmada um papel:

1. **Mês atual** = a escala mais recente que **já começou** e **já tem uma sucessora** confirmada.
2. Se nenhuma atende (por exemplo, só há escalas futuras), a primeira que ainda não terminou.
3. **Mês seguinte** = a escala logo depois da atual.
4. Antes da atual: **anterior**; depois da seguinte: **futura**. Essas duas só o ADM vê.

Assim o par só avança quando **o mês vira e o ADM confirma a escala nova**:

| Situação | Mês atual | Mês seguinte | Só ADM |
|---|---|---|---|
| Novembro, com Dez e Jan confirmados | Dezembro | Janeiro | |
| Dezembro, Fevereiro já confirmado | Dezembro | Janeiro | Fevereiro (futura) |
| Virou janeiro, sem Fevereiro | Dezembro | Janeiro | |
| Virou janeiro **e** Fevereiro confirmado | Janeiro | Fevereiro | Dezembro (anterior) |

Confirmar de novo um período que se sobrepõe a outro substitui só aquela escala; ficam
guardadas as 12 mais recentes.

## 6. Perfis e acesso às informações

As permissões são aplicadas **no servidor**: o perfil Usuário só alcança as rotas da lista
`API_USUARIO` (as demais respondem 403), e as respostas para ele saem **sem** os dados da
coordenação (`escala_json(..., completo=False)`).

| Informação ou ação | ADM | Usuário |
|---|:---:|:---:|
| Ver a escala do mês atual e do mês seguinte (calendário ou lista, cores por profissional) | ✅ | ✅ |
| Trocar o profissional de um plantão (com impedimentos, auditado) | ✅ | ✅ |
| Ver quem pode assumir e quem tem impedimento, com o motivo | ✅ | ✅ |
| Ver o total de plantões de cada pessoa no editor de troca | ✅ | ❌ |
| Indicadores: cobertura, vagas, conflitos, equilíbrio, e os avisos dos turnos | ✅ | ❌ |
| Conflitos com as regras (lista e marcação nas posições) | ✅ | ❌ (o servidor não envia) |
| Distribuição de plantões por profissional | ✅ | ❌ (o servidor não envia) |
| Disponibilidade da equipe (férias, indisponível, preferencial) | ✅ | ❌ (o servidor não envia) |
| Escalas anteriores e futuras | ✅ | ❌ |
| Período, equipe, disponibilidade, gerar proposta, Revisão, confirmar | ✅ | ❌ |
| Baixar PDF, imprimir, exportar e importar | ✅ | ❌ |
| Auditoria (com IPs) e exportação em CSV | ✅ | ❌ |
| Previsão do tempo, instalar como app, atualização em tempo real | ✅ | ✅ |

<table><tr>
<td><img src="img/perfis-celular.jpg" alt="Mesma escala no celular: ADM à esquerda, usuário à direita"></td>
</tr><tr>
<td align="center"><sub>Celular: ADM (etapas, escala futura, botões, revisão em andamento) × Usuário (só as duas escalas)</sub></td>
</tr></table>

## 7. Fluxos (diagramas de sequência)

### Login

```mermaid
sequenceDiagram
    autonumber
    actor P as Pessoa
    participant T as Tela de login
    participant A as webapp.py
    participant U as CadastroUsuarios
    participant L as LimiteTentativas
    participant AU as Auditoria
    P->>T: nome + matrícula
    T->>A: POST /api/login (X-Requested-With: fetch)
    A->>L: bloqueado_por(nome, IP)?
    alt 5 erros em 15 min
        A->>AU: LOGIN_BLOQUEADO
        A-->>T: 429 "tente de novo em N min"
    else
        A->>U: autenticar (scrypt)
        alt incorreto
            A->>L: falhou
            A->>AU: LOGIN_FALHOU
            A-->>T: 401
        else correto
            A->>AU: LOGIN
            A-->>T: 200 + cookie de sessão (12 h)
            T->>P: abre a escala
        end
    end
```

### Troca de plantão com atualização em tempo real

```mermaid
sequenceDiagram
    autonumber
    actor M as Usuária (Emma)
    participant TM as Tela da Emma
    participant A as webapp.py
    participant AV as avaliacao.py
    participant R as Repositório (Postgres)
    participant AU as Auditoria
    participant TO as Outras telas abertas
    M->>TM: clica em "EMMA" (02/12 DIA, Enfermagem)
    TM->>A: GET /api/escala/candidatos?data&turno&cargo
    A->>AV: candidatos() → impedimentos() de cada um
    A-->>TM: lista (sem total de plantões para o usuário)
    TM->>M: "Podem assumir" × "Com impedimento" (motivos)
    M->>TM: escolhe OLIVER
    TM->>A: PATCH /api/escala {funcionario_id, esperado: EMMA}
    A->>R: BEGIN · trava · carrega · confere "esperado"
    alt alguém trocou antes
        A-->>TM: 409 (tela recarrega a posição)
    else
        A->>R: grava e COMMIT (versão + 1)
        A->>AU: PLANTAO_ALTERADO "Qua 02/12 DIA · Enfermagem: EMMA → OLIVER"
        A-->>TM: escala atualizada
    end
    loop a cada 10 s (3 s no modo arquivo)
        TO->>A: GET /api/versao
        A-->>TO: versão mudou + última troca (sem IP)
        TO->>TO: recarrega, avisa e pisca a posição
    end
```

## 8. API

Todas as rotas `/api/*` exigem sessão, exceto `/api/login`. Métodos que alteram dados
exigem o cabeçalho `X-Requested-With: fetch` (proteção contra CSRF).

| Método | Rota | Função | Perfil |
|---|---|---|---|
| `POST` | `/api/login` · `/api/logout` | Entra (nome + matrícula) ou sai | Público / todos |
| `GET` | `/api/eu` | Usuário logado e perfil | Todos |
| `GET` | `/api/versao` | Versão dos dados, última troca e versão da tela (tempo real) | Todos |
| `GET` | `/api/estado` | Período, equipe, rascunho e escalas visíveis com o papel de cada uma | Todos (filtrado) |
| `GET` | `/api/escala[?inicio=AAAA-MM-DD]` | Uma escala confirmada (sem `inicio`, a do mês atual) | Todos (filtrado) |
| `PATCH` | `/api/escala[?inicio=…]` | Troca profissionais (`esperado` contra sobrescrita), auditado | Todos |
| `GET` | `/api/escala/candidatos?data&turno&cargo` | Quem pode assumir e os impedimentos de cada um | Todos (ADM vê o total) |
| `POST` | `/api/escala` | Confirma o rascunho como escala final | ADM |
| `POST` | `/api/escala/editar` | Abre uma cópia da escala confirmada para revisão | ADM |
| `POST` | `/api/escala/importar` | Importa `.json` ou PDF gerado pelo sistema (multipart, `arquivo`) | ADM |
| `GET` | `/api/escala.pdf` · `/api/escala.json` | Baixa a escala em PDF ou JSON | ADM |
| `PUT` | `/api/periodo` | Define o período (até 92 dias) | ADM |
| `POST` | `/api/funcionarios` | Cadastra profissional | ADM |
| `PUT` / `DELETE` | `/api/funcionarios/<id>` | Edita ou remove | ADM |
| `PATCH` | `/api/funcionarios/<id>/disponibilidade` | Disponibilidade em lote | ADM |
| `GET` / `POST` / `DELETE` | `/api/rascunho` | Consulta, gera ou descarta a escala em revisão | ADM |
| `PATCH` | `/api/rascunho` | Ajusta posições em lote (`funcionario_id: null` = vago) | ADM |
| `GET` | `/api/rascunho/candidatos` | Candidatos de uma posição da revisão | ADM |
| `GET` | `/api/auditoria[?usuario&tipo]` · `/api/auditoria.csv` | Eventos (últimos 30 dias) | ADM |
| `GET` | `/saude` | Healthcheck | Público |
| `GET` | `/manifest.webmanifest` · `/sw.js` · `/offline.html` | Arquivos do PWA | Público |

Erros de negócio voltam como `{"erro": "mensagem"}` com 400, 401, 403, 404, 409 ou 429.

## 9. Segurança

| Medida | Onde |
|---|---|
| Matrícula guardada só como hash **scrypt** | `usuarios.py`, `usuarios_cli.py` |
| Bloqueio após 5 tentativas erradas em 15 min (por nome e por IP) | `LimiteTentativas` |
| Sessão assinada, 12 h, cookie `HttpOnly`, `Secure` atrás de HTTPS | `webapp.py`, `ESCALA_COOKIE_SEGURO` |
| CSRF: escrita exige `X-Requested-With: fetch` | `_autorizar()` |
| Permissão por perfil no servidor + filtro dos dados enviados | `API_USUARIO`, `escala_json(completo=…)` |
| Cabeçalhos `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `no-store` na API | `_cabecalhos()` |
| IP real atrás do proxy | `ESCALA_ATRAS_DE_PROXY` (ProxyFix); ligado sozinho na Vercel |
| Bloqueio de login e sessão valem para todas as cópias do app | Tabelas `escala_falhas` e `escala_config` |
| Credenciais do banco só em variável de ambiente | `DATABASE_URL` (injetada pela integração Neon) |
| Nada de dados reais ou segredos no pacote publicado | `.vercelignore` |
| Pod sem root, sistema de arquivos somente leitura, sem capabilities | `k8s/base/deployment.yaml` |
| Segredos fora do Git | `k8s/base/segredos/` no `.gitignore` |

## 10. Dados e persistência

O webapp conversa com quatro interfaces (repositório, cadastro de usuários, auditoria e
limite de tentativas). Cada uma tem duas implementações, escolhidas ao iniciar:

```mermaid
flowchart LR
    W["webapp.py"] --> Q{"DATABASE_URL?"}
    Q -- "sim (Vercel)" --> PG["escala/banco.py<br/>RepositorioPostgres · CadastroPostgres<br/>AuditoriaPostgres · LimitePostgres"]
    Q -- "não (Docker, K8s, desktop)" --> FS["repositorio.py · usuarios.py<br/>RepositorioJSON · CadastroUsuarios<br/>Auditoria · LimiteTentativas"]
    PG --> N[("Neon Postgres")]
    FS --> D[("/data<br/>arquivos JSON")]
```

| Dado | Postgres (produção) | Arquivo (Docker/K8s) | Regras |
|---|---|---|---|
| Equipe, disponibilidade, período, rascunho, até 12 escalas | `escala_estado` (1 linha, JSONB, `versao`) | `dados_escala.json` | Trava + transação no banco; gravação atômica (temporário + rename) no arquivo |
| Auditoria | `escala_auditoria` (índice por data) | `auditoria.jsonl` | Últimos **30 dias** (`ESCALA_AUDITORIA_DIAS`); limpeza no máximo 1×/hora |
| Usuários | `escala_usuarios` | `usuarios.json` (Secret no K8s) | Só o hash scrypt da matrícula |
| Tentativas de login | `escala_falhas` | memória | 5 erros em 15 min bloqueiam nome e IP |
| Chave da sessão | `escala_config` ou `ESCALA_SECRET_KEY` | `.secret_key` ou `ESCALA_SECRET_KEY` | Gerada uma vez |

**Por que um JSON só para a escala?** O domínio já é um agregado (`EstadoApp`) lido e gravado
inteiro, com poucos KB. Guardá-lo como um documento JSONB mantém o mesmo formato do
arquivo: a migração é um comando (`banco_cli.py enviar`) e o backup volta como os mesmos
arquivos (`banco_cli.py baixar`), que abrem no Docker sem conversão.

## 11. Frontend e PWA

- **SPA sem build**: HTML, CSS e JavaScript (ES modules) servidos pelo Flask. A página marca
  os arquivos com a versão (`?v=…`) e recarrega sozinha quando uma versão nova é publicada.
- **Responsivo**: até 760 px a escala abre em lista, com um cartão por dia; o topo deixa o
  símbolo do SAMU à esquerda e põe as informações numa coluna à direita.
- **Identidade visual**: logo SAMU 192 Tubarão (`img/samu-logo.png`) num cartão branco no login e
  no topo, nítida em qualquer tela; o selo do login e os ícones do PWA vêm do emblema (`img/samu-emblema.png`).
- **Previsão do tempo** (`js/clima.js`): Open-Meteo, sem chave, cidade fixa Tubarão-SC,
  atualização a cada 30 min; se falhar, o quadro some.
- **PWA**: `manifest.webmanifest` (ícones do SAMU, `display: standalone`) e `sw.js`:
  - `/api/*` **nunca** passa pelo cache;
  - páginas: sempre da rede; sem conexão, `offline.html`;
  - CSS, JS e imagens: da rede, com cópia para abrir rápido.

## 12. Testes

`pytest` com **80 testes**:

| Arquivo | O que cobre |
|---|---|
| `tests/test_algoritmo.py` | Regras de descanso, disponibilidade, equilíbrio e o algoritmo |
| `tests/test_webapp.py` | API, perfis, troca concorrente (409), mês atual/seguinte, importação, auditoria de 30 dias, PWA |
| `tests/test_banco.py` | **Todos** os testes do webapp de novo sobre um Postgres real, mais: duas cópias do app gravando ao mesmo tempo, sessão e bloqueio de login valendo entre cópias, limpeza da auditoria no banco |

```bash
python -m pytest -q                                   # 48 testes, modo arquivo
docker run -d --rm --name escala-pg-teste -e POSTGRES_PASSWORD=teste -e POSTGRES_DB=escala \
       -p 127.0.0.1:55432:5432 postgres:17-alpine
ESCALA_TESTE_BANCO=postgresql://postgres:teste@127.0.0.1:55432/escala python -m pytest -q   # 80
```

## 13. Implantação

| Modo | Onde | Endereço | Dados | Guia |
|---|---|---|---|---|
| **Produção** | Vercel (função Python, São Paulo) | **https://minhaescala192.vercel.app** | Neon Postgres | [docs/VERCEL.md](VERCEL.md) |
| Kubernetes no PC | Docker Desktop + Cloudflare Tunnel | `https://…trycloudflare.com` ou domínio próprio | Disco do cluster (PVC) | [k8s/README.md](../k8s/README.md) |
| Kubernetes na nuvem | Qualquer cluster + Traefik + Let's Encrypt | Domínio próprio | PVC | [k8s/README.md](../k8s/README.md) |
| Docker Compose | Qualquer PC | `http://localhost:8080` | Pasta `dados/` | [INSTALACAO.md](INSTALACAO.md) |

A produção começou no Kubernetes do próprio PC, com túnel da Cloudflare. A mudança para
Vercel + Neon tirou duas limitações: o sistema não depende mais de um PC ligado, e o
endereço não muda mais (antes, cada mudança quebrava o app instalado nos celulares).

