"""PDF Düzenle — yerel web sunucusu.

Başlat:            uv run server.py
Ağda paylaş:       uv run server.py --paylas
"""

from __future__ import annotations

import argparse
import io
import secrets
import socket
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, session

import fontswap as fs

HERE = Path(__file__).resolve().parent
MAX_HISTORY = 40
SESSION_TTL = 6 * 3600  # 6 saat dokunulmayan belge bellekten silinir

app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")
app.secret_key = secrets.token_hex(16)
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024

DOCS: dict[str, dict] = {}
DOCS_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Oturum başına belge durumu
# --------------------------------------------------------------------------

def _sid() -> str:
    if "sid" not in session:
        session["sid"] = secrets.token_hex(12)
    return session["sid"]


def _state() -> dict:
    with DOCS_LOCK:
        now = time.time()
        for k in [k for k, v in DOCS.items() if now - v["t"] > SESSION_TTL]:
            DOCS.pop(k)
        st = DOCS.get(_sid())
    if st is None:
        raise fs.EditError("Önce bir PDF aç.")
    st["t"] = time.time()
    return st


def _info(st: dict) -> dict:
    return {
        "name": st["name"],
        "pages": [{"w": w, "h": h} for w, h in fs.page_sizes(st["cur"])],
        "ver": st["ver"],
        "canUndo": bool(st["history"]),
        "dirty": st["cur"] is not st["orig"],
    }


def _commit(st: dict, new_pdf: bytes) -> None:
    st["history"].append(st["cur"])
    del st["history"][:-MAX_HISTORY]
    st["cur"] = new_pdf
    st["ver"] += 1


@app.errorhandler(fs.EditError)
def _edit_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(413)
def _too_big(_):
    return jsonify(error="Dosya çok büyük (en fazla 150 MB)."), 413


# --------------------------------------------------------------------------
# Uç noktalar
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return send_file(HERE / "static" / "index.html")


@app.get("/api/fonts")
def fonts():
    out = []
    for fam, faces in fs.families().items():
        styles = [fs.split_label(f.label)[1] for f in faces]
        out.append({
            "name": fam,
            "turkish": any(f.turkish for f in faces),
            "bold": any(fs.is_bold(s) for s in styles),
            "italic": any(fs.is_italic(s) for s in styles),
        })
    out.sort(key=lambda f: f["name"].lower())
    default = fs.split_label(fs.default_font().label)[0]
    return jsonify(families=out, default=default)


@app.post("/api/open")
def open_pdf():
    f = request.files.get("file")
    if f is None:
        raise fs.EditError("Dosya gelmedi.")
    data = f.read()
    try:
        import pymupdf
        with pymupdf.open(stream=data, filetype="pdf") as d:
            if d.needs_pass:
                raise fs.EditError("Bu PDF şifreli. Önce şifresini kaldır.")
    except fs.EditError:
        raise
    except Exception:
        raise fs.EditError("Bu dosya PDF olarak açılamadı.")
    st = {"name": f.filename or "belge.pdf", "orig": data, "cur": data,
          "history": [], "ver": 0, "t": time.time(), "lock": threading.Lock()}
    with DOCS_LOCK:
        DOCS[_sid()] = st
    return jsonify(_info(st))


@app.get("/api/doc")
def doc_info():
    return jsonify(_info(_state()))


@app.get("/api/page/<int:n>.png")
def page_png(n: int):
    st = _state()
    png = fs.render_page(st["cur"], n, zoom=float(request.args.get("z", 2)))
    resp = send_file(io.BytesIO(png), mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=600"
    return resp


@app.get("/api/page/<int:n>/spans")
def page_spans(n: int):
    return jsonify(fs.span_infos(_state()["cur"], n))


@app.post("/api/edit")
def edit():
    st = _state()
    body = request.get_json(force=True)
    targets = body.get("targets") or []
    style = {k: body[k] for k in ("text", "family", "bold", "italic", "size", "color", "dx", "dy")
             if body.get(k) is not None}
    with st["lock"]:
        pdf = st["cur"]
        for t in targets:
            if t.get("ids"):
                pdf = fs.edit_spans(pdf, int(t["page"]), [int(i) for i in t["ids"]],
                                    delete=bool(body.get("delete")), **style)
        if pdf is not st["cur"]:
            _commit(st, pdf)
    return jsonify(_info(st))


@app.post("/api/add")
def add():
    st = _state()
    b = request.get_json(force=True)
    if not str(b.get("text", "")).strip():
        raise fs.EditError("Yazı boş.")
    with st["lock"]:
        new = fs.add_text_styled(st["cur"], int(b["page"]), float(b["x"]), float(b["y"]),
                                 b["text"], b.get("family") or "Arial",
                                 bool(b.get("bold")), bool(b.get("italic")),
                                 float(b.get("size") or 12), b.get("color") or "#000000")
        _commit(st, new)
    return jsonify(_info(st))


@app.post("/api/undo")
def undo():
    st = _state()
    with st["lock"]:
        if st["history"]:
            st["cur"] = st["history"].pop()
            st["ver"] += 1
    return jsonify(_info(st))


@app.get("/api/download")
def download():
    st = _state()
    name = Path(st["name"]).stem + "-duzenlendi.pdf"
    return send_file(io.BytesIO(st["cur"]), mimetype="application/pdf",
                     as_attachment=True, download_name=name)


# --------------------------------------------------------------------------

def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF Düzenle")
    ap.add_argument("--port", type=int, default=8517)
    ap.add_argument("--paylas", action="store_true",
                    help="Aynı ağdaki diğer bilgisayarların da açabilmesi için")
    ap.add_argument("--tarayici-acma", action="store_true")
    args = ap.parse_args()

    host = "0.0.0.0" if args.paylas else "127.0.0.1"
    local = f"http://localhost:{args.port}"
    print(f"\n  PDF Düzenle çalışıyor: {local}")
    if args.paylas:
        print(f"  İş arkadaşın şu adresi açsın: http://{_lan_ip()}:{args.port}")
        print("  (Aynı ağda olmalı. Bu pencere açık kaldıkça çalışır.)")
    print("  Kapatmak için bu pencerede Ctrl+C.\n")
    fs.system_fonts()  # font listesini önceden hazırla
    import logging
    import flask.cli
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # istek satırlarını gizle
    flask.cli.show_server_banner = lambda *a, **k: None
    if not args.tarayici_acma:
        threading.Timer(1.0, lambda: webbrowser.open(local)).start()
    app.run(host=host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
