use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

#[derive(Clone)]
struct Cfg {
    bind_host: String,
    bind_port: u16,
    upstream_host: String,
    upstream_port: u16,
    upstream_chat_path: String,
    upstream_completions_path: String,
    hard_request_bytes: usize,
    hard_input_tokens: usize,
    disable_stream_over_tokens: usize,
    local_model: String,
    force_model: bool,
    auto_start_mlx: bool,
    mlx_cmd: String,
}

fn env_or<T: std::str::FromStr>(k: &str, d: T) -> T {
    env::var(k).ok().and_then(|v| v.parse::<T>().ok()).unwrap_or(d)
}

fn env_or_s(k: &str, d: &str) -> String {
    env::var(k).unwrap_or_else(|_| d.to_string())
}

fn cfg() -> Cfg {
    Cfg {
        bind_host: env_or_s("ROUTER_HOST", "127.0.0.1"),
        bind_port: env_or("ROUTER_PORT", 4000),
        upstream_host: env_or_s("UPSTREAM_HOST", "127.0.0.1"),
        upstream_port: env_or("UPSTREAM_PORT", 8080),
        upstream_chat_path: env_or_s("UPSTREAM_CHAT_PATH", "/v1/chat/completions"),
        upstream_completions_path: env_or_s("UPSTREAM_COMPLETIONS_PATH", "/v1/completions"),
        // Cline can send larger structured contexts; keep limits local-friendly but less strict.
        hard_request_bytes: env_or("HARD_REQUEST_BYTES", 3_000_000usize),
        hard_input_tokens: env_or("HARD_INPUT_TOKENS", 24_000usize),
        disable_stream_over_tokens: env_or("DISABLE_STREAM_OVER_TOKENS", 10_000usize),
        local_model: env_or_s("LOCAL_MODEL", "mlx-community/Qwen3.5-4B-MLX-8bit"),
        force_model: env_or("FORCE_MODEL", 1u8) == 1,
        auto_start_mlx: env_or("AUTO_START_MLX", 0u8) == 1,
        mlx_cmd: env_or_s(
            "MLX_CMD",
            "python -m mlx_lm.server --model mlx-community/Qwen3.5-4B-MLX-8bit --host 127.0.0.1 --port 8080",
        ),
    }
}

fn estimate_tokens(text: &str) -> usize {
    std::cmp::max(1, text.chars().count() / 4)
}

fn json_error(status: &str, code: &str, msg: &str) -> String {
    let body = format!(
        "{{\"error\":\"{}\",\"message\":\"{}\"}}",
        code,
        msg.replace('"', "'")
    );
    format!(
        "HTTP/1.1 {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        status,
        body.as_bytes().len(),
        body
    )
}

fn health_response() -> String {
    let body = "{\"status\":\"ok\",\"service\":\"local_prompt_router_rust\",\"route\":\"local_only\"}";
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.as_bytes().len(),
        body
    )
}

fn models_response(model: &str) -> String {
    let body = format!(
        "{{\"object\":\"list\",\"data\":[{{\"id\":\"{}\",\"object\":\"model\",\"created\":0,\"owned_by\":\"local\"}}]}}",
        model.replace('"', "'")
    );
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.as_bytes().len(),
        body
    )
}

fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

fn read_http_request(stream: &mut TcpStream) -> Option<(String, Vec<(String, String)>, Vec<u8>)> {
    stream.set_read_timeout(Some(Duration::from_secs(30))).ok()?;

    let mut buf = Vec::new();
    let mut tmp = [0u8; 4096];
    let mut header_end = None;

    loop {
        let n = stream.read(&mut tmp).ok()?;
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&tmp[..n]);
        if let Some(pos) = find_subsequence(&buf, b"\r\n\r\n") {
            header_end = Some(pos + 4);
            break;
        }
        if buf.len() > 8 * 1024 * 1024 {
            return None;
        }
    }

    let header_end = header_end?;
    let header_bytes = &buf[..header_end];
    let header_str = String::from_utf8_lossy(header_bytes).to_string();

    let mut lines = header_str.split("\r\n");
    let request_line = lines.next()?.to_string();

    let mut headers = Vec::new();
    let mut content_length = 0usize;
    for line in lines {
        if line.is_empty() {
            continue;
        }
        if let Some((k, v)) = line.split_once(':') {
            let key = k.trim().to_string();
            let val = v.trim().to_string();
            if key.eq_ignore_ascii_case("Content-Length") {
                content_length = val.parse::<usize>().unwrap_or(0);
            }
            headers.push((key, val));
        }
    }

    let mut body = buf[header_end..].to_vec();
    while body.len() < content_length {
        let n = stream.read(&mut tmp).ok()?;
        if n == 0 {
            break;
        }
        body.extend_from_slice(&tmp[..n]);
    }
    body.truncate(content_length);

    Some((request_line, headers, body))
}

