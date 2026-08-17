"""Runner dos evals do pipeline de music video. Ver README.md para os criterios.

Uso:
    python3 evals/run_evals.py --clipes a.mp4 b.mp4 --final final.mp4 \
        --ref-maia maia.jpg --ref-vampiro vamp.jpg --trilha trilha.mp3
"""
import argparse, base64, json, math, os, re, subprocess, sys, urllib.request

MODELO = "google/gemini-2.5-flash"
PESSOAS_ESPERADAS = 2  # sobrescrito por --pessoas
IDENT_MIN = 75
EXPOSICAO_MIN, EXPOSICAO_MAX = 45.0, 85.0
EXPOSICAO_DESVIO_MAX = 10.0
BRILHO_DELTA_MAX = 3.0
EMENDA_DIF_MAX = 9.0
AUDIO_CORR_MIN = 0.95
CORTE_RAZAO_MAX = 4.0
INSTANTES_CENA = ["0.5", "1.5", "2.5", "3.5", "4.5", "5.5", "6.5", "7.5"]


def _instantes(clipe):
    """Amostra dentro da duracao real: bloco de 175 frames tem 7.29s e t=7.5 nao existe."""
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", clipe], capture_output=True, text=True)
    try:
        dur = float(p.stdout.strip())
    except ValueError:
        return INSTANTES_CENA
    fim = max(0.5, dur - 0.15)
    dentro = [t for t in INSTANTES_CENA if float(t) <= fim]
    if not dentro or float(dentro[-1]) < fim - 0.4:
        dentro.append(f"{fim:.2f}")
    return dentro
INSTANTES_ID = ["1.5", "4.0", "6.5"]

resultados = []


def _key():
    with open("/Users/danilo/Documents/platform_k/chave.api") as fh:
        return fh.readlines()[1].split("=", 1)[-1].strip()


def _llm(prompt, *imagens):
    conteudo = [{"type": "text", "text": prompt}]
    for img in imagens:
        with open(img, "rb") as fh:
            conteudo.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()}})
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps({"model": MODELO, "messages": [{"role": "user", "content": conteudo}]}).encode(),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        txt = json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(txt.strip())


def _frame(clip, t, dst, crop=None):
    vf = ["-vf", crop] if crop else []
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", t, "-i", clip,
                    "-frames:v", "1", *vf, "-q:v", "3", dst], check=True, capture_output=True)
    return dst


def _luma(clip):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", clip, "-vf",
                        "select='not(mod(n,12))',signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-f", "null", "-"], capture_output=True, text=True)
    v = [float(l.split("=")[-1]) for l in p.stderr.splitlines() if "YAVG" in l]
    return sum(v) / len(v) if v else 0.0


def registrar(eval_id, ok, detalhe):
    resultados.append((eval_id, ok, detalhe))
    print(f"[{'OK   ' if ok else 'FALHA'}] {eval_id}: {detalhe}", flush=True)


# ---------------- E1: sanidade da cena ----------------
P_CENA = """Analise este frame. Responda APENAS JSON valido:
- "pessoas": inteiro, pessoas humanas visiveis (conte qualquer rosto ou corpo, mesmo parcial, desfocado, deformado ou ao fundo)
- "rostos": inteiro, rostos humanos distintos
- "rosto_duplicado": true se a mesma pessoa aparece mais de uma vez, ou ha rosto extra/fantasma/deformado alem dos personagens esperados
- "pernas": inteiro, quantas PERNAS distintas voce conta na pessoa (o normal e 2; conte coxas/panturrilhas/pes separados, mesmo parciais ou sobrepostos). Se o enquadramento corta as pernas fora, responda 2
- "bracos": inteiro, quantos BRACOS distintos (o normal e 2). Se o enquadramento corta os bracos fora, responda 2
- "maos_ok": true se as maos visiveis tem 5 dedos e formato normal; true tambem se nenhuma mao aparece
- "deformidades": lista curta de defeitos anatomicos (perna extra, braco extro, mao deformada, dedo a mais, rosto derretido, corpos fundidos, membro que nasce do lugar errado); vazia se nao houver

CONTEXTO: quando ha um personagem masculino, ele e um vampiro e TEM orelhas pontudas de elfo
por design. Orelha pontuda NAO e deformidade e NAO deve entrar na lista. Pele palida e olhos
fundos tambem sao do personagem. Reporte apenas defeitos reais de geracao.
Seja literal: conte TODOS os rostos, inclusive parciais, escuros ou distorcidos.
ATENCAO ESPECIAL A MEMBROS: em pose sentada as pernas se sobrepoem e o modelo costuma gerar uma
PERNA EXTRA. Siga cada perna do quadril ate o pe antes de contar. Se houver 3 pernas ou 3 bracos,
reporte o numero real e inclua "perna extra"/"braco extra" em deformidades."""


