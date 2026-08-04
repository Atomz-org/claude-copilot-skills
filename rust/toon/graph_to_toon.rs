//! graph_to_toon — Rust runtime for the Graphify → TOON context pipeline.
//!
//! ============================================================================
//! FUNCTIONALITY (the whole contract of this binary, kept here as comments)
//! ============================================================================
//!
//! Pipeline position:
//!
//!   [ Graphify AST ] ─(JSON / NODE-EDGE text)→ [ this binary ] ─(TOON)→ [ LLM context ]
//!   [ LLM response ] ─(TOON)→ [ this binary --decode ] ─(JSON)→ [ machine-parsable app ]
//!
//! This binary is the SOLE runtime of the pipeline. Build it once per clone
//! with `./scripts/build_toon_rs.sh` (plain `rustc -O`, no cargo); the
//! PreToolUse hook `scripts/hooks/toon_graphify_pipe.py` pipes through it and
//! stays silent when it is unbuilt. Behavior is pinned at the CLI level by
//! `tests/test_toon_serializer.py`, whose cases come from the TOON spec's
//! normative rules; `tests/conftest.py` builds the binary on demand when
//! `rustc` is available (GitHub's ubuntu runners ship it).
//!
//! Inbound modes (stdin is auto-sniffed; --graph reads a file instead):
//!
//!   graphify query "q" --budget 800 | graph_to_toon
//!       Parses graphify's NODE/EDGE line output into {meta, nodes, edges}
//!       and emits TOON. Traversal/TRUNCATED banner lines land in `meta`.
//!
//!   graph_to_toon --graph graphify-out/graph.json --community "Enhanza"
//!       Loads graph.json and NORMALIZES nodes/links to flat uniform rows
//!       {id,label,src,loc,community} / {source,relation,target}. Raw records
//!       differ by optional keys (`metadata`), which breaks TOON tabular
//!       eligibility — normalization is what earns the token savings.
//!       Filters: --community (substring, case-insensitive), --src-prefix,
//!       --relation (exact), --limit-nodes, --limit-edges. When any node
//!       filter is active, edges whose endpoints were dropped are dropped too.
//!
//!   some-tool | graph_to_toon
//!       Any JSON document on stdin is encoded to TOON as-is.
//!
//! Outbound mode:
//!
//!   ... | graph_to_toon --decode          TOON → strict JSON (2-space indent)
//!   --no-strict                           tolerate count/width mismatches
//!
//! Safety and reporting:
//!
//!   --passthrough    hook-safe mode: input that is neither JSON nor graphify
//!                    text is forwarded to stdout unchanged, exit 0. This is
//!                    what makes the PreToolUse auto-pipe unbreakable (e.g.
//!                    `graphify path` emits prose, not NODE/EDGE lines).
//!   --stats          "~N tokens in -> ~M tokens out" to stderr (chars/4
//!                    estimate); stdout stays pipeable.
//!   --delimiter comma|tab|pipe
//!
//! ----------------------------------------------------------------------------
//! TOON rules implemented (subset of https://github.com/toon-format/spec):
//!
//!   Encoding
//!   - Objects: `key: value`; nested objects indent by 2; an empty object is
//!     `key:` with no children; an empty document IS the empty root object.
//!   - Arrays: `key[N]: a,b,c` when every element is primitive;
//!     `key[N]{f1,f2}:` + one row per line when elements are uniform objects
//!     (same key set, all-primitive columns) — nested-uniform columns fold
//!     into the header as `outer{inner1,inner2}` with depth-first leaf order;
//!     otherwise list form `key[N]:` with `- ` items (first field of an
//!     object item rides the hyphen line; `-` alone is an empty object;
//!     `- []` is an empty array item). Empty array in value position: `key: []`.
//!   - Delimiter is declared inside the bracket: `[N]` comma, `[N\t]` tab,
//!     `[N|]` pipe; it governs inline values, header fields, and row cells.
//!   - Strings MUST be quoted when: empty; leading/trailing space or tab;
//!     equal to true/false/null; numeric-like; containing : " \ [ ] { },
//!     a control char, or the active delimiter; starting with '-' or '#'.
//!     Escapes: \\ \" \n \r \t and \uXXXX for other controls.
//!   - Keys are unquoted only when matching ^[A-Za-z_][A-Za-z0-9_.]*$.
//!   - Numbers: NaN/±Inf → null; -0 → 0; plain shortest decimal within
//!     [1e-6, 1e21); Python-style exponent form outside (1e+22, 1e-07).
//!
//!   Decoding (strict mode unless --no-strict)
//!   - Indentation must be an exact multiple of 2 spaces; tabs in the
//!     indentation column error; over-indented lines error; `#` full-line
//!     comments and blank lines are skipped.
//!   - Length markers validate: inline value count, tabular row count, row
//!     cell width vs header leaves, and list item count must equal [N].
//!   - Duplicate keys error. Keyed tabular form `[N:]{...}` errors rather
//!     than misparsing (nothing in this pipeline emits it).
//!   - `key: value` requires exactly one space after the colon, so a token
//!     like `file.md:L23` inside a list item stays a scalar. The encoder
//!     always quotes strings containing ':' so round-trips are unambiguous.
//!   - Root discovery: `[]` alone → empty array; a `[N]...` header → root
//!     array; a single non-entry line → root primitive; else root object.
//!
//! JSON is parsed and printed by hand below (ordered keys preserved) so the
//! binary builds with `rustc -O` alone — no cargo, no crates.io, keeping the
//! module self-contained for submodule consumers. Ints and floats are kept
//! distinct so `3` does not become `3.0` across a round-trip.
//! ============================================================================

use std::collections::HashSet;
use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::process::exit;

// ---------------------------------------------------------------------------
// JSON value model — Vec-backed object preserves insertion order, which TOON
// needs: tabular field order is "first element's key order".
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum Json {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(Vec<(String, Json)>),
}

impl Json {
    fn is_primitive(&self) -> bool {
        !matches!(self, Json::Arr(_) | Json::Obj(_))
    }
    fn get<'a>(&'a self, key: &str) -> Option<&'a Json> {
        if let Json::Obj(pairs) = self {
            pairs.iter().find(|(k, _)| k == key).map(|(_, v)| v)
        } else {
            None
        }
    }
    fn as_str(&self) -> Option<&str> {
        if let Json::Str(s) = self { Some(s) } else { None }
    }
}

// ---------------------------------------------------------------------------
// Hand-rolled JSON parser (recursive descent). Mirrors Python json.loads for
// the shapes this pipeline sees; integers overflowing i64 fall back to f64.
// ---------------------------------------------------------------------------

struct JsonParser {
    chars: Vec<char>,
    pos: usize,
}

