"""Build docs/MoneyPrinter2_Guide.pdf  ->  python docs/build_guide.py

Plain-English guide to how the bot works, how to run it, and what the research
found. Numbers are from the Nov 2026 backtests (run_validate.py / run_arsenal.py).
Text sticks to WinAnsi characters (no unicode arrows/minus signs) so the built-in
PDF fonts render everything.
"""
import os

from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MoneyPrinter2_Guide.pdf")

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#52606d")
ACCENT = colors.HexColor("#1f6feb")
GREEN = colors.HexColor("#2e8b57")
RED = colors.HexColor("#d64545")
GOLD = colors.HexColor("#c99a06")
LIGHT = colors.HexColor("#eef2f7")
RULE = colors.HexColor("#cbd2d9")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=18,
                    textColor=INK, spaceBefore=6, spaceAfter=10)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13,
                    textColor=ACCENT, spaceBefore=12, spaceAfter=6)
BODY = ParagraphStyle("B", parent=ss["BodyText"], fontName="Helvetica", fontSize=10,
                      leading=14.5, textColor=INK, spaceAfter=6)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=8.5, leading=12, textColor=MUTED)
BUL = ParagraphStyle("BL", parent=BODY, leftIndent=14, bulletIndent=4, spaceAfter=3)
MONO = ParagraphStyle("M", parent=BODY, fontName="Courier", fontSize=8.8, leading=12,
                      backColor=LIGHT, borderPadding=6, leftIndent=6, rightIndent=6, spaceAfter=10)
CELL = ParagraphStyle("C", parent=BODY, fontSize=8.8, leading=11.5, spaceAfter=0)
CELLB = ParagraphStyle("CB", parent=CELL, fontName="Helvetica-Bold")
CENTER = ParagraphStyle("CT", parent=BODY, alignment=TA_CENTER)


def P(t, s=BODY):
    return Paragraph(t, s)


def bullets(items):
    return [Paragraph(i, BUL, bulletText="\u2022") for i in items]


def code(text):
    return Paragraph(text.replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;"), MONO)


def table(rows, widths, header=True, zebra=True):
    data = [[Paragraph(str(c), CELLB if (header and r == 0) else CELL) for c in row]
            for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, RULE),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), LIGHT))
    if zebra:
        for r in range(2, len(rows), 2):
            st.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f8fafc")))
    t.setStyle(TableStyle(st))
    return t


def callout(text, color=ACCENT):
    t = Table([[Paragraph(text, BODY)]], colWidths=[6.5 * inch])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, color),
                           ("LINEBEFORE", (0, 0), (0, -1), 4, color),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fc")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


# ----------------------------------------------------------------------------- diagrams
def _candles(d, x0, y_of, closes, w=7, gap=3, color_up=GREEN, color_dn=RED):
    x = x0
    prev = closes[0]
    for c in closes[1:]:
        hi, lo = max(prev, c) + 1.2, min(prev, c) - 1.2
        col = color_up if c >= prev else color_dn
        d.add(Line(x + w / 2, y_of(lo), x + w / 2, y_of(hi), strokeColor=col, strokeWidth=0.8))
        d.add(Rect(x, y_of(min(prev, c)), w, max(abs(y_of(c) - y_of(prev)), 0.8),
                   fillColor=col, strokeColor=col))
        prev = c
        x += w + gap
    return x


def sweep_diagram():
    d = Drawing(460, 130)
    y = lambda v: -36 + v * 1.5           # price units -> pts
    d.add(Rect(10, y(40), 170, y(80) - y(40), fillColor=colors.HexColor("#dbe9fb"),
               strokeColor=ACCENT, strokeWidth=0.6))
    d.add(String(14, y(82), "Asian range 00:00-08:00 London", fontSize=7.5, fillColor=ACCENT))
    d.add(Line(10, y(80), 450, y(80), strokeColor=ACCENT, strokeDashArray=[3, 2], strokeWidth=0.7))
    d.add(Line(10, y(40), 450, y(40), strokeColor=ACCENT, strokeDashArray=[3, 2], strokeWidth=0.7))
    asia = [60, 62, 58, 66, 61, 70, 64, 72, 66, 60, 55, 63, 68, 74, 70, 66, 62]
    x = _candles(d, 14, y, asia)
    post = [66, 74, 79, 86, 90, 84, 78, 72, 64, 58, 52, 47, 44]
    _candles(d, x + 6, y, post)
    d.add(String(232, y(97), "SWEEP: spikes past the high, runs stops", fontSize=7.5, fillColor=RED))
    d.add(Line(205, y(70), 450, y(70), strokeColor=GOLD, strokeWidth=1, strokeDashArray=[4, 2]))
    d.add(String(352, y(72), "BOS: close below swing low -> SELL", fontSize=7.5, fillColor=GOLD))
    d.add(Line(205, y(92), 450, y(92), strokeColor=RED, strokeWidth=0.8))
    d.add(String(390, y(93.5), "stop", fontSize=7.5, fillColor=RED))
    d.add(String(360, y(36), "target = range low", fontSize=7.5, fillColor=GREEN))
    return d


