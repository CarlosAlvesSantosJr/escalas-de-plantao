# Como instalar a Escala de Plantão

Este guia é para usar o sistema no seu computador. Não precisa saber programar.

## Antes de começar (só na primeira vez)

1. Instale o **Docker Desktop**: https://www.docker.com/products/docker-desktop/
   Durante a instalação, aceite as opções padrão. No Windows, ele pode pedir para reiniciar o computador.
2. Abra o Docker Desktop uma vez e espere aparecer "Engine running" (pode levar 1 ou 2 minutos).
3. Copie a pasta `escalas-de-plantao` inteira para o seu computador (por exemplo, para "Documentos").
   Quem usa Git pode baixar direto do GitHub:
   `git clone https://github.com/CarlosAlvesSantosJr/escalas-de-plantao.git`

## Para abrir o sistema

**Windows:** dê dois cliques no arquivo **`iniciar.bat`**.
**Mac:** abra o Terminal na pasta e digite `./iniciar.sh`.

Na primeira vez demora alguns minutos (ele monta o sistema). Nas próximas, leva segundos.
O navegador abre sozinho em **http://localhost:8080**. Se não abrir, digite esse endereço no navegador.

Pode deixar o navegador aberto e usar à vontade. O sistema continua funcionando mesmo depois de reiniciar o computador, desde que o Docker Desktop esteja aberto.

## Para desligar

Dê dois cliques em **`parar.bat`**. Nada se perde.

## Onde ficam os dados

Tudo fica no arquivo `dados/dados_escala.json`, dentro da pasta do sistema: a equipe, a disponibilidade, a revisão em andamento e a escala final confirmada.
**Para fazer backup**, copie a pasta `dados` para um pendrive ou para a nuvem.

## Usando no dia a dia

1. **Período:** escolha o mês da escala.
2. **Equipe:** cadastre profissionais de enfermagem e socorristas.
3. **Disponibilidade:** escolha o pincel (Indisponível, Preferencial, Férias) e clique nos turnos de cada pessoa. Dá para arrastar o mouse para marcar vários de uma vez. Clicar na data marca o dia todo.
4. **Revisão:** o sistema monta uma proposta sozinho. Confira e, se precisar, **clique em qualquer nome** para trocar a pessoa ou deixar a vaga em aberto. A janela mostra quem está livre e por que os outros não estão (férias, já tem plantão no dia, saindo da noite...). Errou? Use **Desfazer** (ou Ctrl+Z). Quando estiver tudo certo, clique em **Confirmar escala**.
5. **Escala:** é a versão final. Use **Baixar PDF** para mandar para a equipe ou **Imprimir**. Cada pessoa tem uma cor; clique num nome da legenda para destacar os plantões dela. Para trocar alguém num plantão, clique no nome direto na escala. Para uma revisão maior, com calma, use **Revisar**.

**Entrar no sistema:** cada pessoa usa o próprio **nome e matrícula**. A coordenação (ADM) vê e faz tudo. Os demais usuários veem só a escala confirmada e podem trocar o profissional de um plantão; conflitos com as regras e a distribuição por profissional aparecem só para o ADM. Toda troca fica registrada em **Auditoria**, que só o ADM acessa. Para cadastrar quem pode entrar, veja "Criar os usuários" no [README](../README.md#-acesso-perfis-e-auditoria).

O PDF traz uma linha por dia, com o turno DIA de um lado e a NOITE do outro (colunas Enfermagem e Socorrista). O resumo de plantões por pessoa fica só no sistema.

## Levar a escala para outro computador

1. No computador de origem, na etapa **Escala**, clique em **Baixar PDF** (ou em **Exportar**, que gera um arquivo `.json`).
2. No outro computador, abra o sistema, vá em **Revisão** ou **Escala** e clique em **Importar**. Escolha o PDF ou o `.json`.
3. A escala abre na Revisão. Quem ainda não estiver cadastrado entra na equipe automaticamente. Confira e clique em **Confirmar escala**.

Só funcionam PDFs baixados desta versão do sistema em diante.

## Se algo der errado

| O que aparece | O que fazer |
|---|---|
| "O Docker Desktop não está aberto" | Abra o Docker Desktop, espere ficar verde e rode o `iniciar.bat` de novo. |
| A página não abre | Espere 30 segundos e atualize o navegador (F5). |
| "Este PDF não traz os dados da escala" | O PDF é de uma versão antiga. Gere um PDF novo no computador de origem e importe de novo. |
| Outra mensagem de erro | Tire um print da janela preta e envie para o Carlos. |
