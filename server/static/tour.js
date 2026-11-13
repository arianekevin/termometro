// Termometro: a guided tour of the screen in view, opened on demand from the "Tour" button at the top. It goes from
// point to point on the real screen: what each part shows, a tip for using it and a practical example of what to take
// from it in day-to-day work. Loaded by the panel after its own script; reads its `PT` and `state`. Nothing is saved.
//
// A step points at:
//   - `h: 'key'`: the section holding the "?" help button with that key (what most panel sections have);
//   - `s: 'css'`: the first visible element matching it (`up: n` takes its n-th parent);
//   - nothing: a card in the middle of the screen (the tour's opening).
// A step whose element is not on screen (an empty list, a section the data does not show) is left out.
(() => {
  const P = (pt, en) => (PT ? pt : en)
  const UI = () => ({
    open: P('Tour', 'Tour'), openTip: P('Tour desta tela: o que dá para fazer aqui, com dicas e exemplos', 'Tour of this screen: what you can do here, with tips and examples'),
    next: P('Próximo', 'Next'), back: P('Voltar', 'Back'), done: P('Concluir', 'Done'), close: P('Fechar o tour', 'Close the tour'),
    of: (i, n) => P(`${i} de ${n}`, `${i} of ${n}`), tip: P('Dica', 'Tip'), ex: P('No dia a dia', 'Day to day'),
    none: P('Esta tela ainda não tem o que mostrar no tour: escolha um período com dados.', 'This screen has nothing to show in the tour yet: pick a period with data.'),
  })

  // ---------- the steps, per tab: [title, body, tip, example] in each language ----------
  const TOURS = {
    overview: [
      { pt: ['Início: o que pede atenção agora', 'O resumo do período escolhido contra o período anterior de mesmo tamanho: se algo piorou, o que fazer primeiro e o que você está acompanhando.', 'Troque o período no topo (24 horas, 7, 30 ou 90 dias): tudo nesta tela acompanha.', 'Segunda de manhã, antes da reunião do time: abra o Início em 7 dias e leve os três primeiros itens da lista.'],
        en: ['Overview: what needs attention now', 'The chosen period against the previous one of the same length: whether something got worse, what to do first and what you are following.', 'Change the period at the top (24 hours, 7, 30 or 90 days): everything here follows.', 'Monday morning, before the team meeting: open the Overview on 7 days and bring the first three items of the list.'] },
      { s: 'section.verdict', pt: ['O veredito', 'Uma frase com quantas telas e falhas precisam de você no período escolhido. Verde quando nada piorou.', '"Ver a lista" desce direto para o que fazer.', 'Mande o print do veredito no canal do time depois de cada deploy: todo mundo vê na hora se a versão foi bem.'],
        en: ['The verdict', 'One sentence with how many screens and failures need you this period. Green when nothing got worse.', '"See the list" jumps straight to what to do.', 'Post a screenshot of the verdict in the team channel after each deploy: everyone sees at once whether the release went well.'] },
      { s: 'section.numbers', pt: ['Os números do período', 'Frustração geral, visitas, pessoas e falhas, cada um com a variação contra o período anterior e um mini gráfico por dia.', 'A seta só ganha cor quando a mudança passa do acaso; cinza é oscilação normal.', 'Falhas subiram muito de uma semana para outra? Vá em Versões e veja se começou junto com um deploy.'],
        en: ['The period\'s numbers', 'Overall frustration, visits, people and failures, each with its change against the previous period and a small chart per day.', 'An arrow only gets colour when the change is beyond chance; grey is normal swing.', 'Failures jumped from one week to the next? Go to Versions and check whether it started with a deploy.'] },
      { h: 'todo', pt: ['Para fazer, por impacto', 'Bugs, irritação e sugestões, ordenados por gravidade vezes alcance: quantas sessões e pessoas cada item atinge. "Ver evidência" abre o detalhe.', '"Ver por tipo" separa em colunas; "+N nesta tela" junta os itens da mesma tela.', 'Escolha o primeiro item, clique "Copiar como demanda" e cole no Jira ou YouTrack: já vai com o problema, quem é afetado no período, a sugestão, um critério de aceite e o link para a evidência.'],
        en: ['To do, by impact', 'Bugs, irritation and suggestions, ranked by severity times reach: how many sessions and people each item hits. "See evidence" opens the detail.', '"By type" splits it into columns; "+N on this screen" groups items of the same screen.', 'Pick the first item, click "Copy as a ticket" and paste it in Jira or YouTrack: it carries the problem, who is hit in the period, the suggestion, an acceptance criterion and the link to the evidence.'] },
      { h: 'follow', pt: ['Acompanhando', 'Decidiu corrigir algo? "Acompanhar" na linha guarda o número de hoje como base e mede só o que veio depois: Melhorou, Igual ou Piorou.', 'Depois de copiar uma demanda, o aviso oferece "Acompanhar também".', 'Corrigiu o botão Salvar na versão nova: uma semana depois, este cartão diz se a irritação caiu de verdade, sem planilha.'],
        en: ['Following', 'Decided to fix something? "Follow" on the row keeps today\'s number as the baseline and measures only what came after: Better, Same or Worse.', 'After copying a ticket, the notice offers "Follow too".', 'You fixed the Save button in the new version: a week later this card tells whether the irritation really dropped, no spreadsheet needed.'] },
      { h: 'release', pt: ['A última versão', 'A versão mais nova contra a anterior: frustração por visita, falhas por 100 sessões e as telas que mais pioraram.', '"Criar marco nesta versão" faz o painel contar só a partir dela.', 'No dia seguinte ao deploy, confira aqui se alguma tela piorou antes de o primeiro cliente reclamar.'],
        en: ['The latest version', 'The newest version against the previous one: frustration per visit, failures per 100 sessions and the screens that got worse.', '"Create a mark at this version" makes the dashboard count only from it.', 'The day after a deploy, check here whether any screen got worse before the first customer complains.'] },
      { h: 'kinds', pt: ['De onde vem a frustração', 'A frustração separada por tipo: irritação, clique sem efeito, erros, lentidão e desistência. O esforço fica à parte.', 'O "por quê" da irritação diz se as pessoas esperavam resposta ou se nada aconteceu.', 'Se Lentidão é o que mais cresce, o assunto é desempenho do servidor, não o desenho da tela.'],
        en: ['Where frustration comes from', 'Frustration split by kind: irritation, clicks with no effect, errors, slowness and giving up. Effort stays apart.', 'The irritation\'s "why" says whether people were waiting for an answer or nothing happened.', 'If Slowness grows the most, the topic is server performance, not the screen\'s design.'] },
      { s: '#byday', pt: ['Dia a dia', 'A frustração de cada dia e as telas dia a dia; o risco vertical marca quando entrou uma versão.', 'No celular fica fechado: toque em "Ver por dia".', 'Um pico num dia só costuma ser incidente; uma faixa que escurece a partir de uma versão é regressão.'],
        en: ['Day by day', 'Each day\'s frustration and the screens day by day; the vertical line marks when a version went in.', 'On a phone it starts closed: tap "By day".', 'A spike on a single day is usually an incident; a row that darkens from a version on is a regression.'] },
      { s: '#marks-open', up: 2, pt: ['Período, conta, filtros e marcos', 'No topo: o período, a conta, os Filtros (versão, papel, feature) e os Marcos (contar só a partir de uma data). Tudo fica no endereço da página.', 'Em ⋯ ficam o tema, o tamanho do texto, as cores e o idioma.', 'Copie o endereço e mande para o time: quem abrir vê exatamente o mesmo recorte.'],
        en: ['Period, account, filters and marks', 'At the top: the period, the account, Filters (version, role, feature) and Marks (count only from a date). Everything lives in the page address.', 'Under ⋯: theme, text size, colours and language.', 'Copy the address and send it to the team: whoever opens it sees exactly the same cut.'] },
    ],
    frustration: [
      { pt: ['Frustração: por onde começar', 'Cada tela ganha um nível de 0 a 100, a partir dos sinais de irritação, erro, lentidão e desistência dividido pelas visitas. Quanto maior, pior.', 'Até 19 é baixa, de 20 a 49 moderada, de 50 para cima alta.', 'Planejando a próxima sprint: as duas telas do topo são as que mais devolvem satisfação por hora de trabalho.'],
        en: ['Frustration: where to start', 'Each screen gets a level from 0 to 100, from the signals of irritation, error, slowness and giving up divided by visits. The higher, the worse.', 'Up to 19 is low, 20 to 49 moderate, 50 and up high.', 'Planning the next sprint: the top two screens give back the most satisfaction per hour of work.'] },
      { s: 'section.numbers', pt: ['O geral e a pior tela', 'A frustração de todo o app, as visitas e a tela mais frustrante do período.', 'Compare com o período anterior pela seta.', 'Leve o número geral para o relatório do mês: é um indicador de qualidade da experiência que não depende de pesquisa.'],
        en: ['The overall and the worst screen', 'Frustration across the app, visits and the most frustrating screen of the period.', 'Compare with the previous period by the arrow.', 'Take the overall number to the monthly report: an experience quality indicator that needs no survey.'] },
      { h: 'screensByFrustration', pt: ['Telas, da mais frustrante para a menos', 'Cada tela com o nível, as visitas e o que mais pesa. Clique numa tela para ver onde ela irrita.', 'Clique numa tela: abaixo aparece Onde irrita, com o elemento de cada clique repetido e o porquê. Olhe as visitas junto: tela muito frustrante e pouco visitada pode esperar.', '"Usuários: 64 em 220 visitas, pesa rage click" é um problema concreto de uma tela que muita gente usa: comece por ela.'],
        en: ['Screens, most frustrating first', 'Each screen with its level, visits and what weighs most. Click a screen to see where it irritates.', 'Click a screen: Where it irritates opens below, with the element behind each repeated click and why. Look at visits too: a very frustrating screen nobody visits can wait.', '"Users: 64 over 220 visits, mostly rage clicks" is a concrete problem on a screen many people use: start there.'] },
      { h: 'whereIrritates', pt: ['Onde irrita', 'O elemento de cada clique repetido de raiva e o motivo provável: esperando resposta, nada aconteceu, erro, não é clicável.', 'O Mapa mostra o mesmo em cima do desenho da tela.', '"Convidar: 44% esperando resposta" não pede redesenho: pede travar o botão enquanto carrega e acelerar a chamada.'],
        en: ['Where it irritates', 'The element behind each angry repeated click and the likely reason: waiting for an answer, nothing happened, an error, not clickable.', 'The Map shows the same over the screen\'s drawing.', '"Invite: 44% waiting for an answer" does not call for a redesign: lock the button while it loads and speed up the request.'] },
      { h: 'byVersion', pt: ['Por versão', 'A frustração do app inteiro em cada versão: em qual delas piorou ou melhorou.', 'Para ver tela a tela, use a aba Versões.', 'A frustração subiu de 18 para 37 entre a 1.5 e a 1.6: é por essa versão que a investigação começa.'],
        en: ['By version', 'The whole app\'s frustration in each version: in which one it got worse or better.', 'For screen by screen, use the Versions tab.', 'Frustration went from 18 to 37 between 1.5 and 1.6: that version is where the investigation starts.'] },
    ],
    failures: [
      { pt: ['Falhas: o que quebra', 'Erros do navegador e do servidor, agrupados pela mensagem, com quantas sessões e pessoas cada um atinge.', 'A etiqueta "nova" marca falha que não existia antes deste período.', 'Depois de um deploy, procure a etiqueta "nova" no alto da lista: é candidata a hotfix no mesmo dia.'],
        en: ['Failures: what breaks', 'Browser and server errors, grouped by message, with how many sessions and people each one hits.', 'The "new" tag marks a failure that did not exist before this period.', 'After a deploy, look for the "new" tag near the top of the list: a same-day hotfix candidate.'] },
      { h: 'failures', pt: ['A lista', 'Sessões, pessoas, vezes, a versão em que começou, a última vez que apareceu e o gráfico por dia.', 'A última vez diz se a correção funcionou: se parou de aparecer depois do deploy, resolveu.', 'A lista já vem pelo que mais pesa: sessões atingidas vezes a gravidade. Uma falha que se repete numa pessoa só pesa menos que uma que pega muita gente.'],
        en: ['The list', 'Sessions, people, times, the version where it started, the last time it showed and the chart per day.', 'The last time tells whether the fix worked: if it stopped after the deploy, it is solved.', 'The list already comes heaviest first: sessions hit times severity. A failure that repeats for one person weighs less than one that hits many.'] },
      { s: 'td.fcell', pt: ['O detalhe de uma falha', 'Clique numa falha: os passos das últimas sessões até ela, as contas atingidas e, quando o coletor manda, o stack do código, os navegadores e o tipo de tela.', '"Copiar como demanda" leva o stack e os passos em Markdown; "Acompanhar" mostra se sumiu depois da correção.', 'O dev recebe a issue já com o caminho para reproduzir: "abriu Usuários, clicou Convidar, POST /api/convites 500".'],
        en: ['A failure\'s detail', 'Click a failure: the steps of the latest sessions up to it, the accounts hit and, when the collector sends them, the code stack, browsers and kind of screen.', '"Copy as a ticket" takes the stack and steps in Markdown; "Follow" shows whether it went away after the fix.', 'The developer gets the issue with the way to reproduce it: "opened Users, clicked Invite, POST /api/invites 500".'] },
    ],
    actions: [
      { pt: ['Ações: quanto custa cada tarefa', 'Cada gravação do app (um POST, um PUT) com quantos cliques e quanto tempo as pessoas levam até ela.', 'Só conta clique de gente: clique feito por código não entra.', 'Antes de discutir "a tela está confusa", meça: "criar ticket leva 12 cliques e 25 s" é argumento.'],
        en: ['Actions: what each task costs', 'Each save in the app (a POST, a PUT) with how many clicks and how long people take to get it done.', 'Only people\'s clicks count: clicks made by code do not.', 'Before arguing "the screen is confusing", measure it: "creating a ticket takes 12 clicks and 25 s" is an argument.'] },
      { h: 'effort', pt: ['Esforço por ação', 'Mediana e p90 de cliques e tempo, e quantos cliques foram na própria tela contra o caminho até ela.', 'p90 alto com mediana baixa: a maioria vai bem, uma parte sofre muito.', '"8 dos 12 cliques são só para chegar à tela" pede um atalho, não um formulário menor.'],
        en: ['Effort per action', 'Median and p90 of clicks and time, and how many clicks were on the screen itself against the way to it.', 'High p90 with a low median: most do fine, some struggle a lot.', '"8 of the 12 clicks are just to reach the screen" calls for a shortcut, not a smaller form.'] },
    ],
    versions: [
      { pt: ['Versões: o deploy melhorou ou piorou?', 'Uma versão contra a outra, tela a tela e ação a ação, e as falhas que só a nova tem.', 'Se a versão nova ficou pouco tempo no ar, o painel amplia o período sozinho e avisa.', 'Na manhã seguinte ao deploy, compare a nova com a anterior antes de liberar para todos os clientes.'],
        en: ['Versions: did the deploy help or hurt?', 'One version against another, screen by screen and action by action, and the failures only the new one has.', 'If the new version has been live briefly, the dashboard widens the period by itself and says so.', 'The morning after a deploy, compare the new one with the previous before releasing it to every customer.'] },
      { s: '#cmp-a', up: 1, pt: ['Escolha as duas versões', 'A da esquerda contra a da direita: por padrão, a mais nova contra a anterior.', 'Dá para comparar versões distantes, como a de hoje contra a de um mês atrás.', 'Um cliente diz que "antes era melhor": compare a versão de hoje com a que ele usava.'],
        en: ['Pick the two versions', 'The left one against the right one: by default the newest against the previous.', 'You can compare far-apart versions, like today\'s against last month\'s.', 'A customer says "it used to be better": compare today\'s version with the one they used.'] },
      { h: 'compare', pt: ['Telas, da que mais piorou', 'A frustração de cada tela nas duas versões, da que mais piorou para a que mais melhorou. Abaixo vêm as ações e as falhas novas.', 'Volume diferente entre versões é só contexto: a comparação é por visita.', 'Uma tela no topo com +30 aponta exatamente o que reverter ou corrigir.'],
        en: ['Screens, most worsened first', 'Each screen\'s frustration in both versions, from most worsened to most improved. Below come the actions and the new failures.', 'Different volume between versions is only context: the comparison is per visit.', 'A screen at the top with +30 points exactly at what to roll back or fix.'] },
    ],
    usage: [
      { pt: ['Uso: o que as pessoas usam', 'As telas e os elementos mais e menos usados, e o que pode ser clicado e ninguém clica.', 'Clique numa tela para ver os elementos dela.', 'Antes de investir numa tela, veja se ela é usada: esforço numa tela de 3 visitas por mês é desperdício.'],
        en: ['Usage: what people use', 'The most and least used screens and elements, and what can be clicked and nobody clicks.', 'Click a screen to see its elements.', 'Before investing in a screen, check that it is used: effort on a screen with 3 visits a month is waste.'] },
      { h: 'screensByUse', pt: ['Telas, da mais usada', 'Visitas, cliques, usuários e frustração por tela, com a variação contra o período anterior.', 'A queda de uso de uma tela importante é sinal precoce de problema.', 'O topo desta lista é o que mais merece cuidado no próximo redesenho.'],
        en: ['Screens, most used first', 'Visits, clicks, users and frustration per screen, with the change against the previous period.', 'A drop in use on an important screen is an early warning.', 'The top of this list is what most deserves care in the next redesign.'] },
      { h: 'elements', pt: ['Elementos da tela', 'Cada botão e link da tela escolhida, com cliques e pessoas. "Abrir mapa de calor" mostra o mesmo desenhado.', 'O nome técnico fica embaixo; dê um nome melhor no Dicionário.', 'Dois botões que fazem quase a mesma coisa e um tem 10× mais cliques: o outro pode sair.'],
        en: ['The screen\'s elements', 'Each button and link of the chosen screen, with clicks and people. "Open heat map" shows the same drawn.', 'The technical name sits below; give it a better name in the Dictionary.', 'Two buttons that do almost the same and one has 10× the clicks: the other can go.'] },
      { h: 'never', pt: ['Nunca clicados', 'O que está na tela, pode ser clicado e ninguém clicou no período.', 'Confira o período: em 7 dias algo raro pode só não ter acontecido.', '"Exportar PDF com 0 cliques em 90 dias": esconda em "Mais ações" ou remova e deixe a tela mais limpa.'],
        en: ['Never clicked', 'What is on the screen, can be clicked and nobody clicked in the period.', 'Mind the period: in 7 days something rare may simply not have happened.', '"Export PDF with 0 clicks in 90 days": hide it under "More actions" or remove it and keep the screen cleaner.'] },
    ],
    journeys: [
      { pt: ['Jornadas: o caminho das pessoas', 'Quanto custa chegar a cada botão, o que as pessoas fazem em sequência, de onde vêm, para onde vão e onde desistem.', 'Cada seção tem o seu "?" com a definição exata.', 'Use esta aba quando a pergunta for "por que demora?" e não "o que quebra?".'],
        en: ['Journeys: the paths people take', 'What it costs to reach each button, what people do in sequence, where they come from, where they go and where they give up.', 'Each section has its "?" with the exact definition.', 'Use this tab when the question is "why does it take long?" rather than "what breaks?".'] },
      { h: 'detours', pt: ['Tarefas interrompidas', 'Quem começa algo, sai para outra tela no meio e volta para concluir.', 'Um desvio frequente é informação que falta na tela de origem.', '"15% saem de Novo ticket para Clientes e voltam": ponha a busca de cliente dentro do formulário.'],
        en: ['Interrupted tasks', 'Who starts something, leaves for another screen midway and comes back to finish.', 'A frequent detour is information missing on the original screen.', '"15% leave New ticket for Clients and come back": put the client search inside the form.'] },
      { h: 'reach', pt: ['Longe demais', 'Botões e ações muito usados que exigem muitos cliques ou telas até chegar.', 'Muito usado e longe é o melhor candidato a atalho.', '"Responder: 600 usos, 4 telas até lá": um botão na lista de tickets economiza horas por semana do time.'],
        en: ['Too far', 'Heavily used buttons and actions that take many clicks or screens to reach.', 'Heavily used and far away is the best shortcut candidate.', '"Reply: 600 uses, 4 screens away": a button on the ticket list saves the team hours a week.'] },
      { h: 'pairs', pt: ['Andam juntas', 'Ações que costumam vir uma logo depois da outra.', 'Juntar as duas num passo, ou aproximar os botões.', '"Salvar e depois Fechar ticket em 70% das vezes": um "Salvar e fechar" resolve.'],
        en: ['Go together', 'Actions that usually come one right after the other.', 'Merge them into one step, or bring the buttons closer.', '"Save then Close ticket 70% of the time": a "Save and close" does it.'] },
      { h: 'flow', pt: ['De onde vêm e para onde vão', 'Para a tela escolhida: de quais telas as pessoas chegam e para quais vão depois.', 'Troque a tela no seletor da seção.', 'Se a maioria sai de Relatórios direto para Tickets, talvez o relatório devesse ter o link para o ticket.'],
        en: ['Where they come from and go', 'For the chosen screen: which screens people arrive from and which they go to next.', 'Change the screen in the section\'s picker.', 'If most leave Reports straight for Tickets, maybe the report should link to the ticket.'] },
      { h: 'funnel', pt: ['Funil', 'Monte passos com telas, ações e botões e veja quantas sessões chegam a cada um e onde se perdem.', 'Até 8 passos; o funil fica no endereço da página.', 'Novo ticket → Salvar → Responder: se metade some entre Salvar e Responder, o problema está ali.'],
        en: ['Funnel', 'Build steps from screens, actions and buttons and see how many sessions reach each one and where they drop.', 'Up to 8 steps; the funnel lives in the page address.', 'New ticket → Save → Reply: if half vanish between Save and Reply, that is where the problem is.'] },
    ],
    map: [
      { pt: ['Mapa: a tela com o calor por cima', 'A tela desenhada com a cara do seu app (sem o conteúdo das pessoas) e três lentes: Calor, Problemas e Rotas.', 'O que um clique abre (uma janela, um menu) também entra no desenho.', 'Numa reunião de produto, mostre o calor da tela em vez de tabelas: todo mundo entende em segundos.'],
        en: ['Map: the screen with the heat on top', 'The screen drawn looking like your app (without people\'s content) and three lenses: Heat, Problems and Routes.', 'What a click opens (a dialog, a menu) is part of the drawing too.', 'In a product meeting, show the screen\'s heat instead of tables: everyone gets it in seconds.'] },
      { s: '#map-screen', pt: ['Escolha a tela', 'As telas com desenho, com as visitas. Desktop e Celular trocam o desenho quando há os dois.', 'Uma tela só ganha desenho depois que alguém a abre com o coletor novo.', 'Compare Desktop e Celular da mesma tela: o que é fácil no computador pode estar escondido no celular.'],
        en: ['Pick the screen', 'The screens that have a drawing, with their visits. Desktop and Phone switch the drawing when both exist.', 'A screen only gets a drawing once someone opens it with the new collector.', 'Compare Desktop and Phone for the same screen: what is easy on a computer may be hidden on a phone.'] },
      { s: '[data-map-lens]', up: 1, pt: ['As lentes', 'Calor: onde mais clicam, do azul ao vermelho. Problemas: onde mais irrita, pela parte dos cliques. Rotas: o próximo passo mais comum depois de cada elemento.', 'O número aparece só nos cinco mais quentes; o resto se lê pela cor.', 'Problemas em vermelho num botão muito usado é a prioridade da semana.'],
        en: ['The lenses', 'Heat: where people click most, blue to red. Problems: where it irritates most, as a share of clicks. Routes: the most common next step after each element.', 'The number shows only on the five hottest; read the rest by colour.', 'Problems in red on a heavily used button is the week\'s priority.'] },
      { s: '#map-svg', pt: ['O desenho', 'Passe o mouse num elemento para ver os números; clique para ver só ele: as rotas de entrada e saída ou o porquê de irritar.', 'Em Rotas, "vai e volta" marca dois elementos entre os quais as pessoas ficam indo e voltando.', 'Em Problemas, "clicou de novo enquanto carregava, POST /api/convites 8,3 s" já diz a correção: travar o botão e acelerar a chamada.'],
        en: ['The drawing', 'Hover an element for its numbers; click it to see only it: the routes in and out, or why it irritates.', 'In Routes, "back and forth" marks two elements people keep going between.', 'In Problems, "clicked again while it was loading, POST /api/invites 8.3 s" already says the fix: lock the button and speed up the request.'] },
      { s: 'aside.mappanel', pt: ['A leitura ao lado', 'Ao lado do desenho, a lista da lente: o que mais se usa, o que mais irrita e por quê, ou os passos mais fortes. Em Problemas e Rotas, uma frase no fim diz o que fazer.', 'Clique num item da lista para destacá-lo no desenho.', 'Selecione a frase do fim (em Problemas ou Rotas) e cole na demanda: ela já tem o número e a sugestão.'],
        en: ['The reading beside it', 'Beside the drawing, the lens\'s list: what is used most, what irritates most and why, or the strongest steps. In Problems and Routes, a closing sentence says what to do.', 'Click an item in the list to highlight it in the drawing.', 'Select the closing sentence (in Problems or Routes) and paste it into the ticket: it already has the number and the suggestion.'] },
      { s: '[data-open-map]', up: 1, pt: ['No app de verdade', '"Abrir com o calor" e "Abrir com as rotas" abrem o seu app com o mesmo mapa por cima. O app continua clicável e o mapa acompanha a rolagem, os menus e as janelas.', 'Abre com o login que você já tem no app; o link do mapa vale por um tempo.', 'Navegue pelo app com o calor ligado para achar o que o desenho não mostra, como uma tela de registro.'],
        en: ['On the real app', '"Open with the heat" and "Open with the routes" open your app with the same map on top. The app stays clickable and the map follows scrolling, menus and dialogs.', 'It opens with the sign-in you already have in the app; the map link lasts a while.', 'Browse the app with the heat on to find what the drawing does not show, like a record\'s screen.'] },
    ],
    product: [
      { pt: ['Produto: o app por área', 'O uso e a frustração por área do app (você define as áreas no Dicionário), o que é visto e pouco usado, e as novidades.', 'Sem áreas definidas, cada tela conta como a sua própria área.', 'No planejamento do trimestre, veja que área cresce e qual está esquecida.'],
        en: ['Product: the app by area', 'Use and frustration by area of the app (you define areas in the Dictionary), what is seen and little used, and what is new.', 'With no areas defined, each screen counts as its own area.', 'In quarterly planning, see which area grows and which is forgotten.'] },
      { h: 'areas', pt: ['Áreas do produto', 'Visitas, pessoas, frustração e falhas de cada área, com a tendência por dia.', 'Áreas pequenas e frustrantes são ganhos rápidos.', '"Relatórios: poucas pessoas, frustração 40": quem usa sofre; vale conversar com essas pessoas.'],
        en: ['Product areas', 'Visits, people, frustration and failures per area, with the trend per day.', 'Small and frustrating areas are quick wins.', '"Reports: few people, frustration 40": whoever uses it suffers; worth talking to them.'] },
      { h: 'low', pt: ['Visto e pouco usado', 'Botões que aparecem em muitas sessões e quase ninguém clica.', 'Pode ser botão que ninguém entende, ou que sobra na tela.', '"Exportar PDF aparece em 833 sessões e foi clicado em 0,4% delas": esconda em "Mais ações" ou pergunte a quem usa se ainda faz falta.'],
        en: ['Seen and little used', 'Buttons that show up in many sessions and almost nobody clicks.', 'It may be a button nobody understands, or one the screen does not need.', '"Export PDF shows in 833 sessions and was clicked in 0.4% of them": hide it under "More actions" or ask its users whether it is still needed.'] },
      { h: 'news', pt: ['Novidades', 'Elementos que apareceram há pouco e se as pessoas já estão usando.', 'O "desde" vem da primeira vez que o coletor viu o elemento.', 'Lançou "Duplicar ticket" na 1.6? Aqui você vê se pegou ou se ninguém achou.'],
        en: ['What is new', 'Elements that appeared recently and whether people are using them yet.', 'The "since" comes from the first time the collector saw the element.', 'Shipped "Duplicate ticket" in 1.6? Here you see whether it caught on or nobody found it.'] },
    ],
    features: [
      { pt: ['Features: as funcionalidades que você vigia', 'Uma feature é um grupo de telas, botões e ações com um nome ("Convidar usuário"). Aqui cada uma tem uso, frustração, falhas e quem usa.', 'Escolha uma feature nos Filtros e o painel inteiro passa a mostrar só ela.', 'Lançou uma funcionalidade nova? Crie a feature no dia do lançamento e acompanhe a adoção semana a semana.'],
        en: ['Features: the functionality you watch', 'A feature is a group of screens, buttons and actions with a name ("Invite user"). Here each one has use, frustration, failures and who uses it.', 'Pick a feature in Filters and the whole dashboard shows only it.', 'Shipped something new? Create the feature on launch day and follow its adoption week by week.'] },
      { h: 'features', pt: ['Criar e editar', 'Dê um nome e escolha o que faz parte: telas, botões, ações e eventos do app, um por vez pelo tipo e pelo item.', 'Uma feature pode juntar partes de telas diferentes.', '"Faturamento" = tela Faturas + botão Emitir nota + ação POST /api/notas: um número só para a reunião com o financeiro.'],
        en: ['Create and edit', 'Give it a name and pick what belongs to it: screens, buttons, actions and app events, one at a time by kind and item.', 'A feature can join parts of different screens.', '"Billing" = Invoices screen + Issue invoice button + POST /api/invoices action: one number for the meeting with finance.'] },
      { s: 'section.card.feature', pt: ['Cada feature', 'Frustração, uso, em quantas sessões aparece, pessoas, contas e falhas, contra o período anterior.', '"Nas sessões" diz a adoção: que parte das sessões usou a feature.', '"Convidar usuário: frustração 49, em 37% das sessões": antes de divulgar mais a feature, conserte o que irrita.'],
        en: ['Each feature', 'Frustration, use, how many sessions it shows in, people, accounts and failures, against the previous period.', '"In sessions" is adoption: the share of sessions that used the feature.', '"Invite user: frustration 49, in 37% of sessions": before promoting the feature more, fix what irritates.'] },
    ],
    people: [
      { pt: ['Pessoas: quem usa', 'O uso por papel e por usuário. O Termometro guarda só ids; o nome aparece se o app mandar.', 'Escolha uma conta no topo para ver só as pessoas dela.', 'Um cliente reclamou? Ache o usuário e veja onde ele mais sofreu antes de responder.'],
        en: ['People: who uses it', 'Use by role and by user. Termometro keeps only ids; the name shows if the app sends it.', 'Pick an account at the top to see only its people.', 'A customer complained? Find the user and see where they struggled most before replying.'] },
      { s: 'section.card.pointer', pt: ['Uso por conta', 'O atalho para a aba Contas, onde cada cliente tem tendência, frustração e falhas.', 'Na tabela de usuários, a conta de cada pessoa também é um link para ela.', 'Achou uma pessoa com problema? Clique na conta dela e veja se o resto da empresa sofre igual.'],
        en: ['Use by account', 'The shortcut to the Accounts tab, where each customer has trend, frustration and failures.', 'In the users table, each person\'s account is a link to it too.', 'Found someone struggling? Click their account and see whether the rest of the company struggles the same.'] },
      { h: 'byUser', pt: ['Por usuário', 'Visitas, papel, conta e as telas que cada pessoa mais usa.', 'No celular, o resto dos números vai para a linha de baixo.', 'Um cliente abriu chamado: ache a pessoa aqui e veja as telas que ela mais usa antes de responder.'],
        en: ['By user', 'Visits, role, account and the screens each person uses most.', 'On a phone, the rest of the numbers move to the line below.', 'A customer opened a ticket: find the person here and see the screens they use most before replying.'] },
    ],
    accounts: [
      { pt: ['Contas: a saúde de cada cliente', 'Pessoas e sessões por dia, uso das features vigiadas, frustração e falhas de cada conta, contra o período anterior.', 'A conta que ficou em 60% ou menos do que era, fora da oscilação normal dela, aparece marcada.', 'Antes da reunião de renovação, veja se o uso da conta caiu: é o aviso de risco de cancelamento mais cedo que existe.'],
        en: ['Accounts: each customer\'s health', 'People and sessions per day, use of the watched features, frustration and failures per account, against the previous period.', 'An account that fell to 60% or less of what it was, beyond its normal swing, is marked.', 'Before a renewal meeting, check whether the account\'s use dropped: the earliest churn warning there is.'] },
      { h: 'accounts', pt: ['A lista e a ordem', '"Só quem caiu" filtra as contas em queda; "Tendência" e "Pior primeiro" mudam a ordem.', 'O botão de copiar leva um resumo da conta pronto para o CRM.', 'Toda segunda, "Só quem caiu": cada conta da lista vira uma ligação do time de sucesso do cliente.'],
        en: ['The list and the order', '"Only who dropped" filters accounts going down; "Trend" and "Worst first" change the order.', 'The copy button takes an account summary ready for the CRM.', 'Every Monday, "Only who dropped": each account on the list becomes a call from customer success.'] },
      { s: 'tr.row[data-account]', pt: ['Abrir uma conta', 'Clique numa conta para ver o pulso dela: as piores telas, o que irrita ali e as falhas que mais a atingem. O painel inteiro passa a mostrar só essa conta.', 'Dê um nome à conta no Dicionário ("Contrato Acme Saúde") para não decorar ids.', 'O cliente diz que "o sistema está lento": abra a conta, veja as lentidões dela e compare com a aba Falhas para saber se é só dele ou de todo mundo.'],
        en: ['Open an account', 'Click an account for its pulse: the worst screens, what irritates there and the failures that hit it most. The whole dashboard then shows only that account.', 'Name the account in the Dictionary ("Acme Health contract") so you do not memorise ids.', 'The customer says "the system is slow": open the account, see its slow requests and compare with the Failures tab to know whether it is theirs or everyone\'s.'] },
    ],
    dictionary: [
      { pt: ['Dicionário: os nomes das pessoas', 'O nome que o seu time usa para cada tela, botão, ação, conta e área. O painel inteiro passa a falar esse nome, com o técnico embaixo.', 'O coletor já traz o rótulo do botão e o nome da tela; aqui você corrige e completa.', 'Antes de mostrar o painel para quem não é técnico, dê nome às 10 telas mais usadas: a leitura muda completamente.'],
        en: ['Dictionary: the names people use', 'The name your team uses for each screen, button, action, account and area. The whole dashboard then speaks that name, with the technical one below.', 'The collector already brings the button label and the screen name; here you fix and complete them.', 'Before showing the dashboard to non-technical people, name the 10 most used screens: the reading changes completely.'] },
      { s: '#dict-filter', pt: ['Buscar', 'Filtra todas as listas ao mesmo tempo, pelo nome ou pelo técnico.', 'Busque pelo pedaço do seletor ("salvar") para achar todos os botões parecidos.', 'Achou "button#btn-sv-2" num aviso? Busque aqui e dê o nome "Salvar rascunho".'],
        en: ['Search', 'Filters every list at once, by name or by technical key.', 'Search a piece of the selector ("save") to find all similar buttons.', 'Saw "button#btn-sv-2" in a warning? Search it here and name it "Save draft".'] },
      { s: '#dict-body', pt: ['Telas, botões, ações, contas e áreas', 'Cada lista com o nome atual e um campo para trocar. Em telas, a área agrupa telas para a aba Produto.', 'O nome vale para todo o painel, os avisos e o que uma IA lê.', 'A conta 7001 vira "Contrato Acme Saúde": nas Contas, nas Pessoas e nos avisos de queda.'],
        en: ['Screens, buttons, actions, accounts and areas', 'Each list with the current name and a field to change it. For screens, the area groups screens for the Product tab.', 'The name holds for the whole dashboard, the warnings and what an AI reads.', 'Account 7001 becomes "Acme Health contract": in Accounts, People and drop warnings.'] },
    ],
  }

  // ---------- the engine ----------
  let run = null // { steps, i, root, hole, card, raf, back }
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'reduce'
  const seen = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 }
  function targetOf(step) {
    let el = null
    if (step.h) el = [...document.querySelectorAll(`main [data-help="${step.h}"]`)].find(seen)?.closest('section, .card, details') ?? null
    else if (step.s) el = [...document.querySelectorAll(step.s)].find(seen) ?? null
    for (let n = step.up || 0; el && n > 0; n--) el = el.parentElement
    return el
  }
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

  function start() {
    if (run) return close()
    const all = TOURS[state.tab] || []
    const steps = all.filter((s) => (!s.h && !s.s) || targetOf(s))
    const root = document.createElement('div')
    root.className = 'tour'
    root.innerHTML = '<div class="tour-hole" aria-hidden="true"></div><div class="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-t"></div>'
    document.body.append(root)
    run = { steps, i: 0, root, hole: root.firstChild, card: root.lastChild, back: document.activeElement }
    if (!steps.length) { run.card.innerHTML = `<p>${esc(UI().none)}</p><div class="tour-foot"><span></span><button class="primary" data-tour="close">${esc(UI().done)}</button></div>`; place(null); run.card.querySelector('button').focus(); return }
    show(0)
  }

  function show(i) {
    const r = run
    r.i = i
    const step = r.steps[i], [title, body, tip, ex] = PT ? step.pt : step.en
    const el = targetOf(step)
    const last = i === r.steps.length - 1
    r.card.innerHTML = `<div class="tour-head"><span class="tour-n">${esc(UI().of(i + 1, r.steps.length))}</span>
        <button class="tour-x" data-tour="close" aria-label="${esc(UI().close)}" title="${esc(UI().close)}">×</button></div>
      <h3 id="tour-t">${esc(title)}</h3><p>${esc(body)}</p>
      ${tip ? `<p class="tour-tip"><b>${esc(UI().tip)}:</b> ${esc(tip)}</p>` : ''}
      ${ex ? `<p class="tour-ex"><b>${esc(UI().ex)}:</b> ${esc(ex)}</p>` : ''}
      <div class="tour-foot"><div class="tour-dots" aria-hidden="true">${r.steps.map((_, k) => `<i class="${k === i ? 'on' : ''}"></i>`).join('')}</div>
        <div>${i ? `<button data-tour="back">${esc(UI().back)}</button>` : ''}<button class="primary" data-tour="${last ? 'close' : 'next'}">${esc(last ? UI().done : UI().next)}</button></div></div>`
    r.target = el
    if (el) {
      const b = el.getBoundingClientRect()
      // The panel's top bar stays on screen: scrolling leaves room for it.
      const bar = [...document.querySelectorAll('header')].find((x) => getComputedStyle(x).position === 'sticky' || getComputedStyle(x).position === 'fixed')
      const under = bar ? bar.getBoundingClientRect().bottom : 0
      el.style.scrollMarginTop = under + 12 + 'px'
      if (b.top < under + 8 || b.bottom > innerHeight - 20) el.scrollIntoView({ block: b.height > innerHeight * 0.6 ? 'start' : 'center', behavior: reduce() ? 'auto' : 'smooth' })
    }
    place(el)
    r.card.querySelector('[data-tour="next"], [data-tour="close"].primary')?.focus({ preventScroll: true })
    cancelAnimationFrame(r.raf)
    const follow = () => { if (run !== r) return; place(r.target); r.raf = requestAnimationFrame(follow) }
    r.raf = requestAnimationFrame(follow)
  }

  // The spotlight on the element and the card beside it: below, else above, else at the bottom of the screen.
  function place(el) {
    const { hole, card } = run
    const pad = 6, gap = 12, m = 12
    const narrow = innerWidth < 640
    if (!el) {
      hole.style.cssText = `left:50%;top:50%;width:0;height:0`
      card.style.cssText = narrow ? `left:${m}px;right:${m}px;bottom:${m}px` : `left:50%;top:50%;transform:translate(-50%,-50%)`
      return
    }
    const r = el.getBoundingClientRect()
    const top = Math.max(r.top - pad, 4), bottom = Math.min(r.bottom + pad, innerHeight - 4)
    hole.style.cssText = `left:${r.left - pad}px;top:${top}px;width:${r.width + pad * 2}px;height:${Math.max(0, bottom - top)}px`
    if (narrow) { card.style.cssText = `left:${m}px;right:${m}px;bottom:${m}px`; return }
    const w = Math.min(400, innerWidth - 2 * m), h = card.offsetHeight
    const left = Math.max(m, Math.min(r.left, innerWidth - w - m))
    let y = bottom + gap, x = left
    if (y + h > innerHeight - m) y = top - gap - h
    // No room above or below (a tall section): the card sits in the bottom right corner, where the start of the section
    // (its title, its first rows) stays in view.
    if (y < m) { y = innerHeight - h - m; x = innerWidth - w - m }
    card.style.cssText = `left:${x}px;top:${y}px;width:${w}px`
  }

  function close() {
    if (!run) return
    cancelAnimationFrame(run.raf)
    run.root.remove()
    const back = run.back
    run = null
    $('#tour-open')?.setAttribute('aria-expanded', 'false')
    back?.focus?.({ preventScroll: true })
  }

  document.addEventListener('click', (e) => {
    if (e.target.closest('#tour-open')) { start(); $('#tour-open')?.setAttribute('aria-expanded', String(!!run)); return }
    const b = run && e.target.closest('[data-tour]')
    if (!b) return
    const a = b.dataset.tour
    if (a === 'close') close()
    else if (a === 'next') show(Math.min(run.i + 1, run.steps.length - 1))
    else if (a === 'back') show(Math.max(run.i - 1, 0))
  })
  document.addEventListener('keydown', (e) => {
    if (!run) return
    if (e.key === 'Escape') { e.preventDefault(); close() }
    else if (e.key === 'ArrowRight' && run.steps.length) show(Math.min(run.i + 1, run.steps.length - 1))
    else if (e.key === 'ArrowLeft' && run.steps.length) show(Math.max(run.i - 1, 0))
    else if (e.key === 'Tab') { // focus stays in the card
      const f = [...run.card.querySelectorAll('button')]
      if (!f.length) return
      const k = f.indexOf(document.activeElement)
      e.preventDefault(); f[(k + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus()
    }
  })
  addEventListener('hashchange', () => { if (run && !location.hash.startsWith('#' + state.tab)) close() })

  // The button at the top, beside ⋯.
  function button() {
    if ($('#tour-open')) return
    const more = $('#prefs-open')?.closest('.prefs-wrap')
    if (!more) return
    more.insertAdjacentHTML('beforebegin', `<span class="prefs-wrap f-tour"><button id="tour-open" aria-haspopup="dialog" aria-expanded="false" title="${esc(UI().openTip)}">${esc(UI().open)}</button></span>`)
  }
  new MutationObserver(button).observe(document.body, { childList: true, subtree: true })
  button()
})()
