# Rodar no Kubernetes (acesso externo)

Com este guia, a escala fica acessível pela internet num endereço como
`https://escala.seudominio.com.br`, com HTTPS e login por nome + matrícula.

```
Internet ──HTTPS──▶ Ingress (Traefik + Let's Encrypt) ──▶ Service ──▶ Pod (1 réplica)
                                                                     ├─ /data  ← disco (PVC): escala + auditoria
                                                                     └─ /etc/escala ← Secret: usuários (hash)
```

**Sempre 1 réplica.** Os dados ficam num arquivo JSON com trava em memória, e
uma segunda réplica corromperia a escala. Para uma equipe deste tamanho, uma
réplica é suficiente. A estratégia `Recreate` garante isso também durante as
atualizações (há alguns segundos de indisponibilidade).

Há dois modos de implantação:

| Pasta | Onde roda | Endereço |
|---|---|---|
| `k8s/tunel/` | Kubernetes do Docker Desktop, **no próprio PC** | `https://xxxx.trycloudflare.com` (muda se o túnel reiniciar) |
| `k8s/tunel-fixo/` | Kubernetes do Docker Desktop, **no próprio PC** | `https://escala.seudominio.com.br` (**fixo**, túnel nomeado) |
| `k8s/` | Nuvem ou VPS, no ar 24 h | Seu domínio, com HTTPS do Let's Encrypt |

## Modo rápido: no próprio PC com Cloudflare Tunnel

1. No Docker Desktop: **Settings → Kubernetes → Enable Kubernetes → Apply & restart**.
2. Crie os segredos (passo 3 abaixo), se ainda não existirem.
3. Suba:

```bash
kubectl config use-context docker-desktop
docker build -t escala-plantao:1.4.1 .        # a mesma tag de newTag em tunel/kustomization.yaml
kubectl apply -k k8s/tunel/
kubectl -n escala-plantao logs deploy/cloudflared | grep trycloudflare   # endereço público
```

**Para atualizar a versão, use sempre uma tag nova** (1.4.2, 1.5.0…). Se você
reconstruir a imagem com a mesma tag, o nó do Kubernetes continua usando a
cópia antiga que já guardou.

```bash
docker build -t escala-plantao:1.5.0 .
# troque newTag para "1.5.0" em k8s/tunel/kustomization.yaml
kubectl apply -k k8s/tunel/
```

Só o pod da aplicação é recriado. O túnel continua de pé, e o endereço
público não muda.

**App instalável (PWA):** pelo endereço `https://` do túnel (ou do seu
domínio), a escala pode ser instalada no celular com "Adicionar à tela
inicial". Sem HTTPS o navegador não oferece a instalação.

**Auditoria:** guarda os últimos 30 dias (variável `ESCALA_AUDITORIA_DIAS` em
`base/deployment.yaml`); eventos mais antigos são apagados automaticamente.

**Limitações:** o sistema só fica no ar com o PC ligado e o Docker Desktop
aberto. O endereço muda se o pod `cloudflared` reiniciar; para um endereço
fixo, use o túnel nomeado (próxima seção). Os dados ficam no disco do Kubernetes do Docker
Desktop, e um "Reset Kubernetes cluster" os apaga, então faça backup
(seção "Dia a dia").

## Endereço fixo com túnel nomeado (recomendado)

O endereço `trycloudflare.com` muda sempre que o túnel reinicia. Quando isso
acontece, o app instalado no celular da equipe deixa de abrir. Com um **túnel
nomeado**, o endereço fica fixo (ex.: `https://escala.seudominio.com.br`) e
sobrevive a reinícios do pod, do Docker e do PC.

**Pré-requisitos:** uma conta gratuita na Cloudflare e **um domínio** usando os
servidores DNS da Cloudflare. O túnel é gratuito, mas a Cloudflare não dá
subdomínio grátis para túnel nomeado. Um `.com.br` no registro.br custa cerca
de R$ 40/ano. Também dá para comprar o domínio direto pela Cloudflare
(Domain Registration), a preço de custo.

### 1. Domínio na Cloudflare (uma vez)

