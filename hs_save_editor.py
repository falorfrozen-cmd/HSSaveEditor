#!/usr/bin/env python3
"""Hero Siege offline character save editor and Season 10 progression forge."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import sys
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
    Canvas,
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


APP_VERSION = "1.2.8"
APP_TITLE = f"Hero Siege Character Save Editor v{APP_VERSION}"
HERO_SIEGE_ROOT = Path.home() / "AppData" / "Local" / "Hero_Siege"
DEFAULT_SAVE_DIR = HERO_SIEGE_ROOT
S10_ACT_COUNT = 9
S10_ZONE_SLOTS_PER_ACT = 10
S10_MAX_CAMPAIGN_CLEAR = 4
S10_ETHER_NODE_COUNT = 216
ETHER_SAVE_VERSION = 1
ETHER_LOADOUT_COUNT = 8
QUESTLOG_SECTION = "4"
CHARM_SLOT_QUEST_CHAIN = "fallOfDarkness"
CHARM_SLOT_QUEST_PROGRESS = 4
CHARM_SLOT_QUEST_DIFFICULTY = 3
CHARM_SLOT_MAX_CELLS = 30
LEGACY_CHARM_SLOT_SAVE_SECTION = "0"
LEGACY_CHARM_SLOT_SAVE_KEY = "charmSlot"
S10_TARGET_TOTAL_ETHER_POINTS = 800
S10_TALENT_LOADOUT_COUNT = 8
# Every current S10 sub-skill tree has fourteen local nodes. The first ten are
# the ordinary 5-rank nodes; s11-s14 are the mutually exclusive major nodes
# and must never be changed by the small-node forge action.
S10_SMALL_SUBTALENT_NODE_IDS = tuple(range(1, 11))
S10_MAJOR_SUBTALENT_NODE_IDS = tuple(range(11, 15))
S10_SMALL_SUBTALENT_BALANCED_RANK = 5.0
S10_SUBTALENT_POINT_BUDGET = 50
# S10 awards Ether through 25 quests. A completed quest advances its chain by
# two save stages; the values below are the native final progress for each
# chain. Difficulty is metadata for newly-created questlog slots.
S10_ETHER_QUEST_CHAINS = (
    ("etheringWormhole", 22, 3),
    ("etheringHell", 6, 2),
    ("etheringInferno", 2, 3),
    ("etheringDamnation", 2, 3),
    ("etheringEquilibrium", 2, 3),
    ("etheringArchDemons", 4, 3),
    ("etheringChallenge", 4, 2),
    ("etheringChallengeInferno", 4, 3),
    ("etheringMonsterSlayer", 4, 3),
)
S10_ETHER_POINT_WEIGHTS = {
    "etheringWormhole": 1,
    "etheringHell": 9,
    "etheringInferno": 5,
    "etheringDamnation": 3,
    "etheringEquilibrium": 3,
    "etheringArchDemons": 5,
    "etheringChallenge": 5,
    "etheringChallengeInferno": 5,
    "etheringMonsterSlayer": 4,
}
UI_BG = "#09070d"
UI_PANEL = "#100c14"
UI_CARD = "#1a1420"
UI_CARD_2 = "#130f19"
UI_BORDER = "#4a354d"
UI_TEXT = "#f2e9d7"
UI_MUTED = "#a394a6"
UI_FIELD = "#08060b"
UI_ACCENT = "#e1ad3f"
UI_ACCENT_DARK = "#b87817"
UI_WAYPOINT = "#2854a5"
UI_WAYPOINT_DARK = "#1c3b76"
UI_DANGER = "#a02738"
UI_DANGER_DARK = "#741c2a"
UI_NOTICE = "#d89c2b"
UI_GOLD_BRIGHT = "#ffd56a"
UI_PURPLE = "#7136b8"
UI_PURPLE_DARK = "#522489"
UI_ETHER = "#159bb2"
UI_ETHER_DARK = "#0d6e80"
UI_SUBTALENT = "#2f8f5b"
UI_SUBTALENT_DARK = "#216b43"


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


class EtherFormatError(ValueError):
    """Raised when an etherN.hss sidecar is not valid Season 10 Ether JSON."""


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


@dataclass(frozen=True)
class SubtalentTreeDefinition:
    talent_id: int
    skill_name: str
    node_names: tuple[str, ...]


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
    18: "Jötunn",
    19: "Illusionist",
    20: "Exo",
    21: "Butcher",
    22: "Stormweaver",
    23: "Bard",
    24: "Prophet",
}
CLASS_NAME_TO_ID = {name.lower(): class_id for class_id, name in CLASS_ID_TO_NAME.items()}
CLASS_DISPLAY_VALUES = [CLASS_ID_TO_NAME[i] for i in sorted(CLASS_ID_TO_NAME)]
CLASS_ID_TO_TRANSLATION_PREFIX = {
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
    11: "DemonSlayer",
    12: "Demonspawn",
    13: "Shaman",
    14: "WhiteMage",
    15: "Marauder",
    16: "PlagueDoctor",
    17: "ShieldLancer",
    18: "Jotunn",
    19: "Illusionist",
    20: "Exo",
    21: "Butcher",
    22: "Stormweaver",
    23: "Bard",
    24: "Prophet",
}

# Season 10 reserves talent IDs 0 and 1, then stores exactly 18 IDs per class.
# This order was verified against the game's EXE xrefs and its 432 talent icon
# records. Translation CSV rows are not an ID table: several classes contain
# legacy rows or use a different display order, so their row positions must
# never be used as save IDs.
S10_CLASS_TALENT_KEYS: dict[int, tuple[str, ...]] = {
    1: ("weaponMaster", "charge", "stoneskin", "devastatingCharge", "norseResistance", "defensiveShout", "odinsFury", "battleAgility", "combatOrders", "seismicSlam", "bruteForce", "zeal", "monsterThrow", "ymirsChampion", "shockwave", "whirlwind", "berserk", "demolishingWinds"),
    2: ("blazingTrail", "fireEnchant", "phoenixFlight", "infernoSlash", "ignite", "fireShield", "searingChains", "fieryPresence", "avatarOfFire", "fireBall", "breathOfFire", "meteor", "scorchingAura", "hydra", "comet", "fireNova", "volcano", "armageddon"),
    3: ("trickShot", "vault", "multishot", "arrowRain", "homingMissile", "criticalAccuracy", "arrowRampage", "agility", "volatileShot", "arrowTurret", "fragGrenade", "beacon", "cannonTurret", "turretMastery", "landMine", "rocketTurret", "masterMechanic", "gunnerDrone"),
    4: ("buckshot", "grenado", "explosiveBarrel", "cannonball", "explosiveBullet", "powderTrail", "kneeCap", "bombBarrage", "rapidFire", "freezeChainShot", "torrent", "frozenLead", "parrot", "setSail", "anchorSwing", "remiges", "treasureHunter", "landAhoy"),
    5: ("sandCarver", "cloudOfSand", "sandGush", "sandEntombment", "oasisAura", "sandTremors", "mysticSand", "dissipatingTornado", "sandVortex", "bladeStrike", "scimitarCharge", "eyeOfRa", "sunRay", "flyingScimitar", "rupture", "chainSlice", "phantomBlade", "hemorrhage"),
    6: ("oilSpill", "pipeBombs", "moonshineMolotov", "tireFire", "combustibleOil", "hillbillyRage", "spontaneousCombustion", "moonshineMadness", "pickupRaid", "durableWear", "chainsawSlash", "loggersEndurance", "chainsawMassacre", "chainsawMastery", "experiencedLogger", "revvedUp", "rogueChainsaw", "treeTrunkTriumph"),
    7: ("boneShred", "meatShield", "meatBomb", "poisonBreath", "boneSpear", "cursedGround", "boneSpirit", "corpseExplosion", "poisonNova", "amplifyDamage", "raiseSkeletonWarrior", "raiseSkeletonMage", "skeletonMastery", "lifeTap", "summonFrenzy", "summonDamnedLegion", "summonResistances", "summonVengefulSpirit"),
    8: ("quickSlash", "battleGlance", "shurikenThrow", "explosiveKunai", "evasion", "smokeBomb", "warriorsSpirit", "bushido", "liveByTheSword", "bladeBarrier", "explodingBolas", "fanOfKnives", "forHonor", "omnislash", "burstOfSpeed", "shadowStep", "wayOfTheWarrior", "empiresSlash"),
    9: ("vengeance", "thunderShield", "divineStorm", "fanaticismAura", "holyShockAura", "lightningFury", "ballLightning", "eyeOfTheStorm", "thorsFury", "holyBolt", "divineWisdom", "lightsEmbrace", "holyRetribution", "holyNova", "holyHammer", "holyAura", "fistOfTheHeavens", "theVeneratedOne"),
    10: ("noxiousStrike", "causticSpearhead", "leapingAmbush", "deathFromAbove", "toxicRemains", "masterPoisoner", "jungleCamouflage", "thrillOfTheHunt", "envenom", "astropesGift", "feint", "rebound", "spearnage", "stormDash", "thunderGoddessesChosen", "chooserOfTheSlain", "thunderFury", "astropesBattleMaiden"),
    11: ("triggerFinger", "eagleEye", "execute", "bulletHell", "shredderTrap", "possessedBullet", "demonsPresence", "concentrationAura", "absoluteMayhem", "fastSlices", "demonsCalling", "heartAttack", "shadowAnomalies", "soulLeech", "swordHandler", "demonsShield", "sliceOfShadows", "demonForm"),
    12: ("boneFragments", "impale", "ossification", "boneStorm", "singleOut", "cartilageBuildUp", "ominousPresence", "spinalTap", "boneBarrage", "bloodBolts", "manaPoolAura", "gutSpread", "manaShield", "manaDevour", "demonicPresence", "bloodSurge", "bloodDemons", "bloodTendrils"),
    13: ("tectonicBoulder", "twisters", "rockFragments", "earthBind", "tornado", "earthsGrace", "meteorStorm", "naturesProphet", "fissures", "earthTotem", "spiritualGuide", "spiritWolves", "scentOfTheWolf", "stormTotem", "fireTotem", "fractalMind", "astralIntellect", "chaosTotem"),
    14: ("satansMark", "restlessSpirits", "digestSouls", "shadowBolt", "soulSpurn", "martyr", "darkOath", "malediction", "blackMass", "heavenlyFire", "burstOfLight", "flashHeal", "benediction", "divineHealing", "chainOfHolyLight", "holyShield", "healingZone", "manaOrb"),
    15: ("heavyBall", "bouncingGrenade", "unstableBomb", "theBigBoom", "wreckingBall", "crazyGrapple", "flailMastery", "bombardment", "forceOverwhelming", "serratedChains", "retiariusNet", "chainTrap", "titaniumChains", "masterTrapMaker", "rendFlesh", "madnessControl", "resilientGladiator", "annihilation"),
    16: ("surgicalBloodLetting", "malpractice", "crowMasksPresence", "bloodSustenance", "miasma", "boosterShot", "lifeBloodAura", "devoutDoctor", "defunctSurgeon", "plagueOfRats", "toxicFlask", "crematus", "oops", "chantOfWeakness", "explodingMice", "jarOfLeeches", "plagueMaster", "randyTheRancidRat"),
    17: ("gloriousStrike", "commendingBanner", "battleCharge", "lanceThrust", "parry", "armorCrush", "crushingLance", "lanceThrow", "glory", "shieldSlam", "taunt", "counter", "knightsResilience", "damageReflect", "honedDefenses", "shieldWall", "knightsVigor", "lastStand"),
    18: ("frozenBoulder", "breathOfIce", "powerOfTheAncients", "orbOfFrost", "frozenHide", "icicles", "portalOfIce", "avatarOfFrost", "blizzard", "glacialTremors", "flashFreeze", "freezingLeap", "permaFrost", "glacialArmor", "frostSunder", "avalanche", "absoluteZero", "theEmbodimentOfAurgelmir"),
    19: ("sandGuardian", "piercingSand", "callForWar", "linkOfSand", "dissipation", "spiritLink", "cheapShot", "circleOfGuardians", "combatOrder", "ageProliferation", "gravitationalSlam", "splitReality", "sandsOfTime", "timeDeceleration", "dimensionalDisplacement", "precognition", "expansiveMind", "temporalHeroes"),
    20: ("scorchingWhip", "whiplash", "solarFlare", "shineBright", "solarDash", "blindingLight", "solarForm", "solarBurst", "supernova", "collision", "darkSideofTheMoon", "tsunami", "asteroid", "lunarForm", "lunarOrbit", "bloodMoon", "moonlight", "blackHole"),
    21: ("slicingThrow", "furiousStrike", "holyForm", "unholyForm", "sacrilegiousScorn", "endingFate", "spiritualDuality", "awakeningFury", "insatiableHunger", "chainRip", "brutalizingSlash", "fuelToFire", "hungerForBlood", "butchersHook", "chainSwing", "submergedKnives", "enragedMania", "blender"),
    22: ("chargedBolts", "manaFiend", "pulsingCharge", "lightningSurge", "gateway", "chainLightning", "staticShock", "stormCloud", "symphonyOfThunder", "electricCells", "stormBolt", "highVoltageAura", "loadedPulse", "waveLength", "theBatteryWithin", "hyperCharged", "apocalypticThunder", "afterShock"),
    23: ("slayingRiffs", "insaneRiff", "visceralGrowl", "ampingUp", "sacrilegiousSymphony", "satansMelody", "soundsOfSilence", "highDb", "progeniesOfTheGreatCataclysm", "headBanger", "crowdPummeler", "crowdDiver", "adrenalineMomentum", "cravingForAttention", "pyroTechnician", "cravingForAnotherKilling", "antiSocialPitFighter", "moshpitMassacre"),
    24: ("carrionWorm", "thornedRoots", "raven", "blessedNature", "summonEnt", "thornedBranch", "spiritOfForest", "deepRooted", "entColossus", "spiritOfWendigo", "woundingPaw", "skinWalker", "leapingCharge", "spiritOfEnt", "maelstromOfFrost", "swampsEssence", "manaDwelling", "spiritOfHawk"),
}

# The current translationsSubTalent.csv retains these historical parent names.
# Values are canonicalized keys from the EXE-confirmed talent table above.
S10_SUBTALENT_PARENT_ALIASES: dict[tuple[str, str], str] = {
    ("viking", "throw"): "monsterthrow",
    ("pirate", "freezingchainshot"): "freezechainshot",
    ("redneck", "chainslash"): "chainsawslash",
    ("necromancer", "raiseskeleton"): "raiseskeletonwarrior",
    ("necromancer", "vengefulspirit"): "summonvengefulspirit",
    ("jotunn", "sweepfreeze"): "frostsunder",
    ("prophet", "spiritofvendigo"): "spiritofwendigo",
    ("prophet", "stormhawk"): "spiritofhawk",
}


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


def ether_path_for_character(path: Path) -> Path:
    slot = save_slot_number(path.name)
    if slot is None:
        raise EtherFormatError(f"Could not determine the character slot from {path.name}.")
    return path.with_name(f"ether{slot}.hss")


def default_ether_data() -> dict[str, object]:
    return {"version": ETHER_SAVE_VERSION, "loadouts": [{} for _ in range(ETHER_LOADOUT_COUNT)]}


def normalize_ether_data(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise EtherFormatError("Ether payload must be a JSON object.")
    version = data.get("version")
    if version != ETHER_SAVE_VERSION:
        raise EtherFormatError(f"Unsupported Ether save version: {version!r}.")
    loadouts = data.get("loadouts")
    if not isinstance(loadouts, list):
        raise EtherFormatError("Ether payload has no loadouts list.")

    normalized = json.loads(json.dumps(data))
    normalized_loadouts = normalized["loadouts"]
    while len(normalized_loadouts) < ETHER_LOADOUT_COUNT:
        normalized_loadouts.append({})
    for index, loadout in enumerate(normalized_loadouts):
        if not isinstance(loadout, dict):
            raise EtherFormatError(f"Ether loadout {index + 1} is not an object.")
        nodes = loadout.get("nodes", [])
        if not isinstance(nodes, list):
            raise EtherFormatError(f"Ether loadout {index + 1} nodes must be a list.")
        clean_nodes: list[int] = []
        for node in nodes:
            if isinstance(node, bool):
                raise EtherFormatError(f"Ether loadout {index + 1} contains an invalid node ID.")
            try:
                node_id = int(node)
            except (TypeError, ValueError) as exc:
                raise EtherFormatError(f"Ether loadout {index + 1} contains an invalid node ID: {node!r}.") from exc
            if node_id != node or not 0 <= node_id < S10_ETHER_NODE_COUNT:
                raise EtherFormatError(f"Ether node ID must be between 0 and {S10_ETHER_NODE_COUNT - 1}: {node!r}.")
            clean_nodes.append(node_id)
        if clean_nodes:
            loadout["nodes"] = clean_nodes
        else:
            loadout.pop("nodes", None)
    return normalized


def decode_ether_bytes(raw: bytes | str) -> dict[str, object]:
    encoded = raw.encode("ascii") if isinstance(raw, str) else raw
    cleaned = b"".join(encoded.replace(b"\x00", b"").split())
    if not cleaned:
        return default_ether_data()
    try:
        payload = base64.b64decode(cleaned, validate=True)
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise EtherFormatError(f"Could not decode Ether sidecar: {exc}") from exc
    return normalize_ether_data(data)


def read_ether_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return default_ether_data()
    return decode_ether_bytes(path.read_bytes())


def encode_ether_data(data: object) -> bytes:
    normalized = normalize_ether_data(data)
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(payload) + b"\x00"


def write_ether_file(path: Path, data: object, create_backup: bool = True) -> Path | None:
    backup_path = None
    if create_backup and path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak_{timestamp}")
        shutil.copy2(path, backup_path)
    path.write_bytes(encode_ether_data(data))
    return backup_path


def ether_loadout_nodes(data: object, loadout_index: int) -> list[int]:
    normalized = normalize_ether_data(data)
    loadouts = normalized["loadouts"]
    if not 0 <= loadout_index < len(loadouts):
        raise EtherFormatError(f"Ether loadout must be between 1 and {len(loadouts)}.")
    return list(loadouts[loadout_index].get("nodes", []))


def set_ether_loadout_nodes(data: object, loadout_index: int, nodes: list[int]) -> dict[str, object]:
    normalized = normalize_ether_data(data)
    loadouts = normalized["loadouts"]
    if not 0 <= loadout_index < len(loadouts):
        raise EtherFormatError(f"Ether loadout must be between 1 and {len(loadouts)}.")
    loadout = loadouts[loadout_index]
    if nodes:
        loadout["nodes"] = list(nodes)
    else:
        loadout.pop("nodes", None)
    return normalize_ether_data(normalized)


def parse_ether_node_ids(value: str) -> list[int]:
    value = value.strip()
    if not value:
        return []
    nodes: list[int] = []
    for token in re.split(r"[\s,;]+", value):
        if not token:
            continue
        try:
            node_id = int(token)
        except ValueError as exc:
            raise EtherFormatError(f"Invalid Ether node ID: {token!r}.") from exc
        if not 0 <= node_id < S10_ETHER_NODE_COUNT:
            raise EtherFormatError(f"Ether node ID must be between 0 and {S10_ETHER_NODE_COUNT - 1}: {node_id}.")
        nodes.append(node_id)
    return nodes


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


def remove_ini_key(text: str, section: str, key: str) -> str:
    """Remove every instance of a key from one INI section only."""
    text = normalize_line_endings(text)
    section_pattern = re.compile(rf"(?ms)^(\[{re.escape(section)}\]\s*)(.*?)(?=^\[|\Z)")
    match = section_pattern.search(text)
    if not match:
        return text

    body = match.group(2)
    key_pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*(?:\n|\Z)")
    body = key_pattern.sub("", body)
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


def is_odyssey_character(text: str) -> bool:
    """Return the native local-character Odyssey flag."""
    raw = get_ini_value(text, "0", "soloselffound") or "0"
    try:
        return parse_number(raw) != 0
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid Odyssey flag: {raw!r}.") from exc


def convert_character_to_odyssey(text: str) -> str:
    """Enable Odyssey without changing character progress or equipment."""
    if not get_ini_value(text, "0", "class"):
        raise ValueError("The save has no character class field.")
    return set_ini_value(text, "0", "soloselffound", "1", "number")


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


def active_talent_loadout_index(text: str) -> int:
    """Return the character's active S10 talent loadout as a zero-based index."""
    raw = get_ini_value(text, "0", "talent_loadout") or "0"
    try:
        value = parse_number(raw)
        index = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid talent loadout value: {raw!r}.") from exc
    if value != index or not 0 <= index < S10_TALENT_LOADOUT_COUNT:
        raise ValueError(
            f"Talent loadout must be between 0 and {S10_TALENT_LOADOUT_COUNT - 1}: {raw!r}."
        )
    return index