impl JsonParser {
    fn parse(text: &str) -> Result<Json, String> {
        let mut p = JsonParser { chars: text.chars().collect(), pos: 0 };
        p.skip_ws();
        let v = p.value()?;
        p.skip_ws();
        if p.pos != p.chars.len() {
            return Err(format!("JSON: trailing data at char {}", p.pos));
        }
        Ok(v)
    }
    fn skip_ws(&mut self) {
        while matches!(self.chars.get(self.pos), Some(' ' | '\t' | '\n' | '\r')) {
            self.pos += 1;
        }
    }
    fn value(&mut self) -> Result<Json, String> {
        match self.chars.get(self.pos) {
            Some('{') => self.object(),
            Some('[') => self.array(),
            Some('"') => Ok(Json::Str(self.string()?)),
            Some('t') => self.literal("true", Json::Bool(true)),
            Some('f') => self.literal("false", Json::Bool(false)),
            Some('n') => self.literal("null", Json::Null),
            Some(c) if *c == '-' || c.is_ascii_digit() => self.number(),
            other => Err(format!("JSON: unexpected {:?} at char {}", other, self.pos)),
        }
    }
    fn literal(&mut self, word: &str, v: Json) -> Result<Json, String> {
        for ch in word.chars() {
            if self.chars.get(self.pos) != Some(&ch) {
                return Err(format!("JSON: bad literal at char {}", self.pos));
            }
            self.pos += 1;
        }
        Ok(v)
    }
    fn number(&mut self) -> Result<Json, String> {
        let start = self.pos;
        if self.chars.get(self.pos) == Some(&'-') {
            self.pos += 1;
        }
        while self.chars.get(self.pos).is_some_and(|c| c.is_ascii_digit()) {
            self.pos += 1;
        }
        let mut is_float = false;
        if self.chars.get(self.pos) == Some(&'.') {
            is_float = true;
            self.pos += 1;
            while self.chars.get(self.pos).is_some_and(|c| c.is_ascii_digit()) {
                self.pos += 1;
            }
        }
        if matches!(self.chars.get(self.pos), Some('e' | 'E')) {
            is_float = true;
            self.pos += 1;
            if matches!(self.chars.get(self.pos), Some('+' | '-')) {
                self.pos += 1;
            }
            while self.chars.get(self.pos).is_some_and(|c| c.is_ascii_digit()) {
                self.pos += 1;
            }
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        if !is_float {
            if let Ok(i) = text.parse::<i64>() {
                return Ok(Json::Int(i));
            }
        }
        text.parse::<f64>()
            .map(Json::Float)
            .map_err(|_| format!("JSON: bad number {:?}", text))
    }
    fn string(&mut self) -> Result<String, String> {
        self.pos += 1; // opening quote
        let mut out = String::new();
        loop {
            match self.chars.get(self.pos) {
                None => return Err("JSON: unterminated string".into()),
                Some('"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some('\\') => {
                    self.pos += 1;
                    match self.chars.get(self.pos) {
                        Some('"') => out.push('"'),
                        Some('\\') => out.push('\\'),
                        Some('/') => out.push('/'),
                        Some('b') => out.push('\u{0008}'),
                        Some('f') => out.push('\u{000C}'),
                        Some('n') => out.push('\n'),
                        Some('r') => out.push('\r'),
                        Some('t') => out.push('\t'),
                        Some('u') => {
                            let hi = self.hex4()?;
                            if (0xD800..=0xDBFF).contains(&hi) {
                                // surrogate pair
                                if self.chars.get(self.pos + 1) == Some(&'\\')
                                    && self.chars.get(self.pos + 2) == Some(&'u')
                                {
                                    self.pos += 2;
                                    let lo = self.hex4()?;
                                    let cp = 0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00);
                                    out.push(
                                        char::from_u32(cp)
                                            .ok_or("JSON: bad surrogate pair")?,
                                    );
                                } else {
                                    return Err("JSON: lone surrogate".into());
                                }
                            } else {
                                out.push(char::from_u32(hi).ok_or("JSON: bad \\u")?);
                            }
                        }
                        other => return Err(format!("JSON: bad escape {:?}", other)),
                    }
                    self.pos += 1;
                }
                Some(c) => {
                    out.push(*c);
                    self.pos += 1;
                }
            }
        }
    }
    fn hex4(&mut self) -> Result<u32, String> {
        let mut v = 0u32;
        for _ in 0..4 {
            self.pos += 1;
            let c = self.chars.get(self.pos).ok_or("JSON: short \\u escape")?;
            v = v * 16 + c.to_digit(16).ok_or("JSON: bad \\u hex digit")?;
        }
        Ok(v)
    }
    fn array(&mut self) -> Result<Json, String> {
        self.pos += 1;
        let mut items = Vec::new();
        self.skip_ws();
        if self.chars.get(self.pos) == Some(&']') {
            self.pos += 1;
            return Ok(Json::Arr(items));
        }
        loop {
            self.skip_ws();
            items.push(self.value()?);
            self.skip_ws();
            match self.chars.get(self.pos) {
                Some(',') => self.pos += 1,
                Some(']') => {
                    self.pos += 1;
                    return Ok(Json::Arr(items));
                }
                other => return Err(format!("JSON: expected , or ] got {:?}", other)),
            }
        }
    }
    fn object(&mut self) -> Result<Json, String> {
        self.pos += 1;
        let mut pairs: Vec<(String, Json)> = Vec::new();
        self.skip_ws();
        if self.chars.get(self.pos) == Some(&'}') {
            self.pos += 1;
            return Ok(Json::Obj(pairs));
        }
        loop {
            self.skip_ws();
            if self.chars.get(self.pos) != Some(&'"') {
                return Err("JSON: object key must be a string".into());
            }
            let key = self.string()?;
            self.skip_ws();
            if self.chars.get(self.pos) != Some(&':') {
                return Err("JSON: expected ':' after key".into());
            }
            self.pos += 1;
            self.skip_ws();
            let val = self.value()?;
            // last value wins, first position kept — matches Python dict update
            if let Some(slot) = pairs.iter_mut().find(|(k, _)| *k == key) {
                slot.1 = val;
            } else {
                pairs.push((key, val));
            }
            self.skip_ws();
            match self.chars.get(self.pos) {
                Some(',') => self.pos += 1,
                Some('}') => {
                    self.pos += 1;
                    return Ok(Json::Obj(pairs));
                }
                other => return Err(format!("JSON: expected , or }} got {:?}", other)),
            }
        }
    }
}

// ---------------------------------------------------------------------------
// JSON writer for --decode: 2-space indent, UTF-8 kept raw (the shape of
// json.dumps(..., indent=2, ensure_ascii=False), which downstream machine
// consumers already parse). Tests compare parsed values, not bytes.
// ---------------------------------------------------------------------------

fn write_json(v: &Json, depth: usize, out: &mut String) {
    let pad = "  ".repeat(depth);
    let pad_in = "  ".repeat(depth + 1);
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Int(i) => out.push_str(&i.to_string()),
        Json::Float(f) => out.push_str(&fmt_float(*f, true)),
        Json::Str(s) => out.push_str(&json_quote(s)),
        Json::Arr(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push_str("[\n");
            for (i, item) in items.iter().enumerate() {
                out.push_str(&pad_in);
                write_json(item, depth + 1, out);
                out.push_str(if i + 1 < items.len() { ",\n" } else { "\n" });
            }
            out.push_str(&pad);
            out.push(']');
        }
        Json::Obj(pairs) => {
            if pairs.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push_str("{\n");
            for (i, (k, val)) in pairs.iter().enumerate() {
                out.push_str(&pad_in);
                out.push_str(&json_quote(k));
                out.push_str(": ");
                write_json(val, depth + 1, out);
                out.push_str(if i + 1 < pairs.len() { ",\n" } else { "\n" });
            }
            out.push_str(&pad);
            out.push('}');
        }
    }
}