def e1_cena(clipes):
    falhas = []
    for c in clipes:
        for t in _instantes(c):
            try:
                r = _llm(P_CENA, _frame(c, t, "/tmp/_e1.jpg"))
            except Exception as exc:
                falhas.append(f"{os.path.basename(c)}@{t}s erro:{exc}")
                continue
            problema = []
            if r.get("pessoas") != PESSOAS_ESPERADAS:
                problema.append(f"{r.get('pessoas')} pessoas")
            # so MEMBRO A MAIS e defeito: contar menos que 2 e enquadramento cortando fora
            if isinstance(r.get("pernas"), int) and r["pernas"] > 2:
                problema.append(f"{r['pernas']} pernas")
            if isinstance(r.get("bracos"), int) and r["bracos"] > 2:
                problema.append(f"{r['bracos']} bracos")
            if r.get("maos_ok") is False:
                problema.append("maos deformadas")
            if r.get("rosto_duplicado"):
                problema.append("DUPLICADO")
            if r.get("deformidades"):
                problema.append(",".join(r["deformidades"])[:60])
            if problema:
                falhas.append(f"{os.path.basename(c)}@{t}s: {'; '.join(problema)}")
    registrar("E1 sanidade da cena", not falhas,
              f"todos os frames com {PESSOAS_ESPERADAS} pessoa(s), sem duplicacao" if not falhas
              else f"{len(falhas)} frame(s): " + " | ".join(falhas[:4]))


# ---------------- E2: identidade ----------------
P_ID = """Duas imagens: a primeira e a REFERENCIA do personagem, a segunda um FRAME de video.
Responda APENAS JSON: {"mesma_pessoa": bool, "similaridade": 0-100, "diferencas": [str]}.
Compare proporcoes faciais, olhos, nariz, labios, mandibula, sobrancelhas, pele.
Ignore iluminacao, angulo, expressao e resolucao."""


