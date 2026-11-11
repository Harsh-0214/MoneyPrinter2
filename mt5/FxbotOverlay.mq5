//+------------------------------------------------------------------+
//| FxbotOverlay.mq5                                                  |
//| Draws what the MoneyPrinter2 Python bots currently "see":         |
//| Asian range box, sweep / BOS / breakout lines, trend channels and |
//| a status panel. Every bot trading this chart's symbol writes      |
//|   <Common>\Files\fxbot_<SYMBOL>.txt         (main strategy)       |
//|   <Common>\Files\fxbot_<SYMBOL>_<sleeve>.txt (extra strategies)   |
//| after each candle; this indicator re-reads them every 2 seconds.  |
//| Display only - it never places or changes orders.                 |
//+------------------------------------------------------------------+
#property copyright "MoneyPrinter2"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

input int  RefreshSeconds = 2;
input int  FontSize       = 9;

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

void OnTimer() { Redraw(); }

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