def decode_subtalent_map(text: str, loadout_index: int) -> dict[str, dict[str, object]]:
    """Decode one loadout's saved sub-skill allocations without inventing trees."""
    if not 0 <= loadout_index < S10_TALENT_LOADOUT_COUNT:
        raise ValueError(f"Talent loadout must be between 0 and {S10_TALENT_LOADOUT_COUNT - 1}.")
    encoded = get_ini_value(text, f"talent_loadout_{loadout_index}", "subtalents")
    if not encoded:
        return {}
    decoded = decode_base64_json(encoded)
    if not isinstance(decoded, dict):
        raise ValueError(f"Talent loadout {loadout_index + 1} has an invalid subtalents payload.")

    clean: dict[str, dict[str, object]] = {}
    for talent_key, nodes in decoded.items():
        if not isinstance(talent_key, str) or not re.fullmatch(r"t\d+", talent_key):
            raise ValueError(f"Invalid sub-skill tree key in loadout {loadout_index + 1}: {talent_key!r}.")
        if not isinstance(nodes, dict):
            raise ValueError(f"Sub-skill tree {talent_key} is not a node map.")
        clean[talent_key] = nodes
    return clean


def allocated_talent_ids(text: str, loadout_index: int) -> set[int]:
    """Return non-zero talent IDs allocated in one S10 loadout."""
    section_name = f"talent_loadout_{loadout_index}"
    body = next((body for name, body in iter_ini_sections(text) if name == section_name), "")
    allocated: set[int] = set()
    for match in re.finditer(r'(?m)^\s*talent_(\d+)\s*=\s*"?([+-]?[\d.]+)"?\s*$', body):
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        if value > 0:
            allocated.add(int(match.group(1)))
    return allocated


