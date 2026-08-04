/**
 * TOON (Token-Oriented Object Notation) serializer for AI-facing context.
 * Spec: https://github.com/toon-format/spec
 *
 * Encode-only by design: TOON is the inbound LLM-context format; machine
 * consumers receive JSON. The executable, fully spec-tested implementation
 * (encode + decode + CLI) is `rust/toon/graph_to_toon.rs`, built by
 * `scripts/build_toon_rs.sh`; this wrapper exists so TypeScript call sites
 * route through ai-core instead of hand-rolling serialization.
 */

export type ToonPrimitive = string | number | boolean | null;
export type ToonValue = ToonPrimitive | ToonValue[] | { [key: string]: ToonValue };

const UNQUOTED_KEY = /^[A-Za-z_][A-Za-z0-9_.]*$/;
const NUMERIC_LIKE = /^[+-]?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?$/i;

function isPrimitive(v: ToonValue): v is ToonPrimitive {
  return v === null || typeof v !== 'object';
}

function quote(s: string): string {
  const escaped = s
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\t/g, '\\t')
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`);
  return `"${escaped}"`;
}

function encodeString(s: string, delimiter: string): string {
  const mustQuote =
    s === '' ||
    s !== s.trim() ||
    s === 'true' || s === 'false' || s === 'null' ||
    NUMERIC_LIKE.test(s) ||
    /[:"\\[\]{}]/.test(s) ||
    // eslint-disable-next-line no-control-regex
    /[\u0000-\u001f]/.test(s) ||
    s.includes(delimiter) ||
    s.startsWith('-') ||
    s.startsWith('#');
  return mustQuote ? quote(s) : s;
}

function encodeScalar(v: ToonPrimitive, delimiter: string): string {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') {
    if (Number.isNaN(v) || !Number.isFinite(v)) return 'null';
    if (Object.is(v, -0)) return '0';
    return String(v);
  }
  return encodeString(v, delimiter);
}

function encodeKey(k: string): string {
  return UNQUOTED_KEY.test(k) ? k : quote(k);
}

/** Rows are tabular-eligible when uniform: same keys, all-primitive values. */
function tabularFields(rows: ToonValue[]): string[] | null {
  if (rows.length === 0) return null;
  const first = rows[0];
  if (isPrimitive(first) || Array.isArray(first)) return null;
  const keys = Object.keys(first);
  if (keys.length === 0) return null;
  for (const row of rows) {
    if (isPrimitive(row) || Array.isArray(row)) return null;
    const rowKeys = Object.keys(row);
    if (rowKeys.length !== keys.length || !keys.every((k) => k in row)) return null;
    if (!keys.every((k) => isPrimitive((row as Record<string, ToonValue>)[k]))) return null;
  }
  return keys;
}

export interface ToonEncodeOptions {
  delimiter?: ',' | '\t' | '|';
  indent?: number;
}

export function encodeToon(value: ToonValue, options: ToonEncodeOptions = {}): string {
  const delimiter = options.delimiter ?? ',';
  const indentSize = options.indent ?? 2;
  const delimSymbol = delimiter === ',' ? '' : delimiter;
  const lines: string[] = [];

  const pad = (depth: number): string => ' '.repeat(depth * indentSize);

  const emitArray = (key: string | null, arr: ToonValue[], depth: number): void => {
    const head = key === null ? '' : key;
    if (arr.length === 0) {
      lines.push(key === null ? `${pad(depth)}[]` : `${pad(depth)}${key}: []`);
      return;
    }
    if (arr.every(isPrimitive)) {
      const cells = arr.map((v) => encodeScalar(v as ToonPrimitive, delimiter)).join(delimiter);
      lines.push(`${pad(depth)}${head}[${arr.length}${delimSymbol}]: ${cells}`);
      return;
    }
    const fields = tabularFields(arr);
    if (fields !== null) {
      const spec = fields.map(encodeKey).join(delimiter);
      lines.push(`${pad(depth)}${head}[${arr.length}${delimSymbol}]{${spec}}:`);
      for (const row of arr) {
        const cells = fields
          .map((f) => encodeScalar((row as Record<string, ToonValue>)[f] as ToonPrimitive, delimiter))
          .join(delimiter);
        lines.push(`${pad(depth + 1)}${cells}`);
      }
      return;
    }
    lines.push(`${pad(depth)}${head}[${arr.length}${delimSymbol}]:`);
    for (const item of arr) {
      if (isPrimitive(item)) {
        lines.push(`${pad(depth + 1)}- ${encodeScalar(item, delimiter)}`);
      } else {
        const before = lines.length;
        if (Array.isArray(item)) {
          emitArray(null, item, depth + 1);
        } else {
          emitObject(item as Record<string, ToonValue>, depth + 2);
          if (lines.length === before) {
            lines.push(`${pad(depth + 1)}-`); // empty object item
            continue;
          }
        }
        // graft the first emitted line onto the hyphen
        const firstLine = lines[before].slice(pad(Array.isArray(item) ? depth + 1 : depth + 2).length);
        lines[before] = `${pad(depth + 1)}- ${firstLine}`;
      }
    }
  };

  const emitObject = (obj: Record<string, ToonValue>, depth: number): void => {
    for (const [k, v] of Object.entries(obj)) {
      const key = encodeKey(k);
      if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
        lines.push(`${pad(depth)}${key}:`);
        emitObject(v as Record<string, ToonValue>, depth + 1);
      } else if (Array.isArray(v)) {
        emitArray(key, v, depth);
      } else {
        lines.push(`${pad(depth)}${key}: ${encodeScalar(v, delimiter)}`);
      }
    }
  };

  if (Array.isArray(value)) {
    emitArray(null, value, 0);
  } else if (value !== null && typeof value === 'object') {
    emitObject(value as Record<string, ToonValue>, 0);
  } else {
    lines.push(encodeScalar(value, delimiter));
  }
  return lines.join('\n');
}
