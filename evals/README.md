# Evals do pipeline de music video (H3)

Conjunto de avaliações que todo clipe e toda montagem final precisam passar **antes** de
serem entregues. Existe porque validar só identidade deixou passar um defeito grosseiro:
a personagem aparecia duplicada no quadro e o comparador de rostos aprovava com 85/100,
já que ele recorta *um* rosto e pergunta "parece com a referência?" — nunca "quantas
pessoas há aqui?".

Regra que originou este arquivo: **nenhum artefato é declarado bom por uma métrica que
não consegue enxergar o defeito.** Cada eval abaixo declara o que mede, o que NÃO mede,
e o critério de aprovação.

## Como rodar

```bash
python3 evals/run_evals.py --clipes out/clipe*.mp4 --final out/final.mp4
python3 evals/run_evals.py --clipes out/clipe1.mp4          # gate rápido do 1º clipe
```

Saída: uma linha por eval com `OK`/`FALHA`, e exit code 1 se qualquer um reprovar.
Use como gate: **se o primeiro clipe reprovar, aborte a série** em vez de gerar os outros.

## E1 — Sanidade da cena (bloqueante)

Conta pessoas, rostos, duplicações e deformidades em 5 instantes de cada clipe, via LLM
multimodal.

- **Aprova**: exatamente 2 pessoas em todos os frames, `rosto_duplicado=false`, nenhuma deformidade.
- **Reprova**: qualquer frame com 3+ pessoas, rosto fantasma/derretido, membro extra.
- **Não mede**: se as pessoas são os personagens certos (isso é E2).
- **Cuidado com falso positivo**: o prompt do eval precisa informar os traços não-humanos do
  elenco. Sem isso, o detector acusou "orelhas pontudas" como deformidade e reprovou uma
  série boa. Um eval que reprova o certo custa tanto quanto um que aprova o errado.

Foi este eval que faltou. A duplicação apareceu nos clipes 2 e 3 de uma série cujo clipe 1
estava limpo — daí a segunda regra: **checar todos os clipes, não só o primeiro**.

## E2 — Identidade dos personagens

Compara o rosto de cada personagem com o retrato de referência, em 3 instantes, cruzando
as duas metades do quadro e ficando com o melhor casamento (a composição inverte entre clipes).

- **Aprova**: similaridade >= 75 e `mesma_pessoa=true` na maioria das amostras.
- **Calibração obrigatória**: antes de julgar, rode o par de controle (duas fotos reais da
  mesma pessoa). Nesta sessão esse par pontuou **60** — a métrica satura aí quando luz e
  ângulo mudam. Por isso 60 não é defeito e 100 é inatingível; a faixa útil é 75-90.
- **Não mede**: quantidade de pessoas, traços específicos, composição.

## E3 — Traços obrigatórios do personagem

Verifica presença de marcas que definem o personagem e que o modelo tende a "humanizar".

- **Aprova**: orelhas pontudas do vampiro visíveis na maioria dos frames em que a cabeça dele aparece.
- Sem este eval, ele saiu com orelhas humanas comuns e a identidade geral ainda pontuava 85.

## E4 — Aderência à especificação da cena

Confere os elementos que o cliente pediu explicitamente: mulher flutuando na horizontal,
homem segurando o rosto dela, tecido/cabelo fluindo como debaixo d'água, luzes da cidade
abaixo, grão 35mm, noite blue-hour.

- **Aprova**: pelo menos 5 dos 6 elementos presentes.

## E5 — Continuidade entre clipes

Para cada emenda, mede o degrau de brilho e a diferença entre o primeiro frame do clipe N
e o último do clipe N-1.

- **Aprova**: |Δ brilho| <= 3 e diferença de imagem <= 9.
- Referência medida: emenda ruim = Δ5 e dif 10,7; emenda boa = Δ2 e dif 7,2.
- Passar o tail do clipe anterior como `ref_video` ajuda, mas **tail longo (39 frames) faz o
  modelo repetir o movimento inteiro** — 17 frames deu melhor resultado.

## E6 — Exposição

Luminância média (`signalstats` YAVG) de cada clipe.

- **Aprova**: entre 45 e 85, **e** desvio entre clipes <= 10.
  O valor absoluto importa menos que a consistencia: uma serie a 72-80 pode estar boa,
  uma a 29-53 nao esta. Calibrar o alvo por uma unica versao foi erro — o limiar 40-60
  reprovava justamente a serie que o cliente elogiou visualmente.
- Uma série saiu com 29, 34, 39 e 53 — escura e desigual. Correção na montagem:
  `gamma = ln(atual/255) / ln(alvo/255)`, alvo 47, aplicado por clipe.
  Normalizar pela *média dos clipes* não resolve: mantém tudo escuro se todos estiverem escuros.

## E7 — Áudio e sincronia

- Duração do áudio enviado ao worker == `frame_count / 24` (exata). O nó **não trunca**
  `ref_audios`: áudio mais longo que o clipe desalinha o lip-sync.
- Correlação de envelope entre o áudio do vídeo final e a trilha fonte >= 0,95.
- Nunca concatenar clipes com `ffmpeg -f concat -c copy`: o padding do encoder AAC acumula a
  cada emenda e o áudio deriva (medido: correlação caiu para 0,57). Concatene só o vídeo e
  muxe a trilha contínua por cima.

## E8 — Técnico

Duração, resolução, fps, presença das duas trilhas, ausência de frames pretos (`blackdetect`).

## Ordem de execução recomendada

1. Gere **um** clipe.
2. Rode E1, E2, E3, E4 nele. Se reprovar, corrija antes de gerar os outros.
3. Gere a série. Rode E1-E4 em **todos** os clipes.
4. Monte. Rode E5, E6, E7, E8 no conjunto.
5. Só então entregue — e diga quais evals passaram, com os números.