def _read_translation_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path).replace("/", "\\").casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def registry_steam_roots() -> list[Path]:
    """Find Steam itself, including non-default Windows installations."""
    roots: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            for hive, key_name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        for value_name in ("SteamPath", "InstallPath"):
                            try:
                                value, _value_type = winreg.QueryValueEx(key, value_name)
                            except OSError:
                                continue
                            if isinstance(value, str) and value.strip():
                                roots.append(Path(value))
                except OSError:
                    continue
        except ImportError:
            pass
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value) / "Steam")
    roots.append(Path(r"C:\Program Files (x86)\Steam"))
    return unique_paths(roots)


def steam_library_roots(steam_roots: list[Path] | None = None) -> list[Path]:
    """Read every configured Steam library from libraryfolders.vdf."""
    libraries: list[Path] = []
    for root in registry_steam_roots() if steam_roots is None else steam_roots:
        libraries.append(root)
        vdf_path = root / "steamapps" / "libraryfolders.vdf"
        try:
            vdf_text = vdf_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw_path in re.findall(r'"path"\s+"([^"]+)"', vdf_text, flags=re.IGNORECASE):
            libraries.append(Path(raw_path.replace(r"\\", "\\")))
    return unique_paths(libraries)


def hero_siege_install_roots(steam_roots: list[Path] | None = None) -> list[Path]:
    """Resolve Hero Siege through its Steam manifest and known folder names."""
    installs: list[Path] = []
    configured = os.environ.get("HERO_SIEGE_DIR")
    if configured:
        installs.append(Path(configured))
    for library in steam_library_roots(steam_roots):
        steamapps = library / "steamapps"
        manifest = steamapps / "appmanifest_269210.acf"
        try:
            manifest_text = manifest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            manifest_text = ""
        install_match = re.search(r'"installdir"\s+"([^"]+)"', manifest_text, flags=re.IGNORECASE)
        if install_match:
            installs.append(steamapps / "common" / install_match.group(1))
        installs.extend((steamapps / "common" / "HeroSiege", steamapps / "common" / "Hero Siege"))
    return unique_paths(installs)


def game_translation_file_pair() -> tuple[Path, Path] | None:
    """Locate the installed game's current talent and subtalent translations."""
    roots: list[Path] = [Path(sys.executable).resolve().parent, Path.cwd()]
    for install_root in hero_siege_install_roots():
        roots.extend((install_root, install_root / "bin"))

    seen: set[Path] = set()
    for root in unique_paths(roots):
        try:
            root = root.resolve()
        except OSError:
            continue
        if root in seen:
            continue
        seen.add(root)
        talent_path = root / "translationsTalent.csv"
        subtalent_path = root / "translationsSubTalent.csv"
        if talent_path.is_file() and subtalent_path.is_file():
            return talent_path, subtalent_path
    return None


def canonical_skill_key(value: str) -> str:
    """Normalize harmless translation-key differences such as Drone/Drones."""
    key = re.sub(r"[^a-z0-9]", "", value.casefold())
    return key[:-1] if key.endswith("s") else key


def canonical_subtalent_parent(class_prefix: str, value: str) -> str:
    key = canonical_skill_key(value)
    return S10_SUBTALENT_PARENT_ALIASES.get((class_prefix.casefold(), key), key)


def talent_names_from_translations(talent_text: str) -> dict[str, str]:
    """Return localized talent names keyed by their stable translation key."""
    names: dict[str, str] = {}
    for line in talent_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("|")
        key = parts[0].strip() if parts else ""
        if not key.startswith("talent_name_"):
            continue
        skill_key = key.removeprefix("talent_name_")
        skill_name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else skill_key
        names.setdefault(skill_key.casefold(), skill_name)
    return names


def class_id_from_translation_prefix(class_prefix: str) -> int:
    for class_id, prefix in CLASS_ID_TO_TRANSLATION_PREFIX.items():
        if prefix.casefold() == class_prefix.casefold():
            return class_id
    raise ValueError(f"Unsupported class translation prefix: {class_prefix}.")


def verified_class_talent_keys(class_id: int, talent_text: str) -> tuple[str, ...]:
    """Return the EXE-confirmed talent order after checking the live translation table."""
    keys = S10_CLASS_TALENT_KEYS.get(class_id)
    if keys is None or len(keys) != 18 or len(set(map(str.casefold, keys))) != 18:
        raise ValueError(f"The verified Season 10 talent map is invalid for class ID {class_id}.")
    translated = talent_names_from_translations(talent_text)
    missing = [key for key in keys if key.casefold() not in translated]
    if missing:
        class_name = CLASS_ID_TO_NAME.get(class_id, str(class_id))
        raise ValueError(
            f"The current game's {class_name} talent table is newer than this editor "
            f"(missing verified keys: {', '.join(missing)})."
        )
    return keys


def active_subtalent_offsets_from_translations(
    class_prefix: str,
    talent_text: str,
    subtalent_text: str,
    allocated_offsets: set[int] | None = None,
) -> tuple[int, ...]:
    """Resolve active-skill positions using the EXE-confirmed 18-talent order."""
    parent_pattern = re.compile(
        rf"^sub{re.escape(class_prefix)}(.+?)(\d{{1,2}})\|",
        re.IGNORECASE,
    )
    parents: set[str] = set()
    for line in subtalent_text.splitlines():
        match = parent_pattern.match(line.strip())
        if not match:
            continue
        local_id = int(match.group(2))
        if 1 <= local_id <= 14:
            parents.add(canonical_subtalent_parent(class_prefix, match.group(1)))
    if not parents:
        raise ValueError(f"No subskill definitions were found for {class_prefix}.")

    class_id = class_id_from_translation_prefix(class_prefix)
    talent_keys = verified_class_talent_keys(class_id, talent_text)
    offsets = tuple(
        offset
        for offset, key in enumerate(talent_keys)
        if canonical_skill_key(key) in parents
    )
    if not offsets:
        raise ValueError(f"No active {class_prefix} talent offsets were resolved.")
    return offsets


def subtalent_tree_definitions_from_translations(
    class_prefix: str,
    class_id: int,
    talent_text: str,
    subtalent_text: str,
    allocated_offsets: set[int] | None = None,
) -> tuple[SubtalentTreeDefinition, ...]:
    """Resolve localized node names for every active skill in one class block."""
    parent_pattern = re.compile(
        rf"^sub{re.escape(class_prefix)}(.+?)(\d{{1,2}})\|",
        re.IGNORECASE,
    )
    node_names: dict[str, dict[int, str]] = {}
    for line in subtalent_text.splitlines():
        stripped = line.strip()
        match = parent_pattern.match(stripped)
        if not match:
            continue
        node_id = int(match.group(2))
        if not 1 <= node_id <= 14:
            continue
        parts = stripped.split("|")
        english_name = parts[1].strip() if len(parts) > 1 else ""
        parent_key = canonical_subtalent_parent(class_prefix, match.group(1))
        node_names.setdefault(parent_key, {})[node_id] = english_name
    if not node_names:
        raise ValueError(f"No subskill definitions were found for {class_prefix}.")

    if class_id_from_translation_prefix(class_prefix) != class_id:
        raise ValueError(f"Class ID {class_id} does not match {class_prefix}.")
    talent_keys = verified_class_talent_keys(class_id, talent_text)
    talent_names = talent_names_from_translations(talent_text)

    class_block_start = 2 + (class_id - 1) * 18
    definitions: list[SubtalentTreeDefinition] = []
    for offset, skill_key in enumerate(talent_keys):
        names = node_names.get(canonical_skill_key(skill_key))
        if names is None:
            continue
        definitions.append(
            SubtalentTreeDefinition(
                talent_id=class_block_start + offset,
                skill_name=talent_names[skill_key.casefold()],
                node_names=tuple(names.get(node_id) or f"Node s{node_id}" for node_id in range(1, 15)),
            )
        )
    return tuple(definitions)


def resolve_allocated_subtalent_definitions(
    text: str,
    loadout_index: int,
    translation_pair: tuple[Path, Path] | None = None,
) -> tuple[SubtalentTreeDefinition, ...]:
    """Resolve allocated active skills and their current localized node names."""
    class_raw = get_ini_value(text, "0", "class")
    try:
        class_id = int(parse_number(class_raw))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid character class value: {class_raw!r}.") from exc
    class_prefix = CLASS_ID_TO_TRANSLATION_PREFIX.get(class_id)
    if not class_prefix:
        raise ValueError(f"Unsupported character class ID: {class_id}.")
    pair = game_translation_file_pair() if translation_pair is None else translation_pair
    if pair is None:
        raise ValueError("The current game's talent translation files could not be located.")
    allocated = allocated_talent_ids(text, loadout_index)
    definitions = subtalent_tree_definitions_from_translations(
        class_prefix,
        class_id,
        _read_translation_text(pair[0]),
        _read_translation_text(pair[1]),
    )
    return tuple(definition for definition in definitions if definition.talent_id in allocated)


def resolve_allocated_subtalent_ids(
    text: str,
    loadout_index: int,
    translation_pair: tuple[Path, Path] | None = None,
) -> set[int]:
    """Resolve allocated active skills without treating passive talents as trees."""
    class_raw = get_ini_value(text, "0", "class")
    try:
        class_id = int(parse_number(class_raw))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid character class value: {class_raw!r}.") from exc
    class_prefix = CLASS_ID_TO_TRANSLATION_PREFIX.get(class_id)
    if not class_prefix:
        raise ValueError(f"Unsupported character class ID: {class_id}.")

    pair = game_translation_file_pair() if translation_pair is None else translation_pair
    if pair is None:
        raise ValueError("The current game's talent translation files could not be located.")
    talent_path, subtalent_path = pair
    class_block_start = 2 + (class_id - 1) * 18
    allocated = allocated_talent_ids(text, loadout_index)
    offsets = active_subtalent_offsets_from_translations(
        class_prefix,
        _read_translation_text(talent_path),
        _read_translation_text(subtalent_path),
    )

    # Season 10 reserves talent IDs 0 and 1, then stores exactly 18 IDs per
    # class in class-ID order. The position map comes from the native EXE xref
    # table; translation files only determine localized names and active trees.
    active_ids = {class_block_start + offset for offset in offsets}
    return active_ids & allocated


