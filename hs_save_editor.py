#!/usr/bin/env python3
"""
Minimal Hero Siege offline character save editor.

This version intentionally keeps only:
- the save-file picker on the left
- editable character fields on the right
- raw decoded save text below the fields
- HSS decode/encode and backup-on-save

It has no item database, stash, ether, snapshot, or external module dependencies.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    VERTICAL,
    X,
    Y,
    Button,
    Entry,
    Frame,
    Label,
    LabelFrame,
    Listbox,
    PanedWindow,
    Scrollbar,
    StringVar,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    ttk,
)
from tkinter.scrolledtext import ScrolledText


APP_TITLE = "Hero Siege Character Save Editor"
HERO_SIEGE_ROOT = Path.home() / "AppData" / "Local" / "Hero_Siege"
DEFAULT_SAVE_DIR = HERO_SIEGE_ROOT
UI_BG = "#0f172a"
UI_PANEL = "#111827"
UI_CARD = "#1f2937"
UI_CARD_2 = "#172033"
UI_BORDER = "#334155"
UI_TEXT = "#e5edf7"
UI_MUTED = "#94a3b8"
UI_FIELD = "#0b1120"
UI_ACCENT = "#38bdf8"
UI_ACCENT_DARK = "#0ea5e9"
UI_WAYPOINT = "#2563eb"
UI_WAYPOINT_DARK = "#1d4ed8"
UI_DANGER = "#ef4444"
UI_DANGER_DARK = "#dc2626"
UI_NOTICE = "#f59e0b"


def normalize_line_endings(text: str) -> str:
    """Hero Siege saves can contain CR-only lines; normalize before parsing/editing."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def looks_like_plain_character_ini(text: str) -> bool:
    text = normalize_line_endings(text).lstrip("\ufeff\x00 \t\r\n")
    return bool(re.search(r"(?m)^\[[^\]]+\]\s*$", text)) and bool(
        re.search(r'(?m)^(?:name|class|level|herolevel|experience)\s*=', text)
    )


def save_slot_sort_key(display: str) -> tuple[int, int, str]:
    match = re.search(r"herosiege(\d+)\.hss$", display.replace("\\", "/"), re.IGNORECASE)
    if match:
        return (0, int(match.group(1)), display.lower())
    return (1, 0, display.lower())


def save_slot_number(display: str) -> int | None:
    match = re.search(r"herosiege(\d+)\.hss$", display.replace("\\", "/"), re.IGNORECASE)
    return int(match.group(1)) if match else None


def iter_ini_sections(text: str) -> list[tuple[str, str]]:
    text = normalize_line_endings(text)
    matches = list(re.finditer(r"(?m)^\[([^\]]+)\]\s*$", text))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[start:end]))
    return sections


def get_ini_value_from_body(body: str, key: str) -> str:
    key_match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", body)
    if not key_match:
        return ""
    return strip_outer_quotes(key_match.group(1))


def character_metadata_from_text(text: str) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []
    for section_name, body in iter_ini_sections(text):
        name = get_ini_value_from_body(body, "name").strip()
        class_raw = get_ini_value_from_body(body, "class").strip()
        if not name and not class_raw:
            continue
        level = get_ini_value_from_body(body, "level").strip()
        hero_level = get_ini_value_from_body(body, "herolevel").strip()
        experience = get_ini_value_from_body(body, "experience").strip()
        playtime = get_ini_value_from_body(body, "playtime").strip()
        score = 0
        if section_name == "0":
            score += 8
        if name:
            score += 10
        if name and name.lower() not in {"new char", "unnamed"}:
            score += 35
        if class_raw:
            score += 10
        if class_raw and format_field_display_value(class_raw, FieldSpec("Class", "0", "class", "number")) != "Viking":
            score += 8
        for value in (level, hero_level, experience, playtime):
            try:
                if parse_number(value) > 0:
                    score += 4
            except ValueError:
                pass
        candidates.append((score, name or "Unnamed", class_raw))

    if not candidates:
        return ("Unnamed", "")
    _score, name, class_raw = max(candidates, key=lambda item: item[0])
    class_name = format_field_display_value(class_raw, FieldSpec("Class", "0", "class", "number")) if class_raw else ""
    return (name, class_name)


def summarize_save_for_list(path: Path) -> tuple[str, str]:
    try:
        text = decode_hss_file(path)
    except Exception:
        return ("Empty / unsupported", "")
    if classify_text(text, path) != "character_ini":
        return ("Not a character", "")
    return character_metadata_from_text(text)


def save_list_label(display: str, path: Path) -> str:
    slot = save_slot_number(display)
    slot_label = f"Slot {slot:02d}" if slot is not None else display
    name, class_name = summarize_save_for_list(path)
    suffix = f" - {class_name}" if class_name else ""
    return f"{slot_label}   {name}{suffix}"

# The second layer is a repeating XOR key over UTF-16LE-ish text bytes.
# Odd bytes become zero after XOR, even bytes contain the actual text.
HSS_XOR_KEY = bytes(
    [
        0xE3,
        0x95,
        0x3D,
        0xB1,
        0x01,
        0x6B,
        0xB6,
        0x58,
        0x54,
        0x38,
        0x3F,
        0x46,
        0xA1,
        0x74,
        0x29,
        0xCC,
        0x45,
        0x45,
        0x51,
        0xF2,
        0xA7,
        0xF7,
        0xAB,
        0xB7,
        0x26,
        0xF1,
        0x37,
        0xA8,
        0x81,
        0x91,
        0xE6,
        0x7E,
    ]
)


class HssFormatError(ValueError):
    """Raised when a file does not look like the supported .hss format."""


@dataclass
class LoadedSave:
    path: Path
    text: str
    file_kind: str
    shop_path: Path | None = None
    shop_text: str | None = None


@dataclass(frozen=True)
class FieldSpec:
    label: str
    section: str
    key: str
    kind: str = "text"
    extra_keys: tuple[str, ...] = ()
    default_value: str = ""


CHARACTER_FIELDS = [
    FieldSpec("Name", "0", "name"),
    FieldSpec("Class", "0", "class", "number"),
    FieldSpec("Level (level=)", "0", "level", "number"),
    FieldSpec("Hero Level (herolevel=)", "0", "herolevel", "number"),
    FieldSpec("Experience", "0", "experience", "number"),
    FieldSpec("Gold", "gold", "gold", "number", ("gold_hc",), "0"),
    FieldSpec("Wormhole Level", "0", "wormhole_level", "number"),
]

