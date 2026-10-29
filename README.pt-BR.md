# Termometro

**Veja onde seus usuários sofrem — sem gravar ninguém.**

O Termometro mede frustração e esforço em cada tela do seu app web: rage clicks, cliques sem resposta, erros,
formulários abandonados, quantos cliques cada gravação custa e o que ninguém nunca clica. Ele não grava sessão,
não coleta o que o usuário digita ou vê e roda no seu próprio servidor.

[English](README.md)

- **Uma nota por tela**, de 0 a 100, para saber por onde começar.
- **Onde irrita:** o elemento de cada rage click e qual requisição falhou depois de qual clique.
- **Esforço por ação:** "criar um pedido leva 12 cliques e 25 s" (mediana e p90).
- **Uso:** telas mais e menos usadas, e os elementos que ninguém clica.
- **Pessoas:** uso por papel, conta e usuário — só ids.
- **Mapa de calor** sobre o seu próprio app, aberto pelo painel.
- **Por versão:** o último deploy melhorou ou piorou?

## Por quê

Ferramentas de gravação de sessão capturam a tela. Isso é um problema quando a tela tem prontuário, processo,
dado bancário ou qualquer coisa sob a LGPD. O Termometro guarda só a forma da interação:

| Vai | Nunca vai |
|---|---|
| o sinal (rage click, clique sem resposta, erro…) | texto da tela ou dos campos |
| a rota como padrão (`/pedidos/:id`) | os ids reais da URL |
| um seletor curto (`button#salvar`) | nomes, e-mails |
| os ids que você escolher mandar (conta, usuário, papel) | gravações, prints |

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
Para entrar com Google: no Google Cloud Console, crie um cliente OAuth do tipo *Aplicativo da Web* com o URI de
redirecionamento `https://SEU-SERVIDOR/auth/google/callback` e defina `TERMOMETRO_GOOGLE_CLIENT_ID`,
`TERMOMETRO_GOOGLE_CLIENT_SECRET`, `TERMOMETRO_PUBLIC_URL` e `TERMOMETRO_ALLOWED_EMAILS` ou `_DOMAINS`.

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
})

router.afterEach((to, _from, failure) => { if (!failure) termometro.page(to.matched[to.matched.length - 1]?.path ?? to.path) })
app.config.errorHandler = (err) => { termometro.error(err); console.error(err) }
```

Sem bundler:

```html
<script src="https://termometro.exemplo.com/termometro.js" data-key="tk_TROCAR" async></script>
```

## Como a nota funciona

Cada sinal vale pontos: rage click 3, clique sem resposta 2, erro na tela 5, erro do servidor 5, pedido recusado 2,
formulário abandonado 2, voltou na hora 1. A nota da tela é a soma dos pontos dividida pelas visitas, vezes 20,
com teto 100. Até 19 está tranquilo, de 20 a 49 pede atenção, de 50 para cima é muita frustração.

## Licença

[AGPL-3.0](LICENSE). Você pode usar, alterar e hospedar o Termometro livremente; se oferecer uma versão alterada
como serviço para outros, compartilha essas alterações sob a mesma licença.
