"""Aplica as decisoes da revisao (pagina de revisao / chat) ao projeto do Reel.

Arquivos do projeto (``projects/<reel>/``), todos gravados de forma atomica::

    cortes.json    {"cuts": [...somente cortes ATIVOS...]}  (render consome sem mudanca)
    legendas.json  {"edits": [{"idx", "base_text", "text"}]}  edicoes manuais de legenda,
                   por indice da frase gerada pelos cortes ATUAIS; valem so enquanto
                   ``base_text`` for o texto automatico da frase (senao "obsoleta")
    revisao.json   {"removed_cuts": [...cortes que o revisor removeu...],
                   "graphics": {"<id>": "keep"|"drop"}, "notes": [{"t", "text"}]}
    review.json    visao de leitura para a pagina de revisao (``build``); ``graphics``
                   repete as decisoes {id: keep|drop} e ``cards`` lista os cards de
                   ``graficos.json`` [{id, title, at, dur, decision}] por instante

``entrada.*`` e ``transcricao.json`` nunca sao alterados.

Decisoes (``apply``): ``cuts_removed`` e ``cuts_added`` sao deltas; ``caption_edits``
e ``graphics`` sao mesclados por chave; ``notes`` SUBSTITUI a lista inteira. Aplicar
as mesmas decisoes de novo nao muda nada (id ja removido e corte ja ativo sao no-op).
Corte novo: kind "manual", id ``c<maior N + 1>`` (ids de cortes removidos contam
como usados, nunca reaproveitados). Duplicado exato ou contido em corte ativo e
ignorado; sobreposto/adjacente a outro corte *manual* e fundido nele (uniao, mantem
o id mais antigo); sobreposto parcialmente a corte automatico fica separado
(``cut.keep_segments`` ja tolera sobreposicao).
Tudo e validado antes (inclusive o formato das legendas editadas); se algo falha,
nada e gravado.

Uso: python3 -I scripts/review_apply.py apply <projeto> <decisoes.json>
     python3 -I scripts/review_apply.py build <projeto>      (grava review.json)
Saida: 0 ok; 1 erro (mensagem ``erro: ...``).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402
import re  # noqa: E402

import captions  # noqa: E402
import common  # noqa: E402
import cut  # noqa: E402
import graphics as graphicsmod  # noqa: E402
import render  # noqa: E402

DECISION_KEYS = {"cuts_removed", "cuts_added", "caption_edits", "graphics", "notes"}
_ASS_CODE = re.compile(r"[\\{}]")
MAX_CAPTION_LINES = 2  # como as frases automaticas (captions.phrases)


class ReviewError(Exception):
    """Decisao de revisao invalida."""


def _load_state(project: Path):
    entrada = render._find_entrada(project)  # noqa: F841  (so confirma que o projeto existe)
    duration, words, cuts = render._load_inputs(project)
    edits = render.load_edits(project)
    rev_path = project / "revisao.json"
    rev = render._read_json(rev_path) if rev_path.exists() else {}
    removed = rev.get("removed_cuts", [])
    graphics = rev.get("graphics", {})
    notes = rev.get("notes", [])
    if not (isinstance(removed, list) and isinstance(graphics, dict) and isinstance(notes, list)):
        raise render.ProjectError("revisao.json invalido")
    for i, c in enumerate(removed):
        if not (isinstance(c, dict) and isinstance(c.get("id"), str)
                and common.is_num(c.get("start")) and common.is_num(c.get("end"))):
            raise render.ProjectError(f"revisao.json invalido: removed_cuts[{i}] precisa ser "
                                      f"{{id, start, end, kind}} com start/end numericos, nao {c!r}")
    active_ids = {c.get("id") for c in cuts}
    removed = _dedupe_by_id([c for c in removed if c.get("id") not in active_ids])
    return duration, words, cuts, edits, removed, graphics, notes


def _phrases_for(duration: float, words: list, cuts: list) -> list:
    return captions.phrases(captions.remap(words, cut.keep_segments(duration, cuts)))


def _id_num(c: dict) -> int:
    m = re.fullmatch(r"c(\d+)", str(c.get("id", "")))
    return int(m.group(1)) if m else 10**9


def _next_id(*lists) -> str:
    top = 0
    for lst in lists:
        for c in lst:
            m = re.fullmatch(r"c(\d+)", str(c.get("id", "")))
            if m:
                top = max(top, int(m.group(1)))
    return f"c{top + 1}"


def _add_cuts(duration: float, active: list, removed: list, added) -> tuple[list, list]:
    if not isinstance(added, list):
        raise ReviewError("cuts_added deve ser uma lista de {start, end}")
    active = [dict(c) for c in active]
    absorbed: list = []
    for item in added:
        if not (isinstance(item, dict) and common.is_num(item.get("start")) and common.is_num(item.get("end"))):
            raise ReviewError(f"corte novo invalido: {item!r} (precisa de start/end numericos)")
        s, e = float(item["start"]), float(item["end"])
        if not (0 <= s < e <= duration):
            raise ReviewError(
                f"corte novo fora do intervalo: {s}-{e} (precisa 0 <= start < end <= {duration})")
        s, e = round(s, 3), round(e, 3)
        if any(c["start"] <= s and e <= c["end"] for c in active):
            continue  # duplicado exato ou contido em corte ativo: nada a fazer
        touching = [c for c in active if c.get("kind") == "manual"
                    and c["start"] <= e and s <= c["end"]]
        for m in touching:
            s, e = min(s, m["start"]), max(e, m["end"])
            active.remove(m)
        if touching:
            cid = min(touching, key=_id_num)["id"]
            absorbed += [m for m in touching if m["id"] != cid]  # historico reversivel
        else:
            cid = _next_id(active, removed, absorbed)
        active.append({"id": cid, "start": s, "end": e, "kind": "manual"})
    active.sort(key=lambda c: (c["start"], c["end"]))
    return active, absorbed


def _dedupe_by_id(cuts: list) -> list:
    seen, out = set(), []
    for c in cuts:
        if c.get("id") not in seen:
            seen.add(c.get("id"))
            out.append(c)
    return out


def _parse_edits(raw) -> dict:
    """``{idx: texto}`` (plano B / conversa) ou ``{idx: {"text", "base_text"}}`` (pagina):
    -> ``{idx: (texto, base_text ou None)}``."""
    if not isinstance(raw, dict):
        raise ReviewError("caption_edits deve ser um objeto {idx: texto} ou {idx: {text, base_text}}")
    out = {}
    for k, v in raw.items():
        if isinstance(k, bool):
            raise ReviewError(f"indice de frase invalido: {k!r}")
        try:
            idx = int(k)
        except (TypeError, ValueError):
            raise ReviewError(f"indice de frase invalido: {k!r}") from None
        base = None
        if isinstance(v, dict):
            if set(v) != {"text", "base_text"} or not all(isinstance(v[x], str) for x in v):
                raise ReviewError(f"edicao da frase {idx} deve ser texto ou {{text, base_text}} (textos)")
            v, base = v["text"], v["base_text"]
        elif not isinstance(v, str):
            raise ReviewError(f"texto da frase {idx} deve ser string")
        out[idx] = (v.strip(), base)
    return out


def _parse_notes(raw) -> list:
    if not isinstance(raw, list):
        raise ReviewError("notes deve ser uma lista de {t, text}")
    out = []
    for n in raw:
        if not (isinstance(n, dict) and common.is_num(n.get("t")) and n["t"] >= 0
                and isinstance(n.get("text"), str) and n["text"].strip()):
            raise ReviewError(f"nota invalida: {n!r} (precisa t >= 0 e text nao vazio)")
        out.append({"t": n["t"], "text": n["text"]})
    return out


def apply(project: Path, decisions: dict) -> None:
    project = Path(project)
    if not isinstance(decisions, dict):
        raise ReviewError("decisoes devem ser um objeto JSON")
    unknown = set(decisions) - DECISION_KEYS
    if unknown:
        raise ReviewError(f"chaves desconhecidas nas decisoes: {', '.join(sorted(unknown))}")
    try:
        duration, words, cuts, edits, removed, graphics, notes = _load_state(project)
    except render.ProjectError as e:
        raise ReviewError(str(e)) from e

    # --- cortes (deltas) ---
    ids = decisions.get("cuts_removed", [])
    if not isinstance(ids, list):
        raise ReviewError("cuts_removed deve ser uma lista de ids")
    by_id = {c.get("id"): c for c in cuts}
    already = {c.get("id") for c in removed}  # ja removidos (inativos): aplicar de novo e no-op
    for cid in ids:
        if not isinstance(cid, str):
            raise ReviewError(f"id de corte invalido em cuts_removed: {cid!r} (use \"c1\", ...)")
        if cid not in by_id and cid not in already:
            raise ReviewError(f"corte desconhecido: {cid!r}")
    ids = [cid for cid in ids if cid in by_id]
    new_removed = removed + [by_id[cid] for cid in dict.fromkeys(ids)]
    new_cuts = [c for c in cuts if c.get("id") not in set(ids)]
    new_cuts, absorbed = _add_cuts(duration, new_cuts, new_removed, decisions.get("cuts_added", []))
    new_removed = _dedupe_by_id(new_removed + absorbed)

    # --- legendas: indices contra as frases dos cortes NOVOS ---
    phrase_list = _phrases_for(duration, words, new_cuts)
    new_edits = list(edits)
    parsed = _parse_edits(decisions.get("caption_edits", {}))
    edited = [(idx, text) for idx, (text, _seen) in parsed.items()]
    for idx, (text, seen) in parsed.items():
        if not 0 <= idx < len(phrase_list):
            raise ReviewError(f"frase {idx} fora do intervalo (0 a {len(phrase_list) - 1})")
        new_edits = [e for e in new_edits if e["idx"] != idx]
        base = phrase_list[idx]["text"]
        if seen is not None and seen != base:
            # a pagina salvou sobre outro texto automatico (cortes mudaram depois): a
            # edicao cairia em outra frase
            raise ReviewError(f"frase {idx}: o texto automatico mudou desde a revisao "
                              f"(era {seen!r}, agora {base!r}); recarregue a pagina e edite de novo")
        if text and text != base:
            new_edits.append({"idx": idx, "base_text": base, "text": text})
    new_edits.sort(key=lambda e: e["idx"])

    # --- graficos / notas ---
    raw_g = decisions.get("graphics", {})
    if not isinstance(raw_g, dict):
        raise ReviewError("graphics deve ser um objeto {id: keep|drop}")
    for gid, v in raw_g.items():
        if v not in ("keep", "drop"):
            raise ReviewError(f"grafico {gid!r}: use keep ou drop, nao {v!r}")
    new_graphics = {**graphics, **raw_g}
    new_notes = _parse_notes(decisions["notes"]) if "notes" in decisions else notes
    try:  # graficos.json invalido e erro aqui, nao so no render
        graphicsmod.load_cards(project)
    except graphicsmod.GraphicsError as e:
        raise ReviewError(str(e)) from e

    # --- formato das legendas editadas: barra invertida e chaves sao codigo de
    # legenda ASS (a legenda nao as desenha), e cada frase tem no maximo 2 linhas ---
    for idx, text in edited:
        if _ASS_CODE.search(text):
            raise ReviewError(f"legenda da frase {idx}: sem barra invertida (\\) nem chaves "
                              "({ }); a legenda nao desenha esses caracteres")
        if len(captions.display_text(text).split("\n")) > MAX_CAPTION_LINES:
            raise ReviewError(f"legenda da frase {idx}: no maximo {MAX_CAPTION_LINES} linhas")

    # --- tudo validado: grava. Ordem fixa legendas, revisao, cortes: se a ultima
    # escrita falhar, o pior caso e um corte continuar ativo (e tambem listado em
    # removed_cuts, o que _load_state descarta); nunca se perde um corte. ---
    common.write_json_atomic(project / "legendas.json", {"edits": new_edits})
    common.write_json_atomic(project / "revisao.json", {
        "removed_cuts": new_removed, "graphics": new_graphics, "notes": new_notes})
    common.write_json_atomic(project / "cortes.json", {"cuts": new_cuts})


def build_review(project: Path) -> dict:
    project = Path(project)
    duration, words, cuts, edits, removed, graphics, notes = _load_state(project)
    auto = _phrases_for(duration, words, cuts)
    shown, stale = captions.apply_edits(auto, edits)
    stale_set = set(stale)
    edited_idx = {e["idx"] for e in edits} - stale_set
    phrases = []
    for i, (a, s) in enumerate(zip(auto, shown)):
        item = {"idx": i, "text": s["text"], "start": a["start"], "end": a["end"],
                "edited": i in edited_idx, "base_text": a["text"]}
        if i in stale_set:
            item["stale"] = True
        phrases.append(item)
    all_cuts = ([{**c, "active": True} for c in cuts]
                + [{**c, "active": False} for c in removed])
    all_cuts.sort(key=lambda c: (c["start"], c["end"]))
    cards = sorted(graphicsmod.load_cards(project), key=lambda c: (c["at"], c["id"]))
    return {
        "duration": duration,
        "words": [{"i": i, "w": w["w"], "start": w["start"], "end": w["end"]}
                  for i, w in enumerate(words)],
        "cuts": all_cuts,
        "phrases": phrases,
        "orphan_edits": [e for e in edits if e["idx"] in stale_set and e["idx"] >= len(auto)],
        "graphics": graphics,
        "cards": [{"id": c["id"], "title": c["title"], "at": c["at"], "dur": c["dur"],
                   "decision": "drop" if graphics.get(c["id"]) == "drop" else "keep"}
                  for c in cards],
        "notes": notes,
        "kept_duration": round(sum(b - a for a, b in cut.keep_segments(duration, cuts)), 3),
    }


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    usage = "uso: review_apply.py apply <projeto> <decisoes.json> | review_apply.py build <projeto>"
    if not argv:
        common.fail(usage)
    cmd = argv[0]
    try:
        if cmd == "apply" and len(argv) == 3:
            try:
                decisions = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                common.fail(f"decisoes ilegiveis ({argv[2]}): {e}")
            apply(Path(argv[1]), decisions)
        elif cmd == "build" and len(argv) == 2:
            project = Path(argv[1])
            common.write_json_atomic(project / "review.json", build_review(project))
        else:
            common.fail(usage)
    except (ReviewError, render.ProjectError, OSError, ValueError) as e:
        common.fail(str(e))


if __name__ == "__main__":
    main()