PROFESSION_FIELDS = [
    FieldSpec("Herbalism", "herbalism", "herbalism", "number", ("herbalism_hc",)),
    FieldSpec("Enchanting", "enchanting", "enchanting", "number", ("enchanting_hc",)),
    FieldSpec("Jewelcrafting", "jewelcrafting", "jewelcrafting", "number", ("jewelcrafting_hc",)),
    FieldSpec("Mining", "mining", "mining", "number", ("mining_hc",)),
]

ALL_FIELDS = CHARACTER_FIELDS + PROFESSION_FIELDS

CLASS_ID_TO_NAME = {
    1: "Viking",
    2: "Pyromancer",
    3: "Marksman",
    4: "Pirate",
    5: "Nomad",
    6: "Redneck",
    7: "Necromancer",
    8: "Samurai",
    9: "Paladin",
    10: "Amazon",
    11: "Demon Slayer",
    12: "Demonspawn",
    13: "Shaman",
    14: "White Mage",
    15: "Marauder",
    16: "Plague Doctor",
    17: "Shield Lancer",
    18: "Illusionist",
    19: "Jötunn",
    20: "Exo",
    21: "Butcher",
    22: "Stormweaver",
    23: "Bard",
    24: "Prophet",
}
CLASS_NAME_TO_ID = {name.lower(): class_id for class_id, name in CLASS_ID_TO_NAME.items()}
CLASS_DISPLAY_VALUES = [CLASS_ID_TO_NAME[i] for i in sorted(CLASS_ID_TO_NAME)]


def xor_bytes(data: bytes) -> bytes:
    return bytes(byte ^ HSS_XOR_KEY[index % len(HSS_XOR_KEY)] for index, byte in enumerate(data))


def decode_hss_bytes(encoded_text: str) -> str:
    cleaned = "".join(ch for ch in encoded_text if not ch.isspace() and ch != "\x00")
    if not cleaned:
        raise HssFormatError("File is empty.")

    try:
        compressed = base64.b64decode(cleaned, validate=True)
    except Exception as exc:
        raise HssFormatError(
            "This file is not a supported encoded Hero Siege character save. "
            "It may be an empty slot, a Steam Cloud placeholder, or a different platform save format."
        ) from exc

    try:
        obfuscated = zlib.decompress(compressed)
    except Exception as exc:
        raise HssFormatError(f"zlib decompress failed: {exc}") from exc

    decoded = xor_bytes(obfuscated)
    high_bytes = decoded[1::2]
    if high_bytes and any(byte != 0 for byte in high_bytes):
        non_zero_ratio = sum(byte != 0 for byte in high_bytes) / len(high_bytes)
        if non_zero_ratio > 0.01:
            raise HssFormatError("XOR decoded, but payload is not the expected text format.")

    payload = decoded[::2]
    try:
        return normalize_line_endings(payload.decode("utf-8"))
    except UnicodeDecodeError:
        return normalize_line_endings(payload.decode("latin-1"))


def encode_hss_text(text: str) -> str:
    text = normalize_line_endings(text)
    payload = text.encode("utf-8")
    utf16_like = bytearray(len(payload) * 2)
    utf16_like[0::2] = payload
    obfuscated = xor_bytes(bytes(utf16_like))
    return base64.b64encode(zlib.compress(obfuscated, level=9)).decode("ascii")


def decode_hss_file(path: Path) -> str:
    raw = path.read_bytes()
    if not raw or not raw.strip(b"\x00\r\n\t "):
        raise HssFormatError("This save slot is empty.")

    plain = normalize_line_endings(raw.decode("utf-8-sig", errors="ignore").replace("\x00", ""))
    if looks_like_plain_character_ini(plain):
        return plain

    return decode_hss_bytes(plain)


def write_hss_file(path: Path, text: str, create_backup: bool = True) -> Path | None:
    backup_path = None
    if create_backup and path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak_{timestamp}")
        shutil.copy2(path, backup_path)

    path.write_text(encode_hss_text(text) + "\x00", encoding="ascii", newline="")
    return backup_path


def write_plain_ini_file(path: Path, text: str, create_backup: bool = True) -> Path | None:
    backup_path = None
    if create_backup and path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak_{timestamp}")
        shutil.copy2(path, backup_path)

    path.write_text(normalize_line_endings(text), encoding="utf-8", newline="\n")
    return backup_path


def classify_text(text: str, path: Path | None = None) -> str:
    name = path.name.lower() if path else ""
    if name.startswith("stash") or text.lstrip().startswith("{"):
        return "non_character"
    if re.search(r"(?m)^\[[^\]]+\]\s*$", text):
        return "character_ini"
    return "text"


def strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def get_ini_value(text: str, section: str, key: str) -> str:
    text = normalize_line_endings(text)
    match = re.search(rf"(?ms)^\[{re.escape(section)}\]\s*\r?\n(.*?)(?=^\[|\Z)", text)
    if not match:
        return ""
    return get_ini_value_from_body(match.group(1), key)


def get_field_value(text: str, spec: FieldSpec) -> str:
    value = get_ini_value(text, spec.section, spec.key)
    if value != "":
        return format_field_display_value(value, spec)
    for key in spec.extra_keys:
        value = get_ini_value(text, spec.section, key)
        if value != "":
            return format_field_display_value(value, spec)
    if spec.default_value != "":
        return format_field_display_value(spec.default_value, spec)
    return ""


def format_field_display_value(value: str, spec: FieldSpec) -> str:
    if spec.section == "0" and spec.key == "class":
        try:
            class_id = int(parse_number(value))
        except ValueError:
            return value
        return CLASS_ID_TO_NAME.get(class_id, value)
    if spec.kind != "number":
        return value
    try:
        number = parse_number(value)
    except ValueError:
        return value
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def normalize_field_save_value(value: str, spec: FieldSpec) -> str:
    value = value.strip()
    if spec.section == "0" and spec.key == "class":
        class_id = CLASS_NAME_TO_ID.get(value.lower())
        if class_id is not None:
            return str(class_id)
    return value


def parse_number(value: str) -> float:
    if not value:
        return 0.0
    return float(value.replace(",", "."))