1. Crie a conta em https://dash.cloudflare.com/sign-up (plano Free).
2. **Add a domain** → digite o domínio → plano **Free**.
3. A Cloudflare mostra dois *nameservers* (ex.: `ana.ns.cloudflare.com`).
   No registro.br: **Domínio → DNS → Alterar servidores DNS** e cole os dois.
   A ativação leva de minutos a algumas horas; a Cloudflare avisa por e-mail.

### 2. Criar o túnel (uma vez)

1. No painel: **Zero Trust → Networks → Tunnels → Create a tunnel**.
2. Tipo **Cloudflared**, nome `escala-plantao` → **Save tunnel**.
3. Na tela de instalação, escolha **Docker** e copie só o token
   (o texto longo depois de `--token`, começando por `eyJ`).
4. **Next** → aba **Public Hostname** → **Add a public hostname**:

| Campo | Valor |
|---|---|
| Subdomain | `escala` |
| Domain | seu domínio |
| Service → Type | `HTTP` |
| Service → URL | `escala.escala-plantao.svc.cluster.local:80` |

5. **Save hostname**. A Cloudflare cria sozinha o registro DNS e o certificado HTTPS.

### 3. Subir no Kubernetes

Guarde o token num arquivo fora do Git (a pasta está no `.gitignore`):

```bash
mkdir -p k8s/tunel-fixo/segredos
echo "TUNNEL_TOKEN=eyJhIjoi...cole-o-token-aqui" > k8s/tunel-fixo/segredos/tunel.env

kubectl config use-context docker-desktop
docker build -t escala-plantao:1.4.1 .        # a mesma tag de newTag em tunel-fixo/kustomization.yaml
kubectl apply -k k8s/tunel-fixo/
kubectl -n escala-plantao rollout status deploy/cloudflared
```

O `tunel-fixo` **substitui** o túnel rápido (o Deployment tem o mesmo nome),
então não rode os dois. No painel da Cloudflare, o túnel deve aparecer como
**HEALTHY**. Abra `https://escala.seudominio.com.br`.

Daqui para frente, **use sempre `k8s/tunel-fixo/`** nas atualizações de versão
(troque `newTag` nele). Para voltar ao endereço temporário, rode
`kubectl apply -k k8s/tunel/`.

**Na troca, a equipe reinstala o app uma última vez:** o app instalado está
preso ao endereço antigo. Cada pessoa abre o endereço novo, faz login e
"Adicionar à tela inicial". Depois disso, o endereço não muda mais.

**Se o token vazar:** no painel do túnel, **Refresh token** (o antigo para de
valer), atualize o `tunel.env` e rode `kubectl apply -k k8s/tunel-fixo/` de novo.

**Diagnóstico:** `kubectl -n escala-plantao logs deploy/cloudflared` deve mostrar
`Registered tunnel connection`. O pod só fica *Ready* quando está conectado à
Cloudflare. Se a conexão cair por cerca de 2 minutos, o Kubernetes o reinicia.

## Modo nuvem/VPS

## O que você precisa

