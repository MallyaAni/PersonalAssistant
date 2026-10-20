# Loopback middleware between the AniOS backend and vLLM (V4.1-Flash-1017).
#
# Why: the backend has one MAIN client for the conversational reply AND for
# bounded helper calls (search planner 200 tokens, document facts 700, vision
# reasoner 1024, ...). vLLM counts thinking tokens against max_tokens, so
# MAIN_LLM_REASONING_EFFORT=high made a 1200-token design request come back
# with finish_reason=length and an EMPTY content (measured 2026-10-20). The
# backend therefore sends effort "none" and this shaper turns thinking on only
# for calls that look like the reply: a large budget, no tools, no grammar.
#
# Raw TCP splice (same design as effort-inject.py): the request is re-framed
# with a corrected Content-Length, the response is passed through verbatim so
# SSE streaming and every header reach the client exactly as vLLM sent them.
import json, os, socket, threading, time

UPSTREAM = ("127.0.0.1", 8000)
LISTEN = ("0.0.0.0", int(os.environ.get("SHAPER_PORT", "8899")))
EFFORT = os.environ.get("REPLY_REASONING_EFFORT", "high")
MIN_BUDGET = int(os.environ.get("REPLY_MIN_MAX_TOKENS", "4096"))
LOG = os.path.expanduser("~/.local/state/reply-effort-shaper.log")

def read_head(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = sock.recv(65536)
        if not c:
            return None, b""
        buf += c
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest

def shape(d):
    budget = d.get("max_tokens") or d.get("max_completion_tokens") or 0
    reply_like = (
        isinstance(budget, int) and budget >= MIN_BUDGET
        and not d.get("tools") and not d.get("response_format")
    )
    if reply_like:
        d["reasoning_effort"] = EFFORT
        kw = d.get("chat_template_kwargs")
        if isinstance(kw, dict):
            kw.pop("thinking", None)
            kw["reasoning_effort"] = EFFORT
    return reply_like, budget

def log(rec):
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass

def handle(client):
    try:
        head, rest = read_head(client)
        if head is None:
            return
        lines = head.split(b"\r\n")
        request_line = lines[0]
        headers = {}
        for ln in lines[1:]:
            k, _, v = ln.partition(b":")
            headers[k.strip().lower()] = v.strip()
        n = int(headers.get(b"content-length", b"0") or 0)
        body = rest
        while len(body) < n:
            c = client.recv(65536)
            if not c:
                break
            body += c
        path = request_line.split(b" ")[1] if b" " in request_line else b""
        if body and b"chat/completions" in path:
            try:
                d = json.loads(body)
                shaped, budget = shape(d)
                body = json.dumps(d).encode()
                log({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "shaped": shaped,
                     "max_tokens": budget, "stream": d.get("stream"),
                     "tools": bool(d.get("tools")), "grammar": bool(d.get("response_format")),
                     "effort_sent": d.get("reasoning_effort"),
                     "kwargs": d.get("chat_template_kwargs")})
            except Exception:
                pass
        out = [request_line]
        for ln in lines[1:]:
            key = ln.split(b":")[0].strip().lower()
            if key not in (b"content-length", b"connection", b"accept-encoding"):
                out.append(ln)
        out.append(b"Content-Length: " + str(len(body)).encode())
        out.append(b"Connection: close")
        up = socket.create_connection(UPSTREAM, timeout=1800)
        up.sendall(b"\r\n".join(out) + b"\r\n\r\n" + body)
        while True:
            c = up.recv(65536)
            if not c:
                break
            client.sendall(c)
        up.close()
    except Exception:
        pass
    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        client.close()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(LISTEN)
srv.listen(128)
while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
