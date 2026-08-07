"""A minimal YAML subset parser, used when PyYAML is not installed.

Supports what dbt YAML actually uses: block mappings and sequences, nested structures,
quoted and bare scalars, inline flow mappings `{a: b}` and sequences `[a, b]` — including
ones that continue across physical lines — block scalars `>` and `|`, comments, and the
`null`/`true`/`false`/number literals.

Deliberately NOT supported: anchors and aliases (`&a` / `*a`), multiple documents,
complex keys, and tags. dbt YAML does not use them; if a file does, install PyYAML.

Scripts that use this prefer PyYAML when it is importable — this exists so the tools
run with no install step, which is the whole point of a standard-library-only scaffold.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


class MiniYamlError(ValueError):
    pass


def parse(text: str) -> Any:
    lines = _logical_lines(text)
    value, index = _parse_block(lines, 0, -1)
    if index < len(lines):
        raise MiniYamlError(
            f"line {lines[index][2]}: unexpected content {lines[index][1]!r}"
        )
    return value


# ---------------------------------------------------------------- lexing


def _logical_lines(text: str) -> List[Tuple[int, str, int]]:
    """-> [(indent, content, line_number)] with blanks and comments removed.

    A flow collection (`[...]` / `{...}`) may continue across physical lines; the
    continuations are folded onto the line that opened it, so the parser only ever
    sees balanced flow text. Folding triggers only when the value *starts* with a
    flow opener — a stray bracket inside a plain scalar never does.
    """
    out: List[Tuple[int, str, int]] = []
    pending = 0  # open-bracket depth of an unfinished flow collection
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise MiniYamlError(f"line {number}: tab in indentation")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        content = _strip_comment(raw).rstrip()
        if not content.strip():
            continue
        if pending:
            prev_indent, prev_content, prev_number = out[-1]
            out[-1] = (prev_indent, prev_content + " " + content.strip(), prev_number)
            pending += _flow_depth_delta(content)
            if pending < 0:
                raise MiniYamlError(f"line {number}: unbalanced flow collection")
            continue
        indent = len(content) - len(content.lstrip())
        out.append((indent, content.strip(), number))
        pending = max(0, _opened_flow_depth(content.strip()))
    if pending:
        raise MiniYamlError(f"line {out[-1][2]}: unclosed flow collection")
    return out


def _opened_flow_depth(content: str) -> int:
    """Net bracket depth of the flow collection this line's value opens, if any."""
    key, sep, rest = _split_key(content)
    candidate = rest.strip() if sep else content
    if candidate.startswith("- "):
        candidate = candidate[2:].strip()
    return _flow_depth_delta(candidate) if _is_flow(candidate) else 0


def _flow_depth_delta(text: str) -> int:
    """Net `[`/`{` depth change across `text`, ignoring brackets inside quotes."""
    depth = 0
    quote: Optional[str] = None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth


def _strip_comment(line: str) -> str:
    """Remove a trailing `#` comment, respecting quotes."""
    quote: Optional[str] = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


# ---------------------------------------------------------------- parsing


def _parse_block(lines: List[Tuple[int, str, int]], index: int,
                 parent_indent: int) -> Tuple[Any, int]:
    if index >= len(lines):
        return None, index
    indent, content, _ = lines[index]
    if indent <= parent_indent:
        return None, index
    if content.startswith("- "):
        return _parse_sequence(lines, index, indent)
    if content == "-":
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_sequence(lines: List[Tuple[int, str, int]], index: int,
                    indent: int) -> Tuple[List[Any], int]:
    items: List[Any] = []
    while index < len(lines):
        cur_indent, content, number = lines[index]
        if cur_indent < indent or not (content == "-" or content.startswith("- ")):
            break
        if cur_indent > indent:
            raise MiniYamlError(f"line {number}: inconsistent sequence indentation")

        rest = content[2:].strip() if content.startswith("- ") else ""
        index += 1

        if not rest:
            value, index = _parse_block(lines, index, cur_indent)
            items.append(value)
            continue

        if ":" in rest and not _is_flow(rest):
            # `- name: x` — an inline mapping that may continue on following lines,
            # indented to the position of the key after the dash.
            synthetic = [(cur_indent + 2, rest, number)]
            child_indent = cur_indent + 2
            while index < len(lines) and lines[index][0] > cur_indent:
                synthetic.append(lines[index])
                index += 1
            value, consumed = _parse_mapping(synthetic, 0, child_indent)
            if consumed != len(synthetic):
                raise MiniYamlError(f"line {number}: could not parse sequence item")
            items.append(value)
        else:
            items.append(_scalar(rest))
    return items, index


