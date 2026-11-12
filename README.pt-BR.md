# Termometro

**Veja onde seus usuários sofrem — sem gravar ninguém.**

O Termometro mede frustração e esforço em cada tela do seu app web: rage clicks, cliques sem resposta, erros,
respostas lentas, formulários abandonados, quantos cliques cada gravação custa e o que ninguém nunca clica. Ele não grava sessão,
não coleta o que o usuário digita ou vê e roda no seu próprio servidor.

[English](README.md)

- **Um início que explica:** o período contra o anterior e a lista do que merece atenção — tela que piorou, falha
  nova, ação trabalhosa, botão muito usado e longe — cada item levando ao detalhe.
- **Uma nota por tela**, de 0 a 100, para saber por onde começar.
- **Onde irrita:** o elemento de cada rage click e qual requisição falhou depois de qual clique.
- **Falhas que o dev consegue corrigir:** agrupadas por mensagem, com o stack do código, navegadores, versões, tipo de
  tela, o que foi clicado logo antes e os passos das últimas sessões até ela — copiadas em Markdown para uma issue.
- **Esforço por ação:** "criar um pedido leva 12 cliques e 25 s" (mediana e p90).
- **Jornadas:** quantos cliques e telas até chegar a cada botão e ação, contra o quanto é usado (muito usado e longe =
  merece um lugar melhor), ações que costumam vir em sequência (aproximar ou juntar), de onde vêm e para onde vão em
  cada tela, e funis montados com telas, ações e botões.
- **Uso:** telas mais e menos usadas, e os elementos que ninguém clica.
- **Pessoas:** uso por papel, conta e usuário — só ids.
- **Mapa de calor** sobre o seu próprio app, aberto pelo painel.
- **Por versão:** o último deploy melhorou ou piorou? Tela a tela, ação a ação, e as falhas que só a versão nova
  tem — com mensagem no Slack ou no Google Chat quando piorou.
- **Cada falha datada:** em que versão começou e quando apareceu pela última vez, para saber se a correção funcionou.
- **Busca e links:** uma caixa acha telas, botões, erros, ações e ids (`/` foca nela); cada visão fica no endereço, dá
  para compartilhar e o voltar funciona. Toda tabela baixa em CSV.
- **Para IA:** o período inteiro num documento com as definições para ler os números (copiar em Markdown ou baixar
  JSON), e um servidor MCP para um assistente consultar sozinho.

## Por quê

Ferramentas de gravação de sessão capturam a tela. Isso é um problema quando a tela tem prontuário, processo,
dado bancário ou qualquer coisa sob a LGPD. O Termometro guarda só a forma da interação:

| Vai | Nunca vai |
|---|---|
| o sinal (rage click, clique sem resposta, erro…) | o que o usuário digitou ou o que um registro mostra |
| a rota como padrão (`/pedidos/:id`) | os ids reais da URL |
| um seletor curto (`button#salvar`) | nomes, e-mails |
| as palavras do próprio app num controle ("Novo usuário") e o nome da tela ("Usuários"), até 40 caracteres | texto de tabelas, listas de registros e campos, título da página de um registro, tudo dentro de `data-termometro-private` |
| os ids que você escolher mandar (conta, usuário, papel) | gravações, prints |
| se quiser, o nome do usuário (`identity.name`), guardado à parte e nunca no que uma IA lê; `"people_names": false` no projeto descarta | |
| família do navegador e do sistema (`Chrome 130 · macOS`), tipo de tela (celular, tablet, computador) | versões exatas, tamanho da tela, IP |
| onde o erro aconteceu no seu código (`loadRows @ /assets/index.js:1:4567`) | a query string ou os dados da página |

E-mails, uuids, números com 3 dígitos ou mais e texto entre aspas são limpos no navegador antes de sair.

## Subir o servidor

**Num servidor com domínio** (HTTPS incluído, pelo Caddy):

```bash
curl -O https://raw.githubusercontent.com/arianekevin/termometro/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/arianekevin/termometro/main/.env.example
# edite o .env: seu domínio, uma senha, seu projeto (gere a chave com o comando abaixo)
docker compose run --rm termometro python termometro.py new-key
docker compose up -d
```

Abra `https://seu-dominio`, entre, e o painel mostra o trecho para o seu app com a chave dele.

**Só para experimentar na sua máquina:**

```bash
docker run --rm -p 8080:8080 -e TERMOMETRO_PASSWORD=teste \
  -e TERMOMETRO_PROJECTS='[{"name":"local","key":"tk_local","origins":[]}]' \
  ghcr.io/arianekevin/termometro:latest
```

Depois abra http://localhost:8080 (senha `teste`). Para um projeto de verdade, gere a chave com
`docker run --rm ghcr.io/arianekevin/termometro python termometro.py new-key` e ponha o endereço do seu app
(por exemplo `http://localhost:5173` em desenvolvimento) nas `origins` do projeto: eventos de outro lugar são recusados.