fn parse_request_line(line: &str) -> (String, String, String) {
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() >= 3 {
        (parts[0].to_string(), parts[1].to_string(), parts[2].to_string())
    } else {
        ("".to_string(), "".to_string(), "".to_string())
    }
}

fn force_stream_false(mut body: String) -> String {
    let patterns = [
        "\"stream\":true",
        "\"stream\": true",
        "\"stream\" :true",
        "\"stream\" : true",
    ];
    for p in patterns {
        body = body.replace(p, "\"stream\": false");
    }
    body
}

fn force_model(mut body: String, model: &str) -> String {
    if let Some(i) = body.find("\"model\"") {
        if let Some(colon_rel) = body[i..].find(':') {
            let colon = i + colon_rel;
            let after = &body[colon + 1..];
            if let Some(first_q_rel) = after.find('"') {
                let first_q = colon + 1 + first_q_rel;
                if let Some(second_q_rel) = body[first_q + 1..].find('"') {
                    let second_q = first_q + 1 + second_q_rel;
                    body.replace_range(first_q + 1..second_q, model);
                    return body;
                }
            }
        }
    }

    if let Some(pos) = body.find('{') {
        let insert = format!("{{\"model\":\"{}\", ", model);
        body.replace_range(pos..=pos, &insert);
    }
    body
}

fn maybe_start_mlx(cfg: &Cfg) {
    if !cfg.auto_start_mlx {
        return;
    }
    if TcpStream::connect((cfg.upstream_host.as_str(), cfg.upstream_port)).is_ok() {
        return;
    }
    let _ = Command::new("sh")
        .arg("-lc")
        .arg(cfg.mlx_cmd.clone())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
    thread::sleep(Duration::from_millis(700));
}

fn forward_to_upstream(cfg: &Cfg, target_path: &str, body: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut s = TcpStream::connect((cfg.upstream_host.as_str(), cfg.upstream_port))?;
    s.set_read_timeout(Some(Duration::from_secs(120)))?;
    s.set_write_timeout(Some(Duration::from_secs(30)))?;

    let req = format!(
        "POST {} HTTP/1.1\r\nHost: {}:{}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        target_path, cfg.upstream_host, cfg.upstream_port, body.len()
    );
    s.write_all(req.as_bytes())?;
    s.write_all(body)?;
    s.flush()?;

    let mut resp = Vec::new();
    s.read_to_end(&mut resp)?;
    Ok(resp)
}

fn response_status_code(resp: &[u8]) -> u16 {
    let text = String::from_utf8_lossy(resp);
    if let Some(line) = text.lines().next() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() >= 2 {
            return parts[1].parse::<u16>().unwrap_or(0);
        }
    }
    0
}

fn split_http_response(resp: &[u8]) -> (String, String, Vec<u8>) {
    if let Some(idx) = find_subsequence(resp, b"\r\n\r\n") {
        let header = String::from_utf8_lossy(&resp[..idx]).to_string();
        let body = resp[idx + 4..].to_vec();
        let status_line = header.lines().next().unwrap_or("").to_string();
        return (status_line, header, body);
    }
    ("".to_string(), "".to_string(), resp.to_vec())
}

fn find_json_string_value(body: &str, key: &str) -> Option<String> {
    let k = format!("\"{}\"", key);
    let i = body.find(&k)?;
    let rest = &body[i + k.len()..];
    let c = rest.find(':')?;
    let mut s = &rest[c + 1..];
    s = s.trim_start();
    if !s.starts_with('"') {
        return None;
    }
    let mut out = String::new();
    let mut escaped = false;
    for ch in s[1..].chars() {
        if escaped {
            out.push(ch);
            escaped = false;
            continue;
        }
        if ch == '\\' {
            escaped = true;
            continue;
        }
        if ch == '"' {
            return Some(out);
        }
        out.push(ch);
    }
    None
}