def max_small_subtalent_nodes(
    text: str,
    loadout_index: int | None = None,
    create_talent_ids: set[int] | None = None,
) -> tuple[str, int, int]:
    """Distribute 50 points as rank 5 in s1-s10 and preserve s11-s14.

    Missing trees are created only for caller-provided, verified active talent
    IDs. Passive talents never receive fabricated sub-skill data.
    """
    index = active_talent_loadout_index(text) if loadout_index is None else loadout_index
    trees = decode_subtalent_map(text, index)
    for talent_id in sorted(create_talent_ids or set()):
        if talent_id < 0:
            raise ValueError(f"Invalid active talent ID: {talent_id}.")
        trees.setdefault(f"t{talent_id}", {})
    changed_nodes = 0
    for nodes in trees.values():
        for node_id in S10_SMALL_SUBTALENT_NODE_IDS:
            key = f"s{node_id}"
            current = nodes.get(key)
            if current is not None:
                try:
                    current_rank = float(current)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(f"Invalid small sub-skill rank {key}={current!r}.") from exc
                if current_rank == S10_SMALL_SUBTALENT_BALANCED_RANK:
                    continue
            nodes[key] = S10_SMALL_SUBTALENT_BALANCED_RANK
            changed_nodes += 1

    if not trees:
        return text, 0, 0
    encoded = encode_base64_json(trees)
    text = set_ini_value(text, f"talent_loadout_{index}", "subtalents", encoded, "text")
    return text, len(trees), changed_nodes


def apply_subtalent_allocations(
    text: str,
    allocations: dict[int, tuple[tuple[int, ...], int | None]],
    loadout_index: int | None = None,
    verified_talent_ids: set[int] | None = None,
) -> tuple[str, int, int]:
    """Write up to 50 distributed small-node points and one optional 3/3 major."""
    index = active_talent_loadout_index(text) if loadout_index is None else loadout_index
    trees = decode_subtalent_map(text, index)
    changed_nodes = 0
    for talent_id, (small_ranks, major_node_id) in allocations.items():
        if verified_talent_ids is not None and talent_id not in verified_talent_ids:
            raise ValueError(f"Talent t{talent_id} is not a verified allocated active skill.")
        if len(small_ranks) != len(S10_SMALL_SUBTALENT_NODE_IDS):
            raise ValueError(f"Talent t{talent_id} must provide exactly ten small-node ranks.")
        nodes = trees.get(f"t{talent_id}", {})
        if any(
            not isinstance(rank, int) or not 0 <= rank <= S10_SUBTALENT_POINT_BUDGET
            for rank in small_ranks
        ):
            raise ValueError(f"Talent t{talent_id} has an invalid small-node rank.")
        if sum(small_ranks) > S10_SUBTALENT_POINT_BUDGET:
            raise ValueError(f"Talent t{talent_id} exceeds the 50-point small-node budget.")
        if major_node_id is not None and major_node_id not in S10_MAJOR_SUBTALENT_NODE_IDS:
            raise ValueError(f"Talent t{talent_id} has an invalid major node s{major_node_id}.")

        nodes = trees.setdefault(f"t{talent_id}", {})
        for node_id, rank in zip(S10_SMALL_SUBTALENT_NODE_IDS, small_ranks):
            key = f"s{node_id}"
            previous = nodes.get(key)
            if rank == 0:
                if key in nodes:
                    nodes.pop(key)
                    changed_nodes += 1
            elif previous is None or float(previous) != float(rank):
                nodes[key] = float(rank)
                changed_nodes += 1

        for node_id in S10_MAJOR_SUBTALENT_NODE_IDS:
            key = f"s{node_id}"
            if node_id == major_node_id:
                previous = nodes.get(key)
                if previous is None or float(previous) != 3.0:
                    nodes[key] = 3.0
                    changed_nodes += 1
            elif key in nodes:
                nodes.pop(key)
                changed_nodes += 1

    if not allocations:
        return text, 0, 0
    encoded = encode_base64_json(trees)
    text = set_ini_value(text, f"talent_loadout_{index}", "subtalents", encoded, "text")
    return text, len(allocations), changed_nodes


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


def campaign_marker(text: str, key: str, default: int = 0) -> int:
    """Read a numeric campaign marker without allowing malformed save values."""
    raw = get_ini_value(text, "0", key)
    if raw == "":
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid campaign marker {key}={raw!r}.") from exc


def set_campaign_marker_at_least(text: str, key: str, target: int) -> str:
    """Raise a campaign marker while preserving higher legitimate progress."""
    value = max(campaign_marker(text, key), target)
    return set_ini_value(text, "0", key, str(value), "number")


def selected_difficulty_waypoint_marker(text: str) -> int:
    """Convert the zero-based selected difficulty to its one-based waypoint tier."""
    difficulty = campaign_marker(text, "difficulty")
    if not 0 <= difficulty < S10_MAX_CAMPAIGN_CLEAR:
        raise ValueError(f"Unsupported selected difficulty value: {difficulty}.")
    return difficulty + 1


def unlock_all_waypoints(text: str) -> str:
    """Unlock S10 waypoints only for the currently selected difficulty.

    ``act_9`` is deliberately excluded: Hero Siege uses it as the campaign-clear
    gate for unlocking difficulties. Act 9 itself is reachable through Act 8
    progress and its own zone markers.
    """
    target = selected_difficulty_waypoint_marker(text)
    for act in range(1, S10_ACT_COUNT + 1):
        if act < S10_ACT_COUNT:
            text = set_campaign_marker_at_least(text, f"act_{act}", target)
        for zone in range(S10_ZONE_SLOTS_PER_ACT):
            text = set_campaign_marker_at_least(text, f"zone{act},{zone}", target)
    return text


def unlock_all_difficulties(text: str) -> str:
    """Unlock all four S10 difficulties without changing the selected one.

    Season 10 gates difficulty selection on the Act 9 campaign-clear value.
    Waypoint/zone markers, the selected difficulty, legacy Hell 1-5 fields and
    hard-coded quest slots are intentionally left untouched.
    """
    return set_campaign_marker_at_least(text, "act_9", S10_MAX_CAMPAIGN_CLEAR)


def unlock_inferno_difficulty(text: str) -> str:
    """Backward-compatible alias for integrations using the old function name."""
    return unlock_all_difficulties(text)


def quest_chain_entries(text: str) -> dict[int, tuple[str, int]]:
    """Return questlog chain slots as {index: (chain_name, progress)}."""
    body = dict(iter_ini_sections(text)).get(QUESTLOG_SECTION, "")
    entries: dict[int, tuple[str, int]] = {}
    pattern = r'(?m)^\s*questlog_chain(\d+)\s*=\s*"?([^"\r\n]*)"?\s*$'
    for match in re.finditer(pattern, body):
        index = int(match.group(1))
        value = match.group(2).strip()
        name, separator, progress_raw = value.partition("|")
        if not name:
            continue
        try:
            progress = int(float(progress_raw)) if separator else 0
        except ValueError:
            progress = 0
        entries[index] = (name, progress)
    return entries


def set_quest_chain_progress(
    text: str,
    chain_name: str,
    progress: int,
    *,
    difficulty: int,
    sub_difficulty: int = 0,
    preserve_higher: bool = True,
) -> str:
    """Upsert a quest chain without overwriting unrelated questlog slots."""
    entries = quest_chain_entries(text)
    matching_indexes = [index for index, entry in entries.items() if entry[0] == chain_name]
    if matching_indexes:
        target_indexes = matching_indexes
    else:
        used_indexes = set(entries)
        index = 0
        while index in used_indexes:
            index += 1
        target_indexes = [index]

    for index in target_indexes:
        existing_progress = entries.get(index, (chain_name, 0))[1]
        final_progress = max(existing_progress, progress) if preserve_higher else progress
        text = set_ini_value(
            text,
            QUESTLOG_SECTION,
            f"questlog_chain{index}",
            f"{chain_name}|{final_progress}",
            "text",
        )
        text = set_ini_value(
            text,
            QUESTLOG_SECTION,
            f"questlog_diff{index}",
            str(difficulty),
            "number",
        )
        text = set_ini_value(
            text,
            QUESTLOG_SECTION,
            f"questlog_sub_diff{index}",
            str(sub_difficulty),
            "number",
        )
    return text


def unlock_charm_slots(text: str) -> str:
    """Complete S10's Light of Dawn reward and stage the native 30-cell grid."""
    text = set_quest_chain_progress(
        text,
        CHARM_SLOT_QUEST_CHAIN,
        CHARM_SLOT_QUEST_PROGRESS,
        difficulty=CHARM_SLOT_QUEST_DIFFICULTY,
    )
    return remove_ini_key(
        text,
        LEGACY_CHARM_SLOT_SAVE_SECTION,
        LEGACY_CHARM_SLOT_SAVE_KEY,
    )


def unlock_all_ether_points(text: str) -> str:
    """Complete all 25 native S10 Ether reward quests."""
    for chain_name, final_progress, difficulty in S10_ETHER_QUEST_CHAINS:
        text = set_quest_chain_progress(
            text,
            chain_name,
            final_progress,
            difficulty=difficulty,
        )
    return text


def ether_earned_points(text: str) -> int:
    """Reproduce S10's StatEtherPoints calculation from quest-chain stages."""
    progress_by_chain: dict[str, int] = {}
    for chain_name, progress in quest_chain_entries(text).values():
        if chain_name in S10_ETHER_POINT_WEIGHTS:
            progress_by_chain[chain_name] = max(progress_by_chain.get(chain_name, 0), progress)
    total = sum(
        progress_by_chain.get(chain_name, 0) * weight / 2
        for chain_name, weight in S10_ETHER_POINT_WEIGHTS.items()
    )
    if not float(total).is_integer():
        raise ValueError("Ether quest progress produced a fractional point total.")
    return int(total)


def grant_available_ether_points(text: str, target_available: int, allocated_nodes: int = 0) -> str:
    """Set the earned total so the active loadout has target_available points."""
    if target_available < 0 or allocated_nodes < 0:
        raise ValueError("Ether point values cannot be negative.")
    return set_total_ether_points(text, target_available + allocated_nodes)


def set_total_ether_points(text: str, target_earned: int) -> str:
    """Set the native quest-derived Ether total to an exact earned value."""
    if target_earned < 0:
        raise ValueError("Ether point values cannot be negative.")
    other_points = 0
    wormhole_difficulty = 3
    for chain_name, final_progress, difficulty in S10_ETHER_QUEST_CHAINS:
        if chain_name == "etheringWormhole":
            wormhole_difficulty = difficulty
            continue
        text = set_quest_chain_progress(
            text,
            chain_name,
            final_progress,
            difficulty=difficulty,
            preserve_higher=False,
        )
        other_points += final_progress * S10_ETHER_POINT_WEIGHTS[chain_name] // 2
    wormhole_points = target_earned - other_points
    if wormhole_points < 0:
        raise ValueError("Requested Ether target is below the points granted by the other native quest chains.")
    return set_quest_chain_progress(
        text,
        "etheringWormhole",
        wormhole_points * 2,
        difficulty=wormhole_difficulty,
        preserve_higher=False,
    )


class HssEditorApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1180x900")
        self.root.minsize(980, 700)
        self.save_dir = DEFAULT_SAVE_DIR if DEFAULT_SAVE_DIR.exists() else Path.cwd()
        self.loaded: LoadedSave | None = None
        self.raw_buffer = ""
        self.raw_window: Toplevel | None = None
        self.raw_text: ScrolledText | None = None
        self.inventory_window: Toplevel | None = None
        # Kept internally for sidecar diagnostics; the release UI grants
        # points through native quest progress instead of exposing node IDs.
        self.ether_window: Toplevel | None = None
        self.ether_path: Path | None = None
        self.ether_data: dict[str, object] | None = None
        self.ether_loadout_list: Listbox | None = None
        self.file_list_paths: dict[str, Path] = {}
        self.field_vars: dict[FieldSpec, StringVar] = {}
        self.field_widgets: dict[FieldSpec, object] = {}
        self._character_field_vars_dirty = False
        self._suppress_field_trace = False
        self.translation_pair: tuple[Path, Path] | None = None

        self.status = StringVar(value="Ready")
        self.current_file = StringVar(value="No character save loaded")
        self.slot_summary = StringVar(value="SCANNING LOCAL VAULT...")
        self.raw_search_var = StringVar(value="")
        self.raw_search_status = StringVar(value="")
        self.ether_file_status = StringVar(value="")
        self.ether_nodes_var = StringVar(value="")

        self._build_layout()
        self.refresh_file_list()

    def locate_translation_pair(self, prompt: bool = False) -> tuple[Path, Path] | None:
        if self.translation_pair is not None and all(path.is_file() for path in self.translation_pair):
            return self.translation_pair
        pair = game_translation_file_pair()
        if pair is not None:
            self.translation_pair = pair
            return pair
        if not prompt:
            return None
        selected = filedialog.askdirectory(
            title="Select the Hero Siege installation folder",
            parent=self.root,
        )
        if not selected:
            return None
        selected_root = Path(selected)
        for root in (selected_root, selected_root / "bin"):
            talent_path = root / "translationsTalent.csv"
            subtalent_path = root / "translationsSubTalent.csv"
            if talent_path.is_file() and subtalent_path.is_file():
                self.translation_pair = (talent_path.resolve(), subtalent_path.resolve())
                return self.translation_pair
        messagebox.showerror(
            APP_TITLE,
            "That folder does not contain the current Hero Siege talent files.\n\n"
            "Select the HeroSiege folder or its bin folder.",
            parent=self.root,
        )
        return None

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
        button = Button(
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
            pady=9,
            cursor="hand2",
            font=("Segoe UI Semibold", 10),
            highlightthickness=1,
            highlightbackground=bg,
            highlightcolor=active_bg,
            takefocus=True,
        )
        button.bind("<Enter>", lambda _event, widget=button, color=active_bg: widget.configure(bg=color))
        button.bind("<Leave>", lambda _event, widget=button, color=bg: widget.configure(bg=color))
        return button

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
            font=("Segoe UI", 10),
        )

    def _draw_forge_header(self, event=None) -> None:
        canvas = self.header_canvas
        width = max(1, event.width if event is not None else canvas.winfo_width())
        height = max(1, event.height if event is not None else canvas.winfo_height())
        canvas.delete("forge_header")

        top_rgb = (14, 8, 17)
        bottom_rgb = (37, 14, 29)
        for y in range(0, height, 3):
            ratio = y / max(1, height - 1)
            rgb = tuple(round(start + (end - start) * ratio) for start, end in zip(top_rgb, bottom_rgb))
            color = "#" + "".join(f"{channel:02x}" for channel in rgb)
            canvas.create_rectangle(0, y, width, min(height, y + 3), fill=color, outline="", tags="forge_header")

        canvas.create_polygon(
            0,
            0,
            min(width, 360),
            0,
            min(width, 250),
            height,
            0,
            height,
            fill="#160d1b",
            outline="",
            tags="forge_header",
        )
        canvas.create_line(0, height - 3, width, height - 3, fill="#6e4517", width=1, tags="forge_header")
        canvas.create_line(0, height - 1, width, height - 1, fill=UI_ACCENT, width=1, tags="forge_header")

        if width >= 720:
            for index in range(6):
                center_x = width - 38 - index * 46
                center_y = height // 2
                size = 13 + (index % 2) * 3
                canvas.create_polygon(
                    center_x,
                    center_y - size,
                    center_x + size,
                    center_y,
                    center_x,
                    center_y + size,
                    center_x - size,
                    center_y,
                    fill="",
                    outline="#5c304c",
                    width=1,
                    tags="forge_header",
                )
                canvas.create_line(
                    center_x - size + 4,
                    center_y,
                    center_x + size - 4,
                    center_y,
                    fill="#6c3b57",
                    tags="forge_header",
                )

        canvas.create_text(
            24,
            12,
            anchor="nw",
            text="HERO SIEGE",
            fill=UI_GOLD_BRIGHT,
            font=("Segoe UI Semibold", 9),
            tags="forge_header",
        )
        canvas.create_text(
            22,
            29,
            anchor="nw",
            text="CHARACTER SAVE FORGE",
            fill=UI_TEXT,
            font=("Segoe UI Semibold", 20),
            tags="forge_header",
        )
        canvas.create_text(
            width - 22,
            18,
            anchor="ne",
            text="OFFLINE  •  SEASON 10",
            fill=UI_MUTED,
            font=("Segoe UI Semibold", 9),
            tags="forge_header",
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
        style.configure(
            "Forge.Vertical.TScrollbar",
            background=UI_CARD,
            troughcolor=UI_FIELD,
            bordercolor=UI_BORDER,
            arrowcolor=UI_MUTED,
            darkcolor=UI_CARD,
            lightcolor=UI_CARD,
        )
        style.map("Forge.Vertical.TScrollbar", background=[("active", UI_BORDER), ("pressed", UI_ACCENT_DARK)])

        self.header_canvas = Canvas(self.root, height=78, bg=UI_PANEL, bd=0, highlightthickness=0)
        self.header_canvas.pack(fill=X)
        self.header_canvas.bind("<Configure>", self._draw_forge_header)

        main = PanedWindow(
            self.root,
            orient="horizontal",
            sashrelief="flat",
            sashwidth=2,
            bg="#2b1e2c",
            bd=0,
        )
        main.pack(fill=BOTH, expand=True)

        sidebar = Frame(main, padx=14, pady=14, bg=UI_PANEL)
        main.add(sidebar, width=300, minsize=270)

        Label(
            sidebar,
            text="CHARACTER VAULT",
            bg=UI_PANEL,
            fg=UI_GOLD_BRIGHT,
            font=("Segoe UI Semibold", 14),
        ).pack(anchor="w")
        Label(
            sidebar,
            text="LOCAL OFFLINE SAVE SLOTS",
            bg=UI_PANEL,
            fg=UI_MUTED,
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(0, 10))

        folder_card = Frame(
            sidebar,
            bg=UI_CARD_2,
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
        )
        folder_card.pack(fill=X, pady=(0, 8))
        Label(
            folder_card,
            text="SAVE DIRECTORY",
            bg=UI_CARD_2,
            fg=UI_NOTICE,
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        self.folder_label = Label(
            folder_card,
            text=str(self.save_dir),
            wraplength=245,
            justify="left",
            fg=UI_MUTED,
            bg=UI_CARD_2,
        )
        self.folder_label.pack(anchor="w", fill=X, pady=(2, 0))

        folder_actions = Frame(sidebar, bg=UI_PANEL)
        folder_actions.pack(fill=X, pady=(0, 10))
        folder_actions.columnconfigure(0, weight=1, uniform="folder_action")
        folder_actions.columnconfigure(1, weight=1, uniform="folder_action")
        self.make_button(folder_actions, "Change Folder", self.choose_save_folder).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        self.make_button(folder_actions, "Refresh", self.refresh_file_list).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        Label(
            sidebar,
            textvariable=self.slot_summary,
            bg=UI_PANEL,
            fg=UI_NOTICE,
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(0, 5))

        list_frame = Frame(
            sidebar,
            bg=UI_FIELD,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
        )
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
            font=("Cascadia Mono", 9),
        )
        self.file_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=VERTICAL,
            command=self.file_list.yview,
            style="Forge.Vertical.TScrollbar",
        )
        scrollbar.pack(side=RIGHT, fill=Y)
        self.file_list.config(yscrollcommand=scrollbar.set)
        self.file_list.bind("<Double-Button-1>", lambda _event: self.open_selected_file())

        self.make_button(sidebar, "OPEN SELECTED CHARACTER", self.open_selected_file, accent=True).pack(
            fill=X, pady=(10, 0)
        )
        self.make_button(sidebar, "Open File...", self.open_file_dialog).pack(fill=X, pady=(8, 0))

        content_host = Frame(main, bg=UI_BG)
        main.add(content_host, minsize=650)
        content_host.rowconfigure(0, weight=1)
        content_host.columnconfigure(0, weight=1)

        content_canvas = Canvas(
            content_host,
            bg=UI_BG,
            bd=0,
            highlightthickness=0,
            yscrollincrement=24,
        )
        content_canvas.grid(row=0, column=0, sticky="nsew")
        content_scrollbar = ttk.Scrollbar(
            content_host,
            orient=VERTICAL,
            command=content_canvas.yview,
            style="Forge.Vertical.TScrollbar",
        )
        content_scrollbar.grid(row=0, column=1, sticky="ns")
        content_canvas.configure(yscrollcommand=content_scrollbar.set)

        content = Frame(content_canvas, padx=20, pady=14, bg=UI_BG)
        content_window = content_canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: content_canvas.configure(scrollregion=content_canvas.bbox("all")),
            add="+",
        )
        content_canvas.bind(
            "<Configure>",
            lambda event: content_canvas.itemconfigure(content_window, width=event.width),
            add="+",
        )

        def scroll_content(event) -> None:
            hovered = self.root.winfo_containing(event.x_root, event.y_root)
            if hovered is None or not str(hovered).startswith(str(content_canvas)):
                return
            delta = -1 if event.delta > 0 else 1
            content_canvas.yview_scroll(delta * 3, "units")

        self.root.bind_all("<MouseWheel>", scroll_content, add="+")

        Label(
            content,
            text="ACTIVE CHARACTER SAVE",
            anchor="w",
            font=("Segoe UI Semibold", 8),
            bg=UI_BG,
            fg=UI_NOTICE,
        ).pack(fill=X)
        current_file_label = Label(
            content,
            textvariable=self.current_file,
            anchor="w",
            justify="left",
            font=("Segoe UI Semibold", 13),
            bg=UI_BG,
            fg=UI_TEXT,
        )
        current_file_label.pack(fill=X, pady=(2, 5))

        help_text = "Open a character, make your changes, then save. A backup is created automatically."
        Label(content, text=help_text, wraplength=720, justify="left", fg=UI_MUTED, bg=UI_BG).pack(
            anchor="w", pady=(0, 9)
        )

        notice_frame = Frame(
            content,
            bg=UI_CARD_2,
            padx=12,
            pady=8,
            highlightthickness=1,
            highlightbackground=UI_NOTICE,
        )
        notice_frame.pack(fill=X, anchor="n", pady=(0, 10))
        Label(
            notice_frame,
            text="OFFLINE SAFETY NOTICE",
            bg=UI_CARD_2,
            fg=UI_NOTICE,
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w")
        notice_text = (
            "Use this editor only with offline characters. Do not use edited characters online."
        )
        notice_label = Label(
            notice_frame,
            text=notice_text,
            wraplength=720,
            justify="left",
            bg=UI_CARD_2,
            fg=UI_TEXT,
        )
        notice_label.pack(fill=X, anchor="w", pady=(3, 0))

        grid = LabelFrame(
            content,
            text="  CHARACTER ATTRIBUTES  ",
            padx=14,
            pady=10,
            bg=UI_CARD,
            fg=UI_GOLD_BRIGHT,
            font=("Segoe UI Semibold", 9),
            bd=1,
            relief="solid",
        )
        grid.pack(fill=X, anchor="n")

        for index, spec in enumerate(CHARACTER_FIELDS):
            row = index // 2
            column = (index % 2) * 2
            Label(grid, text=spec.label, bg=UI_CARD, fg=UI_MUTED).grid(
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

        professions = LabelFrame(
            content,
            text="  PROFESSIONS  ",
            padx=14,
            pady=8,
            bg=UI_CARD,
            fg=UI_GOLD_BRIGHT,
            font=("Segoe UI Semibold", 9),
            bd=1,
            relief="solid",
        )
        professions.pack(fill=X, anchor="n", pady=(8, 0))

        for index, spec in enumerate(PROFESSION_FIELDS):
            row = index // 2
            column = (index % 2) * 2
            Label(professions, text=spec.label, bg=UI_CARD, fg=UI_MUTED).grid(
                row=row, column=column, sticky="w", padx=(0, 10), pady=5
            )
            var = StringVar()
            widget = self.make_entry(professions, var, width=18)
            widget.grid(
                row=row, column=column + 1, sticky="we", padx=(0, 22), pady=5
            )
            self.field_vars[spec] = var
            self.field_widgets[spec] = widget

        for column in range(4):
            professions.columnconfigure(column, weight=1 if column % 2 else 0)

        for var in self.field_vars.values():
            var.trace_add("write", self._mark_character_fields_dirty)

        actions = LabelFrame(
            content,
            text="  SAVE  ",
            padx=8,
            pady=8,
            bg=UI_BG,
            fg=UI_GOLD_BRIGHT,
            font=("Segoe UI Semibold", 9),
            bd=0,
        )
        actions.pack(fill=X, pady=(8, 4))
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="save_action")
        self.make_button(actions, "Undo Unsaved Changes", self.reload_current).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        self.make_button(actions, "SAVE CHARACTER", self.save_current, accent=True).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self.make_button(actions, "Save As...", self.save_as).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

        unlock_actions = LabelFrame(
            content,
            text="  CHARACTER TOOLS  ",
            padx=8,
            pady=8,
            bg=UI_BG,
            fg=UI_GOLD_BRIGHT,
            font=("Segoe UI Semibold", 9),
            bd=0,
        )
        unlock_actions.pack(fill=X, pady=(0, 7))
        for column in range(2):
            unlock_actions.columnconfigure(column, weight=1, uniform="unlock_action")

        self.make_button(
            unlock_actions,
            "Unlock Waypoints",
            self.apply_unlock_all_waypoints,
            bg=UI_WAYPOINT,
            active_bg=UI_WAYPOINT_DARK,
            fg="#eff6ff",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 5))
        self.make_button(
            unlock_actions,
            "Unlock All Difficulties",
            self.apply_unlock_all_difficulties,
            danger=True,
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=(0, 5))
        self.make_button(
            unlock_actions,
            "Unlock All Charm Slots",
            self.apply_unlock_charm_slots,
            bg=UI_PURPLE,
            active_bg=UI_PURPLE_DARK,
            fg="#f5f3ff",
        ).grid(row=1, column=0, sticky="ew", padx=(0, 5), pady=(5, 0))
        self.make_button(
            unlock_actions,
            "Give 800 Ether Points",
            self.apply_unlock_all_ether_points,
            bg=UI_ETHER,
            active_bg=UI_ETHER_DARK,
            fg="#ecfeff",
        ).grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))
        self.make_button(
            unlock_actions,
            "Edit Subskills",
            self.open_subtalent_editor,
            bg=UI_SUBTALENT,
            active_bg=UI_SUBTALENT_DARK,
            fg="#ecfdf5",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.make_button(
            unlock_actions,
            "Convert to Odyssey",
            self.apply_convert_to_odyssey,
            bg=UI_PURPLE,
            active_bg=UI_PURPLE_DARK,
            fg="#f5f3ff",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        status_frame = Frame(
            content,
            bg=UI_CARD_2,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
        )
        status_frame.pack(fill=X, pady=(4, 0))
        Frame(status_frame, width=4, bg=UI_ACCENT).pack(side=LEFT, fill=Y)
        status_body = Frame(status_frame, bg=UI_CARD_2, padx=10, pady=7)
        status_body.pack(side=LEFT, fill=X, expand=True)
        Label(
            status_body,
            text="FORGE STATUS",
            anchor="w",
            fg=UI_NOTICE,
            bg=UI_CARD_2,
            font=("Segoe UI Semibold", 8),
        ).pack(fill=X)
        status_label = Label(
            status_body,
            textvariable=self.status,
            anchor="w",
            justify="left",
            fg=UI_MUTED,
            bg=UI_CARD_2,
        )
        status_label.pack(fill=X, pady=(2, 0))

        def resize_content_labels(event) -> None:
            wrap = max(320, event.width - 64)
            current_file_label.configure(wraplength=wrap)
            notice_label.configure(wraplength=wrap)
            status_label.configure(wraplength=wrap)

        content.bind("<Configure>", resize_content_labels, add="+")

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
            self.slot_summary.set("SAVE DIRECTORY NOT FOUND")
            self.set_status("Save folder not found. Choose the correct Hero Siege save folder.")
            return

        display_paths: list[tuple[str, Path]] = []
        for path in sorted(self.save_dir.glob("herosiege*.hss"), key=lambda p: p.name.lower()):
            display_paths.append((path.name, path))
        sub = self.save_dir / "hs2saves"
        if sub.is_dir():
            for path in sorted(sub.glob("herosiege*.hss"), key=lambda p: p.name.lower()):
                display_paths.append((str(Path("hs2saves") / path.name), path))
        populated_count = 0
        for display, _path in sorted(display_paths, key=lambda item: save_slot_sort_key(item[0])):
            label = save_list_label(display, _path)
            if "   Unnamed" not in label:
                populated_count += 1
            if label in self.file_list_paths:
                label = f"{label}   ({display})"
            self.file_list_paths[label] = _path.resolve()
            self.file_list.insert(END, label)
        self.slot_summary.set(f"{populated_count} CHARACTERS  •  {len(display_paths)} SLOT FILES")
        self.set_status(f"Found {populated_count} character(s).")

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
            messagebox.showinfo(APP_TITLE, "Select a character first.")
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
                    f"{path.name} is not a usable character save.\n\n"
                    "It may be an empty slot or the wrong save folder."
                    f"\n\nDetails: {exc}",
                )
            else:
                messagebox.showerror(APP_TITLE, f"Could not open {path.name}:\n{exc}")
            return

        file_kind = classify_text(text, path)
        if file_kind != "character_ini":
            messagebox.showwarning(
                APP_TITLE,
                f"{path.name} is not an offline character save.",
            )
            return

        shop_path, shop_text = read_shop_ini_near_character(path)
        self.loaded = LoadedSave(path=path, text=text, file_kind=file_kind, shop_path=shop_path, shop_text=shop_text)
        self.current_file.set(str(path))
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False)
        self.set_status(f"Opened {get_ini_value(text, '0', 'name') or path.name}. Ready to edit.")

    def reload_current(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
        self.set_status("Waypoints are ready. Click Save Character to finish.")

    def apply_unlock_all_difficulties(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            text = unlock_all_difficulties(text)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not unlock all difficulties:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status("All difficulties are ready. Click Save Character to finish.")

    def apply_unlock_inferno_difficulty(self) -> None:
        """Compatibility wrapper retained for older UI integrations."""
        self.apply_unlock_all_difficulties()

    def apply_convert_to_odyssey(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            already_odyssey = is_odyssey_character(text)
            character_name = get_ini_value(text, "0", "name") or self.loaded.path.name
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not read the Odyssey state:\n{exc}")
            return
        if already_odyssey:
            messagebox.showinfo(APP_TITLE, f"{character_name} is already an Odyssey character.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Convert {character_name} to Odyssey?\n\n"
            "Your character and items will stay the same.\n\n"
            "You still need to click Save Character.",
            parent=self.root,
        ):
            return
        try:
            text = convert_character_to_odyssey(text)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not convert the character to Odyssey:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status(f"{character_name} is ready for Odyssey. Click Save Character to finish.")

    def apply_unlock_charm_slots(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            text = unlock_charm_slots(text)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not unlock all charm slots:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status("All 30 charm slots are ready. Click Save Character to finish.")

    def apply_unlock_all_ether_points(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
            return
        try:
            ether_path = ether_path_for_character(self.loaded.path)
            ether_data = read_ether_file(ether_path)
            active_loadout = self.active_ether_loadout_index()
            allocated_nodes = len(ether_loadout_nodes(ether_data, active_loadout))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not read the Ether Tree:\n{exc}")
            return
        target_earned = S10_TARGET_TOTAL_ETHER_POINTS
        expected_available = max(0, target_earned - allocated_nodes)
        if not messagebox.askyesno(
            APP_TITLE,
            f"Give this character {target_earned} total Ether Points?\n\n"
            f"Points available after current upgrades: {expected_available}\n\n"
            "Your current Ether upgrades will stay the same. You still need to click Save Character.",
            parent=self.root,
        ):
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            text = set_total_ether_points(text, target_earned)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not unlock the Ether Points:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status(f"{target_earned} Ether Points are ready. Click Save Character to finish.")

    def apply_max_small_subtalents(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character .hss file first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            loadout_index = active_talent_loadout_index(text)
            trees = decode_subtalent_map(text, loadout_index)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not read the active subskill loadout:\n{exc}")
            return

        resolution_warning = ""
        try:
            translation_pair = self.locate_translation_pair(prompt=True)
            if translation_pair is None:
                raise ValueError(
                    "Hero Siege's talent files were not found. Select the game's folder when prompted."
                )
            resolved_ids = resolve_allocated_subtalent_ids(text, loadout_index, translation_pair)
        except Exception as exc:
            resolved_ids = set()
            resolution_warning = str(exc)

        existing_ids = {int(key[1:]) for key in trees}
        target_ids = existing_ids | resolved_ids
        missing_ids = resolved_ids - existing_ids
        if not target_ids:
            details = f"\n\nResolver: {resolution_warning}" if resolution_warning else ""
            messagebox.showinfo(
                APP_TITLE,
                f"Talent loadout {loadout_index + 1} has no allocated active subskill trees."
                f"{details}",
            )
            return

        resolver_note = ""
        if resolution_warning:
            resolver_note = (
                f"\n\nAdaptive resolver warning: {resolution_warning}\n"
                "Only trees already present in the save will be changed."
            )
        if not messagebox.askyesno(
            APP_TITLE,
            f"Max every small node (s1-s10) in {len(target_ids)} allocated active subskill tree(s) "
            f"on talent loadout {loadout_index + 1}?\n\n"
            f"Existing trees: {len(existing_ids)}\n"
            f"Verified missing trees to create: {len(missing_ids)}\n\n"
            "Large/special nodes s11-s14 will be preserved exactly and will not be unlocked or changed.\n\n"
            f"The change is not written until Save With Backup.{resolver_note}",
            parent=self.root,
        ):
            return

        try:
            text, tree_count, changed_nodes = max_small_subtalent_nodes(
                text,
                loadout_index,
                create_talent_ids=resolved_ids,
            )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not max the small subskill nodes:\n{exc}")
            return
        self.set_raw(text)
        self.populate_fields_from_raw(show_errors=False, update_status=False)
        self.set_status(
            f"Staged {changed_nodes} small-node rank changes across {tree_count} tree(s) in talent "
            f"loadout {loadout_index + 1}; created {len(missing_ids)} verified missing tree(s). "
            "Large nodes s11-s14 were preserved. "
            "Press Save With Backup to write the character save."
        )

    def open_subtalent_editor(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
            return
        try:
            text = self.get_raw()
            if self._character_field_vars_dirty:
                text = self.merge_character_field_vars_into_text(text)
            loadout_index = active_talent_loadout_index(text)
            trees = decode_subtalent_map(text, loadout_index)
            translation_pair = self.locate_translation_pair(prompt=True)
            if translation_pair is None:
                raise ValueError(
                    "Hero Siege's talent files were not found. Select the game's folder when prompted."
                )
            definitions = resolve_allocated_subtalent_definitions(text, loadout_index, translation_pair)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open the subskills:\n{exc}")
            return
        if not definitions:
            messagebox.showinfo(
                APP_TITLE,
                "This character has no active skills to edit.",
            )
            return

        working: dict[int, tuple[list[int], int | None]] = {}
        for definition in definitions:
            nodes = trees.get(f"t{definition.talent_id}", {})
            small_ranks: list[int] = []
            for node_id in S10_SMALL_SUBTALENT_NODE_IDS:
                try:
                    rank_value = float(nodes.get(f"s{node_id}", 0))
                except (TypeError, ValueError, OverflowError) as exc:
                    messagebox.showerror(APP_TITLE, f"{definition.skill_name} has invalid saved data.\n\n{exc}")
                    return
                if rank_value < 0 or not rank_value.is_integer():
                    messagebox.showerror(APP_TITLE, f"{definition.skill_name} has an invalid saved point value.")
                    return
                rank = int(rank_value)
                small_ranks.append(rank)
            selected_major = next(
                (
                    node_id
                    for node_id in S10_MAJOR_SUBTALENT_NODE_IDS
                    if float(nodes.get(f"s{node_id}", 0) or 0) > 0
                ),
                None,
            )
            working[definition.talent_id] = (small_ranks, selected_major)

        window = Toplevel(self.root)
        window.title("Edit Subskills")
        window.geometry("780x650")
        window.minsize(720, 600)
        window.configure(bg=UI_BG)
        window.transient(self.root)
        window.grab_set()

        wrapper = Frame(window, padx=18, pady=16, bg=UI_BG)
        wrapper.pack(fill=BOTH, expand=True)
        Label(
            wrapper,
            text="EDIT SUBSKILLS",
            anchor="w",
            fg=UI_GOLD_BRIGHT,
            bg=UI_BG,
            font=("Segoe UI Semibold", 16),
        ).pack(fill=X)
        Label(
            wrapper,
            text=(
                "Choose a skill, spend up to 50 points on its small upgrades, then choose one "
                "major upgrade. Click Apply Changes when you are done."
            ),
            anchor="w",
            justify="left",
            wraplength=730,
            fg=UI_MUTED,
            bg=UI_BG,
        ).pack(fill=X, pady=(4, 12))
        definition_by_label: dict[str, SubtalentTreeDefinition] = {}
        for definition in definitions:
            label = definition.skill_name
            option = 2
            while label in definition_by_label:
                label = f"{definition.skill_name} (Option {option})"
                option += 1
            definition_by_label[label] = definition
        skill_var = StringVar(value=next(iter(definition_by_label)))
        selector = ttk.Combobox(
            wrapper,
            textvariable=skill_var,
            values=tuple(definition_by_label),
            state="readonly",
            style="Modern.TCombobox",
        )
        selector.pack(fill=X, pady=(0, 12))

        node_frame = Frame(wrapper, bg=UI_CARD, padx=14, pady=12)
        node_frame.pack(fill=BOTH, expand=True)
        node_labels: list[Label] = []
        rank_combos: list[ttk.Combobox] = []
        rank_vars = [StringVar(value="0") for _ in S10_SMALL_SUBTALENT_NODE_IDS]
        for index, node_id in enumerate(S10_SMALL_SUBTALENT_NODE_IDS):
            column_group = 0 if index < 5 else 1
            row = index if index < 5 else index - 5
            base_column = column_group * 3
            label = Label(
                node_frame,
                text=f"s{node_id}",
                anchor="w",
                fg=UI_TEXT,
                bg=UI_CARD,
            )
            label.grid(row=row, column=base_column, sticky="w", padx=(0, 8), pady=5)
            node_labels.append(label)
            rank_combo = ttk.Combobox(
                node_frame,
                textvariable=rank_vars[index],
                values=tuple(str(rank) for rank in range(S10_SUBTALENT_POINT_BUDGET + 1)),
                width=4,
                state="readonly",
                style="Modern.TCombobox",
            )
            rank_combo.grid(row=row, column=base_column + 1, sticky="e", padx=(0, 28), pady=5)
            rank_combos.append(rank_combo)
        node_frame.columnconfigure(0, weight=1)
        node_frame.columnconfigure(3, weight=1)

        total_var = StringVar(value="Points used: 0 / 50")
        Label(
            node_frame,
            textvariable=total_var,
            anchor="w",
            fg=UI_NOTICE,
            bg=UI_CARD,
            font=("Segoe UI Semibold", 10),
        ).grid(row=5, column=0, columnspan=5, sticky="w", pady=(12, 6))

        no_major_label = "No major upgrade"
        major_var = StringVar(value=no_major_label)
        major_choice_ids: dict[str, int | None] = {no_major_label: None}
        Label(
            node_frame,
            text="Major upgrade (automatically maxed)",
            anchor="w",
            fg=UI_GOLD_BRIGHT,
            bg=UI_CARD,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 5))
        major_combo = ttk.Combobox(
            node_frame,
            textvariable=major_var,
            state="readonly",
            style="Modern.TCombobox",
        )
        major_combo.grid(row=7, column=0, columnspan=5, sticky="ew", pady=(0, 10))

        current_label = [skill_var.get()]

        def refresh_total(*_args: object) -> None:
            try:
                total = sum(int(variable.get()) for variable in rank_vars)
            except ValueError:
                total = 0
            total_var.set(f"Points used: {total} / 50")

        def store_current(show_error: bool = True) -> bool:
            definition = definition_by_label[current_label[0]]
            try:
                ranks = [int(variable.get()) for variable in rank_vars]
            except ValueError:
                if show_error:
                    messagebox.showerror(APP_TITLE, "Choose one of the listed values for every upgrade.", parent=window)
                return False
            if any(rank < 0 for rank in ranks):
                if show_error:
                    messagebox.showerror(APP_TITLE, "Upgrade points cannot be negative.", parent=window)
                return False
            total = sum(ranks)
            if total > S10_SUBTALENT_POINT_BUDGET:
                if show_error:
                    messagebox.showerror(APP_TITLE, f"{definition.skill_name} uses {total} points. The maximum is 50.", parent=window)
                return False
            major_node_id = major_choice_ids.get(major_var.get())
            working[definition.talent_id] = (ranks, major_node_id)
            return True

        def load_current() -> None:
            definition = definition_by_label[current_label[0]]
            ranks, major_node_id = working[definition.talent_id]
            for index, (label, variable, combo, rank) in enumerate(zip(node_labels, rank_vars, rank_combos, ranks)):
                label.configure(text=definition.node_names[index])
                values = [str(value) for value in range(S10_SUBTALENT_POINT_BUDGET + 1)]
                if rank > S10_SUBTALENT_POINT_BUDGET:
                    values.append(str(rank))
                combo.configure(values=tuple(values))
                variable.set(str(rank))
            major_choice_ids.clear()
            major_choice_ids[no_major_label] = None
            selected_major_label = no_major_label
            major_values = [no_major_label]
            for node_id in S10_MAJOR_SUBTALENT_NODE_IDS:
                choice_label = definition.node_names[node_id - 1]
                if choice_label in major_choice_ids:
                    choice_label = f"{choice_label} (Option {node_id - 10})"
                major_choice_ids[choice_label] = node_id
                major_values.append(choice_label)
                if node_id == major_node_id:
                    selected_major_label = choice_label
            major_combo.configure(values=major_values)
            major_var.set(selected_major_label)
            refresh_total()

        def change_skill(_event: object) -> None:
            new_label = skill_var.get()
            if new_label == current_label[0]:
                return
            if not store_current():
                skill_var.set(current_label[0])
                return
            current_label[0] = new_label
            load_current()

        def set_small_ranks(rank: int) -> None:
            for variable in rank_vars:
                variable.set(str(rank))
            refresh_total()

        def stage_allocations() -> None:
            if not store_current():
                return
            allocations = {
                talent_id: (tuple(ranks), major_node_id)
                for talent_id, (ranks, major_node_id) in working.items()
            }
            major_count = sum(major_node_id is not None for _, major_node_id in working.values())
            if not messagebox.askyesno(
                APP_TITLE,
                "Apply these subskill changes?\n\n"
                f"Major upgrades selected: {major_count}\n\n"
                "You still need to click Save Character in the main window.",
                parent=window,
            ):
                return
            try:
                updated, tree_count, changed_nodes = apply_subtalent_allocations(
                    text,
                    allocations,
                    loadout_index,
                    verified_talent_ids={definition.talent_id for definition in definitions},
                )
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"Could not apply the subskill changes:\n{exc}", parent=window)
                return
            self.set_raw(updated)
            self.populate_fields_from_raw(show_errors=False, update_status=False)
            self.set_status("Subskill changes are ready. Click Save Character to finish.")
            window.destroy()

        for variable in rank_vars:
            variable.trace_add("write", refresh_total)
        selector.bind("<<ComboboxSelected>>", change_skill)
        load_current()

        quick_actions = Frame(wrapper, bg=UI_BG)
        quick_actions.pack(fill=X, pady=(12, 6))
        self.make_button(
            quick_actions,
            "Fill 5 Each (50 Points)",
            lambda: set_small_ranks(5),
            bg=UI_CARD,
            active_bg=UI_BORDER,
            fg=UI_TEXT,
        ).pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        self.make_button(
            quick_actions,
            "Clear Small Upgrades",
            lambda: set_small_ranks(0),
            bg=UI_CARD,
            active_bg=UI_BORDER,
            fg=UI_TEXT,
        ).pack(side=LEFT, fill=X, expand=True, padx=(5, 0))
        self.make_button(
            wrapper,
            "Apply Changes",
            stage_allocations,
            bg=UI_SUBTALENT,
            active_bg=UI_SUBTALENT_DARK,
            fg="#ecfdf5",
        ).pack(fill=X, pady=(6, 0))

    def active_ether_loadout_index(self) -> int:
        if self.ether_loadout_list is not None and self.ether_loadout_list.winfo_exists():
            selection = self.ether_loadout_list.curselection()
            if selection:
                return int(selection[0])
        if self.loaded:
            try:
                index = int(parse_number(get_ini_value(self.get_raw(), "0", "ether_loadout") or "0"))
                if 0 <= index < ETHER_LOADOUT_COUNT:
                    return index
            except ValueError:
                pass
        return 0

    def open_ether_window(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
            return
        try:
            self.ether_path = ether_path_for_character(self.loaded.path)
            self.ether_data = read_ether_file(self.ether_path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open the Season 10 Ether save:\n{exc}")
            return

        if self.ether_window is not None and self.ether_window.winfo_exists():
            self.refresh_ether_window()
            self.ether_window.lift()
            return

        self.ether_window = Toplevel(self.root)
        self.ether_window.title("Season 10 Ether Tree")
        self.ether_window.geometry("760x470")
        self.ether_window.configure(bg=UI_BG)

        wrapper = Frame(self.ether_window, padx=16, pady=16, bg=UI_BG)
        wrapper.pack(fill=BOTH, expand=True)
        Label(wrapper, text="Season 10 Ether Tree", font=("Segoe UI", 16, "bold"), bg=UI_BG, fg=UI_TEXT).pack(
            anchor="w"
        )
        Label(wrapper, textvariable=self.ether_file_status, bg=UI_BG, fg=UI_MUTED).pack(anchor="w", pady=(2, 10))

        body = Frame(wrapper, bg=UI_BG)
        body.pack(fill=BOTH, expand=True)
        left = LabelFrame(body, text="Loadouts", padx=10, pady=10, bg=UI_CARD, fg=UI_TEXT, bd=1, relief="solid")
        left.pack(side=LEFT, fill=Y)
        self.ether_loadout_list = Listbox(
            left,
            width=34,
            height=12,
            exportselection=False,
            bg=UI_FIELD,
            fg=UI_TEXT,
            selectbackground=UI_ACCENT,
            selectforeground="#04111f",
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI_BORDER,
        )
        self.ether_loadout_list.pack(fill=Y, expand=True)
        self.ether_loadout_list.bind("<<ListboxSelect>>", lambda _event: self.show_selected_ether_nodes())

        right = LabelFrame(body, text="Selected Loadout", padx=14, pady=12, bg=UI_CARD, fg=UI_TEXT, bd=1, relief="solid")
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=(12, 0))
        Label(
            right,
            text="Allocated node IDs (comma or space separated). The S10 file preserves order and duplicate IDs.",
            bg=UI_CARD,
            fg=UI_MUTED,
            justify="left",
            wraplength=420,
        ).pack(anchor="w")
        self.make_entry(right, self.ether_nodes_var, width=56).pack(fill=X, pady=(10, 12))
        self.make_button(right, "Apply IDs To Selected Loadout", self.apply_ether_nodes_to_memory, accent=True).pack(
            anchor="w"
        )
        self.make_button(
            right,
            "Reset Selected Loadout",
            self.reset_selected_ether_loadout,
            danger=True,
        ).pack(anchor="w", pady=(10, 0))
        self.make_button(right, "Reset All 8 Loadouts", self.reset_all_ether_loadouts, danger=True).pack(
            anchor="w", pady=(8, 0)
        )
        Label(
            right,
            text="Resetting removes allocated node IDs from the Ether sidecar. Nothing is written until Save Ether With Backup.",
            bg=UI_CARD,
            fg=UI_NOTICE,
            justify="left",
            wraplength=420,
        ).pack(anchor="w", pady=(14, 0))

        actions = Frame(wrapper, bg=UI_BG)
        actions.pack(fill=X, pady=(12, 0))
        self.make_button(actions, "Reload Ether From Disk", self.reload_ether_from_disk).pack(side=LEFT)
        self.make_button(actions, "Save Ether With Backup", self.save_ether_changes, accent=True).pack(side=LEFT, padx=8)
        self.make_button(actions, "Close", self.close_ether_window).pack(side=LEFT)

        self.ether_window.protocol("WM_DELETE_WINDOW", self.close_ether_window)
        self.refresh_ether_window()

    def refresh_ether_window(self, selected_index: int | None = None) -> None:
        if self.ether_window is None or not self.ether_window.winfo_exists() or self.ether_data is None:
            return
        if selected_index is None:
            selected_index = self.active_ether_loadout_index()
        active_index = 0
        if self.loaded:
            try:
                active_index = int(parse_number(get_ini_value(self.get_raw(), "0", "ether_loadout") or "0"))
            except ValueError:
                active_index = 0
        if self.ether_path is not None:
            state = "found" if self.ether_path.exists() else "new sidecar"
            self.ether_file_status.set(f"{self.ether_path.name} — {state}")
        if self.ether_loadout_list is None:
            return
        self.ether_loadout_list.delete(0, END)
        for index in range(ETHER_LOADOUT_COUNT):
            nodes = ether_loadout_nodes(self.ether_data, index)
            active = "  [ACTIVE]" if index == active_index else ""
            self.ether_loadout_list.insert(END, f"Loadout {index + 1}: {len(nodes)} node entries{active}")
        selected_index = max(0, min(selected_index, ETHER_LOADOUT_COUNT - 1))
        self.ether_loadout_list.selection_set(selected_index)
        self.ether_loadout_list.activate(selected_index)
        self.show_selected_ether_nodes()

    def show_selected_ether_nodes(self) -> None:
        if self.ether_data is None:
            self.ether_nodes_var.set("")
            return
        index = self.active_ether_loadout_index()
        self.ether_nodes_var.set(", ".join(str(node) for node in ether_loadout_nodes(self.ether_data, index)))

    def apply_ether_nodes_to_memory(self, *, update_status: bool = True) -> bool:
        if self.ether_data is None:
            return False
        index = self.active_ether_loadout_index()
        try:
            nodes = parse_ether_node_ids(self.ether_nodes_var.get())
            self.ether_data = set_ether_loadout_nodes(self.ether_data, index, nodes)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not apply Ether node IDs:\n{exc}")
            return False
        self.refresh_ether_window(index)
        if update_status:
            self.set_status(f"Ether loadout {index + 1} staged with {len(nodes)} node entries; not saved yet.")
        return True

    def reset_selected_ether_loadout(self) -> None:
        if self.ether_data is None:
            return
        index = self.active_ether_loadout_index()
        if not messagebox.askyesno(APP_TITLE, f"Reset all allocated Ether nodes in loadout {index + 1}?", parent=self.ether_window):
            return
        self.ether_data = set_ether_loadout_nodes(self.ether_data, index, [])
        self.refresh_ether_window(index)
        self.set_status(f"Ether loadout {index + 1} reset staged; not saved yet.")

    def reset_all_ether_loadouts(self) -> None:
        if self.ether_data is None:
            return
        if not messagebox.askyesno(APP_TITLE, "Reset all allocated Ether nodes in all 8 loadouts?", parent=self.ether_window):
            return
        selected = self.active_ether_loadout_index()
        for index in range(ETHER_LOADOUT_COUNT):
            self.ether_data = set_ether_loadout_nodes(self.ether_data, index, [])
        self.refresh_ether_window(selected)
        self.set_status("All 8 Ether loadout resets staged; not saved yet.")

    def reload_ether_from_disk(self) -> None:
        if self.ether_path is None:
            return
        try:
            self.ether_data = read_ether_file(self.ether_path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not reload the Ether sidecar:\n{exc}")
            return
        self.refresh_ether_window()
        self.set_status(f"Reloaded {self.ether_path.name} from disk.")

    def save_ether_changes(self) -> None:
        if self.ether_path is None or self.ether_data is None:
            return
        if not self.apply_ether_nodes_to_memory(update_status=False):
            return
        try:
            backup = write_ether_file(self.ether_path, self.ether_data, create_backup=self.ether_path.exists())
            self.ether_data = read_ether_file(self.ether_path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not save the Ether sidecar:\n{exc}")
            return
        self.refresh_ether_window()
        backup_text = backup.name if backup else "none (new file)"
        self.set_status(f"Saved {self.ether_path.name}. Backup: {backup_text}.")
        messagebox.showinfo(
            APP_TITLE,
            f"Ether tree saved successfully.\n\n{self.ether_path}\n\nBackup:\n{backup}",
            parent=self.ether_window,
        )

    def close_ether_window(self) -> None:
        if self.ether_window is not None and self.ether_window.winfo_exists():
            self.ether_window.destroy()
        self.ether_window = None
        self.ether_loadout_list = None
        self.ether_path = None
        self.ether_data = None
        self.ether_nodes_var.set("")

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
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
            messagebox.showerror(APP_TITLE, f"Could not prepare the character:\n{exc}")
            return None

    def save_current(self, *, show_success_dialog: bool = True) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
        backup_name = backup.name if backup else "No backup needed"
        shop_part = f" Shop backup: {shop_backup.name if shop_backup else 'not needed'}." if shop_text is not None else ""
        self.set_status(f"Character saved. Backup: {backup_name}.{shop_part}")
        if show_success_dialog:
            extra = f"\nShop backup: {shop_backup.name if shop_backup else 'not needed'}" if shop_text is not None else ""
            messagebox.showinfo(APP_TITLE, f"Character saved successfully.\n\nBackup: {backup_name}{extra}")

    def save_as(self) -> None:
        if not self.loaded:
            messagebox.showinfo(APP_TITLE, "Open a character first.")
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
            messagebox.showerror(APP_TITLE, f"Could not save the character:\n{exc}")
            return

        self.loaded = LoadedSave(path, text, classify_text(text, path), shop_path, shop_text)
        self.current_file.set(str(path))
        self.set_raw(text)
        self._character_field_vars_dirty = False
        self.set_status(f"Saved as {path.name}. Backup: {backup.name if backup else 'not needed'}")

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


def default_character_save_paths() -> list[Path]:
    paths = list(DEFAULT_SAVE_DIR.glob("herosiege*.hss"))
    nested = DEFAULT_SAVE_DIR / "hs2saves"
    if nested.is_dir():
        paths.extend(nested.glob("herosiege*.hss"))
    readable: list[Path] = []
    for path in sorted(set(paths), key=lambda candidate: save_slot_sort_key(str(candidate))):
        try:
            text = decode_hss_file(path)
        except HssFormatError:
            continue
        if classify_text(text, path) == "character_ini":
            readable.append(path)
    return readable


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", nargs="*", type=Path, help="Decode and re-encode selected .hss files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.self_test is not None:
        paths = args.self_test or default_character_save_paths()
        return 0 if run_roundtrip_test(paths) else 1

    root = Tk()
    HssEditorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