A configuração completa (login com Google, quem pode entrar, retenção) está no [README em inglês](README.md#configuration).

**Aviso depois do deploy:** com `TERMOMETRO_WEBHOOK_URL` (um webhook de entrada do Slack ou do Google Chat; cada
projeto pode ter o seu `webhook`) e `TERMOMETRO_LANGUAGE=pt-BR`, o servidor confere de hora em hora se a última
versão piorou em relação à anterior e avisa uma vez sobre cada tela cuja nota subiu 15 ou mais (com 30 visitas em
cada versão) e sobre cada erro novo que já aconteceu 5 vezes.
Para entrar com Google: no Google Cloud Console, crie um cliente OAuth do tipo *Aplicativo da Web* com o URI de
redirecionamento `https://SEU-SERVIDOR/auth/google/callback` e defina `TERMOMETRO_GOOGLE_CLIENT_ID`,
`TERMOMETRO_GOOGLE_CLIENT_SECRET`, `TERMOMETRO_PUBLIC_URL` e `TERMOMETRO_ALLOWED_EMAILS` ou `_DOMAINS`.

## Deixar uma IA analisar

**Colar:** no Início, *Copiar análise (Markdown)* põe o período inteiro — números, falhas com stack e passos,
jornadas, esforço e as definições — na área de transferência. Cole num assistente e peça os problemas e as melhorias.
O mesmo documento está em `GET /api/report?project=…&days=…` (JSON, ou `&format=md`).

**MCP:** para um assistente consultar sozinho (Claude Code, Claude Desktop, Cursor…), dê ao servidor um token de API
(`TERMOMETRO_API_TOKENS`) e rode o servidor MCP, um arquivo só, sem dependências, que o seu Termometro serve:

```bash
docker compose run --rm termometro python termometro.py new-token   # ponha em TERMOMETRO_API_TOKENS
curl -O https://termometro.example.com/termometro_mcp.py
claude mcp add termometro -e TERMOMETRO_URL=https://termometro.example.com -e TERMOMETRO_TOKEN=tt_… \
  -e TERMOMETRO_PROJECT=meu-app -- python3 termometro_mcp.py
```

Ferramentas: `report` (comece por ela), `overview`, `search`, `frustration`, `failures`, `failure`, `session`,
`journeys`, `funnel`, `usage`, `effort`, `people`, `compare_versions` e `list_projects`. O token lê todos os projetos da
instância; guarde como senha.

## Colocar o coletor no seu app

```bash
npm install termometro
```

```ts
import { start } from 'termometro'

const termometro = start({
  key: 'tk_TROCAR',
  url: 'https://termometro.exemplo.com',
  version: import.meta.env.VITE_APP_VERSION,
  identity: () => usuario ? { account: usuario.contaId, user: usuario.id, role: usuario.papel } : null,
  pagesFromRouter: true,
  // slowMs: 3000,  // requisição mais lenta que isso é "resposta lenta"; 0 desliga
})

router.afterEach((to, _from, failure) => { if (!failure) termometro.page(to.matched[to.matched.length - 1]?.path ?? to.path) })
app.config.errorHandler = (err) => { termometro.error(err); console.error(err) }
```

Pedidos que não são a experiência do usuário podem ser declarados em `requests`. Cada item é `"METODO /caminho"` ou
`"/caminho"`; o caminho é comparado por prefixo depois que os ids viram `:id` (o item também pode usar `:id`), o método
não diferencia maiúsculas e o host não importa.

```ts
start({
  // ...
  requests: {
    ignore: ['POST /api/analytics'],              // nunca conta (`/cdn-cgi/` já é sempre ignorado)
    background: ['GET /api/notifications'],       // polling: nunca lento nem ação; uma falha por queda
    notActions: ['PUT /api/tickets/:id/presence'] // heartbeat: não é ação e não zera a contagem de cliques
  }
})
```

Sem bundler:

```html
<script src="https://termometro.exemplo.com/termometro.js" data-key="tk_TROCAR" async></script>
```

## Como a nota funciona

Cada sinal vale pontos: rage click 3, clique sem resposta 2, erro na tela 5, erro do servidor 5, pedido recusado 2,
formulário abandonado 2, voltou na hora 1, resposta lenta 1 (requisição de 3 s ou mais com a página na frente do
usuário, uma vez por endereço por visita). A nota da tela é a soma dos pontos dividida pelas visitas, vezes 20,
com teto 100. Até 19 está tranquilo, de 20 a 49 pede atenção, de 50 para cima é muita frustração.

## Recomeçar

Depois de um redesenho ou de uma correção grande, **Recomeçar daqui** (ao lado dos filtros) põe um marco no
projeto: dali em diante o painel, os alertas, o relatório e "falha nova" só contam o que veio depois. Nada é
apagado: **Ver tudo** mostra o que veio antes (`all=1` em qualquer leitura), **Desfazer** tira o marco, e o
dado antigo continua saindo pela retenção.

## Licença

[AGPL-3.0](LICENSE). Você pode usar, alterar e hospedar o Termometro livremente; se oferecer uma versão alterada
como serviço para outros, compartilha essas alterações sob a mesma licença.