def e2_identidade(clipes, refs, controle=None):
    if controle:
        try:
            base = _llm(P_ID, controle[0], controle[1])
            print(f"       calibracao (duas fotos reais da mesma pessoa): {base['similaridade']}", flush=True)
        except Exception:
            pass
    for nome, ref in refs.items():
        if not ref:
            continue
        notas, reprovas = [], []
        for c in clipes:
            # por instante, o recorte certo e o de maior similaridade (a composicao inverte);
            # entre instantes usamos a MEDIANA, nao o melhor, para um bom angulo nao mascarar o resto
            por_instante = []
            for t in INSTANTES_ID:
                melhor, casou = 0, False
                for lado, x in (("esq", 0), ("dir", 384)):
                    f = _frame(c, t, "/tmp/_e2.jpg", f"crop=384:640:{x}:120,scale=400:-1")
                    try:
                        r = _llm(P_ID, ref, f)
                    except Exception:
                        continue
                    if r.get("similaridade", 0) > melhor:
                        melhor, casou = r.get("similaridade", 0), bool(r.get("mesma_pessoa"))
                if melhor:
                    por_instante.append(melhor)
                    if not casou:
                        reprovas.append(f"{os.path.basename(c)}@{t}s mesma_pessoa=false")
            if por_instante:
                notas.append(int(sorted(por_instante)[len(por_instante) // 2]))
        ok = bool(notas) and min(notas) >= IDENT_MIN and not reprovas
        registrar(f"E2 identidade {nome}", ok,
                  f"mediana por clipe {notas} (minimo {IDENT_MIN})"
                  + (f"; {len(reprovas)} amostra(s) com mesma_pessoa=false: " + "; ".join(reprovas[:3])
                     if reprovas else ""))


# ---------------- E3: tracos obrigatorios ----------------
P_TRACO = """Este frame mostra um personagem masculino careca. Responda APENAS JSON:
{"orelhas_visiveis": bool, "orelhas_pontudas": bool, "descricao": str}
"orelhas_pontudas" e true apenas se as orelhas terminam em ponta afilada tipo elfo."""


def e3_tracos(clipes):
    vis, pont = 0, 0
    for c in clipes:
        for t in ("2.0", "5.0"):
            try:
                r = _llm(P_TRACO, _frame(c, t, "/tmp/_e3.jpg"))
            except Exception:
                continue
            if r.get("orelhas_visiveis"):
                vis += 1
                pont += 1 if r.get("orelhas_pontudas") else 0
    ok = vis > 0 and pont / vis >= 0.6
    registrar("E3 orelhas pontudas", ok,
              f"{pont}/{vis} frames com orelha visivel mostram ponta de elfo" if vis
              else "orelhas nunca visiveis nas amostras")


# ---------------- E4: aderencia a especificacao ----------------
P_SPEC = """Responda APENAS JSON com booleanos sobre este frame:
{"mulher_flutuando_horizontal": bool, "homem_segura_o_rosto_dela": bool,
 "tecido_ou_cabelo_fluindo": bool, "luzes_de_cidade_abaixo": bool,
 "grao_de_filme": bool, "noite_azulada": bool}"""


def e4_spec(clipes):
    chaves = ["mulher_flutuando_horizontal", "homem_segura_o_rosto_dela", "tecido_ou_cabelo_fluindo",
              "luzes_de_cidade_abaixo", "grao_de_filme", "noite_azulada"]
    presentes = {k: 0 for k in chaves}
    n = 0
    for c in clipes:
        try:
            r = _llm(P_SPEC, _frame(c, "4.0", "/tmp/_e4.jpg"))
        except Exception:
            continue
        n += 1
        for k in chaves:
            presentes[k] += 1 if r.get(k) else 0
    faltando = [k for k in chaves if n and presentes[k] < n * 0.5]
    ok = n > 0 and len(chaves) - len(faltando) >= 5
    registrar("E4 aderencia a especificacao", ok,
              f"{len(chaves) - len(faltando)}/6 elementos presentes"
              + (f"; faltando: {', '.join(faltando)}" if faltando else ""))


# ---------------- E11: dominante de cor (marca) ----------------
def e11_cor(clipes, p10_min=-15.0):
    """A marca e azul-hora. O defeito real e uma LAVAGEM VERMELHA tomando o plano; medimos
    pela profundidade da excursao (decil inferior de UAVG-VAVG), nao pela media nem pela
    oscilacao - oscilacao reprova push-in legitimo (pele em close desloca a cor).
    Calibrado: clipes entregues ficam entre +3.6 e -10.8; um clipe lavado de vermelho deu -26.7."""
    falhas, detalhes = [], []
    for c in clipes:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-i", c, "-vf",
                            "select='not(mod(n,12))',signalstats,metadata=print",
                            "-f", "null", "-"], capture_output=True, text=True)
        g = lambda k: [float(m) for m in re.findall(rf"signalstats\.{k}=([\d.]+)", p.stderr)]
        u, v = g("UAVG"), g("VAVG")
        if not u or len(u) != len(v):
            falhas.append(f"{os.path.basename(c)}: sem leitura de cor")
            continue
        az = sorted(a - b for a, b in zip(u, v))
        p10 = az[len(az) // 10]
        detalhes.append(f"{os.path.basename(c)}: p10 {p10:+.1f}")
        if p10 < p10_min:
            falhas.append(f"{os.path.basename(c)}: lavagem vermelha (p10 {p10:+.1f} < {p10_min:+.0f})")
    registrar("E11 dominante de cor", not falhas,
              "sem lavagem vermelha - " + ", ".join(detalhes) if not falhas
              else "; ".join(falhas[:3]))


# ---------------- E10: cortes internos ----------------
def e10_cortes(clipes):
    """Um clipe deve ser um plano continuo. Salto grande entre frames vizinhos = corte."""
    import numpy as np
    from PIL import Image
    achados = []
    for c in clipes:
        d = "/tmp/_e10"
        subprocess.run(["rm", "-rf", d], check=False)
        os.makedirs(d, exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", c,
                        "-vf", "fps=8,scale=160:280", f"{d}/f%03d.png"], check=True, capture_output=True)
        fs = sorted(os.listdir(d))
        F = [np.asarray(Image.open(f"{d}/{x}").convert("L"), dtype=float) for x in fs]
        difs = [np.abs(F[i] - F[i - 1]).mean() for i in range(1, len(F))]
        if not difs:
            continue
        med = float(np.median(difs)) or 1e-6
        pico = max(difs)
        razao = pico / med
        if razao > CORTE_RAZAO_MAX:
            achados.append(f"{os.path.basename(c)}: corte em t={difs.index(pico) / 8:.1f}s ({razao:.0f}x a mediana)")
    registrar("E10 sem cortes internos", not achados,
              "todos os clipes sao plano continuo" if not achados else "; ".join(achados[:4]))


# ---------------- E9: orientacao dos personagens ----------------
P_ORI = """Responda APENAS JSON sobre este frame:
{"mulher_de_cabeca_para_baixo": bool, "cabeca_dela_acima_dos_pes": bool,
 "homem_em_pe_no_chao": bool, "descricao": str}
"mulher_de_cabeca_para_baixo" e true se a cabeca dela estiver mais baixa que os quadris/pes,
ou se ela aparecer invertida no quadro."""


def e9_orientacao(clipes, esperado="cabeca_para_cima"):
    """esperado: 'cabeca_para_cima' (padrao) ou 'invertida' (bloco em que ela flutua de
    cabeca para baixo de proposito). Sem isso o eval reprovaria a cena pedida."""
    falhas = []
    for c in clipes:
        for t in ("2.0", "5.0", "7.0"):
            try:
                r = _llm(P_ORI, _frame(c, t, "/tmp/_e9.jpg"))
            except Exception:
                continue
            invertida = bool(r.get("mulher_de_cabeca_para_baixo")) or not r.get("cabeca_dela_acima_dos_pes")
            if esperado == "invertida" and not invertida:
                falhas.append(f"{os.path.basename(c)}@{t}s NAO esta invertida")
            elif esperado != "invertida" and invertida:
                falhas.append(f"{os.path.basename(c)}@{t}s invertida")
    alvo = "de cabeca para baixo" if esperado == "invertida" else "com a cabeca para cima"
    registrar("E9 orientacao dos personagens", not falhas,
              f"ela sempre {alvo}, como esperado" if not falhas
              else f"{len(falhas)} frame(s): " + " | ".join(falhas[:4]))


# ---------------- E5: continuidade ----------------
def e5_continuidade(clipes):
    import numpy as np
    from PIL import Image
    problemas = []
    for i in range(len(clipes) - 1):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-sseof", "-0.1",
                        "-i", clipes[i], "-frames:v", "1", "-vf", "scale=160:280", "/tmp/_a.png"],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-t", "0.1",
                        "-i", clipes[i + 1], "-frames:v", "1", "-vf", "scale=160:280", "/tmp/_b.png"],
                       check=True, capture_output=True)
        a = np.asarray(Image.open("/tmp/_a.png").convert("L"), dtype=float)
        b = np.asarray(Image.open("/tmp/_b.png").convert("L"), dtype=float)
        d_brilho, d_img = abs(a.mean() - b.mean()), np.abs(a - b).mean()
        if d_brilho > BRILHO_DELTA_MAX or d_img > EMENDA_DIF_MAX:
            problemas.append(f"emenda {i + 1}->{i + 2}: brilho {d_brilho:.1f}, dif {d_img:.1f}")
    registrar("E5 continuidade das emendas", not problemas,
              "todas dentro do limite" if not problemas else "; ".join(problemas))