def _parse_mapping(lines: List[Tuple[int, str, int]], index: int,
                   indent: int) -> Tuple[dict, int]:
    result: dict = {}
    while index < len(lines):
        cur_indent, content, number = lines[index]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise MiniYamlError(f"line {number}: unexpected indentation in mapping")
        if content.startswith("- "):
            break

        key, sep, rest = _split_key(content)
        if not sep:
            raise MiniYamlError(f"line {number}: expected 'key: value', got {content!r}")
        key = _scalar(key)
        rest = rest.strip()
        index += 1

        if rest in (">", "|", ">-", "|-", ">+", "|+"):
            value, index = _block_scalar(lines, index, cur_indent, rest)
        elif rest == "":
            # A block sequence may sit at the SAME indentation as the key it belongs to:
            #
            #     relationships:
            #     - name: fct_orders_to_dim_customers
            #
            # which is what `wren context import dbt` emits, and legal YAML everywhere.
            # `_parse_block` requires a deeper indent, so without this the key took the
            # value None and the sequence was left for the caller to choke on — the error
            # surfaced as `unexpected content '- name: ...'` from `parse()`, three frames
            # away from the key that actually owned it.
            #
            # Narrow on purpose: only when the very next line *is* a sequence item at
            # exactly this indent. `a:\nb: 1` must still read as {a: None, b: 1}.
            if index < len(lines) and lines[index][0] == cur_indent and (
                lines[index][1] == "-" or lines[index][1].startswith("- ")
            ):
                value, index = _parse_sequence(lines, index, cur_indent)
            else:
                value, index = _parse_block(lines, index, cur_indent)
        else:
            # A plain scalar may fold across following, more-indented lines that are
            # not themselves mapping keys or sequence items. This is common in dbt
            # descriptions written without an explicit `>` block.
            rest, index = _fold_plain(lines, index, cur_indent, rest)
            value = _scalar(rest)
        result[key] = value
    return result, index


def _fold_plain(lines: List[Tuple[int, str, int]], index: int, indent: int,
                first: str) -> Tuple[str, int]:
    if _is_flow(first):
        return first, index
    if first and first[0] in ("'", '"'):
        return _fold_quoted(lines, index, indent, first)
    parts = [first]
    while index < len(lines):
        nxt_indent, nxt_content, _ = lines[index]
        if nxt_indent <= indent:
            break
        if nxt_content.startswith("- "):
            break
        _, is_key, _ = _split_key(nxt_content)
        if is_key:
            break
        parts.append(nxt_content)
        index += 1
    return " ".join(parts), index


def _fold_quoted(lines: List[Tuple[int, str, int]], index: int, indent: int,
                 first: str) -> Tuple[str, int]:
    """A quoted scalar whose closing quote is on a later line.

    `wren context import dbt` writes column descriptions this way, and stopping at the
    opening line left the continuation to be read as mapping content — `line 30:
    unexpected indentation in mapping`, on a file PyYAML reads without complaint. That is
    the worst failure mode for a fallback parser: not a wrong value, no value at all.

    Folded with spaces, like `_fold_plain`. Exact agreement with PyYAML is out of reach
    here because the lexer drops blank lines, and a blank line inside a quoted scalar is a
    literal newline — so the two agree on the text and can differ in its whitespace, which
    `tests/test_miniyaml.py` states as the contract rather than leaving it to be discovered.
    """
    quote = first[0]
    parts = [first]
    if _quote_closed(first, quote):
        return first, index
    while index < len(lines):
        nxt_indent, nxt_content, _ = lines[index]
        if nxt_indent <= indent:
            break
        parts.append(nxt_content)
        index += 1
        if _quote_closed(nxt_content, quote):
            break
    return " ".join(parts), index