fn json_quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{0008}' => out.push_str("\\b"),
            '\u{000C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

// ---------------------------------------------------------------------------
// Shared scalar rules
// ---------------------------------------------------------------------------

/// Number text. TOON rules: NaN/±Inf → null, -0 → 0, plain decimal within
/// [1e-6, 1e21), Python-style exponent outside (1e+22, 1e-07). `json_mode`
/// keeps NaN → null too (Python's json can emit NaN; ours never does).
fn fmt_float(f: f64, _json_mode: bool) -> String {
    if f.is_nan() || f.is_infinite() {
        return "null".into();
    }
    if f == 0.0 {
        return "0".into(); // covers -0.0: IEEE -0.0 == 0.0
    }
    let a = f.abs();
    if (1e-6..1e21).contains(&a) {
        format!("{}", f) // Rust Display: shortest round-trip, no exponent here
    } else {
        // "{:e}" gives 1e22 / 1.5e-7; Python repr gives 1e+22 / 1.5e-07
        let s = format!("{:e}", f);
        let (mant, exp) = s.split_once('e').expect("exponent form");
        let (sign, digits) = match exp.strip_prefix('-') {
            Some(d) => ('-', d),
            None => ('+', exp.trim_start_matches('+')),
        };
        format!("{}e{}{:0>2}", mant, sign, digits)
    }
}

/// Full-match [+-]?digits(.digits)?([eE][+-]?digits)? — the spec's
/// "numeric-like" test that forces quoting on strings such as "42".
fn is_numeric_like(s: &str) -> bool {
    let b: Vec<char> = s.chars().collect();
    let mut i = 0;
    if matches!(b.get(i), Some('+' | '-')) {
        i += 1;
    }
    let d0 = i;
    while b.get(i).is_some_and(|c| c.is_ascii_digit()) {
        i += 1;
    }
    if i == d0 {
        return false;
    }
    if b.get(i) == Some(&'.') {
        i += 1;
        let d1 = i;
        while b.get(i).is_some_and(|c| c.is_ascii_digit()) {
            i += 1;
        }
        if i == d1 {
            return false;
        }
    }
    if matches!(b.get(i), Some('e' | 'E')) {
        i += 1;
        if matches!(b.get(i), Some('+' | '-')) {
            i += 1;
        }
        let d2 = i;
        while b.get(i).is_some_and(|c| c.is_ascii_digit()) {
            i += 1;
        }
        if i == d2 {
            return false;
        }
    }
    i == b.len()
}

fn is_int_literal(s: &str) -> bool {
    let rest = s.strip_prefix(['+', '-']).unwrap_or(s);
    !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit())
}

// ---------------------------------------------------------------------------
// TOON encoder
// ---------------------------------------------------------------------------

struct Encoder {
    delimiter: char,
    indent: usize,
}

/// Field tree for tabular headers: Leaf = primitive column, Node = a
/// nested-uniform column folded as `name{...}` with depth-first leaves.
enum FieldTree {
    Leaf(String),
    Node(String, Vec<FieldTree>),
}

impl Encoder {
    fn pad(&self, depth: usize) -> String {
        " ".repeat(self.indent * depth)
    }

    fn scalar(&self, v: &Json) -> Result<String, String> {
        Ok(match v {
            Json::Null => "null".into(),
            Json::Bool(b) => if *b { "true" } else { "false" }.into(),
            Json::Int(i) => i.to_string(),
            Json::Float(f) => fmt_float(*f, false),
            Json::Str(s) => self.string(s),
            _ => return Err("scalar() called on a container".into()),
        })
    }

    // The quoting MUST-list from the spec, verbatim (see module header).
    fn needs_quote(&self, s: &str) -> bool {
        if s.is_empty() || s != s.trim_matches([' ', '\t']) {
            return true;
        }
        if matches!(s, "true" | "false" | "null") || is_numeric_like(s) {
            return true;
        }
        if s.chars().any(|c| {
            matches!(c, ':' | '"' | '\\' | '[' | ']' | '{' | '}') || (c as u32) < 0x20
        }) {
            return true;
        }
        s.contains(self.delimiter) || s.starts_with('-') || s.starts_with('#')
    }

    fn quote(&self, s: &str) -> String {
        let mut out = String::with_capacity(s.len() + 2);
        out.push('"');
        for ch in s.chars() {
            match ch {
                '\\' => out.push_str("\\\\"),
                '"' => out.push_str("\\\""),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
                c => out.push(c),
            }
        }
        out.push('"');
        out
    }

    fn string(&self, s: &str) -> String {
        if self.needs_quote(s) { self.quote(s) } else { s.to_string() }
    }

    fn key(&self, k: &str) -> String {
        let unquoted_ok = {
            let mut chars = k.chars();
            match chars.next() {
                Some(c) if c.is_ascii_alphabetic() || c == '_' => {
                    chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.')
                }
                _ => false,
            }
        };
        if unquoted_ok { k.to_string() } else { self.quote(k) }
    }

