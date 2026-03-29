import math
import requests
import time
import random
import re
import os
import json
import ast
from datetime import datetime, timedelta, timezone
import sys
from tg_report import send_telegram, send_game_report
from collections import Counter
# Supaya print() bisa pakai emoji di Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    # Python versi lama tidak ada reconfigure → skip
    pass


# version 1.3 - ForTres_149 Ultimate Hunter & Survival (FIXED)
# ---------------- CONFIG ----------------
BASE_URL = "https://cdn.moltyroyale.com/api" # URL disesuaikan dengan contoh dev
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise Exception("API_KEY tidak ditemukan di environment")

AGENT_NAME = os.getenv("AGENT_NAME", "ForTres")


session = requests.Session()

session.headers.update({
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
})

# 🔥 TAMBAHAN PROXY
PROXY = os.getenv("PROXY")

if PROXY:
    session.proxies.update({
        "http": PROXY,
        "https": PROXY
    })
    print("🌐 Proxy aktif:", PROXY)
else:
    print("⚠ Proxy tidak digunakan")
    try:
        ip_check = session.get("https://api.ipify.org?format=json", timeout=10)
        print("🌍 IP AKTIF:", ip_check.text)
    except Exception as e:
        print("❌ Gagal cek IP:", e)
# =========================
# MEMORY REGION & DEADZONE
# =========================
REGION_MEMORY = {}  # { region_id: { 'isDeathZone': bool, 'lastSeenTurn': int } }
# ==============================
# OPTIONAL RECONNECT (ISI JIKA MAU)
# ==============================
RECONNECT_GAME_ID =   None   # contoh: "game-123"
RECONNECT_AGENT_ID =  None   # contoh: "agent-456"

LAST_STATE = None
MAP_MEMORY = {}
STATE_TIMEOUT = 60
last_state_update = time.time()
WITA = timezone(timedelta(hours=8))
MAX_LAST_REGIONS = 30
TEAM_PREFIXES = ("ForTres", "SEKAI", "GORIS", "GLORIES", "TERIS", "LOSTV", "IMOAIX", "LBXES", "TSAL", "NEEST", "LOOBS", "ENOZ", "NOIGER", "BOBRIO")

def is_teammate(name):
    if not name:
        return False
    return isinstance(name, str) and name.startswith(TEAM_PREFIXES)
TARGET_LOCK = {
    "id": None,
    "until_turn": 0
}
last_regions = []
last_target_id = None
TEAMMATE_MEMORY = {}
REGROUP_MODE = True
SQUAD_TARGET = None
TEAM_MOVE_TARGET = None
LAST_SAFE_REGION = None
CURRENT_GOAL = None
THREAT_MAP = {}
GOAL_TURN = 0
LAST_MOVE = None
MOVE_COMMIT_TURN = 0
GAME_STATS = {
    "kills": 0,
    "deaths": 0
}
REGISTERED = False
LAST_CURSE_ID = None
LAST_ESCAPE_TIME = 0
CURSE_LOCK_ID = None
CURSE_STATE = {
    "last_id": None,
    "last_time": 0
}
SKIP_ITEMS = {
    "megaphone",
    "map",
    "radio"
}
PREV_VISIBLE_AGENTS = {}
LAST_ATTACK_TARGET = None
LAST_KILL_REGION = None
GAME_FINISHED_SENT = False
LAST_CURSE_TIME = 0
CURSE_COOLDOWN = 3
# ---------------- UTILS ----------------

def detect_curse(state, my_id):
    global LAST_CURSE_ID

    latest_curse = None

    for msg in state.get("recentMessages", []):

        if msg.get("senderName") != "Guardian":
            continue

        if msg.get("senderId") == my_id:
            continue

        content = (msg.get("content") or "").strip()

        if "[Curse]" not in content:
            continue

        # 🔥 selalu ambil yang TERBARU
        latest_curse = msg

    if not latest_curse:
        return None

    msg_id = latest_curse.get("id")

    # 🔥 skip kalau sudah diproses
    if msg_id == LAST_CURSE_ID:
        return None

    question = latest_curse.get("content").replace("[Curse]", "", 1).strip()
    #question = question.split("\n")[0].strip()
    return {
        "id": msg_id,
        "question": question,
        "senderId": latest_curse.get("senderId")
    }

def shorten_bg(text):
    text = text.lower()

    text = re.sub(r"\b(there is|imagine)\b", "", text)
    text = re.sub(r"\b(leaping|drifting|flowing|spinning|crossing|echoing)\b", "", text)
    text = re.sub(r"\bin the background\b", "", text)

    text = re.sub(r"\s+", " ", text).strip()

    words = text.split()
    core = " ".join(words[:3])

    return core.capitalize()