def quote_value(value: str, kind: str) -> str:
    value = value.strip()
    if kind == "number":
        number = parse_number(value)
        return f'"{number:.6f}"'
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_ini_value(text: str, section: str, key: str, value: str, kind: str) -> str:
    text = normalize_line_endings(text)
    replacement_value = quote_value(value, kind)
    section_pattern = re.compile(rf"(?ms)^(\[{re.escape(section)}\]\s*)(.*?)(?=^\[|\Z)")
    match = section_pattern.search(text)
    if not match:
        addition = f"\n[{section}]\n{key}={replacement_value}\n"
        return text.rstrip("\n") + addition

    body = match.group(2)
    key_pattern = re.compile(rf"(?m)^({re.escape(key)}\s*=\s*).*$")
    if key_pattern.search(body):
        body = key_pattern.sub(rf"\1{replacement_value}", body, count=1)
    else:
        if body and not body.endswith("\n"):
            body += "\n"
        body += f"{key}={replacement_value}\n"

    return text[: match.start(2)] + body + text[match.end(2) :]


def ensure_section_before_anchor(text: str, section: str, anchors: tuple[str, ...]) -> str:
    text = normalize_line_endings(text)
    if re.search(rf"(?m)^\[{re.escape(section)}\]\s*$", text):
        return text
    anchor_pattern = re.compile(rf"(?m)^\[(?:{'|'.join(re.escape(anchor) for anchor in anchors)})\]\s*$")
    match = anchor_pattern.search(text)
    new_section = f"[{section}]\n"
    if not match:
        return text.rstrip("\n") + "\n" + new_section
    prefix = text[: match.start()].rstrip("\n")
    suffix = text[match.start() :]
    return prefix + "\n" + new_section + suffix


def set_field_value(text: str, spec: FieldSpec, value: str) -> str:
    value = normalize_field_save_value(value, spec)
    if spec in PROFESSION_FIELDS:
        text = ensure_section_before_anchor(text, spec.section, ("shop", "gold", "minion", "emotes", "chat_options", "0"))
    elif spec.section == "gold":
        text = ensure_section_before_anchor(text, spec.section, ("minion", "emotes", "chat_options", "0"))
    text = set_ini_value(text, spec.section, spec.key, value, spec.kind)
    for key in spec.extra_keys:
        text = set_ini_value(text, spec.section, key, value, spec.kind)
    return text


def is_shop_backed_field(spec: FieldSpec) -> bool:
    return spec.section == "gold" or spec in PROFESSION_FIELDS


def is_shop_backed_section(section: str) -> bool:
    return section == "gold" or any(spec.section == section for spec in PROFESSION_FIELDS)


def default_shop_ini_text() -> str:
    return (
        '[herbalism]\nherbalism_hc="0.000000"\nherbalism="0.000000"\n'
        '[enchanting]\nenchanting_hc="0.000000"\nenchanting="0.000000"\n'
        '[jewelcrafting]\njewelcrafting_hc="0.000000"\njewelcrafting="0.000000"\n'
        '[mining]\nmining_hc="0.000000"\nmining="0.000000"\n'
        '[gold]\ngold_hc="0.000000"\ngold="0.000000"\n'
        '[shop]\ncurrency="0.000000"\n'
    )


def read_shop_ini_near_character(path: Path) -> tuple[Path, str | None]:
    shop_path = path.parent / "shop.ini"
    if shop_path.exists():
        return shop_path, normalize_line_endings(shop_path.read_text(encoding="utf-8-sig", errors="ignore"))
    return shop_path, None


def decode_base64_json(value: str) -> object | None:
    value = value.strip()
    if not value:
        return None
    candidates = (value, value + ("=" * ((4 - len(value) % 4) % 4)))
    for candidate in candidates:
        try:
            raw = base64.b64decode(candidate, validate=False)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            continue
    return None


def encode_base64_json(value: object) -> str:
    return base64.b64encode(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode(
        "ascii"
    )


def decode_item_stat_slot(value: object) -> dict[str, int] | None:
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str):
        decoded = decode_base64_json(value)
        if not isinstance(decoded, dict):
            return None
        data = decoded
    else:
        return None
    try:
        return {
            "a": int(float(data.get("a", 0))),
            "b": int(float(data.get("b", 0))),
            "n": int(float(data.get("n", 0))),
        }
    except (TypeError, ValueError, OverflowError):
        return None