    fn delim_symbol(&self) -> &'static str {
        match self.delimiter {
            '\t' => "\t",
            '|' => "|",
            _ => "",
        }
    }

    fn object_body(&self, pairs: &[(String, Json)], depth: usize, lines: &mut Vec<String>)
        -> Result<(), String>
    {
        for (k, v) in pairs {
            let key = self.key(k);
            match v {
                Json::Obj(inner) => {
                    lines.push(format!("{}{}:", self.pad(depth), key));
                    self.object_body(inner, depth + 1, lines)?; // empty → no children
                }
                Json::Arr(arr) => self.array(Some(&key), arr, depth, lines)?,
                _ => lines.push(format!("{}{}: {}", self.pad(depth), key, self.scalar(v)?)),
            }
        }
        Ok(())
    }

    fn array(&self, key: Option<&str>, arr: &[Json], depth: usize, lines: &mut Vec<String>)
        -> Result<(), String>
    {
        let prefix = self.pad(depth);
        if arr.is_empty() {
            lines.push(match key {
                Some(k) => format!("{}{}: []", prefix, k),
                None => format!("{}[]", prefix),
            });
            return Ok(());
        }
        let head = key.unwrap_or("");
        let dsym = self.delim_symbol();
        if arr.iter().all(Json::is_primitive) {
            let cells: Result<Vec<String>, String> =
                arr.iter().map(|v| self.scalar(v)).collect();
            lines.push(format!(
                "{}{}[{}{}]: {}",
                prefix, head, arr.len(), dsym,
                cells?.join(&self.delimiter.to_string())
            ));
            return Ok(());
        }
        if let Some(fields) = tabular_fields(arr) {
            lines.push(format!(
                "{}{}[{}{}]{{{}}}:",
                prefix, head, arr.len(), dsym, self.render_fields(&fields)
            ));
            let row_pad = self.pad(depth + 1);
            for element in arr {
                let mut cells = Vec::new();
                leaf_values(element, &fields, &mut cells);
                let rendered: Result<Vec<String>, String> =
                    cells.iter().map(|v| self.scalar(v)).collect();
                lines.push(format!("{}{}", row_pad, rendered?.join(&self.delimiter.to_string())));
            }
            return Ok(());
        }
        lines.push(format!("{}{}[{}{}]:", prefix, head, arr.len(), dsym));
        self.list_items(arr, depth + 1, lines)
    }

    // List form: primitives on the hyphen; nested arrays graft their keyless
    // header onto the hyphen; object items put their FIRST field on the
    // hyphen line with continuation fields one level deeper; `-` alone is {}.
    fn list_items(&self, arr: &[Json], depth: usize, lines: &mut Vec<String>)
        -> Result<(), String>
    {
        let prefix = self.pad(depth);
        for item in arr {
            match item {
                v if v.is_primitive() => {
                    lines.push(format!("{}- {}", prefix, self.scalar(v)?));
                }
                Json::Arr(inner) => {
                    let mut sub = Vec::new();
                    self.array(None, inner, depth, &mut sub)?;
                    let first = sub[0][prefix.len()..].to_string();
                    lines.push(format!("{}- {}", prefix, first));
                    lines.extend(sub.into_iter().skip(1));
                }
                Json::Obj(pairs) => {
                    if pairs.is_empty() {
                        lines.push(format!("{}-", prefix));
                        continue;
                    }
                    let mut body = Vec::new();
                    self.object_body(pairs, depth + 1, &mut body)?;
                    let first_pad = self.pad(depth + 1);
                    let first = body[0][first_pad.len()..].to_string();
                    lines.push(format!("{}- {}", prefix, first));
                    lines.extend(body.into_iter().skip(1));
                }
                _ => unreachable!(),
            }
        }
        Ok(())
    }

    fn render_fields(&self, tree: &[FieldTree]) -> String {
        tree.iter()
            .map(|f| match f {
                FieldTree::Leaf(name) => self.key(name),
                FieldTree::Node(name, sub) =>
                    format!("{}{{{}}}", self.key(name), self.render_fields(sub)),
            })
            .collect::<Vec<_>>()
            .join(&self.delimiter.to_string())
    }
}

/// Tabular eligibility: every element a non-empty object with the same key
/// set; each column either all-primitive (Leaf) or all non-empty objects that
/// are recursively uniform (Node). Any other shape → None → list form.
fn tabular_fields(arr: &[Json]) -> Option<Vec<FieldTree>> {
    let first = match arr.first() {
        Some(Json::Obj(pairs)) if !pairs.is_empty() => pairs,
        _ => return None,
    };
    let keys: Vec<&String> = first.iter().map(|(k, _)| k).collect();
    let key_set: HashSet<&String> = keys.iter().copied().collect();
    for row in arr {
        match row {
            Json::Obj(pairs) if !pairs.is_empty() => {
                if pairs.len() != keys.len()
                    || !pairs.iter().all(|(k, _)| key_set.contains(k))
                {
                    return None;
                }
            }
            _ => return None,
        }
    }
    let mut tree = Vec::new();
    for k in keys {
        let column: Vec<&Json> = arr.iter().map(|row| row.get(k).unwrap()).collect();
        if column.iter().all(|v| v.is_primitive()) {
            tree.push(FieldTree::Leaf(k.clone()));
        } else if column
            .iter()
            .all(|v| matches!(v, Json::Obj(p) if !p.is_empty()))
        {
            let owned: Vec<Json> = column.into_iter().cloned().collect();
            match tabular_fields(&owned) {
                Some(sub) => tree.push(FieldTree::Node(k.clone(), sub)),
                None => return None,
            }
        } else {
            return None;
        }
    }
    Some(tree)
}

fn leaf_values<'a>(element: &'a Json, tree: &[FieldTree], out: &mut Vec<&'a Json>) {
    for field in tree {
        match field {
            FieldTree::Leaf(name) => out.push(element.get(name).unwrap()),
            FieldTree::Node(name, sub) => leaf_values(element.get(name).unwrap(), sub, out),
        }
    }
}

fn encode_toon(v: &Json, delimiter: char, indent: usize) -> Result<String, String> {
    let enc = Encoder { delimiter, indent };
    let mut lines = Vec::new();
    match v {
        Json::Obj(pairs) => enc.object_body(pairs, 0, &mut lines)?,
        Json::Arr(arr) => enc.array(None, arr, 0, &mut lines)?,
        other => lines.push(enc.scalar(other)?),
    }
    Ok(lines.join("\n"))
}

// ---------------------------------------------------------------------------
// TOON decoder
// ---------------------------------------------------------------------------

struct Line {
    depth: usize,
    content: Vec<char>,
    number: usize,
}

struct Bracket {
    n: usize,
    delimiter: char,
    fields_raw: Option<Vec<char>>,
}

struct Decoder {
    lines: Vec<Line>,
    pos: usize,
    strict: bool,
}

type Entry = (String, String, Option<Bracket>); // key, rest-after-colon, bracket

impl Decoder {
    fn new(text: &str, indent: usize, strict: bool) -> Result<Decoder, String> {
        let mut lines = Vec::new();
        for (idx, raw) in text.split('\n').enumerate() {
            let number = idx + 1;
            if raw.trim().is_empty() {
                continue;
            }
            let stripped = raw.trim_start_matches(' ');
            if stripped.starts_with('#') {
                continue; // full-line comment
            }
            if stripped.starts_with('\t') {
                return Err(format!("line {}: tab used in indentation", number));
            }
            let spaces = raw.len() - stripped.len();
            if strict && spaces % indent != 0 {
                return Err(format!(
                    "line {}: indentation of {} is not a multiple of {}",
                    number, spaces, indent
                ));
            }
            lines.push(Line {
                depth: spaces / indent,
                content: stripped.trim_end().chars().collect(),
                number,
            });
        }
        Ok(Decoder { lines, pos: 0, strict })
    }

    fn content_str(line: &Line) -> String {
        line.content.iter().collect()
    }

    fn parse(&mut self) -> Result<Json, String> {
        if self.lines.is_empty() {
            return Ok(Json::Obj(Vec::new())); // empty document == {}
        }
        let first_no = self.lines[0].number;
        if self.lines[0].depth != 0 {
            return Err(format!("line {}: document must start at depth 0", first_no));
        }
        let first_text = Self::content_str(&self.lines[0]);
        if first_text == "[]" && self.lines.len() == 1 {
            return Ok(Json::Arr(Vec::new()));
        }
        if first_text.starts_with('[') {
            let entry = self.split_key(&self.lines[0].content, first_no)?;
            match entry {
                Some((_, rest, Some(bracket))) => {
                    self.pos += 1;
                    let v = self.array_body(first_no, &rest, bracket, 0)?;
                    self.expect_exhausted()?;
                    return Ok(v);
                }
                _ => return Err(format!("line {}: malformed root array header", first_no)),
            }
        }
        if self.lines.len() == 1 {
            let entry = self.split_key(&self.lines[0].content, first_no)?;
            if entry.is_none() {
                return Ok(self.scalar(&first_text, first_no)?);
            }
        }
        let v = self.object(0)?;
        self.expect_exhausted()?;
        Ok(Json::Obj(v))
    }