def _quote_closed(text: str, quote: str) -> bool:
    """Whether `text` closes a scalar opened with `quote`.

    A doubled quote is an escaped one in YAML's single-quoted style (`customer''s`), and
    a backslash escapes in the double-quoted style; both must not read as the close.
    """
    body = text[1:] if text.startswith(quote) else text
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == quote:
            if quote == "'" and i + 1 < len(body) and body[i + 1] == "'":
                i += 2
                continue
            return True
        if ch == "\\" and quote == '"':
            i += 2
            continue
        i += 1
    return False


def _block_scalar(lines: List[Tuple[int, str, int]], index: int, indent: int,
                  header: str) -> Tuple[str, int]:
    """Block scalar. `>` folds newlines to spaces, `|` keeps them. The chomping
    indicator controls the trailing newline: clip (default) keeps one, `-` strips it,
    `+` keeps all — matching PyYAML so the two parsers agree."""
    style, chomp = header[0], (header[1:] or "")
    parts: List[str] = []
    # The lexer strips indentation, so a body line's own indent has to be put back
    # relative to the block's first line. Without this every `|` block came back
    # left-aligned — which reads fine and silently reformats SQL, and the wren metric
    # views are exactly that: a `statement: |` holding a whole query.
    base: Optional[int] = None
    while index < len(lines) and lines[index][0] > indent:
        line_indent, content, _ = lines[index]
        if base is None:
            base = line_indent
        parts.append(" " * max(0, line_indent - base) + content)
        index += 1
    body = " ".join(parts) if style == ">" else "\n".join(parts)
    if chomp != "-" and body:
        body += "\n"
    return body, index


def _split_key(content: str) -> Tuple[str, bool, str]:
    quote: Optional[str] = None
    depth = 0
    for i, ch in enumerate(content):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            if i + 1 >= len(content) or content[i + 1] in " \t":
                return content[:i].strip(), True, content[i + 1:]
    return content, False, ""


def _is_flow(text: str) -> bool:
    text = text.strip()
    return text.startswith("{") or text.startswith("[")


# ---------------------------------------------------------------- scalars


_DOUBLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "a": "\a", "b": "\b",
    "f": "\f", "v": "\v", "e": "\x1b", "\\": "\\", '"': '"', "/": "/",
    " ": " ", "N": "\x85", "_": "\xa0",
}


def _unquote(quote: str, body: str) -> str:
    """Undo YAML's quoting rules for the two quoted styles.

    Returning the body verbatim was wrong in both styles and read as correct in most
    files: a single-quoted `customer''s` came back with the doubled quote, and a
    double-quoted `\\u2014` — which is how every YAML emitter writes an em dash — came back
    as six literal characters. Both survive a round trip through anything that only
    displays the string, which is why they went unnoticed until the fallback parser was
    compared against PyYAML file by file.
    """
    if quote == "'":
        return body.replace("''", "'")
    out: List[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 >= len(body):
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in ("x", "u", "U"):
            width = {"x": 2, "u": 4, "U": 8}[nxt]
            digits = body[i + 2:i + 2 + width]
            if len(digits) == width:
                try:
                    out.append(chr(int(digits, 16)))
                    i += 2 + width
                    continue
                except ValueError:
                    pass
        out.append(_DOUBLE_ESCAPES.get(nxt, "\\" + nxt))
        i += 2
    return "".join(out)


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        return _flow_mapping(text[1:-1])
    if text.startswith("[") and text.endswith("]"):
        return _flow_sequence(text[1:-1])
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return _unquote(text[0], text[1:-1])
    lowered = text.lower()
    if lowered in ("null", "~", ""):
        return None
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_flow(text: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    quote: Optional[str] = None
    current: List[str] = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
        elif ch in "[{":
            depth += 1
            current.append(ch)
        elif ch in "]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current))
    return parts


def _flow_mapping(text: str) -> dict:
    out: dict = {}
    for part in _split_flow(text):
        key, sep, rest = _split_key(part.strip())
        if not sep:
            raise MiniYamlError(f"malformed flow mapping entry: {part!r}")
        out[_scalar(key)] = _scalar(rest)
    return out


def _flow_sequence(text: str) -> List[Any]:
    return [_scalar(p) for p in _split_flow(text) if p.strip()]


# ---------------------------------------------------------------- loader shim


def load(text: str) -> Any:
    """Parse with PyYAML when available, else the minimal parser."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return parse(text)


def using_pyyaml() -> bool:
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False
