# =========================
# 🌸 CLEAN BACKGROUND
# =========================
def clean_bg(text):
    text = re.sub(
        r"^(note:|context:|background:|scene:|setting:)\s*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    text = re.sub(
        r"\b(in your answer|in your reply)\b.*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

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

    # universal base (aman)
    if style in ["mention", "include", "reference", "weave", "default"]:
        return f"{answer}. {bg}"

    elif style == "acknowledge":
        return f"{answer}. {bg}"

    elif style == "respond":
        return f"{answer}. {bg}"

    return f"{answer}. {bg}"


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

    math_match = re.search(r'(\d+\s*[\+\-\*/]\s*\d+)', expr)
    if math_match:
        try:
            result = eval(math_match.group(1))
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            return str(result)
        except:
            pass

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