    fn expect_exhausted(&self) -> Result<(), String> {
        if self.pos < self.lines.len() {
            return Err(format!(
                "line {}: unexpected content after document root",
                self.lines[self.pos].number
            ));
        }
        Ok(())
    }

    fn is_item_line(line: &Line) -> bool {
        line.content == ['-'] || line.content.starts_with(&['-', ' '])
    }

    fn object(&mut self, depth: usize) -> Result<Vec<(String, Json)>, String> {
        let mut obj: Vec<(String, Json)> = Vec::new();
        while self.pos < self.lines.len() {
            let line_depth = self.lines[self.pos].depth;
            let number = self.lines[self.pos].number;
            if line_depth < depth {
                break;
            }
            if line_depth > depth {
                return Err(format!(
                    "line {}: over-indented line (expected depth {})",
                    number, depth
                ));
            }
            if Self::is_item_line(&self.lines[self.pos]) {
                break; // list items belong to an enclosing array scope
            }
            let content = self.lines[self.pos].content.clone();
            let entry = self.split_key(&content, number)?;
            let (key, rest, bracket) = entry.ok_or(format!(
                "line {}: expected 'key: value', 'key:' or 'key[N]:' form",
                number
            ))?;
            self.pos += 1;
            let value = self.entry_value(number, &rest, bracket, depth)?;
            if obj.iter().any(|(k, _)| *k == key) {
                return Err(format!("line {}: duplicate key {:?}", number, key));
            }
            obj.push((key, value));
        }
        Ok(obj)
    }

    fn entry_value(&mut self, number: usize, rest: &str, bracket: Option<Bracket>, depth: usize)
        -> Result<Json, String>
    {
        if let Some(b) = bracket {
            return self.array_body(number, rest, b, depth);
        }
        if rest.is_empty() {
            // nested object, or empty object when nothing deeper follows
            if self.pos < self.lines.len() {
                let nxt_depth = self.lines[self.pos].depth;
                let nxt_item = Self::is_item_line(&self.lines[self.pos]);
                if nxt_depth == depth + 1 && !nxt_item {
                    return Ok(Json::Obj(self.object(depth + 1)?));
                }
                if nxt_depth > depth + 1 {
                    return Err(format!(
                        "line {}: over-indented line",
                        self.lines[self.pos].number
                    ));
                }
            }
            return Ok(Json::Obj(Vec::new()));
        }
        if rest == "[]" {
            return Ok(Json::Arr(Vec::new()));
        }
        self.scalar(rest, number)
    }

    /// (key, rest, bracket) when the content is an entry; None when it is not.
    /// A value needs exactly one space after ':'; `a:b` is not an entry.
    fn split_key(&self, content: &[char], number: usize) -> Result<Option<Entry>, String> {
        let mut i: usize;
        let key: String;
        if content.first() == Some(&'"') {
            let (k, next) = unquote(content, 0, number)?;
            key = k;
            i = next;
        } else {
            let mut j = content.len();
            for (idx, ch) in content.iter().enumerate() {
                if *ch == '[' || *ch == ':' {
                    j = idx;
                    break;
                }
            }
            key = content[..j].iter().collect();
            i = j;
            if key.is_empty() && content.get(i) == Some(&':') {
                return Ok(None); // unquoted empty key is not an entry
            }
        }
        let mut bracket = None;
        if content.get(i) == Some(&'[') {
            match self.parse_bracket(content, i, number)? {
                None => return Ok(None),
                Some((b, next)) => {
                    i = next;
                    let mut b = b;
                    if content.get(i) == Some(&'{') {
                        let (raw, next) = span_braces(content, i, number)?;
                        b.fields_raw = Some(raw);
                        i = next;
                    }
                    bracket = Some(b);
                }
            }
        }
        if content.get(i) != Some(&':') {
            return Ok(None);
        }
        let rest: Vec<char> = content[i + 1..].to_vec();
        if rest.is_empty() {
            return Ok(Some((key, String::new(), bracket)));
        }
        if rest.first() != Some(&' ') {
            return Ok(None);
        }
        Ok(Some((key, rest[1..].iter().collect(), bracket)))
    }

    /// `[N]`, `[N\t]`, `[N|]`. Keyed form `[N:]` errors; non-numeric content
    /// means "not an array header" (the caller treats the line as a scalar).
    fn parse_bracket(&self, content: &[char], i: usize, number: usize)
        -> Result<Option<(Bracket, usize)>, String>
    {
        let close = match content[i..].iter().position(|c| *c == ']') {
            Some(rel) => i + rel,
            None => return Ok(None),
        };
        let mut inner: Vec<char> = content[i + 1..close].to_vec();
        let mut delimiter = ',';
        match inner.last() {
            Some('\t') => {
                delimiter = '\t';
                inner.pop();
            }
            Some('|') => {
                delimiter = '|';
                inner.pop();
            }
            _ => {}
        }
        if inner.last() == Some(&':') {
            return Err(format!(
                "line {}: keyed tabular form '[N:]' is not supported by this codec",
                number
            ));
        }
        if inner.is_empty() || !inner.iter().all(|c| c.is_ascii_digit()) {
            return Ok(None);
        }
        let n: usize = inner.iter().collect::<String>().parse().unwrap();
        Ok(Some((Bracket { n, delimiter, fields_raw: None }, close + 1)))
    }

    fn array_body(&mut self, header_no: usize, rest: &str, bracket: Bracket, depth: usize)
        -> Result<Json, String>
    {
        let Bracket { n, delimiter, fields_raw } = bracket;
        if let Some(raw) = fields_raw {
            let tree = parse_dec_fields(&raw, delimiter, header_no)?;
            return self.rows(n, &tree, delimiter, depth + 1, header_no);
        }
        if !rest.is_empty() {
            let rest_chars: Vec<char> = rest.chars().collect();
            let cells = split_cells(&rest_chars, delimiter, header_no)?;
            if self.strict && cells.len() != n {
                return Err(format!(
                    "line {}: [{}] declared but {} value(s) present",
                    header_no, n, cells.len()
                ));
            }
            let mut out = Vec::new();
            for c in cells {
                out.push(self.scalar(&c, header_no)?);
            }
            return Ok(Json::Arr(out));
        }
        self.list_items(n, depth + 1, header_no)
    }

    fn rows(&mut self, n: usize, tree: &[DecField], delimiter: char, depth: usize,
        header_no: usize) -> Result<Json, String>
    {
        let leaves = count_dec_leaves(tree);
        let mut rows = Vec::new();
        while self.pos < self.lines.len() {
            let line = &self.lines[self.pos];
            if line.depth < depth || Self::is_item_line(line) {
                break;
            }
            if line.depth > depth {
                return Err(format!("line {}: over-indented tabular row", line.number));
            }
            let number = line.number;
            let cells = split_cells(&line.content.clone(), delimiter, number)?;
            if self.strict && cells.len() != leaves {
                return Err(format!(
                    "line {}: row has {} cell(s), header declares {}",
                    number, cells.len(), leaves
                ));
            }
            let mut values = Vec::new();
            for c in &cells {
                values.push(self.scalar(c, number)?);
            }
            let mut it = values.into_iter();
            rows.push(rebuild_dec(&mut it, tree));
            self.pos += 1;
            if rows.len() == n && !self.strict {
                break;
            }
        }
        if self.strict && rows.len() != n {
            return Err(format!(
                "line {}: [{}] declared but {} row(s) present",
                header_no, n, rows.len()
            ));
        }
        Ok(Json::Arr(rows))
    }