fn find_json_number_literal(body: &str, key: &str) -> Option<String> {
    let k = format!("\"{}\"", key);
    let i = body.find(&k)?;
    let rest = &body[i + k.len()..];
    let c = rest.find(':')?;
    let mut s = &rest[c + 1..];
    s = s.trim_start();
    let mut lit = String::new();
    for ch in s.chars() {
        if ch.is_ascii_digit() || ch == '.' || ch == '-' {
            lit.push(ch);
        } else {
            break;
        }
    }
    if lit.is_empty() { None } else { Some(lit) }
}

fn find_json_bool_literal(body: &str, key: &str) -> Option<String> {
    let k = format!("\"{}\"", key);
    let i = body.find(&k)?;
    let rest = &body[i + k.len()..];
    let c = rest.find(':')?;
    let s = rest[c + 1..].trim_start();
    if s.starts_with("true") {
        Some("true".to_string())
    } else if s.starts_with("false") {
        Some("false".to_string())
    } else {
        None
    }
}

fn extract_chat_content(chat_body: &str) -> String {
    if let Some(i) = chat_body.find("\"message\"") {
        let tail = &chat_body[i..];
        if let Some(content) = find_json_string_value(tail, "content") {
            return content;
        }
    }
    if let Some(i) = chat_body.find("\"text\"") {
        let tail = &chat_body[i..];
        if let Some(text) = find_json_string_value(tail, "text") {
            return text;
        }
    }
    "".to_string()
}