| Item | Exemplos |
|---|---|
| Um cluster Kubernetes | k3s numa VPS barata, DigitalOcean (DOKS), GKE, AKS, EKS |
| Ingress Controller | [Traefik](https://doc.traefik.io/traefik/getting-started/install-traefik/). O k3s já vem com ele |
| [cert-manager](https://cert-manager.io/docs/installation/) | Emite o certificado HTTPS gratuito |
| Um domínio | Com um registro DNS `A` apontando para o IP externo do Ingress |
| Um registry de imagens | GitHub Container Registry (ghcr.io), Docker Hub |

## Passo a passo

### 1. Instalar Traefik e cert-manager (uma vez por cluster)

No **k3s** o Traefik já vem instalado. Em outros clusters:

```bash
helm repo add traefik https://traefik.github.io/charts
helm install traefik traefik/traefik -n traefik --create-namespace
```

Depois o cert-manager (veja a versão atual em https://cert-manager.io/docs/installation/):

```bash
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set crds.enabled=true
```

Edite o e-mail em `cluster-issuer.yaml` e aplique:

```bash
kubectl apply -f k8s/cluster-issuer.yaml
```

> **Outro Ingress Controller?** Troque o `ingressClassName` em `ingress.yaml`
> e `cluster-issuer.yaml`, remova `middleware.yaml` do `kustomization.yaml` e a
> anotação `traefik.ingress...` do `ingress.yaml`. O ingress-nginx foi
> descontinuado pela comunidade Kubernetes em 2026, então prefira o Traefik.

### 2. Publicar a imagem

```bash
docker build -t ghcr.io/SEU-USUARIO/escala-plantao:1.0.0 .
docker login ghcr.io          # usuário do GitHub + token com permissão write:packages
docker push ghcr.io/SEU-USUARIO/escala-plantao:1.0.0
```

Ajuste `newName` e `newTag` em `kustomization.yaml`. Se o pacote no GitHub for
privado, crie um `imagePullSecret` ou torne o pacote público. A imagem não
contém dados nem senhas.

### 3. Segredos: usuários e chave de sessão

Os segredos ficam em `k8s/base/segredos/`, uma pasta que **não vai para o Git**:

| Arquivo | Conteúdo |
|---|---|
| `base/segredos/usuarios.json` | Usuários com a matrícula em **hash** (gerado pelo `usuarios_cli.py`) |
| `base/segredos/sessao.env` | `ESCALA_SECRET_KEY=<64 caracteres aleatórios>` (assina os cookies de sessão) |

Para criar do zero:

```bash
# lista temporária: NOME;MATRICULA;PAPEL  (PAPEL = ADMIN ou vazio)
python usuarios_cli.py gerar lista.csv k8s/base/segredos/usuarios.json
rm lista.csv     # não deixe as matrículas em texto no disco

python -c "import secrets; print('ESCALA_SECRET_KEY=' + secrets.token_hex(32))" > k8s/base/segredos/sessao.env
```

### 4. Domínio

Troque `escala.SEU-DOMINIO.com.br` em `ingress.yaml` (2 lugares) e crie o
registro DNS apontando para o IP do Ingress:

```bash
kubectl get svc -A | grep -i traefik      # coluna EXTERNAL-IP (no k3s: o IP do servidor)
```

### 5. Subir

```bash
kubectl apply -k k8s/
kubectl -n escala-plantao get pods,ingress,certificate
```

Em 1–2 minutos o certificado fica `READY=True` e o sistema responde em
`https://escala.SEU-DOMINIO.com.br`.

### 6. Levar a escala atual para o cluster (opcional)

```bash
POD=$(kubectl -n escala-plantao get pod -l app.kubernetes.io/name=escala -o name | cut -d/ -f2)
kubectl -n escala-plantao cp dados_escala.json $POD:/data/dados_escala.json
```

## Dia a dia

**Atualizar a versão:** gere uma imagem com nova tag, troque `newTag` e rode
`kubectl apply -k k8s/`.

**Adicionar, trocar a matrícula ou desativar alguém:**

```bash
python usuarios_cli.py adicionar k8s/base/segredos/usuarios.json "Nome" [--admin]
python usuarios_cli.py desativar k8s/base/segredos/usuarios.json "Nome"
kubectl apply -k k8s/
```

Quem for desativado perde o acesso na próxima requisição, mesmo que esteja com
a sessão aberta.

**Backup** dos dados e da auditoria:

```bash
kubectl -n escala-plantao cp $POD:/data ./backup-$(date +%F)
```

**Ver a auditoria fora do sistema:** o arquivo `/data/auditoria.jsonl` tem um
evento por linha. Na tela, o ADM usa **Auditoria → Exportar CSV**.

## Segurança: o que já está feito

- HTTPS obrigatório. O cookie de sessão é `Secure`, `HttpOnly` e `SameSite=Lax`, e expira em 12 h.
- As matrículas ficam em hash (scrypt) num Secret, fora da imagem e do Git.
- Depois de 5 tentativas erradas, o login fica bloqueado por 15 minutos para aquele nome ou IP. As tentativas aparecem na auditoria.
- As permissões são checadas no servidor. O perfil USUARIO só consegue ler a escala e trocar profissionais nos plantões dela.
- Proteção contra CSRF: as requisições que gravam exigem um cabeçalho que outros sites não conseguem enviar.
- O pod roda sem root, com sistema de arquivos somente leitura e sem capabilities.

**Atenção:** a matrícula é curta e pode ser conhecida pelos colegas. Ela
identifica quem fez cada alteração, mas não é uma senha forte. Se o sistema
for ficar aberto na internet por muito tempo, considere colocar o endereço
atrás de uma VPN (Tailscale, WireGuard) ou do Cloudflare Access.
