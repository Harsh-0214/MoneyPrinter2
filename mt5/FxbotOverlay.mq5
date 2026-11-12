//+------------------------------------------------------------------+
//| FxbotOverlay.mq5                                                  |
//| Draws what the MoneyPrinter2 Python bots currently "see":         |
//| Asian range box, sweep / BOS / breakout lines, trend channels,    |
//| time lines (windows, exits, news), open-trade entry/stop/target   |
//| and a status panel. Every bot trading this chart's symbol writes      |
//|   <Common>\Files\fxbot_<SYMBOL>.txt         (main strategy)       |
//|   <Common>\Files\fxbot_<SYMBOL>_<sleeve>.txt (extra strategies)   |
//| after each candle; this indicator re-reads them every 2 seconds.  |
//| Display only - it never places or changes orders.                 |
//+------------------------------------------------------------------+
#property copyright "MoneyPrinter2"
#property version   "1.30"
#property indicator_chart_window
#property indicator_plots 0

input int  RefreshSeconds = 2;
input int  FontSize       = 9;
input bool PrintEvents    = true;   // print bot events (orders, fills, closes, skips, daily summary) to the Experts tab
input bool PrintStatus    = true;   // also print "what the bot sees" status changes

ulong g_events_pos  = 0;
bool  g_events_init = false;

const string PFX = "fxbot_";

int OnInit()
{
   EventSetTimer(MathMax(1, RefreshSeconds));
   Redraw();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
   Comment("");
}

int OnCalculate(const int rates_total, const int prev_calculated, const int begin,
                const double &price[])
{
   return(rates_total);
}

void OnTimer() { Redraw(); PrintNewEvents(); }

// New lines the bot appended to <Common>\Files\fxbot_events_<SYMBOL>.txt -> Experts tab
void PrintNewEvents()
{
   if(!PrintEvents) return;
   int h = FileOpen("fxbot_events_" + _Symbol + ".txt", FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON |
                    FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return;
   ulong size = FileSize(h);
   if(!g_events_init)                      // start at the end: only print what happens from now on
   {
      g_events_pos = size;
      g_events_init = true;
      FileClose(h);
      Print("fxbot: printing bot events for ", _Symbol, " here (orders, fills, closes, skips, daily summary)");
      return;
   }
   if(size < g_events_pos) g_events_pos = 0;   // the bot trimmed the file
   FileSeek(h, (long)g_events_pos, SEEK_SET);
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      int bar = StringFind(line, "|");
      if(bar <= 0) continue;
      string label = StringSubstr(line, 0, bar);
      if(label == "STATUS" && !PrintStatus) continue;
      Print("fxbot ", _Symbol, " ", label, ": ", StringSubstr(line, bar + 1));
   }
   g_events_pos = FileTell(h);
   FileClose(h);
}

color ParseColor(string rgb)
{
   string p[];
   if(StringSplit(rgb, ',', p) != 3) return(clrWhite);
   return((color)(StringToInteger(p[0]) | (StringToInteger(p[1]) << 8) | (StringToInteger(p[2]) << 16)));
}

ENUM_LINE_STYLE ParseStyle(string s)
{
   if(s == "dash") return(STYLE_DASH);
   if(s == "dot")  return(STYLE_DOT);
   return(STYLE_SOLID);
}