    fn list_items(&mut self, n: usize, depth: usize, header_no: usize)
        -> Result<Json, String>
    {
        let mut items = Vec::new();
        while self.pos < self.lines.len() {
            let (line_depth, number) =
                (self.lines[self.pos].depth, self.lines[self.pos].number);
            if line_depth < depth {
                break;
            }
            if line_depth > depth {
                return Err(format!("line {}: over-indented list item", number));
            }
            if !Self::is_item_line(&self.lines[self.pos]) {
                break;
            }
            let content = self.lines[self.pos].content.clone();
            self.pos += 1;
            if content == ['-'] {
                items.push(Json::Obj(Vec::new())); // bare hyphen == empty object
                continue;
            }
            let body: Vec<char> = content[2..].to_vec();
            let body_str: String = body.iter().collect();
            if body_str == "[]" {
                items.push(Json::Arr(Vec::new())); // `- []` == empty array item
                continue;
            }
            let entry = self.split_key(&body, number)?;
            match entry {
                Some((key, rest, Some(bracket))) if key.is_empty() => {
                    // `- [M]: ...` nested keyless array on the hyphen line
                    items.push(self.array_body(number, &rest, bracket, depth)?);
                }
                Some((key, rest, bracket)) => {
                    // object item: first field inline, continuation at depth+1
                    let first_value = self.entry_value(number, &rest, bracket, depth + 1)?;
                    let mut obj = vec![(key, first_value)];
                    for (k, v) in self.object(depth + 1)? {
                        if obj.iter().any(|(ok, _)| *ok == k) {
                            return Err(format!(
                                "line {}: duplicate key {:?} in list item",
                                number, k
                            ));
                        }
                        obj.push((k, v));
                    }
                    items.push(Json::Obj(obj));
                }
                None => items.push(self.scalar(&body_str, number)?),
            }
        }
        if self.strict && items.len() != n {
            return Err(format!(
                "line {}: [{}] declared but {} item(s) present",
                header_no, n, items.len()
            ));
        }
        Ok(Json::Arr(items))
    }

    fn scalar(&self, token: &str, number: usize) -> Result<Json, String> {
        let t = token.trim_matches(' ');
        if t.starts_with('"') {
            let chars: Vec<char> = t.chars().collect();
            let (value, end) = unquote(&chars, 0, number)?;
            let tail: String = chars[end..].iter().collect();
            if !tail.trim().is_empty() {
                return Err(format!(
                    "line {}: trailing characters after quoted string",
                    number
                ));
            }
            return Ok(Json::Str(value));
        }
        Ok(match t {
            "null" => Json::Null,
            "true" => Json::Bool(true),
            "false" => Json::Bool(false),
            _ if is_int_literal(t) => match t.parse::<i64>() {
                Ok(i) => Json::Int(i),
                Err(_) => Json::Float(t.parse::<f64>().unwrap_or(f64::NAN)),
            },
            _ if is_numeric_like(t) => Json::Float(
                t.parse::<f64>()
                    .map_err(|_| format!("line {}: bad number {:?}", number, t))?,
            ),
            _ => Json::Str(t.to_string()),
        })
    }
}

/// Decoder-side field tree parsed from a `{f1,f2{g1,g2}}` header segment.
#[derive(Debug)]
enum DecField {
    Leaf(String),
    Node(String, Vec<DecField>),
}

fn parse_dec_fields(raw: &[char], delimiter: char, number: usize)
    -> Result<Vec<DecField>, String>
{
    let mut tree = Vec::new();
    let mut i = 0usize;
    let n = raw.len();
    while i < n {
        let name: String;
        if raw[i] == '"' {
            let (v, next) = unquote(raw, i, number)?;
            name = v;
            i = next;
        } else {
            let mut j = i;
            while j < n && raw[j] != delimiter && raw[j] != '{' {
                j += 1;
            }
            name = raw[i..j].iter().collect::<String>().trim().to_string();
            i = j;
        }
        if i < n && raw[i] == '{' {
            let (inner, next) = span_braces(raw, i, number)?;
            i = next;
            tree.push(DecField::Node(name, parse_dec_fields(&inner, delimiter, number)?));
        } else {
            tree.push(DecField::Leaf(name));
        }
        if i < n {
            if raw[i] != delimiter {
                return Err(format!("line {}: malformed field list in header", number));
            }
            i += 1;
        }
    }
    Ok(tree)
}

fn count_dec_leaves(tree: &[DecField]) -> usize {
    tree.iter()
        .map(|f| match f {
            DecField::Leaf(_) => 1,
            DecField::Node(_, sub) => count_dec_leaves(sub),
        })
        .sum()
}

fn rebuild_dec(values: &mut std::vec::IntoIter<Json>, tree: &[DecField]) -> Json {
    let mut obj = Vec::new();
    for field in tree {
        match field {
            DecField::Leaf(name) => {
                obj.push((name.clone(), values.next().unwrap_or(Json::Null)));
            }
            DecField::Node(name, sub) => obj.push((name.clone(), rebuild_dec(values, sub))),
        }
    }
    Json::Obj(obj)
}

/// Quote-aware `{...}` span. Returns (inner chars, index past '}').
fn span_braces(content: &[char], i: usize, number: usize)
    -> Result<(Vec<char>, usize), String>
{
    let mut depth = 0usize;
    let mut j = i;
    while j < content.len() {
        match content[j] {
            '"' => {
                let (_, next) = unquote(content, j, number)?;
                j = next;
                continue;
            }
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return Ok((content[i + 1..j].to_vec(), j + 1));
                }
            }
            _ => {}
        }
        j += 1;
    }
    Err(format!("line {}: unterminated '{{' in tabular header", number))
}

/// Quote-aware cell split on the active delimiter. Quoted spans are kept raw
/// (including quotes); scalar() re-unquotes them.
fn split_cells(line: &[char], delimiter: char, number: usize)
    -> Result<Vec<String>, String>
{
    let mut cells = Vec::new();
    let mut buf = String::new();
    let mut i = 0usize;
    while i < line.len() {
        let ch = line[i];
        if ch == '"' {
            let (_, j) = unquote(line, i, number)?;
            buf.extend(&line[i..j]);
            i = j;
            continue;
        }
        if ch == delimiter {
            cells.push(std::mem::take(&mut buf));
            i += 1;
            continue;
        }
        buf.push(ch);
        i += 1;
    }
    cells.push(buf);
    Ok(cells)
}