# =========================
# 🌸 CLEAN BACKGROUND
# =========================
def clean_bg(text):
    # hapus prefix
    text = re.sub(
        r"^(note:|context:|background:|scene:|setting:)\s*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    # 🔥 hapus instruksi guardian
    text = re.sub(
        r"\b(acknowledge|mention|include|reference|respond|react|weave)\b.*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    # 🔥 hapus "in your answer" dll
    text = re.sub(
        r"\b(in your answer|in your reply)\b.*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    # rapikan spasi
    text = re.sub(r"\s+", " ", text)

    return text


# =========================
# 🎭 STYLE DETECTOR (MUDAH TAMBAH RULE)
# =========================
def detect_style(full_text):
    t = full_text.lower()

    style_rules = [
        ("weave", ["weave"]),
        ("mention", ["mention"]),
        ("include", ["include"]),
        ("acknowledge", ["acknowledge"]),
        ("reference", ["reference"]),
        ("respond", ["respond", "react"]),
    ]

    for style, keywords in style_rules:
        for kw in keywords:
            if kw in t:
                return style

    return "default"


# =========================
# 🎯 STYLE FORMATTER
# =========================
def apply_style(answer, bg, style):
    if not bg:
        return answer

    short = shorten_bg(bg)

    # math / number → jangan pakai there is / scene shows
    if answer.replace(".", "").isdigit():
        return f"{answer}. {short}"

    if style in ["mention", "include", "reference", "weave"]:
        return f"{answer}. {short}"

    elif style == "acknowledge":
        return f"{answer}. {short}"  # gunakan short bg langsung

    elif style == "respond":
        return f"{answer}. The scene shows {short.lower()}"

    return answer


# =========================
# 🧠 SOLVER CORE
# =========================
def solve_logic(q):
    q_lower = q.lower()
    answer = "idk"

    # CONTRADICTION
    if "contradiction" in q_lower or "paradox" in q_lower:
        match = re.search(r"'([^']+)'", q)
        if match:
            clauses = [c.strip() for c in match.group(1).split(",")]
            if len(clauses) >= 2:
                return f"{clauses[0]} contradicts {clauses[1]}"
        return "the statements contradict each other"

    # NUMBER
    number_match = re.search(r"what is the number (\d+)", q_lower)
    if number_match:
        return f"number {number_match.group(1)}"

    # COUNT !
    ex_match = re.search(r"how many exclamation marks are in '([^']+)'", q_lower)
    if ex_match:
        return str(ex_match.group(1).count("!"))

    # MATH
    expr = q_lower
    expr = expr.replace("plus", "+").replace("minus", "-")
    expr = expr.replace("times", "*").replace("multiplied by", "*")
    expr = expr.replace("divided by", "/")
    expr = expr.replace("×", "*").replace("÷", "/")
    expr = expr.replace(" x ", "*")
    
    math_match = re.search(r'(\d+\s*[\+\-\*/]\s*\d+)', expr)
    if math_match:
        try:
            result = eval(math_match.group(1))
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            return str(result)
        except:
            pass
    # COUNT UPPERCASE
    upper_match = re.search(r"how many uppercase letters are in '([^']+)'", q_lower)
    if upper_match:
        txt = upper_match.group(1)
        return str(sum(1 for c in txt if c.isupper()))

    # COUNT LETTERS
    letters_match = re.search(r"how many letters are in (?:the word )?'([^']+)'", q_lower)
    if letters_match:
        txt = letters_match.group(1)
        return str(len(txt.replace(" ", "")))  # hapus spasi

    # SYLLOGISM
    match_all = re.search(r"all (\w+) are (\w+)", q_lower)
    match_is = re.search(r"(\w+) is a (\w+)", q_lower)

    if match_all and match_is:
        subject = match_all.group(1).rstrip("s")
        entity_class = match_is.group(2).rstrip("s")

        return "yes" if entity_class == subject else "no"

    # TRANSITIVE
    if "is larger than" in q_lower:
        comparisons = re.findall(r"(\w+) is larger than (\w+)", q_lower)
        mapping = {a: b for a, b in comparisons}

        q_match = re.search(r"is (\w+) larger than (\w+)", q_lower)
        if q_match:
            x, y = q_match.groups()
            cur = x

            while cur in mapping:
                if mapping[cur] == y:
                    return "yes"
                cur = mapping[cur]

        return "no"

    return "idk"


# =========================
# 🧩 MAIN FUNCTION
# =========================
def solve_curse(question):
    try:
        q = question.strip()

        # =========================
        # INIT (WAJIB)
        # =========================
        background = ""
        main_q = q

        # =========================
        # SPLIT FLEXIBLE
        # =========================
        parts = re.split(
            r"\b(Scene:|Context:|Background:|Note:|Setting:)\b",
            q,
            maxsplit=1
        )

        if len(parts) >= 3:
            main_q = parts[0].strip()
            background = parts[2].strip()

        # =========================
        # FALLBACK (kalau gagal split)
        # =========================
        if not background:
            bg_match = re.search(
                r"(Scene:|Context:|Background:|Note:|Setting:)(.*)",
                q,
                re.IGNORECASE
            )
            if bg_match:
                main_q = q[:bg_match.start()].strip()
                background = bg_match.group(2).strip()

        # =========================
        # SOLVE
        # =========================
        answer = solve_logic(main_q)

        # =========================
        # STYLE
        # =========================
        style = detect_style(question)

        # =========================
        # CLEAN BG
        # =========================
        bg = clean_bg(background)

        # =========================
        # APPLY STYLE
        # =========================
        if answer != "idk" and bg:
            answer = apply_style(answer, bg, style)

        # =========================
        # FINAL CLEAN
        # =========================
        answer = re.sub(r"\.\s*\.", ".", answer)
        answer = re.sub(r"\s+\.", ".", answer)
        answer = re.sub(r"\s+", " ", answer).strip()

        # DEBUG (optional)
        print("DEBUG BG:", bg)
        print("DEBUG ANSWER:", answer)

        return answer

    except Exception as e:
        print("error:", e)
        return "idk"

def is_safe_goal(rid, state):
    pending_dz = {
        r["id"] if isinstance(r, dict) else r
        for r in (state.get("pendingDeathzones") or [])
    }

    mem = MAP_MEMORY.get(rid, {})
    region_mem = REGION_MEMORY.get(rid, {})

    if rid in pending_dz:
        return False

    if mem.get("isDeathZone") or region_mem.get("isDeathZone"):
        return False

    if mem.get("isMine") or region_mem.get("isMine"):
        return False

    return True
    
def update_threat_map(state):
    global THREAT_MAP

    THREAT_MAP = {}  # 🔥 RESET

    for a in state.get("visibleAgents") or []:
        rid = a.get("regionId")

        if not is_teammate(a.get("name")):
            THREAT_MAP[rid] = THREAT_MAP.get(rid, 0) + (a.get("atk",5) * 8)
        else:
            THREAT_MAP[rid] = THREAT_MAP.get(rid, 0) - 10

    # decay
    for r in list(THREAT_MAP.keys()):
        THREAT_MAP[r] = THREAT_MAP[r]*0.95 + random.uniform(-1,1)

def find_best_global_target(state):
    me = state.get("self", {})
    hp = me.get("hp", 100)
    inventory = me.get("inventory", [])

    best_region = None
    best_score = -9999

    for rid, data in MAP_MEMORY.items():

        # ❌ skip deathzone / mine
        if data.get("isDeathZone") or data.get("isMine"):
            continue

        # ❌ skip info terlalu lama (biar gak stale)
        if state.get("turn", 0) - data.get("lastSeen", 0) > 50:
            continue

        score = 0

        items = data.get("items", [])

        for item in items:
            name = (item.get("name") or "").lower()
            category = item.get("category", "")

            # 🔥 PRIORITY 1: MOLTZ
            if item.get("type") == "currency" or "moltz" in name:
                score += 2000

            # 🔥 PRIORITY 2: WEAPON
            if category == "weapon":
                score += item.get("atkBonus", 0) * 80

            # 🔥 PRIORITY 3: RECOVERY (kalau HP butuh)
            if hp < 70 and category in ["healing", "consumable"]:
                score += 600

            # 🔥 PRIORITY 4: BINOCULARS
            if "binocular" in name:
                score += 300

        # ❌ SKIP ITEM LIST (kecuali prioritas di atas)
        if any((item.get("name") or "").lower() in SKIP_ITEMS for item in items):
            score -= 200

        # ⚠️ THREAT PENALTY
        score -= THREAT_MAP.get(rid, 0)

        # 🧭 DISTANCE BONUS (biar gak ngejar terlalu jauh)
        score -= 5 * random.randint(0, 5)

        if score > best_score:
            best_score = score
            best_region = rid

    return best_region

def choose_goal(state):
    global last_target_id

    me = state.get("self", {})
    hp = me.get("hp", 100)

    region = state.get("currentRegion", {})
    current = region.get("id")

    visible_agents = state.get("visibleAgents", [])

    # =========================
    # 🔒 LOCK TARGET
    # =========================
    if last_target_id:
        for e in visible_agents:
            if e.get("id") == last_target_id:
                return {"target": e.get("regionId"), "type": "attack"}

    # =========================
    # ☠️ PRIORITY 1: GUARDIAN
    # =========================
    guardians = [e for e in visible_agents if is_guardian(e)]
    if guardians:
        target = min(guardians, key=lambda x: x.get("hp", 999))
        if is_safe_goal(target.get("regionId"), state):
            return {"target": target.get("regionId"), "type": "attack"}

    # =========================
    # 🩸 PRIORITY 2: ESCAPE
    # =========================
    if hp < 31:
        safe = [
            r for r in memory_safe_regions(state)
            if r not in [e.get("regionId") for e in visible_agents if not is_guardian(e)]
        ]
        if safe:
            best = min(safe, key=lambda r: THREAT_MAP.get(r, 0))
            return {"target": best, "type": "escape"}

    # =========================
    # ⚔️ PRIORITY 3: ENEMY
    # =========================
    enemies = [
        e for e in visible_agents
        if not is_teammate(e.get("name"))
        and not is_guardian(e)
    ]

    if enemies and hp > 30:
        target = min(enemies, key=lambda x: x.get("hp", 999))
        if is_safe_goal(target.get("regionId"), state):
            return {"target": target.get("regionId"), "type": "attack"}

    # =========================
    # 🌍 PRIORITY 4: GLOBAL LOOT
    # =========================
    target = find_best_global_target(state)
    if target and is_safe_goal(target, state):
        return {"target": target, "type": "loot"}

    # =========================
    # 🧭 PRIORITY 5: EXPLORE
    # =========================
    unexplored = [
        rid for rid, data in MAP_MEMORY.items()
        if state.get("turn", 0) - data.get("lastSeen", 0) > 15
        and is_safe_goal(rid, state)
    ]

    if unexplored:
        best = min(unexplored, key=lambda r: THREAT_MAP.get(r, 0))
        return {"target": best, "type": "explore"}

    return {"target": current, "type": "idle"}

def get_neighbors(region_id, state):

    neighbors = []

    for r in state.get("visibleRegions", []):
        if r.get("id") == region_id:
            neighbors = [
                c["id"] if isinstance(c, dict) else c
                for c in r.get("connections", [])
            ]

    safe_neighbors = []

    for n in neighbors:
        mem = REGION_MEMORY.get(n, {})
        if not mem.get("isDeathZone") and not mem.get("isMine"):
            safe_neighbors.append(n)

    return safe_neighbors


def heuristic(a, b):
    threat_penalty = THREAT_MAP.get(a, 0)
    return 1 + threat_penalty * 0.05


def astar(start, goal, state):
    open_set = [start]
    came_from = {}

    g = {start: 0}
    f = {start: heuristic(start, goal)}

    while open_set:
        current = min(open_set, key=lambda x: f.get(x, 9999))

        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            return list(reversed(path))

        open_set.remove(current)

        for n in get_neighbors(current, state):
            temp_g = g[current] + 1

            if temp_g < g.get(n, 9999):
                came_from[n] = current
                g[n] = temp_g
                f[n] = temp_g + heuristic(n, goal)

                if n not in open_set:
                    open_set.append(n)

    return []

def get_agent_id_from_game(game_id, agent_name):
    """Cari agent_id di game tertentu berdasarkan nama agent"""
    try:
        r = session.get(f"{BASE_URL}/games/{game_id}", headers={"X-API-Key": API_KEY}, timeout=10)
        if r.status_code != 200:
            return None
        agents = r.json().get("data", {}).get("agents", [])
        for a in agents:
            if a.get("name") == agent_name:
                return a.get("id")
        return None
    except Exception as e:
        print("⚠ Gagal ambil agent_id:", e)
        return None

def update_teammate_memory(state):

    for agent in state.get("visibleAgents", []):
        name = agent.get("name")

        if is_teammate(name):
            TEAMMATE_MEMORY[name] = agent.get("regionId")

def log(msg):
    time_str = datetime.now(WITA).strftime('%H:%M:%S')
    print(f"[{time_str}] [{AGENT_NAME}] {msg}")

from collections import Counter

def get_team_center(state):
    agents = state.get("visibleAgents", [])

    regions = [
        a.get("regionId")
        for a in agents
        if is_teammate(a.get("name"))
    ]

    if not regions:
        return None

    return Counter(regions).most_common(1)[0][0]

def update_team_target(state):
    global TEAM_MOVE_TARGET

    center = get_team_center(state)

    if center:
        TEAM_MOVE_TARGET = center

def save_survivor(agent_name):
    try:
        with open("survivors.txt", "a", encoding="utf-8") as f:
            f.write(agent_name + "\n")
        log(f"[SURVIVOR] {agent_name} saved")
    except Exception as e:
        log(f"[ERROR] save_survivor: {e}")

def is_safe_region(rid, state):
    visible = {r["id"]: r for r in state.get("visibleRegions") or []}
    pending_dz = {
        r["id"] if isinstance(r, dict) else r
        for r in (state.get("pendingDeathzones") or [])
    }

    log(f"VISIBLE REGIONS: {len(visible)}")
    log(f"PENDING DZ: {pending_dz}")

    info = visible.get(rid)

    # ❌ Hindari deathzone aktif
    if info and info.get("isDeathZone"):
        return False

    # ❌ Hindari pending deathzone
    if rid in pending_dz:
        return False

    # ❌ Hindari memory deadzone
    mem = REGION_MEMORY.get(rid)
    if mem and mem.get('isDeathZone', False):
        return False

    return True

def current_weapon(agent):
    wid = agent.get("equippedWeapon")
    # Handle jika wid adalah object atau ID string
    actual_id = wid.get("id") if isinstance(wid, dict) else wid
    for item in agent.get("inventory") or []:
        if item.get("id") == actual_id: return item
    return None

def print_header(game_name=None, game_id=None, agent_id=None):
    print("="*50)
    print(f" AGENT: {AGENT_NAME} | MODE: NO-SESSION RECOVERY")
    print("="*50)
    if game_name:
        print(f"Game: {game_name}")
        print(f"G-ID: {game_id} | A-ID: {agent_id}")
        print("="*50)

def get_state(game_id, agent_id):
    try:
        r = session.get(
            f"{BASE_URL}/games/{game_id}/agents/{agent_id}/state",
            headers={"X-API-Key": API_KEY},
            timeout=15
        )
        
        # Cek jika status bukan 200 (OK)
        if r.status_code != 200:
            return None
            
        # Validasi apakah respon berisi JSON
        try:
            data = r.json()
            return data.get("data")
        except ValueError:
            # Ini yang mencegah error 'char 0'
            return None
            
    except Exception:
        return None
    
LAST_API_CALL = 0

def wait_rate_limit():
    global LAST_API_CALL
    now = time.time()
    diff = now - LAST_API_CALL
    if diff < 0.5:
        time.sleep(0.5 - diff)
    LAST_API_CALL = time.time()


def safe_get(url, retries=3):
    for attempt in range(retries):
        try:
            wait_rate_limit()
            r = session.get(url, headers={"X-API-Key": API_KEY}, timeout=15)

            if r.status_code == 429:
                print("⚠ Rate limit, tunggu 1 detik...")
                time.sleep(1)
                continue

            if r.status_code >= 500:
                print("⚠ Server error, retry...")
                time.sleep(0.1)
                continue

            return r

        except requests.RequestException:
            print("⚠ Network error, retry...")
            time.sleep(0.1)

    return None


def safe_post(url, payload, retries=3):
    for attempt in range(retries):
        try:
            wait_rate_limit()
            #log(f"[DEBUG] POST → {url}")
            #log(f"[DEBUG] PAYLOAD → {payload}")

            r = session.post(url, json=payload, headers={"X-API-Key": API_KEY}, timeout=20)
            #log(f"[DEBUG] STATUS → {r.status_code}")

            if r.status_code >= 400:
                log(f"[DEBUG] RESPONSE → {r.text}")

            if r.status_code == 429:
                print("⚠ Rate limit (POST), tunggu 1 detik...")
                time.sleep(1)
                continue

            if r.status_code >= 500:
                print("⚠ Server error (POST), retry...")
                time.sleep(0.1)
                continue

            return r

        except requests.exceptions.Timeout:
            print("⏳ TIMEOUT (POST)")
        except requests.exceptions.ConnectionError:
            print("🔌 CONNECTION ERROR (POST)")
        except requests.exceptions.RequestException as e:
            print("❌ REQUEST ERROR:", e)

        time.sleep(0.1)

    print("❌ safe_post gagal total setelah retry")
    return None

def check_active_game():
    res = safe_get(f"{BASE_URL}/accounts/me")

    if not res or res.status_code != 200:
        return None

    data = res.json().get("data", {})
    games = data.get("currentGames", [])

    if not games:
        return None

    g = games[0]

    # 🔴 kalau agent sudah mati jangan reconnect
    if not g.get("isAlive", True):
        print("💀 Agent di game lama sudah mati, skip reconnect.")
        return None

    game_id = g.get("gameId")
    agent_id = g.get("agentId")

    print("🔁 Found active game!")
    print("Game:", game_id)
    print("Agent:", agent_id)

    return game_id, agent_id

def start_session():
    global GAME_FINISHED_SENT
    GAME_FINISHED_SENT = False

    # 1️⃣ cek apakah masih ada game aktif
    active = check_active_game()

    if active:
        game_id, agent_id = active

        print("🔁 Reconnecting to existing game...")
        return game_id, agent_id

    # 2️⃣ kalau tidak ada → join game baru
    return join_or_create()

def send_register_telegram(AGENT_NAME, game_id, agent_id):
    try:
        text = f"""🚀 AGENT REGISTERED
👤 Agent: {AGENT_NAME}
🎮 Game: {game_id}
🆔 Agent ID: {agent_id}"""

        send_telegram(text)

    except Exception as e:
        log(f"⚠ TG REGISTER ERROR: {e}")

def join_or_create():
    while True:
        # 1️⃣ Cari game waiting
        res = safe_get(f"{BASE_URL}/games?status=waiting")
        if not res:
            print("⚠ Tidak bisa ambil daftar game...")
            continue

        waiting_games = res.json().get("data", [])
        if waiting_games:
            # Cari hanya FREE game
            free_games = [
                g for g in waiting_games
                if g.get("entryType", "").lower() == "free"
            ]

            if free_games:
                game = random.choice(free_games)  # 🔥 FIX
                print(f"🎮 Join FREE game: {game['name']}")
            else:
                game = None
        else:
            game = None

        if not game:
            print("⚠ Tidak ada FREE game waiting, tunggu...")
            time.sleep(0.1)
            continue

        # 2️⃣ Register agent dulu
        reg = safe_post(
            f"{BASE_URL}/games/{game['id']}/agents/register",
            {"name": AGENT_NAME}
        )

        if not reg:
            print("❌ Register gagal (safe_post returned None)")
            continue

        data = reg.json()
        error_code = data.get("error", {}).get("code")

        if reg.status_code in [200, 201, 202] and not error_code:
            # ✅ SUCCESS
            agent_id = data["data"]["id"]
            from tg_report import send_game_start

            send_register_telegram(AGENT_NAME, game["id"], agent_id)
            print("✅ Register sukses")
            print("AGENT NAME", AGENT_NAME)
            print("Game ID:", game["id"])
            print("Agent ID:", agent_id)
            with open("session.json","w") as f:
                json.dump({
                    "game_id": game["id"],
                    "agent_id": agent_id
                }, f)
            return game["id"], agent_id

        # 🔥 Kalau agent sudah di game lain → reconnect
        if error_code == "ACCOUNT_ALREADY_IN_GAME":
            current_game_id = data.get("error", {}).get("currentGameId")
            print(f"⚠ Agent sudah aktif di game lain: {current_game_id}")

            agent_id = get_agent_id_from_game(current_game_id, AGENT_NAME)
            if agent_id:
                global RECONNECT_GAME_ID, RECONNECT_AGENT_ID
                RECONNECT_GAME_ID = current_game_id
                RECONNECT_AGENT_ID = agent_id
                print("🔁 Reconnect otomatis ke game lama...")
                return start_session()
            else:
                print("❌ Gagal ambil agent_id dari game lama, retry 5 detik...")
                continue

        # 🔥 Error lain → retry
        print(f"❌ Register gagal, error_code={error_code}, retry 3 detik...")

        # ✅ SUCCESS
        agent_id = data["data"]["id"]

        print("✅ Register sukses")
        print("Game ID:", game["id"])
        print("Agent ID:", agent_id)
        with open("session.json","w") as f:
            json.dump({
                "game_id": game["id"],
                "agent_id": agent_id
            }, f)

        return game["id"], agent_id

# ---------------- LOGIC ----------------
def get_region_name(region_id, state):
    # 1️⃣ cek visible dulu
    for r in state.get("visibleRegions") or []:
        if r.get("id") == region_id:
            return r.get("name")

    # 2️⃣ cek current region
    current = state.get("currentRegion") or {}
    if current.get("id") == region_id:
        return current.get("name")

    # 3️⃣ cek MAP MEMORY 🔥
    mem = MAP_MEMORY.get(region_id)
    if mem and mem.get("name"):
        return mem.get("name")

    # 4️⃣ fallback
    return str(region_id)

def update_region_memory(state):
    """Update REGION_MEMORY tiap turn termasuk deathzone & mine"""
    global REGION_MEMORY
    current_turn = state.get("turn", 0)
    
    # update visible regions
    for r in state.get("visibleRegions") or []:
        rid = r.get("id")
        REGION_MEMORY[rid] = {
            'isDeathZone': r.get("isDeathZone", False),
            'isMine': r.get("hasMine", False),  # baru: deteksi mine/trap
            'lastSeenTurn': current_turn
        }

    # update pending deathzone
    for r in state.get("pendingDeathzones") or []:
        rid = r.get("id") if isinstance(r, dict) else r
        if rid not in REGION_MEMORY:
            REGION_MEMORY[rid] = {
                'isDeathZone': False,
                'isMine': False,
                'lastSeenTurn': current_turn
            }


def update_map_memory(state):
    if len(MAP_MEMORY) > 500:
        MAP_MEMORY.pop(next(iter(MAP_MEMORY)))

    turn = state.get("turn", 0)

    visible_regions = state.get("visibleRegions") or []

    for r in visible_regions:

        rid = r.get("id")

        MAP_MEMORY[rid] = {
            "name": r.get("name"),   # 🔥 INI PENTING
            "connections": r.get("connections", []),
            "isDeathZone": r.get("isDeathZone", False),
            "items": r.get("items", []),
            "isMine": r.get("hasMine", False),
            "terrain": r.get("terrain"),
            "visionRequirement": r.get("visionRequirement", 0),
            "visionModifier": r.get("visionModifier", 0),
            "lastSeen": turn
        }
def is_guardian(agent):
    return "Guardian" in agent.get("name", "")

def regroup_target(state):

    region = state.get("currentRegion", {})
    my_region = region.get("id")
    connections = normalize_connections(region.get("connections"))

    # simpan region aman terakhir
    global LAST_SAFE_REGION

    if not region.get("isDeathZone"):
        LAST_SAFE_REGION = region.get("id")

    # 1️⃣ cek teammate terlihat
    visible = [
        a for a in state.get("visibleAgents", [])
        if is_teammate(a.get("name"))
        and a.get("regionId") != my_region
    ]

    if visible:
        target = visible[0]["regionId"]

        if target in connections:
            log(f"👥 MOVE TO TEAMMATE → {target}")
            return {"type": "move", "regionId": target}

    # 2️⃣ cek memory teammate
    for name, region_id in TEAMMATE_MEMORY.items():

        if region_id in connections:
            log(f"🧠 MOVE TO LAST SEEN TEAMMATE → {region_id}")
            return {"type": "move", "regionId": region_id}

    return None

def normalize_connections(connections):
    return [
        c["id"] if isinstance(c, dict) else c
        for c in (connections or [])
    ]

def is_killable(enemy, my_atk, my_hp):
    e_hp = enemy.get("hp", 999)
    e_atk = enemy.get("atk", 5)

    turns_to_kill = max(1, e_hp / max(my_atk, 1))
    turns_to_die = max(1, my_hp / max(e_atk, 1))

    return turns_to_kill <= turns_to_die

def smart_move(state, mode="normal"):
    global CURRENT_GOAL, GOAL_TURN
    global last_regions, LAST_SAFE_REGION

    turn = state.get("turn", 0)

    region = state.get("currentRegion") or {}
    current = region.get("id")
    connections = normalize_connections(region.get("connections"))

    if not connections:
        return {"type": "rest"}

    # =========================
    # 🧠 UPDATE GOAL (SINGLE SOURCE)
    # =========================
    if not CURRENT_GOAL or turn - GOAL_TURN > 6:
        CURRENT_GOAL = choose_goal(state)
        GOAL_TURN = turn

    goal_target = None
    goal_type = "idle"

    if isinstance(CURRENT_GOAL, dict):
        goal_target = CURRENT_GOAL.get("target")
        goal_type = CURRENT_GOAL.get("type")
    else:
        goal_target = CURRENT_GOAL

    # =========================
    # 🧠 PATHFINDING
    # =========================
    next_step = None
    if goal_target and goal_target != current:
        path = astar(current, goal_target, state)
        if path:
            next_step = path[0]

    # =========================
    # 🧭 VALID MOVES
    # =========================
    pending_dz = {
        r["id"] if isinstance(r, dict) else r
        for r in (state.get("pendingDeathzones") or [])
    }

    valid_moves = []
    for rid in connections:
        mem = REGION_MEMORY.get(rid, {})
        map_mem = MAP_MEMORY.get(rid, {})

        if rid in pending_dz:
            continue
        if mem.get("isDeathZone") or mem.get("isMine"):
            continue

        # hindari region minus vision
        if str(map_mem.get("visionRequirement")).lower() == "minus":
            continue
        if map_mem.get("visionModifier") == "minus":
            continue

        valid_moves.append(rid)

    if not valid_moves:
        return {"type": "rest"}

    # =========================
    # 🧮 SCORING SYSTEM (GOAL-DRIVEN)
    # =========================
    best = None
    best_score = -9999

    for rid in valid_moves:
        score = 0

        # =========================
        # 🎯 CORE: FOLLOW GOAL
        # =========================
        if rid == next_step:
            score += 800   # 🔥 sangat kuat (ini kunci elite)
        elif goal_target:
            score -= 80    # penalti kalau menjauh

        # =========================
        # ⚠️ THREAT SYSTEM
        # =========================
        threat = THREAT_MAP.get(rid, 0)

        score -= threat

        if threat > 60:
            score -= 400  # hard avoid

        # =========================
        # 🩸 ESCAPE MODE BOOST
        # =========================
        if goal_type == "escape":
            score -= threat * 2   # makin sensitif ke danger

        # =========================
        # ⚔️ ATTACK MODE BOOST
        # =========================
        if goal_type == "attack":
            # kalau ada enemy di region itu → bonus
            for e in state.get("visibleAgents", []):
                if e.get("regionId") == rid and not is_teammate(e.get("name")):
                    score += 250

        # =========================
        # 💰 LOOT MODE BOOST
        # =========================
        if goal_type == "loot":
            items = MAP_MEMORY.get(rid, {}).get("items", [])

            for item in items:
                name = (item.get("name") or "").lower()

                if item.get("type") == "currency" or "moltz" in name:
                    score += 500

                if item.get("category") == "weapon":
                    score += item.get("atkBonus", 0) * 40

        # =========================
        # 🔁 ANTI LOOP
        # =========================
        if rid in last_regions[-3:]:
            score -= 200

        if rid in last_regions:
            score -= 60

        # =========================
        # 🧭 EXPLORATION BONUS
        # =========================
        if rid not in MAP_MEMORY:
            score += 50

        # =========================
        # 💾 SAFE REGION TRACK
        # =========================
        if threat < 30:
            LAST_SAFE_REGION = rid

        # =========================
        # 🏆 PICK BEST
        # =========================
        if score > best_score:
            best_score = score
            best = rid

    # =========================
    # 🔄 FALLBACK SAFETY
    # =========================
    if best and THREAT_MAP.get(best, 0) > 70:
        if LAST_SAFE_REGION and LAST_SAFE_REGION in connections:
            best = LAST_SAFE_REGION

    # =========================
    # 💾 SAVE HISTORY
    # =========================
    if best:
        last_regions.append(best)
        if len(last_regions) > 25:
            last_regions.pop(0)

        return {"type": "move", "regionId": best}

    return {"type": "rest"}

def choose_recovery(self_data):
    hp = self_data["hp"]
    ep = self_data["ep"]
    inventory = self_data.get("inventory", [])

    # --- MEDKIT ---
    if hp <= 50:
        medkit = next((i for i in inventory if i["name"] == "Medkit"), None)
        if medkit:
            return {"type": "use_item", "itemId": medkit["id"]}

    # --- BANDAGE ---
    if hp <= 70:
        bandage = next((i for i in inventory if i["name"] == "Bandage"), None)
        if bandage:
            return {"type": "use_item", "itemId": bandage["id"]}

    # --- RATIONS ---
    if hp <= 80:
        rations = next((i for i in inventory if i["name"] == "Emergency rations"), None)
        if rations:
            return {"type": "use_item", "itemId": rations["id"]}
        
    # --- ENERGY ---
    if ep <= 5:
        energy = next((i for i in inventory if i["name"] == "Energy drink"), None)
        if energy:
            return {"type": "use_item", "itemId": energy["id"]}

    return None

def choose_best_target(enemies, my_attack, my_hp, state):
    global last_target_id
    global SQUAD_TARGET
    global TARGET_LOCK

    current_time = time.time()

    # =========================
    # 🥇 PRIORITAS: ONE HIT KILL
    # =========================
    one_hit_targets = [
        e for e in enemies
        if e.get("hp", 0) <= my_attack
    ]

    if one_hit_targets:
        target = min(one_hit_targets, key=lambda x: x.get("hp", 999))

        TARGET_LOCK["id"] = target.get("id")
        TARGET_LOCK["until_turn"] = state.get("turn", 0) + 2

        return target  
    
    # =========================
    # 🔒 TARGET LOCK
    # =========================
    if TARGET_LOCK["id"] and state.get("turn", 0) < TARGET_LOCK["until_turn"]:
        for e in enemies:
            if e.get("id") == TARGET_LOCK["id"]:
                return e

    # Reset jika target lama tidak ada lagi
    if last_target_id and not any(e.get("id") == last_target_id for e in enemies):
        last_target_id = None
    best_score = -999
    best_target = None

    for e in enemies:
        score = 0
        hp = e.get("hp", 0)
        atk = e.get("atk", 5)
        defense = e.get("def", 0)
        # 💣 Bisa mati dalam 2 turn?
        if hp <= my_attack * 2:
            score += 200

        # 🎯 BONUS FOKUS TARGET SEBELUMNYA
        if e.get("id") == last_target_id:
            score += 40

        # 🎯 1. Kill secure
        if hp <= my_attack:
            score += 1000

        # 🩸 2. Low HP priority
        score += (100 - hp)

        # ⚔ 3. High damage enemy = dangerous
        score += atk * 5

        # 🛡 4. Hindari DEF tinggi
        score -= defense * 3

        # 🚨 5. Kalau HP kita rendah, jangan lawan tank
        if my_hp < 30 and defense > 10:
            score -= 50

        if score > best_score:
            best_score = score
            best_target = e

    if best_target:
        last_target_id = best_target.get("id")
        SQUAD_TARGET = best_target.get("id")

    if best_target:
        TARGET_LOCK["id"] = best_target.get("id")
        TARGET_LOCK["until_turn"] = state.get("turn", 0) + 2
        
    return best_target

def get_team_region(state):
    """Cari region tempat teammate berada"""
    agents = state.get("visibleAgents", [])

    team_regions = [
        a.get("regionId")
        for a in agents
        if is_teammate(a.get("name"))
    ]

    if not team_regions:
        return None

    return min(team_regions, key=lambda r: last_regions.count(r))

def memory_safe_regions(state):
    """Return list region terhubung yang dulu pernah aman (memory), bukan deadzone/mine"""
    region = state.get("currentRegion", {})
    connections = normalize_connections(region.get("connections"))
    safe = []

    for rid in connections:
        mem = REGION_MEMORY.get(rid, {})
        if not mem.get("isDeathZone") and not mem.get("isMine"):
            safe.append(rid)

    return safe

def escape_from_deadzone(state):
    region = state.get("currentRegion", {})
    pending_dz = {
        r["id"] if isinstance(r, dict) else r
        for r in (state.get("pendingDeathzones") or [])
    }
    rid = region.get("id")

    if region.get("isDeathZone") or rid in pending_dz or (REGION_MEMORY.get(rid, {}).get("isDeathZone")):
        safe_mem = memory_safe_regions(state)
        if safe_mem:
            target_rid = min(safe_mem, key=lambda r: last_regions.count(r))
            log(f"⚠ DEADZONE ESCAPE pakai memory → {get_region_name(target_rid,state)}")
            return {"type":"move", "regionId":target_rid}
        else:
            log("⚠ DEADZONE ESCAPE → semua memory deadzone, paksa smart_move")
            return smart_move(state, mode="escape")
    return None

def should_escape(state, me, enemies_here, my_region, pending_dz):
    if state.get("currentRegion", {}).get("isDeathZone"):
        return True

    if my_region in pending_dz:
        return True

    if not enemies_here:
        return False

    my_hp = me.get("hp", 100)
    total_enemy_atk = sum(e.get("atk", 5) for e in enemies_here)

    if len(enemies_here) >= 3:
        return True

    if total_enemy_atk > my_hp * 2.2:
        return True

    weapon = current_weapon(me)
    my_attack = me.get("atk", 10) + (weapon.get("atkBonus", 0) if weapon else 0)

    target = enemies_here[0]
    enemy_hp = target.get("hp", 1)

    turns_to_kill = math.ceil(enemy_hp / max(my_attack, 1))
    turns_to_die = math.ceil(my_hp / max(total_enemy_atk, 1))

    return turns_to_die < turns_to_kill

def combat_decision(state, me, enemies_here):
    weapon = current_weapon(me)
    my_attack = me.get("atk", 10) + (weapon.get("atkBonus", 0) if weapon else 0)
    my_hp = me.get("hp", 100)

    global LAST_ATTACK_TARGET

    target = choose_best_target(enemies_here, my_attack, my_hp, state)

    if not target:
        return None

    LAST_ATTACK_TARGET = target  # ✅ simpan di sini

    log(f"⚔️ ATTACK {target.get('name')}")
    return {
        "type": "attack",
        "targetId": target.get("id"),
        "targetType": "agent"
    }

def ambush_logic(state, me, visible_agents, region):
    connections = normalize_connections(region.get("connections"))

    visible_enemies = [
        a for a in visible_agents
        if a.get("regionId") in connections
    ]

    if not visible_enemies:
        return None

    weapon = current_weapon(me)
    weapon_name = weapon.get("name", "").lower() if weapon else ""

    is_ranged = any(w in weapon_name for w in ["bow", "gun", "rifle", "pistol", "sniper"])

    enemy = visible_enemies[0]

    if is_ranged:
        log(f"🏹 AMBUSH RANGE → {enemy.get('name')}")
        return {
            "type": "attack",
            "targetId": enemy.get("id"),
            "targetType": "agent"
        }

    log(f"⚔ MOVE TO ENEMY → {enemy.get('name')}")
    return {"type": "move", "regionId": enemy.get("regionId")}

def monster_logic(state, me, my_region):
    monsters = [
        m for m in state.get("visibleMonsters", [])
        if m.get("regionId") == my_region
    ]

    if not monsters:
        return None

    if me.get("hp", 100) <= 40:
        return None

    target = min(monsters, key=lambda x: x.get("hp", 999))

    if target.get("atk", 5) * 2 < me.get("hp", 100):
        log(f"👹 MONSTER FIGHT → {target.get('name')}")
        return {
            "type": "attack",
            "targetId": target.get("id"),
            "targetType": "monster"
        }

    return None

def explore_logic(state, me, visible_agents):
    visible_items = state.get("visibleItems", [])

    if not visible_items and not visible_agents:

        if random.random() < 0.75:
            return smart_move(state)

        if me.get("ep", 0) >= 10:
            log("🔍 EXPLORE ACTION")
            return {"type": "explore"}

    return smart_move(state)


def choose_action(state):
    
    update_threat_map(state)
    update_teammate_memory(state)
    global LAST_KILL_REGION

    if LAST_KILL_REGION:
        if LAST_KILL_REGION in normalize_connections(state.get("currentRegion", {}).get("connections")):
            log(f"💰 LOOT MOVE → {LAST_KILL_REGION}")
            target = LAST_KILL_REGION
            LAST_KILL_REGION = None
            return {"type": "move", "regionId": target}

    global REGROUP_MODE, TEAM_MOVE_TARGET, LAST_SAFE_REGION

    me = state.get("self") or {}
    region = state.get("currentRegion", {})
    my_region = region.get("id")

    connections = normalize_connections(region.get("connections"))

    # =========================
    # 🧠 SAFE REGION TRACKING
    # =========================
    if not region.get("isDeathZone"):
        LAST_SAFE_REGION = my_region

    pending_dz = {
        r["id"] if isinstance(r, dict) else r
        for r in (state.get("pendingDeathzones") or [])
    }

    # =========================
    # 👥 ENEMY FILTER
    # =========================
    visible_agents = [
        a for a in state.get("visibleAgents", [])
        if a.get("id") != me.get("id")
        and not is_teammate(a.get("name"))
        and a.get("hp", 0) > 0
    ]
    
    enemies_here = [
        a for a in visible_agents
        if a.get("regionId") == my_region
    ]

    # =========================
    # 🚨 GLOBAL DANGER CHECK (UNIFIED ESCAPE)
    # =========================
    global LAST_ESCAPE_TIME

    now = time.time()

    if should_escape(state, me, enemies_here, my_region, pending_dz):
        log("🚨 ESCAPE TRIGGERED")
        log(f"💀 ENEMIES: {len(enemies_here)}")
        log(f"💀 HP: {me.get('hp')}")
        log(f"💀 PENDING DZ: {pending_dz}")
        return smart_move(state, mode="escape")

    # =========================
    # 🩹 RECOVERY
    # =========================
    recovery = choose_recovery(me)
    if recovery:
        return recovery

    # =========================
    # 🤝 REGROUP
    # =========================
    #if REGROUP_MODE:
        #move = regroup_if_needed(state, visible_agents)
        #if move:
            #return move

    # =========================
    # 🎯 AMBUSH / NEAR ENEMY
    # =========================
    action = ambush_logic(state, me, visible_agents, region)
    if action:
        return action

    # =========================
    # ⚔️ COMBAT PRIORITY SYSTEM (NEW)
    # =========================

    guardians_here = [e for e in enemies_here if is_guardian(e)]
    monsters_here = state.get("visibleMonsters", []) or []
    monsters_here = [m for m in monsters_here if m.get("regionId") == my_region]

    enemies_here = [e for e in enemies_here if not is_guardian(e)]


    # 1️⃣ PRIORITY 1: GUARDIAN
    if guardians_here:
        log("☠ PRIORITY GUARDIAN ENGAGE")
        action = combat_decision(state, me, guardians_here)
        if action:
            return action


    # 2️⃣ PRIORITY 2: MONSTER (kalau ada di region)
    if monsters_here:
        log("👹 PRIORITY MONSTER ENGAGE")
        target = min(monsters_here, key=lambda x: x.get("hp", 999))

        return {
            "type": "attack",
            "targetId": target.get("id"),
            "targetType": "monster"
        }


    # 3️⃣ PRIORITY 3: NORMAL ENEMY PLAYER
    if enemies_here:
        log("👤 PRIORITY ENEMY PLAYER ENGAGE")
        action = combat_decision(state, me, enemies_here)
        if action:
            return action

    # =========================
    # 🧭 EXPLORE / MOVE
    # =========================
    return explore_logic(state, me, visible_agents)

def get_best_weapon(inventory):
    weapons = [
        i for i in inventory
        if i.get("category") == "weapon"
    ]

    if not weapons:
        return None

    return max(weapons, key=lambda x: x.get("atkBonus", 0))

def already_have_weapon(inventory, weapon_name):
    return any(
        i.get("category") == "weapon" and i.get("name") == weapon_name
        for i in inventory
    )

def send_finish_telegram(result, game_id, kills, deaths):
    global GAME_FINISHED_SENT

    if GAME_FINISHED_SENT:
        return

    GAME_FINISHED_SENT = True

    try:
        text = f"""🏁 GAME FINISHED
👤 Agent: {AGENT_NAME}
🎮 Game: {game_id}
🏆 Result: {result}
⚔ Kills: {kills}
💀 Deaths: {deaths}"""

        send_telegram(text)

    except Exception as e:
        log(f"⚠ TG FINISH ERROR: {e}")

# LAST_CURSE_RESULT = None

# def check_curse_result(state):
#     global LAST_CURSE_RESULT

#     for log in state.get("recentLogs", []):
#         msg = (log.get("message") or "").lower()

#         if "curse activated" in msg and "wrong answer" in msg:
#             if LAST_CURSE_RESULT != "wrong":
#                 LAST_CURSE_RESULT = "wrong"
#                 return "wrong"

#         if "curse lifted" in msg or "correct answer" in msg:
#             if LAST_CURSE_RESULT != "correct":
#                 LAST_CURSE_RESULT = "correct"
#                 return "correct"

#     return None
# ---------------- MAIN LOOP ----------------
def agent_loop(game_id, agent_id):
    global LAST_ATTACK_TARGET, LAST_KILL_REGION
    global last_target_id
    global last_state_update
    global LAST_STATE
    global PREV_VISIBLE_AGENTS
    def parse_server_time(timestr):
                if not timestr:
                    return None
                return datetime.fromisoformat(timestr.replace("Z", "+00:00")).timestamp() 

    last_turn = None
    last_turn_action_sent = None  # Track apakah action sudah dikirim untuk turn ini
    last_turn_time = time.time()

    while True:
        try:
            current_agents = {}

            if time.time() - last_state_update > STATE_TIMEOUT:

                log("⚠ 60s tanpa update state → fallback action")

                if LAST_STATE and LAST_STATE.get("canAct"):

                    try:
                        action = choose_action(LAST_STATE)

                        if action:
                            safe_post(
                                f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                                {"action": action}
                            )

                            last_turn_action_sent = last_turn

                            log(f"⚡ FALLBACK ACTION → {action['type']}")

                    except Exception as e:
                        log(f"⚠ fallback error: {e}")

                last_state_update = time.time()
                time.sleep(1.5)
                continue
            
            # 1️⃣ Cek game status
            r_game = safe_get(f"{BASE_URL}/games/{game_id}")

            if not r_game:
                continue

            if r_game.status_code != 200:
                time.sleep(0.3)
                continue

            game_data = r_game.json().get("data", {})
            game_status = game_data.get("status")

            if game_status in ["finished","cancelled"]:

                log("🏁 Game selesai (ambil data server)")

                game_data = r_game.json().get("data", {})

                agents = game_data.get("agents") or []
                my_data = next((a for a in agents if a.get("id") == agent_id), {})

                kills = GAME_STATS["kills"]
                deaths = GAME_STATS["deaths"]

                result_data = game_data.get("result", {})
                result = "WIN" if result_data.get("isWinner") else "LOSS"

                send_finish_telegram(result, game_id, kills, deaths)

                REGION_MEMORY.clear()
                last_regions.clear()
                last_target_id = None
                break

            if game_status != "running":
                log(f"⏳ Game status: {game_status}")
                time.sleep(1)
                continue

            # 2️⃣ Ambil STATE dulu
            r_state = safe_get(
                f"{BASE_URL}/games/{game_id}/agents/{agent_id}/state"
            )

            # update state lama
            PREV_VISIBLE_AGENTS = current_agents

            if not r_state:
                continue
            
            if r_state.status_code == 401:
                log("🔑 API key invalid / session expired → reconnect")
                return

            if r_state.status_code == 404:
                log("⚠ Agent tidak ditemukan → reconnect")
                return

            if r_state.status_code != 200:
                time.sleep(0.1)
                continue

            state = r_state.json().get("data")

            if not state:
                continue
            # result = check_curse_result(state)

            # if result == "wrong":
            #     log("❌ CURSE ANSWER SALAH")
            # elif result == "correct":
            #     log("✅ CURSE ANSWER BENAR")

            current_agents = {
                a["id"]: a for a in state.get("visibleAgents", [])
            }
            
            me = state.get("self", {})
            
            if state:
                LAST_STATE = state

            # reset timer karena state berhasil diterima
            last_state_update = time.time()

             # cek agent mati
            if state.get("self", {}).get("hp", 0) <= 0:
                GAME_STATS["deaths"] += 1
                log("💀 Agent mati.")
                #send_finish_telegram("LOSS", game_id, 0, 1)
                REGION_MEMORY.clear()
                last_regions.clear()
                last_target_id = None
                log("🗑️ Memory, histori last_regions, dan last_target dibersihkan karena agent mati.")
                break

            # =========================
            # INSTANT PICKUP CHECK
            # =========================
            me = state.get("self", {})
            inventory = me.get("inventory", [])
            current_region_id = state.get("currentRegion", {}).get("id")

            visible_items = [
                i.get("item") or i for i in state.get("visibleItems", [])
                if i.get("regionId") == current_region_id
            ]

            # =========================
            # 💰 PRIORITY: CURRENCY (ALWAYS PICK)
            # =========================
            for item in visible_items:
                is_currency = (
                    item.get("type") == "currency" or
                    item.get("category") == "currency"
                )

                if is_currency:
                    res = safe_post(
                        f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                        {"action": {"type": "pickup", "itemId": item.get("id")}}
                    )

                    if res and res.status_code in [200, 201, 202]:
                        log(f"💰 PICKUP MOLTZ → {item.get('name')}")
                        continue

            inventory_count = len(inventory)

            for item in visible_items:
                        
                if inventory_count >= 10:
                    #log("Inventory penuh")
                    break

                name = (item.get("name") or "").lower()
                desc = (item.get("description") or "").lower()

                # ❌ SKIP ITEM
                if name in SKIP_ITEMS or desc in SKIP_ITEMS:
                    #log(f"🚫 SKIP ITEM → {name}")
                    continue

                name = item.get("name","")
                category = item.get("category","")

                # skip duplicate weapon
                if category == "weapon" and already_have_weapon(inventory, name):
                    #log(f"Skip duplicate weapon {name}")
                    continue

                # skip duplicate utility
                if category == "utility" and any(i.get("name")==name for i in inventory):
                    #log(f"Skip duplicate utility {name}")
                    continue

                res_pick = safe_post(
                    f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                    {"action":{"type":"pickup","itemId":item.get("id")}}
                )

                if res_pick and res_pick.status_code in [200,201,202]:
                    log(f"PICKUP → {name}")
                    time.sleep(0.2)
                    me = state.get("self", {})
                    inventory = me.get("inventory", [])

            # 🔹 UPDATE MEMORY REGION
            update_region_memory(state)

            # 🔹 UPDATE MAP MEMORY
            update_map_memory(state)

            me = state.get("self", {})

            # 3️⃣ Ambil TURN dari recentLogs
            current_turn = state.get("turn")
            for log_item in state.get("recentLogs", []):
                if log_item.get("type") == "system" and "Turn" in log_item.get("message", ""):
                    msg = log_item["message"]
                    parts = msg.split("Turn ")
                    if len(parts) > 1:
                        current_turn = int(parts[1].split(" ")[0])

            if current_turn is None:
                time.sleep(0.3)
                continue

            # 4️⃣ Kalau action sudah terkirim untuk turn ini → tunggu
            if last_turn_action_sent == current_turn:
                pass
               
            # =========================
            # TURN STUCK FALLBACK
            # =========================
                if time.time() - last_turn_time > 75:

                    if last_turn_action_sent == current_turn:
                        continue
                    log("⚠ TURN STUCK >75s → FALLBACK")

                    if LAST_STATE:
                        try:
                            action = choose_action(LAST_STATE)
                            log(f"📍 CURRENT: {current_region_id}")
                            log(f"➡️ TARGET: {action}")
                            if action:
                                safe_post(
                                    f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                                    {"action": action}
                                )

                                log(f"⚡ FALLBACK ACTION → {action['type']}")

                                last_turn_time = time.time()

                        except Exception as e:
                            log(f"fallback error: {e}")

            # 5️⃣ Kalau turn baru → reset last_turn_action_sent
            if current_turn != last_turn:
                last_turn = current_turn
                last_turn_action_sent = None   # 🔥 FIX INI PENTING
                last_turn_time = time.time()
                log(f"🔥 TURN {current_turn} EXECUTE")

                # =========================
                # 🧠 CURSE EDGE DETECTION (ANTI SPAM)
                # =========================
                curse = detect_curse(state, me.get("id"))

                if curse:
                    now = time.time()

                    global LAST_CURSE_ID
                    global LAST_CURSE_TIME
                    LAST_CURSE_TIME = globals().get("LAST_CURSE_TIME", 0)
                    CURSE_COOLDOWN = globals().get("CURSE_COOLDOWN", 3)

                    # 🔥 hanya proses kalau curse BARU
                    if curse["id"] != LAST_CURSE_ID and now - LAST_CURSE_TIME >= CURSE_COOLDOWN:
                        LAST_CURSE_TIME = now

                        globals()["LAST_CURSE_TIME"] = now
                        globals()["LAST_CURSE_ID"] = curse["id"]

                        log(f"💀 CURSE RECEIVED → {curse['question']}")

                        answer = solve_curse(curse["question"])

                        safe_post(
                            
                            f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                            {
                                "action": {
                                    "type": "whisper",
                                    "targetId": curse["senderId"],
                                    "message": answer
                                }
                            }
                        )
                        log(f"✅ CURSE ANSWER SENT → {answer}")
                        # 🚨 PENTING: STOP LOOP STEP SELANJUTNYA

                # =========================
                # AUTO EQUIP TERBAIK (WAITING MODE)
                # =========================
                inventory = me.get("inventory", [])
                equipped_weapon = current_weapon(me)
                best_weapon = get_best_weapon(inventory)

                if best_weapon:
                    current_bonus = equipped_weapon.get("atkBonus", 0) if equipped_weapon else 0
                    best_bonus = best_weapon.get("atkBonus", 0)

                    if not equipped_weapon or best_bonus > current_bonus:

                        equip_payload = {
                            "action": {
                                "type": "equip",
                                "itemId": best_weapon["id"]
                            }
                        }

                        res_equip = session.post(
                            f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                            json=equip_payload,
                            timeout=10
                        )

                        if res_equip.status_code in [200, 201, 202]:
                            log(f"🗡️ WAITING EQUIP → {best_weapon['name']}")
                            time.sleep(0.3)      

            # cek apakah agent boleh bertindak
            can_act = state.get("canAct")

            # kalau field tidak ada, anggap boleh act
            if can_act is False:
                log("⏳ Cannot act yet")
                time.sleep(0.4)
                continue
            if last_turn_action_sent == current_turn:
                time.sleep(0.2)
                continue
            main_action = choose_action(state)

            if main_action:
                res_action = safe_post(
                    f"{BASE_URL}/games/{game_id}/agents/{agent_id}/action",
                    {"action": main_action}
                )
                if not main_action or "type" not in main_action:
                    continue

                if res_action:

                    try:
                        data = res_action.json()
                        
                        if data.get("success"):
                            log(f"⚡ {main_action['type'].upper()} SUCCESS")

                            # ✅ ONLY COUNT KILL IF SERVER CONFIRMS DEATH
                            if main_action["type"] == "attack":                                    

                                    for aid, prev in PREV_VISIBLE_AGENTS.items():
                                        if aid not in current_agents:
                                            if LAST_ATTACK_TARGET and LAST_ATTACK_TARGET.get("id") == aid:
                                                GAME_STATS["kills"] += 1

                            last_turn_action_sent = current_turn

                        else:
                            log(f"❌ ACTION FAILED → {data.get('error')}")

                    except:
                        log("⚠ Invalid response from server")
                    time.sleep(random.uniform(0.2,0.4))

            # cek agent mati
            if state.get("self", {}).get("hp", 0) <= 0:
                log("💀 Agent mati.")
                #send_finish_telegram("LOSS", game_id, 0, 1)
                REGION_MEMORY.clear()
                last_regions.clear()
                last_target_id = None
                log("🗑️ Memory, histori last_regions, dan last_target dibersihkan karena agent mati.")              
                break

        except requests.exceptions.ConnectionError:
            log("🌐 Connection lost → reconnect")
            return

        except Exception as e:
            log(f"💥 Unexpected error: {e}")
            time.sleep(2)
            continue

def main():
    while True:
        try:
            game_id, agent_id = start_session()
            print_header("Molty Royale", game_id, agent_id)
            agent_loop(game_id, agent_id)
            time.sleep(1)

        except Exception as e:
            log(f"💥 Error sistem: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