def format_compact_value(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def iter_inventory_payloads(text: str) -> list[tuple[str, dict]]:
    payloads: list[tuple[str, dict]] = []
    for section_name in ("inventory", "0"):
        encoded = get_ini_value(text, section_name, "inventory")
        if not encoded:
            continue
        decoded = decode_base64_json(encoded)
        if isinstance(decoded, dict):
            payloads.append((section_name, decoded))
    return payloads


def default_item_db_path() -> Path | None:
    candidates = [
        Path.home() / "AppData" / "Local" / "HSeditor" / "app-3.3.1" / "ini.dll",
        HERO_SIEGE_ROOT / "hseditor" / "hero_siege_editor_items.sqlite",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def lookup_item_name(db_path: Path | None, item_id: object, slot_id: object = None) -> str:
    try:
        item_id_int = int(float(item_id))
    except (TypeError, ValueError, OverflowError):
        return ""
    slot_id_int: int | None = None
    try:
        if slot_id is not None:
            slot_id_int = int(float(slot_id))
    except (TypeError, ValueError, OverflowError):
        slot_id_int = None
    if db_path is None or not db_path.exists():
        return ""
    try:
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            queries: list[tuple[str, str, tuple[object, ...]]] = []
            if slot_id_int is not None:
                queries.extend(
                    [
                        ("Items", "SELECT name FROM Items WHERE ingameid=? AND slotid=? LIMIT 1", (item_id_int, slot_id_int)),
                        (
                            "Generics",
                            "SELECT name FROM Generics WHERE ingameid=? AND slotid=? LIMIT 1",
                            (item_id_int, slot_id_int),
                        ),
                    ]
                )
            queries.extend(
                [
                    ("Items", "SELECT name FROM Items WHERE ingameid=? LIMIT 1", (item_id_int,)),
                    ("Generics", "SELECT name FROM Generics WHERE ingameid=? LIMIT 1", (item_id_int,)),
                ]
            )
            for table, query, params in queries:
                row = con.execute(query, params).fetchone()
                if row:
                    return f"{row['name']} [{table}]"
    except Exception:
        return ""
    return ""


def lookup_stat_name(db_path: Path | None, stat_id: object) -> str:
    try:
        stat_id_int = int(float(stat_id))
    except (TypeError, ValueError, OverflowError):
        return ""
    if db_path is None or not db_path.exists():
        return ""
    try:
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT name, description, type FROM Stats WHERE rowid=?", (stat_id_int,)).fetchone()
            if row:
                suffix = "%" if row["type"] == "%" else ""
                return f"{row['description']} ({row['name']}{suffix})"
    except Exception:
        return ""
    return ""


def summarize_item_data(data: dict) -> str:
    keys = ("b", "g", "j", "a", "c", "w", "f", "i", "k", "l", "m", "n", "p", "r")
    parts = [f"{key}={format_compact_value(data[key])}" for key in keys if key in data]
    return ", ".join(parts)


def summarize_item_stat_slots(data: dict, db_path: Path | None) -> str:
    lines: list[str] = []
    for index in range(1, 7):
        key = f"s{index}"
        decoded = decode_item_stat_slot(data.get(key))
        if not decoded:
            continue
        stat_name = lookup_stat_name(db_path, decoded["b"])
        label = f" ({stat_name})" if stat_name else ""
        lines.append(f"{key}: a={decoded['a']} b={decoded['b']} n={decoded['n']}{label}")
    return "; ".join(lines)


def unlock_all_waypoints(text: str) -> str:
    for act in range(1, 9):
        text = set_ini_value(text, "0", f"act_{act}", "4", "number")
        for zone in range(5):
            text = set_ini_value(text, "0", f"zone{act},{zone}", "4", "number")
    return text


def unlock_inferno_difficulty(text: str) -> str:
    text = unlock_all_waypoints(text)
    text = set_ini_value(text, "0", "difficulty", "3", "number")
    text = set_ini_value(text, "0", "hell_subdifficulty", "6", "number")
    text = set_ini_value(text, "0", "act_previous", "0", "number")
    text = set_ini_value(text, "0", "act_previous_0_0", "3", "number")
    text = set_ini_value(text, "0", "act_previous_1_0", "1", "number")
    text = set_ini_value(text, "0", "act_previous_2_0", "1", "number")
    text = set_ini_value(text, "0", "act_previous_2_2", "4", "number")
    text = set_ini_value(text, "0", "act_previous_2_3", "5", "number")
    text = set_ini_value(text, "0", "act_previous_2_4", "0", "number")
    text = set_ini_value(text, "0", "act_previous_3_0", "3", "number")
    text = set_ini_value(text, "0", "waypoints", "eyB9", "text")
    # Inferno being selectable appears to depend on quest/progress chains, not
    # only the current difficulty value. These values were observed on a save
    # where Inferno is unlocked.
    text = set_ini_value(text, "4", "questlog_chain1", "mainNightmare|1", "text")
    text = set_ini_value(text, "4", "questlog_chain8", "etheringHell|6", "text")
    text = set_ini_value(text, "4", "questlog_chain9", "etheringDamnation|1", "text")
    text = set_ini_value(text, "4", "questlog_chain12", "mainHell|1", "text")
    text = set_ini_value(text, "4", "questlog_chain13", "etheringInferno|1", "text")
    text = set_ini_value(text, "4", "questlog_chain17", "etheringChallengeInferno|1", "text")
    text = set_ini_value(text, "4", "questlog_diff5", "3", "number")
    text = set_ini_value(text, "4", "questlog_diff6", "3", "number")
    text = set_ini_value(text, "4", "questlog_diff7", "3", "number")
    text = set_ini_value(text, "4", "questlog_diff8", "2", "number")
    text = set_ini_value(text, "4", "questlog_diff9", "3", "number")
    for index in range(5, 10):
        text = set_ini_value(text, "4", f"questlog_sub_diff{index}", "0", "number")
    return text


class HssEditorApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x760")
        self.save_dir = DEFAULT_SAVE_DIR if DEFAULT_SAVE_DIR.exists() else Path.cwd()
        self.loaded: LoadedSave | None = None
        self.raw_buffer = ""
        self.raw_window: Toplevel | None = None
        self.raw_text: ScrolledText | None = None
        self.inventory_window: Toplevel | None = None
        self.file_list_paths: dict[str, Path] = {}
        self.field_vars: dict[FieldSpec, StringVar] = {}
        self.field_widgets: dict[FieldSpec, object] = {}
        self._character_field_vars_dirty = False
        self._suppress_field_trace = False

        self.status = StringVar(value="Ready")
        self.current_file = StringVar(value="No character save loaded")
        self.raw_search_var = StringVar(value="")
        self.raw_search_status = StringVar(value="")

        self._build_layout()
        self.refresh_file_list()

    def make_button(
        self,
        parent,
        text: str,
        command,
        *,
        accent: bool = False,
        danger: bool = False,
        bg: str | None = None,
        active_bg: str | None = None,
        fg: str | None = None,
    ) -> Button:
        if danger:
            default_bg = UI_DANGER
            default_active_bg = UI_DANGER_DARK
            default_fg = "#fff7ed"
        elif accent:
            default_bg = UI_ACCENT
            default_active_bg = UI_ACCENT_DARK
            default_fg = "#04111f"
        else:
            default_bg = UI_CARD
            default_active_bg = UI_BORDER
            default_fg = UI_TEXT
        bg = bg or default_bg
        active_bg = active_bg or default_active_bg
        fg = fg or default_fg
        return Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            bd=0,
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )

    def make_entry(self, parent, var: StringVar, width: int = 26) -> Entry:
        return Entry(
            parent,
            textvariable=var,
            width=width,
            bg=UI_FIELD,
            fg=UI_TEXT,
            insertbackground=UI_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
        )

    def _build_layout(self) -> None:
        self.root.configure(bg=UI_BG)
        self.root.option_add("*Font", ("Segoe UI", 10))
        self.root.option_add("*Button.Background", UI_CARD)
        self.root.option_add("*Button.Foreground", UI_TEXT)
        self.root.option_add("*Button.ActiveBackground", UI_BORDER)
        self.root.option_add("*Button.ActiveForeground", UI_TEXT)
        self.root.option_add("*Button.Relief", "flat")
        self.root.option_add("*TCombobox*Listbox.Background", UI_FIELD)
        self.root.option_add("*TCombobox*Listbox.Foreground", UI_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", UI_ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#04111f")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Modern.TCombobox",
            fieldbackground=UI_FIELD,
            background=UI_CARD,
            foreground=UI_TEXT,
            arrowcolor=UI_ACCENT,
            bordercolor=UI_BORDER,
            lightcolor=UI_BORDER,
            darkcolor=UI_BORDER,
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", UI_FIELD), ("focus", UI_FIELD)],
            foreground=[("readonly", UI_TEXT), ("focus", UI_TEXT)],
            selectbackground=[("readonly", UI_FIELD), ("focus", UI_FIELD)],
            selectforeground=[("readonly", UI_TEXT), ("focus", UI_TEXT)],
        )
        style.configure(
            "Treeview",
            background=UI_FIELD,
            foreground=UI_TEXT,
            fieldbackground=UI_FIELD,
            bordercolor=UI_BORDER,
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=UI_CARD,
            foreground=UI_TEXT,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Treeview", background=[("selected", UI_ACCENT)], foreground=[("selected", "#04111f")])

        main = PanedWindow(self.root, orient="horizontal", sashrelief="flat", bg=UI_BG, bd=0)
        main.pack(fill=BOTH, expand=True)

        sidebar = Frame(main, padx=14, pady=14, bg=UI_PANEL)
        main.add(sidebar, width=330)

        Label(sidebar, text="Save Folder", bg=UI_PANEL, fg=UI_TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.folder_label = Label(sidebar, text=str(self.save_dir), wraplength=290, fg=UI_MUTED, bg=UI_PANEL)
        self.folder_label.pack(anchor="w", fill=X, pady=(0, 8))

        self.make_button(sidebar, "Change Folder", self.choose_save_folder).pack(fill=X)
        self.make_button(sidebar, "Refresh", self.refresh_file_list).pack(fill=X, pady=(8, 12))

        list_frame = Frame(sidebar, bg=UI_PANEL)
        list_frame.pack(fill=BOTH, expand=True)
        self.file_list = Listbox(
            list_frame,
            bg=UI_FIELD,
            fg=UI_TEXT,
            selectbackground=UI_ACCENT,
            selectforeground="#04111f",
            activestyle="none",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
            font=("Consolas", 10),
        )
        self.file_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=self.file_list.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.file_list.config(yscrollcommand=scrollbar.set)
        self.file_list.bind("<Double-Button-1>", lambda _event: self.open_selected_file())

        self.make_button(sidebar, "Open Selected", self.open_selected_file, accent=True).pack(fill=X, pady=(12, 0))
        self.make_button(sidebar, "Open File...", self.open_file_dialog).pack(fill=X, pady=(8, 0))

        content = Frame(main, padx=22, pady=20, bg=UI_BG)
        main.add(content)

        Label(
            content,
            textvariable=self.current_file,
            anchor="w",
            font=("Segoe UI", 13, "bold"),
            bg=UI_BG,
            fg=UI_TEXT,
        ).pack(
            fill=X, pady=(0, 12)
        )

        help_text = "Open a character .hss file, edit the fields, then press Save With Backup. Empty fields are not written."
        Label(content, text=help_text, wraplength=720, justify="left", fg=UI_MUTED, bg=UI_BG).pack(
            anchor="w", pady=(0, 14)
        )

        notice_frame = Frame(
            content,
            bg=UI_CARD_2,
            padx=14,
            pady=10,
            highlightthickness=1,
            highlightbackground=UI_NOTICE,
        )
        notice_frame.pack(fill=X, anchor="n", pady=(0, 14))
        Label(
            notice_frame,
            text="Important Notice",
            bg=UI_CARD_2,
            fg=UI_NOTICE,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        notice_text = (
            "This editor is intended for offline/single-player character saves only. "
            "Do not use it with multiplayer, online characters, leaderboards, trading, "
            "or anti-cheat protected modes."
        )
        notice_label = Label(
            notice_frame,
            text=notice_text,
            wraplength=720,
            justify="left",
            bg=UI_CARD_2,
            fg=UI_TEXT,
        )
        notice_label.pack(fill=X, anchor="w", pady=(4, 0))
        content.bind(
            "<Configure>",
            lambda event: notice_label.configure(wraplength=max(320, event.width - 72)),
            add="+",
        )

        grid = LabelFrame(content, text="Character Fields", padx=16, pady=14, bg=UI_CARD, fg=UI_TEXT, bd=1, relief="solid")
        grid.pack(fill=X, anchor="n")

        for index, spec in enumerate(CHARACTER_FIELDS):
            row = index // 2
            column = (index % 2) * 2
            Label(grid, text=spec.label, bg=UI_CARD, fg=UI_TEXT).grid(
                row=row, column=column, sticky="w", padx=(0, 12), pady=7
            )
            var = StringVar()
            if spec.section == "0" and spec.key == "class":
                widget = ttk.Combobox(
                    grid,
                    textvariable=var,
                    values=CLASS_DISPLAY_VALUES,
                    width=24,
                    state="readonly",
                    style="Modern.TCombobox",
                )
            else:
                widget = self.make_entry(grid, var, width=26)
            widget.grid(row=row, column=column + 1, sticky="we", padx=(0, 26), pady=7)
            self.field_vars[spec] = var
            self.field_widgets[spec] = widget

        for column in range(4):
            grid.columnconfigure(column, weight=1 if column in (1, 3) else 0)

        professions = LabelFrame(content, text="Professions", padx=16, pady=12, bg=UI_CARD, fg=UI_TEXT, bd=1, relief="solid")
        professions.pack(fill=X, anchor="n", pady=(8, 0))

        for index, spec in enumerate(PROFESSION_FIELDS):
            column = index * 2
            Label(professions, text=spec.label, bg=UI_CARD, fg=UI_TEXT).grid(
                row=0, column=column, sticky="w", padx=(0, 10), pady=6
            )
            var = StringVar()
            widget = self.make_entry(professions, var, width=18)
            widget.grid(
                row=0, column=column + 1, sticky="we", padx=(0, 24), pady=6
            )
            self.field_vars[spec] = var
            self.field_widgets[spec] = widget

        for column in range(8):
            professions.columnconfigure(column, weight=1 if column % 2 else 0)

        for var in self.field_vars.values():
            var.trace_add("write", self._mark_character_fields_dirty)

        actions = Frame(content, bg=UI_BG)
        actions.pack(fill=X, pady=14)
        self.make_button(actions, "Reload From Disk", self.reload_current).pack(side=LEFT)
        self.make_button(actions, "Save With Backup", self.save_current, accent=True).pack(side=LEFT)
        self.make_button(actions, "Save As...", self.save_as).pack(side=LEFT, padx=8)

        unlock_actions = Frame(content, bg=UI_BG)
        unlock_actions.pack(fill=X, pady=(0, 12))
        self.make_button(
            unlock_actions,
            "Unlock All Waypoints",
            self.apply_unlock_all_waypoints,
            bg=UI_WAYPOINT,
            active_bg=UI_WAYPOINT_DARK,
            fg="#eff6ff",
        ).pack(side=LEFT)
        self.make_button(
            unlock_actions,
            "Unlock Inferno Difficulty",
            self.apply_unlock_inferno_difficulty,
            danger=True,
        ).pack(side=LEFT, padx=8)

        Label(content, textvariable=self.status, anchor="w", fg=UI_MUTED, bg=UI_BG).pack(fill=X, pady=(10, 0))

    def choose_save_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.save_dir), title="Choose Hero Siege save folder")
        if selected:
            self.save_dir = Path(selected)
            self.folder_label.config(text=str(self.save_dir))
            self.refresh_file_list()

    def refresh_file_list(self) -> None:
        self.file_list.delete(0, END)
        self.file_list_paths.clear()
        if not self.save_dir.exists():
            self.set_status(f"Folder does not exist: {self.save_dir}")
            return

        display_paths: list[tuple[str, Path]] = []
        for path in sorted(self.save_dir.glob("herosiege*.hss"), key=lambda p: p.name.lower()):
            display_paths.append((path.name, path))
        sub = self.save_dir / "hs2saves"
        if sub.is_dir():
            for path in sorted(sub.glob("herosiege*.hss"), key=lambda p: p.name.lower()):
                display_paths.append((str(Path("hs2saves") / path.name), path))
        for display, _path in sorted(display_paths, key=lambda item: save_slot_sort_key(item[0])):
            label = save_list_label(display, _path)
            if label in self.file_list_paths:
                label = f"{label}   ({display})"
            self.file_list_paths[label] = _path.resolve()
            self.file_list.insert(END, label)
        self.set_status(f"Found {len(display_paths)} character .hss files.")

    def _path_from_file_list_entry(self, entry: str) -> Path:
        mapped = self.file_list_paths.get(entry)
        if mapped is not None:
            return mapped
        p = Path(entry)
        if len(p.parts) >= 2 and p.parts[0].lower() == "hs2saves":
            return (self.save_dir / p).resolve()
        return (self.save_dir / entry).resolve()

    def open_selected_file(self) -> None:
        selection = self.file_list.curselection()
        if not selection:
            messagebox.showinfo(APP_TITLE, "Select a .hss file first.")
            return
        self.load_file(self._path_from_file_list_entry(self.file_list.get(selection[0])))

    def open_file_dialog(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(self.save_dir),
            title="Open character .hss file",
            filetypes=[("Hero Siege saves", "*.hss"), ("All files", "*.*")],
        )
        if selected:
            self.load_file(Path(selected))

    def load_file(self, path: Path) -> None:
        try:
            text = decode_hss_file(path)
        except Exception as exc:
            if isinstance(exc, HssFormatError):
                messagebox.showinfo(
                    APP_TITLE,
                    f"{path.name} is not a readable character save slot.\n\n"
                    f"{exc}\n\n"
                    "On Steam Deck/Proton, make sure you select the real Hero Siege save folder for the "
                    "same Proton prefix/account that the game is using. Empty slots can be ignored.",
                )
            else:
                messagebox.showerror(APP_TITLE, f"Could not open {path.name}:\n{exc}")
            return

        file_kind = classify_text(text, path)
        if file_kind != "character_ini":
            messagebox.showwarning(
                APP_TITLE,
                f"{path.name} does not look like a character save.\n\n"
                "This simplified editor only edits offline character .hss files.",
            )
            return

        shop_path, shop_text = read_shop_ini_near_character(path)
        self.loaded = LoadedSave(path=path, text=text, file_kind=file_kind, shop_path=shop_path, shop_text=shop_text)
        self.current_file.set(f"{path}  ({file_kind})")
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False)
        shop_note = f" Shop data: {shop_path.name}." if shop_text is not None else " No shop.ini found; one will be created if shop-backed fields are saved."
        self.set_status(f"Loaded {path.name}.{shop_note}")

    def reload_current(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return
        self.load_file(self.loaded.path)

    def _mark_character_fields_dirty(self, *_a: object) -> None:
        if self._suppress_field_trace:
            return
        self._character_field_vars_dirty = True

    def get_raw(self) -> str:
        if self.raw_text is not None and self.raw_text.winfo_exists():
            self.raw_buffer = normalize_line_endings(self.raw_text.get("1.0", END).rstrip("\n"))
        return self.raw_buffer

    def set_raw(self, text: str) -> None:
        self.raw_buffer = normalize_line_endings(text)
        if self.raw_text is not None and self.raw_text.winfo_exists():
            self.raw_text.delete("1.0", END)
            self.raw_text.insert("1.0", self.raw_buffer)

    def open_inventory_inspector(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return
        if self.inventory_window is not None and self.inventory_window.winfo_exists():
            self.inventory_window.lift()
            return

        text = self.get_raw()
        payloads = iter_inventory_payloads(text)
        if not payloads:
            messagebox.showinfo(APP_TITLE, "No decoded inventory payload was found in this save.")
            return

        db_path = default_item_db_path()
        rows: list[dict[str, object]] = []
        for section_name, payload in payloads:
            for container_name, container in payload.items():
                if not isinstance(container, dict):
                    continue
                for item_key, item in container.items():
                    if not isinstance(item, dict):
                        continue
                    data = item.get("data") if isinstance(item.get("data"), dict) else item
                    if not isinstance(data, dict):
                        continue
                    pos = item.get("pos")
                    pos_text = ""
                    if isinstance(pos, list) and len(pos) >= 2:
                        pos_text = f"{format_compact_value(pos[0])},{format_compact_value(pos[1])}"
                    item_name = lookup_item_name(db_path, data.get("b"), data.get("g"))
                    stat_summary = summarize_item_stat_slots(data, db_path)
                    rows.append(
                        {
                            "section": section_name,
                            "container": container_name,
                            "key": str(item_key),
                            "item": item_name or f"item id {format_compact_value(data.get('b', '?'))}",
                            "pos": pos_text,
                            "data": summarize_item_data(data),
                            "stats": stat_summary or "No s1-s6 slots",
                            "raw": item,
                        }
                    )

        self.inventory_window = Toplevel(self.root)
        self.inventory_window.title("Inventory Inspector - Read Only")
        self.inventory_window.geometry("1180x720")
        self.inventory_window.minsize(900, 520)
        self.inventory_window.configure(bg=UI_BG)

        header = Frame(self.inventory_window, padx=12, pady=10, bg=UI_BG)
        header.pack(fill=X)
        Label(
            header,
            text="Inventory Inspector",
            bg=UI_BG,
            fg=UI_TEXT,
            font=("Segoe UI", 13, "bold"),
        ).pack(side=LEFT)
        db_status = f"Item DB: {db_path}" if db_path else "Item DB not found; showing IDs only."
        Label(
            header,
            text=f"Read-only decoded view. {len(rows)} items found. {db_status}",
            bg=UI_BG,
            fg=UI_MUTED,
        ).pack(side=LEFT, padx=(14, 0))

        body = PanedWindow(self.inventory_window, orient="vertical", sashrelief="flat", bg=UI_BG, bd=0)
        body.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))

        table_frame = Frame(body, bg=UI_BG)
        body.add(table_frame, height=390)
        columns = ("section", "container", "item", "pos", "data", "stats")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        tree.heading("section", text="Section")
        tree.heading("container", text="Container")
        tree.heading("item", text="Item")
        tree.heading("pos", text="Pos")
        tree.heading("data", text="Decoded Data")
        tree.heading("stats", text="s1-s6 Stat Slots")
        tree.column("section", width=80, stretch=False)
        tree.column("container", width=170, stretch=False)
        tree.column("item", width=260, stretch=False)
        tree.column("pos", width=70, stretch=False)
        tree.column("data", width=300, stretch=True)
        tree.column("stats", width=420, stretch=True)
        tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = Scrollbar(table_frame, orient=VERTICAL, command=tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        tree.configure(yscrollcommand=scrollbar.set)

        details = ScrolledText(
            body,
            wrap="none",
            font=("Consolas", 9),
            bg=UI_FIELD,
            fg=UI_TEXT,
            insertbackground=UI_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
        )
        body.add(details, height=250)

        row_by_iid: dict[str, dict[str, object]] = {}
        for index, row in enumerate(rows):
            iid = str(index)
            row_by_iid[iid] = row
            tree.insert(
                "",
                END,
                iid=iid,
                values=(
                    row["section"],
                    row["container"],
                    row["item"],
                    row["pos"],
                    row["data"],
                    row["stats"],
                ),
            )

        def show_details(_event: object = None) -> None:
            details.delete("1.0", END)
            selection = tree.selection()
            if not selection:
                details.insert("1.0", "Select an item to inspect its decoded JSON.")
                return
            row = row_by_iid.get(selection[0])
            if not row:
                return
            header_lines = [
                f"Section: {row['section']}",
                f"Container: {row['container']}",
                f"Item: {row['item']}",
                f"Key: {row['key']}",
                f"Decoded data: {row['data']}",
                f"Stat slots: {row['stats']}",
                "",
                "Raw decoded item JSON:",
                "",
            ]
            details.insert("1.0", "\n".join(header_lines) + json.dumps(row["raw"], ensure_ascii=False, indent=2))

        tree.bind("<<TreeviewSelect>>", show_details)
        if rows:
            tree.selection_set("0")
            tree.focus("0")
            show_details()
        else:
            details.insert("1.0", "No item rows were found inside the inventory payload.")

        self.inventory_window.protocol("WM_DELETE_WINDOW", self.close_inventory_inspector)

    def close_inventory_inspector(self) -> None:
        if self.inventory_window is not None and self.inventory_window.winfo_exists():
            self.inventory_window.destroy()
        self.inventory_window = None

    def open_raw_window(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return
        if self.raw_window is not None and self.raw_window.winfo_exists():
            self.raw_window.lift()
            return

        self.raw_window = Toplevel(self.root)
        self.raw_window.title("Raw Decoded Text")
        self.raw_window.geometry("900x620")
        self.raw_window.configure(bg=UI_BG)

        top = Frame(self.raw_window, padx=10, pady=10, bg=UI_BG)
        top.pack(fill=X)
        self.make_button(top, "Refresh Fields From Raw", self.populate_fields_from_raw).pack(side=LEFT)
        Label(top, text="Search", bg=UI_BG, fg=UI_TEXT).pack(side=LEFT, padx=(14, 6))
        search_entry = self.make_entry(top, self.raw_search_var, width=28)
        search_entry.pack(side=LEFT)
        search_entry.bind("<Return>", lambda _event: self.find_raw_text(1))
        self.make_button(top, "Find Next", lambda: self.find_raw_text(1)).pack(side=LEFT, padx=(8, 0))
        self.make_button(top, "Previous", lambda: self.find_raw_text(-1)).pack(side=LEFT, padx=(6, 0))
        Label(top, textvariable=self.raw_search_status, bg=UI_BG, fg=UI_MUTED).pack(side=LEFT, padx=(10, 0))

        self.raw_text = ScrolledText(
            self.raw_window,
            undo=True,
            wrap="none",
            font=("Consolas", 9),
            bg=UI_FIELD,
            fg=UI_TEXT,
            insertbackground=UI_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
        )
        self.raw_text.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.raw_text.insert("1.0", self.raw_buffer)
        self.raw_text.tag_configure("raw_find", background=UI_NOTICE, foreground="#111827")
        self.raw_text.bind(
            "<KeyRelease>",
            lambda _event: self.populate_fields_from_raw(show_errors=False, update_status=False),
        )
        self.raw_text.bind(
            "<<Paste>>",
            lambda _event: self.root.after(
                1, lambda: self.populate_fields_from_raw(show_errors=False, update_status=False)
            ),
        )
        self.raw_window.protocol("WM_DELETE_WINDOW", self.close_raw_window)
        search_entry.focus_set()

    def find_raw_text(self, direction: int = 1) -> None:
        if self.raw_text is None or not self.raw_text.winfo_exists():
            return
        query = self.raw_search_var.get()
        self.raw_text.tag_remove("raw_find", "1.0", END)
        if not query:
            self.raw_search_status.set("Type a search value.")
            return

        if direction < 0:
            start = self.raw_text.index("insert -1c")
            match = self.raw_text.search(query, start, stopindex="1.0", backwards=True, nocase=True)
            if not match:
                match = self.raw_text.search(query, END, stopindex="1.0", backwards=True, nocase=True)
        else:
            start = self.raw_text.index("insert +1c")
            match = self.raw_text.search(query, start, stopindex=END, nocase=True)
            if not match:
                match = self.raw_text.search(query, "1.0", stopindex=END, nocase=True)

        if not match:
            self.raw_search_status.set("No matches.")
            return

        end = f"{match}+{len(query)}c"
        self.raw_text.tag_add("raw_find", match, end)
        self.raw_text.mark_set("insert", match)
        self.raw_text.see(match)
        line, column = match.split(".")
        self.raw_search_status.set(f"Found at line {line}, column {int(column) + 1}.")

    def close_raw_window(self) -> None:
        self.get_raw()
        if self.raw_window is not None and self.raw_window.winfo_exists():
            self.raw_window.destroy()
        self.raw_window = None
        self.raw_text = None

    def populate_fields_from_raw(self, show_errors: bool = True, update_status: bool = True) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return

        text = self.get_raw()
        self._suppress_field_trace = True
        try:
            for spec, var in self.field_vars.items():
                source_text = self.loaded.shop_text if is_shop_backed_field(spec) and self.loaded.shop_text is not None else text
                var.set(get_field_value(source_text, spec))
                widget = self.field_widgets.get(spec)
                if spec.section == "0" and spec.key == "class" and widget is not None:
                    try:
                        widget.selection_clear()
                    except Exception:
                        pass
        except Exception as exc:
            if show_errors:
                messagebox.showerror(APP_TITLE, f"Could not parse character fields:\n{exc}")
            return
        finally:
            self._suppress_field_trace = False
        self._character_field_vars_dirty = False
        if update_status:
            self.set_status("Character fields loaded from raw text.")

    def apply_unlock_all_waypoints(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            text = unlock_all_waypoints(text)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not unlock waypoints:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status("All act/zone waypoint values set to 4 in raw text. Save With Backup to write the file.")

    def apply_unlock_inferno_difficulty(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            text = unlock_inferno_difficulty(text)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not unlock Inferno difficulty:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status("Inferno difficulty/progress flags set in raw text. Save With Backup to write the file.")

    def merge_character_field_vars_into_text(self, text: str) -> str:
        for spec, var in self.field_vars.items():
            if is_shop_backed_field(spec):
                continue
            value = var.get().strip()
            if value == "":
                continue
            text = set_field_value(text, spec, value)
        return text

    def merge_shop_field_vars_into_text(self, text: str | None) -> str:
        text = text if text is not None else default_shop_ini_text()
        for spec, var in self.field_vars.items():
            if not is_shop_backed_field(spec):
                continue
            value = var.get().strip()
            if value == "":
                continue
            text = set_field_value(text, spec, value)
        return text

    def prepared_texts_for_save(self, shop_path: Path | None = None) -> tuple[str, str | None] | None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return None
        try:
            text = self.get_raw()
            shop_text = self.loaded.shop_text
            if shop_path is not None and shop_path != self.loaded.shop_path and shop_path.exists():
                shop_text = normalize_line_endings(shop_path.read_text(encoding="utf-8-sig", errors="ignore"))
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
                shop_text = self.merge_shop_field_vars_into_text(shop_text)
                self.set_raw(text)
            elif shop_text is not None:
                shop_text = self.merge_shop_field_vars_into_text(shop_text)
            return text, shop_text
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Character fields could not be saved:\n{exc}")
            return None

    def save_current(self, *, show_success_dialog: bool = True) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return

        prepared = self.prepared_texts_for_save(self.loaded.shop_path)
        if prepared is None:
            return
        text, shop_text = prepared

        try:
            backup = write_hss_file(self.loaded.path, text, create_backup=True)
            shop_backup = None
            if shop_text is not None and self.loaded.shop_path is not None:
                shop_backup = write_plain_ini_file(self.loaded.shop_path, shop_text, create_backup=self.loaded.shop_path.exists())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Save failed:\n{exc}")
            return

        self.loaded = LoadedSave(self.loaded.path, text, classify_text(text, self.loaded.path), self.loaded.shop_path, shop_text)
        self.set_raw(text)
        self._character_field_vars_dirty = False
        shop_part = f" Shop.ini backup: {shop_backup.name if shop_backup else 'none'}." if shop_text is not None else ""
        self.set_status(f"Saved: {self.loaded.path.resolve()}. Backup: {backup.name if backup else 'none'}.{shop_part}")
        if show_success_dialog:
            extra = f"\n\nShop data:\n{self.loaded.shop_path}\nBackup:\n{shop_backup}" if shop_text is not None else ""
            messagebox.showinfo(APP_TITLE, f"Saved successfully.\n\n{self.loaded.path.resolve()}\n\nBackup:\n{backup}{extra}")

    def save_as(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return

        selected = filedialog.asksaveasfilename(
            initialdir=str(self.loaded.path.parent),
            initialfile=self.loaded.path.name,
            defaultextension=".hss",
            filetypes=[("Hero Siege saves", "*.hss"), ("All files", "*.*")],
        )
        if not selected:
            return

        path = Path(selected)
        shop_path = path.parent / "shop.ini" if self.loaded.shop_path is not None else None
        prepared = self.prepared_texts_for_save(shop_path)
        if prepared is None:
            return
        text, shop_text = prepared

        try:
            backup = write_hss_file(path, text, create_backup=path.exists())
            if shop_text is not None and shop_path is not None:
                write_plain_ini_file(shop_path, shop_text, create_backup=shop_path.exists())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Save As failed:\n{exc}")
            return

        self.loaded = LoadedSave(path, text, classify_text(text, path), shop_path, shop_text)
        self.current_file.set(f"{path}  ({self.loaded.file_kind})")
        self.set_raw(text)
        self._character_field_vars_dirty = False
        self.set_status(f"Saved as {path.name}. Backup: {backup.name if backup else 'none'}")

    def set_status(self, message: str) -> None:
        self.status.set(message)


def run_roundtrip_test(paths: list[Path]) -> bool:
    ok = True
    for path in paths:
        try:
            text = decode_hss_file(path)
            encoded = encode_hss_text(text)
            decoded = decode_hss_bytes(encoded)
            if decoded != text:
                print(f"FAIL roundtrip mismatch: {path}")
                ok = False
        except Exception as exc:
            print(f"FAIL {path}: {exc}")
            ok = False
    return ok


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", nargs="*", type=Path, help="Decode and re-encode selected .hss files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.self_test is not None:
        paths = args.self_test or list(DEFAULT_SAVE_DIR.glob("*.hss"))
        return 0 if run_roundtrip_test(paths) else 1

    root = Tk()
    HssEditorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
