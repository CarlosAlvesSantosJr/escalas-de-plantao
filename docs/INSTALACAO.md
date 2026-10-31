# Como instalar a Escala de Plantão

Este guia é para usar o sistema no seu computador. Não precisa saber programar.

## Antes de começar (só na primeira vez)

1. Instale o **Docker Desktop**: https://www.docker.com/products/docker-desktop/
   Durante a instalação, aceite as opções padrão. No Windows, ele pode pedir para reiniciar o computador.
2. Abra o Docker Desktop uma vez e espere aparecer "Engine running" (pode levar 1 ou 2 minutos).
3. Copie a pasta `escalas-de-plantao` inteira para o seu computador (por exemplo, para "Documentos").

## Para abrir o sistema

**Windows:** dê dois cliques no arquivo **`iniciar.bat`**.
**Mac:** abra o Terminal na pasta e digite `./iniciar.sh`.

Na primeira vez demora alguns minutos (ele monta o sistema). Nas próximas, leva segundos.
O navegador abre sozinho em **http://localhost:8080**. Se não abrir, digite esse endereço no navegador.

Pode deixar o navegador aberto e usar à vontade. O sistema continua funcionando mesmo depois de reiniciar o computador, desde que o Docker Desktop esteja aberto.

## Para desligar

Dê dois cliques em **`parar.bat`**. Nada se perde.

## Onde ficam os dados

Tudo o que você cadastra fica no arquivo `dados/dados_escala.json`, dentro da pasta do sistema.
**Para fazer backup**, copie a pasta `dados` para um pendrive ou para a nuvem.

## Usando no dia a dia

1. **Período:** escolha o mês da escala.
2. **Equipe:** cadastre enfermeiros(as) e motoristas.
3. **Disponibilidade:** escolha o pincel (Indisponível, Preferencial, Férias) e clique nos turnos de cada pessoa. Dá para arrastar o mouse para marcar vários de uma vez. Clicar na data marca o dia todo.
4. **Escala:** clique em **Gerar escala**. Se aparecer alguma vaga, o sistema diz o motivo. Use o botão **PDF** para baixar e mandar para a equipe.

## Se algo der errado

| O que aparece | O que fazer |
|---|---|
| "O Docker Desktop não está aberto" | Abra o Docker Desktop, espere ficar verde e rode o `iniciar.bat` de novo. |
| A página não abre | Espere 30 segundos e atualize o navegador (F5). |
| Outra mensagem de erro | Tire um print da janela preta e envie para o Carlos. |
