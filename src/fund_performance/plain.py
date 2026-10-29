""" Plain-English reasons for the Value and Fees ratings, written by code from the figures the scorecard used
(`Pillar.values`). Shared by the findings, the report's ratings table and the web page, so all three say the same """


def value_sentence(v: dict) -> str:
    """ e.g. "the peer, Sample Tracker B, returned 1.17 pp a year less than the fund over 5 years, both after fees" """
    gap = v["gap_pp"]
    if gap == 0:
        how = "the same as the fund"
    else:
        how = f"{abs(gap):.2f} pp a year {'more' if gap > 0 else 'less'} than the fund"
    return f"the peer, {v['peer']}, returned {how} over {v['years']} years, both after fees"


def fees_sentence(v: dict) -> str:
    """ e.g. "the fund's 0.10% yearly ongoing charge (OCF) is 0.05 pp above the peer's 0.05%" """
    gap = v["gap_pp"]
    where = "the same as" if gap == 0 else f"{abs(gap):.2f} pp {'above' if gap > 0 else 'below'}"
    return f"the fund's {v['fund_ocf']:.2f}% yearly ongoing charge (OCF) is {where} the peer's {v['peer_ocf']:.2f}%"


SENTENCES = {"Value for investors": value_sentence, "Fees": fees_sentence}


def plain_peer_reason(name: str, values: dict) -> str | None:
    """ The sentence for Value or Fees when a peer was used, or None """
    make = SENTENCES.get(name)
    return make(values) if make and values else None