def breakout_diagram():
    d = Drawing(460, 112)
    y = lambda v: -42 + v * 1.4
    d.add(Rect(10, y(40), 170, y(70) - y(40), fillColor=colors.HexColor("#dbe9fb"),
               strokeColor=ACCENT, strokeWidth=0.6))
    d.add(String(14, y(72), "Asian range (22-80 pips)", fontSize=7.5, fillColor=ACCENT))
    asia = [55, 58, 52, 60, 54, 63, 57, 50, 56, 62, 59, 53, 58, 61, 55, 60, 57]
    x = _candles(d, 14, y, asia)
    post = [60, 68, 74, 71, 76, 79, 77, 82, 85, 83, 88, 92, 95]
    _candles(d, x + 6, y, post)
    d.add(Line(10, y(70), 450, y(70), strokeColor=GREEN, strokeDashArray=[3, 2]))
    d.add(String(196, y(64), "08:05 closes above the range...", fontSize=7.5, fillColor=MUTED))
    d.add(String(275, y(99), "...still above at 10:30 -> BUY (with the daily trend)", fontSize=7.5,
                 fillColor=GREEN))
    d.add(Line(10, y(40), 450, y(40), strokeColor=RED, strokeWidth=0.8))
    d.add(String(380, y(42), "stop = range low", fontSize=7.5, fillColor=RED))
    return d


def gold_diagram():
    d = Drawing(460, 150)
    y = lambda v: -12 + v * 1.3
    import math
    pts = []
    for i in range(110):
        v = 40 + 10 * math.sin(i / 6.0) + (0 if i < 60 else (i - 60) * 1.1)
        pts.append((10 + i * 4, y(v)))
    d.add(PolyLine([c for p in pts for c in p], strokeColor=INK, strokeWidth=1))
    d.add(Line(10, y(51), 250, y(51), strokeColor=GREEN, strokeDashArray=[4, 2]))
    d.add(String(12, y(53), "55-day high", fontSize=7.5, fillColor=GREEN))
    d.add(Polygon([250, y(55), 245, y(47), 255, y(47)], fillColor=GREEN, strokeColor=GREEN))
    d.add(String(232, y(43), "BUY", fontSize=7.5, fillColor=GREEN))
    trail = []
    best = 0
    for i, (px, py) in enumerate(pts):
        if px >= 250:
            best = max(best, py)
            trail.append((px, best - 30))
    d.add(PolyLine([c for p in trail for c in p], strokeColor=RED, strokeWidth=0.9,
                   strokeDashArray=[2, 2]))
    d.add(String(12, 136, "red dotted line = trailing stop, 2x the daily range behind the best price",
                 fontSize=7.5, fillColor=RED))
    d.add(String(300, y(108), "hold for weeks while the trend lasts", fontSize=7.5, fillColor=MUTED))
    return d


# ----------------------------------------------------------------------------- page chrome
def on_page(c, doc):
    c.saveState()
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(0.75 * inch, 0.5 * inch, "MoneyPrinter2 - How everything works  |  Nov 2026")
    c.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
    c.restoreState()


def on_first(c, doc):
    c.saveState()
    c.setFillColor(ACCENT)
    c.rect(0, 10.2 * inch, 8.5 * inch, 0.8 * inch, fill=1, stroke=0)
    c.restoreState()
    on_page(c, doc)