# ---------------- E6: exposicao ----------------
def e6_exposicao(clipes):
    lums = [_luma(c) for c in clipes]
    fora = [f"{os.path.basename(c)}={l:.0f}" for c, l in zip(clipes, lums)
            if not EXPOSICAO_MIN <= l <= EXPOSICAO_MAX]
    desvio = max(lums) - min(lums) if lums else 0
    ok = not fora and desvio <= EXPOSICAO_DESVIO_MAX
    registrar("E6 exposicao", ok,
              f"luminancias {[round(l) for l in lums]}, desvio {desvio:.0f} "
              f"(faixa {EXPOSICAO_MIN:.0f}-{EXPOSICAO_MAX:.0f}, desvio max {EXPOSICAO_DESVIO_MAX:.0f})"
              + (f"; fora: {', '.join(fora)}" if fora else ""))


# ---------------- E7: audio ----------------
def e7_audio(final, trilha):
    import wave, struct
    def env(src, dst, t=None):
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src]
        if t:
            cmd += ["-t", str(t)]
        subprocess.run(cmd + ["-vn", "-ac", "1", "-ar", "8000", dst], check=True, capture_output=True)
        w = wave.open(dst); n = w.getnframes(); sr = w.getframerate()
        d = struct.unpack("<%dh" % n, w.readframes(n)); w.close()
        s = sr // 8
        return [math.sqrt(sum(x * x for x in d[i:i + s]) / max(1, len(d[i:i + s]))) for i in range(0, len(d) - s, s)]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", final], capture_output=True, text=True).stdout.strip())
    a, b = env(final, "/tmp/_fa.wav"), env(trilha, "/tmp/_fb.wav", t=dur)
    m = min(len(a), len(b)); a, b = a[:m], b[:m]
    ma, mb = sum(a) / m, sum(b) / m
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a)); vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    corr = cov / (va * vb) if va and vb else 0
    registrar("E7 audio alinhado", corr >= AUDIO_CORR_MIN, f"correlacao {corr:.4f} (minimo {AUDIO_CORR_MIN})")