/// TOON quoted-string reader. Escapes: \\ \" \n \r \t \uXXXX (with surrogate
/// pairs); anything else — including lone surrogates and running off the end
/// of the line — is an error, per the spec's decoder table.
fn unquote(s: &[char], start: usize, number: usize) -> Result<(String, usize), String> {
    if s.get(start) != Some(&'"') {
        return Err(format!("line {}: expected opening quote", number));
    }
    let mut out = String::new();
    let mut i = start + 1;
    while i < s.len() {
        match s[i] {
            '"' => return Ok((out, i + 1)),
            '\\' => {
                let nxt = *s.get(i + 1).ok_or(format!("line {}: dangling escape", number))?;
                match nxt {
                    '\\' => out.push('\\'),
                    '"' => out.push('"'),
                    'n' => out.push('\n'),
                    'r' => out.push('\r'),
                    't' => out.push('\t'),
                    'u' => {
                        let cp = hex4_at(s, i + 2, number)?;
                        if (0xD800..=0xDBFF).contains(&cp) {
                            if s.get(i + 6) == Some(&'\\') && s.get(i + 7) == Some(&'u') {
                                let lo = hex4_at(s, i + 8, number)?;
                                if (0xDC00..=0xDFFF).contains(&lo) {
                                    let c = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                    out.push(char::from_u32(c).ok_or(format!(
                                        "line {}: lone surrogate in \\u escape",
                                        number
                                    ))?);
                                    i += 12;
                                    continue;
                                }
                            }
                            return Err(format!(
                                "line {}: lone surrogate in \\u escape",
                                number
                            ));
                        }
                        if (0xDC00..=0xDFFF).contains(&cp) {
                            return Err(format!(
                                "line {}: lone surrogate in \\u escape",
                                number
                            ));
                        }
                        out.push(char::from_u32(cp).ok_or(format!(
                            "line {}: invalid \\u escape",
                            number
                        ))?);
                        i += 6;
                        continue;
                    }
                    other => {
                        return Err(format!(
                            "line {}: unsupported escape \\{}",
                            number, other
                        ))
                    }
                }
                i += 2;
            }
            c => {
                out.push(c);
                i += 1;
            }
        }
    }
    Err(format!("line {}: unterminated quoted string", number))
}

fn hex4_at(s: &[char], at: usize, number: usize) -> Result<u32, String> {
    let mut v = 0u32;
    for k in 0..4 {
        let c = s
            .get(at + k)
            .ok_or(format!("line {}: invalid \\u escape", number))?;
        v = v * 16 + c.to_digit(16).ok_or(format!("line {}: invalid \\u escape", number))?;
    }
    Ok(v)
}

fn decode_toon(text: &str, indent: usize, strict: bool) -> Result<Json, String> {
    Decoder::new(text, indent, strict)?.parse()
}

// ---------------------------------------------------------------------------
// Graphify NODE/EDGE text → {meta, nodes, edges}
//
// Non-greedy field extraction via first-occurrence splits:
//   NODE <name> [src=<src> loc=<loc> community=<community>]
//   EDGE <source> --<relation> [<KIND>]--> <target> [at=<at>]
// Banner lines "Traversal: ..." and "[!] ..." land in meta.
// ---------------------------------------------------------------------------

fn none_if_none_literal(s: &str) -> Json {
    if s.is_empty() || s == "None" {
        Json::Null
    } else {
        Json::Str(s.to_string())
    }
}

fn parse_graphify_text(text: &str) -> Json {
    let mut meta: Vec<(String, Json)> = Vec::new();
    let mut nodes = Vec::new();
    let mut edges = Vec::new();
    for raw in text.split('\n') {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        if let Some(rest) = line.strip_prefix("NODE ") {
            if let Some((node, ())) = parse_node_line(rest) {
                nodes.push(node);
                continue;
            }
        }
        if let Some(rest) = line.strip_prefix("EDGE ") {
            if let Some(edge) = parse_edge_line(rest) {
                edges.push(edge);
                continue;
            }
        }
        if let Some(rest) = line.strip_prefix("Traversal:") {
            meta.push(("traversal".into(), Json::Str(rest.trim().to_string())));
        } else if let Some(rest) = line.strip_prefix("[!]") {
            meta.push(("warning".into(), Json::Str(rest.trim().to_string())));
        }
    }
    let mut doc = Vec::new();
    if !meta.is_empty() {
        doc.push(("meta".into(), Json::Obj(meta)));
    }
    doc.push(("nodes".into(), Json::Arr(nodes)));
    doc.push(("edges".into(), Json::Arr(edges)));
    Json::Obj(doc)
}

fn parse_node_line(rest: &str) -> Option<(Json, ())> {
    // rest = "<name> [src=<src> loc=<loc> community=<community>]"
    let inner_start = rest.find(" [src=")?;
    let name = &rest[..inner_start];
    if name.is_empty() || !rest.ends_with(']') {
        return None;
    }
    let inner = &rest[inner_start + " [src=".len()..rest.len() - 1];
    let loc_at = inner.find(" loc=")?;
    let src = &inner[..loc_at];
    let after_loc = &inner[loc_at + " loc=".len()..];
    let comm_at = after_loc.find(" community=")?;
    let loc = &after_loc[..comm_at];
    let community = &after_loc[comm_at + " community=".len()..];
    Some((
        Json::Obj(vec![
            ("name".into(), Json::Str(name.to_string())),
            ("src".into(), none_if_none_literal(src)),
            ("loc".into(), none_if_none_literal(loc)),
            ("community".into(), none_if_none_literal(community)),
        ]),
        (),
    ))
}

fn parse_edge_line(rest: &str) -> Option<Json> {
    // rest = "<source> --<relation> [<KIND>]--> <target>[ at=<at>]"
    let src_end = rest.find(" --")?;
    let source = &rest[..src_end];
    let after = &rest[src_end + " --".len()..];
    let arrow = after.find("]--> ")?;
    let head = &after[..arrow]; // "<relation> [<KIND>"
    let bracket = head.rfind(" [")?;
    let relation = head[..bracket].trim();
    let kind = &head[bracket + 2..];
    if kind.is_empty() || !kind.chars().all(|c| c.is_ascii_uppercase()) {
        return None;
    }
    let tail = &after[arrow + "]--> ".len()..];
    let (target, at) = match tail.find(" at=") {
        Some(p) => (&tail[..p], Json::Str(tail[p + " at=".len()..].to_string())),
        None => (tail, Json::Null),
    };
    if source.is_empty() || target.is_empty() {
        return None;
    }
    Some(Json::Obj(vec![
        ("source".into(), Json::Str(source.to_string())),
        ("relation".into(), Json::Str(relation.to_string())),
        ("kind".into(), Json::Str(kind.to_string())),
        ("target".into(), Json::Str(target.to_string())),
        ("at".into(), at),
    ]))
}

// ---------------------------------------------------------------------------
// graph.json subset loader — normalize, filter, and count (see module header)
// ---------------------------------------------------------------------------

struct GraphFilters {
    community: Option<String>,
    src_prefix: Option<String>,
    relation: Option<String>,
    limit_nodes: Option<usize>,
    limit_edges: Option<usize>,
}