fn completions_to_chat_json(completions_body: &str, model: &str) -> String {
    let prompt = find_json_string_value(completions_body, "prompt").unwrap_or_default();
    let max_tokens = find_json_number_literal(completions_body, "max_tokens").unwrap_or_else(|| "128".to_string());
    let stream = find_json_bool_literal(completions_body, "stream").unwrap_or_else(|| "false".to_string());
    let temperature = find_json_number_literal(completions_body, "temperature");
    let top_p = find_json_number_literal(completions_body, "top_p");

    let mut fields = vec![
        format!("\"model\":\"{}\"", model.replace('"', "'")),
        format!("\"messages\":[{{\"role\":\"user\",\"content\":\"{}\"}}]", prompt.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n")),
        format!("\"max_tokens\":{}", max_tokens),
        format!("\"stream\":{}", stream),
    ];

    if let Some(t) = temperature {
        fields.push(format!("\"temperature\":{}", t));
    }
    if let Some(tp) = top_p {
        fields.push(format!("\"top_p\":{}", tp));
    }

    format!("{{{}}}", fields.join(","))
}

fn chat_to_completions_response(chat_resp: &[u8], model_default: &str) -> Vec<u8> {
    let (status_line, _header, body_bytes) = split_http_response(chat_resp);
    let status_code = response_status_code(chat_resp);
    if status_code == 0 {
        return chat_resp.to_vec();
    }

    let body_str = String::from_utf8_lossy(&body_bytes).to_string();
    let text = extract_chat_content(&body_str).replace('"', "\\\"");
    let id = find_json_string_value(&body_str, "id").unwrap_or_else(|| "cmpl-local".to_string());
    let model = find_json_string_value(&body_str, "model").unwrap_or_else(|| model_default.to_string());
    let created = find_json_number_literal(&body_str, "created").unwrap_or_else(|| "0".to_string());

    let out_body = format!(
        "{{\"id\":\"{}\",\"object\":\"text_completion\",\"created\":{},\"model\":\"{}\",\"choices\":[{{\"text\":\"{}\",\"index\":0,\"finish_reason\":\"stop\"}}]}}",
        id.replace('"', "'"),
        created,
        model.replace('"', "'"),
        text
    );

    let status = if status_line.is_empty() { "HTTP/1.1 200 OK".to_string() } else { status_line };
    let out = format!(
        "{}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        status,
        out_body.as_bytes().len(),
        out_body
    );
    out.into_bytes()
}

fn handle_client(mut stream: TcpStream, cfg: Cfg) {
    let (request_line, _headers, body_bytes) = match read_http_request(&mut stream) {
        Some(v) => v,
        None => {
            let _ = stream.write_all(json_error("400 Bad Request", "bad_request", "Invalid HTTP request").as_bytes());
            return;
        }
    };

    let (method, path, _ver) = parse_request_line(&request_line);

    if method == "GET" && (path == "/" || path == "/health" || path == "/v1/health") {
        let _ = stream.write_all(health_response().as_bytes());
        return;
    }

    if method == "GET" && (path == "/v1/models" || path == "/models") {
        let _ = stream.write_all(models_response(&cfg.local_model).as_bytes());
        return;
    }

    let is_chat = method == "POST" && path == "/v1/chat/completions";
    let is_completions = method == "POST" && path == "/v1/completions";
    if !is_chat && !is_completions {
        let _ = stream.write_all(
            json_error(
                "404 Not Found",
                "not_found",
                "Use GET /v1/models, POST /v1/chat/completions, POST /v1/completions, or GET /health",
            )
            .as_bytes(),
        );
        return;
    }

    if body_bytes.len() > cfg.hard_request_bytes {
        let msg = format!(
            "Request too large for local budget ({} > {} bytes). Narrow scope and retry.",
            body_bytes.len(),
            cfg.hard_request_bytes
        );
        let _ = stream.write_all(json_error("413 Payload Too Large", "local_budget_exceeded", &msg).as_bytes());
        return;
    }

    let mut body = match String::from_utf8(body_bytes) {
        Ok(s) => s,
        Err(_) => {
            let _ = stream.write_all(json_error("400 Bad Request", "bad_request", "Body is not valid UTF-8 JSON").as_bytes());
            return;
        }
    };

    let tok_est = estimate_tokens(&body);
    if tok_est > cfg.hard_input_tokens {
        let msg = format!(
            "Estimated input tokens exceed local hard limit ({} > {}). Narrow scope and retry.",
            tok_est, cfg.hard_input_tokens
        );
        let _ = stream.write_all(json_error("413 Payload Too Large", "local_budget_exceeded", &msg).as_bytes());
        return;
    }

    if tok_est > cfg.disable_stream_over_tokens {
        body = force_stream_false(body);
    }

    if cfg.force_model {
        body = force_model(body, &cfg.local_model);
    }

    maybe_start_mlx(&cfg);

    if is_chat {
        match forward_to_upstream(&cfg, &cfg.upstream_chat_path, body.as_bytes()) {
            Ok(resp) => {
                let _ = stream.write_all(&resp);
            }
            Err(e) => {
                let msg = format!("Local upstream unavailable: {}", e);
                let _ = stream.write_all(
                    json_error("429 Too Many Requests", "local_temporarily_unavailable", &msg).as_bytes(),
                );
            }
        }
        return;
    }

    match forward_to_upstream(&cfg, &cfg.upstream_completions_path, body.as_bytes()) {
        Ok(resp) => {
            let code = response_status_code(&resp);
            if code == 404 || code == 405 || code == 501 {
                let chat_body = completions_to_chat_json(&body, &cfg.local_model);
                match forward_to_upstream(&cfg, &cfg.upstream_chat_path, chat_body.as_bytes()) {
                    Ok(chat_resp) => {
                        let converted = chat_to_completions_response(&chat_resp, &cfg.local_model);
                        let _ = stream.write_all(&converted);
                    }
                    Err(e) => {
                        let msg = format!("Completions fallback to chat failed: {}", e);
                        let _ = stream.write_all(
                            json_error("429 Too Many Requests", "local_temporarily_unavailable", &msg).as_bytes(),
                        );
                    }
                }
            } else {
                let _ = stream.write_all(&resp);
            }
        }
        Err(e) => {
            let msg = format!("Local upstream unavailable: {}", e);
            let _ = stream.write_all(
                json_error("429 Too Many Requests", "local_temporarily_unavailable", &msg).as_bytes(),
            );
        }
    }
}

fn main() {
    let cfg = cfg();
    let addr = format!("{}:{}", cfg.bind_host, cfg.bind_port);
    let listener = TcpListener::bind(&addr).expect("failed to bind router");

    eprintln!("local_prompt_router_rust listening on http://{}", addr);
    eprintln!(
        "forwarding chat to http://{}:{}{}",
        cfg.upstream_host, cfg.upstream_port, cfg.upstream_chat_path
    );
    eprintln!(
        "forwarding completions to http://{}:{}{}",
        cfg.upstream_host, cfg.upstream_port, cfg.upstream_completions_path
    );

    for conn in listener.incoming() {
        match conn {
            Ok(stream) => {
                let c = cfg.clone();
                thread::spawn(move || handle_client(stream, c));
            }
            Err(err) => {
                eprintln!("accept error: {}", err);
            }
        }
    }
}