def build():
    s = []
    W = 6.5 * inch

    # ---------------------------------------------------------------- cover / at a glance
    s += [Spacer(1, 0.55 * inch),
          P("MoneyPrinter2", ParagraphStyle("T", parent=H1, fontSize=30, leading=34)),
          P("How the trading bot works, how to run it, and what the research found",
            ParagraphStyle("ST", parent=BODY, fontSize=12.5, textColor=MUTED)),
          Spacer(1, 10)]
    s.append(callout(
        "<b>In one paragraph.</b> Three small programs (\"bots\"), one per market, watch EURUSD, "
        "GBPUSD and gold on your MetaTrader 5 demo account and trade on their own. Each bot runs "
        "several strategies and trades whichever one has a setup; two strategies on the same market "
        "can even hold trades at the same time. EURUSD and "
        "GBPUSD are traded around the London open (the <i>Sweep</i> and the <i>Breakout</i>) and "
        "with a daily <i>swing pullback</i>. Gold is traded with two daily trend-following systems "
        "(slow and fast). Each trade risks 1% of a $50,000 sizing base (about $500 CAD), and all "
        "bots together never risk more than 5% at once. Over 2021-2025 the combination "
        "backtested at <b>+69% total (about 11% a year), with a worst drop of -9.7% and no "
        "losing year</b>. That is a backtest, not a promise. The demo period is there to check it."))
    s.append(Spacer(1, 12))
    s.append(P("The three bots and their strategies", H2))
    s.append(table([
        ["Market bot", "Strategy", "Chart", "Trades / yr", "When it trades (Toronto time)"],
        ["EURUSD", "London Sweep + London Breakout, daily trend filter", "5 min", "~27",
         "3:00-6:00 AM entries, closed by 11:00 AM"],
        ["", "Daily swing pullback (buy dips in uptrends, 100-day trend)", "1 hour", "~10",
         "Decides daily (7 PM), holds 1-10 days"],
        ["GBPUSD", "London Sweep + London Breakout (cross-checks EURUSD)", "5 min", "~38",
         "3:00-6:00 AM entries, closed by 11:00 AM"],
        ["", "Daily swing pullback, 200-day trend", "1 hour", "~11", "Decides daily, holds 1-10 days"],
        ["XAUUSD", "Gold trend following, 55-day, buy-only", "1 hour", "~5",
         "Decides daily (7 PM), holds weeks"],
        ["", "Gold trend following, 20-day, buy-only", "1 hour", "~6", "Same"],
    ], [1.05 * inch, 2.15 * inch, 0.55 * inch, 0.7 * inch, 2.05 * inch]))
    s.append(Spacer(1, 10))
    s.append(P("Backtest results, 2021-2025 (1% risk per trade, your account's real costs)", H2))
    s.append(table([
        ["", "5-year return", "Per year", "Worst drop", "Profit factor", "Trades"],
        ["EURUSD stack", "+9.3%", "1.8%", "-11.1%", "1.25", "135"],
        ["GBPUSD stack", "+21.0%", "3.9%", "-8.5%", "1.32", "192"],
        ["EURUSD pullback", "+2.6%", "0.5%", "-2.9%", "1.40", "52"],
        ["GBPUSD pullback", "+3.6%", "0.7%", "-1.3%", "1.87", "54"],
        ["Gold trend (55-day)", "+14.9%", "2.8%", "-4.3%", "3.55", "24"],
        ["Gold trend fast (20-day)", "+18.1%", "3.4%", "-3.6%", "2.94", "32"],
        ["<b>All strategies together</b>", "<b>+69.4%</b>", "<b>11.2%</b>", "<b>-9.7%</b>", "<b>1.54</b>", "<b>489</b>"],
    ], [1.6 * inch, 1.0 * inch, 0.8 * inch, 1.0 * inch, 1.0 * inch, 1.1 * inch]))
    s.append(Spacer(1, 6))
    s.append(table([
        ["Year", "2021", "2022", "2023", "2024", "2025"],
        ["All strategies", "+12.6%", "+13.1%", "+0.2%", "+4.3%", "+27.3%"],
    ], [1.6 * inch] + [0.98 * inch] * 5))
    s.append(P("The four newer strategies were chosen from many candidates, so some of their "
               "backtest strength is luck. Expect live results to be lower.", SMALL))
    s.append(P("Profit factor = money won / money lost. Above 1.0 makes money; 1.3+ is solid "
               "for this kind of strategy. \"Worst drop\" is the largest fall from a peak.", SMALL))

    # ---------------------------------------------------------------- the day
    s.append(PageBreak())
    s.append(P("1. A day in the life of the bot", H1))
    s.append(P("All strategy times are London time, because that's when these markets are most "
               "active. Toronto is 5 hours behind London for most of the year. For a couple of "
               "weeks in March and in late Oct/Nov the gap is 4 hours, because the UK and North "
               "America change their clocks on different dates."))
    s.append(table([
        ["London", "Toronto", "What happens"],
        ["00:00-08:00", "7 PM-3 AM", "EURUSD/GBPUSD bots record the overnight (\"Asian\") high and low: the <b>range</b>. "
         "The gold and pullback bots make their once-a-day decisions at 00:00 London."],
        ["08:00-10:30", "3:00-5:30 AM", "The <b>Sweep</b> watches for a fake break of the range followed by a sharp reversal."],
        ["10:30-11:00", "5:30-6:00 AM", "If no Sweep happened, the <b>Breakout</b> checks whether price broke out of the range and is still outside it."],
        ["13:30-16:00", "8:30-11:00 AM", "New York opens. This is where most of the profit on open trades is made."],
        ["16:00", "11:00 AM", "Any EURUSD/GBPUSD trade still open is closed. Gold trades are left open."],
        ["Every 5 min", "Every 5 min", "Each bot reads the newest closed candle, updates what it sees, writes its log, and redraws the chart overlay."],
    ], [0.95 * inch, 1.05 * inch, 4.5 * inch]))
    s.append(Spacer(1, 6))
    s.append(P("At most <b>one trade per pair per day</b> for EURUSD and GBPUSD. Mondays are "
               "skipped (Monday lost money in 4 of 5 years). Many days have no trade at all. "
               "That's normal: the bot only acts when its rules line up."))

    # ---------------------------------------------------------------- strategies
    s.append(P("2. The strategies", H1))
    s.append(P("2.1 London Sweep (a fake-out reversal)", H2))
    s.append(P("Big players often push price just past an obvious level (the overnight high or "
               "low) to trigger other traders' stop-losses, then reverse. The Sweep tries to "
               "catch that reversal."))
    s.append(sweep_diagram())
    s += bullets([
        "<b>Sweep:</b> between 08:00 and 10:30, price pokes 1-15 pips past the range high (or low). "
        "Further than 15 pips counts as a real move, not a fake-out.",
        "<b>Confirmation (BOS, \"break of structure\"):</b> a candle closes back through the last "
        "small swing point made before the spike. The trade is taken against the spike.",
        "<b>SMT check:</b> on EURUSD the trade is only valid if GBPUSD did <i>not</i> make the same spike "
        "(and vice versa). Two pairs disagreeing is a sign of a genuine stop hunt.",
        "<b>Stop:</b> just beyond the spike's extreme (max 25 pips). <b>Target:</b> the other side of the "
        "range, and only if that's at least 1.5 times the risk.",
        "<b>Rare but strong:</b> only ~3 trades a year per pair, averaging about +0.6R each.",
    ])
    s.append(KeepTogether([P("2.2 London Breakout (the workhorse)", H2),
                           P("When the overnight range is reasonably tight, the London open often "
                             "breaks it decisively. About 90% of FX trades come from this strategy."),
                           breakout_diagram()]))
    s += bullets([
        "<b>Range filter:</b> the overnight range must be 22-80 pips. Narrower ranges whipsaw; "
        "wider ones have usually already moved.",
        "<b>Patience:</b> it notes a break between 08:00 and 10:30 but waits until 10:30. If price "
        "is back inside the range by then, it was a false break and nothing is traded.",
        "<b>Stop:</b> the opposite side of the range (about 45 pips on average). <b>Target:</b> 2 times the risk. "
        "<b>Breakeven:</b> at +1R the stop moves to the entry price.",
        "<b>Most trades end at 16:00</b>, not at the stop or target, because the target is far away "
        "(see section 4).",
    ])
    s.append(P("2.3 The daily trend filter (looking at the bigger chart)", H2))
    s.append(P("Before any EURUSD/GBPUSD trade, the bot checks the <b>50-day average</b> of daily "
               "closing prices. Price above it: only buys are allowed. Below it: only sells. "
               "This is the bot's version of a trader checking the daily chart before trading the "
               "5-minute one. It cut trades by about 40% but roughly doubled profit per trade. "
               "Every average length from 30 to 200 days worked, so it isn't a lucky setting."))
    s.append(KeepTogether([P("2.4 Gold daily trend following", H2),
                           P("Gold tends to move in long, strong trends. This strategy ignores the "
                             "minute-to-minute noise and rides those trends."),
                           gold_diagram()]))
    s += bullets([
        "<b>Buy</b> when a daily close is higher than the highest price of the previous 55 days. "
        "Buy-only: selling gold lost money in every test.",
        "<b>Stop:</b> 2 times gold's average daily range below the entry, then it <b>trails</b> 2 times that "
        "range behind the best price reached. It only ever moves up.",
        "<b>Exit:</b> the trailing stop, or a daily close below the lowest price of the last 20 days.",
        "<b>Few trades, big wins:</b> ~5 a year, winners can be several R. Most of the backtest profit "
        "came in 2024-2025 (a strong gold rally). In sideways years it roughly breaks even.",
        "<b>Holds overnight,</b> so financing (\"swap\") applies. The backtest assumes a pessimistic "
        "-6.5% a year on the position's value.",
        "<b>Fast version (XAUUSD fast):</b> the same rules with a 20-day high to buy and a 10-day "
        "low to exit. It catches shorter gold trends the slow system misses. Both can be in a trade "
        "at the same time (2% at risk on gold).",
    ])
    s.append(P("2.5 Daily swing pullback (EURUSD pullback, GBPUSD pullback)", H2))
    s.append(P("A completely different style from the London strategies: buy a short, sharp dip "
               "inside a bigger uptrend, and sell the bounce a few days later."))
    s += bullets([
        "<b>Trend:</b> the daily close versus its 100-day average (EURUSD) or 200-day average (GBPUSD).",
        "<b>Entry:</b> in an uptrend, buy when the 2-day RSI of daily closes drops below 10 "
        "(price fell hard for 1-3 days). In a downtrend, sell when it rises above 90.",
        "<b>Exit:</b> when the daily close gets back above the 5-day average (or below it for sells), "
        "or after 10 days. There's a protective stop at 3 times the daily range.",
        "<b>Why it's here:</b> about 70% of trades win, and it makes and loses money at different "
        "times from the London strategies (correlation about 0), so it smooths the overall results. "
        "Profits are small per pair (+0.5-0.7% a year) but steady.",
    ])

    # ---------------------------------------------------------------- risk
    s.append(P("3. Money management: how big each trade is", H1))
    s.append(P("The bot doesn't pick a lot size directly. It decides <b>how much to lose if the stop "
               "is hit</b> and works the size backwards from the stop distance. A wide stop means a "
               "small position; a tight stop means a bigger one. The money at risk is the same either way."))
    s.append(code("risk per trade  = 1% x 50,000 (live.equity_cap)       = 500 CAD\n"
                  "position size   = 500 CAD / (stop distance x USD->CAD rate)\n\n"
                  "Example: GBPUSD breakout, stop 31 pips (0.0031), USD->CAD 1.42\n"
                  "         500 / (0.0031 x 1.42) = ~113,000 units = 1.13 lots"))
    s += bullets([
        "<b>Your account is in CAD,</b> while EURUSD, GBPUSD and gold make profits in USD. The bot "
        "asks MT5 for the live conversion rate (about 1.42) so the risk really is 500 CAD.",
        "<b>Daily loss limit:</b> after losing 2% (1,000 CAD) in a day, no new trades open until tomorrow.",
        "<b>Leverage cap:</b> a position can never exceed 10 times the sizing base.",
        "<b>Portfolio cap:</b> before any trade, the bot adds up what all open bot trades would lose "
        "at their stops. If that plus the new trade is over 5% (2,500 CAD), the trade is skipped "
        "(logged as RISK CAP). Trades whose stop is already at breakeven count as zero.",
        "<b>Sizing base:</b> <font face='Courier'>equity_cap: 50000</font> in config.yaml sizes trades as if the account "
        "were exactly 50,000, plus or minus the bot's own profit and loss since it started.",
        "<b>At 1% risk</b> the backtest's worst drop was about -11% (-5,500 CAD). At 0.5% risk, "
        "returns and drops both roughly halve.",
    ])

    s.append(P("4. Exits: why winners and losers look similar", H1))
    s.append(table([
        ["How EURUSD/GBPUSD trades end", "Share", "Typical result"],
        ["Closed at 16:00 London", "69%", "small, either way (average +0.26R)"],
        ["Stop loss hit", "25%", "about -0.9R"],
        ["2R target hit", "6%", "about +2R"],
    ], [3.1 * inch, 0.8 * inch, 2.6 * inch]))
    s.append(Spacer(1, 6))
    s.append(P("The Breakout's stop sits across the whole overnight range, so a 2R target needs a "
               "move most afternoons don't make. Most trades end at 16:00 wherever price is, which "
               "makes wins and losses similar in size (average win +0.79R, average loss -0.59R). "
               "The edge is being on the right side slightly more often and slightly bigger: "
               "about +0.1R per trade."))
    s.append(P("Every alternative exit was tested and did worse: closer or further targets, earlier "
               "or no breakeven, exiting at 14:00 or 15:00 (cuts profit to +3% / +19%), tighter "
               "stops (profit fell to 0%), and 9 trailing-stop versions. The profit is made during "
               "the New York open, so the trade has to stay open until 16:00. <i>R</i> = the amount "
               "risked on a trade; +2R means the trade made twice what it risked."))

    # ---------------------------------------------------------------- running it
    s.append(P("5. Running the bots", H1))
    s.append(P("5.1 Start, stop, check", H2))
    s.append(table([
        ["To...", "Do this"],
        ["Start everything", "Double-click <font face='Courier'>start_bots.bat</font>. It opens MT5 if needed, then three "
         "windows: fxbot EURUSD / GBPUSD / XAUUSD. Each market bot runs all of that market's "
         "strategies, and restarts itself 60 s after a crash."],
        ["Stop the bots", "Double-click <font face='Courier'>stop_bots.bat</font> (or close the windows). Open "
         "trades stay open, with their stop and target held at the broker."],
        ["Run one bot by hand", "<font face='Courier'>venv\\Scripts\\activate</font>, then "
         "<font face='Courier'>python run_live.py --pair EURUSD</font> (runs all EURUSD strategies)"],
        ["Watch without trading", "add <font face='Courier'>--dry-run</font> (logs what it would do, sends nothing)"],
        ["See how the demo is doing", "<font face='Courier'>python run_report.py</font>: every bot trade, P/L in CAD, "
         "R, slippage, and the backtest's expectation for comparison"],
    ], [1.6 * inch, 4.9 * inch]))
    s.append(P("A second copy of the same pair refuses to start (\"Another run_live.py is already "
               "running\"), so starting the bots twice can't double your trades."))
    s.append(P("5.2 Keeping it running 24/7", H2))
    s += bullets([
        "<b>Auto-start at login</b> (run once in PowerShell):<br/><font face='Courier' size='8'>schtasks /Create /TN \"MoneyPrinter2 bots\" "
        "/TR \"C:\\Users\\harsh\\MoneyPrinter2\\start_bots.bat\" /SC ONLOGON /RL LIMITED /F</font>",
        "<b>No sleep on power</b>: <font face='Courier' size='8'>powercfg /change standby-timeout-ac 0</font>",
        "<b>MT5 must stay open and logged in.</b> Tick \"Save password\" when logging in, and keep the "
        "<i>Algo Trading</i> button green.",
        "<b>Windows Update</b> can restart the PC overnight. Set Active Hours, or check in the morning "
        "that the three windows are back.",
    ])
    s.append(P("5.3 Seeing what the bot \"thinks\"", H2))
    s.append(P("<b>Terminal windows.</b> Each market's window explains itself in plain English, like "
               "code comments, e.g. <i># London wants to SELL GBPUSD: price broke below the overnight "
               "range and stayed there.</i> It covers startup, what each strategy is waiting for, every "
               "order, stop move, close (with P/L), skipped trades and why, and a daily summary. Add "
               "<font face='Courier'>--verbose</font> to also see the technical lines."))
    s.append(P("<b>Journal.</b> logs/journal_&lt;date&gt;.log collects the important events from all "
               "three markets in one file. The FxbotOverlay indicator also prints them in MT5's "
               "<b>Experts</b> tab."))
    s.append(P("<b>Chart overlay.</b> In MT5, open a 5-minute EURUSD., GBPUSD. or XAUUSD chart, then "
               "Navigator (Ctrl+N), Indicators, <b>FxbotOverlay</b>, and drag it onto the chart. The "
               "bot redraws it after every candle. It only draws; it never trades."))
    s.append(table([
        ["On the chart", "Meaning"],
        ["Blue box / blue lines", "the overnight range (Asian high and low)"],
        ["Grey dotted lines", "the sweep limit: past this it's a real move, not a fake-out"],
        ["Red line", "where price swept (the spike's extreme)"],
        ["Gold dashed line", "the trigger: a close past it means the bot enters"],
        ["Green dashed lines", "breakout buy and sell zones"],
        ["Silver dotted line", "the 50-day average (the daily trend)"],
        ["Gold chart: green/grey", "55-day high (buy trigger) and 20-day low (exit)"],
        ["Top-left text", "status, e.g. \"high swept -&gt; waiting for close below 1.12307 (9 bars left)\""],
    ], [1.8 * inch, 4.7 * inch]))
    s.append(P("<b>Logs</b> are in <font face='Courier'>logs\\live_&lt;PAIR&gt;_&lt;date&gt;.log</font>. The useful lines:", BODY))
    s.append(code("STATUS Sweep: trend DOWN -> sells only; high swept -> waiting for close below 1.12307\n"
                  "ORDER SELL 0.14 lots @ ~1.34283  SL=1.34595  TP=1.33644  spread=2.0 pips\n"
                  "Order filled: ticket=14427020 fill_price=1.34283 requested=1.34283\n"
                  "Stop moved to 1.34283\n"
                  "CLOSED short_break SELL ... P/L 125.99  reason=[tp 1.33644]"))

    # ---------------------------------------------------------------- research
    s.append(PageBreak())
    s.append(P("6. What was tested (and why most of it isn't used)", H1))
    s.append(P("Each idea was backtested on 5 years of 1-minute data with your account's real "
               "costs (EURUSD 1.4 pips, GBPUSD 2.0, gold $0.80), and judged year by year. A "
               "strategy that made money only in one lucky year doesn't count."))
    s.append(table([
        ["Idea", "Result", "Verdict"],
        ["London Sweep + Breakout with trend filter (EUR, GBP)", "+30% at 1% risk, PF 1.30", "<b>LIVE</b>"],
        ["Gold daily trend following, buy-only (55-day and 20-day)", "+14.9% / +18.1%, PF 3.55 / 2.94", "<b>LIVE</b>"],
        ["Daily swing pullback on EURUSD / GBPUSD", "+2.6% / +3.6%, PF 1.40 / 1.87, ~70% winners", "<b>LIVE</b>"],
        ["Volatility breakout, previous-day breakout", "lost on all three markets", "rejected"],
        ["NR7 / NR4 / inside-day breakouts", "about break-even (gold inside-day +12% but raised drawdown)", "rejected"],
        ["Same London strategies on gold or AUDUSD", "about break-even or losing", "rejected"],
        ["Opening-range breakouts (London / NY open)", "lost 27-91% in 5 years", "rejected"],
        ["Pullback scalping (RSI-2 on 5m / 15m / 1h)", "lost 21-99%, 190-780 trades/yr", "rejected"],
        ["Support/resistance lines (\"key levels\")", "all 48 versions lost money", "rejected"],
        ["London-close reversal / continuation", "both directions lost", "rejected"],
        ["Daily trend following on EURUSD / GBPUSD", "about zero, even with no swap", "rejected"],
        ["1-minute candles instead of 5", "worse (stops hit by noise)", "rejected"],
        ["Trading Mondays / longer windows / NY session sweep", "more trades, less profit", "rejected"],
    ], [3.0 * inch, 2.3 * inch, 1.2 * inch]))
    s.append(Spacer(1, 6))
    s.append(callout(
        "<b>About bots that make 4+ trades a day.</b> The fast strategies above trade that often and "
        "lose, even at the cheaper costs of a raw-spread account. Every trade pays the spread: at "
        "1.4 pips, 1,000 trades a year cost 1,400 pips before any edge. Bots advertising many "
        "trades and smooth profits are often grid/martingale systems (add to losers; they look great "
        "until one trend wipes the account) or backtests run without costs.", RED))
    s.append(P("Robustness checks on the live setup", H2))
    s += bullets([
        "<b>Not overfit to the past:</b> settings chosen on 2021-2023 (+7.5%/yr) also worked on "
        "2024-2025 (+8.5%/yr), data they were never tuned on.",
        "<b>Survives higher costs:</b> still profitable at a 2-pip spread on both pairs.",
        "<b>Stable settings:</b> nearby values of the key settings (range 20-25 pips, trend 30-200 days, "
        "gold 40-100-day channel) all made money. One setting that only worked at an exact value "
        "would be a red flag.",
        "<b>Honest weak spots:</b> EURUSD alone roughly broke even in 2024-2025. Gold's profit depends "
        "on gold trending. Gold's real overnight financing is an estimate, since the demo shows 0.",
    ])

    # ---------------------------------------------------------------- demo plan
    s.append(KeepTogether([P("7. The demo plan", H1), table([
        ["Step", "What"],
        ["Now", "Run all three bots on the demo 24/7. Don't change strategy settings during the test."],
        ["Weekly", "<font face='Courier'>python run_report.py</font>. Compare live win rate, average R and trades per week with the backtest."],
        ["~2 months (30+ trades)", "Decide: <b>matches the backtest</b>, so keep going (consider a raw-spread account or a "
         "real account at low risk). <b>Much worse</b>, so find out why (costs, execution, market change) before changing "
         "anything. <b>Unclear</b>, so keep running; small samples swing a lot."],
    ], [1.5 * inch, 5.0 * inch])]))
    s.append(P("What to expect: roughly 2 trades a week across all strategies, a gold trade every "
               "month or two, losing weeks and possibly losing months. One trade, or one "
               "week, tells you almost nothing.", SMALL))

    # ---------------------------------------------------------------- reference
    s.append(PageBreak())
    s.append(P("8. Reference", H1))
    s.append(P("Files", H2))
    s.append(table([
        ["File", "What it is"],
        ["config.yaml", "every setting: risk, costs, strategies, the three markets (pairs:), live options"],
        ["run_live.py", "the live/demo bot (one per market: --pair EURUSD | GBPUSD | XAUUSD)"],
        ["start_bots.bat / stop_bots.bat / run_forever.bat", "24/7 launchers"],
        ["run_report.py", "demo results vs backtest expectations (writes results/live_trades.csv)"],
        ["run_validate.py", "walk-forward, per-year and robustness checks of the live setup"],
        ["run_arsenal.py", "tests every strategy on every market (the research table in section 6)"],
        ["fxbot/strategies/", "the strategy rules (london_sweep, london_breakout, trend_follow, ...)"],
        ["fxbot/brokers/mt5_broker.py", "talks to MetaTrader 5 (orders, stops, CAD conversion, gold contract size)"],
        ["fxbot/brokers/sim_broker.py", "the backtest simulator (spread, slippage, swap, gaps)"],
        ["mt5/FxbotOverlay.mq5", "the chart-drawing indicator for MT5"],
        ["logs/", "one log per bot per day"],
    ], [2.35 * inch, 4.15 * inch]))
    s.append(P("Settings you might change", H2))
    s.append(table([
        ["Setting (config.yaml)", "Now", "Effect"],
        ["risk.risk_per_trade_pct", "1.0", "% of the sizing base lost if a stop is hit. Halve it to halve both returns and drawdowns."],
        ["live.equity_cap", "50000", "sizing base. null = use the real account equity."],
        ["live.max_open_risk_pct", "5.0", "most that all open bot trades together may lose at their stops"],
        ["risk.max_daily_loss_pct", "2.0", "no new trades for the day after this loss"],
        ["pairs: spread_pips", "1.4 / 2.0 / 8.0", "cost assumption for backtests (live uses the real spread)"],
        ["live.allow_live", "false", "must be true, plus --allow-live, before it will touch a real-money account"],
    ], [1.9 * inch, 1.0 * inch, 3.6 * inch]))
    s.append(P("Safety built in", H2))
    s += bullets([
        "Refuses real-money accounts unless you explicitly enable it twice (config + command flag).",
        "Every order is sent with its stop loss attached, so a crash or power cut still leaves the stop at the broker.",
        "One bot per market (lock file). Each strategy labels its trades with its own magic number: "
        "EURUSD London 12345 / pullback 12445, GBPUSD London 12346 / pullback 12446, gold 55-day "
        "12347 / 20-day 12447. Strategies only manage their own trades, never yours or each other's.",
        "Closes positions by ticket, which is required on your hedging-mode account. Without this, a close "
        "would open an opposite trade instead.",
        "Daily loss limit, leverage cap, and the CAD conversion so the risk is what it says.",
        "Spread guard: no new entry while the live spread is over 2.5 times normal (news spikes, rollover).",
        "Drawdown circuit breaker: no new trades once the account is 15% below its best level. Open "
        "trades keep their stops. Delete data/state/peak_equity.json to resume after checking why.",
        "Stall watchdog: if the market is open but MT5 stops sending candles, the bot reconnects.",
        "<b>News filter:</b> no new trades 30 minutes either side of high-impact news for that "
        "market's currencies (EURUSD: USD and EUR, GBPUSD: USD and GBP, gold: USD). The bot reads "
        "the Forex Factory weekly calendar every 4 hours and caches it. If the download fails it "
        "keeps the last copy. Open trades are not closed. Skips are logged as NEWS: skipping entry. "
        "Backtest cost: 69.4% to 69.1% over 2021-2025, same drawdown.",
    ])
    s.append(Spacer(1, 10))
    s.append(P("Nothing here is financial advice. Backtests describe the past under assumptions; "
               "live results will differ. Only trade money you can afford to lose.", SMALL))

    doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                            title="MoneyPrinter2 - How everything works", author="MoneyPrinter2")
    doc.build(s, onFirstPage=on_first, onLaterPages=on_page)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