fn load_graph_subset(path: &str, f: &GraphFilters) -> Result<Json, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("cannot read {}: {}", path, e))?;
    let g = JsonParser::parse(&text)?;
    let empty = Json::Arr(Vec::new());
    let raw_nodes = match g.get("nodes") {
        Some(Json::Arr(_)) => g.get("nodes").unwrap(),
        _ => &empty,
    };
    let raw_edges = match g.get("links").or_else(|| g.get("edges")) {
        Some(Json::Arr(_)) => g.get("links").or_else(|| g.get("edges")).unwrap(),
        _ => &empty,
    };
    let (raw_nodes, raw_edges) = match (raw_nodes, raw_edges) {
        (Json::Arr(n), Json::Arr(e)) => (n, e),
        _ => unreachable!(),
    };

    let mut nodes = Vec::new();
    for rn in raw_nodes {
        let pick = |key: &str| rn.get(key).cloned().unwrap_or(Json::Null);
        let record = vec![
            ("id".to_string(), pick("id")),
            ("label".to_string(), pick("label")),
            ("src".to_string(), pick("source_file")),
            ("loc".to_string(), pick("source_location")),
            ("community".to_string(), pick("community_name")),
        ];
        if let Some(needle) = &f.community {
            let hay = record[4].1.as_str().unwrap_or("").to_lowercase();
            if !hay.contains(&needle.to_lowercase()) {
                continue;
            }
        }
        if let Some(prefix) = &f.src_prefix {
            if !record[2].1.as_str().unwrap_or("").starts_with(prefix.as_str()) {
                continue;
            }
        }
        nodes.push(Json::Obj(record));
    }
    if let Some(cap) = f.limit_nodes {
        nodes.truncate(cap);
    }
    let kept_ids: HashSet<&str> = nodes
        .iter()
        .filter_map(|n| n.get("id").and_then(Json::as_str))
        .collect();
    let filtered =
        f.community.is_some() || f.src_prefix.is_some() || f.limit_nodes.is_some();

    let mut edges = Vec::new();
    for re in raw_edges {
        let pick = |key: &str| re.get(key).cloned().unwrap_or(Json::Null);
        let record = vec![
            ("source".to_string(), pick("source")),
            ("relation".to_string(), pick("relation")),
            ("target".to_string(), pick("target")),
        ];
        if let Some(rel) = &f.relation {
            if record[1].1.as_str() != Some(rel.as_str()) {
                continue;
            }
        }
        if filtered {
            let s_in = record[0].1.as_str().is_some_and(|s| kept_ids.contains(s));
            let t_in = record[2].1.as_str().is_some_and(|s| kept_ids.contains(s));
            if !(s_in && t_in) {
                continue;
            }
        }
        edges.push(Json::Obj(record));
    }
    if let Some(cap) = f.limit_edges {
        edges.truncate(cap);
    }

    Ok(Json::Obj(vec![
        (
            "meta".into(),
            Json::Obj(vec![
                ("graph".into(), Json::Str(path.to_string())),
                ("nodes_total".into(), Json::Int(raw_nodes.len() as i64)),
                ("edges_total".into(), Json::Int(raw_edges.len() as i64)),
            ]),
        ),
        ("nodes".into(), Json::Arr(nodes)),
        ("edges".into(), Json::Arr(edges)),
    ]))
}

// ---------------------------------------------------------------------------
// CLI — flags documented in the module header
// ---------------------------------------------------------------------------

fn estimate_tokens(text: &str) -> usize {
    std::cmp::max(1, text.chars().count() / 4)
}

fn sniff_and_parse(text: &str) -> Result<Json, ()> {
    let lead = text.trim_start();
    if lead.starts_with('{') || lead.starts_with('[') {
        return JsonParser::parse(text).map_err(|_| ());
    }
    let looks_graphify = text.lines().any(|l| {
        l.starts_with("NODE ") || l.starts_with("EDGE ") || l.starts_with("Traversal: ")
    });
    if looks_graphify {
        return Ok(parse_graphify_text(text));
    }
    Err(())
}

fn usage_error(msg: &str) -> ! {
    eprintln!("graph_to_toon: {}", msg);
    exit(2);
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let mut graph: Option<String> = None;
    let mut filters = GraphFilters {
        community: None,
        src_prefix: None,
        relation: None,
        limit_nodes: None,
        limit_edges: None,
    };
    let mut delimiter = ',';
    let mut decode = false;
    let mut strict = true;
    let mut stats = false;
    let mut passthrough = false;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        let mut take = |name: &str| -> String {
            it.next().unwrap_or_else(|| usage_error(&format!("{} requires a value", name)))
        };
        match arg.as_str() {
            "--graph" => graph = Some(take("--graph")),
            "--community" => filters.community = Some(take("--community")),
            "--src-prefix" => filters.src_prefix = Some(take("--src-prefix")),
            "--relation" => filters.relation = Some(take("--relation")),
            "--limit-nodes" => {
                filters.limit_nodes =
                    Some(take("--limit-nodes").parse().unwrap_or_else(|_| {
                        usage_error("--limit-nodes expects an integer")
                    }))
            }
            "--limit-edges" => {
                filters.limit_edges =
                    Some(take("--limit-edges").parse().unwrap_or_else(|_| {
                        usage_error("--limit-edges expects an integer")
                    }))
            }
            "--delimiter" => {
                delimiter = match take("--delimiter").as_str() {
                    "comma" => ',',
                    "tab" => '\t',
                    "pipe" => '|',
                    other => usage_error(&format!("unknown delimiter {:?}", other)),
                }
            }
            "--decode" => decode = true,
            "--no-strict" => strict = false,
            "--stats" => stats = true,
            "--passthrough" => passthrough = true,
            other => usage_error(&format!("unknown argument {:?}", other)),
        }
    }

    let fail = |msg: String| -> ! {
        eprintln!("{}", msg);
        exit(1);
    };

    let (source, output) = if decode {
        let mut source = String::new();
        io::stdin().read_to_string(&mut source).unwrap_or_else(|e| fail(e.to_string()));
        let value = decode_toon(&source, 2, strict).unwrap_or_else(|e| fail(e));
        let mut out = String::new();
        write_json(&value, 0, &mut out);
        (source, out)
    } else if let Some(path) = graph {
        let doc = load_graph_subset(&path, &filters).unwrap_or_else(|e| fail(e));
        let mut source = String::new();
        write_json(&doc, 0, &mut source); // stats baseline, like Python's json.dumps
        let out = encode_toon(&doc, delimiter, 2).unwrap_or_else(|e| fail(e));
        (source, out)
    } else {
        let mut source = String::new();
        io::stdin().read_to_string(&mut source).unwrap_or_else(|e| fail(e.to_string()));
        match sniff_and_parse(&source) {
            Ok(doc) => {
                let out = encode_toon(&doc, delimiter, 2).unwrap_or_else(|e| fail(e));
                (source, out)
            }
            Err(()) => {
                if passthrough {
                    // hook-safe mode: never break the command whose output we wrap
                    print!("{}", source);
                    exit(0);
                }
                fail(
                    "graph_to_toon: stdin is neither JSON nor graphify NODE/EDGE output \
                     (use --decode for TOON input)"
                        .to_string(),
                )
            }
        }
    };

    println!("{}", output);
    if stats {
        let before = estimate_tokens(&source);
        let after = estimate_tokens(&output);
        let saved = if before > 0 {
            (1.0 - after as f64 / before as f64) * 100.0
        } else {
            0.0
        };
        let _ = writeln!(
            io::stderr(),
            "graph_to_toon: ~{} tokens in -> ~{} tokens out ({:+.0}% is savings)",
            before, after, saved
        );
    }
}
