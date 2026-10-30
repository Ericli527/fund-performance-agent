""" Plain-English reasons for the Value and Fees ratings, written by code from the figures the scorecard used
(`Pillar.values`). Shared by the findings, the report's ratings table and the web page, so all three say the same """


def value_sentence(v: dict) -> str:
    """ e.g. "the peer, Sample Tracker B, returned 1.17 pp a year less than the fund over 5 years, both after fees",
    or with several peers "the 2 peers (A and B) returned on average ..." """
    gap = v["gap_pp"]
    if gap == 0:
        how = "the same as the fund"
    else:
        how = f"{abs(gap):.2f} pp a year {'more' if gap > 0 else 'less'} than the fund"
    names = v.get("peers") or [v["peer"]]
    who = (f"the peer, {names[0]}, returned" if len(names) == 1 else
           f"the {len(names)} peers ({', '.join(names[:-1])} and {names[-1]}) returned on average")
    return f"{who} {how} over {v['years']} years, both after fees"


def fees_sentence(v: dict) -> str:
    """ e.g. "the fund's 0.10% yearly ongoing charge (OCF) is 0.05 pp above the peer's 0.05%" """
    gap = v["gap_pp"]
    where = "the same as" if gap == 0 else f"{abs(gap):.2f} pp {'above' if gap > 0 else 'below'}"
    fees = v.get("peer_fees") or []
    if len(fees) > 1:
        each = " and ".join(f"{f:.2f}%" for f in fees)
        return (f"the fund's {v['fund_ocf']:.2f}% yearly ongoing charge (OCF) is {where} the {len(fees)} peers' "
                f"average of {v['peer_ocf']:.2f}% ({each})")
    return f"the fund's {v['fund_ocf']:.2f}% yearly ongoing charge (OCF) is {where} the peer's {v['peer_ocf']:.2f}%"


SENTENCES = {"Value for investors": value_sentence, "Fees": fees_sentence}


def plain_peer_reason(name: str, values: dict) -> str | None:
    """ The sentence for Value or Fees when a peer was used, or None """
    make = SENTENCES.get(name)
    return make(values) if make and values else None


# --- Verdict names (B3): the codes stay in facts.json and the scorecard; people see these words ---------------

VERDICT_NAMES = {"Retain": ("Satisfied", "No action needed"), "Monitor": ("Monitor", "Keep a close eye on it"),
                 "Review": ("Action needed", "Investigate and engage the manager"),
                 "Pending data check": ("Pending data check", "Resolve the data check before deciding")}


def verdict_name(code: str) -> str:
    """ "Retain" -> "Satisfied", "Review" -> "Action needed"; "Monitor (data check needed: Value)" keeps its detail """
    for key, (name, _) in VERDICT_NAMES.items():
        if code.startswith(key):
            return name + code[len(key):]
    return code


def verdict_meaning(code: str) -> str:
    return next((meaning for key, (_, meaning) in VERDICT_NAMES.items() if code.startswith(key)), "")