# ---------------- E8: tecnico ----------------
def e8_tecnico(final):
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", final],
        capture_output=True, text=True).stdout)
    streams = info.get("streams", [])
    tem_v = any(s.get("codec_type") == "video" for s in streams)
    tem_a = any(s.get("codec_type") == "audio" for s in streams)
    dur = float(info["format"]["duration"])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", final, "-vf",
                        "blackdetect=d=0.15:pix_th=0.10", "-f", "null", "-"], capture_output=True, text=True)
    pretos = "black_start" in p.stderr
    ok = tem_v and tem_a and not pretos
    registrar("E8 tecnico", ok, f"{dur:.2f}s, video={tem_v}, audio={tem_a}, frames pretos={pretos}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clipes", nargs="*", default=[])
    ap.add_argument("--final")
    ap.add_argument("--trilha")
    ap.add_argument("--ref-maia")
    ap.add_argument("--ref-vampiro")
    ap.add_argument("--controle", nargs=2)
    ap.add_argument("--so", nargs="*", help="rodar apenas alguns evals, ex: E1 E2")
    ap.add_argument("--luz-min", type=float, default=None,
                    help="piso de luminancia do E6 (default 45, calibrado em cena iluminada; praia noturna pede ~30)")
    ap.add_argument("--pessoas", type=int, default=2,
                    help="quantas pessoas o E1 deve exigir em cada frame")
    ap.add_argument("--orientacao", default="cabeca_para_cima",
                    choices=["cabeca_para_cima", "invertida"],
                    help="orientacao esperada da personagem neste bloco")
    a = ap.parse_args()
    global PESSOAS_ESPERADAS, EXPOSICAO_MIN
    PESSOAS_ESPERADAS = a.pessoas
    if a.luz_min is not None:
        EXPOSICAO_MIN = a.luz_min
    quer = lambda e: not a.so or e in a.so

    if a.clipes:
        if quer("E1"):
            e1_cena(a.clipes)
        if quer("E2"):
            e2_identidade(a.clipes, {"maia": a.ref_maia, "vampiro": a.ref_vampiro}, a.controle)
        if quer("E3"):
            e3_tracos(a.clipes)
        if quer("E4"):
            e4_spec(a.clipes)
        if quer("E9"):
            e9_orientacao(a.clipes, a.orientacao)
        if quer("E11"):
            e11_cor(a.clipes)
        if quer("E10"):
            e10_cortes(a.clipes)
        if quer("E5") and len(a.clipes) > 1:
            e5_continuidade(a.clipes)
        if quer("E6"):
            e6_exposicao(a.clipes)
    if a.final:
        if quer("E7") and a.trilha:
            e7_audio(a.final, a.trilha)
        if quer("E8"):
            e8_tecnico(a.final)

    if not resultados:
        print("\nERRO: nenhum eval foi executado. Um gate que nao avalia nada nao aprova nada.\n"
              "Passe --clipes e/ou --final (e --trilha para E7).", file=sys.stderr)
        sys.exit(2)
    esperados = set(a.so) if a.so else None
    if esperados:
        rodados = {r[0].split()[0] for r in resultados}
        faltando = esperados - rodados
        if faltando:
            print(f"\nERRO: evals pedidos mas nao executados: {', '.join(sorted(faltando))} "
                  f"(faltou argumento de entrada?)", file=sys.stderr)
            sys.exit(2)
    falhas = [r for r in resultados if not r[1]]
    print(f"\n{'REPROVADO' if falhas else 'APROVADO'}: {len(falhas)} de {len(resultados)} evals com falha")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