// Draw one bot file; returns its status text. n = running object counter.
string DrawFile(string fname, int &n)
{
   int h = FileOpen(fname, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON |
                           FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return("");
   string status = "";
   datetime now = TimeCurrent();
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) == 0) continue;
      string f[];
      int k = StringSplit(line, '|', f);
      if(k < 2) continue;
      if(f[0] == "STATUS")
         status += f[1] + "\n";
      else if(f[0] == "HLINE" && k >= 5)
      {
         string nm = PFX + "h" + IntegerToString(n++);
         double pr = StringToDouble(f[1]);
         ObjectCreate(0, nm, OBJ_HLINE, 0, 0, pr);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, ParseColor(f[2]));
         ObjectSetInteger(0, nm, OBJPROP_STYLE, ParseStyle(f[3]));
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP, f[4] + " " + DoubleToString(pr, _Digits));
         string tl = nm + "t";
         ObjectCreate(0, tl, OBJ_TEXT, 0, now, pr);
         ObjectSetString(0, tl, OBJPROP_TEXT, "  " + f[4]);
         ObjectSetInteger(0, tl, OBJPROP_COLOR, ParseColor(f[2]));
         ObjectSetInteger(0, tl, OBJPROP_FONTSIZE, FontSize);
         ObjectSetInteger(0, tl, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0, tl, OBJPROP_SELECTABLE, false);
      }
      else if(f[0] == "VLINE" && k >= 5)          // a moment in time: window opens/closes, exits, news
      {
         string nm = PFX + "v" + IntegerToString(n++);
         datetime t = (datetime)StringToInteger(f[1]);
         ObjectCreate(0, nm, OBJ_VLINE, 0, t, 0);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, ParseColor(f[2]));
         ObjectSetInteger(0, nm, OBJPROP_STYLE, ParseStyle(f[3]));
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP, f[4]);
         string tl = nm + "t";
         double top = ChartGetDouble(0, CHART_PRICE_MAX);
         ObjectCreate(0, tl, OBJ_TEXT, 0, t, top);
         ObjectSetString(0, tl, OBJPROP_TEXT, " " + f[4]);
         ObjectSetInteger(0, tl, OBJPROP_COLOR, ParseColor(f[2]));
         ObjectSetInteger(0, tl, OBJPROP_FONTSIZE, FontSize - 1);
         ObjectSetDouble(0, tl, OBJPROP_ANGLE, -90.0);
         ObjectSetInteger(0, tl, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
         ObjectSetInteger(0, tl, OBJPROP_SELECTABLE, false);
      }
      else if(f[0] == "TLINE" && k >= 6)          // a level that starts at a time (open trade levels)
      {
         string nm = PFX + "l" + IntegerToString(n++);
         datetime t1 = (datetime)StringToInteger(f[1]);
         double pr = StringToDouble(f[2]);
         ObjectCreate(0, nm, OBJ_TREND, 0, t1, pr, now, pr);
         ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, true);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, ParseColor(f[3]));
         ObjectSetInteger(0, nm, OBJPROP_STYLE, ParseStyle(f[4]));
         ObjectSetInteger(0, nm, OBJPROP_WIDTH, f[4] == "solid" ? 2 : 1);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP, f[5] + " " + DoubleToString(pr, _Digits));
         string tl = nm + "t";
         ObjectCreate(0, tl, OBJ_TEXT, 0, now, pr);
         ObjectSetString(0, tl, OBJPROP_TEXT, "  " + f[5] + " " + DoubleToString(pr, _Digits));
         ObjectSetInteger(0, tl, OBJPROP_COLOR, ParseColor(f[3]));
         ObjectSetInteger(0, tl, OBJPROP_FONTSIZE, FontSize);
         ObjectSetInteger(0, tl, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0, tl, OBJPROP_SELECTABLE, false);
      }
      else if(f[0] == "BOX" && k >= 7)
      {
         string nm = PFX + "b" + IntegerToString(n++);
         datetime t1 = (datetime)StringToInteger(f[1]);
         datetime t2 = (datetime)StringToInteger(f[3]);
         ObjectCreate(0, nm, OBJ_RECTANGLE, 0, t1, StringToDouble(f[2]), t2, StringToDouble(f[4]));
         ObjectSetInteger(0, nm, OBJPROP_COLOR, ParseColor(f[5]));
         ObjectSetInteger(0, nm, OBJPROP_FILL, true);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP, f[6]);
      }
   }
   FileClose(h);
   return(status);
}

void Redraw()
{
   ObjectsDeleteAll(0, PFX);
   int n = 0;
   string status = "";
   string found;
   // main bot file first, then any sleeve files (fxbot_<SYMBOL>_<sleeve>.txt)
   status += DrawFile("fxbot_" + _Symbol + ".txt", n);
   long hf = FileFindFirst("fxbot_" + _Symbol + "_*.txt", found, FILE_COMMON);
   if(hf != INVALID_HANDLE)
   {
      do
      {
         status += "\n" + DrawFile(found, n);
      }
      while(FileFindNext(hf, found));
      FileFindClose(hf);
   }
   if(StringLen(status) == 0)
      status = "fxbot overlay: no data for " + _Symbol + " yet (is a bot running for this market?)";
   Comment(status);
   ChartRedraw();
}
